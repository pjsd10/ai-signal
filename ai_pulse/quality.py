"""Catch mechanical editorial defects before a model draft is saved or shown."""

from difflib import SequenceMatcher
from html import unescape
import re

from ai_pulse.models import Digest, SourceItem, Story
from ai_pulse.process import is_main_news_item


def check_automatic_story(story: Story, item: SourceItem) -> None:
    """Reject changed source facts and claims absent from the supplied evidence."""
    if (story.id != item.id or story.title != item.title
            or story.source_type != 'rss'
            or str(story.source_url) != str(item.source_url)
            or story.source_name != item.source_name
            or story.published_at != item.published_at
            or story.category != item.category
            or story.source_excerpt != item.description
            or story.summary_basis != ('article_text' if item.article_text else 'rss_preview')):
        raise ValueError('Generated story changed publisher-controlled fields')
    evidence = f'{item.source_name} {item.title} {item.description} {item.article_text}'
    claims = f'{story.simple_explanation} {story.why_it_matters}'
    source_numbers = set(re.findall(r'\b\d+(?:[.,]\d+)*\b', evidence))
    claimed_numbers = set(re.findall(r'\b\d+(?:[.,]\d+)*\b', claims))
    if not claimed_numbers <= source_numbers:
        raise ValueError('Generated story contains a number absent from its source')
    evidence_words = set(re.findall(r'\w+', evidence.casefold()))
    common_caps = {'The', 'This', 'These', 'A', 'An', 'It', 'Its', 'They', 'Their',
                   'Readers', 'Teams', 'AI'}
    unsupported_names = {word for word in re.findall(r'\b[A-Z][A-Za-z0-9]+\b', claims)
                         if word not in common_caps and word.casefold() not in evidence_words}
    if unsupported_names:
        raise ValueError('Generated story names an entity absent from its source')
    quoted = re.findall(r'["“]([^"”]+)["”]', claims)
    if any(phrase.casefold() not in evidence.casefold() for phrase in quoted):
        raise ValueError('Generated story quotes text absent from its source')


def plain_words(value: str) -> str:
    """Decode entities and reduce punctuation so two phrasings can be compared."""
    decoded = unescape(unescape(value)).casefold()
    return ' '.join(re.findall(r'[\w]+', decoded))


def check_story(story: Story) -> list[str]:
    """List detectable repetition, formatting, and process-copy problems."""
    issues = []
    explanation = plain_words(story.simple_explanation)
    excerpt = plain_words(story.source_excerpt)
    takeaway = plain_words(story.why_it_matters)
    if excerpt and SequenceMatcher(None, explanation, excerpt).ratio() >= 0.82:
        issues.append('explanation is too similar to the publisher excerpt')
    if SequenceMatcher(None, explanation, takeaway).ratio() >= 0.82:
        issues.append('why-it-matters repeats the explanation')
    if re.search(r'\[\s*(?:\.\.\.|…)\s*\]',
                 story.simple_explanation + story.why_it_matters):
        issues.append('model prose contains a cut-off marker')
    if re.search(r'&#(?:x[0-9a-f]+|[0-9]+);|&(?:amp|quot|apos|lt|gt);',
                 story.simple_explanation + story.why_it_matters, re.IGNORECASE):
        issues.append('model prose contains an undecoded HTML entity')
    if re.search(r'\b(?:rss preview|feed excerpt|article text was unavailable)\b',
                 story.why_it_matters, re.IGNORECASE):
        issues.append('why-it-matters contains feed-processing commentary')
    if re.search(r'https?://|\[[^\]]+\]\([^)]*\)',
                 story.simple_explanation + story.why_it_matters,
                 re.IGNORECASE):
        issues.append('model prose contains an unapproved link')
    return issues


def check_digest(digest: Digest) -> list[str]:
    """Return story-specific editorial issues for a complete draft digest."""
    issues = [f'{story.id}: {issue}' for story in digest.stories
              for issue in check_story(story)]
    issues.extend(f'{story.id}: AI for Good belongs in the separate feature'
                  for story in digest.stories if not is_main_news_item(story))
    return issues
