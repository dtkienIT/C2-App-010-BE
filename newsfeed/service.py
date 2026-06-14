from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import ipaddress
import re
import socket
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from defusedxml import ElementTree as DET

from backend.core.config import settings
from backend.newsfeed.schemas import NewsfeedItem, NewsfeedResponse

USER_AGENT = 'StudyBuddyNewsfeed/1.0 (+https://example.local)'
REQUEST_TIMEOUT_SECONDS = settings.newsfeed_request_timeout_seconds
CACHE_TTL = timedelta(minutes=settings.newsfeed_cache_ttl_minutes)
CACHE_MAX_ITEMS = settings.newsfeed_cache_max_items
ALLOWED_FEED_HOSTS = tuple(settings.newsfeed_allowed_hosts_list)
ALLOWED_FEED_SCHEMES = ('http', 'https')
MEDIA_NAMESPACE = {'media': 'http://search.yahoo.com/mrss/'}

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
