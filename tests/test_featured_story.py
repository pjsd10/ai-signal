"""Checks for the separately dated, approved human-interest story."""

from datetime import datetime, timezone

from ai_pulse.featured_story import current_feature
from ai_pulse.fetch_news import FEEDS


def test_human_story_has_verified_date_and_expires():
    """A feature stays separate from breaking news and disappears when old."""
    current = current_feature(datetime(2026, 10, 11, tzinfo=timezone.utc))
    assert current is not None
    assert current.source_type == 'editorial'
    assert current.date_precision == 'day'
    assert current.published_at.date().isoformat() == '2026-10-05'
    assert current_feature(datetime(2026, 10, 22, tzinfo=timezone.utc)) is None


def test_expanded_feed_list_stays_within_user_cap():
    """The expanded source set contains only the nine explicitly checked feeds."""
    assert len(FEEDS) == 9
    assert len({feed.name for feed in FEEDS}) == len(FEEDS)
    assert any(feed.name == 'Google DeepMind' for feed in FEEDS)
    assert not any(feed.name in ('TechCrunch', 'VentureBeat AI') for feed in FEEDS)
