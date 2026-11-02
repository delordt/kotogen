"""The generic source: any web page at all, any text file at all.

Pages are read over plain HTTP, unlike NHK Easy, whose audio needs a browser.
`fetch` returns `(title, lines)` like `nhk.fetch_article_text`. It keeps the body of the
page (`body`), turns `<ruby>` into `漢字[かな]` to keep a site's furigana, and
keeps only the lines holding Japanese. It runs no JavaScript: a page built on
load gives back little, and the error says so.
"""

from __future__ import annotations

import http.client
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from kotogen import console
from kotogen.furigana import JP_RUN_RE
from kotogen.generators import download
from kotogen.i18n import _, quoted

# Enough for a press article or a short chapter, and a matter of cost: at about
# 1.5 characters per token, 8,000 characters keep an extraction under $0.02,
# where a whole encyclopedia page costs $0.08. The cut is said on screen.
MAX_LINES = 150
MAX_CHARS = 8_000

# An HTML page rarely goes past this; beyond it we are downloading something else.
MAX_DOWNLOAD = 5 * 1024 * 1024

# Extensions read as text; PDF (vision) and audio have routes of their own.
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".html", ".htm", ".xhtml",
                 ".srt", ".vtt", ".ass", ".ssa", ".csv", ".tsv", ".json", ".xml", ""}

# Encodings tried in order: a Japanese text drawn from an old site or a Japanese
# Windows editor is often Shift-JIS, not UTF-8. `utf-8-sig` reads plain UTF-8
# too, and drops the BOM Notepad writes, which would open the first line.
_ENCODINGS = ("utf-8-sig", "cp932", "euc_jp", "iso2022_jp", "cp1252")

_BLOCK_END_RE = re.compile(
    r"</(?:p|div|li|tr|h[1-6]|section|article|blockquote|figcaption|td|dd|dt)\s*>"
    r"|<br\s*/?>", re.IGNORECASE)
_DROP_RE = re.compile(
    r"<(script|style|noscript|head|nav|footer|aside|form|select)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]*>")
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


# -- Recognising the input ----------------------------------------------------

def is_url(s: str) -> bool:
    """True if the input is an http(s) URL."""
    return (s or "").strip().lower().startswith(("http://", "https://"))


def clean_path(s: str) -> Path:
    """A path stripped of the quotes a paste leaves (copy "as path")."""
    return Path((s or "").strip().strip('"').strip("'"))


def is_text_file(s: str) -> bool:
    """True if the input names a local file readable as text."""
    if not s or is_url(s):
        return False
    path = clean_path(s)
    return path.is_file() and path.suffix.lower() in TEXT_SUFFIXES


def is_source(s: str) -> bool:
    """True if the input is a generic source (any URL, or a text file)."""
    return is_url(s) or is_text_file(s)


# -- Fetching -----------------------------------------------------------------

def decode(raw: bytes, hint: str = "") -> str:
    """Decodes bytes, trying the announced encoding then the usual Japanese ones."""
    candidates = ([hint] if hint else []) + list(_ENCODINGS)
    for encoding in candidates:
        try:
            # A page announced as `utf-8` may still open on a BOM.
            return raw.decode(encoding).removeprefix("\ufeff")
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8-sig", errors="replace")


def encode_url(url: str) -> str:
    """Encodes the non-ASCII part of a URL, as a browser would.

    A pasted address carries its path in plain characters (`.../wiki/日本語`),
    which http.client refuses: the path is percent-encoded, the domain punycoded.
    """
    parts = urllib.parse.urlsplit(url.strip())
    host = parts.netloc
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            pass  # an exotic domain: left as it is, the error will speak for itself
    return urllib.parse.urlunsplit((
        parts.scheme,
        host,
        urllib.parse.quote(parts.path, safe="/%~"),
        urllib.parse.quote(parts.query, safe="=&%?+;:,"),
        urllib.parse.quote(parts.fragment, safe="%"),
    ))


def fetch_url(url: str) -> tuple[str, str]:
    """Downloads a page; returns (html, content type). Raises RuntimeError.

    With a plain message ("site unreachable", the HTTP code), never a traceback.
    """
    try:
        # The shared opener: http and https only, redirections included, since a
        # page address can come from a feed or another page.
        with download.open_url(encode_url(url), 20, download.HEADERS) as response:
            content_type = (response.headers.get("content-type") or "").lower()
            announced = int(response.headers.get("Content-Length") or 0)
            raw = response.read(MAX_DOWNLOAD)
            charset = ""
            if "charset=" in content_type:
                charset = content_type.split("charset=", 1)[1].split(";")[0].strip()
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise download.failure(exc, url) from exc
    # A page past the cap is cut on purpose: only a shorter one is cut short.
    download.check_whole(len(raw), min(announced, MAX_DOWNLOAD))

    if content_type and not any(
            kind in content_type for kind in ("text", "html", "xml", "json")):
        raise RuntimeError(
            _("this address gives back not text but {kind} - give the URL of a "
              "page, not of a file to download.")
            .format(kind=quoted(content_type.split(';')[0])))
    return decode(raw, charset), content_type


# -- Pulling the text out -----------------------------------------------------

# -- The body of the page -----------------------------------------------------
# The Japanese filter cannot tell a menu from a paragraph, so the body is found
# first, after Readability: each container is scored on the Japanese it carries
# outside links (a menu is links), and the smallest one close to the best score
# wins, since <body> holds everything. HTMLParser suffices: the page is not
# rebuilt, only a slice of its source named.

CONTAINERS = frozenset({"article", "main", "section", "div", "td", "body"})
# They close themselves: stacking them would make the stack drift.
VOID_TAGS = frozenset({"br", "hr", "img", "input", "meta", "link", "source",
                       "col", "area", "base", "embed", "track", "wbr", "param"})

# A container carrying at least this share of the best score is preferred to it
# if it is smaller: that is what makes us descend from <body> to the article.
BODY_SHARE = 0.85
# Below this best score no body stands out (a home page, a page of links), and
# the page is taken whole.
BODY_MINIMUM = 200


class _Scanner(HTMLParser):
    """Records the bounds of every container and the Japanese it carries."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        # HTMLParser gives (line, column): where each line starts makes it an offset.
        self.starts = [0]
        for line in source.split("\n")[:-1]:
            self.starts.append(self.starts[-1] + len(line) + 1)
        self.stack: list[dict] = []
        self.blocks: list[dict] = []
        self.links = 0      # nesting depth of the <a> tags

    def _offset(self) -> int:
        line, column = self.getpos()
        return self.starts[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        if tag == "a":
            self.links += 1
        elif tag in CONTAINERS:
            opening = self.source.find(">", self._offset())
            self.stack.append({"tag": tag, "start": opening + 1, "text": 0})

    def handle_endtag(self, tag):
        if tag == "a":
            self.links = max(0, self.links - 1)
            return
        if tag not in CONTAINERS:
            return
        # The containers left open inside it are dropped, so that a malformed page
        # does not shift everything after it.
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                block = self.stack.pop(i)
                del self.stack[i:]
                block["end"] = self._offset()
                self.blocks.append(block)
                return

    def handle_data(self, data):
        if self.links:
            return      # link text: that is what makes a menu
        japanese = sum(len(m.group(0)) for m in JP_RUN_RE.finditer(data))
        if japanese:
            for block in self.stack:
                block["text"] += japanese


def body(html: str) -> str:
    """The container carrying the article, or the whole page for want of better.

    Never raises: a page the scanner cannot read is returned as it is.
    """
    scanner = _Scanner(html)
    try:
        scanner.feed(html)
    except Exception:
        return html
    blocks = [b for b in scanner.blocks if "end" in b and b["end"] > b["start"]]
    if not blocks:
        return html
    best = max(b["text"] for b in blocks)
    if best < BODY_MINIMUM:
        return html
    kept = [b for b in blocks if b["text"] >= best * BODY_SHARE]
    chosen = min(kept, key=lambda b: b["end"] - b["start"])
    return html[chosen["start"]:chosen["end"]]


def _flatten_tags(html: str) -> str:
    """Every tag brought back onto one single line.

    The page is cut at line breaks, and a tag split over two lines would not be
    recognised: its attributes would pass for text (`aria-label="メニューを開閉"`).
    """
    return _TAG_RE.sub(lambda m: " ".join(m.group(0).split()), html)


def _strip_html(html: str) -> str:
    """HTML -> text, the block structure kept as line breaks.

    `<ruby>` goes through NHK's conversion, so a site's furigana are kept rather
    than regenerated by MeCab.
    """
    from kotogen.generators.nhk import ruby_html_to_furigana

    html = body(_flatten_tags(html))
    html = _DROP_RE.sub(" ", html)
    html = _BLOCK_END_RE.sub("\n", html)
    return "\n".join(ruby_html_to_furigana(part) for part in html.split("\n"))


def _title_of(html: str) -> str:
    """The title of the page: <h1> if there is one, <title> otherwise."""
    from kotogen.generators.nhk import ruby_html_to_furigana

    for pattern in (_H1_RE, _TITLE_RE):
        found = pattern.search(html)
        if found:
            title = ruby_html_to_furigana(_DROP_RE.sub(" ", found.group(1)))
            if title:
                return title.split(" | ")[0].split(" - ")[0].strip()
    return ""


def to_lines(text: str) -> list[str]:
    """Raw text -> usable lines: Japanese only, with no repetitions.

    Keeping only Japanese drops footers, cookie banners and English legal notices
    without knowing the site.
    """
    lines: list[str] = []
    previous = ""
    for raw in text.split("\n"):
        line = " ".join(raw.split()).strip()
        if len(line) < 4 or line == previous or not JP_RUN_RE.search(line):
            continue
        lines.append(line)
        previous = line
    return lines


def _cap(lines: list[str]) -> list[str]:
    """Bounds what leaves for the model, and says so.

    The bound protects the cost of vocabulary, which sends a page in one call.
    Reading pays per passage kept, and the bound would only stop it short of the
    rest of a novel (see `cursor`): it asks for `whole=True` instead.
    """
    kept: list[str] = []
    total = 0
    for line in lines[:MAX_LINES]:
        if total + len(line) > MAX_CHARS:
            break
        kept.append(line)
        total += len(line)
    if len(kept) < len(lines):
        console.aside(_("text truncated to {kept} lines out of {total} (past "
                        "that, the prompt would cost more than it brings back)")
                      .format(kept=len(kept), total=len(lines)))
    return kept


# -- Entry point --------------------------------------------------------------

def page_text(url: str, max_chars: int = MAX_CHARS) -> tuple[str, str]:
    """Reads a page for what it explains; returns (title, flat text).

    Unlike `fetch`, it keeps the lines without Japanese: a grammar entry explains
    its rule in the reader's language. Raises RuntimeError with a plain reason.
    """
    html, _type = fetch_url(url)
    text = " ".join(_strip_html(html).split())
    if not text:
        raise RuntimeError(
            _("empty page. It may be built in JavaScript (the content only "
              "exists once a browser has been over it) or reserved for "
              "subscribers."))
    return _title_of(html), text[:max_chars]


def fetch(source: str, *, whole: bool = False) -> tuple[str, list[str]]:
    """Reads a generic source; returns (title, Japanese lines).

    Raises RuntimeError with a plain reason (unreachable, unreadable, no Japanese)
    for the generator to display. `whole` skips the bound of `_cap`, for reading.
    """
    if is_url(source):
        html, _type = fetch_url(source)
        title = _title_of(html)
        lines = to_lines(_strip_html(html))
        empty_reason = _(
            "no Japanese text on this page. It may be built in JavaScript (the "
            "content only exists once a browser has been over it), reserved for "
            "subscribers, or simply not in Japanese.")
    else:
        path = clean_path(source)
        if not path.is_file():
            raise RuntimeError(_("file not found: {path}").format(path=path))
        # Imported here: `subtitles` borrows `decode` from this module.
        from kotogen.generators import subtitles

        suffix = path.suffix.lower()
        if suffix in subtitles.EXTENSIONS:
            # Read cue by cue: as lines, a cue wrapped for the screen would give
            # two half sentences, and an `.ass` its whole markup.
            text = "\n".join(cue.text for cue in subtitles.read(path))
            title = path.stem
        else:
            text = decode(path.read_bytes())
            if suffix in (".html", ".htm", ".xhtml"):
                title = _title_of(text)
                text = _strip_html(text)
            else:
                title = path.stem
        lines = to_lines(text)
        empty_reason = _(
            "no Japanese text in {name} - an empty file, one in another "
            "language, or one in a format this mode does not read (a PDF is "
            "given as it is, it has a route of its own).").format(
                name=quoted(path.name))

    if not lines:
        raise RuntimeError(empty_reason)
    return title, (lines if whole else _cap(lines))
