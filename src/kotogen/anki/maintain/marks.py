"""The marks `maintain` handles, and what every pass does to the notes they mark.

Anki's flags and the star, the action each triggers and the list of targets the
screens draw; the flagged cards found, a change shown and applied (to the whole
passage when its text is shared), a note deleted, a flag laid or taken off.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace

from kotogen import console
from kotogen.anki.connect import request as anki
from kotogen.anki.deck import card as as_card
from kotogen.exporter import ask_choice, short
from kotogen.i18n import _, convention, counted, quoted
from kotogen.maintenance import kinds
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.review import (
    ACTIONS,
    _field,
    _passage_stem,
    card_name,
    field_lines,
    sharing,
)

# ── What the run has written ──────────────────────────────────────────────────

@dataclass
class Tally:
    """What a run of `maintain` has written, counted as each card is written.

    The passes add to it rather than hand their counts up, so that a run cut
    short (Anki closed, a dead key, Ctrl+C) still says what reached the deck.
    """

    changed: int = 0
    cleared: int = 0
    # Leeches: the false ones cleared, with the real ones kept as they stood.
    cleaned: int = 0
    reworked: int = 0

    def start(self) -> Tally:
        """A copy to measure a pass by (`since`)."""
        return replace(self)

    def since(self, start: Tally) -> tuple[int, int]:
        """(cards changed, marks removed) since `start`."""
        return self.changed - start.changed, self.cleared - start.cleared

    def reset(self) -> None:
        self.changed = self.cleared = self.cleaned = self.reworked = 0


# The tally of the run in progress, reset by `run_maintain`; never rebound, so
# that the modules holding it share one.
tally = Tally()


class Quit(BaseException):
    """The `[q]` of a pass: the run stops there, its summary still said.

    Not an Exception: like Ctrl+C, it goes through the `except Exception` that
    keeps a pass going past one card's failure.
    """


def ai_failed(exc: Exception, note: dict | None = None) -> None:
    """A model call that failed on one card: its first line, the card named when
    automatic mode gives it no header of its own."""
    where = card_name(note) + convention("colon", ": ") if note is not None else ""
    console.failed(_("AI error: {where}{error}").format(
        where=where, error=console.reason(exc)))


# Mark -> (emoji, name): Anki's seven flags under their own numbers, then the
# star, the `marked` tag Anki lays on the whole NOTE (Ctrl+K), numbered here to go
# through the same code. `--only` takes the name, or a flag's number; a header
# capitalises and translates it.
STAR = 8
MARKED_TAG = "marked"
FLAG_COLOURS: dict[int, tuple[str, str]] = {
    1: ("🔴", "red"),
    2: ("🟠", "orange"),
    3: ("🟢", "green"),
    4: ("🔵", "blue"),
    5: ("🌸", "pink"),
    6: ("🩵", "turquoise"),
    7: ("🟣", "purple"),
    STAR: ("⭐", "star"),
}
ANKI_FLAGS = range(1, 8)

# Mark name -> its number (accepted by --only, on top of the numbers 1-7).
FLAG_BY_NAME: dict[str, int] = {colour: number
                                for number, (_emoji, colour) in FLAG_COLOURS.items()}


# The action each mark triggers by default. The star triggers none: it is often a
# favourite, which a pass would take off.
DEFAULT_FLAG_ACTIONS: dict[int, str] = {
    1: "error",
    2: "simplify",
    3: "enrich",
    4: "text",
    5: "derive",
    6: "duplicate",
    7: "audio",
    STAR: "",
}

# The setting that says otherwise, the differences only:
# `pink=renew,star=derive,purple=none`. What is not written follows the default,
# even one a later release changes.
FLAGS_SETTING = "KOTOGEN_FLAGS"
NO_ACTION = "none"

# The leech shares the setting and the screen but takes no action from the
# table: Anki lays it, and its handling is its own (see leech). `leech=none`
# leaves it alone; its one action has a key for the screen to offer it.
REWORK = "rework"


def flag_actions() -> dict[int, str]:
    """The action of every mark, "" for a mark that triggers none.

    Read at every call, as the menu changes the setting mid-session; an unknown
    mark or action is passed over. An action answers one mark at most: a written
    mark wins over a default, and the first of two written marks wins.
    """
    from kotogen import settings

    actions = dict(DEFAULT_FLAG_ACTIONS)
    written: dict[int, str] = {}
    for pair in settings.items(FLAGS_SETTING):
        name, _sep, action = pair.partition("=")
        mark = FLAG_BY_NAME.get(name.strip().lower())
        action = action.strip().lower()
        if mark is None or mark in written:
            continue
        if action == NO_ACTION:
            action = ""
        elif action not in ACTIONS or action in written.values():
            continue
        written[mark] = action
    for mark, action in written.items():
        for other in actions:
            if action and other not in written and actions[other] == action:
                actions[other] = ""
        actions[mark] = action
    return actions


def handles_leeches() -> bool:
    """Whether the leeches are handled; the first `leech=` written decides."""
    from kotogen import settings

    for pair in settings.items(FLAGS_SETTING):
        name, _sep, value = pair.partition("=")
        if name.strip().lower() == "leech":
            return value.strip().lower() != NO_ACTION
    return True


def active_marks() -> list[int]:
    """The marks that trigger an action, in Anki's order and the star last."""
    return [mark for mark, action in flag_actions().items() if action]


def write_flag_actions(actions: dict[int, str], leeches: bool = True) -> str:
    """The value of the setting for these actions: the differences only."""
    pairs = [f"{FLAG_COLOURS[mark][1]}={action or NO_ACTION}"
             for mark, action in actions.items()
             if action != DEFAULT_FLAG_ACTIONS[mark]]
    return ",".join(pairs if leeches else [*pairs, f"leech={NO_ACTION}"])


def assign(actions: dict[int, str], mark: int, action: str) -> dict[int, str]:
    """`actions` with `action` on `mark`. The mark that held it takes the one
    `mark` leaves: a swap, so that no action falls off the table unasked."""
    actions = dict(actions)
    for other, held in actions.items():
        if action and held == action and other != mark:
            actions[other] = actions[mark]
    actions[mark] = action
    return actions


# ── The list of targets, as it is written everywhere ──────────────────────────
# Drawn here for both the dialogue and the survey (`--scan`), so that the two
# screens show the same lines.

def targets() -> list[tuple[str, str, str]]:
    """Each target in Anki order: the name to type, its emoji, what it aims at.

    `leech` has no emoji, not being a flag, and leaves the list when it is not
    handled, as a flag with no action does.
    """
    actions = flag_actions()
    listing = [(FLAG_COLOURS[mark][1], FLAG_COLOURS[mark][0], ACTIONS[actions[mark]])
               for mark in active_marks()]
    if handles_leeches():
        listing.append(("leech", "", "failed over and over"))
    return listing


def flag_header(flag: int, notetype: str = "") -> str:
    """The head of a flag's pass: the emoji, `Red - possible mistake`, then the
    note type when the run goes through several (`... - Grammar`)."""
    emoji, colour = FLAG_COLOURS[flag]
    head = f"{emoji}  {_(colour.capitalize())} - {_(ACTIONS[flag_actions()[flag]])}"
    return f"{head} - {notetype}" if notetype else head


# Every name a target can take, not only the active ones: the columns stay put
# when an action moves to another flag.
NAME_COLUMN = max(len(name) for name in [*FLAG_BY_NAME, "leech"]) + 3


def target_lines(counts: dict[str, int | tuple[int, ...]] | None = None,
                 only: Collection[str] | None = None,
                 marks: dict[str, str] | None = None,
                 headers: list[str] | None = None) -> list[str]:
    """The targets in three columns: the name, what it aims at, what it carries.

    `counts` adds right-aligned figures, blank rather than "0"; a tuple gives one
    column per note type, named by `headers`. `only` keeps the targets asked for
    and `marks` ends a line with a mention ("[automatic]"), but the columns are
    always set on the whole list, so that the screens line up.
    """
    every = targets()
    column = NAME_COLUMN
    # `width` rather than `len`: the labels can carry accents, or Japanese.
    defs = max(console.width(_(label)) for _target, _emoji, label in every) + 2
    rows = {target: count if isinstance(count, tuple) else (count,)
            for target, count in (counts or {}).items()}
    spread = len(headers) if headers else 1
    widths = [max([len(str(row[i])) for row in rows.values()]
                  + [console.width(headers[i]) if headers else 0])
              for i in range(spread)] if rows else []

    def figures(row: tuple[int, ...]) -> str:
        return "  ".join(f"{n if n else '':>{w}}" for n, w in zip(row, widths))

    lines = []
    if counts is not None and headers:
        lines.append(" " * (2 + 3 + column + defs)
                     + "  ".join(console.pad_left(h, w) for h, w in zip(headers, widths)))
    for target, emoji, label in every:
        if only is not None and target not in only:
            continue
        line = f"  {console.pad(emoji, 2)} {target:<{column}}"
        if counts is None:
            line += _(label)
        else:
            line += console.pad(_(label), defs) + figures(
                rows.get(target, (0,) * spread))
        lines.append((line + (marks or {}).get(target, "")).rstrip())
    return lines


# The detail of a line goes under the definitions, so that it does not read as
# one more target.
DETAIL = " " * (2 + 3 + NAME_COLUMN)


def find_flagged(notetype: str, flag: int) -> list[int]:
    """IDs of the cards of the given type carrying the mark `flag`.

    The star marks a note and not a card: one card per note, or a note of two
    cards would be worked on - and paid for - twice.
    """
    if flag != STAR:
        return anki("findCards", query=f'"note:{notetype}" flag:{flag}') or []
    card_ids = anki("findCards", query=f'"note:{notetype}" tag:{MARKED_TAG}') or []
    if not card_ids:
        return []
    kept: dict[int, int] = {}
    for card in anki("cardsInfo", cards=card_ids) or []:
        kept.setdefault(card["note"], card["cardId"])
    return list(kept.values())


def load_notes(notetype: str) -> list[dict]:
    """Every note of the given type, as cards (for the duplicate search over the
    whole deck)."""
    note_ids = anki("findNotes", query=f'"note:{notetype}"') or []
    return [as_card(n) for n in (anki("notesInfo", notes=note_ids) if note_ids else [])]


def passage_of(note: dict, kind: CardKind,
               known: dict[int, dict] | None = None) -> list[dict]:
    """The OTHER notes of the passage `note` belongs to, as cards, [] for a card
    alone.

    `known` notes are handed back rather than read again, so that the rest of the
    pass sees what a correction wrote into them.
    """
    stem = _passage_stem(note) if kind.shared else ""
    if not stem:
        return []
    # `_` is an Anki search wildcard: the stem comparison keeps the passage alone.
    ids = anki("findNotes", query=f'"note:{kind.notetype}" "ID:{stem}_*"') or []
    others = [n for n in map(as_card, anki("notesInfo", notes=ids) if ids else [])
              if n["id"] != note["id"] and _passage_stem(n) == stem]
    return [(known or {}).get(n["id"], n) for n in others]


def apply_to_passage(note: dict, kind: CardKind, fields: dict[str, str],
                     add_tags: list[str], remove_tags: list[str],
                     passage: list[dict]) -> int:
    """Applies a change to the card, and its shared fields to the passage.

    Hands back how many other cards of the passage were changed with it. The
    tags stay the card's own: a question is filed on its own merits.
    """
    reached = sharing(note, kind, fields, passage)
    shared = {name: value for name, value in fields.items() if name in kind.shared}
    before = {name: _field(note, name) for name in shared}
    apply_changes(note["id"], fields, add_tags, remove_tags)
    for other in reached:
        same = {name: value for name, value in shared.items()
                if _field(other, name) == before[name]}
        apply_changes(other["id"], same, [], [])
        for name, value in same.items():
            other["fields"][name] = value
    return len(reached)


def passage_summary(count: int) -> str:
    """`3 other cards of the passage too`, for the one-line report."""
    return counted(count,
                   "{count} other card of the passage too",
                   "{count} other cards of the passage too").format(count=count)


# ── Applying ──────────────────────────────────────────────────────────────────

def apply_changes(note_id: int, fields: dict, add_tags: list[str], remove_tags: list[str]) -> None:
    if fields:
        anki("updateNoteFields", note={"id": note_id, "fields": fields})
    if add_tags:
        anki("addTags", notes=[note_id], tags=" ".join(add_tags))
    if remove_tags:
        anki("removeTags", notes=[note_id], tags=" ".join(remove_tags))


def delete_notes(note_ids: list[int]) -> None:
    """Deletes notes (and therefore all their cards). Irreversible."""
    anki("deleteNotes", notes=note_ids)


def clear_flag(card_id: int) -> None:
    """Removes the flag of a card (flags = 0)."""
    set_flag(card_id, 0)


def set_flag(card_id: int, flag: int) -> None:
    """Lays a flag on a card (1 to 7), or takes it off (0).

    `flags` takes an integer, not a string; the answer is checked so as not to
    fail in silence.
    """
    res = anki(
        "setSpecificValueOfCard",
        card=card_id,
        keys=["flags"],
        newValues=[flag],
        warning_check=True,
    )
    # Result per key: `True` on success, `[False, "message"]` on failure.
    if isinstance(res, list) and res:
        entry = res[0]
        if isinstance(entry, (list, tuple)):
            if not entry[0]:
                message = (_("cannot remove the flag: {error}") if not flag
                           else _("cannot lay the flag: {error}"))
                raise RuntimeError(message.format(error=entry[1]))
        elif entry is not True:
            raise RuntimeError(_("cannot remove the flag (value refused)") if not flag
                               else _("cannot lay the flag (value refused)"))


def show_diff(note: dict, fields: dict, add_tags: list[str], remove_tags: list[str],
              reason: str, reached: int = 0, refused: list[str] | None = None) -> None:
    """The change proposed, field by field, before it is accepted.

    A field held one sentence per line shows only the lines that move, by rank.
    `reached` is how many other cards of the passage the shared fields reach.
    """
    kind = kinds.of_note(note)
    colon = convention("colon", ": ")
    print(f"   {kind.label}{colon}{card_name(note)}")
    if reason:
        print("   " + _("Reason: {reason}").format(reason=console.clean(reason)))
    empty = _("(empty)")
    for name, new in fields.items():
        print(f"   {name}" + colon.rstrip())
        old = _field(note, name)
        if name in kind.lines and field_lines(old):
            before, after = field_lines(old), field_lines(new)
            for rank, (was, now) in enumerate(zip(before, after), 1):
                if was != now:
                    print(f"      {rank} - {short(was) or empty}")
                    print(f"      {rank} + {short(now) or empty}")
            continue
        print(f"      - {short(old) or empty}")
        print(f"      + {short(new) or empty}")
    if add_tags or remove_tags:
        print("   " + _("Tags") + colon.rstrip())
        if remove_tags:
            print("      - " + " ".join(remove_tags))
        if add_tags:
            print("      + " + " ".join(add_tags))
    for line in refused or []:
        print("   ! " + line)
    if reached:
        print("   = " + counted(reached,
                                "{count} other card of the passage carries the same "
                                "text: it changes with it",
                                "{count} other cards of the passage carry the same text: "
                                "they change with it").format(count=reached))


# ── Deletion decided by hand ──────────────────────────────────────────────────

def offer_manual_deletion(note: dict) -> bool:
    """Deletes the note on your decision alone, with no AI verdict having asked for it.

    The detections miss cases and the model keeps quiet when in doubt, hence this
    way out. Confirmation required; hands back True when the note was deleted.
    """
    expr = _field(note, "Expression") or _("(no expression)")
    if ask_choice(_("Delete {expression} (note {note}) for good? [y] yes  [n] no").format(
            expression=quoted(expr), note=note["id"]), "yn") != "y":
        print("   " + _("deletion cancelled"))
        return False
    delete_notes([note["id"]])
    print("   " + _("note deleted"))
    return True
