"""Automatic publication reuses checked cards and rejects unsupported claims."""

from datetime import datetime, timezone
import sys
from types import SimpleNamespace

import pytest

import main as command_line
from ai_pulse.automatic import build_automatic_digest
from ai_pulse.models import SourceItem
from ai_pulse.storage import load_digest
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
    assert all(entry.times_shown == 2 for entry in second.story_history)


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


def test_refresh_local_publishes_without_a_review_flag(monkeypatch, tmp_path):
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

    def fake_local_summary(articles, _model, deadline=None):
        """Return deterministic story explanations without contacting Ollama."""
        return safe_summarizer(articles)

    def fake_article_reader(item):
        """Return enough fictional article text for each selected test item."""
        return f'OpenAI article describing AI {item.id} and its research method. ' * 10

    def fake_model_identity(_model):
        """Resolve fictional installed weights without a localhost request."""
        return 'ollama:already-installed:' + 'a' * 64

    monkeypatch.setattr(command_line, 'DEFAULT_DIGEST', visible)
    monkeypatch.setattr(command_line, 'cached_candidates', fake_pool)
    monkeypatch.setattr(command_line, 'load_settings', fake_settings)
    monkeypatch.setattr(command_line, 'read_article', fake_article_reader)
    monkeypatch.setattr(command_line, 'summarize_local_items', fake_local_summary)
    monkeypatch.setattr(command_line, 'local_model_identity', fake_model_identity)
    monkeypatch.setattr(command_line, 'DEFAULT_SUMMARY_CACHE', tmp_path / 'cache.json')
    monkeypatch.setattr(sys, 'argv', ['main.py', 'refresh-local'])
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
