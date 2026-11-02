"""The generic source: any URL at all, any text file at all.

Only NHK Easy goes through the browser, for its audio; everything else is read
over plain HTTP, its failures said in plain words rather than as a traceback.
"""

from __future__ import annotations

import http.client
import io
import urllib.error

import pytest

from kotogen.generators import nhk, text_source as ts

# -- Recognising the input ----------------------------------------------------

@pytest.mark.parametrize("entry, expected", [
    ("https://example.jp/page", True),
    ("http://example.jp", True),
    ("涼しい", False),
    ("nhk", False),
    ("course.pdf", False),
])
def test_a_url_is_recognised(entry, expected):
    assert ts.is_url(entry) is expected


def test_a_text_file_is_recognised(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("日本語", encoding="utf-8")
    assert ts.is_text_file(str(txt))
    assert ts.is_source(str(txt))


def test_a_pdf_keeps_its_own_route(tmp_path):
    """A PDF goes to the model in vision: it has no business here."""
    pdf = tmp_path / "course.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    assert not ts.is_text_file(str(pdf))


def test_a_file_that_does_not_exist_is_not_a_source():
    """Otherwise a misspelt word would pass for a path."""
    assert not ts.is_source("涼しい.txt")


def test_an_nhk_url_stays_nhk_business():
    """The routing order counts: NHK first, generic after."""
    url = "https://news.web.nhk/news/easy/ne2024/ne2024.html"
    assert nhk.is_nhk_url(url)
    assert not nhk.is_nhk_url("https://ja.wikipedia.org/wiki/日本語")
    assert not nhk.is_nhk_input("https://example.jp/article")
    # The domain is not enough: nhk.or.jp also serves the RSS feed of the radio
    # bulletins, which reads over plain HTTP and has no business in a browser.
    assert not nhk.is_nhk_url(
        "https://www.nhk.or.jp/s-media/news/podcast/list/v1/all.xml")


# -- Encoding the URL ---------------------------------------------------------

def test_a_japanese_url_is_encoded():
    """A path copied from the browser holds raw characters, which http.client refuses."""
    encoded = ts.encode_url("https://ja.wikipedia.org/wiki/日本語")
    assert encoded == "https://ja.wikipedia.org/wiki/%E6%97%A5%E6%9C%AC%E8%AA%9E"
    assert encoded.isascii()


def test_a_japanese_domain_goes_to_punycode():
    assert ts.encode_url("https://日本.jp/a").startswith("https://xn--")


def test_a_url_already_encoded_stays_intact():
    url = "https://example.jp/a%20b?x=1&y=2#z"
    assert ts.encode_url(url) == url


# -- Pulling the text out -----------------------------------------------------

def responding(monkeypatch, page_body: str,
               content_type="text/html; charset=utf-8", error=None):
    def fake_open(url, timeout, headers=None):
        if error:
            raise error
        return _Response(page_body.encode("utf-8"), content_type)

    monkeypatch.setattr(ts.download, "open_url", fake_open)


@pytest.mark.parametrize("address", ["file:///C:/Users/x/notes.txt", "ftp://example.jp/a.txt"])
def test_a_page_that_is_not_on_the_web_is_refused(address):
    """A page address can come from a feed or another page: a local file or an
    ftp server is not one, and is never read."""
    with pytest.raises(RuntimeError, match="http or https"):
        ts.fetch_url(address)


class _Response(io.BytesIO):
    def __init__(self, data, content_type):
        super().__init__(data)
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


PAGE = """<html><head><title>私の日記 | My site</title>
<script>var x = "これはdu script";</script>
<style>.a { color: red }</style></head>
<body><nav><a href="/">Home</a> <a href="/x">ホーム</a></nav>
<h1>今日[きょう]の話</h1>
<p>私は毎日日本語を勉強しています。</p>
<p>Some English boilerplate about cookies and privacy.</p>
<p><ruby>吾輩<rt>わがはい</rt></ruby>は猫である。</p>
<footer>© 2026</footer></body></html>"""


def test_a_page_reduced_to_its_japanese(monkeypatch):
    responding(monkeypatch, PAGE)
    title, lines = ts.fetch("https://example.jp/a")
    assert title == "今日[きょう]の話"
    assert "私は毎日日本語を勉強しています。" in lines
    # The Japanese does the sorting on its own: no script, no menu, no footer,
    # and not the English line - with no need to know the site.
    assert not any("script" in l for l in lines)
    assert not any("English" in l for l in lines)
    assert not any("Home" in l for l in lines)


def test_the_original_ruby_is_kept(monkeypatch):
    """A site's own furigana are kept rather than regenerated."""
    responding(monkeypatch, PAGE)
    _title, lines = ts.fetch("https://example.jp/a")
    assert "吾輩[わがはい]は猫である。" in lines


def test_a_page_with_no_japanese_says_so(monkeypatch):
    responding(monkeypatch, "<html><body><p>Only English here, sorry.</p></body></html>")
    with pytest.raises(RuntimeError) as excinfo:
        ts.fetch("https://example.jp/a")
    message = str(excinfo.value)
    assert "no Japanese text" in message
    assert "JavaScript" in message      # the commonest cause is named


def test_the_text_is_bounded(monkeypatch):
    responding(monkeypatch, "<html><body>"
               + "".join(f"<p>これは{i}番目の文です。</p>" for i in range(500))
               + "</body></html>")
    _title, lines = ts.fetch("https://example.jp/a")
    assert len(lines) <= ts.MAX_LINES
    assert sum(len(l) for l in lines) <= ts.MAX_CHARS


# -- Network failures: a reason, not a traceback ------------------------------

def test_an_unreachable_site(monkeypatch):
    responding(monkeypatch, "", error=urllib.error.URLError("getaddrinfo failed"))
    with pytest.raises(RuntimeError) as excinfo:
        ts.fetch("https://does-not-exist.jp/a")
    assert "site unreachable" in str(excinfo.value)


def test_a_page_not_found(monkeypatch):
    responding(monkeypatch, "", error=urllib.error.HTTPError(
        "https://example.jp/a", 404, "Not Found", {}, None))
    with pytest.raises(RuntimeError) as excinfo:
        ts.fetch("https://example.jp/a")
    assert "HTTP 404" in str(excinfo.value)


def test_a_cut_answer_is_said_in_plain_words(monkeypatch):
    """`IncompleteRead` is no `OSError`: it would reach the screen as a traceback."""
    responding(monkeypatch, "", error=http.client.IncompleteRead(b"<html>", 2000))
    with pytest.raises(RuntimeError, match="download interrupted"):
        ts.fetch("https://example.jp/a")


def _announcing(monkeypatch, body: bytes, announced: int) -> None:
    def fake_open(url, timeout, headers=None):
        response = _Response(body, "text/html; charset=utf-8")
        response.headers["Content-Length"] = str(announced)
        return response

    monkeypatch.setattr(ts.download, "open_url", fake_open)


def test_a_page_cut_short_is_not_taken_for_the_whole_page(monkeypatch):
    """`http.client` ends the read on a closed connection without a word."""
    _announcing(monkeypatch, PAGE.encode("utf-8")[:200], len(PAGE.encode("utf-8")))
    with pytest.raises(RuntimeError, match="download interrupted"):
        ts.fetch_url("https://example.jp/a")


def test_a_page_past_the_cap_is_cut_without_complaint(monkeypatch):
    """The cut is the cap's own: the text is bounded further down anyway."""
    monkeypatch.setattr(ts, "MAX_DOWNLOAD", 100)
    _announcing(monkeypatch, PAGE.encode("utf-8"), len(PAGE.encode("utf-8")))
    html, _kind = ts.fetch_url("https://example.jp/a")
    assert len(html.encode("utf-8")) <= 100


def test_a_page_is_asked_for_under_the_name_of_kotogen(monkeypatch):
    """A page is read as a program reads it, not posing as a browser."""
    sent = {}

    def fake_open(url, timeout, headers=None):
        sent.update(headers or {})
        return _Response(PAGE.encode("utf-8"), "text/html; charset=utf-8")

    monkeypatch.setattr(ts.download, "open_url", fake_open)
    ts.fetch_url("https://example.jp/a")

    assert sent["User-Agent"] == ts.download.AGENT


def test_non_textual_content_is_refused(monkeypatch):
    responding(monkeypatch, "binary", content_type="image/png")
    with pytest.raises(RuntimeError) as excinfo:
        ts.fetch("https://example.jp/image.png")
    assert "not text" in str(excinfo.value)


# -- Local files --------------------------------------------------------------

def test_a_text_file_is_read(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("私は学生です。\n\nよろしくお願いします。\n", encoding="utf-8")
    title, lines = ts.fetch(str(path))
    assert title == "notes"
    assert lines == ["私は学生です。", "よろしくお願いします。"]


def test_a_file_in_shift_jis(tmp_path):
    """Old sites and Japanese Windows editors do not write UTF-8."""
    path = tmp_path / "old.txt"
    path.write_bytes("難しいですが、面白いです。\n".encode("cp932"))
    _title, lines = ts.fetch(str(path))
    assert lines == ["難しいですが、面白いです。"]


def test_the_bom_of_a_windows_editor_does_not_open_the_first_line(tmp_path):
    """Notepad opens a UTF-8 file on a BOM: kept, it would stick to the first
    word, and to the rule a grammar file names on that line."""
    path = tmp_path / "notes.txt"
    path.write_text("雨が降っています。\n", encoding="utf-8-sig")
    _title, lines = ts.fetch(str(path))
    assert lines == ["雨が降っています。"]
    assert ts.decode(b"\xef\xbb\xbf" + "はい".encode(), "utf-8") == "はい"


def test_a_local_html_file_is_handled_like_a_page(tmp_path):
    path = tmp_path / "page.html"
    path.write_text(PAGE, encoding="utf-8")
    title, lines = ts.fetch(str(path))
    assert title == "今日[きょう]の話"
    assert "私は毎日日本語を勉強しています。" in lines


def test_a_subtitle_is_read_cue_by_cue(tmp_path):
    """A cue broken over two lines for the width of the screen is one line of
    the text, not two halves translated apart on the back of a reading card."""
    path = tmp_path / "ep01.ja.srt"
    path.write_text("1\n00:00:01,000 --> 00:00:03,000\n今日は町へ\n野菜を買いに行くんだ\n",
                    encoding="utf-8")
    title, lines = ts.fetch(str(path))
    assert title == "ep01.ja"
    assert lines == ["今日は町へ 野菜を買いに行くんだ"]


def test_an_ass_file_gives_its_dialogue_and_not_its_markup(tmp_path):
    """The dialect of anime subtitles: the timings, style names and overrides
    must not reach the model with the dialogue."""
    path = tmp_path / "ep01.ja.ass"
    path.write_text(
        "[Script Info]\nTitle: 第1話\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname\nStyle: Default,ＭＳ ゴシック\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, "
        "MarginL, MarginR, MarginV, Effect, Text\n"
        r"Dialogue: 0,0:00:01.23,0:00:03.45,Default,,0,0,0,,"
        r"{\an8}おはようございます" "\n"
        r"Dialogue: 0,0:00:04.00,0:00:06.10,Default,,0,0,0,,"
        r"今日は町へ\N野菜を買いに行くんだ" "\n",
        encoding="utf-8")
    assert ts.is_text_file(str(path))
    _title, lines = ts.fetch(str(path))
    assert lines == ["おはようございます", "今日は町へ 野菜を買いに行くんだ"]


def test_a_file_with_no_japanese_says_so(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("nothing japanese in here\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as excinfo:
        ts.fetch(str(path))
    assert "no Japanese text" in str(excinfo.value)
    assert "empty.txt" in str(excinfo.value)


def test_a_file_not_found():
    with pytest.raises(RuntimeError) as excinfo:
        ts.fetch("/path/that/does/not/exist.txt")
    assert "not found" in str(excinfo.value)


# -- Lines --------------------------------------------------------------------

def test_repeated_lines_are_discarded():
    """Menus repeat themselves from one block to the next."""
    assert ts.to_lines("ホームページ\nホームページ\n私は学生です。") == [
        "ホームページ", "私は学生です。"]


def test_lines_that_are_too_short_are_discarded():
    assert ts.to_lines("あ\n私は学生です。") == ["私は学生です。"]

# -- The body of the page -----------------------------------------------------
# A menu of sections is Japanese too, so the rule is the Japanese outside the
# links. Its guard rails matter most: a wrong container gives back an empty page,
# and AI calls paid for nothing.

PARAGRAPH = "日本語の文章です。" * 25
OTHER = "もっと長い日本語の文章です。" * 25


def page(text: str, menu: str = "") -> str:
    menu = menu or ('<div id="nav"><a href="/a">経済</a><a href="/b">国際</a>'
                    '<a href="/c">社会</a><a href="/d">スポーツ</a></div>')
    return f"<html><body>{menu}{text}<footer>会社案内について</footer></body></html>"


def test_the_menu_of_sections_does_not_precede_the_article():
    """A menu ahead of the article would be paid for and shown on the card."""
    html = page(f"<article><h1>寿司[すし]の話[はなし]</h1><p>{PARAGRAPH}</p></article>")
    lines = ts.to_lines(ts._strip_html(html))
    # The original furigana are kept, spaced as the notation wants them.
    assert lines[0] == "寿司[すし]の 話[はなし]"
    assert not any("経済" in line for line in lines)
    assert not any("会社案内" in line for line in lines)


def test_the_body_is_the_smallest_container_carrying_the_text():
    """Without this rule, <body> would always win: it holds everything."""
    html = page(f"<div id=\"page\"><div id=\"content\"><p>{PARAGRAPH}</p>"
                f"<p>{OTHER}</p></div></div>")
    kept = ts.body(ts._flatten_tags(html))
    assert "経済" not in kept
    assert PARAGRAPH[:20] in kept and OTHER[:20] in kept


def test_link_text_does_not_count_towards_an_article():
    """A menu is made of links, an article is not."""
    links = "".join(f'<a href="/{n}">とても長い日本語のリンクの名前です{n}</a>'
                    for n in range(40))
    html = page(f"<article><p>{PARAGRAPH}</p></article>", menu=f"<div>{links}</div>")
    lines = ts.to_lines(ts._strip_html(html))
    assert not any("リンクの名前" in line for line in lines)


def test_a_page_with_no_body_standing_out_is_taken_whole():
    """A table of contents, a home page: with no article, keeping everything is
    better than picking a block at random and giving back an empty page."""
    html = page("<div><p>短い。</p></div>")
    assert ts.body(ts._flatten_tags(html)) == ts._flatten_tags(html)


def test_an_unreadable_page_gets_through_without_raising():
    """Broken HTML is common: what cannot be parsed passes as it is."""
    broken = "<div><p>" + PARAGRAPH + "</div></span></p></article>"
    assert ts.body(broken)


def test_a_tag_written_over_several_lines_does_not_leak_into_the_text():
    """A tag cut by a line break must still be recognised, or its attributes
    end up in the text: `aria-label` at the head of an article."""
    html = ('<button\n  aria-label="メニューを開閉する"\n  class="b">押す</button>'
            f"<article><p>{PARAGRAPH}</p></article>")
    lines = ts.to_lines(ts._strip_html(html))
    assert not any("aria-label" in line for line in lines)
    assert not any("メニューを開閉" in line for line in lines)


def test_the_text_of_an_article_stays_whole():
    """Cleaning must cost no content: lost sentences would go unnoticed."""
    html = page(f"<article><p>{PARAGRAPH}</p><p>{OTHER}</p></article>")
    text = "".join(ts.to_lines(ts._strip_html(html)))
    assert PARAGRAPH in text and OTHER in text
