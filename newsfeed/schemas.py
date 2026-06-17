from pydantic import BaseModel, Field


class NewsfeedItem(BaseModel):
    id: str
    title: str
    summary: str
    source: str
    publishedAt: str
    url: str | None = None
    imageUrl: str | None = None
    imageAlt: str | None = None
    topicTag: str | None = None
    ctaLabel: str | None = None
    isNew: bool = False
    learningAction: str | None = None


class NewsfeedResponse(BaseModel):
    items: list[NewsfeedItem] = Field(default_factory=list)
    source: str = 'rss'


class BreakQuestArticleInput(BaseModel):
    id: str
    title: str
    summary: str
    source: str
    publishedAt: str | None = None
    url: str | None = None
    imageUrl: str | None = None


class BreakQuestRequest(BaseModel):
    article: BreakQuestArticleInput


class BreakQuestVocabularyItem(BaseModel):
    word: str
    meaningVi: str
    exampleEn: str
    sourceSentence: str | None = None


class BreakQuestQuestion(BaseModel):
    id: str
    type: str = 'multiple_choice'
    question: str
    options: list[str] = Field(default_factory=list)
    correctIndex: int
    explanationVi: str


class BreakQuestResponse(BaseModel):
    articleId: str
    title: str
    imageUrl: str | None = None
    summaryVi: str
    vocabulary: list[BreakQuestVocabularyItem] = Field(default_factory=list)
    questions: list[BreakQuestQuestion] = Field(default_factory=list)
    companionLines: list[str]
    source: str = 'fallback'
