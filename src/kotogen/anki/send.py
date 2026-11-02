"""Sending the cards into Anki: their media, the names Anki keeps, the notes.

The run's file is written as it goes; the same cards are sent once the run is
over (see `exporter.finish`), in the order `take` gives. Nothing here raises: a
send that did not happen is said in one line, the cards being in their file.
"""

from __future__ import annotations

from pathlib import Path

from kotogen import console, exporter
from kotogen.anki import connect
from kotogen.anki.connect import request as anki
from kotogen.anki.media import install_media_files
from kotogen.exporter import Taken
from kotogen.i18n import _


def _add_notes(cards: list[dict], fields: list[str], deck: str, notetype: str) -> list:
    """Add the notes through AnkiConnect; return the ids created (None = duplicate).

    Each note carries what the file holds for its card (see `exporter.outgoing`).
    """
    notes = []
    for card in cards:
        out = exporter.outgoing(card, fields)
        notes.append({
            "deckName": deck,
            "modelName": notetype,
            "fields": out["fields"],
            "tags": out["tags"],
            "options": {"allowDuplicate": False, "duplicateScope": "deck"},
        })
    return anki("addNotes", notes=notes) or []


def send_to_anki_connect(cards: list[dict], fields: list[str], deck: str,
                         notetype: str) -> tuple[int, int]:
    """Send the cards to Anki (creating the deck if need be).

    Returns (added, duplicates refused) silently: `exporter.finish` says it.
    """
    anki("createDeck", deck=deck)  # no effect if the deck already exists
    ids = _add_notes(cards, fields, deck, notetype)
    added = sum(1 for i in ids if i is not None)
    return added, len(ids) - added


def follow_renames(cards: list[dict], renamed: dict[str, str]) -> None:
    """Point the fields of the cards at the names Anki kept.

    Every media tag names its file in a `src` attribute (`exporter.MEDIA_SRC_RE`).
    The ID field keeps the original name: it is Anki's duplicate key, and moving
    it would no longer match the cards of earlier runs.
    """
    for card in cards:
        for name, value in card.items():
            if isinstance(value, str) and 'src="' in value:
                card[name] = exporter.MEDIA_SRC_RE.sub(
                    lambda m: f'src="{renamed.get(m.group(1), m.group(1))}"', value)


def complete_fields(notetype: str, fields: list[str]) -> list[str]:
    """Add the fields the cards carry and the note type lacks; return those added.

    AnkiConnect silently drops the value of an unknown field; an added one
    arrives empty and overwrites nothing. Never raises: an unknown type or a
    closed Anki is left to the send, and an answer listing no field adds nothing.
    """
    try:
        present = anki("modelFieldNames", modelName=notetype) or []
    except (ConnectionError, RuntimeError):
        return []
    if not present:
        return []
    added: list[str] = []
    try:
        for name in (name for name in fields if name not in present):
            anki("modelFieldAdd", modelName=notetype, fieldName=name)
            added.append(name)
            # At its rank, as `notetypes.add_fields` does: a TSV import matches
            # its columns to the fields by rank.
            anki("modelFieldReposition", modelName=notetype, fieldName=name,
                 index=fields.index(name))
    except (ConnectionError, RuntimeError):
        pass
    return added


def send_cards(cards: list[dict], fields: list[str], deck: str,
               notetype: str) -> tuple[tuple[int, int] | None, str]:
    """Send the cards, and say what that gave.

    Returns `((added, duplicates), "")`, or `(None, obstacle)`: a sentence
    fragment the closing block joins to the file's path. Never fails. Anki is
    checked again here: it may have been opened during a long generation.
    """
    if not connect.status(refresh=True).connected:
        return None, _("Anki was not connected")
    try:
        return send_to_anki_connect(cards, fields, deck, notetype), ""
    except ConnectionError:
        # Anki closed during the send: an obstacle, as above, not a refusal.
        return None, _("Anki was no longer connected")
    except RuntimeError as exc:
        return None, _("Anki refused the send ({error})").format(error=console.reason(exc))


def take(cards: list[dict], fields: list[str], deck: str, notetype: str,
         media: list[Path]) -> Taken:
    """The media, the names Anki kept for them, then the notes.

    Media first: Anki may rename a file (see `media`), and the fields follow
    while the cards are still in hand.
    """
    renamed: dict[str, str] = {}
    left_out = install_media_files(media, renamed)
    if renamed:
        follow_renames(cards, renamed)
    completed = complete_fields(notetype, fields)
    sent, blocked = send_cards(cards, fields, deck, notetype)
    return Taken(sent, blocked, left_out, completed)
