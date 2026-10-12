"""Explicit local generation actions; the dashboard only reads saved stories."""
import argparse
import sys
from datetime import datetime, timezone
from time import monotonic
from ai_pulse.config import load_settings
from ai_pulse.article_text import enrich_articles, read_article
from ai_pulse.automatic import build_automatic_digest
from ai_pulse.fetch_news import FEEDS, fetch_news
from ai_pulse.featured_story import current_feature
from ai_pulse.ollama import local_model_identity, summarize_local_items
from ai_pulse.models import SourceItem
from ai_pulse.process import (filter_recent, history_index, remember_approved,
                              remember_feature, select_for_rerun, url_key)
from ai_pulse.quality import check_digest
from ai_pulse.runs import pending_draft_reason, same_issue, same_publication
from ai_pulse.storage import (DEMO_DIGEST, DEFAULT_DIGEST, DRAFT_DIGEST,
                              load_digest, save_digest)
from ai_pulse.story_pool import cached_candidates
from ai_pulse.summarize import summarize_items
from ai_pulse.summary_cache import DEFAULT_SUMMARY_CACHE, SummaryCache


def main() -> int:
    """Run an explicit local command for demo, RSS preview, or live generation."""
    parser = argparse.ArgumentParser(description='AI Signal')
    parser.add_argument('command', choices=['demo', 'validate', 'fetch-news', 'generate',
                                           'generate-local', 'refresh-local',
                                           'probe-articles', 'add-feature',
                                           'review-draft',
                                           'approve-draft'])
    parser.add_argument('--draft', action='store_true',
                        help='validate the generated draft instead of the visible digest')
    parser.add_argument('--reviewed', action='store_true',
                        help='confirm each draft claim was checked against its publisher')
    parser.add_argument('--force', action='store_true',
                        help='replace an unreviewed draft')
    parser.add_argument('--refresh-feeds', action='store_true',
                        help='check approved feeds again even if today has a local story pool')
    parser.add_argument('--timeout-seconds', type=int, default=300,
                        help='refresh-local generation budget, 60–1800 seconds (default: 300)')
    parser.add_argument('--model-timeout-seconds', type=int, default=120,
                        help='refresh-local model request limit, 30–600 seconds (default: 120)')
    args = parser.parse_args()
    if not 60 <= args.timeout_seconds <= 1800:
        parser.error('--timeout-seconds must be between 60 and 1800')
    if not 30 <= args.model_timeout_seconds <= 600:
        parser.error('--model-timeout-seconds must be between 30 and 600')
    if args.command == 'demo':
        save_digest(load_digest(DEMO_DIGEST))
        print(f'Saved labeled DEMO sample data to {DEFAULT_DIGEST}')
    elif args.command == 'validate':
        digest = load_digest(DRAFT_DIGEST if args.draft else DEFAULT_DIGEST)
        issues = check_digest(digest)
        if issues:
            print('Quality check failed: ' + '; '.join(issues))
            return 1
        feature_count = int(digest.featured_story is not None)
        print(f'Valid {digest.status} digest: {len(digest.stories)} current stories'
              f' + {feature_count} dated feature')
    elif args.command == 'approve-draft':
        if not args.reviewed:
            print('Review every draft claim against its publisher article, then use '
                  'approve-draft --reviewed. The visible digest was not changed.')
            return 1
        digest = load_digest(DRAFT_DIGEST)
        issues = check_digest(digest)
        if issues:
            print('Quality check failed: ' + '; '.join(issues))
            return 1
        if digest.status == 'live' and len(digest.stories) != 5:
            print('A live issue needs five distinct news stories; '
                  'the current dashboard digest was not changed.')
            return 1
        previous = load_digest(DEFAULT_DIGEST) if DEFAULT_DIGEST.exists() else None
        if previous and same_publication(previous, digest):
            print('This draft is already the visible digest; nothing was changed.')
            return 0
        if previous and same_issue(previous, digest):
            approved = digest.model_copy(update={'story_history': previous.story_history})
        else:
            approved = remember_approved(digest, previous, datetime.now(timezone.utc))
        save_digest(approved, DEFAULT_DIGEST)
        print(f'Approved reviewed draft to {DEFAULT_DIGEST}')
    elif args.command == 'review-draft':
        digest = load_digest(DRAFT_DIGEST)
        issues = check_digest(digest)
        for position, story in enumerate(digest.stories, start=1):
            print(f'\n{position}. {story.title} ({story.published_at:%Y-%m-%d})')
            print(f'Publisher: {story.source_name} | Basis: {story.summary_basis}')
            print(f'Original: {story.source_url}')
            print(f'Excerpt: {story.source_excerpt}')
            print(f'Explanation: {story.simple_explanation}')
            print(f'Why it matters: {story.why_it_matters}')
        print(f'\nAutomatic quality issues: {len(issues)}')
        for issue in issues:
            print(issue)
        print('Check each fact and the takeaway against the original article '
              'before approving the draft.')
    elif args.command == 'probe-articles':
        for story in load_digest().stories:
            item = SourceItem(id=story.id, title=story.title,
                              source_name=story.source_name, source_url=story.source_url,
                              published_at=story.published_at,
                              description=story.source_excerpt, category=story.category)
            try:
                article = read_article(item)
                print(f'{story.source_name}: {len(article)} article characters available')
            except (OSError, UnicodeError, ValueError, LookupError) as exc:
                print(f'{story.source_name}: article unavailable ({type(exc).__name__})')
    elif args.command == 'add-feature':
        digest = load_digest()
        if digest.status != 'live':
            print('The human-interest feature can only be added to a live briefing.')
            return 1
        feature = current_feature(datetime.now(timezone.utc))
        if feature is None:
            print('The reviewed feature is older than 15 days; no digest was changed.')
            return 1
        if digest.featured_story and url_key(digest.featured_story.source_url) == url_key(feature.source_url):
            print('The dated feature is already displayed; nothing was changed.')
            return 0
        save_digest(remember_feature(digest, feature, datetime.now(timezone.utc)))
        print(f'Added the dated human-interest feature to {DEFAULT_DIGEST}')
    else:
        if not FEEDS:
            print('No approved RSS feeds configured yet. Choose sources before fetching.')
            return 1
        if args.command in ('generate', 'generate-local') and not args.force:
            reason = pending_draft_reason(DRAFT_DIGEST, DEFAULT_DIGEST)
            if reason:
                print(f'{reason}; no feeds or model were called. Review it or '
                      'use --force if you intentionally want to replace it.')
                return 0
        settings = load_settings()
        if args.command == 'generate' and (
            not settings.gemini_api_key or settings.gemini_api_key.get_secret_value() == 'your_key_here'
            or not settings.gemini_model
            or settings.gemini_model == 'select_a_supported_free_tier_model'
        ):
            print('Set GEMINI_API_KEY and GEMINI_MODEL in .env before generating.')
            return 1
        now = datetime.now(timezone.utc)
        previous = load_digest(DEFAULT_DIGEST) if DEFAULT_DIGEST.exists() else None
        history = history_index(previous)
        try:
            pool = cached_candidates(now, refresh=args.refresh_feeds,
                                     shown_urls=set(history), fetcher=fetch_news)
        except (OSError, ValueError) as exc:
            print(f'Candidate pool failed validation ({type(exc).__name__}); '
                  'the visible digest was not changed.')
            return 1
        fetched, errors = pool.items, pool.errors
        if pool.all_feeds_failed and args.command != 'fetch-news':
            print('All approved feeds failed their last check; '
                  'the last visible digest and its age were kept.')
            return 1
        selected = select_for_rerun(fetched, now, settings.lookback_hours,
                                    settings.story_count, previous,
                                    relaxed_category=pool.relaxed_category)
        new_count = sum(url_key(item.source_url) not in history for item in selected)
        pool_hours = 120 if history else max(72, settings.lookback_hours)
        pool_count = len(filter_recent(fetched, now, pool_hours))
        origin = ('Last feed check failed; cached'
                  if pool.all_feeds_failed else
                  'Cached' if pool.used_cache else
                  'Checked approved feeds and cached')
        print(f'{origin} {len(fetched)} dated candidates; {pool_count} unique '
              f'candidates within {pool_hours} hours; selected {len(selected)} '
              f'({new_count} not previously shown, '
              f'{len(selected) - new_count} least-recently-shown repeats).')
        for error in errors:
            print(f'Feed unavailable: {error}')
        for position, item in enumerate(selected, start=1):
            if args.command == 'fetch-news':
                print(f'{position}. [{item.category}] {item.title} — {item.source_name} '
                      f'({item.published_at:%Y-%m-%d %H:%M UTC})')
                print(f'   {item.source_url}')
                print(f'   Feed excerpt: {item.description}')
        if not selected:
            print('No verified candidate stories are available. '
                  'The existing digest was not changed.')
            return 1
        if args.command == 'refresh-local':
            if len(selected) != 5:
                print('Fewer than five distinct approved stories are available; '
                      'the last complete digest remains visible.')
                return 1

            deadline = monotonic() + args.timeout_seconds
            print(f'Generation budget: {args.timeout_seconds}s; '
                  f'per-model-request limit: {args.model_timeout_seconds}s.', flush=True)

            def cache_model_identity() -> str:
                """Identify local model weights once, when a new story needs the cache."""
                return local_model_identity(settings.ollama_model)

            summary_cache = SummaryCache(DEFAULT_SUMMARY_CACHE, now, cache_model_identity)

            def local_summary(items: list[SourceItem]):
                """Send only genuinely new selected articles to installed Ollama."""
                return summarize_local_items(items, settings.ollama_model,
                                             deadline=deadline,
                                             request_timeout=args.model_timeout_seconds)

            def show_refresh_progress(message: str) -> None:
                """Print each checked story promptly during a slow local run."""
                print(message, flush=True)

            try:
                candidate_order = select_for_rerun(
                    fetched, now, settings.lookback_hours,
                    min(12, len(fetched) + 5), previous,
                    relaxed_category=pool.relaxed_category)
                digest, article_notes = build_automatic_digest(
                    candidate_order, previous, now, local_summary,
                    reader=read_article, deadline=deadline,
                    on_progress=show_refresh_progress, summary_cache=summary_cache)
                for note in article_notes:
                    print(note)
                if digest == previous:
                    print('No new checked stories; the saved digest was not rewritten.')
                    return 0
                save_digest(digest, DEFAULT_DIGEST)
            except Exception as exc:
                print(f'Automatic refresh failed ({type(exc).__name__}: {exc}); '
                      'the last visible digest was kept.')
                return 1
            finally:
                print(f'Summary cache: {summary_cache.hits} reused, '
                      f'{summary_cache.misses} need generation, '
                      f'{summary_cache.saved} saved.', flush=True)
                for note in summary_cache.notes:
                    print(note, flush=True)
            print(f'Published {len(digest.stories)} verified-source stories to '
                  f'{DEFAULT_DIGEST}; {int(digest.featured_story is not None)} '
                  'dated human-interest feature.')
        elif args.command == 'generate':
            try:
                selected, article_notes = enrich_articles(selected)
                for note in article_notes:
                    print(note)
                digest = summarize_items(selected,
                                         settings.gemini_api_key.get_secret_value(),
                                         settings.gemini_model)
                feature = current_feature(now)
                digest = digest.model_copy(update={'featured_story': feature})
                save_digest(digest, DRAFT_DIGEST)
            except Exception as exc:
                print(f'Generation failed ({type(exc).__name__}); existing digest was kept.')
                return 1
            print(f'Saved {len(digest.stories)} draft stories and '
                  f'{int(digest.featured_story is not None)} dated feature to {DRAFT_DIGEST}')
        elif args.command == 'generate-local':
            try:
                selected, article_notes = enrich_articles(selected)
                for note in article_notes:
                    print(note)
                digest = summarize_local_items(selected, settings.ollama_model)
                feature = current_feature(now)
                digest = digest.model_copy(update={'featured_story': feature})
                save_digest(digest, DRAFT_DIGEST)
            except Exception as exc:
                print(f'Local generation failed ({type(exc).__name__}); '
                      'existing digest was kept.')
                return 1
            print(f'Saved {len(digest.stories)} locally summarized draft stories and '
                  f'{int(digest.featured_story is not None)} dated feature to {DRAFT_DIGEST}')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
