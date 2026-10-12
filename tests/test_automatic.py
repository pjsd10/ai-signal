"""Automatic publication reuses checked cards and rejects unsupported claims."""

from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace

import pytest
from pydantic import HttpUrl

import main as command_line
import ai_pulse.automatic as automatic
from ai_pulse.automatic import build_automatic_digest
from ai_pulse.models import SourceItem
from ai_pulse.storage import load_digest, save_digest
from ai_pulse.process import normalized_title, url_key
from ai_pulse.summarize import SummaryBatch, SummaryItem, digest_from_batch
from ai_pulse.summary_cache import SummaryCache


NOW = datetime(2026, 10, 11, 21, tzinfo=timezone.utc)


def source(slug: str) -> SourceItem:
    """Create a fictional article URL on an approved publisher domain."""
    return SourceItem(id=slug, title=f'OpenAI explains AI {slug}',
                      source_name='OpenAI News',
                      source_url=f'https://openai.com/index/{slug}',
                      published_at=NOW,
                      description=f'The publisher describes {slug} in AI research.',
                      category='AI Research')


def fictional_article(item):
    """Supply fictional publisher article paragraphs without networking."""
    return (f'OpenAI describes {item.id} in its publisher article. '
            'The article explains the research goal and the method '
            'used to test the idea. ') * 4


def safe_summarizer(items):
    """Create deterministic source-matched prose for publication tests."""
    batch = SummaryBatch(stories=[SummaryItem(
        id=item.id,
        simple_explanation=f'OpenAI describes an AI research update called {item.id}.',
        why_it_matters=f'Readers can compare the published details for {item.id}.',
    ) for item in items])
    return digest_from_batch(items, batch)


def test_automatic_refresh_publishes_five_and_reuses_repeats():
    """The next refresh needs no article fetch or model call for shown links."""
    items = [source(f'topic-{index}') for index in range(5)]
    first, _ = build_automatic_digest(items, None, NOW, safe_summarizer,
                                      fictional_article)
    assert len(first.stories) == 5
    assert len(first.story_history) == 6  # Five news cards plus the dated feature.

    def unexpected_summarizer(_items):
        """Fail if a repeat story needlessly calls the model again."""
        raise AssertionError('Repeated stories were summarized again')

    second, _ = build_automatic_digest(items, first, NOW,
                                       unexpected_summarizer, fictional_article)
    assert len(second.stories) == 5
    assert second is first
    assert all(entry.times_shown == 1 for entry in second.story_history)


def test_automatic_refresh_rejects_a_number_not_in_source():
    """A model-introduced statistic stops publication before the saved file changes."""
    items = [source(f'topic-{index}') for index in range(5)]

    def invented_number(items_to_summarize):
        """Return a numeric claim absent from the supplied publisher text."""
        digest = safe_summarizer(items_to_summarize)
        changed = digest.stories[0].model_copy(update={
            'why_it_matters': 'This improves the result by 99 percent.',
        })
        return digest.model_copy(update={'stories': [changed, *digest.stories[1:]]})

    with pytest.raises(ValueError, match='number absent'):
        build_automatic_digest(items, None, NOW, invented_number,
                               fictional_article)


def test_automatic_refresh_keeps_old_issue_when_article_text_is_missing():
    """A short RSS preview alone cannot be published without human checking."""
    items = [source(f'topic-{index}') for index in range(5)]

    def missing_article(_item):
        """Simulate approved publisher pages with no readable article body."""
        return ''

    with pytest.raises(ValueError, match='Fewer than five'):
        build_automatic_digest(items, None, NOW, safe_summarizer,
                               missing_article)


def test_unreadable_article_uses_the_next_verified_candidate():
    """One inaccessible publisher page does not prevent a full safe issue."""
    candidates = [source(f'topic-{index}') for index in range(6)]

    def selective_reader(item):
        """Fail the first article and provide readable text for the others."""
        if item.id == 'topic-0':
            raise ValueError('No substantial article body was available')
        return f'OpenAI article about {item.id}. ' * 30

    digest, notes = build_automatic_digest(candidates, None, NOW,
                                          safe_summarizer, reader=selective_reader)
    assert [story.id for story in digest.stories] == [
        f'topic-{index}' for index in range(1, 6)]
    assert len(notes) == 1


def test_copied_summary_uses_the_next_verified_candidate():
    """A failed summary is skipped while other passed summaries are retained."""
    candidates = [source(f'topic-{index}') for index in range(6)]

    def sometimes_copied(items):
        """Echo the first excerpt and explain every other article distinctly."""
        if items[0].id == 'topic-0':
            batch = SummaryBatch(stories=[SummaryItem(
                id='topic-0', simple_explanation=items[0].description,
                why_it_matters='Readers can inspect the publisher details.')])
            return digest_from_batch(items, batch)
        return safe_summarizer(items)

    digest, notes = build_automatic_digest(candidates, None, NOW,
                                          sometimes_copied, reader=fictional_article)
    assert [story.id for story in digest.stories] == [
        f'topic-{index}' for index in range(1, 6)]
    assert len(notes) == 1


def test_expired_refresh_budget_stops_before_reading_an_article():
    """An expired run leaves publication to the caller without new work."""
    def unexpected_reader(_item):
        """Fail if an expired run tries to contact an article publisher."""
        raise AssertionError('Expired run read an article')

    with pytest.raises(TimeoutError, match='time budget expired'):
        build_automatic_digest([source('topic-1')], None, NOW,
                               safe_summarizer, reader=unexpected_reader,
                               deadline=0)


@pytest.mark.parametrize('budget, request_limit', [(300, 120), (900, 300)])
def test_refresh_local_publishes_without_a_review_flag(monkeypatch, tmp_path,
                                                     budget, request_limit):
    """The automatic command writes five checked cards without a manual gate."""
    items = [source(f'topic-{index}') for index in range(5)]
    visible = tmp_path / 'latest.json'

    def fake_pool(_now, refresh=False, shown_urls=None, fetcher=None):
        """Supply approved-looking buffered stories without touching the network."""
        return SimpleNamespace(items=items, errors=[], used_cache=True,
                               relaxed_category=False, all_feeds_failed=False)

    def fake_settings():
        """Provide only the local settings needed by this command."""
        return SimpleNamespace(lookback_hours=48, story_count=5,
                               ollama_model='already-installed')

    def fake_local_summary(articles, _model, deadline=None, request_timeout=120):
        """Return deterministic story explanations without contacting Ollama."""
        assert deadline == 10 + budget
        assert request_timeout == request_limit
        return safe_summarizer(articles)

    def fake_article_reader(item):
        """Return enough fictional article text for each selected test item."""
        return f'OpenAI article describing AI {item.id} and its research method. ' * 10

    def fake_model_identity(_model):
        """Resolve fictional installed weights without a localhost request."""
        return 'ollama:already-installed:' + 'a' * 64

    def fake_clock():
        """Use a fixed reference time to verify the configured generation budget."""
        return 10

    monkeypatch.setattr(command_line, 'DEFAULT_DIGEST', visible)
    monkeypatch.setattr(command_line, 'cached_candidates', fake_pool)
    monkeypatch.setattr(command_line, 'load_settings', fake_settings)
    monkeypatch.setattr(command_line, 'read_article', fake_article_reader)
    monkeypatch.setattr(command_line, 'summarize_local_items', fake_local_summary)
    monkeypatch.setattr(command_line, 'local_model_identity', fake_model_identity)
    monkeypatch.setattr(command_line, 'monotonic', fake_clock)
    monkeypatch.setattr(automatic, 'monotonic', fake_clock)
    monkeypatch.setattr(command_line, 'DEFAULT_SUMMARY_CACHE', tmp_path / 'cache.json')
    monkeypatch.setattr(sys, 'argv', ['main.py', 'refresh-local',
                                    '--timeout-seconds', str(budget),
                                    '--model-timeout-seconds', str(request_limit)])
    assert command_line.main() == 0
    assert len(load_digest(visible).stories) == 5


def test_partial_refresh_keeps_passed_summaries_for_next_run(tmp_path):
    """A timeout after two cards leaves two cache hits and only three new calls."""
    items = [source(f'topic-{index}') for index in range(5)]
    path = tmp_path / 'cache.json'
    calls = []

    def model_identity():
        """Identify a fixed fictional model for both independent runs."""
        return 'ollama:fictional:' + 'a' * 64

    def interrupted_summarizer(batch):
        """Succeed twice, then simulate a timed-out local model request."""
        if batch[0].id == 'topic-2':
            raise TimeoutError('simulated model timeout')
        return safe_summarizer(batch)

    def counted_summarizer(batch):
        """Record exactly which remaining stories need model generation."""
        calls.append(batch[0].id)
        return safe_summarizer(batch)

    first_cache = SummaryCache(path, NOW, model_identity)
    with pytest.raises(TimeoutError):
        build_automatic_digest(items, None, NOW, interrupted_summarizer,
                               fictional_article, summary_cache=first_cache)
    assert first_cache.saved == 2
    second_cache = SummaryCache(path, NOW, model_identity)
    digest, _ = build_automatic_digest(items, None, NOW, counted_summarizer,
                                       fictional_article, summary_cache=second_cache)
    assert second_cache.hits == 2
    assert calls == ['topic-2', 'topic-3', 'topic-4']
    assert len(digest.stories) == 5
    assert all(entry.times_shown == 1 for entry in digest.story_history)
    third_cache = SummaryCache(path, NOW, model_identity)
    build_automatic_digest(items, None, NOW, counted_summarizer,
                           fictional_article, summary_cache=third_cache)
    assert third_cache.hits == 5
    assert calls == ['topic-2', 'topic-3', 'topic-4']


def test_publisher_skips_human_features_even_when_called_without_selection():
    """A direct publication call cannot put an AI-for-Good item in the news five."""
    human = source('human').model_copy(update={
        'title': 'AI helps students learn independently', 'category': 'Other'})
    items = [human, *[source(f'topic-{index}') for index in range(5)]]
    digest, notes = build_automatic_digest(items, None, NOW, safe_summarizer,
                                          fictional_article)
    assert len(digest.stories) == 5
    assert human.id not in {story.id for story in digest.stories}
    assert notes == [f'Reserved for the separate AI for Good feature: {human.title}']


def previous_issue():
    """Build five already-checked fictional cards for fallback tests."""
    items = [source(f'old-{index}') for index in range(5)]
    return build_automatic_digest(items, None, NOW, safe_summarizer,
                                  fictional_article)[0]


@pytest.mark.parametrize('passed_count', [4, 2, 0])
@pytest.mark.parametrize('failure', ['quality', 'timeout', 'budget'])
def test_partial_refresh_fills_only_from_checked_cards(
        monkeypatch, tmp_path, passed_count, failure):
    """Publish 4+1 or 2+3; keep the entire original issue when none pass."""
    previous = previous_issue()
    before = previous.model_dump_json()
    now = NOW + timedelta(hours=1)
    items = [source(f'new-{index}') for index in range(5)]
    completed = []

    def model_identity():
        """Identify fixed fictional weights without contacting a server."""
        return 'ollama:fictional:' + 'b' * 64

    def failing_model(batch):
        """Simulate either a quality failure or a timeout after passing cards."""
        if len(completed) >= passed_count:
            if failure == 'timeout':
                raise TimeoutError('simulated model timeout')
            result = safe_summarizer(batch)
            bad = result.stories[0].model_copy(update={
                'why_it_matters': 'This improves the result by 999 percent.'})
            return result.model_copy(update={'stories': [bad]})
        completed.append(batch[0].id)
        return safe_summarizer(batch)

    def controlled_clock():
        """Expire the generation budget immediately after the requested successes."""
        return 100 if len(completed) >= passed_count else 0

    if failure == 'budget':
        monkeypatch.setattr(automatic, 'monotonic', controlled_clock)
    cache = SummaryCache(tmp_path / 'cache.json', now, model_identity)
    digest, notes = build_automatic_digest(
        items, previous, now, failing_model, fictional_article,
        deadline=50 if failure == 'budget' else None, summary_cache=cache)
    assert len(digest.stories) == 5
    assert len({url_key(story.source_url) for story in digest.stories}) == 5
    assert len({normalized_title(story.title) for story in digest.stories}) == 5
    assert [story.id for story in digest.stories[:passed_count]] == completed
    assert sum(story.id.startswith('old-') for story in digest.stories) == 5 - passed_count
    assert cache.saved == passed_count
    assert previous.model_dump_json() == before
    assert all(story.published_at == NOW for story in digest.stories)
    shown = {url_key(entry.url) for entry in digest.story_history}
    assert all(url_key(item.source_url) not in shown for item in items[passed_count:])
    assert notes
    if passed_count:
        assert digest.generated_at == now
    else:
        assert digest is previous
        assert digest.generated_at == NOW


@pytest.mark.parametrize('passed_count', [4, 2, 0])
def test_partial_refresh_command_publishes_complete_file(
        monkeypatch, tmp_path, passed_count):
    """Exercise the actual CLI path and prove zero success never rewrites the file."""
    previous = previous_issue()
    visible = tmp_path / 'latest.json'
    save_digest(previous, visible)
    original = visible.read_bytes()
    original_mtime = visible.stat().st_mtime_ns
    items = [source(f'new-{index}') for index in range(5)]
    calls = []
    writes = []

    def fake_pool(_now, refresh=False, shown_urls=None, fetcher=None):
        """Return independent candidates while keeping all test traffic offline."""
        return SimpleNamespace(items=items, errors=[], used_cache=True,
                               relaxed_category=False, all_feeds_failed=False)

    def fake_settings():
        """Provide the existing local model and five-story target."""
        return SimpleNamespace(lookback_hours=48, story_count=5,
                               ollama_model='already-installed')

    def controlled_model(articles, _model, deadline=None, request_timeout=120):
        """Time out after the scenario's requested number of successful cards."""
        if len(calls) >= passed_count:
            raise TimeoutError('simulated model timeout')
        calls.append(articles[0].id)
        return safe_summarizer(articles)

    def fake_identity(_model):
        """Return fixed model metadata without touching Ollama."""
        return 'ollama:already-installed:' + 'a' * 64

    def record_save(digest, path):
        """Assert only a complete digest reaches the real atomic file writer."""
        assert len(digest.stories) == 5
        writes.append(digest)
        save_digest(digest, path)

    class FixedTime(datetime):
        """Keep source freshness and generated timestamps deterministic."""

        @classmethod
        def now(cls, tz=None):
            """Return the next refresh time in the requested timezone."""
            return (NOW + timedelta(hours=1)).astimezone(tz)

    monkeypatch.setattr(command_line, 'datetime', FixedTime)
    monkeypatch.setattr(command_line, 'DEFAULT_DIGEST', visible)
    monkeypatch.setattr(command_line, 'DEFAULT_SUMMARY_CACHE', tmp_path / 'cache.json')
    monkeypatch.setattr(command_line, 'cached_candidates', fake_pool)
    monkeypatch.setattr(command_line, 'load_settings', fake_settings)
    monkeypatch.setattr(command_line, 'read_article', fictional_article)
    monkeypatch.setattr(command_line, 'summarize_local_items', controlled_model)
    monkeypatch.setattr(command_line, 'local_model_identity', fake_identity)
    monkeypatch.setattr(command_line, 'save_digest', record_save)
    monkeypatch.setattr(sys, 'argv', ['main.py', 'refresh-local'])
    assert command_line.main() == 0
    published = load_digest(visible)
    assert len({str(story.source_url) for story in published.stories}) == 5
    assert sum(story.id.startswith('new-') for story in published.stories) == passed_count
    assert len(writes) == int(passed_count > 0)
    if not passed_count:
        assert visible.read_bytes() == original
        assert visible.stat().st_mtime_ns == original_mtime
        assert published == previous
    else:
        assert published.generated_at == NOW + timedelta(hours=1)


@pytest.mark.parametrize('duplicate_kind', ['url', 'id', 'headline'])
def test_partial_refresh_deduplicates_new_and_fallback_cards(duplicate_kind):
    """Never include two cards with the same link, ID, or normalized headline."""
    previous = previous_issue()
    fresh = source('new-topic')
    duplicate = source('duplicate-topic')
    if duplicate_kind == 'url':
        duplicate = duplicate.model_copy(update={'source_url': fresh.source_url})
    elif duplicate_kind == 'id':
        duplicate = duplicate.model_copy(update={'id': fresh.id})
    else:
        duplicate = duplicate.model_copy(update={'title': fresh.title.upper() + '!!!'})
    # One new card shares an old headline, so its old equivalent must be skipped.
    matching_old = source('changed-link').model_copy(update={
        'title': previous.stories[0].title})
    calls = []

    def counted_model(items):
        """Track model calls to prove duplicate candidates are skipped early."""
        calls.append(str(items[0].source_url))
        return safe_summarizer(items)

    digest, _ = build_automatic_digest(
        [fresh, duplicate, matching_old], previous, NOW + timedelta(hours=1),
        counted_model, fictional_article)
    assert len(calls) == 2
    assert len(digest.stories) == 5
    assert previous.stories[0].id not in {story.id for story in digest.stories}
    assert len({story.id for story in digest.stories}) == 5
    assert len({url_key(story.source_url) for story in digest.stories}) == 5
    assert len({normalized_title(story.title) for story in digest.stories}) == 5


@pytest.mark.parametrize('fault', [
    'unapproved', 'tracking', 'future', 'rss_only', 'copied', 'human'])
def test_fallback_rechecks_saved_cards(fault):
    """Reject unsafe, outdated-policy, or defective saved cards before reuse."""
    previous = previous_issue()
    saved = previous.stories[0]
    updates = {
        'unapproved': {'source_url': HttpUrl('https://unapproved.example/article')},
        'tracking': {'source_url': HttpUrl(str(saved.source_url) + '?utm_source=test')},
        'future': {'published_at': NOW + timedelta(days=1)},
        'rss_only': {'summary_basis': 'rss_preview'},
        'copied': {'simple_explanation': saved.source_excerpt},
        'human': {'title': 'AI helps students learn independently'},
    }
    previous = previous.model_copy(update={
        'stories': [saved.model_copy(update=updates[fault]), *previous.stories[1:]]})
    fresh = [source(f'new-{index}') for index in range(4)]
    digest, _ = build_automatic_digest(fresh, previous, NOW + timedelta(hours=1),
                                      safe_summarizer, fictional_article)
    assert len(digest.stories) == 5
    assert saved.id not in {story.id for story in digest.stories}
    assert digest.stories[-1].id == 'old-1'


def test_bad_candidate_never_reaches_the_article_reader():
    """Unapproved and tracking-bearing URLs fail before any retrieval attempt."""
    previous = previous_issue()
    bad = [source('unsafe').model_copy(update={
        'source_url': 'https://unapproved.example/article'}),
        source('tracking').model_copy(update={
            'source_url': 'https://openai.com/index/topic?utm_source=test'})]

    def unexpected_reader(_item):
        """Fail if source validation allows a prohibited article request."""
        raise AssertionError('Unsafe candidate reached the network layer')

    digest, notes = build_automatic_digest(bad, previous, NOW + timedelta(hours=1),
                                          safe_summarizer, unexpected_reader)
    assert digest is previous
    assert len(notes) == 3


def test_insufficient_verified_fallback_never_invents_a_fifth_card():
    """Fail publication when a new card plus valid saved cards cannot fill five."""
    previous = previous_issue()
    previous = previous.model_copy(update={'stories': previous.stories[:3]})
    with pytest.raises(ValueError, match='Fewer than five distinct'):
        build_automatic_digest([source('new-topic')], previous,
                               NOW + timedelta(hours=1), safe_summarizer,
                               fictional_article)


def test_direct_publication_never_reads_new_stale_articles():
    """The publisher independently enforces the five-day cap for new article reads."""
    previous = previous_issue()
    stale = source('stale').model_copy(update={
        'published_at': NOW - timedelta(days=5, seconds=1)})

    def unexpected_reader(_item):
        """Fail if an out-of-window new article reaches the network."""
        raise AssertionError('Read a stale new candidate')

    digest, notes = build_automatic_digest([stale], previous, NOW,
                                          safe_summarizer, unexpected_reader)
    assert digest is previous
    assert any('five-day window' in note for note in notes)
