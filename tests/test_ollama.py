"""Offline checks for local Ollama output and fixed-source provenance."""

import io
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
import ai_pulse.ollama as local_model

from ai_pulse.models import SourceItem
from ai_pulse.ollama import local_model_identity, summarize_local_items
from ai_pulse.storage import DEMO_DIGEST, load_digest, save_digest


def source_item() -> SourceItem:
    """Make one fictional feed item whose title and link must stay unchanged."""
    return SourceItem(
        id='story-1', title='Fictional AI tool announced',
        source_name='Fictional Test Feed',
        source_url='https://example.com/fictional-ai-tool',
        published_at=datetime(2026, 10, 10, 12, tzinfo=timezone.utc),
        description='A fictional writing assistant was announced.',
        category='AI Tools',
    )


@pytest.mark.parametrize('request_limit, remaining, expected', [
    (120, None, 120), (300, None, 300), (300, 45, 45)])
def test_local_summary_uses_loopback_and_preserves_source_facts(
        monkeypatch, request_limit, remaining, expected):
    """Send one schema request to localhost and keep source-controlled data."""
    requests = []

    def fake_open(request, timeout):
        """Capture the local request and provide a valid fictional response."""
        requests.append((request, timeout))
        if request.full_url.endswith('/tags'):
            return io.BytesIO(b'{"models":[{"name":"gemma3:4b"}]}')
        body = {'message': {'content': json.dumps({'stories': [{
            'id': 'story-1',
            'simple_explanation': 'A fictional writing tool was introduced.',
            'why_it_matters': 'It gives beginners another drafting option.',
            'analogy': None,
        }]})}}
        return io.BytesIO(json.dumps(body).encode('utf-8'))

    def fake_clock():
        """Make the remaining total budget deterministic without sleeping."""
        return 100

    monkeypatch.setattr(local_model, 'monotonic', fake_clock)
    digest = summarize_local_items(
        [source_item()], 'gemma3:4b', open_url=fake_open,
        request_timeout=request_limit,
        deadline=None if remaining is None else 100 + remaining)
    request, timeout = requests[1]
    payload = json.loads(request.data)
    assert requests[0][0].full_url == 'http://127.0.0.1:11434/api/tags'
    assert request.full_url == 'http://127.0.0.1:11434/api/chat'
    assert timeout == expected
    assert payload['model'] == 'gemma3:4b'
    assert payload['format']['type'] == 'object'
    assert payload['stream'] is False
    assert len(requests) == 2
    assert digest.stories[0].title == source_item().title
    assert digest.stories[0].source_url == source_item().source_url
    assert digest.stories[0].source_excerpt == source_item().description


def test_invalid_local_output_keeps_previous_digest(tmp_path):
    """Reject a mismatched story ID before replacing the saved digest."""
    path = tmp_path / 'digest.json'
    save_digest(load_digest(DEMO_DIGEST), path)
    before = path.read_bytes()

    def fake_open(request, timeout):
        """Return a JSON shape with a story ID absent from the source feed."""
        if request.full_url.endswith('/tags'):
            return io.BytesIO(b'{"models":[{"name":"gemma3:4b"}]}')
        body = {'message': {'content': json.dumps({'stories': [{
            'id': 'unknown', 'simple_explanation': 'Text',
            'why_it_matters': 'Text',
        }]})}}
        return io.BytesIO(json.dumps(body).encode('utf-8'))

    with pytest.raises((ValueError, ValidationError)):
        digest = summarize_local_items([source_item()], 'gemma3:4b',
                                       open_url=fake_open)
        save_digest(digest, path)
    assert path.read_bytes() == before


def test_missing_local_model_never_reaches_chat():
    """An uninstalled model name cannot trigger a chat or download."""
    requests = []

    def fake_open(request, timeout):
        """List one installed model and record any attempted request."""
        requests.append(request.full_url)
        return io.BytesIO(b'{"models":[{"name":"gemma3:4b"}]}')

    with pytest.raises(ValueError, match='not installed locally'):
        summarize_local_items([source_item()], 'unknown:1b', open_url=fake_open)
    assert requests == ['http://127.0.0.1:11434/api/tags']


def test_local_summarizer_requests_each_story_separately():
    """Split a two-story digest into small calls and return both verified IDs."""
    requests = []
    second = source_item().model_copy(update={
        'id': 'story-2', 'title': 'Fictional AI game announced',
        'source_url': 'https://example.com/fictional-ai-game',
    })

    def fake_open(request, timeout):
        """Return an installed-model list, then the ID of each requested story."""
        requests.append(request)
        if request.full_url.endswith('/tags'):
            return io.BytesIO(b'{"models":[{"name":"gemma3:4b"}]}')
        story_id = f'story-{len(requests) - 1}'
        body = {'message': {'content': json.dumps({'stories': [{
            'id': story_id, 'simple_explanation': 'Fictional update.',
            'why_it_matters': 'Fictional context.',
        }]})}}
        return io.BytesIO(json.dumps(body).encode('utf-8'))

    digest = summarize_local_items([source_item(), second], 'gemma3:4b',
                                   open_url=fake_open)
    assert len(requests) == 3
    assert [story.id for story in digest.stories] == ['story-1', 'story-2']


def test_local_summarizer_retries_copied_excerpt_once():
    """A copied first answer gets one source-grounded rewrite attempt."""
    requests = []

    def fake_open(request, timeout):
        """Return installed tags, one copied excerpt, then a distinct summary."""
        requests.append(request)
        if request.full_url.endswith('/tags'):
            return io.BytesIO(b'{"models":[{"name":"gemma3:4b"}]}')
        copied = len(requests) == 2
        body = {'message': {'content': json.dumps({'stories': [{
            'id': 'story-1',
            'simple_explanation': ('A fictional writing assistant was announced.'
                                   if copied else
                                   'The publisher describes a writing helper for beginners.'),
            'why_it_matters': 'Beginners can compare another drafting option.',
        }]})}}
        return io.BytesIO(json.dumps(body).encode('utf-8'))

    digest = summarize_local_items([source_item()], 'gemma3:4b', open_url=fake_open)
    assert len(requests) == 3
    assert 'writing helper' in digest.stories[0].simple_explanation


def test_expired_local_summary_budget_never_calls_chat():
    """A spent time budget does not start another slow model request."""
    requests = []

    def fake_open(request, timeout):
        """Allow the installed-model check and record any chat attempt."""
        requests.append(request.full_url)
        return io.BytesIO(b'{"models":[{"name":"gemma3:4b"}]}')

    with pytest.raises(TimeoutError, match='time budget expired'):
        summarize_local_items([source_item()], 'gemma3:4b',
                              open_url=fake_open, deadline=0)
    assert requests == ['http://127.0.0.1:11434/api/tags']


def test_model_identity_uses_the_installed_weight_digest():
    """Use the installed weight hash so repulling a tag invalidates old summaries."""
    def fake_open(request, timeout):
        """Return model metadata only and reject any inference request."""
        assert request.full_url == 'http://127.0.0.1:11434/api/tags'
        assert timeout == 5
        return io.BytesIO(json.dumps({'models': [
            {'name': 'qwen2:7b', 'digest': 'a' * 64}]}).encode())

    assert local_model_identity('qwen2:7b', fake_open) == 'ollama:qwen2:7b:' + 'a' * 64
    with pytest.raises(ValueError, match='not installed'):
        local_model_identity('unknown:4b', fake_open)
