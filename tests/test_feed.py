"""Reading a feed, in the three dialects met on the web.

A dialect the reader missed would make a sound feed look empty, with nothing to
say why: some of the press sites serve RDF.
"""

from __future__ import annotations

import pytest

from kotogen.generators import feed

RSS2 = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>My site</title>
  <item>
    <title>First article</title>
    <link>https://example.test/1</link>
    <pubDate>Mon, 24 Aug 2026 06:00:00 +0900</pubDate>
  </item>
  <item>
    <title>Older article</title>
    <link>https://example.test/0</link>
    <pubDate>Sun, 23 Aug 2026 06:00:00 +0900</pubDate>
  </item>
</channel></rss>"""

RDF = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel><title>Impress Watch</title></channel>
  <item>
    <title>Article of the day</title>
    <link>https://example.test/rdf1</link>
    <dc:date>2026-08-24T08:20:00+09:00</dc:date>
  </item>
</rdf:RDF>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>A notebook</title>
  <entry>
    <title>A post</title>
    <link rel="edit" href="https://example.test/edit/1"/>
    <link href="https://example.test/atom1"/>
    <updated>2026-08-24T08:20:00Z</updated>
  </entry>
</feed>"""


@pytest.mark.parametrize("data, name, link", [
    (RSS2, "My site", "https://example.test/1"),
    (RDF, "Impress Watch", "https://example.test/rdf1"),
    (ATOM, "A notebook", "https://example.test/atom1"),
])
def test_the_three_dialects_give_the_same_thing(data, name, link):
    title, items = feed.read(data)
    assert title == name
    assert items[0].link == link
    assert items[0].title


def test_the_atom_link_is_the_one_that_reads():
    """Of an Atom entry's links, the article is "alternate", also the default."""
    _, items = feed.read(ATOM)
    assert items[0].link == "https://example.test/atom1"


def test_from_the_most_recent_to_the_oldest():
    _, items = feed.read(RSS2)
    assert [item.title for item in items] == ["First article", "Older article"]


def test_the_feed_order_is_kept_when_a_date_is_missing():
    """Sorting on half-absent dates would do far worse than not sorting."""
    undated = RSS2.replace(b"<pubDate>Mon, 24 Aug 2026 06:00:00 +0900</pubDate>", b"")
    _, items = feed.read(undated)
    assert [item.title for item in items] == ["First article", "Older article"]


def test_incomparable_dates_do_not_fail_the_reading():
    """One date has a timezone and the other not: Python cannot compare them."""
    mixed = RSS2.replace(b"Sun, 23 Aug 2026 06:00:00 +0900", b"Sun, 23 Aug 2026 06:00:00")
    _, items = feed.read(mixed)
    assert len(items) == 2


def test_an_xml_that_is_not_a_feed_gives_an_empty_list():
    """The caller says what that means ("no audio episode", "no article")."""
    name, items = feed.read(b"<html><body><h1>A site</h1></body></html>")
    assert items == []


def test_a_broken_xml_names_its_feed():
    with pytest.raises(ValueError, match="unreadable RSS feed: https://example.test/rss"):
        feed.read(b"<rss><channel", "https://example.test/rss")


@pytest.mark.parametrize("written", [
    "Mon, 24 Aug 2026 06:00:00 +0900",   # RFC 822, the RSS one
    "2026-08-24T08:20:00+09:00",         # ISO 8601, the RDF one
    "2026-08-24T08:20:00Z",              # ISO 8601 with a Z, the Atom one
])
def test_the_dates_of_the_three_dialects_read(written):
    assert feed.when(written) is not None


@pytest.mark.parametrize("written", ["", "yesterday", "24 August"])
def test_an_unreadable_date_counts_as_no_date(written):
    assert feed.when(written) is None
