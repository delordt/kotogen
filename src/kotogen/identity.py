"""The identity of a card: one string, drawn from what the card says.

The same matter generated twice gives the same identity, written on every card
line of the JSON Lines file (`exporter._json_row`), so that a reader can tell a
card it holds from a new one without asking Anki. Listening and reading cards
take it from their `ID` field; vocabulary and grammar cards get no such field (it
would not be the first, which Anki checks for duplicates, and would stay empty in
existing notes), so theirs is derived from their fields, and can be again from a
note read out of Anki. A note edited since may no longer match. Colons part the
string after its kind, but it is compared whole: a part may hold a colon.
"""

from __future__ import annotations

import hashlib
import html
import re
from importlib import import_module

from kotogen import grammar_table
from kotogen.furigana import KANJI_RE, reading_key, surface_key

# The generator modules whose cards have an identity, by kind: the name of the
# command, which `notetypes.SPECS` uses too.
KINDS = ("kanji", "vocab", "grammar", "audio", "reading")

# Same length as the fingerprints of the media and of the reading matter.
_HASH_LEN = 8

# The end of an `ID` from the audio and reading generators: the fingerprint of
# the matter, then the rank of the question. The name of the source before it is
# left out: renaming a file would change it, not the matter.
_ID_TAIL_RE = re.compile(r"_([0-9a-f]{8})_(\d+)$")

_CLOZE_RE = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}")
_TAG_RE = re.compile(r"<[^>]*>")


def kind_of(fields: list[str]) -> str | None:
    """The kind of the cards written with these fields, or None.

    Read off the field list rather than carried along, so that every writer of a
    line (`append_cards`, `remove_cards`, the proofreading rewrite) agrees.
    """
    for kind in KINDS:
        if list(import_module(f"kotogen.generators.{kind}").FIELDS) == list(fields):
            return kind
    return None


def _text(value: str) -> str:
    """The plain text of a field: no HTML, no entity, no line break."""
    return html.unescape(_TAG_RE.sub(" ", value or ""))


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_HASH_LEN]


def _vocab(fields: dict[str, str]) -> str:
    """The word as written and as read: 橋 and 箸 stay apart, 食[た]べる and
    食[た] べる come together.

    Kanji with no reading in brackets leave kanji in the reading: the written
    form then stands alone.
    """
    expression = _text(fields.get("Expression", ""))
    surface = surface_key(expression)
    reading = reading_key(expression)
    if not reading or KANJI_RE.search(reading):
        return f"vocab:{surface}"
    return f"vocab:{surface}:{reading}"


def _grammar(fields: dict[str, str]) -> str:
    """The rule, then the sentence: one note is one sentence for one rule.

    The rule by its `grammar_table.key`, unique per point; the sentence without
    its hole, hint, readings or spaces, so that a reading touched up leaves it
    the same sentence.
    """
    rule = grammar_table.key(_text(fields.get("Rule", "")))
    sentence = surface_key(_CLOZE_RE.sub(r"\1", _text(fields.get("Sentence", ""))))
    return f"grammar:{rule}:{_hash(sentence)}"


def _question(kind: str, fields: dict[str, str]) -> str:
    """The fingerprint of the matter and the rank of the question, read off `ID`.

    An `ID` that does not end that way (written by hand, say) is kept whole: it
    is still what Anki compares.
    """
    card_id = (fields.get("ID") or "").strip()
    tail = _ID_TAIL_RE.search(card_id)
    if tail:
        return f"{kind}:{tail.group(1)}:{int(tail.group(2)):03d}"
    return f"{kind}:{card_id}"


def of(kind: str, fields: dict[str, str]) -> str:
    """The identity of a card of this kind, from its fields as they are written."""
    if kind == "vocab":
        return _vocab(fields)
    if kind == "grammar":
        return _grammar(fields)
    if kind in ("audio", "reading"):
        return _question(kind, fields)
    if kind == "kanji":
        # One note per kanji, and the character is the whole of it.
        return f"kanji:{_text(fields.get('Kanji', '')).strip()}"
    raise ValueError(f"no identity for the kind {kind!r}")
