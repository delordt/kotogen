"""The routing of text sources, shared by the generators.

`text_sources()` resolves the inputs (the keyword "nhk", a URL, a text file)
into `TextSource`s and `each()` unrolls them, an unreadable text never stopping
the ones after it: a generator only says what it does with the lines. A PDF
goes to the model in vision, so only its recognition is here (`split`);
listening needs the sound (`nhk.generate_for_url`) and shares only the
recognition of the inputs and the resolution of the URLs.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from kotogen import console
from kotogen.ai_client import AIAuthError
from kotogen.exporter import short
from kotogen.furigana import without_readings
from kotogen.i18n import _

# The source modules are imported inside the functions: `nhk` imports `audio`,
# which uses this module, and a top-level import would close the cycle.


# -- Recognising the inputs ---------------------------------------------------

def is_pdf(source: str) -> bool:
    """True if the input names a PDF document (vision route, handled by each generator)."""
    from kotogen.generators import pdf_source
    return pdf_source.is_pdf_input(source)


def is_nhk(source: str) -> bool:
    """True if the input names NHK Easy: the keyword "nhk" or a URL of the site."""
    from kotogen.generators import nhk
    return nhk.is_nhk_input(source)


def is_youtube(source: str) -> bool:
    """True if the input names YouTube: a catalogue alias, or a URL of the site.

    Listening only. Tested before `is_podcast`, which takes any URL that is not
    NHK for a feed.
    """
    from kotogen.generators import youtube
    return youtube.is_youtube_input(source)


def is_jlpt(source: str) -> bool:
    """True if the input names the official past papers: "jlpt", "jlpt2012-n3"...

    Shared by reading (the booklets) and listening (the listening sections).
    """
    from kotogen.generators import jlpt_papers
    return jlpt_papers.is_jlpt_input(source)


def is_irodori(source: str) -> bool:
    """True if the input names いろどり: "irodori", or one of its four volumes.

    Shared by listening and reading: a lesson has its dialogue and its page.
    """
    from kotogen.generators import irodori
    return irodori.is_irodori_input(source)


def is_roudoku(source: str) -> bool:
    """True if the input names 青空朗読: its alias, or the address of a reading.

    Listening only: the collection is sound alone. The text of the same works is
    the `aozora` reading source.
    """
    from kotogen.generators import aozora_roudoku
    return aozora_roudoku.is_roudoku_input(source)


def is_aozora(source: str) -> bool:
    """True if the input is an address of the 青空文庫 collection (card or work page)."""
    from kotogen.generators import aozora
    return aozora.is_aozora_input(source)


def is_podcast(source: str) -> bool:
    """True if the input names a podcast: a known alias, or a feed URL.

    The widest test, so it goes after NHK and YouTube: it takes any URL that is
    not a file, and even a bare word, so that a mistyped alias gets the list of
    the known ones. Listening only: a feed has no text, hence no place in
    `split()`.
    """
    from kotogen.generators import podcast
    return podcast.is_podcast_input(source)


def is_text(source: str) -> bool:
    """True if the input is a generic source: a web page or a text file."""
    from kotogen.generators import text_source
    return text_source.is_source(source)


def is_url(source: str) -> bool:
    """True if the input is an http(s) address - hence to be kept whole."""
    from kotogen.generators import text_source
    return text_source.is_url(source)


# -- The provenance trace (Source field of the cards) -------------------------

def provenance(origin: str | Path, detail: str = "", link: str = "") -> str:
    """What the card will keep of its source: where its matter comes from, and where exactly.

    A `Path` is reduced to its file name, the full path having no place in a note
    one may export; a string passes whole (a URL, or a label like "feed - episode"
    that `.name` would cut at a slash). `detail` locates the passage in its source
    (audio bounds, a page range). `link` reopens a label that is not an address
    (a YouTube video named by channel and title): it goes after the label, where
    the back of the card makes the label clickable, and only if the text lacks it.
    """
    text = origin.name if isinstance(origin, Path) else str(origin).strip()
    if detail:
        text = f"{text} ({detail})"
    link = link.strip()
    return f"{text} {link}" if link and link not in text else text


@dataclass
class Split:
    """The inputs filed by route, each in one file and one only."""

    pdf: list[str] = field(default_factory=list)
    nhk: list[str] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


def split(inputs: Iterable[str]) -> Split:
    """Files every input in its route, in the order it was given.

    Routes are tried from the most specific to the widest: an NHK URL taken for a
    plain web page would be read over HTTP, and its tokenised SPA gives nothing
    back. `other` keeps the rest (a word, a grammar rule, an audio file) for the
    caller.
    """
    routes = Split()
    for source in inputs:
        if is_pdf(source):
            routes.pdf.append(source)
        elif is_nhk(source):
            routes.nhk.append(source)
        elif is_text(source):
            routes.text.append(source)
        else:
            routes.other.append(source)
    return routes


# -- A text source ------------------------------------------------------------

class TextSource:
    """A text to handle: how to announce it, read it, and mark it done.

    `loading` and `source_name` hold plain English, translated where they are
    shown (`each`, `announce`): a module-level `_()` would resolve the language
    at import time.
    """

    kind = ""

    # The first action of this text's block; `summary()` is its result.
    loading = "Reading"

    # The title of the block these texts are announced under. Empty when the
    # source introduces itself, as NHK Easy does by listing its articles.
    source_name = "Text sources"

    def __init__(self, origin: str) -> None:
        self.origin = origin

    @property
    def label(self) -> str:
        """The name this text announces itself under before being read.

        Shown in the list of the source and on the rank line ("[1/4] ..."), which
        must match; the title and length come after, in `summary()`.
        """
        return self.origin

    def fetch(self) -> tuple[str, list[str]]:
        """Returns (title, Japanese lines). Raises with a plain reason."""
        raise NotImplementedError

    def summary(self, title: str, lines: list[str]) -> str:
        """What the reading gave back, as the result of the loading action.

        A text fetched from elsewhere gives its title and size; one written here
        has nothing to name, its title and words having been announced already.
        """
        raise NotImplementedError

    def mark_done(self, title: str) -> None:
        """Memorises the source as handled.

        Does nothing here; `NhkArticle` and `AozoraWork` keep a history.
        """

    @property
    def tracking_key(self) -> str:
        """The key the progress in this text is kept under (see `cursor`).

        Empty, the default, means no cursor: the text is read from the start each
        time. Only long sources read over several runs need one.
        """
        return ""

    @property
    def provenance(self) -> str:
        """Where this text comes from, as the card will keep it (Source field)."""
        return provenance(self.origin if is_url(self.origin) else Path(self.origin))


class NhkArticle(TextSource):
    """An NHK Easy article: browser, the site's furigana, history per mode."""

    kind = "nhk"
    loading = "Loading the article"
    # The site introduced itself by listing its articles (`nhk.collect_urls`).
    source_name = ""

    def __init__(self, url: str, mode: str) -> None:
        super().__init__(url)
        self.mode = mode

    @property
    def label(self) -> str:
        """The identifier of the article, as the NHK list has just announced it."""
        from kotogen.generators import nhk
        return nhk.article_id(self.origin)

    def fetch(self) -> tuple[str, list[str]]:
        from kotogen.generators import nhk
        title, lines = nhk.fetch_article_text(self.origin)
        if not lines:
            raise RuntimeError(_("text of the article not found"))
        return title, lines

    def summary(self, title: str, lines: list[str]) -> str:
        return (f"{short(without_readings(title), 45) or '(?)'} - "
                f"{len(lines)} {console.plural(len(lines), 'line')}")

    def mark_done(self, title: str) -> None:
        from kotogen.generators import nhk
        nhk.mark_seen(self.origin, title, mode=self.mode)


class GenericText(TextSource):
    """Any web page or text file at all, read over plain HTTP."""

    kind = "text"

    def __init__(self, origin: str, furigana: bool = False,
                 whole: bool = False) -> None:
        super().__init__(origin)
        self.furigana = furigana
        self.whole = whole

    @property
    def tracking_key(self) -> str:
        """A page or a file is followed when read `whole`, which only reading asks.

        Vocabulary reads the text in one block and moves nowhere.
        """
        from kotogen.generators import cursor
        return cursor.key_for(self.origin) if self.whole else ""

    @property
    def loading(self) -> str:
        """A page loads, a file is read: the label says which."""
        return "Loading the page" if is_url(self.origin) else "Reading the file"

    @property
    def source_name(self) -> str:
        """Web pages and text files are announced in separate blocks."""
        return "Web pages" if is_url(self.origin) else "Text files"

    @property
    def label(self) -> str:
        """The whole address, or the file name alone."""
        return self.origin if is_url(self.origin) else Path(self.origin).name

    def fetch(self) -> tuple[str, list[str]]:
        from kotogen.furigana import process_furigana
        from kotogen.generators import text_source
        title, lines = text_source.fetch(self.origin, whole=self.whole)
        if self.furigana:
            title = process_furigana(title)
            lines = [process_furigana(line) for line in lines]
        return title, lines

    def summary(self, title: str, lines: list[str]) -> str:
        return (f"{short(without_readings(title), 45) or _('(no title)')} - "
                f"{len(lines)} {console.plural(len(lines), 'line')} "
                f"{_('of Japanese')}")


class AozoraWork(GenericText):
    """A work of the 青空文庫 collection, read as a web page but followed as a work.

    The book card one pastes is not the page of the text: it is resolved to it in
    `text_sources`, before any fetch. The work enters the history under its
    number, so the catalogue can say "already handled", and its progress is kept
    under that number too (`tracking_key`).
    """

    kind = "aozora"
    source_name = "青空文庫"

    def __init__(self, origin: str, work=None, furigana: bool = False,
                 whole: bool = False, mode: str = "reading") -> None:
        super().__init__(origin, furigana, whole)
        self.work = work
        self.mode = mode

    @property
    def label(self) -> str:
        """The title and the author when the catalogue knows them, the address otherwise."""
        return self.work.label if self.work else self.origin

    @property
    def tracking_key(self) -> str:
        """The progress is followed under the number of the work, not its address.

        The settings screen, where a reading is forgotten, finds the title from the
        number; a URL key (`www-aozora-gr-jp-d281cfc4`) would show a fingerprint.
        An address outside the catalogue falls back on the URL key.
        """
        if not self.whole:
            return ""
        from kotogen.generators import aozora
        return f"{aozora.SOURCE}-{self.work.work_id}" if self.work \
            else super().tracking_key

    def mark_done(self, title: str) -> None:
        from kotogen.generators import aozora
        aozora.mark_seen(self.work, self.mode)


# -- Resolving ----------------------------------------------------------------

def nhk_urls(inputs: list[str], latest: int, mode: str) -> list[str]:
    """The NHK URLs to handle, or a clean stop if the site will not let itself be read.

    The keyword "nhk" adds the latest articles this `mode` has not handled yet;
    an explicit URL always gets through, even one already seen.
    """
    if not inputs:
        return []
    from kotogen.generators import nhk
    try:
        return nhk.collect_urls(inputs, latest, mode=mode)
    except Exception as exc:
        # No "NHK" in the message: the block opened above already names the site.
        sys.exit(console.clean(str(exc)))


def text_sources(inputs: Iterable[str], *, mode: str, latest: int,
                 furigana: bool = False, whole: bool = False) -> list[TextSource]:
    """Resolves the inputs into text sources ready to unroll.

    `mode` keys the NHK history (an article done in vocabulary is still to do in
    reading), `latest` serves the "nhk" keyword. `furigana` runs the lines of the
    generic sources through MeCab, which the Text field of a reading card needs
    and word extraction does not. `whole` leaves the text unbounded, for reading
    (see `text_source._cap`). Inputs of the other routes are ignored (`split`).
    """
    routes = split(inputs)
    urls = nhk_urls(routes.nhk, latest, mode)
    resolved: list[TextSource] = [NhkArticle(url, mode) for url in urls]
    for src in routes.text:
        # A book card does not carry its text: it is resolved here, once. If that
        # fails (collection unreachable), the address is read as it is, outside
        # the history.
        if is_aozora(src):
            from kotogen.generators import aozora
            try:
                url, work = aozora.resolve(src)
            except Exception:
                url, work = src, None
            resolved.append(AozoraWork(url, work, furigana, whole, mode))
        else:
            resolved.append(GenericText(src, furigana, whole))
    return resolved


def no_news(activity: str = "") -> str:
    """The answer to the keyword "nhk" when the latest articles are all done."""
    return (_("Nothing new on NHK Easy: every one of the latest articles has "
              "already been handled{where} (give the URL of an article to redo "
              "it).").format(where=_(" in {activity}").format(activity=activity)
                             if activity else ""))


# -- Unrolling ----------------------------------------------------------------

def announce(sources: list[TextSource]) -> None:
    """Opens the block of each source, with what it carries, before unrolling.

    One block per `source_name`, in the order given. A source that introduced
    itself while fetching its items (NHK Easy) is not repeated.
    """
    blocks: dict[str, list[str]] = {}
    for source in sources:
        if source.source_name:
            blocks.setdefault(source.source_name, []).append(source.label)
    for name, labels in blocks.items():
        console.title(_(name))
        console.items(labels)


def each(sources: list[TextSource],
         handle: Callable[[TextSource, str, list[str]], object]) -> int:
    """Unrolls the sources by the template: rank, loading, then the work.

    `handle(source, title, lines)` does the generator's work and returns something
    true once the source is done with; only then is it marked done, so a failure
    leaves it to be taken again. An error is said under its rank and the loop goes
    on, except a refused key or an exhausted quota, which every later source would
    hit too. Returns the number of sources marked done.
    """
    announce(sources)
    done = 0
    for n, source in enumerate(sources, 1):
        console.rank(n, len(sources), source.label)
        console.action(_(source.loading))
        try:
            # Whatever the source, a fetch can take a while and print nothing.
            title, lines = console.while_working(source.fetch)
        except AIAuthError:
            console.close_line()
            raise
        except Exception as exc:
            # Only a failure shows the address: it is what one reopens by hand.
            where = "" if source.label == source.origin else f" - {source.origin}"
            console.failed(f"{exc}{where}")
            continue
        console.done(source.summary(title, lines))
        try:
            produced = handle(source, title, lines)
        except AIAuthError:
            console.close_line()
            raise
        except Exception as exc:
            console.failed(str(exc))
            continue
        # The generator may have left its last action open.
        console.close_line()
        if produced:
            source.mark_done(title)
            done += 1
    return done
