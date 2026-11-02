"""Interactive assistant: run when `kotogen` is called with no argument.

Its menus only build the equivalent command line, parsed by argparse as usual,
so no logic is duplicated; in verbose mode ("v" setting or KOTOGEN_VERBOSE) that
command is shown after the generation (`cli._print_footer`). A command is a menu
of sources then the questions it leads to, and every step goes back to the
previous one, up to the main menu, which is here.

Each command has its dialogue in the module of its name. `screen` holds what
every screen is made of, `lists` the long lists one searches and ticks,
`catalogues` what listening and reading share, `status` the probe of Anki, and
`settings_menu` the settings, with the AI model in `models` and the history of
the sources in `history`.
"""

from __future__ import annotations

from kotogen import console, prefs
from kotogen.cli import format_cmd, output_format
from kotogen.i18n import _, quoted
from kotogen.interactive import status
from kotogen.interactive.audio import _audio_options, _audio_source
from kotogen.interactive.backup import _backup_mode, _backup_options
from kotogen.interactive.deck import _deck_mode, _deck_options
from kotogen.interactive.grammar import _grammar_options, _grammar_source
from kotogen.interactive.kanji import _kanji_options, _kanji_source
from kotogen.interactive.maintain import _maintain_mode, _maintain_options
from kotogen.interactive.reading import _reading_options, _reading_source
from kotogen.interactive.screen import _ask_yes_no, _Back, _dialog, _header, _menu, _pause
from kotogen.interactive.settings_menu import _settings
from kotogen.interactive.status import (
    _NAMES,
    ANKI_ONLY,
    IA_COMMANDS,
    _anki_state,
    _missing_for,
    _print_status,
    _refresh_anki,
    _still_missing,
    _visible_menu,
    _why_not,
)
from kotogen.interactive.vocab import _vocab_options, _vocab_source

# The last command, kept between calls of `interactive_argv`: its source menu
# reopens once it is over, and the main menu opens on its line.
_last_command: str | None = None

# Its argv, for the "c" key of the pause after it ran: that pause comes one call
# later, when the CLI has kept nothing of it.
_last_argv: list[str] | None = None


# Command -> (menu of sources, questions that follow), chained by `_dialog`.
_DIALOGS = {
    "kanji": (_kanji_source, _kanji_options),
    "vocab": (_vocab_source, _vocab_options),
    "grammar": (_grammar_source, _grammar_options),
    "audio": (_audio_source, _audio_options),
    "reading": (_reading_source, _reading_options),
    "maintain": (_maintain_mode, _maintain_options),
    "deck": (_deck_mode, _deck_options),
    "backup": (_backup_mode, _backup_options),
}


def interactive_argv(*, banner: bool = True) -> list[str] | None:
    """Main dialogue. Hands back the equivalent argv, or None if the user quits.

    `banner=False` is a return after a command: a key is awaited before wiping
    its output, and the menu of that command reopens rather than the main one.
    A dialogue left (Escape on its first menu, Ctrl+C) comes back here; "q", or
    Ctrl+C at the main menu or in the settings, quits."""
    global _last_command, _last_argv
    if not banner:
        # "c" is offered only in verbose mode, where `cli._print_footer` has just
        # printed the command above this pause.
        to_copy = (f"kotogen {format_cmd(_last_argv)}"
                   if _last_argv and prefs.verbose() else "")
        _pause(_("Enter to come back to the menu")
               + (_(", {key} to copy the command").format(key=quoted("c"))
                  if to_copy else "") + "...",
               to_copy=to_copy)

    try:
        # AnkiConnect is probed at the first menu only (`_anki_state`), never on a
        # redraw or a return from a command: see `status._anki`.
        # The menu opens on the line last left, back from the settings, a
        # dialogue or a command.
        command = _last_command
        # After a command, its source menu opens straight away: the only turn
        # that skips the main menu.
        direct = command is not None
        while True:
            if direct:
                direct = False
            else:
                _header()
                asked = len(status._skip_offered)
                anki = _anki_state()
                if len(status._skip_offered) != asked:
                    # The first probe asked about a missing note type under the
                    # banner: redraw rather than pile the menu under the question.
                    _header()
                _print_status(*anki)
                missing = _missing_for(anki=ANKI_ONLY, ai=IA_COMMANDS)
                visible = _visible_menu()
                column = max([13] + [console.width(_(name)) + 2
                                     for key, name, _desc in visible if key is not None])
                command = _menu(
                    "",
                    # The name is set flush left to line the descriptions up, in
                    # screen columns: a kanji takes two.
                    [(key, _(name) if key is None
                      else console.pad(_(name), column) + _(desc))
                     for key, name, desc in visible],
                    allow_quit=True,
                    # The settings get a screen of their own to keep this menu
                    # short; they and the update, about the program rather than
                    # the deck, stay apart from the commands.
                    extras=[(None, ""), ("s", _("Settings")), ("u", _("Update"))],
                    marks=dict.fromkeys(_anki_state()[1], "  (!)"),
                    disabled=missing,
                    default=command,
                )
                if command == "q":
                    return None
                if command == "s":
                    _settings()
                    continue
                if command == "u":
                    # No dialogue: the entry is the command, run the usual way.
                    # Forgetting the last command brings the main menu back next.
                    _last_command, _last_argv = None, ["update"]
                    console.space()
                    return ["update"]
                if command in missing and (
                        lacking := _still_missing(missing[command])):
                    # Still dimmed: say what it lacks, then redraw the menu.
                    _why_not(lacking, _(_NAMES[command]))
                    continue
            try:
                argv = _dialog(*_DIALOGS[command])
            except _Back:
                continue  # back onto the menu of commands
            except (KeyboardInterrupt, EOFError):
                # Ctrl+C cancels the dialogue, not the session: "q" here quits.
                console.space()
                print(_("Dialogue cancelled."))
                _pause(_("Enter to come back to the menu..."))
                continue
            break

        # Set once the dialogue is complete, so that one given up (Escape, Ctrl+C)
        # leaves the previous command remembered.
        _last_command = command

        # Only the generators writing TSV are asked about the send: `maintain`,
        # `deck` and `backup` work in Anki itself and say so when it is closed
        # (`anki.connect.UNREACHABLE`), and a JSON Lines file is not for Anki.
        if command not in ("maintain", "deck", "backup") and output_format() == "tsv":
            if prefs.auto_send():
                # Even with Anki closed: the send is tried at the end of the
                # generation, which says what became of it.
                argv.append("--send")
            # Probed again, Anki having perhaps changed state during the dialogue.
            # Closed, nothing is asked or said: the generation ends on the state
            # of things, path of the file included.
            elif _refresh_anki(offer_skip=False)[0].connected:
                if _ask_yes_no(_("Send the cards into Anki as well (AnkiConnect)")):
                    argv.append("--send")
    except (KeyboardInterrupt, EOFError):
        console.space()
        print(_("Cancelled."))
        return None

    # A blank line before the output of the command, unless the dialogue ended on
    # a menu, which already leaves one.
    console.space()
    _last_argv = argv
    return argv
