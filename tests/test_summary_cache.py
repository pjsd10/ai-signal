"""Verify cache reuse, invalidation, persistence, and source checks offline."""

from datetime import datetime, timedelta, timezone
import json

import pytest

import ai_pulse.summary_cache as cache_module
from ai_pulse.models import SourceItem
from ai_pulse.summary_cache import SummaryCache
from ai_pulse.summarize import SummaryBatch, SummaryItem, digest_from_batch


NOW = datetime(2026, 10, 11, 21, tzinfo=timezone.utc)


def installed_model() -> str:
    """Provide a deterministic fictional model identity without Ollama."""
    return 'ollama:fictional:4b:' + 'a' * 64


def article() -> SourceItem:
    """Make source evidence for a fictional article on an approved domain."""
    return SourceItem(
        id='fictional-1', title='OpenAI explains a fictional AI study',
        source_name='OpenAI News', source_url='https://openai.com/index/fictional-1',
        published_at=NOW, category='AI Research',
        description='A fictional study of an AI writing assistant.',
        article_text=('OpenAI describes a fictional writing study with a published '
                      'research method. Readers can compare the results and method. ') * 5,
    )


def summary(item):
    """Create short prose supported by the fictional article evidence."""
    return digest_from_batch([item], SummaryBatch(stories=[SummaryItem(
        id=item.id,
        simple_explanation='OpenAI describes the method used in its writing study.',
        why_it_matters='Readers can compare the published research results.',
    )])).stories[0]


def test_cache_reloads_summary_without_persisting_article_or_prompt(tmp_path):
    """A later process can reuse a checked card without storing its full evidence."""
    path = tmp_path / 'summaries.json'
    item = article()
    first = SummaryCache(path, NOW, installed_model)
    first.put(item, summary(item))
    second = SummaryCache(path, NOW, installed_model)
    assert second.get(item) == summary(item)
    assert second.hits == 1
    raw = path.read_text(encoding='utf-8')
    assert '"article_text":' not in raw
    assert item.article_text not in raw
    assert 'You explain AI news' not in raw
    assert 'story_history' not in raw


@pytest.mark.parametrize('field, changed', [
    ('article_text', article().article_text + ' The method has been updated.'),
    ('description', 'An updated publisher description of the AI writing study.'),
    ('title', 'OpenAI updates its fictional AI study'),
    ('category', 'AI Tools'),
])
def test_changed_source_invalidates_summary(tmp_path, field, changed):
    """Publisher corrections or changed classification require fresh model output."""
    cache = SummaryCache(tmp_path / 'summaries.json', NOW, installed_model)
    item = article()
    cache.put(item, summary(item))
    assert cache.get(item.model_copy(update={field: changed})) is None


def test_model_prompt_and_policy_changes_invalidate_summary(tmp_path, monkeypatch):
    """A cache result cannot leak across model weights, prompt edits, or policies."""
    path = tmp_path / 'summaries.json'
    item = article()
    SummaryCache(path, NOW, installed_model).put(item, summary(item))

    def different_weights():
        """Simulate replacing the weights behind the same model name."""
        return 'ollama:fictional:4b:' + 'b' * 64

    assert SummaryCache(path, NOW, different_weights).get(item) is None
    monkeypatch.setattr(cache_module, 'SUMMARY_POLICY_VERSION', 'changed')
    assert SummaryCache(path, NOW, installed_model).get(item) is None
    monkeypatch.setattr(cache_module, 'SUMMARY_POLICY_VERSION', '1')
    original_prompt = cache_module.build_prompt

    def changed_prompt(items):
        """Represent a changed editorial instruction in the model input."""
        return original_prompt(items) + '\nUse the revised editorial style.'

    monkeypatch.setattr(cache_module, 'build_prompt', changed_prompt)
    assert SummaryCache(path, NOW, installed_model).get(item) is None


def test_expired_and_future_dated_entries_are_not_reused(tmp_path):
    """Seven-day expiry and clock anomalies both produce safe cache misses."""
    path = tmp_path / 'summaries.json'
    item = article()
    SummaryCache(path, NOW, installed_model).put(item, summary(item))
    assert SummaryCache(path, NOW + timedelta(days=7), installed_model).get(item) is None
    assert SummaryCache(path, NOW - timedelta(seconds=1), installed_model).entries == {}


def test_corrupt_cache_is_ignored_and_rebuilt(tmp_path):
    """A truncated local cache cannot block otherwise valid generation."""
    path = tmp_path / 'summaries.json'
    path.write_text('{broken', encoding='utf-8')
    cache = SummaryCache(path, NOW, installed_model)
    assert cache.get(article()) is None
    assert len(cache.notes) == 1
    cache.put(article(), summary(article()))
    assert SummaryCache(path, NOW, installed_model).get(article()) is not None


def test_modified_cached_claim_is_revalidated(tmp_path):
    """Even a well-formed cache entry cannot introduce an unsupported statistic."""
    path = tmp_path / 'summaries.json'
    item = article()
    SummaryCache(path, NOW, installed_model).put(item, summary(item))
    data = json.loads(path.read_text(encoding='utf-8'))
    next(iter(data['entries'].values()))['story']['why_it_matters'] = 'It is 99 percent faster.'
    path.write_text(json.dumps(data), encoding='utf-8')
    cache = SummaryCache(path, NOW, installed_model)
    assert cache.get(item) is None
    assert len(cache.notes) == 1


def test_failed_quality_and_unapproved_source_are_never_cached(tmp_path):
    """Reject copied prose and reject source domains before looking up or saving."""
    cache = SummaryCache(tmp_path / 'summaries.json', NOW, installed_model)
    item = article()
    copied = summary(item).model_copy(update={'simple_explanation': item.description})
    with pytest.raises(ValueError, match='quality check failed'):
        cache.put(item, copied)
    unsafe = item.model_copy(update={'source_url': 'https://unapproved.example/story'})
    with pytest.raises(ValueError, match='approved-source'):
        cache.get(unsafe)
    assert not cache.path.exists()


def test_failed_cache_replace_preserves_previous_cache(tmp_path, monkeypatch):
    """An interrupted disk write keeps existing usable cache bytes intact."""
    path = tmp_path / 'summaries.json'
    cache = SummaryCache(path, NOW, installed_model)
    item = article()
    cache.put(item, summary(item))
    before = path.read_bytes()

    def failed_replace(_source, _target):
        """Simulate a real filesystem write failure without touching the target."""
        raise OSError('simulated disk error')

    monkeypatch.setattr(cache_module.os, 'replace', failed_replace)
    changed = item.model_copy(update={'article_text': item.article_text + ' Updated.'})
    cache.put(changed, summary(changed))
    assert path.read_bytes() == before
    assert len(cache.notes) == 1
    assert list(tmp_path.glob('*.tmp')) == []


def test_cache_evicts_oldest_entries(tmp_path, monkeypatch):
    """A bounded cache retains the latest generated summaries."""
    monkeypatch.setattr(cache_module, 'MAX_ENTRIES', 2)
    path = tmp_path / 'summaries.json'
    first = article()
    second = first.model_copy(update={'id': 'fictional-2'})
    third = first.model_copy(update={'id': 'fictional-3'})
    for index, item in enumerate([first, second, third]):
        SummaryCache(path, NOW + timedelta(minutes=index), installed_model).put(item, summary(item))
    cache = SummaryCache(path, NOW + timedelta(minutes=3), installed_model)
    assert len(cache.entries) == 2
    assert cache.get(first) is None
    assert cache.get(third) is not None
