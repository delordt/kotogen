"""Builds a listening card from an NHK `やさしいことば` article (NEWS WEB EASY).

NHK Easy is a tokenised SPA, so a browser (Playwright/Chromium, with a persistent
profile that keeps the consent) loads the article. Its text is read with the
site's own furigana, then put through the local furigana pipeline; its audio is
copied or re-encoded (`audio_quality`). The model only translates and writes the
questions. A failed extraction leaves a diagnostic in a temporary folder.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

from kotogen import audio_quality, console, memory, prompts, seen, system, video_clip
from kotogen.ai_client import AIClient
from kotogen.exporter import short
from kotogen.furigana import fix_furigana_spacing, process_furigana, without_readings
from kotogen.generators import quota, timecodes, whisper
from kotogen.generators.audio import _post_process
from kotogen.generators.audio_split import Segment
from kotogen.generators.subtitles import JA_MARKS
from kotogen.i18n import _, counted
from kotogen.known import NO_SOURCES

# Persistent Chromium profile: the NHK consent is only asked for once.
PROFILE_DIR = Path.home() / ".kotogen" / "nhk_profile"
# The "For Users Abroad" consent sits on the list page, and an article opened
# directly in a fresh session answers 404: the list is loaded first.
EASY_LIST_URL = "https://news.web.nhk/news/easy/list/"
# At a session's first load the SPA often sticks on `読みこみ中…`, never asking
# for news-list.json; a reload unblocks it (see `_open_list`).
LIST_TRIES = 3

# Said when the page needs a visible window: one opens, and nothing is asked of
# the user in it.
VISIBLE_WINDOW = "The site wants a window: it opens once, nothing to click."

# Includes a possible query string (?token=...): it may carry an auth.
_AUDIO_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+?\.(?:m4a|mp3|aac|m3u8)(?:[?#][^\s\"'<>]*)?", re.IGNORECASE)
_ARTICLE_ID_RE = re.compile(r"(ne\d{6,}|k1\d{12})")

# NHK media token server: signs the Akamai access to the audio stream (?hdnts=...).
NHK_TOKEN_URL = "https://mediatoken.web.nhk/v1/token"

# The site's name on screen, heading its list of articles like a channel name.
SOURCE_NAME = "NHK Easy News"

# Where a page the extraction cannot read is reported: the `Issues` address of
# pyproject.toml.
ISSUES = "https://github.com/delordt/kotogen/issues"


# -- Turning ruby into Anki furigana -------------------------------------------

def ruby_html_to_furigana(html: str) -> str:
    """`<ruby>漢字<rt>かな</rt></ruby>` -> `漢字[かな]`. Drops the other tags.

    Conversion only, the readings as they are: `finalize_lines` completes them for
    NHK, and `text_source` applies its own policy to other pages.
    """
    # <rp>...</rp> = fallback parentheses, to be removed
    html = re.sub(r"<rp\b[^>]*>.*?</rp>", "", html, flags=re.IGNORECASE | re.DOTALL)
    # <ruby>BASE<rt>READING</rt></ruby> -> BASE[READING]
    html = re.sub(
        r"<ruby\b[^>]*>(.*?)<rt\b[^>]*>(.*?)</rt>\s*</ruby>",
        lambda m: f"{_strip_tags(m.group(1))}[{_strip_tags(m.group(2))}]",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = _strip_tags(html)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return fix_furigana_spacing(text)


def _strip_tags(html: str) -> str:
    import html as _h
    return _h.unescape(re.sub(r"<[^>]+>", "", html))


# -- Schema-agnostic extraction ------------------------------------------------

def _iter_strings(obj):
    """Walks every string of a JSON object, recursively."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)


def find_body_html(payloads: list) -> str:
    """The longest HTML fragment holding <ruby> tags (= the body of the article)."""
    best = ""
    for p in payloads:
        for s in _iter_strings(p):
            if "<ruby" in s.lower() and len(s) > len(best):
                best = s
    return best


def finalize_lines(title: str, lines: list[str]) -> tuple[str, list[str]]:
    """Puts the text extracted from the site through the local furigana pipeline.

    NHK's hand-written readings are kept, being right where MeCab errs (proper
    nouns, 日本[にほん]). The pipeline drops the layout spaces, reads the bare
    kanji and recomposes number + counter (`35人[さんじゅうごにん]`). Done here
    rather than at export, so that the console and the model see the card's text.
    """
    return process_furigana(title), [process_furigana(l) for l in lines]


# Sentence boundary: after 。！？!?, unless a closing mark, quote or bracket
# follows (「はい。」と 言[い]った。 is one sentence).
_SENTENCE_END_RE = re.compile(r"(?<=[。！？!?])(?![。！？!?」』）\)】])")


def split_sentences(lines: list[str]) -> list[str]:
    """Cuts lines of text back into one line per sentence.

    The listening card sets a translation under each line, which a paragraph
    would make impossible to pair up. A line with no final punctuation comes out
    unchanged.
    """
    out: list[str] = []
    for line in lines:
        for part in _SENTENCE_END_RE.split(line):
            # A furigana leading space anchors nothing at a line start.
            part = part.strip()
            if part:
                out.append(part)
    return out


def body_html_to_lines(body_html: str) -> list[str]:
    """Cuts the body into lines (by <p>/<br>/breaks) and converts the furigana."""
    # Normalise the block separators to \n
    parts = re.split(r"</p\s*>|<br\s*/?>|</div\s*>|\n", body_html, flags=re.IGNORECASE)
    lines = []
    for part in parts:
        line = ruby_html_to_furigana(part)
        if line:
            lines.append(line)
    return lines


# -- Discovering the latest articles (`kotogen audio nhk` mode) --------------

_ARTICLE_HREF_RE = re.compile(r"/news/easy/(ne\d{6,}|k1\d{12})")

# NHK's name in the shared history, which `seen` partitions by source.
SOURCE = "nhk"


def load_seen(mode: str) -> dict[str, str]:
    """Articles already done by the given mode: {news_id: title}."""
    return seen.load(mode, SOURCE)


def mark_seen(url: str, title: str = "", mode: str = "audio") -> None:
    """Remembers that an article was generated successfully (`nhk` mode dedup).

    A URL with no news_id gives an empty identifier, for which `seen.mark` keeps
    nothing.
    """
    seen.mark(mode, SOURCE, _article_id(url), title)


def _latest_entries(payloads: list, hrefs: list[str]) -> list[tuple[str, str]]:
    """Extracts [(news_id, title)] from the most recent to the oldest.

    From the dicts of news-list.json carrying a `news_id`, by descending
    `news_prearranged_time` when there is one; failing those, from the article
    links of the DOM, in display order.
    """
    order: list[str] = []          # ids in the order they were found
    times: dict[str, str] = {}
    titles: dict[str, str] = {}

    def walk(o):
        if isinstance(o, dict):
            nid = o.get("news_id")
            if isinstance(nid, str) and _ARTICLE_ID_RE.fullmatch(nid):
                if nid not in times:
                    order.append(nid)
                times[nid] = str(o.get("news_prearranged_time", "") or times.get(nid, ""))
                title = o.get("title") or o.get("news_web_easy_title") or ""
                if title:
                    # Drop the reading of the <rt>/<rp> before stripping the
                    # tags, otherwise it ends up inlined in the text (新あたらしい…).
                    clean = re.sub(r"<r[tp]\b[^>]*>.*?</r[tp]>", "", str(title),
                                   flags=re.IGNORECASE | re.DOTALL)
                    titles[nid] = _strip_tags(clean)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for p in payloads:
        walk(p)

    if not order:  # DOM fallback: display order of the list
        for href in hrefs:
            m = _ARTICLE_HREF_RE.search(href or "")
            if m and m.group(1) not in order:
                order.append(m.group(1))

    # ISO timestamps compare lexically; a stable sort -> the order of the JSON
    # settles the entries with no date.
    ids = sorted(order, key=lambda i: times.get(i, ""), reverse=True) if any(times.values()) else order
    return [(i, titles.get(i, "")) for i in ids]


# -- Browser -------------------------------------------------------------------

def _playwright():
    """`sync_playwright`, or a clean stop on the line that says what to install."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(_("Playwright missing: pip install playwright, then {hint}")
                 .format(hint=system.chromium_hint()))
    return sync_playwright


def _launch(pw, headless: bool):
    """Opens the persistent NHK profile in Chromium.

    Persistent to keep the consent (see `fetch_article`). The user agent is set
    because the site serves a degraded page to browsers it does not recognise.
    """
    try:
        return pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=headless,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        )
    except Exception as exc:
        if not system.missing_chromium(exc):
            raise
        sys.exit(_("Playwright's Chromium is missing or out of date (package "
                   "updated): {hint}").format(hint=system.chromium_hint()))


def _open_list(page, list_loaded) -> bool:
    """Opens the LIST page until the SPA really serves `news-list.json`.

    Up to `LIST_TRIES` tries, reloading while it sticks. `list_loaded` says
    whether the list has arrived; returns False if it never does.
    """
    for attempt in range(LIST_TRIES):
        if attempt:
            page.reload(wait_until="domcontentloaded", timeout=60_000)
        else:
            page.goto(EASY_LIST_URL, wait_until="domcontentloaded", timeout=60_000)
        _try_consent(page)
        for _step in range(24):      # 12 s of patience, in steps of 500 ms
            if list_loaded():
                break
            page.wait_for_timeout(500)
        if not list_loaded():
            continue                 # stuck: reload rather than wait for nothing
        # Let the SPA get its token (the /tix call) after consent, or the audio
        # player stays stuck (401): network idle, plus a margin.
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        return True
    return False


def _list_attempt(headless: bool) -> tuple[list, list[str]]:
    """Loads the LIST page and returns (captured JSON payloads, DOM hrefs)."""
    sync_playwright = _playwright()

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    api_payloads: list = []
    list_json: list[str] = []   # news-list.json served = the SPA has finished loading

    with sync_playwright() as pw:
        ctx = _launch(pw, headless)
        page = ctx.new_page()

        def on_response(resp):
            try:
                if "news-list.json" in resp.url:
                    list_json.append(resp.url)
                ct = (resp.headers or {}).get("content-type", "")
                if "json" in ct and "web.nhk" in resp.url:
                    api_payloads.append(resp.json())
            except Exception:
                pass

        page.on("response", on_response)
        _open_list(page, lambda: bool(list_json))
        try:
            hrefs = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => e.getAttribute('href'))") or []
        except Exception:
            hrefs = []
        ctx.close()

    return api_payloads, hrefs


def fetch_latest_urls(count: int, mode: str = "audio", skip_seen: bool = True) -> list[str]:
    """The URLs of the `count` latest NHK Easy articles not yet done by the given
    `mode` (audio, reading).

    Headless first, then a visible browser once if the list will not load, as in
    `fetch_article`. One action in the source's block, opened by `collect_urls`.
    """
    console.action(_("Looking for the latest articles"))
    # The SPA takes a dozen seconds to load: the line spins meanwhile.
    payloads, hrefs = console.while_working(lambda: _list_attempt(headless=True))
    entries = _latest_entries(payloads, hrefs)

    if not entries:
        # The action stays open, the second attempt being the same search, and
        # the line has no marker: nothing failed.
        console.item(_(VISIBLE_WINDOW))
        payloads, hrefs = console.while_working(lambda: _list_attempt(headless=False))
        entries = _latest_entries(payloads, hrefs)

    if not entries:
        console.close_line()
        raise RuntimeError(_(
            "list of articles not found on the NHK Easy page - try again later, "
            "or give the article URLs directly."
        ))

    already_done = load_seen(mode) if skip_seen else {}
    # The deck too, which knows what other machines did. The news_id is looked for
    # anywhere in the provenance: NHK changed domain, and older cards carry the
    # old address.
    deck = memory.known().sources() if skip_seen else NO_SOURCES
    urls: list[str] = []
    titles: list[str] = []
    skipped = 0
    for art_id, title in entries:
        if art_id in already_done or deck.knows_id(mode, art_id):
            skipped += 1
            continue
        urls.append(f"https://news.web.nhk/news/easy/{art_id}/{art_id}.html")
        titles.append(f"{art_id} - {title}" if title else art_id)
        if len(urls) >= count:
            break

    # The count skipped ends the search's line rather than taking its own.
    found = counted(len(urls),
                    "{count} new article",
                    "{count} new articles").format(count=len(urls))
    if skipped:
        found += _(", {count} already done").format(count=skipped)
    console.done(found)
    console.items(titles)
    return urls


# -- Fetching through Playwright -----------------------------------------------

def fetch_article_text(url: str) -> tuple[str, list[str]]:
    """The text alone of an article: (title, furigana lines) - no audio captured.

    Used by the vocab and reading modes, which have no need of the sound.
    """
    title, lines, _audio, _ext, _audio_url = fetch_article(
        url, headed=False, dump=None, need_audio=False)
    return title, lines


def fetch_article(url: str, headed: bool, dump: Path | None, need_audio: bool = True):
    """Loads the article. Returns (title, japanese_lines, audio_bytes|None, ext, audio_url).

    `audio_url` may be an HLS stream (.m3u8), `audio_bytes` a direct file.
    Headless first; if the text will not load, a visible browser once, which the
    profile remembers.
    """
    title, lines, audio, ext, audio_url = console.while_working(
        lambda: _attempt(url, headless=not headed, wait_ms=20_000, dump=dump,
                         need_audio=need_audio))
    if lines:
        return title, lines, audio, ext, audio_url

    if not headed:
        console.item(_(VISIBLE_WINDOW))
        diag = dump or Path(tempfile.mkdtemp(prefix="kotogen_nhk_diag_"))
        title, lines, audio, ext, audio_url = console.while_working(
            lambda: _attempt(url, headless=False, wait_ms=120_000, dump=diag,
                             need_audio=need_audio))
        if lines:
            return title, lines, audio, ext, audio_url
        dump = diag

    raise RuntimeError(_(
        "Text of the article not found: the site may have changed the way it "
        "builds its pages.\n"
        "   A diagnostic was written to: {folder}\n"
        "   To get the reading fixed, open an issue at {issues} and attach "
        "page.html, dom.json and api_payloads.json from that folder."
    ).format(folder=dump, issues=ISSUES))


def _attempt(url: str, headless: bool, wait_ms: int, dump: Path | None,
             need_audio: bool = True):
    """One browser session: (title, lines, audio_bytes|None, ext, audio_url).

    Lines and audio may be empty, for the caller to judge. With `need_audio=False`
    no media token or audio diagnostic is asked for.
    """
    sync_playwright = _playwright()

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    api_payloads: list = []
    audio_captures: list[tuple[str, bytes]] = []
    hls_urls: list[str] = []      # HLS stream URLs (easy_audio / .m3u8)
    network_log: list[str] = []   # every response (audio diagnostic)
    list_json: list[str] = []     # news-list.json served = the list page has loaded

    with sync_playwright() as pw:
        ctx = _launch(pw, headless)
        page = ctx.new_page()

        def on_response(resp):
            ct = (resp.headers or {}).get("content-type", "")
            u = resp.url
            if "news-list.json" in u:
                list_json.append(u)
            network_log.append(f"{resp.status}\t{ct}\t{u}")
            try:
                if "easy_audio" in u or ".m3u8" in u or "mpegurl" in ct:
                    hls_urls.append(u)  # signed HLS stream -> handled by ffmpeg
                elif "json" in ct and "web.nhk" in u:
                    api_payloads.append(resp.json())
                elif ("audio" in ct or "mp4" in ct or _AUDIO_URL_RE.search(u)):
                    body = resp.body()
                    if body and len(body) > 1000:  # direct progressive file
                        audio_captures.append((_ext_of(u), body))
            except Exception:
                pass

        page.on("response", on_response)

        # 1) Consent on the LIST page, or the article answers 404 and the player
        #    gets no token. Its news-list.json feeds `_find_voice_uri`.
        _open_list(page, lambda: bool(list_json))

        # 2) The article itself (the "For Users Abroad" consent may reappear here)
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        _try_consent(page)
        try:
            page.wait_for_selector("ruby", timeout=wait_ms)
        except Exception:
            pass
        # Still gated (consent button still there, no ruby) -> try once more
        if page.locator(_CONSENT_SELECTORS[0]).count() or not page.locator("ruby").count():
            # Nothing to click: stuck as on the list, which a reload clears.
            if not _try_consent(page) and not page.locator("ruby").count():
                page.reload(wait_until="domcontentloaded", timeout=60_000)
                _try_consent(page)
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
                page.wait_for_selector("ruby", timeout=10_000)
            except Exception:
                pass
        page.wait_for_timeout(2000)

        # 3) Audio: not by clicking `ニュースを聞く`, the player being nested iframes
        #    unreliable to drive (see below).

        # The body alone: the date and a banner's label (inside an <a>) are
        # paragraphs too, which the audio never speaks.
        dom = page.evaluate(
            """() => {
                const c = document.querySelector('article') || document.querySelector('main') || document.body;
                const h1 = c.querySelector('h1') || document.querySelector('h1');
                const body = c.querySelector('#js-article-body') || c;
                const src = [...body.querySelectorAll('p')].filter(
                    p => !p.closest('a') && !p.classList.contains('article-date'));
                const ps = src.filter(p => p.querySelector('ruby'));
                return {
                    title: h1 ? h1.innerHTML : '',
                    paragraphs: (ps.length ? ps : src).map(p => p.innerHTML),
                    fullHtml: body.innerHTML,
                };
            }"""
        )

        # Audio: the signed m3u8 URL, from the voiceId of the JSON and a fresh
        #   media token (Akamai hdnts).
        audio_url = _pick_audio_m3u8(hls_urls)  # best effort, if ever caught in passing
        if not audio_url and need_audio:
            voice_uri = _find_voice_uri(api_payloads, _article_id(url))
            if voice_uri:
                audio_url = _build_signed_audio_url(page, ctx, voice_uri)

        page_html = page.content()
        if dump:
            _dump(dump, page_html, dom, api_payloads, audio_url, audio_captures, network_log)

        ctx.close()

    # Japanese lines: the DOM first, falling back on the HTML body of the API payloads
    title = ruby_html_to_furigana(dom.get("title", ""))
    lines = [l for l in (ruby_html_to_furigana(p) for p in dom.get("paragraphs", [])) if l]
    if not lines:
        body_html = find_body_html(api_payloads) or dom.get("fullHtml", "")
        lines = body_html_to_lines(body_html)

    if not lines:
        return title, [], None, "", ""
    title, lines = finalize_lines(title, lines)
    # The title is not prefixed to the lines, as the audio does not read it; it
    # goes separately to the prompt and the file name.

    # Audio present = direct bytes OR a captured HLS URL
    is_hls = "m3u8" in audio_url
    if need_audio and not audio_captures and not is_hls and not dump:
        diag = Path(tempfile.mkdtemp(prefix="kotogen_nhk_audio_"))
        _dump(diag, page_html, dom, api_payloads, audio_url, [], network_log)
        console.failed(_("audio not captured automatically - diagnostic in: {folder}")
                       .format(folder=diag))

    if audio_captures:
        ext, body = audio_captures[0]
        return title, lines, body, ext, audio_url
    return title, lines, None, "", audio_url


_CONSENT_SELECTORS = (
    "button:has-text('I understand')",
    "button:has-text('確認しました')",
    "button:has-text('同意')",
)


def _try_consent(page) -> bool:
    """Clicks the `確認しました / I understand` consent BUTTON and waits for it to go.

    The <button>, not its <span>, and the screen must close: until then no token
    is issued. True if a consent was accepted.
    """
    try:
        page.wait_for_selector(", ".join(_CONSENT_SELECTORS), timeout=6000)
    except Exception:
        return False   # no consent screen: nothing to click
    for sel in _CONSENT_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=3000)
                try:
                    page.wait_for_selector(sel, state="detached", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
    return False


def _find_voice_uri(payloads: list, art_id: str) -> str:
    """Looks for the `news_easy_voice_uri` of the article in the captured JSON.

    news-list.json, loaded with the LIST page, covers every article.
    """
    def walk(o):
        if isinstance(o, dict):
            if o.get("news_id") == art_id and o.get("news_easy_voice_uri"):
                return o["news_easy_voice_uri"]
            for v in o.values():
                found = walk(v)
                if found:
                    return found
        elif isinstance(o, list):
            for v in o:
                found = walk(v)
                if found:
                    return found
        return ""

    for p in payloads:
        found = walk(p)
        if found:
            return found
    return ""


def _build_signed_audio_url(page, ctx, voice_uri: str) -> str:
    """Builds the signed m3u8 URL of the NHK audio player.

    As the player does: `<hlsurl>?hdnts=<token>`, the Akamai token coming from
    mediatoken.web.nhk on the `z_at` session cookie (as a Bearer). "" if none.
    """
    stem = re.sub(r"\.(m4a|mp3|aac)$", "", voice_uri, flags=re.IGNORECASE)
    hls = f"https://media.vd.st.nhk/news/easy_audio/{stem}/index.m3u8"
    z_at = next((c["value"] for c in ctx.cookies() if c["name"] == "z_at"), "")
    try:
        resp = page.request.get(
            NHK_TOKEN_URL,
            headers={"Authorization": "Bearer " + z_at, "Referer": "https://news.web.nhk/"},
        )
        if resp.status == 200:
            token = (resp.json() or {}).get("token", "")
            if token:
                return f"{hls}?hdnts={token}"
    except Exception:
        pass
    return ""


def _ext_of(url: str) -> str:
    m = re.search(r"\.(m4a|mp3|aac)", url, re.IGNORECASE)
    return f".{m.group(1).lower()}" if m else ".m4a"


def _extract_m3u8(u: str) -> str:
    """The real m3u8. The NHK player goes through an iframe
    `.../player/index.html?mrurl=<m3u8>&...`: we pull the mrurl parameter out of it."""
    if "mrurl=" in u:
        from urllib.parse import parse_qs, unquote, urlparse
        vals = parse_qs(urlparse(u).query).get("mrurl")
        if vals:
            return unquote(vals[0])
    return u


def _pick_audio_m3u8(hls_urls: list[str]) -> str:
    """Among the captured streams, keep the read-aloud audio (easy_audio), not the video."""
    for u in hls_urls:
        real = _extract_m3u8(u)
        if "easy_audio" in real:
            return real
    return ""


def _dump(dump: Path, html: str, dom: dict, payloads: list, audio_url: str, audio, network_log=None) -> None:
    dump.mkdir(parents=True, exist_ok=True)
    (dump / "page.html").write_text(html, encoding="utf-8")
    (dump / "dom.json").write_text(json.dumps(dom, ensure_ascii=False, indent=2), encoding="utf-8")
    (dump / "api_payloads.json").write_text(
        json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8")
    (dump / "audio_url.txt").write_text(audio_url, encoding="utf-8")
    if network_log is not None:
        (dump / "network.txt").write_text("\n".join(network_log), encoding="utf-8")
    for i, (ext, body) in enumerate(audio):
        (dump / f"audio_{i}{ext}").write_bytes(body)


# -- Audio: duration, ffmpeg compression ---------------------------------------

# Headers the NHK CDN (Akamai) insists on: without them the signed stream is refused.
_MEDIA_HEADERS = ("Referer: https://news.web.nhk/\r\n"
                  "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n")


class AudioTooLong(RuntimeError):
    """The audio of the article is longer than asked for (--max-duration).

    A class of its own, so that the caller announces a deliberate skip rather
    than a failure.
    """


def _remote_input_args(url: str) -> list[str]:
    """ffmpeg/ffprobe input arguments for a remote stream (signed HLS included).

    `file` is left out of the protocols: a remote playlist naming a file of this
    machine would have it read into the extract.
    """
    return [
        "-protocol_whitelist", "http,https,tcp,tls,crypto",
        "-headers", _MEDIA_HEADERS,
        "-i", url,
    ]


def format_duration(seconds: float) -> str:
    """"3 min 32 s", or "45 s" under the minute, in the units of the screen."""
    total = int(round(seconds))
    if total < 60:
        return _("{seconds} s").format(seconds=total)
    return _("{minutes} min {seconds} s").format(minutes=total // 60,
                                                 seconds=f"{total % 60:02d}")


def probe_duration(source: str | Path) -> float | None:
    """The length in seconds of an HLS stream or an audio file, through ffprobe.

    On an m3u8, ffprobe adds up the playlist's EXTINF, with no download. None when
    the measure fails, which lets the article through.
    """
    if shutil.which("ffprobe") is None:
        console.failed(_("ffprobe not found: the length of the audio was not checked."))
        return None
    src = str(source)
    cmd = ["ffprobe", "-hide_banner", "-v", "error",
           "-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
           *(_remote_input_args(src) if src.startswith("http") else ["-i", src])]
    try:
        out = subprocess.run(cmd, check=True, capture_output=True, timeout=120).stdout
        return float(out.decode("utf-8", "replace").strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def max_duration_seconds(args) -> int | None:
    """The length limit asked for on the command line (--max-duration), in seconds."""
    return getattr(args, "max_duration", None)


def check_duration(source: str | Path, limit_seconds: float | None) -> None:
    """Raises AudioTooLong if the audio is over the limit; does nothing without one.

    Called before the download and the model call, so that a skipped article
    costs neither. Prints nothing: the length is shown on the audio's line.
    """
    if not limit_seconds:
        return
    seconds = probe_duration(source)
    if seconds is None:
        return
    # Compared rounded, as shown: "3 min 00 s" refused over a "3 min 00 s" limit
    # would look like a bug.
    if round(seconds) > round(limit_seconds):
        raise AudioTooLong(_(
            "Audio of {length}, over the limit asked for ({limit}) - article "
            "ignored, no card generated."
        ).format(length=format_duration(seconds), limit=format_duration(limit_seconds)))


# The container that takes a codec's stream as it is, when no compression is
# asked for; a codec not listed is re-encoded. Anki reads them all, desktop and
# mobile.
_COPY_CONTAINERS = {
    "aac": ".m4a",
    "alac": ".m4a",
    "mp3": ".mp3",
    "opus": ".opus",
    "vorbis": ".ogg",
    "flac": ".flac",
}


def probe_codec(source: str | Path, stream: str = "a:0") -> str | None:
    """The codec of an audio stream, through ffprobe, or None if the measure fails.

    None leads to a re-encode, not a failure. `stream` must be the one about to
    be written: probing another would pick a container its codec may not fit.
    """
    if shutil.which("ffprobe") is None:
        return None
    src = str(source)
    cmd = ["ffprobe", "-hide_banner", "-v", "error", "-select_streams", stream,
           "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1",
           *(_remote_input_args(src) if src.startswith("http") else ["-i", src])]
    try:
        out = subprocess.run(cmd, check=True, capture_output=True, timeout=120).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    return out.decode("utf-8", "replace").strip().lower() or None


def copy_extension(source: str | Path, stream: str = "a:0") -> str | None:
    """The extension of the container that would take this stream unencoded, or None."""
    return _COPY_CONTAINERS.get(probe_codec(source, stream) or "")


# -- Picking the sound track, when the file carries several --------------------

def probe_audio_tracks(source: str | Path) -> list[tuple[str, str]]:
    """The declared language and label of every sound track, in track order.

    Empty when the measure fails, which leaves the choice to ffmpeg. The rank in
    the list is the N of `-map 0:a:N`, not ffprobe's `index`, which counts every
    stream, picture included.
    """
    if shutil.which("ffprobe") is None:
        return []
    cmd = ["ffprobe", "-hide_banner", "-v", "error", "-select_streams", "a",
           "-show_entries", "stream=index:stream_tags=language,title",
           "-of", "json", "-i", str(source)]
    try:
        out = subprocess.run(cmd, check=True, capture_output=True, timeout=120).stdout
        streams = json.loads(out.decode("utf-8", "replace")).get("streams") or []
    except (subprocess.SubprocessError, OSError, ValueError, AttributeError):
        return []
    return [((f.get("tags") or {}).get("language", ""),
             (f.get("tags") or {}).get("title", "")) for f in streams]


def _says_japanese(label: str) -> bool:
    """Does the free label of a track give it as Japanese?

    Looked for in the languages the program speaks as well as in Japanese: a
    label is written in its publisher's language.
    """
    lowered = label.strip().lower()
    return any(mark in lowered for mark in ("japanese", "japonais", "日本語", "jpn"))


def japanese_track(tracks: list[tuple[str, str]]) -> int | None:
    """The rank of the Japanese track, when there really is a choice to make.

    None lets ffmpeg pick: one track only, or none that says it is Japanese.
    Without `-map`, ffmpeg takes the track with the most channels, so an English
    5.1 dub beats a Japanese stereo track. Once the file carries one language
    tag, the free labels are ignored: "English (translated from Japanese)" says
    Japanese.
    """
    if len(tracks) < 2:
        return None
    if any(language.strip() for language, _label in tracks):
        for rank, (language, _label) in enumerate(tracks):
            if language.strip().lower() in JA_MARKS:
                return rank
        return None
    for rank, (_language, label) in enumerate(tracks):
        if _says_japanese(label):
            return rank
    return None


def map_args(track: int | None) -> list[str]:
    """The `-map` of the chosen track, or nothing at all if we did not settle it."""
    return [] if track is None else ["-map", f"0:a:{track}"]


class _Progress:
    """Where ffmpeg is up to in the media, read off its own progress report.

    `-progress pipe:1` writes `key=value` lines every half second, `out_time_us`
    being the position in microseconds. The total is known only when the command
    bounds itself with `-t`: ffprobe is not called for a waiting line.
    """

    def __init__(self, total: float = 0.0) -> None:
        self.second = 0.0
        self.total = total

    def read(self, line: str) -> None:
        key, _sep, value = line.strip().partition("=")
        # "N/A" until ffmpeg has written something.
        if key == "out_time_us" and value.isdigit():
            self.second = int(value) / 1_000_000

    def where(self) -> str:
        if self.total:
            return _("{position} of {total}").format(
                position=console.duration(self.second),
                total=console.duration(self.total))
        return console.duration(self.second)


def _bounded_duration(input_args: list[str], output_args: list[str]) -> float:
    """The length the command gives itself (`-t`), zero when it gives none.

    An output `-t` is the total; input ones bound each span, and the spans are
    glued end to end, so they add up.
    """
    def values(args: list[str]) -> list[float]:
        found = []
        for rank, word in enumerate(args[:-1]):
            if word == "-t":
                try:
                    found.append(float(args[rank + 1]))
                except ValueError:
                    pass
        return found

    on_output = values(output_args)
    return on_output[-1] if on_output else sum(values(input_args))


def _ffmpeg_run(input_args: list[str], dest: Path, level=None, *,
                copy: bool = False, output_args: list[str] | None = None) -> None:
    """Writes `dest`: stream copied as it is, or re-encoded at the level's bitrate.

    `output_args` replaces the audio level's arguments, for the video clip
    (`video_clip`). Run behind the action line, as a VP9 clip takes minutes. The
    errors go to a file: a second pipe left unread would fill up and block ffmpeg.
    """
    if shutil.which("ffmpeg") is None:
        sys.exit(_("ffmpeg not found on the PATH ({hint}).")
                 .format(hint=system.ffmpeg_hint()))
    output = (output_args if output_args is not None
              else audio_quality.encoder_args(level, copy=copy))
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats",
           "-progress", "pipe:1", "-y", *input_args,
           *output, "-map_metadata", "-1", str(dest)]
    progress = _Progress(_bounded_duration(input_args, output))

    def encode() -> None:
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                       stderr=log, text=True)
            with process:
                for line in process.stdout:  # type: ignore[union-attr]
                    progress.read(line)
            if process.returncode:
                log.seek(0)
                # The real error is at the end of the log.
                err = log.read().decode("utf-8", "replace").strip()
                raise RuntimeError(err[-800:] or _("ffmpeg failed with no message"))

    console.while_working(encode, progress.where)


def _write_audio(input_args: list[str], probe_src: str | Path, out_dir: Path,
                 stem: str, level, *, stream: str = "a:0") -> Path:
    """Drops the audio into `out_dir` under that name, and returns the path obtained.

    With no compression, the extension is the container the codec dictates. A
    copy ffmpeg refuses falls back on an MP3 re-encode, said on the line, rather
    than stopping the generation.
    """
    ext = copy_extension(probe_src, stream) if level.bitrate is None else None
    if ext:
        dest = out_dir / f"{stem}{ext}"
        try:
            _ffmpeg_run(input_args, dest, level, copy=True)
            return dest
        except RuntimeError:
            with contextlib.suppress(OSError):
                dest.unlink(missing_ok=True)
            console.failed(_("stream not copyable as it is: re-encoded."))
    dest = out_dir / f"{stem}.mp3"
    try:
        _ffmpeg_run(input_args, dest, level, copy=False)
    except BaseException:
        # ffmpeg writes as it goes: what it leaves would pass for the audio. On
        # Windows it may still hold the file after a Ctrl+C (WinError 32), whose
        # PermissionError would replace the KeyboardInterrupt.
        with contextlib.suppress(OSError):
            dest.unlink(missing_ok=True)
        raise
    return dest


def transcode_bytes(src_bytes: bytes, src_ext: str, out_dir: Path, stem: str,
                    level) -> Path:
    """Writes an already downloaded audio, as it is or re-encoded. Returns its path."""
    with tempfile.NamedTemporaryFile(suffix=src_ext, delete=False) as tmp:
        tmp.write(src_bytes)
        tmp_path = tmp.name
    try:
        return _write_audio(["-i", tmp_path], tmp_path, out_dir, stem, level)
    finally:
        with contextlib.suppress(OSError):  # still held by ffmpeg, as above
            Path(tmp_path).unlink(missing_ok=True)


def transcode_url(url: str, out_dir: Path, stem: str, level) -> Path:
    """Downloads a remote stream (Akamai-signed HLS .m3u8 included). Returns its path."""
    return _write_audio(_remote_input_args(url), url, out_dir, stem, level)


def extract_audio_track(src: Path, out_dir: Path, stem: str, level,
                        track: int | None = None) -> Path:
    """The sound track of a local file, picture left out. Returns its path.

    Copied as it is at the default level. `track` is the rank `japanese_track`
    gives, None letting ffmpeg pick. `-vn` is set here, after the input, and not
    only for a copy as in `audio_quality.encoder_args`: a re-encode would
    otherwise carry the file's cover art, if any, into the MP3.
    """
    return _write_audio(["-i", str(src), *map_args(track), "-vn"], src, out_dir,
                        stem, level, stream=f"a:{track or 0}")


def transcode_spans_to_mp3(src: Path, dest: Path, spans: list[tuple[float, float]],
                           level) -> None:
    """Extracts `(start, length)` spans of a local file into a single MP3.

    For `audio_split`. `-t` rather than `-to`, whose meaning after an input `-ss`
    differs between ffmpeg versions. Always re-encoded: a copy cuts on frame
    boundaries, tens of milliseconds off, enough to clip a mora. Spans are glued
    end to end, the joins falling in silences. "No compression" here means an
    inaudible bitrate (`audio_quality.UNCOMPRESSED_BITRATE`).
    """
    if not spans:
        raise ValueError(_("no span to extract"))
    inputs: list[str] = []
    for start, length in spans:
        inputs += ["-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.01, length):.3f}",
                   "-i", str(src)]
    if len(spans) > 1:
        labels = "".join(f"[{i}:a]" for i in range(len(spans)))
        inputs += ["-filter_complex", f"{labels}concat=n={len(spans)}:v=0:a=1"]
    _ffmpeg_run(inputs, dest, level)


def transcode_spans_to_clip(src: Path, dest: Path,
                           spans: list[tuple[float, float]],
                           track: int | None = None) -> None:
    """Extracts `(start, length)` spans of a local file into a single WebM clip.

    The video twin of `transcode_spans_to_mp3`, with the profile of `video_clip`.
    With several spans the scaling goes inside the filter graph, ffmpeg refusing
    `-vf` on a `-filter_complex` output. `track` is the transcribed sound track;
    naming it needs `-map 0:v:0` too, or the clip comes out with no picture.
    """
    if not spans:
        raise ValueError(_("no span to extract"))
    inputs: list[str] = []
    for start, length in spans:
        inputs += ["-ss", f"{max(0.0, start):.3f}", "-t", f"{max(0.01, length):.3f}",
                   "-i", str(src)]
    output = video_clip.encoder_args()
    # The graph names the track in its labels: on a two-track file, `[0:a]` takes
    # the fullest one silently, the dub.
    sound = f"a:{track}" if track is not None else "a"
    if len(spans) > 1:
        scaled = ";".join(f"[{i}:v]{video_clip.SCALE}[v{i}]" for i in range(len(spans)))
        pairs = "".join(f"[v{i}][{i}:{sound}]" for i in range(len(spans)))
        inputs += ["-filter_complex",
                   f"{scaled};{pairs}concat=n={len(spans)}:v=1:a=1[v][a]"]
        output = ["-map", "[v]", "-map", "[a]", *output]
    else:
        selection = ["-map", "0:v:0", *map_args(track)] if track is not None else []
        output = ["-vf", video_clip.SCALE, *selection, *output]
    _ffmpeg_run(inputs, dest, output_args=output)


# -- Main entry point ----------------------------------------------------------

def _article_id(url: str) -> str:
    """The `news_id` read out of the URL, or an empty string if there is none.

    Never a placeholder: the id is compared with the site's own (history, voice
    file lookup), where a made-up word would pass for an article.
    """
    m = _ARTICLE_ID_RE.search(url)
    return m.group(1) if m else ""


def _media_id(url: str) -> str:
    """The identifier used to NAME what the article produces (audio, ID field).

    Falls back on a hash of the address: with a fixed name, two such articles
    would overwrite each other's audio, and Anki refuse their cards as duplicates.
    """
    return _article_id(url) or hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def article_id(url: str) -> str:
    """The name an article announces itself under on screen, list and rank included.

    The one that names its files, so that the screen and the media library agree.
    """
    return _media_id(url)


# The hosts and path of NHK Easy, the only pages that need the browser; other
# URLs go through `text_source`. The path matters: nhk.or.jp also serves the
# NHKラジオニュース feed (`nhk-radio`).
_NHK_HOSTS = ("news.web.nhk", "nhk.or.jp")
_NHK_PATH = "/news/easy"


def is_nhk_url(s: str) -> bool:
    """True if the input is an NHK Easy article URL (neither a path nor another URL).

    Read on the host itself: an address merely carrying `news.web.nhk` in its
    query is another site's. A backslash or a user name is refused, since
    urllib and Chromium do not read the host of `evil.com\\@news.web.nhk` alike.
    """
    s = (s or "").strip()
    parts = urllib.parse.urlsplit(s)
    if "\\" in s or "@" in parts.netloc:
        return False
    host = (parts.hostname or "").lower()
    return (parts.scheme.lower() in ("http", "https")
            and any(host == known or host.endswith(f".{known}") for known in _NHK_HOSTS)
            and parts.path.lower().startswith(_NHK_PATH))


def is_nhk_input(s: str) -> bool:
    """True if the input names an NHK source: the keyword 'nhk' or a URL."""
    return s.strip().lower() == "nhk" or is_nhk_url(s)


def collect_urls(inputs: list[str], latest: int, mode: str) -> list[str]:
    """Resolves the NHK inputs (keyword 'nhk' and/or URLs) into a list of article URLs.

    The keyword adds the `latest` articles not yet done by this `mode`; a URL is
    always processed, even one already seen, which is how an article is redone.
    """
    urls = [i for i in inputs if is_nhk_url(i)]
    wants_latest = any(i.strip().lower() == "nhk" for i in inputs)
    if not urls and not wants_latest:
        # Nothing for NHK: no source block to open.
        return []

    # One block for the URLs given and the latest articles alike.
    console.title(SOURCE_NAME)
    console.items([article_id(u) for u in urls])
    if wants_latest:
        already = {_media_id(u) for u in urls}
        urls.extend(u for u in fetch_latest_urls(latest, mode=mode)
                    if _media_id(u) not in already)
    return urls


# -- What the audio really says ------------------------------------------------

# The site's text is not always what the voice file reads: the sound may stop
# early, and some paragraphs are never read. Listening places each sentence of
# the text in the sound, or finds it missing, and gives the lines their timecodes.

# Not `--whisper-model`: this transcription never reaches a card, it only places
# known sentences. `small` does that on a synthesised voice in seconds, where
# `medium` would add a 1.4 GB download and take several times longer.
LISTENING_MODEL = "small"


def _listen(audio_path: Path, work_dir: Path | None = None,
            whisper_models: dict | None = None) -> list[Segment]:
    """The audio transcribed and timed, or an empty list if the listening does not happen.

    Whisper is not part of `kotogen[nhk]`: without it the article is still made,
    with no cross-check, and the line says so.
    """
    if importlib.util.find_spec("whisper") is None:
        console.aside(_("Whisper missing: the text of the site is not cross-checked "
                        "with the audio (pip install -U openai-whisper)."))
        return []
    caches = whisper_models if whisper_models is not None else {}
    try:
        if work_dir is not None:
            return whisper._transcribe(audio_path, LISTENING_MODEL, caches, work_dir)
        # With no work folder the transcription is not kept: its cache is named
        # after the audio's path, which another compression level rewrites as is.
        with tempfile.TemporaryDirectory(prefix="kotogen_nhk_") as tmp:
            return whisper._transcribe(audio_path, LISTENING_MODEL, caches, Path(tmp))
    except Exception as exc:
        console.failed(_("listening impossible ({error}): the text of the site is "
                         "not cross-checked with the audio.")
                       .format(error=console.reason(exc)))
        return []


def generate_for_url(url: str, args: argparse.Namespace, client: AIClient,
                     out_dir: Path, work_dir: Path | None = None,
                     whisper_models: dict | None = None) -> tuple[list[dict], Path]:
    """The NHK pipeline for ONE URL: browser -> text+audio -> AI translation/MCQ -> cards.

    Returns (cards, audio_path). Raises on failure (handled by the caller).

    Leaves the "Generating the cards..." action open, for the caller to close
    with its result (`console.done`), failure included.
    """
    art_id = _media_id(url)
    console.action(_("Loading the article"))
    title, lines, audio_bytes, ext, audio_url = fetch_article(url, headed=False, dump=None)
    # One line per sentence, cut before the model call so that the translation
    # and the key line are numbered on sentences, not on the site's paragraphs.
    lines = split_sentences(lines)
    console.done(_("{title} - {count} {sentences}").format(
        title=short(without_readings(title), 45) or "(?)",
        count=len(lines), sentences=console.plural(len(lines), "sentence")))

    # No audio, no card. The length is checked on the stream when possible,
    # before any download, otherwise on the file obtained.
    level = audio_quality.resolve(args)
    limit = max_duration_seconds(args)
    console.action(_("Fetching the audio"))
    if audio_url and "m3u8" in audio_url:
        check_duration(audio_url, limit)
        audio_path = transcode_url(audio_url, out_dir, f"nhk_{art_id}", level)
    elif audio_bytes:
        audio_path = transcode_bytes(audio_bytes, ext, out_dir, f"nhk_{art_id}", level)
        try:
            check_duration(audio_path, limit)
        except AudioTooLong:
            audio_path.unlink(missing_ok=True)  # no card: no orphan medium
            raise
    else:
        raise RuntimeError(_(
            "audio not found - card NOT created (the audio is compulsory for an "
            "NHK card)."
        ))
    # Only the extension is shown, the name being the article ID already on
    # screen: with no compression it is the original stream's, not always .mp3.
    audio_name = audio_path.name
    length = probe_duration(audio_path)
    says_length = f"{format_duration(length)}, " if length else ""
    console.done(f"{audio_path.suffix.lstrip('.')}, {says_length}"
                 f"{console.size(audio_path.stat().st_size)}, {_(level.detail)}")

    # The text keeps only what the audio says, compared on readings (the site
    # writes `このあとも` where Whisper hears `この後も`), before the model call,
    # which never pays for a line nobody hears.
    segments = _listen(audio_path, work_dir, whisper_models)
    if segments:
        lines, silent = timecodes.spoken_lines(lines, segments, reading=True)
        if not lines:
            # No sentence found in the sound: the audio does not go with this
            # text. The article is not marked done, so a later pass retries it.
            audio_path.unlink(missing_ok=True)
            raise RuntimeError(_(
                "the audio says nothing of the text of the article - card NOT "
                "created (sound and text do not go together)."
            ))
        if silent:
            # Two whole sentences rather than an added "s": French agrees the
            # participle too (`retirée` / `retirées`).
            console.aside(counted(len(silent),
                                  "{count} line at the end of the article removed: the audio "
                                  "stops before.",
                                  "{count} lines at the end of the article removed: the audio "
                                  "stops before.").format(count=len(silent)))

    # The model writes the translation and the questions; --count is a ceiling,
    # never a target, and by default the length of the article sets it.
    limit = quota.resolve(args.count, lines)
    # Left open: the caller closes it with the result.
    console.action(quota.announce())
    numbered = "\n".join(f"{i}. {l}" for i, l in enumerate(lines, 1))
    # Prompt text, so in the language of the cards: `prompts.say`, not `_()`.
    user_msg = (
        prompts.say("NHK article \"{title}\" ({count} lines):")
        .format(title=title, count=len(lines))
        + f"\n\n{numbered}\n\n{quota.instruction(limit)}"
    )
    cards: list[dict] = []
    try:
        result = client.chat_json(prompts.load("nhk_card"), user_msg)
        if not isinstance(result, dict):
            raise ValueError(_("unexpected JSON: {kind}").format(kind=type(result).__name__))

        # The transcript is the site's, furigana included, not the model's.
        result["TranscriptLines"] = lines
        # The article's URL goes with the cards: their source, openable months later.
        cards = quota.enforce(
            _post_process(result, audio_name, art_id, args.level, url,
                          segments=segments, reading=True), limit)
    finally:
        # No card, whether the call failed or gave none: nothing points at the
        # audio, which would sit in the media folder unused.
        if not cards:
            audio_path.unlink(missing_ok=True)
    if cards:
        mark_seen(url, title)  # `nhk` mode history: do not redo this article
    return cards, audio_path
