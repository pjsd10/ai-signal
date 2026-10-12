"""Offline checks for Gemini's structured output and source provenance."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_pulse.models import SourceItem
from ai_pulse.storage import DEMO_DIGEST, load_digest, save_digest
from ai_pulse.summarize import summarize_items


class FakeInteractions:
    """Return a chosen JSON response without contacting Gemini."""

    def __init__(self, output_text: str):
        """Store the simulated model text for the next create call."""
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        """Record the request and return a response shaped like the SDK's."""
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


def source_item() -> SourceItem:
    """Provide a fictional article whose source facts must remain unchanged."""
    return SourceItem(
        id='story-1', title='A company launches an AI tool',
        source_name='Fictional Test Feed',
        source_url='https://example.com/ai-tool',
        published_at=datetime(2026, 10, 10, 12, tzinfo=timezone.utc),
        description='A fictional new writing assistant.', category='AI Tools',
    )


def test_summary_uses_one_call_and_keeps_source_facts():
    """Only explanation fields come from Gemini; source URL/date/title stay fixed."""
    fake = FakeInteractions(json.dumps({'stories': [{
        'id': 'story-1',
        'simple_explanation': 'The company introduced a writing assistant.',
        'why_it_matters': 'It may give beginners another way to draft text.',
        'analogy': None,
    }]}))
    digest = summarize_items([source_item()], 'fake-key', 'fake-model',
                             client=SimpleNamespace(interactions=fake))
    assert digest.status == 'live'
    assert digest.stories[0].source_url == source_item().source_url
    assert digest.stories[0].title == source_item().title
    assert digest.stories[0].published_at == source_item().published_at
    assert len(fake.calls) == 1
    assert fake.calls[0]['response_format']['mime_type'] == 'application/json'


@pytest.mark.parametrize('output', [
    'not json',
    json.dumps({'stories': [{'id': 'wrong-id', 'simple_explanation': 'Text',
                             'why_it_matters': 'Text'}]}),
    json.dumps({'stories': [{'id': 'story-1', 'simple_explanation': 'Text',
                             'why_it_matters': 'Text',
                             'source_url': 'https://evil.example/story'}]}),
])
def test_invalid_model_output_cannot_replace_saved_digest(tmp_path, output):
    """Malformed, mismatched, or source-overriding output leaves saved data intact."""
    path = tmp_path / 'digest.json'
    save_digest(load_digest(DEMO_DIGEST), path)
    before = path.read_bytes()
    fake = FakeInteractions(output)
    with pytest.raises((ValidationError, ValueError)):
        new_digest = summarize_items([source_item()], 'fake-key', 'fake-model',
                                     client=SimpleNamespace(interactions=fake))
        save_digest(new_digest, path)
    assert path.read_bytes() == before
