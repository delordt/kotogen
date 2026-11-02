"""`kotogen ask`: a request in plain words, carried out by the AI on the deck.

For what the targets of `maintain` do not cover ("take the N4 tag off the cards
I already know"). The model never talks to Anki: it calls the tools declared
here, and what is not declared it cannot do. The scope is the backup's
(`scope()`), the snapshot is taken at the first accepted write (`_net`), and
every write is shown as it will be stored before it is confirmed (`_confirm`);
`--yes` answers for every write but a deletion.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field

from kotogen import console, prompts, settings
from kotogen.ai_client import TOOL_PROVIDERS, AIClient
from kotogen.anki.connect import EditorOpen, request as anki
from kotogen.exporter import RAW_HTML_FIELDS, ask_choice, plain_field, safe_tag, safe_text
from kotogen.furigana import process_furigana
from kotogen.i18n import BACK_ANSWERS, QUIT_ANSWERS, _, convention, counted, listed, means, quoted

# Turns the model may take on its own, past which it is going round in circles.
# Reset each time the user answers.
MAX_TURNS = 20

# The most notes a search hands back to the model. Past it the count is still
# given whole and the model is told the list is cut, so it narrows its query.
MAX_SEARCH = 80

# How many notes one `read_notes` call may open. Lower than `MAX_SEARCH`: a
# search hands back labels, a read hands back every field of every note.
MAX_READ = 40

# What a note is called in a search result, enough for the model to choose which
# ones to open: the first of these fields that is filled (see `_label`).
_LABEL_FIELDS = ("Expression", "Translation")


# -- The scope -----------------------------------------------------------------

def scope() -> dict[str, str]:
    """Note type -> deck, for exactly what a snapshot covers.

    Read from `backup.targets()`, so that what is modifiable is what is
    restorable. A note type absent from the profile drops out.
    """
    from kotogen.anki import backup
    from kotogen.anki.connect import status as anki_status
    from kotogen.cli import deck_config

    present = anki_status(refresh=True).notetypes
    found: dict[str, str] = {}
    for command in backup.targets():
        deck, notetype = deck_config(command)
        if notetype in present:
            found[notetype] = deck
    return found


def _fence(notetypes) -> str:
    """The Anki search that holds the scope, as a bracketed disjunction.

    Every query the model writes is held inside it, in brackets of its own:
    appended bare, an `or` would escape the fence and reach notes no snapshot
    covers.
    """
    return "(" + " OR ".join(f'"note:{name}"' for name in notetypes) + ")"


def _nested(query: str) -> bool:
    """True if the brackets of this query close where they open, quotes aside.

    `x) OR (deck:*` balances its count yet closes the brackets around it, and
    its OR then searches the whole collection. Inside quotes, or after a
    backslash, a bracket is text to Anki.
    """
    depth, quoted, escaped = 0, False, False
    for char in query:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quoted


# -- Declaring the tools -------------------------------------------------------
# The model reads these descriptions as instructions: each says what the tool
# does and what it will refuse.

def _tool(name: str, description: str, properties: dict,
          required: tuple[str, ...] = ()) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required),
            },
        },
    }


def _ids(description: str) -> dict:
    return {"type": "array", "items": {"type": "integer"}, "description": description}


def _tags(description: str) -> dict:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _query() -> dict:
    """The search a batch tool runs itself, in place of `note_ids` (`_batch`)."""
    return {"type": "string",
            "description": "An Anki search, in place of note_ids, for a batch larger "
                           "than a search lists: every note it finds in the scope, in "
                           "one go and one confirmation. Write it as for search_notes."}


def read_tools() -> list[dict]:
    """The three that look. Given in every mode, `--scan` included."""
    return [
        _tool("deck_scope",
              "The note types you may work on, their fields and how many notes "
              "each one holds. Call it first: it is the only way to know what "
              "the deck is made of, and the field names you will have to use.",
              {}),
        _tool("search_notes",
              "Search the deck with the Anki query syntax (tag:N4, "
              "prop:ivl>60, flag:1, Expression:*猫*, -is:suspended...). Returns "
              "the matching notes, identified and labelled. The search is held "
              "inside the scope: you cannot reach a note outside it.",
              {"query": {"type": "string",
                         "description": "An Anki search, without the note type filter."},
               "limit": {"type": "integer",
                         "description": f"How many notes to return (default and "
                                        f"maximum {MAX_SEARCH})."}},
              ("query",)),
        _tool("read_notes",
              "Read notes whole: every field, every tag, and the state of their "
              "cards (interval, lapses, flag). This is what you work from - a "
              "search only labels.",
              {"note_ids": _ids("The notes to open, at most "
                                f"{MAX_READ} at a time.")},
              ("note_ids",)),
    ]


def flag_names() -> list[str]:
    """The colours a flag takes, as the protocol names them: red, orange..."""
    from kotogen.anki.maintain.marks import ANKI_FLAGS, FLAG_COLOURS

    return [FLAG_COLOURS[number][1] for number in ANKI_FLAGS]


def write_tools() -> list[dict]:
    """The five that write. Not declared at all under `--scan`.

    Rather than declared and refused: a tool the model sees is one it calls, and
    each refusal costs a paid turn.
    """
    return [
        _tool("edit_note",
              "Rewrite fields of ONE note, and/or change its tags. Only pass the "
              "fields you really change. In a field that carries readings, the "
              "Japanese you write is normalised (furigana) before being stored, so "
              "write it as you know it; a field that carries none is stored exactly "
              "as written.",
              {"note_id": {"type": "integer", "description": "The note to change."},
               "fields": {"type": "object",
                          "description": "Field name -> new content. The names are "
                                         "those of the note type, exactly.",
                          "additionalProperties": {"type": "string"}},
               "add_tags": _tags("Tags to add."),
               "remove_tags": _tags("Tags to remove."),
               "reason": {"type": "string",
                          "description": "Very short, in the language of the cards: "
                                         "what you are doing and why. It is shown to "
                                         "the user with the change."}},
              ("note_id",)),
        _tool("tag_notes",
              "Add and/or remove tags on a BATCH of notes, in one go. This is the "
              "tool for a tagging job: calling edit_note forty times to lay one "
              "tag asks the user forty questions.",
              {"note_ids": _ids("The notes to tag."),
               "query": _query(),
               "add_tags": _tags("Tags to add."),
               "remove_tags": _tags("Tags to remove."),
               "reason": {"type": "string", "description": "Very short: why."}}),
        _tool("clear_flag",
              "Take the colour flag off the cards of these notes. A flag is a "
              "note left for later by the user: clear it once what it asked for "
              "is done, not to tidy the deck up.",
              {"note_ids": _ids("The notes whose cards lose their flag."),
               "query": _query(),
               "reason": {"type": "string", "description": "Very short: why."}}),
        _tool("flag_cards",
              "Lay a colour flag on these notes, on the first card of each. A flag "
              "is how the user hands a card over to `kotogen maintain`, and each "
              "colour asks it for something: lay one only when the user asks for "
              "it, in the colour they named.",
              {"note_ids": _ids("The notes to flag."),
               "query": _query(),
               "flag": {"type": "string", "enum": flag_names(),
                        "description": "The colour of the flag."},
               "reason": {"type": "string", "description": "Very short: why."}},
              ("flag",)),
        _tool("delete_notes",
              "Delete notes, and every card they carry. Irreversible other than "
              "by restoring the backup, always confirmed by the user one call at "
              "a time, and never the answer to a doubt: if a card may be worth "
              "keeping, say so and let the user decide.",
              {"note_ids": _ids("The notes to delete."),
               "reason": {"type": "string",
                          "description": "Why each of them has no place in the deck. "
                                         "Shown to the user before they answer."}},
              ("note_ids",)),
    ]


WRITE_NAMES = frozenset({"edit_note", "tag_notes", "clear_flag", "flag_cards",
                         "delete_notes"})


# -- The session ---------------------------------------------------------------

@dataclass
class Session:
    """What the run carries across turns: its scope, its net, its tally."""

    notetypes: dict[str, str]
    auto: bool = False
    scan: bool = False
    stamp: str = ""              # the snapshot, once taken
    edited: int = 0
    tagged: int = 0
    unflagged: int = 0
    flagged: int = 0
    deleted: int = 0
    refused: int = 0             # writes the user turned down
    lines: list[str] = field(default_factory=list)   # the final report

    @property
    def wrote(self) -> int:
        return self.edited + self.tagged + self.unflagged + self.flagged + self.deleted


def _net(session: Session) -> bool:
    """Take the snapshot, if it has not been taken yet. False if it failed.

    Called by the write tools only, once the user has accepted and before Anki
    is touched. A failed snapshot stops the write, unlike elsewhere in the
    program: here the writes are the model's plan, not a command the user typed.
    """
    from kotogen.anki import backup

    if session.stamp or not backup.enabled():
        return True
    path = backup.before("ask")
    if path is None:
        console.failed(_("no backup: the change is not applied."))
        return False
    session.stamp = backup.parse_name(path)[0]
    return True


# -- Reading the deck ----------------------------------------------------------

def _field(note: dict, name: str) -> str:
    return note.get("fields", {}).get(name, {}).get("value", "")


# -- What the screen says ------------------------------------------------------
# The program's shape (see `console`): at the margin what names, indented what
# relates to it. Each change the AI wants is a block of its own, ended by the
# answer; each call that only looks is one line under the indent.

_TAGS = re.compile(r"<[^>]+>")

# The markdown the model writes out of habit and a console does not render:
# emphasis stars and underscores, heading hashes. A leading dash stays, being a
# list in plain text too.
_MARKUP = re.compile(r"\*{1,3}|_{2,}|^#{1,6}[ \t]*", re.MULTILINE)


def _plain(text: str, room: int) -> str:
    """A field as it reads on one line: no HTML, cut in screen columns.

    Columns, not characters: a kanji takes two, and an overlong line wraps to
    column zero, out of its block's indent. The model's text and the deck's are
    shown without their control characters (`console.clean`).
    """
    text = console.clean(html.unescape(_TAGS.sub(" ", text)))
    return console.truncate(" ".join(text.split()), room)


def _room(margin: int = 0) -> int:
    """The columns left to a text written under the indent.

    One stays free on the right: a line filling the last column wraps on the
    terminals that do not wait for the next character to do it.
    """
    return max(24, console.columns() - len(console.INDENT) - margin - 1)


def _label(note: dict) -> str:
    """What a note is called in a listing: its first filled leading field."""
    for name in _LABEL_FIELDS:
        value = _field(note, name)
        if value:
            return _plain(value, _room())
    # Otherwise the first filled field: Anki's browser shows the first one.
    for value in note.get("fields", {}).values():
        if value.get("value"):
            return _plain(value["value"], _room())
    return _("(empty note)")


def _notes_info(note_ids: list[int]) -> list[dict]:
    return anki("notesInfo", notes=note_ids) if note_ids else []


def _in_scope(session: Session, note_ids: list[int]) -> tuple[list[dict], list[int]]:
    """Splits the notes asked for into those in scope and the ids refused.

    The second check after the search fence: an id can also come from the
    model's memory of an earlier run, or be invented, without any search.
    """
    notes = [note for note in _notes_info(note_ids) if note]
    inside = [note for note in notes if note.get("modelName") in session.notetypes]
    kept = {note["noteId"] for note in inside}
    return inside, [nid for nid in note_ids if nid not in kept]


def _batch(session: Session, args: dict) -> tuple[list[dict], list[int], str]:
    """The notes a batch tool works on: (in scope, refused ids, why none).

    Listed by id, or found by a `query` the tool runs itself, fenced like any
    search: it reaches past MAX_SEARCH in one go and one confirmation.
    """
    query = str(args.get("query") or "").strip()
    if not query:
        notes, refused = _in_scope(session, [int(i) for i in (args.get("note_ids") or [])])
        return notes, refused, ""
    if not _nested(query):
        return [], [], ("every bracket and quote of the query must close inside it; "
                        "write it again balanced")
    try:
        ids = anki("findNotes", query=f"{_fence(session.notetypes)} ({query})") or []
    except RuntimeError as exc:
        return [], [], f"Anki refused this search: {exc}"
    notes, refused = _in_scope(session, ids)
    return notes, refused, "" if notes else "the query finds no note in the scope"


# -- Writing -------------------------------------------------------------------

def _kind(notetype: str) -> str | None:
    """The command that owns this note type, None when none does.

    Read off the settings, as the scope is: the export reads it off the fields,
    and a note type in Anki may carry one the generator does not write.
    """
    from kotogen.cli import DECK_COMMANDS, deck_config

    return next((command for command in DECK_COMMANDS
                 if deck_config(command)[1] == notetype), None)


def _normalise(fields: dict, kind: str | None) -> dict[str, str]:
    """What the model wants to write, as the card can carry it.

    A field goes through the furigana pass unless the export writes it plain on
    that kind of card (`exporter.plain_field`), and comes out as text
    (`exporter.safe_text`), since a note can carry an instruction planted in its
    source page. `[sound:…]`, a filename, skips the furigana; a media field can
    only be emptied, its tag being the program's.
    """
    out: dict[str, str] = {}
    for name, value in fields.items():
        text = "" if value is None else str(value)
        if name in RAW_HTML_FIELDS:
            if not text.strip():
                out[name] = ""
            continue
        bare = "[sound:" in text or plain_field(name, kind)
        out[name] = safe_text(text, str if bare else process_furigana)
    return out


def _changed(note: dict, fields: dict[str, str]) -> dict[str, str]:
    """Keeps the fields that really change, and that the note type really has.

    An unknown field is dropped: `updateNoteFields` would take it in silence and
    show it nowhere. Both sides are compared unescaped, `"` matching `&quot;`.
    """
    known = set(note.get("fields", {}))
    return {name: value for name, value in fields.items()
            if name in known
            and html.unescape(value) != html.unescape(_field(note, name))}


def _show_reason(args: dict) -> None:
    """Why the AI wants this, in its own words, between the card and the change.

    Cut to the width: its length is the model's.
    """
    if reason := str(args.get("reason") or "").strip():
        console.item(_plain(_("Reason: {reason}").format(reason=reason),
                            _room()))


def _show_fields(note: dict, fields: dict[str, str]) -> None:
    """The change, the line before above the line after.

    Two Japanese sentences do not fit one line; the shape is also that of
    `marks.show_diff` in `maintain`.
    """
    empty = _("(empty)")
    room = _room(4)
    for name, value in fields.items():
        console.item(name)
        console.item(f"  - {_plain(_field(note, name), room) or empty}")
        console.item(f"  + {_plain(value, room)}")


def _show_tags(add: list[str], remove: list[str], count: int = 0) -> None:
    """The tags laid and taken off, and on how many notes.

    The count opens the line: "5 notes: - N4" would read as a bulleted list.
    """
    head = (counted(count,
                    "{count} note",
                    "{count} notes").format(count=count) + "  ") if count else ""
    if add:
        console.item(console.clean(f"{head}+ " + " ".join(add)))
    if remove:
        console.item(console.clean(f"{head}- " + " ".join(remove)))


def _confirm(session: Session, *, deletion: bool = False) -> bool:
    """Ask before writing. True to go ahead.

    `--yes` answers yes, except for a deletion: that rule lives here, once, for
    every write tool.
    """
    if session.auto and not deletion:
        answered = True
    else:
        question = (_("Delete? [y] yes  [n] no") if deletion
                    else _("Apply? [y] yes  [n] no"))
        answered = ask_choice(question, "yn", default="n") == "y"
    # A space ends the block, or the next turn's line would read as part of it.
    console.space()
    return answered


# -- The tools themselves ------------------------------------------------------
# Each hands back (what the model is told, as JSON, and what closes the turn
# line, "" when the tool has shown a block of its own).


def _tool_deck_scope(session: Session, args: dict) -> tuple[dict, str]:
    decks = []
    for notetype, deck in session.notetypes.items():
        ids = anki("findNotes", query=f'"note:{notetype}"') or []
        decks.append({
            "notetype": notetype,
            "deck": deck,
            "notes": len(ids),
            "fields": anki("modelFieldNames", modelName=notetype) or [],
        })
    written = counted(len(decks),
                      "{count} note type",
                      "{count} note types").format(count=len(decks))
    return {"scope": decks, "writable": not session.scan}, written


def _tool_search_notes(session: Session, args: dict) -> tuple[dict, str]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"error": "an empty query matches nothing; say what you look for"}, ""
    limit = min(int(args.get("limit") or MAX_SEARCH), MAX_SEARCH)
    if not _nested(query):
        return {"error": "every bracket and quote of the query must close inside "
                         "it; write it again balanced"}, _("refused search")

    full = f"{_fence(session.notetypes)} ({query})"
    try:
        ids = anki("findNotes", query=full) or []
    except RuntimeError as exc:
        # The model gets Anki's message, and tries again on the next turn.
        return {"error": f"Anki refused this search: {exc}"}, _("refused search")

    # Checked again on the way out, as the writes are (`_in_scope`): a label
    # outside the scope is a note of the collection read to the model.
    notes = _notes_info(ids[:limit])
    listed = [{"note_id": note["noteId"], "notetype": note.get("modelName", ""),
               "label": _label(note), "tags": note.get("tags", [])}
              for note in notes if note and note.get("modelName") in session.notetypes]
    answer: dict = {"found": len(ids), "notes": listed}
    if len(ids) > limit:
        answer["truncated"] = (
            f"{len(ids)} notes match, {limit} are listed. Narrow the query "
            "rather than assuming the deck holds only these - or, to change all "
            "of them, hand the query itself to the batch tool.")
    # The query is in the line's label already: the count alone closes it.
    count = counted(len(ids), "{count} note", "{count} notes")
    return answer, count.format(count=len(ids))


def _tool_read_notes(session: Session, args: dict) -> tuple[dict, str]:
    ids = [int(i) for i in (args.get("note_ids") or [])][:MAX_READ]
    notes, refused = _in_scope(session, ids)

    cards = {}
    card_ids = [cid for note in notes for cid in (note.get("cards") or [])]
    for card in (anki("cardsInfo", cards=card_ids) or []) if card_ids else []:
        cards.setdefault(card.get("note"), []).append(
            {"interval": card.get("interval"), "lapses": card.get("lapses"),
             "flag": card.get("flags"), "suspended": card.get("queue") == -1})

    read = [{"note_id": note["noteId"], "notetype": note.get("modelName", ""),
             "fields": {name: value.get("value", "")
                        for name, value in (note.get("fields") or {}).items()},
             "tags": note.get("tags", []),
             "cards": cards.get(note["noteId"], [])}
            for note in notes]
    answer: dict = {"notes": read}
    if refused:
        answer["out_of_scope"] = refused
    # "Reading the notes… (3 notes)": the count alone closes the line.
    written = counted(len(read), "{count} note", "{count} notes").format(count=len(read))
    return answer, written


def _tool_edit_note(session: Session, args: dict) -> tuple[dict, str]:
    note_id = int(args.get("note_id") or 0)
    notes, refused = _in_scope(session, [note_id])
    if not notes:
        return {"applied": False,
                "error": f"note {note_id} is outside the scope or does not exist",
                "out_of_scope": refused}, _("note out of scope")
    note = notes[0]

    fields = _changed(note, _normalise(args.get("fields") or {},
                                       _kind(note.get("modelName", ""))))
    current = set(note.get("tags", []))
    add = [t for t in map(safe_tag, args.get("add_tags") or []) if t and t not in current]
    remove = [t for t in (args.get("remove_tags") or []) if t in current]
    if not fields and not add and not remove:
        # Not an error: the note already says it, and saying so plainly stops
        # the model from trying again.
        return {"applied": False, "reason": "nothing changes: the note already says that"}, \
               _("nothing to change")

    console.title(_("A note to change"))
    console.item(_label(note))
    _show_reason(args)
    _show_fields(note, fields)
    _show_tags(add, remove)
    if not _confirm(session):
        session.refused += 1
        return {"applied": False, "reason": "the user turned this change down"}, ""
    if not _net(session):
        return {"applied": False, "reason": "no backup could be taken, nothing written"}, ""

    if fields:
        anki("updateNoteFields", note={"id": note_id, "fields": fields})
    if add:
        anki("addTags", notes=[note_id], tags=" ".join(add))
    if remove:
        anki("removeTags", notes=[note_id], tags=" ".join(remove))

    session.edited += 1
    changes = list(fields) + [f"+{t}" for t in add] + [f"-{t}" for t in remove]
    session.lines.append(_("note {id}: {changes}").format(
        id=note_id, changes=listed(changes)))
    return {"applied": True, "fields": fields, "add_tags": add, "remove_tags": remove,
            "note": "the fields are given back as STORED, furigana normalised"}, ""


def _tool_tag_notes(session: Session, args: dict) -> tuple[dict, str]:
    notes, refused, why = _batch(session, args)
    add = [t for t in map(safe_tag, args.get("add_tags") or []) if t]
    remove = [t for t in (args.get("remove_tags") or []) if t]
    if not notes:
        return {"applied": False, "error": why or "no note of that list is in the scope",
                "out_of_scope": refused}, _("no note in scope")
    if not add and not remove:
        return {"applied": False, "error": "neither a tag to add nor one to remove"}, ""

    console.title(_("Tags to change"))
    _show_reason(args)
    _show_tags(add, remove, len(notes))
    console.items([_label(note) for note in notes])
    if not _confirm(session):
        session.refused += 1
        return {"applied": False, "reason": "the user turned this tagging down"}, ""
    if not _net(session):
        return {"applied": False, "reason": "no backup could be taken, nothing written"}, ""

    note_ids = [note["noteId"] for note in notes]
    if add:
        anki("addTags", notes=note_ids, tags=" ".join(add))
    if remove:
        anki("removeTags", notes=note_ids, tags=" ".join(remove))

    session.tagged += len(note_ids)
    count = counted(len(note_ids), "{count} note", "{count} notes").format(count=len(note_ids))
    marks = " ".join([f"+{t}" for t in add] + [f"-{t}" for t in remove])
    session.lines.append(f"{count}{convention('colon', ': ')}{marks}")
    answer = {"applied": True, "notes": len(note_ids)}
    if refused:
        answer["out_of_scope"] = refused
    return answer, ""


def _tool_clear_flag(session: Session, args: dict) -> tuple[dict, str]:
    notes, refused, why = _batch(session, args)
    if why:
        return {"applied": False, "error": why, "out_of_scope": refused}, _("no note in scope")

    # Only the cards that carry a flag, which sits on a card and not its note.
    # `setSpecificValueOfCard` accepts an unflagged card in silence: it would be
    # counted as a flag removed, and its note listed.
    by_note = {note["noteId"]: note for note in notes}
    all_cards = [cid for note in notes for cid in (note.get("cards") or [])]
    flagged = [card for card in
               ((anki("cardsInfo", cards=all_cards) or []) if all_cards else [])
               if card.get("flags")]
    cards = [card["cardId"] for card in flagged]
    touched = {card.get("note") for card in flagged}
    if not cards:
        return {"applied": False, "error": "none of those cards carries a flag",
                "out_of_scope": refused}, _("no flag to remove")

    console.title(_("A flag to remove"))
    _show_reason(args)
    console.items([_label(by_note[nid]) for nid in touched if nid in by_note])
    if not _confirm(session):
        session.refused += 1
        return {"applied": False, "reason": "the user turned this down"}, ""
    if not _net(session):
        return {"applied": False, "reason": "no backup could be taken, nothing written"}, ""

    done, stopped = _write_flags(session, cards, 0)
    answer = {"applied": bool(done), "cards": done}
    if stopped:
        answer["error"] = stopped
    return answer, ""


def _write_flags(session: Session, cards: list[int], flag: int) -> tuple[int, str]:
    """Lay `flag` (0 to take it off) on these cards: (how many, why it stopped).

    An open editing window stops the loop, every later card being refused the
    same way; any other refusal is its card's alone. One request per card, under
    a spinner, as a batch found by a query can hold thousands. Each card is
    counted in `session` once written, so that a Ctrl+C or a closed Anki leaves
    the report true.
    """
    from kotogen.anki.maintain import marks

    done = 0
    stopped = ""
    failures: list[str] = []
    halted = False

    def write() -> None:
        nonlocal done, stopped
        for card in cards:
            if halted:
                return
            try:
                if flag:
                    marks.set_flag(card, flag)
                    session.flagged += 1
                else:
                    marks.clear_flag(card)
                    session.unflagged += 1
                done += 1
            except EditorOpen as exc:
                stopped = str(exc)
                return
            except RuntimeError as exc:
                failures.append(console.reason(exc))

    console.action(_("Laying the flags") if flag else _("Taking the flags off"))
    try:
        console.while_working(write)
    except KeyboardInterrupt:
        # The thread is not waited for: it stops at its next card rather than
        # write on behind the report.
        halted = True
        raise
    finally:
        session.lines.append((counted(done, "{count} flag laid", "{count} flags laid")
                              if flag else
                              counted(done, "{count} flag removed", "{count} flags removed"))
                             .format(count=done))
    console.done(f"{done} {console.plural(done, 'card')}")
    for reason in failures:
        console.failed(reason)
    if stopped:
        console.failed(stopped)
    return done, stopped


def _tool_flag_cards(session: Session, args: dict) -> tuple[dict, str]:
    from kotogen.anki.maintain.marks import FLAG_BY_NAME, flag_header

    colour = str(args.get("flag") or "").strip().lower()
    if colour not in flag_names():
        return {"applied": False, "error": f"unknown flag {colour!r}; the flags are: "
                + ", ".join(flag_names())}, _("unknown flag")
    number = FLAG_BY_NAME[colour]
    notes, refused, why = _batch(session, args)
    if not notes:
        return {"applied": False, "error": why or "no note of that list is in the scope",
                "out_of_scope": refused}, _("no note in scope")

    # The first card of each note only: `maintain` handles every flagged card,
    # and two of one note would be reworked, and paid for, twice. The owner is
    # read off the note's card list rather than off `cardsInfo`.
    owner = {cid: note["noteId"] for note in notes for cid in (note.get("cards") or [])}
    first: dict[int, dict] = {}
    for card in (anki("cardsInfo", cards=list(owner)) or []) if owner else []:
        held = first.get(owner.get(card.get("cardId")))
        if held is None or card.get("ord", 0) < held.get("ord", 0):
            first[owner.get(card.get("cardId"))] = card
    cards = [card["cardId"] for card in first.values() if card.get("flags") != number]
    if not cards:
        return {"applied": False, "reason": "every one of them already carries that flag",
                "out_of_scope": refused}, _("already flagged")

    flagged = {owner[cid] for cid in cards}
    console.title(_("Flags to lay"))
    _show_reason(args)
    console.item(counted(len(flagged), "{count} note", "{count} notes").format(
        count=len(flagged)) + "  " + flag_header(number))
    console.items([_label(note) for note in notes if note["noteId"] in flagged])
    if not _confirm(session):
        session.refused += 1
        return {"applied": False, "reason": "the user turned this flagging down"}, ""
    if not _net(session):
        return {"applied": False, "reason": "no backup could be taken, nothing written"}, ""

    done, stopped = _write_flags(session, cards, number)
    answer = {"applied": bool(done), "cards": done}
    if stopped:
        answer["error"] = stopped
    if refused:
        answer["out_of_scope"] = refused
    return answer, ""


def _tool_delete_notes(session: Session, args: dict) -> tuple[dict, str]:
    ids = [int(i) for i in (args.get("note_ids") or [])]
    notes, refused = _in_scope(session, ids)
    if not notes:
        return {"applied": False, "error": "no note of that list is in the scope",
                "out_of_scope": refused}, _("no note in scope")

    console.title(_("A deletion to confirm"))
    _show_reason(args)
    console.items([_label(note) for note in notes])
    console.item("!! " + (counted(len(notes),
                                  "{count} note and all its cards",
                                  "{count} notes and all their cards")
                          .format(count=len(notes))))
    # `deletion=True`: `--yes` does not answer this one. See `_confirm`.
    if not _confirm(session, deletion=True):
        session.refused += 1
        return {"applied": False,
                "reason": "the user refused the deletion; the notes are still there"}, ""
    if not _net(session):
        return {"applied": False, "reason": "no backup could be taken, nothing deleted"}, ""

    note_ids = [note["noteId"] for note in notes]
    anki("deleteNotes", notes=note_ids)
    session.deleted += len(note_ids)
    session.lines.append(counted(len(note_ids),
                                 "{count} note deleted",
                                 "{count} notes deleted").format(count=len(note_ids)))
    return {"applied": True, "deleted": len(note_ids)}, ""


TOOLS = {
    "deck_scope": _tool_deck_scope,
    "search_notes": _tool_search_notes,
    "read_notes": _tool_read_notes,
    "edit_note": _tool_edit_note,
    "tag_notes": _tool_tag_notes,
    "clear_flag": _tool_clear_flag,
    "flag_cards": _tool_flag_cards,
    "delete_notes": _tool_delete_notes,
}


def run_tool(session: Session, name: str, raw_arguments: str) -> tuple[dict, str]:
    """Run one call from the model; every failure is an answer, but a closed Anki.

    Invalid JSON, an unknown tool, a write under `--scan` or an Anki refusal go
    back to the model, which gets the next turn, rather than end a half-applied
    plan on a traceback. A closed Anki raises: every later call would fail the
    same way, each one a paid turn.
    """
    def failure(message: str, written: str = "") -> tuple[dict, str]:
        """An answer the model can act on, shaped like the successful ones.

        A failed write says `applied: false`, as the tools do: it is the key the
        model reads to know whether the deck moved. A read has no such key.
        """
        answer = {"error": message}
        if name in WRITE_NAMES:
            answer["applied"] = False
        return answer, written

    try:
        arguments = json.loads(raw_arguments or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("the arguments must be an object")
    except (ValueError, TypeError) as exc:
        return failure(f"unreadable arguments ({exc}); send valid JSON",
                       _("unreadable call"))

    if name in WRITE_NAMES and session.scan:
        return failure("this run only looks (--scan): nothing can be written")
    tool = TOOLS.get(name)
    if tool is None:
        return failure(f"unknown tool {name!r}; the tools you have are: "
                       + ", ".join(TOOLS), _("unknown tool"))
    try:
        return tool(session, arguments)
    except ConnectionError:
        raise
    except (RuntimeError, KeyError, TypeError, ValueError) as exc:
        console.failed(console.reason(exc))
        return failure(f"the tool failed: {exc}")


# -- The conversation ----------------------------------------------------------

def _doing(name: str, raw_arguments: str) -> str:
    """The line this call writes while it runs, or "" if it writes a block.

    A write opens a block of its own. The arguments are read leniently: refusing
    them is for `run_tool`, which tells the model.
    """
    if name in WRITE_NAMES or name not in TOOLS:
        return ""
    try:
        args = json.loads(raw_arguments or "{}")
    except (ValueError, TypeError):
        args = {}
    if not isinstance(args, dict):
        args = {}
    if name == "search_notes":
        query = str(args.get("query") or "").strip()
        # Cut, not cleaned: an Anki query is not HTML, and `prop:ivl<60
        # prop:lapses>3` carries a `<...>` the tag pattern would eat whole.
        return (_("Searching {query}").format(
            query=quoted(console.truncate(console.clean(query), 48)))
            if query else _("Searching the deck"))
    if name == "read_notes":
        return _("Reading the notes")
    return _("Looking at the note types")


def _fold(text: str, room: int) -> list[str]:
    """A line cut to `room` screen columns, at a space where there is one.

    Columns, as a kanji takes two. A run without spaces, a Japanese sentence, is
    cut where it fills the line.
    """
    lines: list[str] = []
    line = ""
    for char in text:
        if line and console.width(line + char) > room:
            cut = line.rfind(" ")
            lines.append(line[:cut] if cut > 0 else line)
            line = line[cut + 1:] if cut > 0 else ""
        line += char
    if line:
        lines.append(line)
    return lines or [""]


# Opens each line of the model's answer, which the indent alone does not tell
# from the turn lines. Not `>`, the prompt of what the user types.
_ANSWER_BAR = "│ "


def _head() -> str:
    """The margin line the report of the model hangs under: who is talking."""
    return _("The AI answers")


def _speak(text: str) -> None:
    """What the model says, when it is worth reading.

    Only its last word, the report: the commentary between tools repeats the
    turn lines (`_debug` shows it). Folded to the width, its markdown taken off,
    and indented behind `_ANSWER_BAR` under its margin line.
    """
    if not text.strip():
        return
    console.title(_head())
    room = min(console.columns() - 1 - len(console.INDENT) - len(_ANSWER_BAR), 88)
    for line in _MARKUP.sub("", console.clean(text).strip()).splitlines():
        for folded in _fold(line.rstrip(), room):
            console.item((_ANSWER_BAR + folded).rstrip())


def _debug(text: str) -> None:
    """The commentary `_speak` leaves out, under KOTOGEN_DEBUG."""
    if text.strip() and settings.flag("KOTOGEN_DEBUG"):
        for line in console.clean(text).strip().splitlines():
            console.item(f". {line}")


def _turn(client: AIClient, system: str, history: list[dict], tools: list[dict]):
    """One call to the model, the line animated while it thinks, then taken off.

    "Thinking…" is a wait, not a fact: what the answer gives writes its own line.
    """
    console.action(_("Thinking"))
    try:
        return console.while_working(
            lambda: client.conversation(system, history, tools))
    finally:
        console.drop_line()


def _report(session: Session) -> None:
    """The closing tally: what was written, and the line that undoes it.

    A snapshot is taken only for a write about to happen: with one, the deck may
    have moved even when nothing was counted (a tool failing half-way, flags
    laid by a thread a Ctrl+C cut short).
    """
    console.space()
    if not session.wrote and not session.stamp:
        print(_("Nothing was changed.") if not session.scan
              else _("Nothing was changed: this run only looked."))
        if session.refused:
            print(counted(session.refused,
                          "{count} change turned down.",
                          "{count} changes turned down.").format(count=session.refused))
        return

    if session.wrote:
        print(counted(session.wrote,
                      "Change applied ({count}):",
                      "Changes applied ({count}):").format(count=session.wrote))
        for line in session.lines:
            console.item(line)
    else:
        print(_("A write was cut short: part of it may be in the deck."))
    if session.stamp:
        # The command that undoes it all, ready to copy.
        console.item(_("Go back: kotogen backup --restore {stamp}").format(
            stamp=session.stamp))


def _ask_again(first: bool = False) -> str:
    """The hand back to the user. An empty answer, or a way out, ends it.

    A bare ">", the prompt of the menus, its use said the `first` time only.
    Every way out leaves without a word: an empty line, the menus' "b" and "q",
    Escape, Ctrl+C, the end of the input.
    """
    console.space()
    if first:
        print(_("Answer to carry on, Enter alone to finish."))
    print("> ", end="", flush=True)
    try:
        # Key by key, for Escape to be heard (see `console.read_answer`).
        typed = console.read_answer()
    except (EOFError, KeyboardInterrupt):
        return ""
    if typed is None:
        return ""
    answer = typed.strip()
    leaving = means(answer.lower(), BACK_ANSWERS, "back") or means(
        answer.lower(), QUIT_ANSWERS, "quit")
    return "" if leaving else answer


def preflight(args: argparse.Namespace) -> None:
    """Stop a command line that `ask` cannot serve, before the model is looked for.

    The command line calls it ahead of its check of the model: a provider that
    drives no tools would otherwise be told to pick a model first, for nothing.
    """
    if not (getattr(args, "request", "") or "").strip():
        # The command is built here: a table would quote it the way its prose
        # quotes, which no shell reads.
        words = _("your request")
        sys.exit(_("Say what the AI is to do: {command}.").format(
            command=f'kotogen ask "{words}"'))
    if args.provider not in TOOL_PROVIDERS:
        # A model is named too: the one of the settings belongs to another
        # provider (`cli.chosen_model`).
        sys.exit(_("kotogen ask drives tools, which only {providers} does here. "
                   "Add --provider openrouter --model <model>.").format(
                       providers=listed(TOOL_PROVIDERS)))


def run_ask(args: argparse.Namespace) -> None:
    """`kotogen ask "..."`: the whole conversation."""
    preflight(args)
    request = args.request.strip()

    try:
        notetypes = scope()
    except (ConnectionError, RuntimeError) as exc:
        sys.exit(console.reason(exc, console.ALONE))
    if not notetypes:
        sys.exit(_("None of the note types of the program is in this profile: "
                   "there is nothing to maintain."))

    session = Session(notetypes=notetypes,
                      auto=bool(getattr(args, "yes", False)),
                      scan=bool(getattr(args, "scan", False)))
    tools = read_tools() + ([] if session.scan else write_tools())

    # The margin line the run's indent hangs under. It names the work, not the
    # scope, which is every note type the program makes.
    console.title(_("What the AI does"))
    if session.scan:
        console.item(_("Looking only: the writing tools are not given to the AI."))

    system = prompts.load("ask")
    history: list[dict] = [{"role": "user", "content": request}]
    handed = False   # whether the hand came back once, and its wording was read
    client = AIClient(provider=args.provider, model=args.model)

    try:
        while True:
            for _turn_number in range(MAX_TURNS):
                reply = _turn(client, system, history, tools)
                history.append(reply.message)

                if not reply.calls:
                    _speak(reply.text)
                    break

                _debug(reply.text)
                for call in reply.calls:
                    if label := _doing(call.name, call.arguments):
                        console.action(label)
                    answer, written = run_tool(session, call.name, call.arguments)
                    if console.is_open():
                        console.done(written)
                    elif written:
                        # A write turned back before showing its block: no line
                        # is open to close.
                        console.aside(written)
                    history.append({"role": "tool", "tool_call_id": call.call_id,
                                    "content": json.dumps(answer, ensure_ascii=False)})
            else:
                # The ceiling is said: the report below shows what was done.
                console.space()
                print("!! " + _("Stopped after {count} turns: the AI was going "
                                "round in circles. What was applied is below.")
                      .format(count=MAX_TURNS))
                break

            answer = _ask_again(first=not handed)
            handed = True
            if not answer:
                break
            history.append({"role": "user", "content": answer})
    except KeyboardInterrupt:
        console.close_line()
        console.space()
        print(_("Interrupted by the user."))
        _report(session)
        sys.exit(130)  # what a shell expects of a program stopped by Ctrl+C
    except Exception as exc:
        # The key refused, Anki closed, the service down: what was written is
        # said, with the line that undoes it, before the reason.
        console.close_line()
        _report(session)
        if settings.flag("KOTOGEN_DEBUG"):
            raise  # the traceback, through the program's net
        sys.exit(_("Interrupted: {error}").format(
            error=console.reason(exc, console.ALONE)))

    _report(session)
