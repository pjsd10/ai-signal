"""Publish passing new cards with distinct, previously verified fallback stories."""

from datetime import datetime, timedelta
from time import monotonic

from ai_pulse.article_text import read_article
from ai_pulse.featured_story import current_feature
from ai_pulse.models import Digest, SourceItem, Story
from ai_pulse.process import (classify_category, history_index, is_main_news_item,
                              normalized_title, remember_approved, url_key)
from ai_pulse.quality import check_automatic_story, check_digest, check_story
from ai_pulse.story_pool import validate_pool_item
from ai_pulse.summary_cache import SummaryCache


def repeats_story(story: Story | SourceItem, selected: list[Story]) -> bool:
    """Detect repeated canonical links, IDs, or normalized headlines in an issue."""
    return any(url_key(story.source_url) == url_key(other.source_url)
               or story.id == other.id
               or normalized_title(story.title) == normalized_title(other.title)
               for other in selected)


def verified_previous_stories(previous: Digest | None, now: datetime) -> list[Story]:
    """Recheck saved news cards locally before considering them as fallback content."""
    if previous is None or previous.status != 'live':
        return []
    verified: list[Story] = []
    for saved in previous.stories:
        try:
            story = Story.model_validate(saved.model_dump())
            if (story.source_type != 'rss'
                    or story.summary_basis not in ('article_text', 'editorial_review')
                    or not is_main_news_item(story) or check_story(story)):
                continue
            item = SourceItem(id=story.id, title=story.title,
                              source_name=story.source_name, source_url=story.source_url,
                              published_at=story.published_at,
                              description=story.source_excerpt,
                              category=classify_category(story.title, story.source_excerpt))
            validate_pool_item(item, now)
            if not is_main_news_item(item) or repeats_story(story, verified):
                continue
        except ValueError:
            continue
        verified.append(story.model_copy(update={'category': item.category}))
    history = history_index(previous)
    verified.sort(key=lambda story: (
        now - story.published_at > timedelta(days=5),
        history[url_key(story.source_url)].last_shown_at,
        history[url_key(story.source_url)].times_shown,
        -story.published_at.timestamp()))
    return verified


def build_automatic_digest(candidates: list[SourceItem], previous: Digest | None,
                           now: datetime, summarizer,
                           reader=read_article, deadline: float | None = None,
                           on_progress=None,
                           summary_cache: SummaryCache | None = None) -> tuple[Digest, list[str]]:
    """Keep passing new cards, then fill five slots from verified saved news."""
    older = verified_previous_stories(previous, now)
    old_keys = {url_key(story.source_url) for story in older}
    notes: list[str] = []
    stories: list[Story] = []
    attempted: set[str] = set()
    last_error: Exception | None = None
    for item in candidates[:12]:
        if not is_main_news_item(item):
            notes.append(f'Reserved for the separate AI for Good feature: {item.title}')
            continue
        if deadline is not None and monotonic() >= deadline:
            last_error = TimeoutError('Automatic refresh time budget expired')
            notes.append(str(last_error))
            break
        try:
            validate_pool_item(item, now)
        except ValueError as exc:
            last_error = exc
            notes.append(f'Skipped candidate that failed approved-source validation: {item.title}')
            continue
        key = url_key(item.source_url)
        if key in attempted or key in old_keys or repeats_story(item, stories):
            continue
        if now - item.published_at > timedelta(days=5):
            notes.append(f'Skipped candidate outside the five-day window: {item.title}')
            continue
        attempted.add(key)
        if on_progress:
            on_progress(f'Checking article and summary from {item.source_name} ({len(stories) + 1}/5)')
        try:
            article = reader(item)
            if len(article) < 300:
                raise ValueError('Article body had fewer than 300 characters')
        except (OSError, UnicodeError, ValueError, LookupError) as exc:
            last_error = exc
            notes.append(f'Skipped {item.source_name}: {item.title} (article {type(exc).__name__})')
            if on_progress:
                on_progress(f'Skipped unreadable article from {item.source_name}')
            continue
        enriched = item.model_copy(update={'article_text': article})
        try:
            story = summary_cache.get(enriched) if summary_cache else None
            cached = story is not None
            if cached:
                if on_progress:
                    on_progress(f'Used saved summary from {item.source_name}')
            else:
                result = summarizer([enriched])
                if len(result.stories) != 1:
                    raise ValueError('Summarizer returned an incomplete story set')
                story = result.stories[0]
            check_automatic_story(story, enriched)
            issues = check_story(story)
            if issues:
                raise ValueError('Draft quality check failed: ' + '; '.join(issues))
            if summary_cache and not cached:
                summary_cache.put(enriched, story)
        except (OSError, LookupError) as exc:
            last_error = exc
            notes.append(f'Generation stopped ({type(exc).__name__}); retaining passing summaries.')
            break
        except ValueError as exc:
            last_error = exc
            notes.append(f'Skipped {item.source_name}: {item.title} ({exc})')
            if on_progress:
                on_progress(f'Skipped summary that failed checks from {item.source_name}')
            continue
        stories.append(story)
        if on_progress:
            on_progress(f'Checked story {len(stories)}/5 from {item.source_name}')
        if len(stories) == 5:
            break

    if not stories and previous is not None and len(older) == 5:
        notes.append('No new checked stories; kept the previous issue, timestamp, and display history.')
        return previous, notes

    new_count = len(stories)
    for story in older:
        if len(stories) == 5:
            break
        if not repeats_story(story, stories):
            stories.append(story)
    if len(stories) != 5:
        if isinstance(last_error, (OSError, LookupError)):
            raise last_error
        raise ValueError('Fewer than five distinct approved stories passed '
                         'article and summary checks; ' + '; '.join(notes))
    if new_count < 5:
        notes.append(f'Published {new_count} newly checked stories with '
                     f'{5 - new_count} previously verified stories.')
    digest = Digest(generated_at=now, status='live', stories=stories,
                    featured_story=current_feature(now))
    issues = check_digest(digest)
    if issues:
        raise ValueError('Automatic quality check failed: ' + '; '.join(issues))
    return remember_approved(digest, previous, now), notes
