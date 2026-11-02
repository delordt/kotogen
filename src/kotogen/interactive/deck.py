"""The dialogue of `kotogen deck`, the "Templates" entry of the menu.

What the cards look like - the settings of their templates, laid on disk or
opened in the preview - then what Anki holds of them: the note types, their
cards, their names, and whether a command is used at all.
"""

from __future__ import annotations

from kotogen import console
from kotogen.anki import templates as card_templates
from kotogen.cli import cards_var, deck_config, skipped_commands, wanted_cards
from kotogen.i18n import _, counted, listed, quoted
from kotogen.interactive.screen import (
    _ask,
    _ask_yes_no,
    _Back,
    _entry,
    _header,
    _menu,
    _pause,
    _remember_toggle,
)
from kotogen.interactive.status import CARD_COMMANDS, _missing_for, _still_missing, _why_not


def _deck_mode() -> str:
    """What the cards look like, then what Anki holds of them: one screen, two
    groups.

    One screen, as a setting of the appearance reaches Anki at the next install.
    Only Install and Compare are commands, handed back to become `deck install`,
    and only they dim offline; the other three open a screen, reopen this menu
    on leaving it (hence the loop) and work with Anki closed.
    """
    choice: int | str = "preview"
    while True:
        missing = _missing_for(anki=("", "--check"))
        choice = _menu(_("Templates - what to do?"), [
            (None, _("Your cards")),
            ("preview", _entry(_("Preview"),
                               _("see them in the browser, set them on the spot"), 19)),
            ("appearance", _entry(_("Appearance"),
                                  _("the same settings, in the terminal"), 19)),
            (None, _("In Anki")),
            ("", _entry(_("Install"),
                        _("create what is missing, ask before overwriting"), 19)),
            ("--check", _entry(_("Compare"),
                               _("what differs, without changing anything"), 19)),
            ("decks", _entry(_("Decks and types"),
                             _("what your profile installs, and where"), 19)),
        ], default=choice, allow_back=True, memory="deck",
            disabled=missing)
        if choice in missing and (lacking := _still_missing(missing[choice])):
            _why_not(lacking)
        elif choice == "preview":
            _preview()
        elif choice == "appearance":
            _appearance()
        elif choice == "decks":
            _decks()
        else:
            return choice
        # Or the menu redraws under the screen just left: `_dialog` clears the
        # page for the first pass only.
        _header()


def _deck_options(mode: str) -> list[str]:
    return ["deck", "install"] + ([mode] if mode else [])


# Column of the values, common to both screens of this menu: "Interlinear
# translation", the longest label planned for, fits ahead of it.
_VALUES = 26


# ── Decks and note types ──────────────────────────────────────────────────────
# Four settings per command, on a screen apart from the appearance: this one is
# visited when setting up, the other whenever a card irritates.

_INSTALLED, _CARDS, _DECK, _NOTETYPE = "installed", "cards", "deck", "notetype"


def _decks() -> None:
    """The choice of the note type; its four settings are on the next screen.

    One type at a time, as all five would overflow a low window (see
    `menu.fits_on_screen`); the list shows where each goes in Anki.
    """
    choice = None
    while True:
        _header()
        console.space()
        print(_("Kotogen carries one note type per kind of card; these settings say"))
        print(_("which ones your profile installs, and under which names."))
        # No subheading parts the list from the text above: a blank line does.
        console.space()
        try:
            choice = _menu("", _deck_notetypes(), allow_back=True, default=choice)
        except _Back:
            return
        _deck_card(choice)


def _deck_notetypes() -> list[tuple[str | None, str]]:
    """One note type per line, with where it goes in Anki - or that it does not."""
    from kotogen.anki import notetypes

    names = dict(CARD_COMMANDS)
    skipped = skipped_commands()
    lines: list[tuple[str | None, str]] = []
    for spec in notetypes.SPECS:
        deck, _notetype = deck_config(spec.command)
        lines.append((spec.command,
                      _row(_(names.get(spec.command, spec.command)),
                           _("not installed") if spec.command in skipped else deck)))
    return lines


def _deck_card(command: str) -> None:
    """The four settings of a note type, each opening on the spot."""
    from kotogen.anki import notetypes

    spec = next(s for s in notetypes.SPECS if s.command == command)
    name = _(dict(CARD_COMMANDS).get(command, command))
    choice = None
    while True:
        _header()
        console.space()
        print(_("What your profile installs of the {name} note type.")
              .format(name=quoted(name)))
        console.space()
        try:
            choice = _menu("", _deck_entries(spec), allow_back=True, default=choice)
        except _Back:
            return
        if choice == _INSTALLED:
            _toggle_installed(command)
        elif choice == _CARDS:
            _choose_cards(command)
        else:
            _rename(command, choice)


def _deck_entries(spec) -> list[tuple[str | None, str]]:
    """The settings of this note type, value in a column.

    The line of the cards shows only for a type with more than one card.
    """
    installed = _("no") if spec.command in skipped_commands() else _("yes")
    lines: list[tuple[str | None, str]] = [(_INSTALLED, _row(_("Installed"), installed))]
    if len(spec.all_cards) > 1:
        wanted = wanted_cards(spec.command)
        lines.append((_CARDS, _row(_("Cards installed"),
                                   listed(wanted) if wanted else _("all", "cards"))))
    deck, notetype = deck_config(spec.command)
    lines.append((_DECK, _row(_("Anki deck"), deck)))
    lines.append((_NOTETYPE, _row(_("Note type"), notetype)))
    return lines


def _row(label: str, value: str) -> str:
    """A label and its value, in a column: the screen reads like a table.

    Stripped on the right: the selection bar and the truncation are set on the
    longest line, which trailing spaces would throw off.
    """
    return (console.pad(label, _VALUES) + value).rstrip()


def _toggle_installed(command: str) -> None:
    """Makes a command enter or leave the list of the unused ones.

    It then leaves the welcome menu too: it is the same setting.
    """
    skipped = set(skipped_commands())
    skipped.symmetric_difference_update({command})
    _remember_toggle("KOTOGEN_SKIP", ",".join(sorted(skipped)))


def _choose_cards(command: str) -> None:
    """The whitelist of the cards of this note type, card by card.

    Every card is written as nothing ("all"), so that a card the repository adds
    reaches a profile that takes them all without a new setting.
    """
    from kotogen.anki import notetypes

    spec = next(s for s in notetypes.SPECS if s.command == command)
    all_names = [name for name, _template in spec.all_cards]
    choice = None
    while True:
        wanted = wanted_cards(command) or all_names
        _header()
        console.space()
        print(_("Cards of the {name} note type that this profile installs.")
              .format(name=quoted(deck_config(command)[1])))
        print(_("A card not installed is neither created, nor compared, nor reported."))
        # No subheading parts the list from the text above: a blank line does.
        console.space()
        try:
            choice = _menu("", [(name, _row(name, _("yes") if name in wanted
                                            else _("no")))
                                for name in all_names],
                           allow_back=True, default=choice)
        except _Back:
            return
        kept = [name for name in all_names
                if (name in wanted) != (name == choice)]
        if not kept:
            console.space()
            print(_("A note type with no card would install nothing: that is what"))
            print("   " + _("{setting} says, and it lights up again with one key.")
                  .format(setting=quoted(_("Installed: no"))))
            _pause(_("Enter to come back..."))
            continue
        _remember_toggle(cards_var(command),
                         "" if kept == all_names else ", ".join(kept))


def _rename(command: str, what: str) -> None:
    """Changes the name of the deck or of the note type of this command.

    A deck renamed is created by Anki at the first send; a note type renamed is
    another type, the old one keeping its notes, as the screen warns.
    """
    deck, notetype = deck_config(command)
    if what == _DECK:
        label, current = _("Anki deck"), deck
    else:
        label, current = _("Note type"), notetype
    _header()
    console.space()
    print(_("{label} of the {command} command.").format(
        label=label, command=_(dict(CARD_COMMANDS).get(command, command))))
    if what == _NOTETYPE:
        print("   " + _("This name renames nothing in Anki: it makes it aim at"
                        " another note"))
        print("   " + _("type, and the old one stays where it is with all its notes."))
    console.space()
    try:
        new = _ask(label, current, back=True).strip()
    except (_Back, KeyboardInterrupt, EOFError):
        return
    if new and new != current:
        _remember_toggle(f"KOTOGEN_{command.upper()}_{what.upper()}", new)


# ── Appearance of the cards ───────────────────────────────────────────────────
# What this profile keeps of the shipped templates, on two levels, the card then
# its settings: all at once would be taller than the terminal, where a menu
# redraws awry under the arrows (see `menu.fits_on_screen`). The entries are
# numbered, as letters would mean nothing here, and toggle on the spot.

def _appearance() -> None:
    """The choice of the card to set, and what holds for all five.

    The global settings (the palette) stay on this level, which has their reach.
    """
    choice = None
    while True:
        _header()
        console.space()
        print(_("Your cards ship complete; these settings say what you keep of them."))
        try:
            choice = _menu("", _appearance_entries(), extras=_appearance_extras(),
                           allow_back=True, default=choice)
        except _Back:
            return
        if choice == "w":
            _write_templates()
        elif choice == "z":
            _reset_to_defaults()
        elif choice.isdigit():
            _toggle(card_templates.SETTINGS[int(choice)])
        else:
            _appearance_card(choice)


def _appearance_entries() -> list[tuple[str | None, str]]:
    """The five cards and what they keep, then the settings of all of them.

    Headed "cards", what one sees, not "note types", how Anki files them."""
    lines: list[tuple[str | None, str]] = [(None, _("Card by card"))]
    for command, name in CARD_COMMANDS:
        lines.append((command, _row(_(name), _says_the_changes(command))))
    lines.append((None, _("All the cards")))
    lines += _appearance_settings(card_templates.GLOBAL)
    return lines


def _says_the_changes(command: str) -> str:
    """What has been changed on this card, in one column.

    Empty when nothing has, so that a card that was set stands out. One change
    is said in full, several are counted: their list would not fit, and the
    card's own screen has it.
    """
    changes = card_templates.differences(command)
    if not changes:
        return ""
    return (changes[0] if len(changes) == 1
            else counted(len(changes), "{count} change", "{count} changes").format(
                count=len(changes)))


def _appearance_card(command: str) -> None:
    """The template settings of a card: one toggles as many of them as one likes.

    For whoever knows what they change, and for machines with no browser: the
    preview, which carries the same switches and shows their effect, heads the
    Templates menu one step up and is not offered again here.
    """
    name = _(dict(CARD_COMMANDS).get(command, command))
    choice = None
    while True:
        _header()
        console.space()
        print(_("What your {name} cards keep of the default templates.")
              .format(name=quoted(name)))
        console.space()
        try:
            choice = _menu("", _appearance_settings(command),
                           allow_back=True, default=choice)
        except _Back:
            return
        _toggle(card_templates.SETTINGS[int(choice)])


def _appearance_settings(command: str) -> list[tuple[str | None, str]]:
    """The settings of this reach, one per line, value in a column.

    Keyed by the rank in `card_templates.SETTINGS`, whatever screen shows them.
    The language of the cards, which changes no template, is left to the
    settings ("g").
    """
    return [(str(rank), _row(_(setting.label),
                             setting.show(card_templates.value(setting.key))))
            for rank, setting in enumerate(card_templates.SETTINGS)
            if setting.command == command
            and setting is not card_templates.LANGUAGE]


def _appearance_extras() -> list[tuple[str | None, str]]:
    """The writing to disk, and the reset to the repository if there is anything
    to reset.

    Not on the card screens, as they bear on all five note types.
    """
    extras: list[tuple[str | None, str]] = [
        (None, ""),
        ("w", _("Write the templates to disk")),
    ]
    if not card_templates.is_default():
        extras.append(("z", _("Put everything back to default")))
    return extras


def _write_templates() -> None:
    """Lays the rendered templates in a folder, to be pasted into Anki by hand.

    The way out when AnkiConnect does not answer or no browser opens the preview.
    The folder is that of the TSV files, not asked for; its path is said after.
    """
    from kotogen.anki import notetypes
    from kotogen.exporter import output_dir

    dest = output_dir() / "templates"
    _header()
    console.space()
    try:
        written = notetypes.export_templates(dest)
    except OSError as exc:
        # FileNotFoundError included: "templates/" not found (the program launched
        # from elsewhere) is the common case, and its message says so.
        console.failed(console.reason(exc, console.ALONE))
        _pause(_("Enter to come back..."))
        return
    print(counted(len(written),
                  "{count} file written in {dest}",
                  "{count} files written in {dest}")
          .format(count=len(written), dest=dest))
    print(f"{console.INDENT}"
          + _("README.txt says where to paste what in Anki."))
    _pause(_("Enter to come back..."))


def _apply_template(setting, value: str) -> None:
    """Lays a choice about the cards into `templates.env`, silent when it works.

    A failed write is said before the redraw, the choices being read back from
    the file with no copy in the session. Shared by the Appearance screen and the
    list of the languages of the cards.
    """
    try:
        card_templates.set_one(setting.key, value)
    except OSError as exc:
        console.space()
        print(_("Write impossible ({reason}).").format(reason=exc))
        print("   " + _("The setting has not been kept."))
        _pause(_("Enter to come back..."))


def _toggle(setting) -> None:
    """Moves to the next notch, and comes back to the first after the last."""
    positions = setting.positions
    _apply_template(setting, positions[
        (positions.index(card_templates.value(setting.key)) + 1) % len(positions)])


def _preview() -> None:
    """Opens the cards in the browser, as these settings make them.

    It reads the same templates as `deck install`, and what is applied there goes
    into the same file, read back on return. The page opens on the first card.
    The screen is cleared so that the line saying how to close it stays in view.
    """
    from kotogen.anki import preview as preview_module

    _header()
    console.space()
    try:
        opened = preview_module.serve()
    except (preview_module.Unavailable, OSError) as exc:
        print(_("Preview unavailable: {reason}").format(reason=exc))
        # The only other way to see what these settings do.
        print(f"{console.INDENT}"
              + _("The templates can be written into a folder: entry {key} of"
                  " the Appearance screen.").format(key=quoted("w")))
        _pause(_("Enter to come back..."))
        return
    print(_("Preview opened in the browser: {url}").format(url=opened.url))
    for note in opened.notes:
        print(f"   {note}")
    print("   " + _("The settings applied there are kept here."))
    try:
        _pause(_("Enter to close the preview..."))
    finally:
        # The server does not survive the screen that opened it: a tab left
        # behind must stop being able to write into the settings.
        opened.stop()


def _reset_to_defaults() -> None:
    """Gives the templates back to the repository, after saying what that undoes.

    The one question of the screen: the other keys undo themselves when pressed
    again, this one undoes every setting.
    """
    console.space()
    print(_("These settings will go back to what kotogen ships:"))
    for change in card_templates.differences():
        print(f"   {change}")
    console.space()
    if not _ask_yes_no(_("Put everything back to default")):
        return
    try:
        card_templates.reset()
    except OSError as exc:
        console.space()
        print(_("Erasing impossible ({reason}).").format(reason=exc))
        _pause(_("Enter to come back..."))
