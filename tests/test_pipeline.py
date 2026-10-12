"""One offline path through RSS, Gemini validation, and saved dashboard data."""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from ai_pulse.fetch_news import FeedSource, fetch_news
from ai_pulse.process import prepare_candidates, select_stories
from ai_pulse.storage import load_digest, save_digest
from ai_pulse.summarize import summarize_items


class FixtureGemini:
    """Produce structured fictional explanations for the selected feed items."""

    def create(self, **kwargs):
        """Echo source IDs in a valid JSON response while recording no secrets."""
        inputs = json.loads(kwargs['input'].split('\n\n')[-1])
        summaries = [
            {'id': entry['id'],
             'simple_explanation': 'This fictional item describes an AI development.',
             'why_it_matters': 'It illustrates the briefing workflow.',
             'analogy': None}
            for entry in inputs
        ]
        return SimpleNamespace(output_text=json.dumps({'stories': summaries}))


def test_pipeline_saves_validated_dashboard_data(tmp_path):
    """The offline workflow saves explanations with the selected source links."""
    source = FeedSource('Fictional Test Feed', 'https://example.com/feed', ('example.com',))

    def fake_read(url, timeout):
        """Return only fictional RSS bytes for the approved test feed."""
        assert url == source.url
        return (Path(__file__).parent / 'fixtures' / 'rss_sample.xml').read_bytes()

    items, errors = fetch_news(feeds=(source,), read=fake_read)
    now = datetime(2026, 10, 10, 15, tzinfo=timezone.utc)
    selected = select_stories(prepare_candidates(items, now))
    digest = summarize_items(selected, 'fake-key', 'fake-model',
                             client=SimpleNamespace(interactions=FixtureGemini()))
    path = tmp_path / 'latest_digest.json'
    save_digest(digest, path)
    dashboard_data = load_digest(path)
    assert errors == []
    assert len(selected) == len(dashboard_data.stories) == 2
    assert dashboard_data.status == 'live'
    assert [story.title for story in dashboard_data.stories] == [item.title for item in selected]
    assert [story.source_url for story in dashboard_data.stories] == [item.source_url for item in selected]
    assert all(story.simple_explanation and story.why_it_matters for story in dashboard_data.stories)
