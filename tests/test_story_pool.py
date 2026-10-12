"""Approved feed metadata is cached without retaining article bodies."""

from datetime import datetime, timedelta, timezone

import pytest

from ai_pulse.models import SourceItem
from ai_pulse.story_pool import cached_candidates, load_pool


NOW = datetime(2026, 10, 11, 21, tzinfo=timezone.utc)


def item(slug: str, published_at: datetime) -> SourceItem:
    """Create an approved-publisher AI item for the offline pool tests."""
    return SourceItem(id=slug, title=f'OpenAI announces AI {slug}',
                      source_name='OpenAI News',
                      source_url=f'https://openai.com/index/{slug}',
                      published_at=published_at,
                      description=f'An AI update about {slug}.')


def test_pool_reuses_same_day_metadata_and_merges_next_day(tmp_path):
    """The buffer is reused while unseen; exhausted refreshes fetch again."""
    path = tmp_path / 'pool.json'
    fetched = []

    def fake_fetch():
        """Return a new article on each simulated calendar-day fetch."""
        fetched.append(True)
        return [item(f'update-{len(fetched)}', NOW)], []

    first = cached_candidates(NOW, path, fetcher=fake_fetch)
    second = cached_candidates(NOW + timedelta(minutes=10), path,
                               fetcher=fake_fetch)
    exhausted = cached_candidates(NOW + timedelta(minutes=20), path,
                                  shown_urls={'https://openai.com/index/update-1'},
                                  fetcher=fake_fetch)
    repeated = cached_candidates(NOW + timedelta(minutes=30), path,
                                 shown_urls={'https://openai.com/index/update-1',
                                             'https://openai.com/index/update-2'},
                                 fetcher=fake_fetch)
    next_day = cached_candidates(NOW + timedelta(days=1), path,
                                 fetcher=fake_fetch)
    assert len(fetched) == 4
    assert [entry.id for entry in first.items] == ['update-1']
    assert [entry.id for entry in second.items] == ['update-1']
    assert {entry.id for entry in exhausted.items} == {'update-1', 'update-2'}
    assert not repeated.used_cache and repeated.relaxed_category
    assert {entry.id for entry in next_day.items} == {
        'update-1', 'update-2', 'update-3', 'update-4'}
    assert (first.used_cache, second.used_cache, exhausted.used_cache,
            repeated.used_cache, next_day.used_cache) == (
                False, True, False, False, False)
    assert 'article_text' not in path.read_text(encoding='utf-8')


def test_all_feed_failures_retry_on_the_next_exhausted_refresh(tmp_path):
    """An unavailable feed set can be checked again on the next refresh."""
    path = tmp_path / 'pool.json'
    calls = []

    def failed_fetch():
        """Simulate all approved publisher feeds failing their checks."""
        calls.append(True)
        from ai_pulse.fetch_news import FEEDS
        return [], [f'{feed.name}: OSError' for feed in FEEDS]

    first = cached_candidates(NOW, path, fetcher=failed_fetch)
    second = cached_candidates(NOW + timedelta(minutes=5), path,
                               fetcher=failed_fetch)
    assert len(calls) == 2
    assert first.all_feeds_failed and second.all_feeds_failed


def test_first_success_after_failure_keeps_daily_category_preference(tmp_path):
    """A blocked fetch does not count as using up an unseen story buffer."""
    path = tmp_path / 'pool.json'

    def failed_fetch():
        """Represent a network failure across all approved feed endpoints."""
        from ai_pulse.fetch_news import FEEDS
        return [], [f'{feed.name}: PermissionError' for feed in FEEDS]

    def working_fetch():
        """Supply the first usable candidate after the blocked attempt."""
        return [item('working', NOW)], []

    assert cached_candidates(NOW, path, fetcher=failed_fetch).all_feeds_failed
    recovered = cached_candidates(NOW + timedelta(minutes=1), path,
                                  fetcher=working_fetch)
    assert not recovered.relaxed_category


def test_tampered_pool_link_is_rejected(tmp_path):
    """A cached publisher name cannot authorize an unrelated article domain."""
    path = tmp_path / 'pool.json'
    bad = SourceItem.model_validate({
        **item('bad', NOW).model_dump(),
        'source_url': 'https://unapproved.example/bad',
    })
    path.write_text('{"checked_at":"2026-10-11T21:00:00Z","items":['
                    + bad.model_dump_json() + ']}', encoding='utf-8')
    with pytest.raises(ValueError):
        load_pool(path, NOW)


def test_cached_features_are_reclassified_and_do_not_block_a_refetch(tmp_path):
    """A buffer with only an unseen human feature counts as exhausted for news."""
    from ai_pulse.story_pool import StoryPool, save_pool
    path = tmp_path / 'pool.json'
    human = item('human', NOW).model_copy(update={
        'title': 'AI helps students learn independently', 'category': 'Other'})
    save_pool(StoryPool(checked_at=NOW, items=[human]), path)
    assert load_pool(path, NOW).items[0].category == 'AI for Good'
    calls = []

    def fresh_news():
        """Record that a news fetch happens despite the unused feature in cache."""
        calls.append(True)
        return [item('fresh-news', NOW)], []

    result = cached_candidates(NOW, path, fetcher=fresh_news)
    assert calls == [True]
    assert not result.used_cache
