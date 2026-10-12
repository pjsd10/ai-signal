"""Retrieve RSS entries and turn their metadata into validated source items."""

import calendar
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from html import unescape
import re
import ssl
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import feedparser
from pydantic import ValidationError

from ai_pulse.models import SourceItem
from ai_pulse.process import classify_category, has_sufficient_ai_context


@dataclass(frozen=True)
class FeedSource:
    """An approved HTTPS feed and the publisher domains its articles may use."""

    name: str
    url: str
    article_hosts: tuple[str, ...]

    def __post_init__(self):
        """Reject a feed without HTTPS or an explicit article-domain allowlist."""
        parts = urlsplit(self.url)
        if (parts.scheme != 'https' or not parts.hostname or not self.article_hosts
                or parts.username or parts.password or parts.port not in (None, 443)):
            raise ValueError('Feed needs HTTPS and approved article domains')
        if not any(parts.hostname == host or parts.hostname.endswith('.' + host)
                   for host in self.article_hosts):
            raise ValueError('Feed host must belong to its approved publisher')


# Use only the verified publisher endpoints and their approved article domains.
FEEDS: tuple[FeedSource, ...] = (
    FeedSource('OpenAI News', 'https://openai.com/news/rss.xml', ('openai.com',)),
    FeedSource('Google DeepMind', 'https://deepmind.google/blog/rss.xml', ('deepmind.google',)),
    FeedSource('The Verge', 'https://www.theverge.com/rss/index.xml', ('theverge.com',)),
    FeedSource('Ars Technica', 'https://feeds.arstechnica.com/arstechnica/technology-lab',
               ('arstechnica.com',)),
    FeedSource('Microsoft Security Blog', 'https://www.microsoft.com/en-us/security/blog/feed/',
               ('microsoft.com',)),
    FeedSource('Microsoft Research', 'https://www.microsoft.com/en-us/research/blog/feed/',
               ('microsoft.com',)),
    FeedSource('Microsoft Official Blog', 'https://blogs.microsoft.com/feed/',
               ('microsoft.com',)),
    FeedSource('ImportAI', 'https://importai.substack.com/feed',
               ('importai.substack.com',)),
    FeedSource("Ben's Bites", 'https://www.bensbites.com/feed',
               ('bensbites.com',)),
)

TRACKING_KEYS = {'fbclid', 'gclid', 'mc_cid', 'mc_eid', 'ref', 'source'}


class NoFeedRedirect(HTTPRedirectHandler):
    """Stop a feed from silently moving to an unapproved address."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        """Return no follow-up request so redirects become visible errors."""
        return None


def read_feed(url: str, timeout: int = 12) -> bytes:
    """Read a bounded HTTPS feed using the operating system's trusted roots."""
    context = ssl.create_default_context()
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError('TLS certificate and hostname verification are required')
    opener = build_opener(NoFeedRedirect(), HTTPSHandler(context=context))
    request = Request(url, headers={'User-Agent': 'AI-Pulse/0.1 RSS reader'})
    with opener.open(request, timeout=timeout) as response:
        if response.geturl() != url:
            raise ValueError('Feed URL changed during retrieval')
        if response.status != 200:
            raise ValueError(f'Unexpected feed status: {response.status}')
        content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError('Feed exceeded the 2 MB size limit')
    return content


def canonical_url(url: str) -> str:
    """Accept HTTPS links and remove tracking tags before comparing articles."""
    parts = urlsplit(url.strip())
    if (parts.scheme.lower() != 'https' or not parts.hostname or parts.username
            or parts.password or parts.port not in (None, 443)):
        raise ValueError('Article link must use HTTPS')
    query = urlencode([
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith('utm_') and key.lower() not in TRACKING_KEYS
    ])
    path = parts.path.rstrip('/') or '/'
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ''))


def plain_text(value: str, limit: int = 800) -> str:
    """Remove feed HTML markup and keep a short text excerpt for later summarizing."""
    without_tags = re.sub(r'<[^>]*>', ' ', value or '')
    return ' '.join(unescape(without_tags).split())[:limit]


def approved_article_host(url: str, hosts: tuple[str, ...]) -> bool:
    """Allow an article only on its publisher's approved domain or subdomain."""
    hostname = urlsplit(url).hostname or ''
    return any(hostname == host or hostname.endswith('.' + host) for host in hosts)


def normalize_entry(entry, source: FeedSource) -> SourceItem | None:
    """Validate an entry's date, HTTPS link, and approved publisher domain."""
    published = entry.get('published_parsed')
    if not published:
        return None
    try:
        published_at = datetime.fromtimestamp(calendar.timegm(published), tz=timezone.utc)
        url = canonical_url(entry.get('link', ''))
        if not approved_article_host(url, source.article_hosts):
            return None
        title = plain_text(entry.get('title', ''), limit=250)
        description = plain_text(entry.get('summary', entry.get('description', '')))
        if not has_sufficient_ai_context(title, description):
            return None
        return SourceItem(
            id=sha256(url.encode('utf-8')).hexdigest()[:16],
            title=title,
            source_name=source.name,
            source_url=url,
            published_at=published_at,
            description=description,
            category=classify_category(title, description),
        )
    except (ValueError, OverflowError, TypeError, ValidationError):
        return None


def fetch_news(feeds: tuple[FeedSource, ...] = FEEDS,
               read=read_feed) -> tuple[list[SourceItem], list[str]]:
    """Fetch each feed independently and return usable items plus safe error notes."""
    items: list[SourceItem] = []
    errors: list[str] = []
    for source in feeds:
        try:
            content = read(source.url, timeout=12)
            if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
                raise ValueError('Feed XML declarations with entities are not allowed')
            parsed = feedparser.parse(content)
            if parsed.bozo and not parsed.entries:
                raise ValueError('Invalid RSS or Atom response')
            for entry in parsed.entries[:30]:
                item = normalize_entry(entry, source)
                if item:
                    items.append(item)
        except (OSError, URLError, ValueError) as exc:
            errors.append(f'{source.name}: {type(exc).__name__}')
    return items, errors
