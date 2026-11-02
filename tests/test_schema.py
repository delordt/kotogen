"""What a collection already holds stays valid: the note types change by addition.

`deck install` brings any collection up to the repository as long as it only
ADDS a note type, a field or a card. A rename (Anki sees a field vanish and
another appear), a removal, a field moved ahead of another or a Basic type
turned Cloze cannot be repaired once released.

`SHIPPED` only grows: an addition goes in at its rank, with its line under
**Note types** in `CHANGELOG.md`. A failure on a rename asks for the old name to
stay and its replacement to be added beside it, not for `SHIPPED` to follow.
"""

from __future__ import annotations

import pytest

from kotogen import settings
from kotogen.anki import notetypes

SHIPPED = {
    "kanji": {
        "notetype": "Kanji", "deck": "Japanese::Kanji", "cloze": False,
        "cards": ["Recognition"],
        "fields": ["Kanji", "Meaning", "Onyomi", "Kunyomi", "Words", "Strokes",
                   "OtherReadings", "Composition", "LookAlikes", "Notes",
                   "Decoy1", "Decoy2", "Decoy3"],
    },
    "vocab": {
        "notetype": "Vocabulary", "deck": "Japanese::Vocabulary", "cloze": False,
        "cards": ["Recognition", "Production"],
        "fields": ["Expression", "Translation", "Context", "Notes", "Example",
                   "ExampleTranslation", "Audio"],
    },
    "grammar": {
        "notetype": "Grammar", "deck": "Japanese::Grammar", "cloze": True,
        "cards": ["Grammar"],
        "fields": ["Sentence", "Translation", "Target", "Hint", "Nuance", "Rule",
                   "Explanation", "Answer", "URL"],
    },
    "audio": {
        "notetype": "Listening", "deck": "Japanese::Listening", "cloze": False,
        "cards": ["Listening"],
        "fields": ["ID", "Audio", "Video", "Question", "Decoy1", "Decoy2", "Decoy3",
                   "Image", "Answer", "Transcript", "Translation", "Timecodes",
                   "KeyLine", "Source"],
    },
    "reading": {
        "notetype": "Reading", "deck": "Japanese::Reading", "cloze": False,
        "cards": ["Reading"],
        "fields": ["ID", "Text", "Images", "Question", "Decoy1", "Decoy2", "Decoy3",
                   "Answer", "Translation", "KeyLine", "KeyPage", "Source"],
    },
}

SPECS = {spec.command: spec for spec in notetypes.SPECS}

# Said by every failure about something taken away: the fix is in the code, not
# in this file.
_KEEP = ("a collection installed from an earlier release still has it, and "
         "`deck install` cannot move its content: keep it, and add what replaces "
         "it beside it")

# Said by every failure about something new.
_DECLARE = ("add it to SHIPPED in tests/test_schema.py, at its rank, and give it "
            "its line under the Note types heading of CHANGELOG.md")


def _cards(command: str) -> list[str]:
    return [name for name, _sub in SPECS[command].all_cards]


@pytest.mark.parametrize("command", SHIPPED)
def test_a_shipped_note_type_is_still_there_under_its_name(command):
    """A type renamed by default is a second type created beside the first:
    the notes stay in the old one, the new cards go to the new one."""
    assert command in SPECS, f"note type {command!r} removed: {_KEEP}"
    deck, notetype = settings.DECK_DEFAULTS[command]
    shipped = SHIPPED[command]
    assert notetype == shipped["notetype"], f"note type renamed: {_KEEP}"
    assert deck == shipped["deck"], (
        f"deck of {command!r} renamed: the cards already made stay in "
        f"{shipped['deck']!r} and the new ones go elsewhere")


@pytest.mark.parametrize("command", SHIPPED)
def test_a_note_type_keeps_its_kind(command):
    """Anki turns no Basic type into a Cloze, nor the reverse: the notes would
    have to be moved to another type, scheduling and all."""
    assert SPECS[command].is_cloze == SHIPPED[command]["cloze"]


@pytest.mark.parametrize("command", SHIPPED)
def test_the_shipped_fields_are_still_there_in_their_order(command):
    """A field may be inserted anywhere, never taken away nor moved ahead of
    another: `deck install` puts an added field back at its rank, and the
    import of a TSV pairs its columns with the rank of the fields."""
    fields = SPECS[command].fields
    shipped = SHIPPED[command]["fields"]
    missing = [name for name in shipped if name not in fields]
    assert not missing, f"{command}: fields {missing} removed or renamed: {_KEEP}"
    assert [name for name in fields if name in shipped] == shipped, (
        f"{command}: shipped fields reordered - a collection keeps the order it "
        "has, and the TSV columns would land beside their field")


@pytest.mark.parametrize("command", SHIPPED)
def test_the_first_field_never_changes(command):
    """Anki sorts and checks duplicates on the first field, and refuses a note
    whose first field is empty: a field added at the head of an existing type
    would arrive empty on every note already there."""
    first = SHIPPED[command]["fields"][0]
    assert SPECS[command].fields[0] == first, (
        f"{command}: {first!r} is no longer the first field - an added field "
        "goes after it")


@pytest.mark.parametrize("command", SHIPPED)
def test_the_shipped_cards_are_still_there_in_their_order(command):
    """A card renamed is paired by its rank, a card removed leaves its reviews
    behind in every collection."""
    cards = _cards(command)
    shipped = SHIPPED[command]["cards"]
    missing = [name for name in shipped if name not in cards]
    assert not missing, f"{command}: cards {missing} removed or renamed: {_KEEP}"
    assert [name for name in cards if name in shipped] == shipped, (
        f"{command}: shipped cards reordered")


def test_every_note_type_of_the_code_is_declared():
    new = [command for command in SPECS if command not in SHIPPED]
    assert not new, f"new note types {new}: {_DECLARE}"


@pytest.mark.parametrize("command", SHIPPED)
def test_every_field_and_card_of_the_code_is_declared(command):
    """Left out of SHIPPED, it could be renamed after release unnoticed."""
    fields = [f for f in SPECS[command].fields if f not in SHIPPED[command]["fields"]]
    assert not fields, f"{command}: new fields {fields}: {_DECLARE}"
    cards = [c for c in _cards(command) if c not in SHIPPED[command]["cards"]]
    assert not cards, f"{command}: new cards {cards}: {_DECLARE}"
