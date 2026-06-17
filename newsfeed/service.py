from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from defusedxml import ElementTree as DET

from backend.core.config import settings
from backend.newsfeed.schemas import BreakQuestResponse, NewsfeedItem, NewsfeedResponse

USER_AGENT = 'StudyBuddyNewsfeed/1.0 (+https://example.local)'
REQUEST_TIMEOUT_SECONDS = settings.newsfeed_request_timeout_seconds
CACHE_TTL = timedelta(minutes=settings.newsfeed_cache_ttl_minutes)
CACHE_MAX_ITEMS = settings.newsfeed_cache_max_items
ALLOWED_FEED_HOSTS = tuple(settings.newsfeed_allowed_hosts_list)
ALLOWED_FEED_SCHEMES = ('http', 'https')
MEDIA_NAMESPACE = {'media': 'http://search.yahoo.com/mrss/'}
MISTRAL_CHAT_COMPLETIONS_PATH = '/v1/chat/completions'


@dataclass(frozen=True)
class FeedSource:
    name: str
    topic_tag: str
    url: str
    cta_label: str
    learning_action: str


FEED_SOURCES: tuple[FeedSource, ...] = (
    FeedSource(
        name='BBC News',
        topic_tag='Reading',
        url='https://feeds.bbci.co.uk/news/world/rss.xml',
        cta_label='Doc tom tat',
        learning_action='open_summary',
    ),
    FeedSource(
        name='NPR Technology',
        topic_tag='Vocabulary',
        url='https://feeds.npr.org/1019/rss.xml',
        cta_label='Luu tu vung',
        learning_action='save_vocab',
    ),
    FeedSource(
        name='BBC News Business',
        topic_tag='Focus',
        url='https://feeds.bbci.co.uk/news/business/rss.xml',
        cta_label='Lam quiz nhanh',
        learning_action='start_quiz',
    ),
)

_CACHE: dict[str, object] = {
    'items': [],
    'expires_at': datetime.min.replace(tzinfo=UTC),
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return ' '.join(self.parts)


def _is_private_host(hostname: str) -> bool:
    lowered = hostname.strip().lower()
    if lowered in {'localhost', '127.0.0.1', '::1', '0.0.0.0'}:
        return True

    try:
        parsed_ip = ipaddress.ip_address(lowered)
        return (
            parsed_ip.is_private
            or parsed_ip.is_loopback
            or parsed_ip.is_link_local
            or parsed_ip.is_multicast
            or parsed_ip.is_reserved
            or parsed_ip.is_unspecified
        )
    except ValueError:
        pass

    try:
        resolved_ips = {
            info[4][0]
            for info in socket.getaddrinfo(lowered, None, proto=socket.IPPROTO_TCP)
        }
    except socket.gaierror:
        return True

    for value in resolved_ips:
        try:
            parsed_ip = ipaddress.ip_address(value)
        except ValueError:
            return True
        if (
            parsed_ip.is_private
            or parsed_ip.is_loopback
            or parsed_ip.is_link_local
            or parsed_ip.is_multicast
            or parsed_ip.is_reserved
            or parsed_ip.is_unspecified
        ):
            return True
    return False


def _validate_feed_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_FEED_SCHEMES:
        raise ValueError('Only http/https feed URLs are allowed.')

    hostname = (parsed.hostname or '').strip().lower()
    if not hostname:
        raise ValueError('Feed URL must include a valid hostname.')
    if not ALLOWED_FEED_HOSTS:
        raise ValueError('No allowed newsfeed hosts configured.')
    if hostname not in ALLOWED_FEED_HOSTS:
        raise ValueError('Feed host is not in the allowlist.')
    if _is_private_host(hostname):
        raise ValueError('Feed host resolves to a private or unsafe address.')
    return url


def _fetch_text(url: str) -> str:
    safe_url = _validate_feed_url(url)
    request = Request(safe_url, headers={'User-Agent': USER_AGENT})
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        final_url = response.geturl()
        _validate_feed_url(final_url)
        return response.read().decode('utf-8', errors='ignore')


def _strip_html(value: str | None) -> str:
    if not value:
        return ''
    parser = _HTMLTextExtractor()
    parser.feed(unescape(value))
    text = parser.text()
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _truncate_summary(summary: str, limit: int = 170) -> str:
    cleaned = summary.strip()
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[:limit].rsplit(' ', 1)[0].strip()
    return f'{clipped}...'


def _format_published_at(raw_value: str | None) -> str:
    if not raw_value:
        return 'Moi cap nhat'
    try:
        published = parsedate_to_datetime(raw_value)
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        delta = max(now - published.astimezone(UTC), timedelta())
        if delta < timedelta(minutes=60):
            minutes = max(1, int(delta.total_seconds() // 60))
            return f'{minutes} phut truoc'
        if delta < timedelta(hours=24):
            hours = max(1, int(delta.total_seconds() // 3600))
            return f'{hours} gio truoc'
        days = max(1, delta.days)
        return f'{days} ngay truoc'
    except (TypeError, ValueError, OverflowError):
        return 'Moi cap nhat'


def _find_image_url(item: DET.Element, link: str | None) -> str | None:
    media_thumbnail = item.find('media:thumbnail', MEDIA_NAMESPACE)
    if media_thumbnail is not None and media_thumbnail.attrib.get('url'):
        return media_thumbnail.attrib['url']

    media_content = item.find('media:content', MEDIA_NAMESPACE)
    if media_content is not None and media_content.attrib.get('url'):
        return media_content.attrib['url']

    enclosure = item.find('enclosure')
    if enclosure is not None and enclosure.attrib.get('type', '').startswith('image/') and enclosure.attrib.get('url'):
        return enclosure.attrib['url']

    if link:
        seed = quote(link, safe='')[:64]
        return f'https://picsum.photos/seed/{seed}/960/1280'
    return None


def _build_item_id(source_name: str, link: str | None, title: str) -> str:
    base = link or title or source_name
    slug = re.sub(r'[^a-z0-9]+', '-', base.lower()).strip('-')
    if not slug:
        slug = 'news-item'
    return f'{source_name.lower().replace(" ", "-")}-{slug[:72]}'


def _parse_feed(source: FeedSource, xml_text: str) -> list[NewsfeedItem]:
    root = DET.fromstring(xml_text)
    items = root.findall('.//item')
    parsed_items: list[NewsfeedItem] = []

    for entry in items[:6]:
        title = (entry.findtext('title') or '').strip()
        link = (entry.findtext('link') or '').strip() or None
        description = _strip_html(entry.findtext('description'))
        summary = _truncate_summary(description or title)
        image_url = _find_image_url(entry, link)
        image_alt = f'{title} - {source.name}' if title else source.name
        if not title or not summary:
            continue
        parsed_items.append(
            NewsfeedItem(
                id=_build_item_id(source.name, link, title),
                title=title,
                summary=summary,
                source=source.name,
                publishedAt=_format_published_at(entry.findtext('pubDate')),
                url=link,
                imageUrl=image_url,
                imageAlt=image_alt,
                topicTag=source.topic_tag,
                ctaLabel=source.cta_label,
                isNew=True,
                learningAction=source.learning_action,
            )
        )
    return parsed_items


def _merge_by_round_robin(groups: list[list[NewsfeedItem]]) -> list[NewsfeedItem]:
    merged: list[NewsfeedItem] = []
    max_length = max((len(group) for group in groups), default=0)
    for index in range(max_length):
        for group in groups:
            if index < len(group):
                merged.append(group[index])
    return merged


def _dedupe_items(items: list[NewsfeedItem], limit: int) -> list[NewsfeedItem]:
    deduped: list[NewsfeedItem] = []
    seen_ids: set[str] = set()

    for item in items:
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def _cache_valid() -> bool:
    expires_at = _CACHE.get('expires_at')
    return isinstance(expires_at, datetime) and expires_at > datetime.now(UTC)


def _extract_candidate_words(article: dict[str, str]) -> list[str]:
    corpus = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    matches = re.findall(r"[a-z][a-z\-]{3,}", corpus)
    stop_words = {
        'that', 'this', 'with', 'from', 'have', 'about', 'their', 'there', 'after',
        'before', 'would', 'could', 'should', 'while', 'where', 'which', 'world',
        'today', 'these', 'those', 'being', 'still', 'into', 'over', 'under', 'between',
    }
    unique: list[str] = []
    for word in matches:
        if word in stop_words or word in unique:
            continue
        unique.append(word)
    return unique[:6]


def _build_fallback_break_quest(article: dict[str, str]) -> dict[str, object]:
    title = article.get('title', 'Break Quest')
    summary = article.get('summary', '').strip() or title
    words = _extract_candidate_words(article)
    selected_words = (words + ['headline', 'source', 'detail'])[:3]
    vocabulary = [
        {
            'word': word,
            'meaningVi': 'Tu khoa lien quan den bai doc nay.',
            'exampleEn': f'The article mentions {word} in a short context.',
            'sourceSentence': summary,
        }
        for word in selected_words
    ]
    questions = [
        {
            'id': 'q1',
            'type': 'multiple_choice',
            'question': f'Which word appears in the article highlight for "{title}"?',
            'options': [selected_words[0], 'review', 'session'],
            'correctIndex': 0,
            'explanationVi': 'Chon tu khoa duoc lay truc tiep tu bai doc.',
        }
    ]
    return BreakQuestResponse(
        articleId=article.get('id', 'article-fallback'),
        title=title,
        imageUrl=article.get('imageUrl'),
        summaryVi=summary,
        vocabulary=vocabulary,
        questions=questions,
        companionLines=[
            'Mình đã chuẩn bị một Break Quest ngắn để bạn đọc nhanh và học 3 từ mới.',
            'Cố lên nhé! Mỗi ngày học thêm một chút xíu thôi là giỏi lắm rồi.',
            'Nghỉ ngơi đọc tin tức một chút rồi chúng ta quay lại học tiếp nhé.',
            'Đừng bỏ cuộc! Bạn đang làm rất tốt, hãy nạp năng lượng bằng Break Quest này.',
            'Cùng nhau học từ vựng để tăng thêm hiểu biết nào!',
        ],
        source='fallback',
    ).model_dump()


def _normalize_mistral_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text':
                text_value = item.get('text')
                if isinstance(text_value, str):
                    text_parts.append(text_value)
        return ''.join(text_parts)
    return ''


def _request_mistral_break_quest(article: dict[str, str]) -> dict[str, object]:
    if not settings.mistral_api_key:
        raise ValueError('Mistral API key is not configured.')

    endpoint = urljoin(settings.mistral_api_base.rstrip('/') + '/', MISTRAL_CHAT_COMPLETIONS_PATH.lstrip('/'))
    request_payload = {
        'model': settings.mistral_model,
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You are generating a Study Buddy break quest. '
                    'Return JSON only. Summarize the article in Vietnamese, extract exactly 3 vocabulary items, '
                    'create 1 to 3 multiple choice questions grounded only in the article, '
                    'and generate exactly 5 short, encouraging motivational lines in Vietnamese for the companionLines field.'
                ),
            },
            {
                'role': 'user',
                'content': json.dumps({
                    'article': article,
                    'required_shape': {
                        'summaryVi': 'string',
                        'vocabulary': [
                            {
                                'word': 'string',
                                'meaningVi': 'string',
                                'exampleEn': 'string',
                                'sourceSentence': 'string',
                            }
                        ],
                        'questions': [
                            {
                                'id': 'string',
                                'type': 'multiple_choice',
                                'question': 'string',
                                'options': ['string'],
                                'correctIndex': 0,
                                'explanationVi': 'string',
                            }
                        ],
                        'companionLines': ['string', 'string', 'string', 'string', 'string'],
                    },
                }),
            },
        ],
        'temperature': 0.2,
        'response_format': {'type': 'json_object'},
    }
    body = json.dumps(request_payload).encode('utf-8')
    request = Request(
        endpoint,
        data=body,
        headers={
            'Authorization': f'Bearer {settings.mistral_api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': USER_AGENT,
        },
        method='POST',
    )

    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode('utf-8', errors='ignore'))

    choices = payload.get('choices') or []
    if not choices:
        raise ValueError('Mistral returned no choices.')
    message = choices[0].get('message') or {}
    content = _normalize_mistral_content(message.get('content'))
    if not content:
        raise ValueError('Mistral returned empty content.')
    return json.loads(content)


def _validate_break_quest_payload(article: dict[str, str], payload: dict[str, object], source: str) -> dict[str, object]:
    summary = str(payload.get('summaryVi') or '').strip()
    raw_companion_lines = payload.get('companionLines')
    
    if not isinstance(raw_companion_lines, list):
        # Fallback in case LLM only gave a single string
        old_line = str(payload.get('companionLine') or '').strip()
        companion_lines = [old_line] if old_line else []
    else:
        companion_lines = [str(line).strip() for line in raw_companion_lines if str(line).strip()]

    raw_vocabulary = payload.get('vocabulary') or []
    raw_questions = payload.get('questions') or []

    if not summary or not companion_lines or not isinstance(raw_vocabulary, list) or not isinstance(raw_questions, list):
        raise ValueError('Break quest payload is missing required fields.')

    vocabulary: list[dict[str, object]] = []
    for entry in raw_vocabulary[:3]:
        if not isinstance(entry, dict):
            continue
        word = str(entry.get('word') or '').strip()
        meaning_vi = str(entry.get('meaningVi') or '').strip()
        example_en = str(entry.get('exampleEn') or '').strip()
        source_sentence = str(entry.get('sourceSentence') or '').strip() or article.get('summary', '')
        if not word or not meaning_vi or not example_en:
            continue
        vocabulary.append({
            'word': word,
            'meaningVi': meaning_vi,
            'exampleEn': example_en,
            'sourceSentence': source_sentence,
        })

    questions: list[dict[str, object]] = []
    for index, entry in enumerate(raw_questions[:3], start=1):
        if not isinstance(entry, dict):
            continue
        options = entry.get('options') or []
        if not isinstance(options, list):
            continue
        normalized_options = [str(option).strip() for option in options if str(option).strip()]
        correct_index = int(entry.get('correctIndex') or 0)
        if len(normalized_options) < 2 or correct_index < 0 or correct_index >= len(normalized_options):
            continue
        question = str(entry.get('question') or '').strip()
        explanation_vi = str(entry.get('explanationVi') or '').strip()
        if not question or not explanation_vi:
            continue
        questions.append({
            'id': str(entry.get('id') or f'q{index}'),
            'type': 'multiple_choice',
            'question': question,
            'options': normalized_options,
            'correctIndex': correct_index,
            'explanationVi': explanation_vi,
        })

    if len(vocabulary) != 3 or not questions:
        raise ValueError('Break quest payload failed validation.')

    return BreakQuestResponse(
        articleId=article.get('id', 'article-fallback'),
        title=article.get('title', 'Break Quest'),
        imageUrl=article.get('imageUrl'),
        summaryVi=summary,
        vocabulary=vocabulary,
        questions=questions,
        companionLines=companion_lines,
        source=source,
    ).model_dump()


def generate_break_quest(article: dict[str, str]) -> dict[str, object]:
    try:
        raw_payload = _request_mistral_break_quest(article)
        return _validate_break_quest_payload(article, raw_payload, source='llm')
    except Exception as e:
        print(f"Failed to generate break quest: {e}")
        return _build_fallback_break_quest(article)


def generate_motivational_lines() -> list[str]:
    if not settings.mistral_api_key:
        return [
            "Cố lên nhé! Mỗi ngày học thêm một chút xíu thôi là giỏi lắm rồi.",
            "Hãy cứ bước đi, dù chậm nhưng chắc chắn bạn sẽ tới đích.",
            "Mọi cố gắng hôm nay sẽ được đền đáp vào ngày mai.",
            "Bạn đang làm rất tốt, đừng bỏ cuộc nhé!",
            "Tập trung thêm một chút nữa nào!",
            "Hãy giữ tinh thần thoải mái để học tập hiệu quả.",
            "Chỉ cần bạn không dừng lại, việc tiến chậm cũng không sao.",
            "Học tập là hạt giống của kiến thức, kiến thức là hạt giống của hạnh phúc.",
            "Hôm nay bạn đã tiến bộ hơn ngày hôm qua rồi đó.",
            "Chúng ta cùng cố gắng nhé!"
        ]

    endpoint = urljoin(settings.mistral_api_base.rstrip('/') + '/', MISTRAL_CHAT_COMPLETIONS_PATH.lstrip('/'))
    request_payload = {
        'model': settings.mistral_model,
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You are generating motivational lines for a Study Buddy. '
                    'Return JSON only. Generate exactly 10 short, encouraging motivational lines in Vietnamese.'
                ),
            },
            {
                'role': 'user',
                'content': json.dumps({
                    'required_shape': {
                        'lines': ['string', 'string', 'string', 'string', 'string', 'string', 'string', 'string', 'string', 'string'],
                    },
                }),
            },
        ],
        'temperature': 0.7,
        'response_format': {'type': 'json_object'},
    }
    body = json.dumps(request_payload).encode('utf-8')
    request = Request(
        endpoint,
        data=body,
        headers={
            'Authorization': f'Bearer {settings.mistral_api_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': USER_AGENT,
        },
        method='POST',
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode('utf-8', errors='ignore'))
        choices = payload.get('choices') or []
        if not choices:
            raise ValueError('Mistral returned no choices.')
        message = choices[0].get('message') or {}
        content = _normalize_mistral_content(message.get('content'))
        if not content:
            raise ValueError('Mistral returned empty content.')
        data = json.loads(content)
        lines = data.get('lines')
        if not isinstance(lines, list) or len(lines) < 1:
            raise ValueError('Invalid lines returned')
        return [str(line).strip() for line in lines][:10]
    except Exception as e:
        print(f"Error generating motivational lines: {e}")
        return [
            "Cố lên nhé! Mỗi ngày học thêm một chút xíu thôi là giỏi lắm rồi.",
            "Hãy cứ bước đi, dù chậm nhưng chắc chắn bạn sẽ tới đích.",
            "Mọi cố gắng hôm nay sẽ được đền đáp vào ngày mai.",
            "Bạn đang làm rất tốt, đừng bỏ cuộc nhé!",
            "Tập trung thêm một chút nữa nào!",
            "Hãy giữ tinh thần thoải mái để học tập hiệu quả.",
            "Chỉ cần bạn không dừng lại, việc tiến chậm cũng không sao.",
            "Học tập là hạt giống của kiến thức, kiến thức là hạt giống của hạnh phúc.",
            "Hôm nay bạn đã tiến bộ hơn ngày hôm qua rồi đó.",
            "Chúng ta cùng cố gắng nhé!"
        ]


def get_newsfeed(limit: int = 8) -> dict[str, object]:
    safe_limit = max(1, min(limit, CACHE_MAX_ITEMS))
    if _cache_valid() and _CACHE.get('items'):
        cached_items = _CACHE['items']
        if isinstance(cached_items, list):
            return NewsfeedResponse(items=cached_items[:safe_limit]).model_dump()

    grouped_items: list[list[NewsfeedItem]] = []
    for source in FEED_SOURCES:
        try:
            xml_text = _fetch_text(source.url)
            parsed_items = _parse_feed(source, xml_text)
            if parsed_items:
                grouped_items.append(parsed_items)
        except (URLError, TimeoutError, DET.ParseError, ValueError):
            continue

    merged_items = _merge_by_round_robin(grouped_items)
    items = _dedupe_items(merged_items, CACHE_MAX_ITEMS)
    _CACHE['items'] = items
    _CACHE['expires_at'] = datetime.now(UTC) + CACHE_TTL
    return NewsfeedResponse(items=items[:safe_limit]).model_dump()
