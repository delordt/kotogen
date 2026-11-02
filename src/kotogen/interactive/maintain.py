"""The dialogue of `kotogen maintain`: what is waiting in the deck, the
targets to work on, and the screen that says what each mark asks for."""

from __future__ import annotations

from kotogen import console, settings
from kotogen.i18n import _, counted, means
from kotogen.interactive.screen import (
    _ALL_ANSWERS,
    _NONE_ANSWERS,
    _ask,
    _Back,
    _entry,
    _header,
    _menu,
    _pause,
    _remember_toggle,
)
from kotogen.interactive.status import _missing_for, _why_not


def _ask_maintain_targets(prompt: str, allowed: frozenset[str] | set[str]) -> list[str] | None:
    """Asks for a list of maintenance targets. None = all of them ("all")."""
    while True:
        answer = _ask(prompt, _("all", "targets"), back=True).lower()
        if means(answer, _ALL_ANSWERS, "all") or answer == _("all", "targets"):
            return None
        tokens = answer.split()
        unknown = [t for t in tokens if t not in allowed]
        if not unknown:
            return tokens
        print("   " + counted(len(unknown),
                              "Unknown target: {names}",
                              "Unknown targets: {names}")
              .format(names=" ".join(unknown)))


def _ask_auto_targets(allowed: frozenset[str] | set[str]) -> list[str]:
    """Asks for the targets to apply without validation; hands back the argv fragment.

    The three forms of `--yes`: nothing automatic (`[]`), everything (`--yes`
    alone), or the named targets."""
    while True:
        answer = _ask(_("Targets to apply without validation"), _("none", "targets"),
                      back=True).lower()
        if means(answer, _NONE_ANSWERS, "none") or answer == _("none", "targets"):
            return []
        if means(answer, _ALL_ANSWERS, "all") or answer == _("all", "targets"):
            return ["--yes"]
        tokens = answer.split()
        unknown = [t for t in tokens if t not in allowed]
        if not unknown:
            return ["--yes", *tokens]
        print("   " + counted(len(unknown),
                              "Unknown target: {names}",
                              "Unknown targets: {names}")
              .format(names=" ".join(unknown)))


def _maintain_mode() -> str:
    """The three ways into the deck, and the screen that says what each mark does.

    The last entry opens a screen rather than a command, hence the loop, as in
    the menu of the note types.
    """
    choice: int | str = 1
    while True:
        # Dimmed: what calls the model without a key or a model, and `ask`
        # without a provider that drives tools. Looking and the marks stay open.
        missing = _missing_for(ai=("", "ask"), tools=("ask",))
        choice = _menu(_("Corrections - what to do?"), [
            ("--scan", _entry(_("Look"),
                              _("what needs attention, without changing anything"), 17)),
            ("", _entry(_("Handle"), _("put the marked cards right"), 17)),
            ("ask", _entry(_("Ask"),
                           _("make a request, the AI acts on the deck"), 17)),
            ("marks", _entry(_("Marks"), _("what each mark asks for"), 17)),
        ], default=choice, allow_back=True, memory="maintain", disabled=missing)
        if choice in missing:
            _why_not(missing[choice], _("Ask") if choice == "ask" else _("Handle"))
        elif choice != "marks":
            return choice
        else:
            _marks()
        _header()


def _maintain_options(mode: str) -> list[str]:
    # `ask` is another command, offered here as it looks after the deck: the
    # request typed is its only step, and the example shows the grain expected.
    if mode == "ask":
        console.space()
        print(_("What the AI is to do, in your own words. Every change will be\n"
                "shown to you before being applied, and the deck is backed up first."))
        print(_("E.g.: take the N4 tag off the cards whose interval is over 60 days"))
        console.space()
        return [mode, _ask(_("Your request"), back=True)]

    argv = ["maintain"]
    if mode == "--scan":
        return argv + [mode]

    # One target per line: what it aims at, and how many cards it carries.
    counts = _maintain_counts()
    console.space()
    for line in _maintain_target_lines(counts):
        print(line)
    console.space()

    # A clean deck: the questions would only lead to "Nothing to do".
    if counts is not None and not sum(counts.values()):
        print(_("Nothing to handle: no marked card in this deck."))
        _pause(_("Enter to come back to the menu..."))
        raise _Back

    # What goes through without validation is chosen target by target (the tags,
    # say, rather than the leeches), right after the targets, from the same list.
    allowed = maintain_targets()
    targets = _ask_maintain_targets(_("Targets to handle, separated by spaces"), allowed)
    if targets:
        argv += ["--only", *targets]
    return argv + _ask_auto_targets(frozenset(targets) if targets else allowed)


def maintain_targets() -> frozenset[str]:
    """What `maintain --only` accepts today: the names of the marks that trigger
    an action, the numbers of those that are flags, the actions themselves, and
    `leech` when it is handled.

    Read at every call, as the screen of the marks changes it mid-session. Only
    the names are offered on screen (see `_maintain_target_lines`).
    """
    from kotogen.anki.maintain.marks import ANKI_FLAGS, FLAG_COLOURS, flag_actions, handles_leeches

    actions = flag_actions()
    active = [mark for mark, action in actions.items() if action]
    return frozenset({FLAG_COLOURS[mark][1] for mark in active}
                     | {str(mark) for mark in active if mark in ANKI_FLAGS}
                     | {actions[mark] for mark in active}
                     | ({"leech"} if handles_leeches() else set()))


def _maintain_target_lines(counts: dict[str, int] | None = None) -> list[str]:
    """The targets of `maintain`, each glossed: the name to type, what it aims at.

    The list the report draws too (`marks.target_lines`). `counts` adds a column
    of figures; without it (a silent deck) the targets show bare. Imported late,
    as `marks` drags the AI client behind it.
    """
    from kotogen.anki.maintain.marks import target_lines

    return target_lines(counts)


def _maintain_counts() -> dict[str, int] | None:
    """What each target carries in the deck, or None if the deck does not answer.

    Nine `findCards` requests per note type in use (seven flags, the two halves
    of the leech tag), the price of choosing targets knowing which have work.
    The menu dims maintenance without Anki (`ANKI_ONLY`); None when Anki has
    closed since: the list shows without figures, and the command says so.
    """
    from kotogen.anki.maintain.marks import active_marks, handles_leeches
    from kotogen.anki.maintain.review import scan_counts, survey
    from kotogen.maintenance import DEFAULT_TAG, IVL_MATURE, kinds

    try:
        found = survey(kinds.selected(), active_marks(), handles_leeches(), DEFAULT_TAG,
                       IVL_MATURE)
    except (ConnectionError, RuntimeError):
        return None
    # One figure per target over all note types: the dialogue picks targets.
    counts, _headers = scan_counts(found)
    return {target: sum(n) if isinstance(n, tuple) else n for target, n in counts.items()}


# ── What each mark asks for ───────────────────────────────────────────────────
# The action each flag asks for, and the star (Anki's mark of the note) too. The
# leech, laid by Anki, is only handled or not. One setting holds what differs
# from the default (see `marks.flag_actions`).

# Column of the actions: the longest mark, "Turquoise" behind its emoji, fits
# ahead of it.
_MARK_COLUMN = 16


def _marks() -> None:
    """One line per mark with its action; each opens on the choice of action."""
    from kotogen.anki.maintain import marks

    choice = None
    while True:
        _header()
        console.space()
        print(_("What each mark asks of the corrections. A mark with no action\n"
                "is left alone; the star marks the whole note (Ctrl+K in Anki),\n"
                "and Anki lays the leech itself on a card failed over and over."))
        console.space()
        actions = marks.flag_actions()
        extras: list[tuple[str | None, str]] = []
        if settings.raw(marks.FLAGS_SETTING):
            extras = [(None, ""), ("z", _("Put everything back to default"))]
        try:
            choice = _menu("", [*[(str(mark), _flag_row(mark, action))
                                  for mark, action in actions.items()],
                                (None, ""), ("leech", _leech_row())],
                           extras=extras, allow_back=True, default=choice)
        except _Back:
            return
        if choice == "z":
            _remember_toggle(marks.FLAGS_SETTING, "")
            continue
        if choice == "leech":
            _leech_action()
            continue
        _flag_action(int(choice))


def _flag_row(mark: int, action: str) -> str:
    """`🌸 Pink         to derive`, the action in a column."""
    from kotogen.anki.maintain.marks import FLAG_COLOURS
    from kotogen.maintenance.review import ACTIONS

    emoji, name = FLAG_COLOURS[mark]
    shown = _(ACTIONS[action]) if action else _("no action")
    return console.pad(f"{emoji} {_(name.capitalize())}", _MARK_COLUMN) + shown


def _flag_action(mark: int) -> None:
    """The action of one mark. An action another mark held moves over to it, and
    that mark takes the one this one leaves: nothing falls off the table unasked."""
    from kotogen.anki.maintain import marks
    from kotogen.maintenance.review import ACTION_DESCRIPTIONS, ACTIONS

    actions = marks.flag_actions()
    emoji, name = marks.FLAG_COLOURS[mark]
    labels = {action: _(label) for action, label in ACTIONS.items()}
    width = max(console.width(label) for label in [*labels.values(), _("no action")]) + 3
    options: list[tuple[str | None, str]] = [
        (action, console.pad(label, width) + _(ACTION_DESCRIPTIONS[action]))
        for action, label in labels.items()]
    options += [(None, ""), (marks.NO_ACTION, console.pad(_("no action"), width)
                             + _("the flag is left alone"))]
    _header()
    try:
        choice = _menu(_("{flag} - which action?").format(
            flag=f"{emoji} {_(name.capitalize())}"), options, allow_back=True,
            default=actions[mark] or marks.NO_ACTION)
    except _Back:
        return
    action = "" if choice == marks.NO_ACTION else choice
    _remember_toggle(marks.FLAGS_SETTING,
                     marks.write_flag_actions(marks.assign(actions, mark, action),
                                              marks.handles_leeches()))


def _leech_row() -> str:
    """`   Leech        to rework`: no emoji, it is not a flag."""
    from kotogen.anki.maintain import marks

    shown = _("to rework") if marks.handles_leeches() else _("no action")
    return console.pad(f"   {_('Leech')}", _MARK_COLUMN) + shown


def _leech_action() -> None:
    """Whether the leeches are handled: its one action, or none."""
    from kotogen.anki.maintain import marks

    labels = [_("to rework"), _("no action")]
    width = max(console.width(label) for label in labels) + 3
    _header()
    try:
        choice = _menu(_("{flag} - which action?").format(flag=_("Leech")), [
            (marks.REWORK, console.pad(labels[0], width)
             + _("clear the false leeches, rewrite the real ones")),
            (None, ""),
            (marks.NO_ACTION, console.pad(labels[1], width)
             + _("the leeches are left alone")),
        ], allow_back=True,
            default=marks.REWORK if marks.handles_leeches() else marks.NO_ACTION)
    except _Back:
        return
    _remember_toggle(marks.FLAGS_SETTING, marks.write_flag_actions(
        marks.flag_actions(), choice != marks.NO_ACTION))
