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
