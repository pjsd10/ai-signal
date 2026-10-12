"""A dated, manually reviewed human-interest feature for this MVP briefing."""

from datetime import datetime
from zoneinfo import ZoneInfo

from ai_pulse.fetch_news import approved_article_host, canonical_url
from ai_pulse.models import Story


EASTERN = ZoneInfo('America/New_York')
FEATURE = Story(
    id='feature-students-2026-10-05',
    title='How students who cannot write are creating with AI',
    source_name='Google Blog',
    source_type='editorial',
    source_url=('https://blog.google/products-and-platforms/products/education/'
                'special-education-gemini'),
    published_at=datetime(2026, 10, 5, 12, tzinfo=EASTERN),
    category='AI for Good',
    summary_basis='editorial_review',
    date_precision='day',
    simple_explanation=('In Indonesia, special-needs teacher Eni Wulandari says '
                        'students who cannot write use voice prompts with Gemini to '
                        'make images and express their ideas. She also creates simple '
                        'visual guides for students who cannot read.'),
    why_it_matters=('Speaking to an AI tool gives these students another way to '
                    'participate and show what they imagine when writing is a barrier.'),
)


def current_feature(now: datetime) -> Story | None:
    """Offer the reviewed feature only for its first fifteen calendar days."""
    url = str(FEATURE.source_url)
    if canonical_url(url) != url or not approved_article_host(url, ('blog.google',)):
        raise ValueError('Featured article must remain on its approved publisher domain')
    age_days = (now.astimezone(EASTERN).date()
                - FEATURE.published_at.astimezone(EASTERN).date()).days
    return FEATURE if 0 <= age_days <= 15 else None
