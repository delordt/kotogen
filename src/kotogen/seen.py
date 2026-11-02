"""History of sources already handled, by mode and by source.

It lets the "latest articles" and "latest episode" modes run daily without
paying twice for the same cards. Keyed by mode (vocabulary and listening share
an NHK article) and by source, since two feeds may carry the same `guid`.
Wiped, it remakes the cards already made, so it lives in `~/.kotogen`, never
in a cache; `forget` erases on request.

The deck is the other memory: the file holds what THIS machine handled, the
synced deck what every machine did (`memory` says which collection stands for
it). `recover` reads the deck into the file, `missing` says what the deck no
longer carries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from kotogen import system
from kotogen.i18n import _, counted

# {mode: {source: {identifier: title}}}
FILE = Path.home() / ".kotogen" / "seen.json"


def _normalise(data) -> dict[str, dict[str, dict[str, str]]]:
    """Keep what has the shape {mode: {source: {identifier: title}}}, and only that.

    A hand edit or a truncated write can leave anything: what does not fit is
    dropped rather than raised.
    """
    if not isinstance(data, dict):
        return {}
    return {
        mode: {source: {k: v for k, v in ids.items() if isinstance(v, str)}
               for source, ids in content.items() if isinstance(ids, dict)}
        for mode, content in data.items() if isinstance(content, dict)
    }


def _path() -> Path | None:
    """The history of this run: `FILE`, a JSON file's own, or none (see `memory`)."""
    from kotogen import memory

    return memory.known().history(FILE)


def _read() -> dict[str, dict[str, dict[str, str]]]:
    """The whole history."""
    path = _path()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return _normalise(data)


def _write(data: dict[str, dict[str, dict[str, str]]]) -> None:
    """Save the history, whole or not at all: a truncated file reads as empty."""
    path = _path()
    if path is None:
        return
    system.write_whole(path, json.dumps(data, ensure_ascii=False, indent=1))


def load(mode: str, source: str) -> dict[str, str]:
    """What this mode has already handled for this source: {identifier: title}."""
    return _read().get(mode, {}).get(source, {})


def sources(mode: str) -> tuple[str, ...]:
    """The sources under which this mode has kept something.

    By file key, unlike `inventory`'s screen names, for a caller comparing mode
    by mode with the deck.
    """
    return tuple(sorted(key for key, ids in _read().get(mode, {}).items() if ids))


def mark(mode: str, source: str, item_id: str, title: str = "") -> None:
    """Remember an item that was handled, so that the next pass skips it.

    Nothing is written without an identifier: an empty one would match every
    other item that has none.
    """
    if not item_id:
        return
    data = _read()
    known = data.setdefault(mode, {}).setdefault(source, {})
    # A pass without a title keeps the one already known.
    known[item_id] = title or known.get(item_id, "")
    _write(data)


# -- What the history keeps, and how to forget it -----------------------------
# For the settings screen: what the history weighs, and forgetting a source.

# The modes under their screen name: the history files them by command name.
MODES = {"vocab": "vocabulary", "grammar": "grammar",
         "audio": "listening", "reading": "reading"}


@dataclass(frozen=True)
class Trace:
    """What a source left in the history: how much, and under which modes."""

    source: str
    total: int
    modes: tuple[str, ...]


def inventory() -> list[Trace]:
    """The sources that have a history, the fullest one first.

    By source rather than (mode, source): one forgets a show, not a show under
    one mode. The modes are listed too, since the total counts an item per mode.
    """
    data = _read()
    totals: dict[str, int] = {}
    modes: dict[str, set[str]] = {}
    for mode, by_source in data.items():
        for source, ids in by_source.items():
            if not ids:
                continue
            totals[source] = totals.get(source, 0) + len(ids)
            modes.setdefault(source, set()).add(MODES.get(mode, mode))
    # The order of the main menu: the file's would vary from machine to machine.
    order = list(MODES.values())

    def rank(mode: str) -> tuple[int, str]:
        return (order.index(mode) if mode in order else len(order), mode)

    return [Trace(source, total, tuple(sorted(modes[source], key=rank)))
            for source, total in sorted(totals.items(),
                                        key=lambda item: (-item[1], item[0]))]


def describe() -> str:
    """The history in one line, as the settings screen carries it."""
    traces = inventory()
    if not traces:
        return _("empty")
    total = sum(trace.total for trace in traces)
    entries = counted(total, "{count} entry", "{count} entries").format(count=total)
    count = len(traces)
    named = counted(count, "{count} source", "{count} sources").format(count=count)
    return f"{entries}, {named}"


def forget(source: str | None = None) -> int:
    """Forget a source (all its modes), or the whole history. Returns the count.

    Nothing is written when there was nothing to forget.
    """
    data = _read()
    if source is None:
        erased = sum(len(ids) for by_source in data.values() for ids in by_source.values())
        rest: dict[str, dict[str, dict[str, str]]] = {}
    else:
        erased = sum(len(by_source.get(source, {})) for by_source in data.values())
        rest = {}
        for mode, by_source in data.items():
            # A mode left empty goes too: `{"audio": {}}` would read back as a history.
            if kept := {key: ids for key, ids in by_source.items() if key != source}:
                rest[mode] = kept
    if not erased:
        return 0
    _write(rest)
    return erased


# -- Recovering the history from the deck --------------------------------------
# On a new machine the local history is empty while the synced deck knows
# everything: this fills it once, on request. It is the only place that READS a
# provenance rather than comparing it; what it misses (a podcast `guid`, the
# fingerprint of a long reading's passage, neither carried by the card) is still
# seen by the check on the fly. An address (NHK, Tadoku, YouTube) is read back
# here, a composed label by the source that wrote it (`recognise`).


@dataclass(frozen=True)
class Recovery:
    """What a recovery found in the deck, and what it wrote out of it."""

    added: dict[str, int] = field(default_factory=dict)  # source key -> entries
    known: int = 0          # already in the local history
    without_id: int = 0     # recognised, but the card carries no way of naming them
    foreign: int = 0        # provenances outside the sources followed (a file of one's own)
    # The sources the history keeps and the deck no longer carries a card of:
    # said, never erased (see the section below).
    missing: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return sum(self.added.values())


# The short address `youtube.link` puts after the label of a video.
_VIDEO_RE = re.compile(r"youtu\.be/([\w-]{6,})")


def _recognise(trace: str) -> tuple[str, str] | None:
    """A provenance -> (source key, identifier), or None if nothing names it.

    An empty identifier means a known source with nothing to write, unlike None.
    """
    from kotogen.generators import (
        aozora,
        aozora_roudoku,
        deck_story,
        irodori,
        jlpt_papers,
        nhk,
        pdf_web,
        podcast,
        youtube,
    )

    # `_article_id`, not `article_id`: the latter falls back on a fingerprint,
    # which would pass any provenance for an NHK article.
    if article := nhk._article_id(trace):
        return nhk.SOURCE, article
    if book := pdf_web.book_id(trace):
        return pdf_web.SOURCE, book
    # The sources that read their own provenance back. Each answers None to what
    # is not its own, so their order carries no meaning.
    for source in (jlpt_papers, irodori, aozora_roudoku, aozora, deck_story):
        if found := source.recognise(trace):
            return found
    # Both write "channel name - title", and the catalogues hold the names.
    name = trace.split(" - ", 1)[0].strip()
    for key, channel in youtube.catalogue().items():
        if channel.name == name:
            found = _VIDEO_RE.search(trace)
            return (key, found.group(1)) if found else None
    for key, channel in podcast.catalogue().items():
        if channel.name == name:
            return key, ""   # the `guid` is not in the card
    return None


# -- What the deck no longer carries -------------------------------------------
# Deleting cards leaves the history alone on purpose: a card is mostly deleted
# for being bad, and forgetting it would pay to remake it on the next run. The
# screen names the sources the deck no longer carries; forgetting stays manual.
#
# An absence is concluded only when the mode has a Source field (vocabulary and
# grammar do not), the deck answered for that mode (Anki may be closed or behind
# on sync), and a card can name the source (`checkable`).


def checkable(keys: list[str]) -> set[str]:
    """Those of these keys a card would be recognised by, from its provenance.

    The one list of recognised sources: those the deck would show a card of if
    one were left. Out are the keys no card rebuilds (a long reading's cursor,
    `cursor.key_for`; a renamed catalogue alias). The catalogues are read once,
    since each rereads the user's own feed file.
    """
    from kotogen.generators import (
        aozora,
        aozora_roudoku,
        irodori,
        jlpt_papers,
        nhk,
        pdf_web,
        podcast,
        youtube,
    )

    collections = {nhk.SOURCE, pdf_web.SOURCE, aozora.SOURCE, aozora_roudoku.SOURCE}
    channels, feeds = youtube.catalogue(), podcast.catalogue()
    return {key for key in keys
            if key in collections or key in channels or key in feeds
            or key in irodori.VOLUMES or jlpt_papers.is_jlpt_input(key)}


def _present(deck) -> dict[str, set[str]]:
    """For each mode the deck answered for, the sources it still carries in it.

    `deck` is a `known.Sources`. `recover` does the same reading inline rather
    than call this, sparing a second pass over a large deck.
    """
    present: dict[str, set[str]] = {}
    for mode in deck.by_mode:
        seen_here = present.setdefault(mode, set())
        for trace in deck.traces(mode):
            if found := _recognise(trace):
                seen_here.add(found[0])
    return present


def missing(deck) -> tuple[str, ...]:
    """The sources of the history `deck` no longer carries a single card from.

    `deck` is a `known.Known`, read on demand. Nothing is written: the screen
    decides to forget, and asks first.
    """
    from kotogen.known import sources_of

    return _missing(_present(sources_of(deck)))


def _missing(present: dict[str, set[str]]) -> tuple[str, ...]:
    """The sources of the history the deck no longer carries a single card from.

    `present` maps each mode the deck answered for to the sources it carries. A
    source kept under a mode absent from it is not concluded gone: a false
    "gone" leads to a forgetting, and to paying the model again.
    """
    from kotogen.known import SOURCE_SETTINGS

    history = {mode: sources(mode) for mode in SOURCE_SETTINGS}
    known = checkable(sorted({key for keys in history.values() for key in keys}))
    gone = []
    for key in sorted(known):
        modes = [mode for mode, keys in history.items() if key in keys]
        if any(mode not in present for mode in modes):
            continue
        if not any(key in present[mode] for mode in modes):
            gone.append(key)
    return tuple(gone)


def recover(deck) -> Recovery:
    """Write into the local history what `deck` knows of the recognised sources.

    `deck` is a `known.Known`, read afresh. It only ADDS, so that two machines
    recovering from each other converge; what the deck lost is said by `missing`.
    """
    from kotogen.known import sources_of

    read = sources_of(deck)
    added: dict[str, int] = {}
    known = without_id = foreign = 0
    # Gathered in this pass rather than by `_present`, which would walk the traces again.
    present: dict[str, set[str]] = {}
    for mode in read.by_mode:
        already = {}
        seen_here = present.setdefault(mode, set())
        for trace in sorted(read.traces(mode)):
            found = _recognise(trace)
            if found is None:
                foreign += 1
                continue
            source, identifier = found
            seen_here.add(source)
            if not identifier:
                without_id += 1
                continue
            if source not in already:
                already[source] = dict(load(mode, source))
            if identifier in already[source]:
                known += 1
                continue
            mark(mode, source, identifier)
            already[source][identifier] = ""
            added[source] = added.get(source, 0) + 1
    return Recovery(added, known, without_id, foreign, _missing(present))
