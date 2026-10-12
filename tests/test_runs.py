"""A pending draft stays protected while new approved issues may be generated."""

import sys
from types import SimpleNamespace

import main as command_line
from ai_pulse.runs import pending_draft_reason, same_issue, same_publication
from ai_pulse.storage import DEMO_DIGEST, load_digest, save_digest


def test_only_an_unreviewed_draft_blocks_generation(tmp_path):
    """An approved issue from today allows another run, but a pending draft waits."""
    reviewed = tmp_path / 'latest.json'
    draft = tmp_path / 'draft.json'
    digest = load_digest(DEMO_DIGEST).model_copy(update={'status': 'live'})
    assert pending_draft_reason(draft, reviewed) is None
    save_digest(digest, draft)
    assert pending_draft_reason(draft, reviewed) == 'An unreviewed draft already exists'
    save_digest(digest, reviewed)
    assert pending_draft_reason(draft, reviewed) is None


def test_an_edited_approved_issue_needs_review_again(tmp_path):
    """Changing a draft takeaway creates pending work without a new story issue."""
    reviewed = tmp_path / 'latest.json'
    draft = tmp_path / 'draft.json'
    original = load_digest(DEMO_DIGEST).model_copy(update={'status': 'live'})
    save_digest(original, reviewed)
    edited_story = original.stories[0].model_copy(update={
        'why_it_matters': 'This corrected takeaway needs a new review.'})
    edited = original.model_copy(update={
        'stories': [edited_story, *original.stories[1:]],
    })
    save_digest(edited, draft)
    assert same_issue(original, edited)
    assert not same_publication(original, edited)
    assert pending_draft_reason(draft, reviewed) == 'An unreviewed draft already exists'


def test_generation_skips_fetch_until_force_is_explicit(monkeypatch, tmp_path):
    """A pending draft makes no feed request while --force reaches fetching."""
    reviewed = tmp_path / 'latest.json'
    draft = tmp_path / 'draft.json'
    save_digest(load_digest(DEMO_DIGEST).model_copy(update={'status': 'live'}), draft)
    monkeypatch.setattr(command_line, 'DEFAULT_DIGEST', reviewed)
    monkeypatch.setattr(command_line, 'DRAFT_DIGEST', draft)
    called = []

    def fake_fetch():
        """Record a fetch attempt while returning no live candidates."""
        called.append(True)
        return [], []

    def fake_settings():
        """Provide selection settings without reading local credentials."""
        return SimpleNamespace(lookback_hours=48, story_count=5)

    def fake_pool(_now, refresh=False, shown_urls=None, fetcher=None):
        """Exercise the injected fetcher without writing a real project cache."""
        items, errors = fetcher()
        return SimpleNamespace(items=items, errors=errors, used_cache=False,
                               relaxed_category=False, all_feeds_failed=False)

    monkeypatch.setattr(command_line, 'fetch_news', fake_fetch)
    monkeypatch.setattr(command_line, 'cached_candidates', fake_pool)
    monkeypatch.setattr(command_line, 'load_settings', fake_settings)
    monkeypatch.setattr(sys, 'argv', ['main.py', 'generate-local'])
    assert command_line.main() == 0
    assert called == []
    monkeypatch.setattr(sys, 'argv', ['main.py', 'generate-local', '--force'])
    assert command_line.main() == 1
    assert called == [True]
