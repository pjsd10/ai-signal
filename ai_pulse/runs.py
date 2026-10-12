"""Protect an unreviewed draft while allowing new daily story selections."""

from pathlib import Path

from ai_pulse.models import Digest
from ai_pulse.storage import load_digest


def same_issue(first: Digest, second: Digest) -> bool:
    """Match an issue by generation time and story IDs despite copy edits."""
    return (first.generated_at == second.generated_at and
            [story.id for story in first.stories] ==
            [story.id for story in second.stories] and
            (first.featured_story.id if first.featured_story else None) ==
            (second.featured_story.id if second.featured_story else None))


def same_publication(first: Digest, second: Digest) -> bool:
    """Compare visible content while ignoring approval-only link history."""
    return (same_issue(first, second) and
            first.model_dump(mode='json', exclude={'story_history'}) ==
            second.model_dump(mode='json', exclude={'story_history'}))


def pending_draft_reason(draft_path: Path, visible_path: Path) -> str | None:
    """Ask for an intentional override before replacing an unreviewed draft."""
    if not draft_path.exists():
        return None
    draft = load_digest(draft_path)
    if visible_path.exists() and same_publication(draft, load_digest(visible_path)):
        return None
    return 'An unreviewed draft already exists'
