"""Check that future model drafts cannot simply echo publisher feed text."""

from ai_pulse.models import Digest, Story
from ai_pulse.quality import check_digest, check_story


def sample_story(**changes) -> Story:
    """Build a valid fictional story while allowing one quality defect at a time."""
    fields = {
        'id': 'sample', 'title': 'Fictional AI testing tool',
        'source_name': 'Example Publisher', 'source_url': 'https://example.com/story',
        'published_at': '2026-10-10T12:00:00Z', 'category': 'AI Tools',
        'source_excerpt': 'A fictional testing tool was introduced for developers.',
        'simple_explanation': 'The company introduced a testing tool for developers.',
        'why_it_matters': 'Developers could use it to explore more test cases.'}
    fields.update(changes)
    return Story.model_validate(fields)


def test_repeated_feed_text_is_rejected():
    """A copied publisher excerpt should fail before it becomes a visible card."""
    story = sample_story(simple_explanation='A fictional testing tool was introduced for developers.')
    assert any('publisher excerpt' in issue for issue in check_story(story))


def test_process_copy_and_cutoff_are_rejected():
    """A takeaway must not contain internal feed wording or cut-off markers."""
    story = sample_story(why_it_matters='The RSS preview shows this might help […]')
    issues = check_story(story)
    assert any('feed-processing' in issue for issue in issues)
    assert any('cut-off' in issue for issue in issues)


def test_article_detail_passes_when_distinct_from_excerpt():
    """A concrete explanation drawn from article details can pass the mechanical check."""
    story = sample_story(simple_explanation=(
        'The tool gathers browser screenshots and records the steps that failed. '
        'It then prepares a test case for a developer to review.'))
    assert check_story(story) == []


def test_model_written_links_are_rejected():
    """Only Python-controlled publisher links may become clickable in a card."""
    story = sample_story(why_it_matters='Read https://unapproved.example for more.')
    assert any('unapproved link' in issue for issue in check_story(story))


def test_manual_draft_checks_reject_a_human_feature_in_main_news():
    """Draft review and approval use the same separation rule as auto refresh."""
    human = sample_story(title='AI helps students learn independently', category='Other')
    digest = Digest(generated_at=human.published_at, status='live', stories=[human])
    assert any('separate feature' in issue for issue in check_digest(digest))
    separated = digest.model_copy(update={'stories': [sample_story()], 'featured_story': human})
    assert check_digest(separated) == []
