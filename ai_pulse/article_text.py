"""Read text only from selected publisher articles over verified HTTPS."""

from html.parser import HTMLParser
import ssl
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPSHandler, Request, build_opener

from ai_pulse.fetch_news import FEEDS, NoFeedRedirect, approved_article_host, canonical_url
from ai_pulse.models import SourceItem


MAX_HTML_BYTES = 2_000_000
MAX_MODEL_CHARS = 12_000
SKIP_TAGS = {'script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'svg'}


class ArticleParser(HTMLParser):
    """Keep paragraph text inside a specified publisher content element."""

    def __init__(self, root_tag: str) -> None:
        """Start with no content, paragraph, or skipped-element context."""
        super().__init__(convert_charrefs=True)
        self.root_tag = root_tag
        self.article_depth = 0
        self.skip_depth = 0
        self.paragraph_depth = 0
        self.current: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Track article paragraphs while ignoring navigation and executable text."""
        if tag == self.root_tag:
            self.article_depth += 1
        elif self.article_depth:
            if tag in SKIP_TAGS or self.skip_depth:
                self.skip_depth += 1
            elif tag == 'p':
                self.paragraph_depth += 1

    def handle_endtag(self, tag: str) -> None:
        """Finish a paragraph and leave ignored or article elements."""
        if tag == self.root_tag and self.article_depth:
            self.article_depth -= 1
        elif self.article_depth and self.skip_depth:
            self.skip_depth -= 1
        elif self.article_depth and tag == 'p' and self.paragraph_depth:
            self.paragraph_depth -= 1
            if not self.paragraph_depth:
                paragraph = ' '.join(''.join(self.current).split())
                if len(paragraph) >= 35:
                    self.paragraphs.append(paragraph)
                self.current = []

    def handle_data(self, data: str) -> None:
        """Collect visible text only while inside an article paragraph."""
        if self.article_depth and self.paragraph_depth and not self.skip_depth:
            self.current.append(data)


def extract_article_text(html: str) -> str:
    """Return useful article paragraphs or fail when a page has no article body."""
    parser = ArticleParser('article')
    parser.feed(html)
    text = '\n\n'.join(parser.paragraphs)
    if len(text) < 300:
        parser = ArticleParser('main')
        parser.feed(html)
        text = '\n\n'.join(parser.paragraphs)
    if len(text) < 300:
        raise ValueError('No substantial article body was available')
    return text[:MAX_MODEL_CHARS]


def read_article(item: SourceItem, timeout: int = 12, opener=None) -> str:
    """Fetch bounded HTML only from the item's approved publisher host."""
    source = next((source for source in FEEDS if source.name == item.source_name), None)
    url = str(item.source_url)
    if source is None or canonical_url(url) != url or not approved_article_host(url, source.article_hosts):
        raise ValueError('Article URL is not approved for this publisher')
    parts = urlsplit(url)
    if parts.fragment:
        raise ValueError('Article URL cannot contain a fragment')
    request_url = url
    if (source.name == 'OpenAI News' and parts.hostname == 'openai.com'
            and parts.path.startswith('/index/') and not parts.path.endswith('/')):
        request_url = urlunsplit((parts.scheme, parts.netloc, parts.path + '/',
                                  parts.query, ''))
    context = ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError('TLS certificate and hostname verification are required')
    if opener is None:
        opener = build_opener(NoFeedRedirect(), HTTPSHandler(context=context))
    request = Request(request_url, headers={'User-Agent': 'AI-Pulse/0.1 article reader',
                                    'Accept': 'text/html,application/xhtml+xml'})
    with opener.open(request, timeout=timeout) as response:
        if response.geturl() != request_url or response.status != 200:
            raise ValueError('Article request changed URL or did not succeed')
        content_type = response.headers.get_content_type()
        if content_type not in ('text/html', 'application/xhtml+xml'):
            raise ValueError('Article response is not HTML')
        raw = response.read(MAX_HTML_BYTES + 1)
        encoding = response.headers.get_content_charset() or 'utf-8'
    if len(raw) > MAX_HTML_BYTES:
        raise ValueError('Article exceeded the 2 MB size limit')
    return extract_article_text(raw.decode(encoding, errors='replace'))


def enrich_articles(items: list[SourceItem]) -> tuple[list[SourceItem], list[str]]:
    """Attach readable article text in memory and report publisher failures."""
    enriched: list[SourceItem] = []
    notes: list[str] = []
    for item in items:
        try:
            enriched.append(item.model_copy(update={'article_text': read_article(item)}))
            notes.append(f'{item.source_name}: article text available')
        except (OSError, UnicodeError, ValueError, LookupError) as exc:
            enriched.append(item)
            notes.append(f'{item.source_name}: article unavailable ({type(exc).__name__}); RSS only')
    return enriched, notes
