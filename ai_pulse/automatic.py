"""Publish a complete local digest only after mechanical source and copy checks."""

from datetime import datetime
from time import monotonic

from ai_pulse.article_text import read_article
from ai_pulse.featured_story import current_feature
from ai_pulse.models import Digest, SourceItem, Story
from ai_pulse.process import is_main_news_item, remember_approved, url_key
from ai_pulse.quality import check_automatic_story, check_digest, check_story
from ai_pulse.story_pool import validate_pool_item
from ai_pulse.summary_cache import SummaryCache


def build_automatic_digest(candidates: list[SourceItem], previous: Digest | None,
                           now: datetime, summarizer,
                           reader=read_article, deadline: float | None = None,
                           on_progress=None,
                           summary_cache: SummaryCache | None = None) -> tuple[Digest, list[str]]:
    """Try approved candidates until five safe cards or the time budget ends."""
    old_stories = ({url_key(story.source_url): story for story in previous.stories}
                   if previous and previous.status == 'live' else {})
    notes: list[str] = []
    stories: list[Story] = []
    seen: set[str] = set()
    for item in candidates[:12]:
        if not is_main_news_item(item):
            notes.append(f'Reserved for the separate AI for Good feature: {item.title}')
            continue
        if deadline is not None and monotonic() >= deadline:
            raise TimeoutError('Automatic refresh time budget expired')
        validate_pool_item(item, now)
        key = url_key(item.source_url)
        if key in seen:
            continue
        seen.add(key)
        if key in old_stories:
            stories.append(old_stories[key].model_copy(update={'category': item.category}))
            if on_progress:
                on_progress(f'Reused checked story {len(stories)}/5 from '
                            f'{item.source_name}')
        else:
            if on_progress:
                on_progress(f'Checking article and summary from '
                            f'{item.source_name} ({len(stories) + 1}/5)')
            try:
                article = reader(item)
                if len(article) < 300:
                    raise ValueError('Article body had fewer than 300 characters')
            except (OSError, UnicodeError, ValueError, LookupError) as exc:
                notes.append(f'Skipped {item.source_name}: {item.title} '
                             f'(article {type(exc).__name__})')
                if on_progress:
                    on_progress(f'Skipped unreadable article from '
                                f'{item.source_name}')
                continue
            enriched = item.model_copy(update={'article_text': article})
            try:
                story = summary_cache.get(enriched) if summary_cache else None
                cached = story is not None
                if story is not None:
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
            except ValueError as exc:
                if not (str(exc).startswith('Draft quality check failed:')
                        or str(exc).startswith('Generated story ')):
                    raise
                notes.append(f'Skipped {item.source_name}: {item.title} '
                             f'({exc})')
                if on_progress:
                    on_progress(f'Skipped summary that failed checks from '
                                f'{item.source_name}')
                continue
            stories.append(story)
            if on_progress:
                on_progress(f'Checked story {len(stories)}/5 from '
                            f'{item.source_name}')
        if len(stories) == 5:
            break
    if len(stories) != 5:
        raise ValueError('Fewer than five distinct approved stories passed '
                         'article and summary checks; ' + '; '.join(notes))
    digest = Digest(generated_at=now, status='live', stories=stories,
                    featured_story=current_feature(now))
    issues = check_digest(digest)
    if issues:
        raise ValueError('Automatic quality check failed: ' + '; '.join(issues))
    return remember_approved(digest, previous, now), notes
