"""A rerun should use unseen five-day stories before rotating older links."""

from datetime import datetime, timedelta, timezone

from ai_pulse.models import Digest, SourceItem, Story, StoryHistoryEntry
from ai_pulse.process import remember_approved, remember_feature, select_for_rerun
from ai_pulse.storage import load_digest, save_digest


NOW = datetime(2026, 10, 11, 21, tzinfo=timezone.utc)


def source(slug: str, hours_old: int) -> SourceItem:
    """Create a dated fictional publisher item for selection tests."""
    return SourceItem(id=slug, title=f'AI news about {slug}',
                      source_name='Example Publisher',
                      source_url=f'https://example.com/{slug}',
                      published_at=NOW - timedelta(hours=hours_old),
                      category='AI Research')


def story(item: SourceItem) -> Story:
    """Turn a fictional feed item into a previously reviewed card."""
    return Story(id=item.id, title=item.title, source_name=item.source_name,
                 source_url=item.source_url, published_at=item.published_at,
                 category=item.category, simple_explanation='A research update.',
                 why_it_matters='Readers can inspect the linked research.')


def previous_issue(items: list[SourceItem]) -> Digest:
    """Make an issue with different last-shown times for repeat ordering."""
    return Digest(generated_at=NOW - timedelta(hours=2), status='live',
                  stories=[story(items[0]), story(items[1])],
                  story_history=[
                      StoryHistoryEntry(url=items[0].source_url,
                                        last_shown_at=NOW - timedelta(days=4),
                                        times_shown=1),
                      StoryHistoryEntry(url=items[1].source_url,
                                        last_shown_at=NOW - timedelta(days=1),
                                        times_shown=2),
                      StoryHistoryEntry(url=items[2].source_url,
                                        last_shown_at=NOW - timedelta(days=3),
                                        times_shown=1),
                  ])


def test_rerun_widens_to_five_days_then_uses_least_recent_repeats():
    """New links win, including older ones, before previously shown links fill gaps."""
    old_a, old_b, old_c = source('old-a', 10), source('old-b', 5), source('old-c', 30)
    prior = previous_issue([old_a, old_b, old_c])
    items = [source('new-today', 1), source('new-three-days', 70),
             source('new-four-days', 100), old_a, old_b, old_c,
             source('too-old', 130)]
    selected = select_for_rerun(items, NOW, 48, 5, prior)
    assert [item.id for item in selected] == [
        'new-today', 'new-three-days', 'new-four-days', 'old-a', 'old-c']


def test_first_issue_uses_normal_window_and_approval_persists_links(tmp_path):
    """The five-day expansion starts only after an issue has been shown."""
    today, four_days = source('today', 1), source('four-days', 100)
    assert [item.id for item in select_for_rerun([today, four_days], NOW, 48, 5,
                                                 None)] == ['today']
    draft = Digest(generated_at=NOW, status='live', stories=[story(today)])
    approved = remember_approved(draft, None, NOW)
    path = tmp_path / 'latest.json'
    save_digest(approved, path)
    saved = load_digest(path)
    assert str(saved.story_history[0].url).rstrip('/') == 'https://example.com/today'
    assert saved.story_history[0].times_shown == 1
    assert [item.id for item in select_for_rerun([today, four_days], NOW, 48, 5,
                                                 saved)] == ['four-days', 'today']


def test_manually_added_feature_is_remembered_without_recounting_news():
    """Adding a separate human feature saves its link but keeps news counts."""
    news, human = source('news', 1), source('human', 24)
    first = remember_approved(Digest(generated_at=NOW, status='live',
                                     stories=[story(news)]), None, NOW)
    updated = remember_feature(first, story(human), NOW + timedelta(minutes=1))
    counts = {str(entry.url).rstrip('/'): entry.times_shown
              for entry in updated.story_history}
    assert counts == {'https://example.com/news': 1,
                      'https://example.com/human': 1}


def test_same_day_refresh_uses_newest_unseen_even_without_category_mix():
    """A second refresh today can use five news items before an older tool."""
    yesterday = source('yesterday', 30)
    prior = remember_approved(Digest(generated_at=NOW - timedelta(days=1),
                                     status='live', stories=[story(yesterday)]),
                              None, NOW - timedelta(minutes=10))
    newest_news = [source(f'news-{index}', index + 1) for index in range(5)]
    older_tool = source('older-tool', 20).model_copy(update={'category': 'AI Tools'})
    selected = select_for_rerun([older_tool, *newest_news], NOW, 48, 5, prior,
                                relaxed_category=True)
    assert [item.id for item in selected] == [item.id for item in newest_news]


def test_sparse_new_pool_keeps_five_using_previous_older_cards():
    """Previously shown cards fill the issue if only two recent links exist."""
    older = [source(f'previous-{index}', 200 + index) for index in range(5)]
    prior = Digest(generated_at=NOW - timedelta(days=8), status='live',
                   stories=[story(item) for item in older])
    new_items = [source('new-one', 1), source('new-two', 2)]
    selected = select_for_rerun(new_items, NOW, 48, 5, prior)
    assert len(selected) == 5
    assert [item.id for item in selected[:2]] == ['new-one', 'new-two']
    assert {item.id for item in selected[2:]} <= {item.id for item in older}


def test_relaxed_reruns_and_old_fallbacks_exclude_human_features():
    """Relaxing category quotas never mixes the separate human feature into news."""
    human = source('human', 200).model_copy(update={
        'title': 'AI helps students learn independently', 'category': 'Other'})
    prior = Digest(generated_at=NOW - timedelta(hours=1), status='live',
                   stories=[story(human)])
    fresh_human = source('fresh-human', 0).model_copy(update={'category': 'AI for Good'})
    news = [source(f'news-{index}', index + 1) for index in range(5)]
    selected = select_for_rerun([fresh_human, *news], NOW, 48, 6, prior,
                                relaxed_category=True)
    assert [item.id for item in selected] == [item.id for item in news]
