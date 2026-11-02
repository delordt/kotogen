"""Routing and running the text sources, shared by the generators.

An input goes into one route only, an unreadable text does not take the
following ones with it, a definitive failure stops everything, and an NHK
article is remembered as handled only if it gave cards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kotogen import console, i18n
from kotogen.ai_client import AIAuthError
from kotogen.generators import sources

# ── Recognising the inputs ───────────────────────────────────────────────────

def test_each_input_goes_into_one_route_and_one_only(tmp_path):
    pdf = tmp_path / "course.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    txt = tmp_path / "chapter.txt"
    txt.write_text("日本語", encoding="utf-8")

    routes = sources.split([
        str(pdf), "nhk", "https://news.web.nhk/news/easy/ne2024/ne2024.html",
        "https://example.jp/article", str(txt), "涼しい",
    ])

    assert routes.pdf == [str(pdf)]
    assert routes.nhk == ["nhk", "https://news.web.nhk/news/easy/ne2024/ne2024.html"]
    assert routes.text == ["https://example.jp/article", str(txt)]
    assert routes.other == ["涼しい"]


def test_an_nhk_url_does_not_go_out_as_plain_http():
    """The order of the routing counts: the tokenised SPA would give nothing."""
    routes = sources.split(["https://news.web.nhk/news/easy/ne2024/ne2024.html"])
    assert not routes.text and len(routes.nhk) == 1


def test_a_pdf_is_recognised_before_the_text_file(tmp_path):
    """A PDF is a file: without the order, it would end up read as text."""
    pdf = tmp_path / "past-papers.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    routes = sources.split([str(pdf)])
    assert routes.pdf and not routes.text


# ── Resolution ───────────────────────────────────────────────────────────────

def _no_nhk(monkeypatch, urls=()):
    """Neutralises the browser: `collect_urls` gives back what it is told."""
    from kotogen.generators import nhk
    monkeypatch.setattr(nhk, "collect_urls", lambda inputs, latest, mode: list(urls))


def test_sources_are_resolved_in_the_order_given(monkeypatch, tmp_path):
    """Articles first, then the generic sources: `each` numbers them on one count."""
    _no_nhk(monkeypatch, ["https://news.web.nhk/news/easy/ne1/ne1.html",
                          "https://news.web.nhk/news/easy/ne2/ne2.html"])
    txt = tmp_path / "chapter.txt"
    txt.write_text("日本語", encoding="utf-8")

    resolved = sources.text_sources(["nhk", str(txt)], mode="vocab", latest=2)

    assert [s.kind for s in resolved] == ["nhk", "nhk", "text"]
    assert [s.origin for s in resolved][-1] == str(txt)


def test_a_pdf_and_a_word_are_ignored_by_the_resolution(monkeypatch, tmp_path):
    """They have their own route: `text_sources` must not pick them up."""
    _no_nhk(monkeypatch)
    pdf = tmp_path / "course.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert sources.text_sources([str(pdf), "涼しい"], mode="vocab", latest=1) == []


def test_an_unreachable_site_stops_the_command(monkeypatch):
    from kotogen.generators import nhk

    def boom(inputs, latest, mode):
        raise RuntimeError("article list not found")

    monkeypatch.setattr(nhk, "collect_urls", boom)
    with pytest.raises(SystemExit) as err:
        sources.nhk_urls(["nhk"], 2, "vocab")
    # No "NHK:" prefix: the head of the block already names the site.
    assert str(err.value) == "article list not found"


def test_a_breakdown_read_off_the_site_exits_without_its_control_characters(
        monkeypatch):
    """The reason may carry what the page held: an escape sequence would drive
    the terminal on its way to stderr."""
    from kotogen.generators import nhk

    def boom(inputs, latest, mode):
        raise RuntimeError("article list not found\x1b]0;title\x07")

    monkeypatch.setattr(nhk, "collect_urls", boom)
    with pytest.raises(SystemExit) as err:
        sources.nhk_urls(["nhk"], 2, "vocab")
    assert "\x1b" not in str(err.value) and "\x07" not in str(err.value)


def test_no_nhk_input_does_not_open_the_browser(monkeypatch):
    from kotogen.generators import nhk

    def refuse(*a, **k):
        pytest.fail("the browser must not be launched with no NHK input")

    monkeypatch.setattr(nhk, "collect_urls", refuse)
    assert sources.nhk_urls([], 2, "vocab") == []


def test_furigana_are_completed_for_the_reading_only(monkeypatch, tmp_path):
    """Asking for them for a word extraction would be paying for nothing."""
    _no_nhk(monkeypatch)
    from kotogen.generators import text_source
    monkeypatch.setattr(text_source, "fetch",
                        lambda src, **kwargs: ("題名", ["水を飲む"]))
    txt = tmp_path / "chapter.txt"
    txt.write_text("日本語", encoding="utf-8")

    raw = sources.text_sources([str(txt)], mode="vocab", latest=1)[0].fetch()
    assert raw == ("題名", ["水を飲む"])

    title, lines = sources.text_sources(
        [str(txt)], mode="reading", latest=1, furigana=True)[0].fetch()
    assert "[" in lines[0]  # 水[みず]..., completed locally by MeCab


# ── Running them ─────────────────────────────────────────────────────────────

@pytest.fixture
def no_block(monkeypatch):
    """Neutralises the announcement of the sources, which has tests of its own."""
    monkeypatch.setattr(sources, "announce", lambda sources_: None)

class FakeSource(sources.TextSource):
    """A scripted source: what it gives back, or the error it raises."""

    kind = "nhk"
    source_name = "Text sources"

    def __init__(self, name, lines=("一行",), error=None):
        super().__init__(name)
        self.lines = list(lines)
        self.error = error
        self.done = []

    def fetch(self):
        if self.error is not None:
            raise self.error
        return f"title {self.origin}", self.lines

    def summary(self, title, lines):
        return f"{title} - {len(lines)} line(s)"

    def mark_done(self, title):
        self.done.append(title)


def test_an_unreadable_source_does_not_take_the_following_ones(capsys):
    broken = FakeSource("a", error=RuntimeError("text not found"))
    sound = FakeSource("b")
    seen = []

    done = sources.each([broken, sound],
                        lambda source, title, lines: seen.append(source.origin) or True)

    assert seen == ["b"] and done == 1
    assert "text not found" in capsys.readouterr().err


def test_a_definitive_failure_stops_everything():
    """Key refused or quota spent: the next source would pay to learn it."""
    first = FakeSource("a")
    second = FakeSource("b")

    def refuse(source, title, lines):
        raise AIAuthError("key refused")

    with pytest.raises(AIAuthError):
        sources.each([first, second], refuse)
    assert not second.done


def test_an_article_is_remembered_only_if_it_gave_cards():
    """Otherwise a failure would make the article vanish from tomorrow's list."""
    fertile = FakeSource("a")
    barren = FakeSource("b")

    sources.each([fertile, barren],
                 lambda source, title, lines: source.origin == "a")

    assert fertile.done == ["title a"] and barren.done == []


def test_a_source_announces_what_it_is_about_to_run(capsys):
    """The texts are listed first, by provenance: a rank below is looked up there."""
    console.watch()
    sources.each([FakeSource("chapter.txt"), FakeSource("next.txt")],
                 lambda source, title, lines: True)
    assert capsys.readouterr().out.splitlines()[:4] == [
        "Text sources",
        "   chapter.txt",
        "   next.txt",
        "",
    ]


def test_a_source_already_introduced_does_not_announce_itself_again(capsys):
    """NHK Easy lists its articles while fetching them: a second title adds nothing."""
    console.watch()

    class NoBlock(FakeSource):
        source_name = ""

    sources.each([NoBlock("a")], lambda source, title, lines: True)
    assert capsys.readouterr().out.splitlines()[0] == "[1/1] a"


def test_each_source_runs_the_same_shape(capsys, no_block):
    """The rank names the source, then one line per action, its result in brackets."""
    console.watch()

    def generate(source, title, lines):
        console.action("Generating the cards")
        console.done("2 cards")
        return True

    sources.each([FakeSource("a", lines=["one", "two"]), FakeSource("b")], generate)
    assert capsys.readouterr().out.splitlines() == [
        "[1/2] a",
        "   Reading… (title a - 2 line(s))",
        "   Generating the cards… (2 cards)",
        "",
        "[2/2] b",
        "   Reading… (title b - 1 line(s))",
        "   Generating the cards… (2 cards)",
    ]


def test_a_reading_that_fails_says_so_under_its_rank(capsys, no_block):
    """The reason is written under the rank, marked "!!", and the next source
    still opens its own block."""
    console.watch()
    sources.each([FakeSource("https://example.jp/a", error=RuntimeError("text not found")),
                  FakeSource("https://example.jp/b")],
                 lambda source, title, lines: True)
    output = capsys.readouterr()
    lines = [l for l in output.out.splitlines() if l]
    assert lines[0] == "[1/2] https://example.jp/a"
    assert lines[1] == "   Reading…"          # opened, never completed
    assert lines[2] == "[2/2] https://example.jp/b"
    assert "text not found" in output.err


def test_one_empty_line_separates_two_sources_and_never_two(capsys, no_block):
    """One empty line between sources, whatever the generator wrote in between."""
    console.watch()

    def chatty(source, title, lines):
        console.item(f"{title} in three passages")
        return True

    sources.each([FakeSource("a"), FakeSource("b")], chatty)
    assert capsys.readouterr().out.splitlines() == [
        "[1/2] a",
        "   Reading… (title a - 1 line(s))",
        "   title a in three passages",
        "",
        "[2/2] b",
        "   Reading… (title b - 1 line(s))",
        "   title b in three passages",
    ]


def test_the_nothing_new_message_names_the_mode():
    assert "handled in vocabulary" in sources.no_news("vocabulary")
    assert "handled (" in sources.no_news()


# ── Provenance trace (the Source field of the cards) ─────────────────────────
# The type of the argument decides what is kept: a path reduces to its name (the
# rest describes the machine), a string goes through whole.

def test_a_path_reduces_to_its_file_name():
    assert sources.provenance(Path("D:/papers/JLPT/n3_choukai.mp3")) == "n3_choukai.mp3"


def test_a_url_is_kept_whole():
    """It is what will be reopened: truncated, it leads nowhere any more."""
    url = "https://news.web.nhk/news/easy/ne2026082512345/ne2026082512345.html"
    assert sources.provenance(url) == url


def test_a_free_label_goes_through_as_it_stands():
    """An episode whose title carries a slash is not a path: reducing it to its
    "file name" would cut off the start."""
    assert sources.provenance("Teppei - #123 ゲスト回 / 後半") == "Teppei - #123 ゲスト回 / 後半"


def test_the_detail_locates_the_passage_inside_its_source():
    assert sources.provenance(Path("collection.mp3"), "03:12 → 04:50") == "collection.mp3 (03:12 → 04:50)"


def test_with_no_detail_there_is_no_empty_bracket():
    assert sources.provenance(Path("collection.mp3"), "") == "collection.mp3"


def test_a_link_back_sits_behind_the_label():
    """The link goes after the label, which the back of the card makes clickable."""
    assert sources.provenance(
        "Onomappu - オノマトペ入門", "03:12 → 04:50",
        "https://youtu.be/abc12345678?t=192",
    ) == "Onomappu - オノマトペ入門 (03:12 → 04:50) https://youtu.be/abc12345678?t=192"


def test_no_double_link_when_the_provenance_is_already_the_address():
    """An NHK article need not carry its URL twice."""
    url = "https://news.web.nhk/news/easy/ne2026082512345/ne2026082512345.html"
    assert sources.provenance(url, "", url) == url


def test_with_no_link_the_provenance_does_not_change():
    """A podcast episode has nothing to reopen: the field stays what it was."""
    assert sources.provenance("Teppei - #123", "", "") == "Teppei - #123"


def test_the_provenance_of_a_text_source_follows_its_nature(tmp_path):
    """One class serves a URL, kept whole, and a local file, reduced to its name."""
    path = tmp_path / "chapter.txt"
    web = sources.GenericText("https://example.jp/reading", "title")
    local = sources.GenericText(str(path), "title")
    assert web.provenance == "https://example.jp/reading"
    assert local.provenance == "chapter.txt"


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_table_names_the_blocks_and_the_loadings_of_the_sources(lang):
    """`source_name` and `loading` are held in English and translated where
    `announce` and `each` show them. 青空文庫 is a name, shown as it stands."""
    from kotogen.generators import deck_story

    texts = [sources.TextSource("notes.txt"), sources.GenericText("notes.txt"),
             sources.GenericText("https://example.jp/a"),
             sources.NhkArticle("https://news.web.nhk/news/easy/ne1/ne1.html", "vocab"),
             sources.AozoraWork("https://www.aozora.gr.jp/a.html")]
    wanted = {text.source_name for text in texts
              if text.source_name and text.source_name != sources.AozoraWork.source_name}
    wanted |= {text.loading for text in texts} | {deck_story.DeckStory.loading}
    table = i18n._load(lang)
    assert sorted(key for key in wanted if key not in table) == []
