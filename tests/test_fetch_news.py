from pathlib import Path
from time import gmtime

from feedparser import FeedParserDict

from ai_pulse.fetch_news import FeedSource, NoFeedRedirect, canonical_url, fetch_news, normalize_entry


FIXTURE = Path(__file__).parent / 'fixtures' / 'rss_sample.xml'


def fake_read(url, timeout):
    """Fail one source while returning fixture bytes from the other."""
    if 'broken' in url:
        raise OSError('offline test failure')
    return FIXTURE.read_bytes()


def test_one_failed_feed_does_not_block_another():
    """Working feeds should still supply items when a different feed fails."""
    feeds = (
        FeedSource('Broken', 'https://broken.example/feed', ('broken.example',)),
        FeedSource('Fixture', 'https://example.com/feed', ('example.com',)),
    )
    items, errors = fetch_news(feeds=feeds, read=fake_read)
    assert len(items) == 2
    assert len(errors) == 1
    assert errors[0].startswith('Broken:')
    assert all(item.source_name == 'Fixture' for item in items)


def test_tracking_removed_and_unsafe_link_rejected():
    """Tracking tags should disappear and script URLs should be refused."""
    assert canonical_url('https://example.com/a?utm_source=x&id=1#part') == 'https://example.com/a?id=1'
    for unsafe_link in ('http://example.com/insecure',
                        'https://user:secret@example.com/story',
                        'https://example.com:8443/story'):
        try:
            canonical_url(unsafe_link)
        except ValueError:
            pass
        else:
            raise AssertionError('Unsafe link was accepted')


def test_unapproved_article_domain_is_skipped():
    """A feed cannot insert a clickable link to an unapproved domain."""
    source = FeedSource('Fixture', 'https://trusted.example/feed', ('trusted.example',))
    items, errors = fetch_news(feeds=(source,), read=fake_read)
    assert items == []
    assert errors == []


def test_broad_feed_does_not_admit_unrelated_security_news():
    """A technology feed's security story needs explicit AI evidence to qualify."""
    source = FeedSource('Broad Feed', 'https://example.com/feed', ('example.com',))
    entry = FeedParserDict(title='Patch fixes a browser vulnerability',
                           summary='An update for web browsers.',
                           link='https://example.com/patch',
                           published_parsed=gmtime(1791633600))
    assert normalize_entry(entry, source) is None


def test_generic_headline_needs_substantial_ai_context():
    """A vague headline and tiny AI mention do not make a useful news card."""
    source = FeedSource('Broad Feed', 'https://example.com/feed', ('example.com',))
    entry = FeedParserDict(title='Text is so 2023', summary='An AI wife, maybe.',
                           link='https://example.com/vague',
                           published_parsed=gmtime(1791633600))
    assert normalize_entry(entry, source) is None


def test_updated_time_cannot_replace_missing_publication_date():
    """An update timestamp alone cannot prove when an article was published."""
    source = FeedSource('Fixture', 'https://example.com/feed', ('example.com',))
    entry = FeedParserDict(title='AI model updated', summary='New AI model news.',
                           link='https://example.com/model',
                           updated_parsed=gmtime(1791633600))
    assert normalize_entry(entry, source) is None


def test_feed_host_must_match_approved_publisher():
    """A feed address on another domain cannot impersonate an approved source."""
    try:
        FeedSource('Impostor', 'https://other.example/feed', ('trusted.example',))
    except ValueError:
        pass
    else:
        raise AssertionError('Unapproved feed host was accepted')


def test_feed_redirect_is_never_followed():
    """A publisher redirect must not silently contact a different endpoint."""
    handler = NoFeedRedirect()
    assert handler.redirect_request(None, None, 302, 'Moved', {},
                                    'https://other.example/feed') is None


def test_entity_declaration_is_rejected_before_xml_parsing():
    """Potentially dangerous XML entities never reach the feed parser."""
    source = FeedSource('Fixture', 'https://example.com/feed', ('example.com',))

    def fake_entity_feed(url, timeout):
        """Supply a tiny RSS document containing an external entity."""
        return b'<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///secret">]><rss/>'

    items, errors = fetch_news(feeds=(source,), read=fake_entity_feed)
    assert items == []
    assert errors == ['Fixture: ValueError']
