"""Tests of the `kotogen audio nhk` mode: discovering the latest articles and
the deduplication history (pure logic, no browser and no network)."""

from pathlib import Path

import pytest

from kotogen import i18n, seen
from kotogen.generators import nhk

# -- _latest_entries ----------------------------------------------------------

def test_latest_entries_sorted_by_time_desc():
    payloads = [{
        "channel": {"item": [
            {"news_id": "ne2026071001", "news_prearranged_time": "2026-07-10 17:00:00",
             "title": "Older"},
            {"news_id": "ne2026071201", "news_prearranged_time": "2026-07-12 11:30:00",
             "title": "Newer"},
        ]}
    }]
    entries = nhk._latest_entries(payloads, [])
    assert [i for i, _ in entries] == ["ne2026071201", "ne2026071001"]


def test_latest_entries_strips_ruby_from_title():
    payloads = [{"news_id": "ne2026071201",
                 "news_prearranged_time": "2026-07-12 11:30:00",
                 "title": "<ruby>新<rt>あたら</rt></ruby>しいニュース"}]
    entries = nhk._latest_entries(payloads, [])
    assert entries == [("ne2026071201", "新しいニュース")]


def test_latest_entries_falls_back_to_dom_links():
    hrefs = [
        "/news/easy/list/",                          # not an article
        "/news/easy/ne2026071201/ne2026071201.html",
        "/news/easy/ne2026071105/ne2026071105.html",
        "/news/easy/ne2026071201/ne2026071201.html", # duplicate -> ignored
    ]
    entries = nhk._latest_entries([], hrefs)
    assert [i for i, _ in entries] == ["ne2026071201", "ne2026071105"]


def test_latest_entries_ignores_non_article_ids():
    payloads = [{"news_id": "not-an-id"}, {"news_id": "ne2026071201"}]
    entries = nhk._latest_entries(payloads, [])
    assert [i for i, _ in entries] == ["ne2026071201"]


# -- History (seen) -----------------------------------------------------------
# The storage itself is tested in test_seen.py: here, only what NHK makes of it -
# reading the news_id out of the URL and filing under its own source.

ART_URL = "https://news.web.nhk/news/easy/ne2026071201/ne2026071201.html"


@pytest.fixture
def history(tmp_path, monkeypatch):
    """An empty, throwaway history, never the machine's."""
    monkeypatch.setattr(seen, "FILE", tmp_path / "seen.json")


def test_mark_seen_roundtrip(history):
    assert nhk.load_seen("audio") == {}
    nhk.mark_seen(ART_URL, "Title", mode="audio")
    assert nhk.load_seen("audio") == {"ne2026071201": "Title"}
    # written again with no title: the existing title is kept
    nhk.mark_seen(ART_URL, mode="audio")
    assert nhk.load_seen("audio") == {"ne2026071201": "Title"}


def test_mark_seen_is_namespaced_by_mode(history):
    # An article done in audio stays available for vocabulary, and so on.
    nhk.mark_seen(ART_URL, "Title", mode="audio")
    assert nhk.load_seen("vocab") == {}
    nhk.mark_seen(ART_URL, "Title", mode="vocab")
    assert nhk.load_seen("audio") == nhk.load_seen("vocab") == {"ne2026071201": "Title"}


def test_mark_seen_lands_under_the_nhk_source(history):
    # A podcast numbering its episodes the way NHK does must not think itself
    # already done, and the other way round.
    nhk.mark_seen(ART_URL, "Title", mode="audio")
    assert seen.load("audio", "nhk") == {"ne2026071201": "Title"}
    assert seen.load("audio", "teppei") == {}


def test_mark_seen_ignores_url_without_article_id(history):
    nhk.mark_seen("https://news.web.nhk/news/easy/list/")
    assert nhk.load_seen("audio") == {}


# -- The deck, a second memory ------------------------------------------------
# The local history only knows this machine. The deck is synchronised: that is
# what stops a fresh machine paying again for what the other one already did.

def test_an_article_already_in_the_deck_is_skipped(monkeypatch, history, capsys):
    """With no line of local history: it is the card, in Anki, that says so."""
    from kotogen import memory
    from kotogen.known import Sources as DeckSources

    monkeypatch.setattr(nhk, "_list_attempt", lambda headless=True: ([], []))
    monkeypatch.setattr(nhk, "_latest_entries",
                        lambda payloads, hrefs: [("ne2026071201", "One"),
                                                 ("ne2026071202", "Two")])
    # The card carries the site's old domain: the article is still recognised, its
    # news_id being looked for anywhere in the provenance.
    monkeypatch.setattr(memory.known(), "_sources", DeckSources({
        "audio": frozenset({"https://www3.nhk.or.jp/news/easy/ne2026071201/"
                            "ne2026071201.html"})}))
    urls = nhk.fetch_latest_urls(2, mode="audio")
    assert [nhk.article_id(url) for url in urls] == ["ne2026071202"]
    # And not in reading: the deck partitions by mode, just like the file.
    assert len(nhk.fetch_latest_urls(2, mode="reading")) == 2
    capsys.readouterr()


# -- collect_urls -------------------------------------------------------------

def test_collect_urls_passes_explicit_urls_through(monkeypatch):
    # No 'nhk' keyword -> no network call, the URLs go through as they are.
    monkeypatch.setattr(nhk, "fetch_latest_urls", lambda *a, **k: pytest.fail("network"))
    assert nhk.collect_urls([ART_URL], latest=4, mode="vocab") == [ART_URL]


def test_collect_urls_merges_latest_without_duplicates(monkeypatch):
    other = "https://news.web.nhk/news/easy/ne2026071105/ne2026071105.html"
    monkeypatch.setattr(nhk, "fetch_latest_urls", lambda count, mode: [ART_URL, other])
    urls = nhk.collect_urls(["nhk", ART_URL], latest=2, mode="grammar")
    assert urls == [ART_URL, other]  # ART_URL not duplicated


# -- _launch ------------------------------------------------------------------

class _FakeChromium:
    def __init__(self, exc):
        self._exc = exc

    def launch_persistent_context(self, *a, **k):
        raise self._exc


class _FakePlaywright:
    def __init__(self, exc):
        self.chromium = _FakeChromium(exc)


def test_a_missing_browser_fits_on_one_line():
    """Playwright answers with a ten-line framed slab: we keep one line of it."""
    exc = RuntimeError(
        "BrowserType.launch_persistent_context: Executable doesn't exist at "
        "chrome-headless-shell.exe\n"
        "+---------------------------------------------+\n"
        "| Looks like Playwright was just installed... |\n"
        "+---------------------------------------------+")
    with pytest.raises(SystemExit) as info:
        nhk._launch(_FakePlaywright(exc), headless=True)
    message = str(info.value)
    assert message.count("\n") == 0
    assert "playwright install" in message


def test_the_other_browser_breakdowns_come_back_as_they_are():
    exc = RuntimeError("Timeout 30000ms exceeded")
    with pytest.raises(RuntimeError, match="Timeout"):
        nhk._launch(_FakePlaywright(exc), headless=True)


# -- _open_list: the list page stuck on `読みこみ中…` --------------------------

class _FakePage:
    """A fake NHK page that serves `news-list.json` only on the n-th load.

    As on the site, where a session's first load can leave the SPA on its loading
    indicator, never asking for the list nor showing the consent screen.
    """

    def __init__(self, loads_at: int, consent: bool = False):
        self.loads_at = loads_at
        self.consent = consent
        self.loads = 0
        self.reloads = 0
        self.consents = 0
        self.waited_ms = 0

    def _load(self):
        self.loads += 1

    def goto(self, url, **kw):
        self.url = url
        self._load()

    def reload(self, **kw):
        self.reloads += 1
        self._load()

    def list_loaded(self):
        return self.loads >= self.loads_at

    def wait_for_timeout(self, ms):
        self.waited_ms += ms

    def wait_for_load_state(self, *a, **kw):
        pass


def _open(page):
    """Calls `_open_list` with the consent neutralised (no network)."""
    import kotogen.generators.nhk as module
    original = module._try_consent
    module._try_consent = lambda p: (setattr(p, "consents", p.consents + 1)
                                     or p.consent)
    try:
        return module._open_list(page, page.list_loaded)
    finally:
        module._try_consent = original


def test_open_list_reloads_when_the_list_does_not_come():
    """The reload is the "refresh" one would otherwise do by hand."""
    page = _FakePage(loads_at=2)
    assert _open(page) is True
    assert page.reloads == 1
    assert page.url == nhk.EASY_LIST_URL


def test_open_list_does_not_reload_a_list_that_arrives_first_time():
    page = _FakePage(loads_at=1)
    assert _open(page) is True
    assert page.reloads == 0


def test_open_list_gives_up_after_a_few_tries():
    """The list never served: we hand back rather than reload forever."""
    page = _FakePage(loads_at=99)
    assert _open(page) is False
    assert page.loads == nhk.LIST_TRIES
    assert page.consents == nhk.LIST_TRIES   # the consent is retried every time


# -- When the article does not read ------------------------------------------

def test_an_article_that_does_not_read_says_where_to_report_it(monkeypatch, tmp_path):
    """Said to every user, not to the author: where the diagnostic is, and
    where to bring it."""
    monkeypatch.setattr(nhk.console, "while_working", lambda work, detail=None: work())
    monkeypatch.setattr(nhk, "_attempt",
                        lambda *a, **k: ("", [], None, "", ""))
    with pytest.raises(RuntimeError) as raised:
        nhk.fetch_article("https://news.web.nhk/news/easy/ne1/ne1.html",
                          headed=True, dump=tmp_path)
    said = str(raised.value)
    assert str(tmp_path) in said and nhk.ISSUES in said
    assert "Send me" not in said


def test_the_address_to_report_to_is_the_one_of_the_project():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8")
    assert f'Issues = "{nhk.ISSUES}"' in pyproject


@pytest.mark.parametrize("url", [
    "https://evil.example/?next=https://news.web.nhk/news/easy/ne1.html",
    "https://news.web.nhk.evil.example/news/easy/ne1.html",
    "https://notnhk.or.jp/news/easy/ne1.html",
    # urllib reads the host after the "@", Chromium takes the backslash for a "/".
    "https://evil.example\\@news.web.nhk/news/easy/ne1.html",
    "https://user@news.web.nhk/news/easy/ne1.html",
])
def test_an_address_that_only_mentions_the_site_is_not_the_site(url):
    """The host is compared, not searched for in the whole address."""
    assert not nhk.is_nhk_url(url)


def test_the_old_host_of_the_site_is_still_recognised():
    assert nhk.is_nhk_url("https://www3.nhk.or.jp/news/easy/k10014321000/k10014321000.html")


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_table_says_the_visible_window(lang):
    """Held in a constant and translated where it is said: the scan of the
    literals does not see it."""
    assert nhk.VISIBLE_WINDOW in i18n._load(lang)
