"""Prove that a generated draft stays off the dashboard until explicit review."""

import sys

import main as command_line
from ai_pulse.models import Story
from ai_pulse.storage import DEMO_DIGEST, load_digest, save_digest


def five_story_draft():
    """Expand the labeled fictional fixture into a complete live test issue."""
    digest = load_digest(DEMO_DIGEST).model_copy(update={'status': 'live'})
    clones = [Story.model_validate({**digest.stories[0].model_dump(),
        'id': f'extra-{index}',
        'title': f'Fictional extra AI story {index}',
        'source_url': f'https://example.com/extra-{index}',
    }) for index in range(3)]
    return digest.model_copy(update={'stories': [*digest.stories, *clones]})


def test_draft_needs_review_flag_before_it_replaces_visible_digest(monkeypatch, tmp_path):
    """Promotion must require the explicit human-review step."""
    draft = tmp_path / 'draft.json'
    visible = tmp_path / 'latest.json'
    save_digest(five_story_draft(), draft)
    monkeypatch.setattr(command_line, 'DRAFT_DIGEST', draft)
    monkeypatch.setattr(command_line, 'DEFAULT_DIGEST', visible)
    monkeypatch.setattr(sys, 'argv', ['main.py', 'approve-draft'])
    assert command_line.main() == 1
    assert not visible.exists()
    monkeypatch.setattr(sys, 'argv', ['main.py', 'approve-draft', '--reviewed'])
    assert command_line.main() == 0
    assert load_digest(visible).stories[0].id == 'demo-tools'
    assert len(load_digest(visible).story_history) == len(load_digest(draft).stories)

    def unexpected_save(*_args, **_kwargs):
        """Make the test fail if repeated approval writes the digest again."""
        raise AssertionError('Repeated approval wrote the same digest')

    monkeypatch.setattr(command_line, 'save_digest', unexpected_save)
    assert command_line.main() == 0


def test_approved_copy_edit_preserves_show_counts(monkeypatch, tmp_path):
    """Corrected text is publishable after review without counting a new issue."""
    draft = tmp_path / 'draft.json'
    visible = tmp_path / 'latest.json'
    original = five_story_draft()
    save_digest(original, draft)
    monkeypatch.setattr(command_line, 'DRAFT_DIGEST', draft)
    monkeypatch.setattr(command_line, 'DEFAULT_DIGEST', visible)
    monkeypatch.setattr(sys, 'argv', ['main.py', 'approve-draft', '--reviewed'])
    assert command_line.main() == 0
    before = load_digest(visible)
    corrected_story = original.stories[0].model_copy(update={
        'why_it_matters': 'A checked correction to the original takeaway.'})
    save_digest(original.model_copy(update={
        'stories': [corrected_story, *original.stories[1:]],
    }), draft)
    assert command_line.main() == 0
    after = load_digest(visible)
    assert after.stories[0].why_it_matters == corrected_story.why_it_matters
    assert after.story_history == before.story_history


def test_short_live_draft_cannot_replace_five_card_issue(monkeypatch, tmp_path):
    """The optional manual path also protects the five-story public layout."""
    draft = tmp_path / 'draft.json'
    visible = tmp_path / 'latest.json'
    save_digest(five_story_draft(), visible)
    before = visible.read_bytes()
    save_digest(load_digest(DEMO_DIGEST).model_copy(update={'status': 'live'}), draft)
    monkeypatch.setattr(command_line, 'DRAFT_DIGEST', draft)
    monkeypatch.setattr(command_line, 'DEFAULT_DIGEST', visible)
    monkeypatch.setattr(sys, 'argv', ['main.py', 'approve-draft', '--reviewed'])
    assert command_line.main() == 1
    assert visible.read_bytes() == before
