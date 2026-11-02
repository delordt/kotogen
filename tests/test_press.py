"""The press catalogue: the table, its user file, and the reading of a feed.

Nothing goes out on the network. Checked: the order of the genres, and a feed
that fails saying why rather than handing the menu an empty list.
"""

from __future__ import annotations

import http.client
import json

import pytest

from kotogen.generators import download, press

# -- The table ----------------------------------------------------------------

def test_every_site_carries_a_feed_and_a_known_genre():
    """A genre off the list would go to the end of the menu unnoticed."""
    for alias, site in press.SITES.items():
        assert site.url.startswith("https://"), alias
        assert site.name, alias
        assert site.genre in press.GENRES, alias


def test_the_genres_go_from_the_general_to_the_specialised():
    genres = [genre for genre, _sites in press.by_genre()]
    assert genres == [g for g in press.GENRES if g in genres]


def test_an_unknown_genre_goes_to_the_end_instead_of_disappearing():
    """The user's file is allowed to invent a genre."""
    known = dict(press.SITES)
    known["manga"] = press.Site("A site", "https://example.test/rss", "Manga")
    assert [genre for genre, _sites in press.by_genre(known)][-1] == "Manga"


# -- The user's file ----------------------------------------------------------

def _write(monkeypatch, tmp_path, content) -> None:
    path = tmp_path / "press.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(press, "catalogue_file", lambda: path)


def test_the_file_adds_a_site(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, {"asahi": {"name": "朝日",
                                             "url": "https://asahi.test/rss",
                                             "genre": "News"}})
    known = press.catalogue()
    assert known["asahi"].name == "朝日"
    assert len(known) == len(press.SITES) + 1


def test_the_file_fixes_a_feed_that_changed_address(monkeypatch, tmp_path):
    """The override repairs an address without waiting for a release."""
    _write(monkeypatch, tmp_path, {"jiji": {"url": "https://jiji.test/new.rdf"}})
    assert press.catalogue()["jiji"].url == "https://jiji.test/new.rdf"


def test_a_file_saved_with_a_bom_is_read(monkeypatch, tmp_path):
    """A BOM, as Notepad and PowerShell 5 write it, would lose the whole file."""
    path = tmp_path / "press.json"
    path.write_text(json.dumps({"asahi": {"url": "https://asahi.test/rss"}}),
                    encoding="utf-8-sig")
    monkeypatch.setattr(press, "catalogue_file", lambda: path)
    assert "asahi" in press.catalogue()


def test_an_unreadable_file_leaves_the_table_intact(monkeypatch, tmp_path):
    path = tmp_path / "press.json"
    path.write_text("{this is not JSON", encoding="utf-8")
    monkeypatch.setattr(press, "catalogue_file", lambda: path)
    assert press.catalogue() == press.SITES


def test_an_entry_with_no_address_is_ignored(monkeypatch, tmp_path):
    _write(monkeypatch, tmp_path, {"empty": {"name": "No feed"},
                                   "wrong": "not an object"})
    assert press.catalogue() == press.SITES


# -- The articles of a feed ---------------------------------------------------

FEED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>A site</title>
  <item><title>An article</title><link>https://example.test/1</link></item>
  <item><title>No link</title></item>
  <item><link>https://example.test/3</link></item>
</channel></rss>"""


class _Answer:
    """What the site sends back, read block by block as a socket gives it."""

    def __init__(self, data: bytes, endless: bool = False) -> None:
        self.data, self.endless = data, endless

    def read(self, size: int = -1) -> bytes:
        if self.endless:
            assert size > 0, "read whole, it would never return"
            return b"x" * size
        block, self.data = self.data[:size], self.data[size:]
        return block

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, data, *, endless: bool = False) -> None:
    monkeypatch.setattr(download, "open_url",
                        lambda url, timeout, headers=None: _Answer(data, endless))


def test_an_article_with_no_title_or_no_link_is_not_offered(monkeypatch):
    """The menu would show it empty, or open nothing."""
    _serve(monkeypatch, FEED)
    articles = press.articles("https://example.test/rss")
    assert [a.title for a in articles] == ["An article"]


def test_the_limit_bounds_what_is_offered(monkeypatch):
    _serve(monkeypatch, FEED)
    assert len(press.articles("https://example.test/rss", 1)) == 1


def test_an_article_off_the_web_is_not_offered(monkeypatch):
    """The feed is someone else's: a local path would be read as a file of this
    machine and sent to the model."""
    _serve(monkeypatch, b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>A site</title>
  <item><title>A scan</title><link>C:\\Users\\me\\scan.pdf</link></item>
  <item><title>A passport</title><link>passport.pdf</link></item>
  <item><title>A system file</title><link>file:///etc/passwd</link></item>
  <item><title>An article</title><link>https://example.test/1</link></item>
</channel></rss>""")
    assert [a.title for a in press.articles("https://example.test/rss")] == ["An article"]


def test_a_feed_that_never_ends_is_refused(monkeypatch):
    monkeypatch.setattr(download, "MAX_FEED", 1024)
    _serve(monkeypatch, b"", endless=True)
    with pytest.raises(RuntimeError, match="outsized answer"):
        press.articles("https://example.test/rss")


def test_a_web_page_instead_of_the_feed_says_so(monkeypatch):
    """The most likely mistake: pasting the address of the site, not of the RSS."""
    _serve(monkeypatch, b"<html><body><h1>A site</h1></body></html>")
    with pytest.raises(RuntimeError, match="no article in this feed"):
        press.articles("https://example.test/")


def test_an_unreachable_site_says_so_in_plain_words(monkeypatch):
    def cut(url, timeout, headers=None):
        raise press.urllib.error.URLError("no network")

    monkeypatch.setattr(download, "open_url", cut)
    with pytest.raises(RuntimeError, match="site unreachable"):
        press.articles("https://example.test/rss")


def test_a_broken_answer_says_so_in_plain_words(monkeypatch):
    """`IncompleteRead` and `BadStatusLine` are no `OSError`."""
    def broken(url, timeout, headers=None):
        raise http.client.BadStatusLine("garbage")

    monkeypatch.setattr(download, "open_url", broken)
    with pytest.raises(RuntimeError, match="download interrupted"):
        press.articles("https://example.test/rss")


def test_a_feed_that_moved_says_so_with_its_code(monkeypatch):
    def error(url, timeout, headers=None):
        raise press.urllib.error.HTTPError("https://example.test/rss", 404,
                                           "Not Found", {}, None)

    monkeypatch.setattr(download, "open_url", error)
    with pytest.raises(RuntimeError, match="404"):
        press.articles("https://example.test/rss")
