"""Validated public data used by generation, storage, and the dashboard."""
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, UrlConstraints

Category = Literal['AI Models', 'AI Agents', 'AI Tools', 'AI Research', 'AI in Testing', 'AI & Cybersecurity', 'AI for Good', 'AI News', 'Other']
HttpsUrl = Annotated[HttpUrl, UrlConstraints(allowed_schemes=['https'])]


class SourceItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_type: Literal['rss'] = 'rss'
    source_url: HttpsUrl
    published_at: AwareDatetime
    description: str = ''
    article_text: str = Field(default='', max_length=12_000, exclude=True)
    category: Category = 'Other'


class Story(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_type: Literal['rss', 'editorial'] = 'rss'
    source_url: HttpsUrl
    published_at: AwareDatetime
    category: Category
    source_excerpt: str = Field(default='', max_length=800)
    summary_basis: Literal['article_text', 'rss_preview', 'editorial_review'] = 'rss_preview'
    date_precision: Literal['timestamp', 'day'] = 'timestamp'
    simple_explanation: str = Field(min_length=1)
    why_it_matters: str = Field(min_length=1)
    analogy: str | None = None


class StoryHistoryEntry(BaseModel):
    """Remember when a publisher link was last shown in an approved digest."""

    model_config = ConfigDict(extra='forbid')
    url: HttpsUrl
    last_shown_at: AwareDatetime
    times_shown: int = Field(ge=1)


class Digest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    generated_at: AwareDatetime
    timezone: Literal['America/New_York'] = 'America/New_York'
    status: Literal['live', 'demo']
    stories: list[Story] = Field(min_length=1, max_length=5)
    featured_story: Story | None = None
    story_history: list[StoryHistoryEntry] = Field(default_factory=list)
