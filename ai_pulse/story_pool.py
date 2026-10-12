"""Keep approved RSS metadata locally for several refreshes on one day."""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict

from ai_pulse.fetch_news import (FEEDS, approved_article_host, canonical_url,
                                 fetch_news)
from ai_pulse.models import SourceItem
from ai_pulse.process import (classify_category, filter_recent, has_sufficient_ai_context,
                              is_ai_related_text, is_main_news_item, url_key)
from ai_pulse.storage import ROOT


DEFAULT_POOL = ROOT / 'data' / 'story_pool.json'
EASTERN = ZoneInfo('America/New_York')


class StoryPool(BaseModel):
    """Store a feed-check time and validated article metadata, never article HTML."""

    model_config = ConfigDict(extra='forbid')
    checked_at: AwareDatetime
    items: list[SourceItem]
    category_relaxed: bool = False
    last_check_succeeded: bool = True


@dataclass(frozen=True)
class PoolResult:
    """Report cached candidates plus whether a depleted-pool fetch succeeded."""

    items: list[SourceItem]
    errors: list[str]
    used_cache: bool
    relaxed_category: bool
    all_feeds_failed: bool


def validate_pool_item(item: SourceItem, now: datetime) -> None:
    """Reject cached links that no longer match the approved publisher list."""
    source = next((feed for feed in FEEDS if feed.name == item.source_name), None)
    url = str(item.source_url)
    if (source is None or canonical_url(url) != url
            or not approved_article_host(url, source.article_hosts)
            or not is_ai_related_text(f'{item.title} {item.description}')
            or item.article_text
            or item.published_at > now):
        raise ValueError('Cached article failed approved-source validation')


def load_pool(path: Path, now: datetime) -> StoryPool | None:
    """Read cached feed items and recheck every source before reusing them."""
    if not path.exists():
        return None
    pool = StoryPool.model_validate_json(path.read_text(encoding='utf-8'))
    for item in pool.items:
        validate_pool_item(item, now)
    eligible = [item.model_copy(update={'category': classify_category(item.title, item.description)})
                for item in pool.items
                if has_sufficient_ai_context(item.title, item.description)]
    return pool.model_copy(update={'items': eligible})


def save_pool(pool: StoryPool, path: Path) -> None:
    """Atomically save bounded RSS metadata without article bodies or scripts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, suffix='.tmp',
                                         delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(pool.model_dump_json(indent=2) + '\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def cached_candidates(now: datetime, path: Path = DEFAULT_POOL,
                      refresh: bool = False, shown_urls: set[str] | None = None,
                      fetcher=fetch_news) -> PoolResult:
    """Use unseen buffered links first; fetch on every exhausted refresh."""
    prior = load_pool(path, now)
    shown = shown_urls or set()
    same_day = (prior is not None and prior.checked_at.astimezone(EASTERN).date()
                == now.astimezone(EASTERN).date())
    buffered_unseen = ([item for item in filter_recent(prior.items, now, 120)
                        if is_main_news_item(item)
                        and url_key(item.source_url) not in shown] if prior else [])
    if (same_day and not refresh and buffered_unseen
            and prior.last_check_succeeded):
        return PoolResult(prior.items, [], True, prior.category_relaxed, False)
    fetched, errors = fetcher()
    all_failed = not fetched and len(errors) >= len(FEEDS)
    for item in fetched:
        validate_pool_item(item, now)
    combined = [*fetched, *(prior.items if prior else [])]
    kept = filter_recent(combined, now, 24 * 365 * 20)[:1000]
    relaxed = bool(same_day and (prior.category_relaxed or
                               (prior.last_check_succeeded and not buffered_unseen)))
    save_pool(StoryPool(checked_at=now, items=kept,
                        category_relaxed=relaxed,
                        last_check_succeeded=not all_failed), path)
    return PoolResult(kept, errors, False, relaxed, all_failed)
