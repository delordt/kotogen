"""The deck of Anki, answering what already exists (`kotogen.known`), and
taking the cards a run sends it (`exporter.Outlet`).

Reading the deck before generation spares the AI call a duplicate would burn,
and never blocks: a missing note type or field, or Anki closed, answers
"nothing". With Anki closed, comparisons use the copy kept in the cache at the
last reading; the cards generated meanwhile join it, and the next reading
replaces it whole.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from kotogen.anki import connect, media, send
from kotogen.anki.connect import request as anki
from kotogen.exporter import Outlet, Taken
from kotogen.known import Known

# Anki calls a card mature from this interval on, in days, and `maintain` draws
# the same line for leeches: under it, a card is still being learnt.
MATURE = 21


def card(note: dict) -> dict:
    """A note as AnkiConnect hands it back, as the library reads a card.

    The note id becomes the card's `id`, by which Anki is asked about it later.
    """
    fields = note.get("fields") or {}
    return {"id": note.get("noteId"),
            "fields": {name: str((value or {}).get("value", ""))
                       for name, value in fields.items()},
            "tags": list(note.get("tags") or [])}


class Deck(Known, Outlet):
    """The deck of the profile open in Anki, or the copy kept of it."""

    def cards(self, notetype: str) -> list[dict]:
        """Every note of a type: Anki's, else the copy kept at its last reading.

        A note type absent gives an empty list, never an error.
        """
        try:
            note_ids = anki("findNotes", query=f'"note:{notetype}"') or []
            found = (anki("notesInfo", notes=note_ids) if note_ids else []) or []
        except ConnectionError:
            return [card(note) for note in deck_copy(notetype)]
        except RuntimeError:
            return []
        keep_copy(notetype, found)
        return [card(note) for note in found]

    def learning(self, notetype: str) -> set | None:
        """The notes still being learnt: under maturity, neither new nor suspended.

        None without Anki: the copy kept of the deck has no intervals.
        """
        query = f'"note:{notetype}" prop:ivl<{MATURE} -is:new -is:suspended'
        try:
            return set(anki("findNotes", query=query) or [])
        except (ConnectionError, RuntimeError):
            return None

    def reachable(self, notetype: str) -> bool:
        """Anki open, or a copy of the deck to compare with."""
        return connect.status(refresh=True).connected or _copy_path(notetype).exists()

    def live(self) -> bool:
        return connect.status().connected

    def history(self, default: Path) -> Path | None:
        """The deck keeps the history of this machine, `seen.json`."""
        return default

    def written(self, notetype: str, cards: list[dict]) -> None:
        """Cards meant for the deck go into its copy: a second run with Anki
        closed, before their file is imported, must not make them again."""
        add_to_copy(notetype, cards)

    def take(self, cards: list[dict], fields: list[str], deck: str, notetype: str,
             media_files: list[Path]) -> Taken:
        """The media, then the notes (see `send`).

        A send that went through forgets what this session had read of the deck.
        """
        taken = send.take(cards, fields, deck, notetype, media_files)
        if taken.sent is not None:
            self.forget()
        return taken

    def by_hand(self) -> str:
        return media.media_dir_hint()


# One deck for the session: what a command read of it holds for the next one,
# until a send changes it.
DECK = Deck()


# -- The copy of the deck ------------------------------------------------------

# Only the fields a comparison reads: the rest would make the copy ten times
# heavier. The tags are kept, a grammar rule being also read off them.
KEPT_FIELDS = ("Expression", "Rule", "URL", "Source", "Kanji")

# The note types whose copy has already been announced: the deck is read by
# several comparisons, and the line is said once.
_announced: set[str] = set()


def _copy_path(notetype: str) -> Path:
    """Where the copy of this note type lives. Disposable: the cache."""
    from kotogen import system

    safe = re.sub(r"[^\w-]+", "_", notetype) or "_"
    return system.cache_dir() / "deck" / f"{safe}.json"


def _kept(note: dict) -> dict:
    fields = note.get("fields") or {}
    return {"fields": {name: {"value": (fields.get(name) or {}).get("value", "")}
                       for name in KEPT_FIELDS if name in fields},
            "tags": list(note.get("tags") or [])}


def _write_copy(notetype: str, read: float, notes: list[dict]) -> None:
    path = _copy_path(notetype)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"read": read, "notes": notes}, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass  # no copy is a filtering that does not happen, not an error


def _read_copy(notetype: str) -> tuple[float, list[dict]] | None:
    try:
        data = json.loads(_copy_path(notetype).read_text(encoding="utf-8"))
        return float(data["read"]), list(data["notes"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def keep_copy(notetype: str, notes: list[dict]) -> None:
    """Anki has just answered: its notes replace the copy of this note type."""
    _write_copy(notetype, time.time(), [_kept(note) for note in notes])


def deck_copy(notetype: str) -> list[dict]:
    """The notes of the copy, for a run with Anki closed; [] with no copy.

    Says once which day the copy dates from: a copy weeks old is worth knowing about.
    """
    found = _read_copy(notetype)
    if found is None:
        return []
    read, notes = found
    if notetype not in _announced:
        _announced.add(notetype)
        from kotogen import console
        from kotogen.i18n import _, convention

        day = time.strftime(convention("date", "%b %d, %Y"), time.localtime(read))
        console.item(_("Anki closed: compared with the deck as of {day}").format(day=day))
    return notes


def add_to_copy(notetype: str, cards: list[dict]) -> None:
    """Cards just generated for the deck join its copy.

    Only a copy that exists: one made of these cards alone would pass for a deck
    holding nothing else, and a JLPT source would take its whole level for missing.
    """
    if not cards:
        return
    found = _read_copy(notetype)
    if found is None:
        return
    read, notes = found
    notes += [_kept({"fields": {name: {"value": str(card.get(name, ""))}
                                for name in KEPT_FIELDS if name in card},
                     "tags": str(card.get("Tags", "")).split()})
              for card in cards]
    _write_copy(notetype, read, notes)
