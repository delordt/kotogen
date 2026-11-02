"""A lone kanji that is not a word, and the other cards with no place in the vocabulary."""

from __future__ import annotations

from kotogen import console, kanji_word, memory
from kotogen.anki.connect import request as anki
from kotogen.anki.maintain import marks
from kotogen.exporter import ask_choice, choose
from kotogen.generators import kanji as kanji_cards
from kotogen.i18n import _, counted, quoted
from kotogen.maintenance.review import (
    CATEGORY_HINTS,
    CATEGORY_LABELS,
    CATEGORY_TAG_KEPT,
    CATEGORY_TAG_TODO,
    CATEGORY_TAGS,
    _field,
    auto_line,
)

# ── Lone kanji that is not a word ─────────────────────────────────────────────
# Such a card (語, 的, 勉...) cannot be tested as a word. It moves to the kanji
# note type when the profile has one, else it is deleted. Moving makes the card
# as `kotogen kanji` does, then deletes the vocabulary note once Anki has it.

# Kanji going to the kanji deck in this run -> the vocabulary notes deleted once
# its card is in, made in one batch after the passes (`move_to_kanji_deck`). A
# kanji with no note is the automatic mode's: the deletion is left to you.
moving: dict[str, list[int]] = {}


def kanji_deck() -> tuple[str, str] | None:
    """Deck and note type of the kanji cards, or None when there is nowhere to move to.

    Nowhere: `KOTOGEN_SKIP` drops the kanji, or the collection lacks the note type.
    """
    from kotogen.cli import deck_config, skipped_commands  # late import (cli reads maintenance)

    if "kanji" in skipped_commands():
        return None
    deck, notetype = deck_config("kanji")
    try:
        if notetype not in (anki("modelNames") or []):
            return None
    except (ConnectionError, RuntimeError):
        return None
    return deck, notetype


def offer_lone_kanji(client, note: dict, auto: bool) -> str:
    """A card reduced to a kanji that is not a word: offers to move or delete it.

    Hands back KEPT when the card is to be corrected like the others; DELETED,
    MOVED (at the end of the run) and HELD stop the caller. The automatic mode
    deletes nothing: it makes the kanji card where there is a kanji deck, and
    holds the note tagged `Category::ToReview`, so that the next run only asks
    about the deletion.
    """
    expr = _field(note, "Expression")
    if not kanji_word.is_single_kanji(expr):
        return KEPT
    flagged = kanji_word.not_words(client, [expr])
    if expr not in flagged:
        return KEPT
    char = kanji_word.bare_expression(expr)
    target = kanji_deck()
    carded = target is not None and char in kanji_cards.carded(memory.known(), target[1])
    movable = target is not None and not carded

    if auto:
        if movable:
            moving.setdefault(char, [])
        _tag_category(note, CATEGORY_TAG_TODO)
        held_notes.add(note["id"])
        if target is None:
            print("   ! " + _("{expression}: lone kanji, not a word - deletion to be "
                              "decided by hand").format(expression=expr))
        else:
            auto_line("!", note, (_("lone kanji, its card goes to the kanji deck - "
                                    "deletion to be decided by hand") if movable
                                  else _("lone kanji, already in the kanji deck - "
                                         "deletion to be decided by hand")))
        return HELD

    # The model's own words: cleaned, as everything it says on screen.
    why = console.clean(kanji_word.explained(*flagged[expr]))
    line = (_("{expression}: lone kanji, not a vocabulary word on its own ({why})") if why
            else _("{expression}: lone kanji, not a vocabulary word on its own"))
    print("   !! " + line.format(expression=expr, why=why))
    if carded:
        print("      " + _("its card is already in the kanji deck"))

    choice = choose(([("m", _("move it to the kanji deck"))] if movable else [])
                    + [("d", _("delete the card")),
                       ("k", _("keep it and review it"))])
    if choice == "m" and ask_choice(
            _("Make the card of {kanji} in the kanji deck, then delete note {note} for "
              "good? [y] yes  [n] no").format(kanji=char, note=note["id"]), "yn") == "y":
        moving.setdefault(char, []).append(note["id"])
        return MOVED
    if choice == "d" and ask_choice(
            _("Delete note {note} for good? [y] yes  [n] no").format(
                note=note["id"]), "yn") == "y":
        marks.delete_notes([note["id"]])
        print("   " + _("note deleted"))
        return DELETED
    # Kept, by `[k]` or by a "no" to the confirmation: an automatic run's
    # `Category::ToReview` would leave it waiting for a decision now taken.
    if CATEGORY_TAG_TODO in (note.get("tags") or []):
        marks.apply_changes(note["id"], {}, [], [CATEGORY_TAG_TODO])
        note["tags"] = [t for t in note["tags"] if t != CATEGORY_TAG_TODO]
    return KEPT


def move_to_kanji_deck(client) -> int:
    """Makes the kanji cards of the run, then deletes the notes they replace.

    Hands back how many notes went. A note goes only once its kanji is in the
    kanji deck; otherwise it stays, flag and all, for the next run.
    """
    if not moving:
        return 0
    target = kanji_deck()
    chars = list(moving)
    try:
        console.space()
        made = kanji_cards.generate_into(client, chars, *target) if target else set()
        gone = [note_id for char in chars if char in made for note_id in moving[char]]
        left = [char for char in chars if char not in made]
        if gone:
            marks.delete_notes(gone)
            marks.tally.changed += len(gone)
            print("   " + counted(len(gone),
                                  "{count} vocabulary note deleted: its kanji is in the "
                                  "kanji deck",
                                  "{count} vocabulary notes deleted: their kanji are in the "
                                  "kanji deck").format(count=len(gone)))
        if left:
            print("! " + _("no kanji card for {kanji}: the vocabulary notes stay for "
                           "the next run").format(kanji="、".join(left)))
        return len(gone)
    finally:
        moving.clear()


# What `offer_category_fix` and `offer_lone_kanji` hand back; MOVED is the
# latter's alone (the card goes to the kanji deck at the end of the run).
DELETED, HELD, KEPT, MOVED = "deleted", "held", "kept", "moved"

# Notes left waiting during this run, counted once each (a card can come back
# under two flags). `run_maintain` empties it first and counts it at the end.
held_notes: set[int] = set()


def _tag_category(note: dict, tag: str) -> None:
    """Lays a tracking tag and removes the other (the two would contradict each other).

    `note["tags"]` follows: the same note can come back in this run, under another flag.
    """
    current = note.get("tags") or []
    add = [] if tag in current else [tag]
    remove = [t for t in CATEGORY_TAGS if t != tag and t in current]
    marks.apply_changes(note["id"], {}, add, remove)
    note["tags"] = [t for t in current if t not in remove] + add


def offer_category_fix(note: dict, verdict: tuple[str, str], auto: bool) -> str:
    """A card that has no place in this deck: report it and offer a way out.

    Hands back DELETED, HELD or KEPT; only KEPT lets the caller correct the card.
    Automatic mode lays `Category::ToReview` and holds the card, like `[l] later`.
    """
    kind, reason = verdict
    expr = _field(note, "Expression") or _("(no expression)")

    if auto:
        _tag_category(note, CATEGORY_TAG_TODO)
        held_notes.add(note["id"])
        auto_line("!", note, _("{label} - left as it is, tagged {tag}").format(
            label=_(CATEGORY_LABELS[kind]), tag=quoted(CATEGORY_TAG_TODO)))
        return HELD

    print("   !! " + _("{expression}: this card has no place in the vocabulary").format(
        expression=expr))
    print(f"      {_(CATEGORY_LABELS[kind])}")
    if reason:
        print(f"      {console.clean(reason)}")
    hint = CATEGORY_HINTS.get(kind)
    if hint:
        print("      → " + _("to remake with: {command}").format(
            command=hint.format(expr=kanji_word.bare_expression(expr))))

    # The last choice, which only tags the card, is what an EOF keeps.
    choice = choose([("d", _("delete the note")),
                     ("k", _("keep it (stop reporting it)")),
                     ("l", _("later"))])
    if choice == "d" and ask_choice(
            _("Delete note {note} for good? [y] yes  [n] no").format(
                note=note["id"]), "yn") == "y":
        marks.delete_notes([note["id"]])
        print("   " + _("note deleted"))
        return DELETED
    if choice == "k":
        _tag_category(note, CATEGORY_TAG_KEPT)
        print("   " + _("kept, tagged {tag} - no more reporting").format(
            tag=quoted(CATEGORY_TAG_KEPT)))
        return KEPT
    _tag_category(note, CATEGORY_TAG_TODO)
    held_notes.add(note["id"])
    print("   " + _("left as it is, tagged {tag}").format(tag=quoted(CATEGORY_TAG_TODO)))
    return HELD
