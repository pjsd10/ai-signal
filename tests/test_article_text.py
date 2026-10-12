"""Offline checks for bounded publisher article reading and provenance."""

from datetime import datetime, timezone
from email.message import Message

import pytest

from ai_pulse.article_text import MAX_HTML_BYTES, extract_article_text, read_article
from ai_pulse.models import SourceItem
from ai_pulse.summarize import SummaryBatch, SummaryItem, build_prompt, digest_from_batch


def item(url: str = 'https://openai.com/news/example') -> SourceItem:
    """Make a selected-publisher story without contacting the network."""
    return SourceItem(id='a', title='AI article', source_name='OpenAI News',
                      source_url=url, published_at=datetime.now(timezone.utc),
                      description='Short feed preview […]')


def test_article_parser_ignores_scripts_and_navigation():
    """Only substantial visible paragraphs inside article reach the model."""
    html = ('<nav><p>Navigation text that should not appear anywhere.</p></nav>'
            '<article><script>alert("bad")</script><p>This is a substantial '
            'first paragraph about what the publisher reported in its story.</p>'
            '<p>This is a substantial second paragraph about the likely effect '
            'for people using the product.</p></article>')
    with pytest.raises(ValueError):
        extract_article_text(html)
    html += '<article><p>' + ('A verified fact from the approved article. ' * 10) + '</p></article>'
    text = extract_article_text(html)
    assert 'verified fact' in text
    assert 'Navigation' not in text
    assert 'alert' not in text


def test_unapproved_article_link_is_rejected_before_request():
    """A forged source URL cannot lead the reader to another host."""
    with pytest.raises(ValueError, match='approved'):
        read_article(item('https://evil.example/story'))


def test_article_reader_rejects_redirected_and_oversized_responses():
    """A changed URL or large response never becomes model input."""
    class FakeResponse:
        """Simulate an HTTP response without making a request."""

        status = 200

        def __init__(self, url: str, body: bytes):
            """Store the response address and bytes."""
            self.url, self.body = url, body
            self.headers = Message()
            self.headers['Content-Type'] = 'text/html; charset=utf-8'

        def __enter__(self):
            """Allow the response to be used in a context manager."""
            return self

        def __exit__(self, *_args):
            """Finish the fake response without suppressing errors."""
            return False

        def geturl(self):
            """Return the response's final URL."""
            return self.url

        def read(self, _limit):
            """Return the fake response body."""
            return self.body

    class FakeOpener:
        """Return the configured response from open."""

        def __init__(self, response):
            """Keep the chosen response for the request."""
            self.response = response
            self.requested_url = None

        def open(self, request, timeout):
            """Provide a response without a network connection."""
            self.requested_url = request.full_url
            return self.response

    with pytest.raises(ValueError, match='changed URL'):
        read_article(item(), opener=FakeOpener(FakeResponse('https://evil.example/', b'')))
    with pytest.raises(ValueError, match='2 MB'):
        read_article(item(), opener=FakeOpener(FakeResponse(
            'https://openai.com/news/example', b'X' * (MAX_HTML_BYTES + 1))))
    slash_opener = FakeOpener(FakeResponse('https://openai.com/index/example/', b''))
    with pytest.raises(ValueError, match='No substantial'):
        read_article(item('https://openai.com/index/example'), opener=slash_opener)
    assert slash_opener.requested_url == 'https://openai.com/index/example/'


def test_summary_basis_follows_article_evidence():
    """A saved takeaway identifies whether the model saw article text."""
    source = item().model_copy(update={'article_text': 'This approved article describes a new tool.'})
    assert 'This approved article' in build_prompt([source])
    batch = SummaryBatch(stories=[SummaryItem(
        id='a', simple_explanation='The company described a new tool.',
        why_it_matters='Readers can understand the reported use.')])
    digest = digest_from_batch([source], batch)
    assert digest.stories[0].summary_basis == 'article_text'
    assert source.article_text not in digest.model_dump_json()
