"""The main screen of the assistant: banner, status line, the loop back after a
command, navigation, what it greys without Anki or a key, the argv it builds."""

import builtins
import io
import os
import re
import sys
import time

import pytest

from kotogen import console, interactive, prefs
from kotogen.anki.connect import AnkiStatus
from kotogen.cli import build_parser
from kotogen.interactive import interactive_argv
from kotogen.interactive.screen import BANNER
from menus import *  # the fixtures every menu test starts from, and its helpers

# ── Ways out ──────────────────────────────────────────────────────────────────

def test_quit_returns_none(monkeypatch):
    feed(monkeypatch, ["q"])
    assert interactive_argv() is None


def test_ctrl_c_returns_none(monkeypatch):
    def interrupt(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr(builtins, "input", interrupt)
    assert interactive_argv() is None


def test_a_skipped_command_leaves_the_menu(monkeypatch, capsys):
    monkeypatch.setenv("KOTOGEN_SKIP", "grammar")
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        _fake_status(AnkiStatus(connected=True, profile="Test")))
    feed(monkeypatch, ["q"])
    interactive_argv()

    out = capsys.readouterr().out
    assert "Grammar" not in out            # neither the menu entry nor the warning
    assert "Hidden commands: grammar" in out
    assert "Vocabulary" in out             # the others stay on offer



# ── A note type missing at start-up ───────────────────────────────────────────

def _offered(monkeypatch, answer: str, installed: bool = True) -> tuple[dict, list]:
    """Asks about a missing Kanji type, answering `answer`; hands back what is
    still missing and the argv the install was run with."""
    monkeypatch.setattr(interactive.status.system, "can_ask", lambda: True)
    # Answered through `ask_choice`, the numbered path, on every platform.
    monkeypatch.setattr("kotogen.keyboard.available", lambda: False)
    monkeypatch.setattr(interactive.status, "_pause", lambda message: None)
    monkeypatch.setattr(interactive.status, "_skip_offered", set())
    monkeypatch.setattr("kotogen.exporter.ask_choice", lambda *a, **k: answer)
    ran = []
    monkeypatch.setattr("kotogen.anki.notetypes.run_deck", lambda args: ran.append(args.only))
    monkeypatch.delenv("KOTOGEN_SKIP", raising=False)
    types = CONNECTED.notetypes - ({"Kanji"} if not installed else set())
    monkeypatch.setattr("kotogen.interactive.status.anki_status", _fake_status(
        AnkiStatus(connected=True, profile="Test", notetypes=frozenset(types))))
    missing = {"kanji": "Kanji"}
    interactive.status._offer_skip(missing)
    return missing, ran


def test_a_missing_note_type_can_be_installed_on_the_spot(monkeypatch):
    """Installing only that type: the whole install would also question every
    other type of the profile."""
    missing, ran = _offered(monkeypatch, "i")
    assert ran == [["kanji"]]
    assert missing == {}


def test_an_install_that_did_not_take_leaves_the_command_marked(monkeypatch):
    missing, ran = _offered(monkeypatch, "i", installed=False)
    assert ran == [["kanji"]]
    assert missing == {"kanji": "Kanji"}


def test_a_missing_note_type_can_hide_its_command(monkeypatch):
    missing, ran = _offered(monkeypatch, "h")
    assert ran == []
    assert missing == {}
    assert os.environ["KOTOGEN_SKIP"] == "kanji"


def test_later_changes_nothing(monkeypatch):
    missing, ran = _offered(monkeypatch, "l")
    assert (missing, ran) == ({"kanji": "Kanji"}, [])
    assert "KOTOGEN_SKIP" not in os.environ

def test_a_menu_title_opens_on_a_blank_line(monkeypatch, capsys):
    feed(monkeypatch, ["1"])
    console.watch()
    print("a question asked just before")
    interactive.screen._menu("Which podcast?", [("a", "A")], default=1)
    assert "just before\n\nWhich podcast?" in capsys.readouterr().out


def test_a_menu_does_not_double_the_blank_line_of_the_previous_one(monkeypatch, capsys):
    """A menu ends on a blank line, so the next title must not add a second."""
    feed(monkeypatch, ["1"])
    console.watch()
    print("a menu left behind\n")
    interactive.screen._menu("Which podcast?", [("a", "A")], default=1)
    assert "behind\n\nWhich podcast?" in capsys.readouterr().out


def test_the_dialogue_closes_on_a_single_blank_line(monkeypatch, tmp_path, capsys):
    """The launched command opens on its own blank line, so the dialogue must end
    on a counted one: the newline the user types does not go through
    `sys.stdout`, and the prompt would pass for unfinished."""
    audio = tmp_path / "14.mp3"
    audio.write_bytes(b"")
    feed(monkeypatch, ["4", "5", str(audio), "", ""])
    console.watch()
    assert interactive_argv() == ["audio", str(audio)]
    assert console.ends_blank()


# ── Welcome screen ────────────────────────────────────────────────────────────

def test_banner_is_drawn_without_touching_a_captured_screen(monkeypatch, capsys):
    """The banner heads the menu; outside a terminal, no wiping code pollutes the
    output (and the return to the menu waits for no key)."""
    feed(monkeypatch, ["q"])
    interactive_argv(banner=False)
    out = capsys.readouterr().out
    assert BANNER in out
    assert "\033[" not in out


def test_ready_status_holds_one_line(monkeypatch, capsys):
    """AI and Anki fit on one line of facts: no "everything is ready", and no list
    of decks, since a missing deck is created at the send."""
    feed(monkeypatch, ["q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert "Anki [Test]" in _status_bar(out)
    assert "everything is ready" not in out
    assert "!!" not in out
    assert "Decks" not in out


def test_api_key_present_is_announced_with_the_model(monkeypatch, capsys):
    """The welcome screen says what will be called, without ever showing the key."""
    feed(monkeypatch, ["q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert _status_bar(out).startswith(f"AI [{MODEL} via openrouter]")
    assert "key present" not in out
    assert "sk-or-test" not in out


def test_the_menu_holds_the_commands_then_what_is_not_one(monkeypatch, capsys):
    """The commands under their two subheadings, then the settings, the update and
    the way out, and nothing else."""
    feed(monkeypatch, ["q"])
    interactive_argv()
    out = capsys.readouterr().out
    entries = [line.strip() for line in out.splitlines() if line.strip()[1:2] == "."]
    assert [entry[:2] for entry in entries] == [f"{n}." for n in range(1, 9)] \
                                               + ["s.", "u.", "q."]
    assert entries[-3:] == ["s. Settings", "u. Update", "q. Quit"]


def test_the_update_entry_is_the_command_and_asks_nothing(monkeypatch):
    """No dialogue, just the command line. The last command is forgotten, so the
    screen after it is the main menu, not the previous command's dialogue."""
    feed(monkeypatch, ["u"])
    assert interactive_argv() == ["update"]
    assert interactive._last_command is None


def test_settings_are_ordered_by_what_their_key_opens(monkeypatch, capsys):
    """Settings by kind: the seven that open a choice, the five that toggle on the
    spot, then the probe that sets nothing. The letters are explained in
    `settings_menu._settings_entries`.

    The two languages sit one under the other, shown the same way. Values sit in
    a column; this screen alone has no status line, which would only repeat it."""
    feed(monkeypatch, ["s", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    screen = out[out.rindex("\nSettings\n"):]
    screen = screen[:screen.index("AI [")]  # the menu, redrawn just afterwards
    settings = [line.strip() for line in screen.splitlines()
                if line.strip()[1:2] == "."]
    assert [entry[:2] for entry in settings] == ["k.", "m.", "o.", "c.", "h.",
                                                 "l.", "g.", "s.", "v.", "q.",
                                                 "i.", "p.", "a.", "b."]
    assert settings[0].endswith("OPENROUTER_API_KEY set")
    assert settings[1].endswith(f"{MODEL} via openrouter")
    # The currency, and nothing more: the rate applied is on its own screen.
    assert settings[3].endswith("USD $")
    assert settings[4].endswith("empty")
    # The code (what KOTOGEN_LANG holds) and the name; the language of the cards
    # is shown the same way, with the same default.
    assert settings[5].endswith("en - English")
    assert settings[6].endswith("en - English")
    assert settings[7].endswith("off")
    # One word each: nothing is typed on this screen, "q" and "i" move one notch.
    assert settings[9].endswith("none")
    assert settings[10].endswith("ask")
    # Doubtful cards start by asking, like the picture, and show the same word.
    assert settings[11].endswith("ask")
    assert settings[12].endswith("connected to Test")


def test_the_three_natures_of_settings_are_set_apart(monkeypatch, capsys):
    """A blank line after the choices and another after the toggles: otherwise
    nothing tells a key that opens a list from one that acts at once."""
    feed(monkeypatch, ["s", "b", "q"])
    interactive_argv()
    out = capsys.readouterr().out
    screen = out[out.rindex("\nSettings\n"):]
    screen = screen[:screen.index("AI [")]
    keys = [line.strip()[:1] if line.strip() else "" for line in screen.splitlines()
            if not line.strip() or line.strip()[1:2] == "."]
    # After `g`, the last of the choices, and after `p`, the last toggle.
    assert keys[keys.index("g") + 1] == ""
    assert keys[keys.index("p") + 1] == ""


def test_session_cost_follows_the_status_bar(monkeypatch, capsys):
    """The running total of the session is read under the status line, at the same
    left margin."""
    from kotogen.ai_client import session_usage

    usage = session_usage()
    monkeypatch.setattr(usage, "calls", 2)
    monkeypatch.setattr(usage, "prompt_tokens", 7000)
    monkeypatch.setattr(usage, "completion_tokens", 1400)
    monkeypatch.setattr(usage, "seconds", 74.0)
    feed(monkeypatch, ["q"])
    interactive_argv()
    out = capsys.readouterr().out
    lines = out.splitlines()
    session = lines[lines.index(_status_bar(out)) + 1]
    # Word for word the line that ends a command, with no "session" label: under
    # the status line, it is plainly the assistant's.
    assert session == "2 AI calls (8,400 tokens, 1 min 14 s)"


def test_missing_api_key_is_flagged_before_the_dialog(monkeypatch, capsys):
    """With no key, the menu says so before any dialogue, in the AI bracket alone:
    no "!!" and no line naming the variable, which the settings and the command
    asking for the key already show."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    feed(monkeypatch, ["q"])
    interactive_argv()
    out = capsys.readouterr().out
    assert _status_bar(out).startswith("AI [key to be set]")
    assert "!!" not in out
    assert "OPENROUTER_API_KEY" not in out


def test_api_key_entry_is_kept_and_saved(monkeypatch, capsys):
    """"k" takes the key, holds it and records it, without asking permission: one
    does not go into the settings for a single command."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-or-typed")
    written: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda name, value: written.append((name, value)) or "/tmp/secrets.env")
    # settings; "k"; back to the menu; quit - no question in between
    feed(monkeypatch, ["s", "k", "b", "q"])
    assert interactive_argv() is None
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-typed"
    assert written == [("OPENROUTER_API_KEY", "sk-or-typed")]
    out = capsys.readouterr().out
    assert "sk-or-typed" not in out          # the key never shows
    assert "Record it" not in out            # nor a question about keeping it
    # The menu redrawn reflects it, in one single place: the "!!" is gone.
    assert not _status_bar(out).endswith("!!")
    assert "API key (" not in out


def test_a_failed_write_keeps_the_setting_for_the_session(monkeypatch, capsys):
    """A setting that cannot be written (disk full, read-only folder) still holds
    for the session, and the screen says so."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-or-typed")

    def refusal(name, value):
        raise OSError("read-only")

    monkeypatch.setattr("kotogen.settings.write", refusal)
    feed(monkeypatch, ["s", "k", "b", "q"])
    interactive_argv()
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-typed"
    out = capsys.readouterr().out
    assert "Write impossible (read-only)" in out
    assert "holds for this session only" in out


# ── Navigation (going back) ───────────────────────────────────────────────────

def test_back_from_a_source_menu_returns_to_the_main_menu(monkeypatch, capsys):
    feed(monkeypatch, ["2", "b", "q"])
    assert interactive_argv() is None
    out = capsys.readouterr().out
    assert "Vocabulary cards" in out
    # The main menu was indeed redrawn after the way back.
    assert out.count("Make cards") == 2


def test_back_from_a_question_returns_to_the_source_menu(monkeypatch):
    # vocab; "a word"; b; a URL; 8 words; no send
    feed(monkeypatch, ["2", "1", "b", "4", "https://ja.wikipedia.org/wiki/寿司",
                       "8", ""])
    assert interactive_argv() == [
        "vocab", "https://ja.wikipedia.org/wiki/寿司", "--count", "8",
    ]


def test_back_works_from_a_later_question(monkeypatch):
    # grammar; a file of rules; b on its path; "one rule"; のに; cards; no send
    feed(monkeypatch, ["3", "4", "b", "1", "のに", "", ""])
    assert interactive_argv() == ["grammar", "のに"]


def test_back_does_not_probe_ankiconnect_again(monkeypatch):
    """Going back redraws the menu without probing Anki: a probe may take seconds,
    and moving between menus changes nothing in Anki."""
    probes = []
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        lambda *, refresh=False, timeout=2: (probes.append(refresh)
                                                             or CONNECTED))
    # vocab; back; grammar; back; quit
    feed(monkeypatch, ["1", "b", "2", "b", "q"])
    assert interactive_argv() is None
    assert probes == [True]


def test_returning_to_the_menu_does_not_probe_ankiconnect_again(monkeypatch):
    """The menu reopened after a command reuses the known state: Anki is probed at
    start-up only."""
    probes = []
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        lambda *, refresh=False, timeout=2: (probes.append(refresh)
                                                             or CONNECTED))
    feed(monkeypatch, ["q"])
    interactive_argv()
    assert probes == [True]
    feed(monkeypatch, ["q"])
    interactive_argv(banner=False)
    assert probes == [True]


def test_menu_key_retests_ankiconnect(monkeypatch, capsys):
    """"a" asks for the state again, to see an Anki opened after the launch."""
    states = iter([AnkiStatus(connected=False), CONNECTED])
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        lambda *, refresh=False, timeout=2: next(states))
    feed(monkeypatch, ["s", "a", "b", "q"])  # settings; "a"; back; quit
    assert interactive_argv() is None
    out = capsys.readouterr().out
    # First drawing: Anki closed; after "a", the bracket names the profile.
    assert out.index("Anki [not connected]") < out.index("Settings")
    assert _status_bar(out).endswith("Anki [Test]")


def test_ctrl_c_in_a_dialog_returns_to_the_menu(monkeypatch, capsys):
    """Ctrl+C cancels the dialogue in hand; only "q" puts an end to the session."""
    feed(monkeypatch, ["1", KeyboardInterrupt, "q"])
    assert interactive_argv() is None
    assert "Dialogue cancelled." in capsys.readouterr().out


# ── AnkiConnect unavailable ───────────────────────────────────────────────────

def test_send_question_skipped_when_anki_down(monkeypatch):
    # Anki closed: the send question is not asked (no answer supplied)
    anki_down(monkeypatch)
    feed(monkeypatch, ["2", "1", "食べる"])
    assert interactive_argv() == ["vocab", "食べる"]


def test_maintain_is_greyed_out_when_anki_down(monkeypatch, capsys):
    """Without Anki, Corrections is dimmed but keeps its number and gets no note
    (the status line says Anki is down): pressing it says what to do."""
    anki_down(monkeypatch)
    feed(monkeypatch, ["q"])
    interactive_argv()

    out = capsys.readouterr().out
    assert re.search(r"^ *6\. Corrections +marked cards: flags, leeches$", out,
                     re.MULTILINE)
    assert "\033[" not in out          # the half-tone is only laid on a terminal


def test_numbering_keeps_its_place_when_an_entry_is_greyed(monkeypatch):
    """The numbers do not move with the state of Anki: a key learnt with Anki open
    must open the same entry with Anki closed."""
    anki_down(monkeypatch)
    # 7 = Templates, 5 = Decks and types: the same numbers as with Anki open.
    feed(monkeypatch, ["7", "5", "b", "b", "q"])
    assert interactive_argv() is None


def test_a_greyed_entry_says_what_it_lacks_when_chosen(monkeypatch, capsys):
    """Chosen all the same, the dimmed entry asks Anki again, then opens onto what
    it lacks and what to check - then the menu comes back."""
    anki_down(monkeypatch)
    feed(monkeypatch, ["6", "q"])
    assert interactive_argv() is None

    out = capsys.readouterr().out
    assert "Corrections needs Anki." in out
    assert ("Anki does not answer  -> is Anki open, with the AnkiConnect add-on"
            " installed?") in out


def test_a_greyed_entry_opens_once_anki_answers(monkeypatch):
    """Anki opened after the menu was drawn: choosing the dimmed line probes
    again, and it opens as if it had never been dimmed."""
    probes = iter([AnkiStatus(connected=False), CONNECTED])
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        lambda *, refresh=False, timeout=2: next(probes))
    feed(monkeypatch, ["6", "2", "all", "all"])
    assert interactive_argv()[0] == "maintain"


def test_a_refused_key_is_not_asked_whether_anki_is_open(monkeypatch, capsys):
    """Anki answers but refuses the key: asking whether it is open would send the
    user off to open what is open. The screen names the setting instead."""
    monkeypatch.setattr("kotogen.interactive.status.anki_status",
                        lambda *, refresh=False, timeout=2:
                        AnkiStatus(connected=False, key_refused=True))
    feed(monkeypatch, ["6", "q"])
    assert interactive_argv() is None

    out = capsys.readouterr().out
    assert "AnkiConnect refuses the key  -> setting KOTOGEN_ANKICONNECT_KEY" in out
    assert "is Anki open" not in out


def test_ai_commands_are_greyed_without_a_key(monkeypatch, capsys):
    """With no key, the four generating commands are dimmed: the command would ask
    for the key anyway, but only after the whole dialogue."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    feed(monkeypatch, ["2", "q"])
    assert interactive_argv() is None

    out = capsys.readouterr().out
    assert re.search(r"^ *2\. Vocabulary +words, a web page, a text file or a PDF$",
                     out, re.MULTILINE)
    # One warning: the reason, then its way out on the very next line, flush left.
    assert ('Vocabulary needs an API key.\n'
            'OPENROUTER_API_KEY missing  -> the settings, key "k"\n') in out


def test_the_two_lacks_add_up_on_handling_the_marks(monkeypatch, capsys):
    """The line carries no mark of its own, the screen details both lacks. The
    Corrections entry itself stays open: looking at the deck calls no model."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("KOTOGEN_MODEL", raising=False)
    feed(monkeypatch, ["6", "2", "b", "q"])
    assert interactive_argv() is None

    out = capsys.readouterr().out
    assert re.search(r"^ *6\. Corrections +marked cards: flags, leeches$", out,
                     re.MULTILINE)
    assert "Handle needs an API key and a model.\nOPENROUTER_API_KEY missing" in out
    # Arrows in one column: each lack on the left, where to set it on the right.
    arrows = {line.index("->") for line in out.splitlines() if "->" in line}
    assert len(arrows) == 1
    assert "No model chosen" in out


def test_deck_menu_greys_what_needs_anki(monkeypatch, capsys):
    """Install and Compare need the profile; the preview and the two settings
    screens do not, so the main menu's entry stays open."""
    anki_down(monkeypatch)
    feed(monkeypatch, ["7", "b", "q"])
    assert interactive_argv() is None

    out = capsys.readouterr().out
    assert re.search(r"^ *1\. Preview ", out, re.MULTILINE)
    assert re.search(r"^ *2\. Appearance ", out, re.MULTILINE)
    assert re.search(r"^ *3\. Install .*overwriting$", out, re.MULTILINE)
    assert re.search(r"^ *4\. Compare .*anything$", out, re.MULTILINE)
    assert re.search(r"^ *5\. Decks and types", out, re.MULTILINE)


def test_backup_menu_greys_what_needs_anki(monkeypatch, capsys):
    """Listing reads the folder of the backups; the other four, the deck. All four
    keep their number, and say so when one chooses them."""
    anki_down(monkeypatch)
    feed(monkeypatch, ["8", "3"])   # 8 = Backup, 3 = List
    assert interactive_argv() == ["backup", "--list"]

    out = capsys.readouterr().out
    assert re.search(r"^ *3\. List", out, re.MULTILINE)
    for greyed in ("Back up", "Archive", "Compare", "Restore"):
        assert re.search(rf"^ *\d+\. {greyed} ", out, re.MULTILINE)
    assert "(Anki not connected)" not in out


def test_a_greyed_backup_entry_comes_back_to_its_own_menu(monkeypatch, capsys):
    """The explanation hands back to the backup menu, which was never left, not to
    the main menu."""
    anki_down(monkeypatch)
    feed(monkeypatch, ["8", "1", "3"])   # Backup; Back up (dimmed); List
    assert interactive_argv() == ["backup", "--list"]

    out = capsys.readouterr().out
    assert "This command needs Anki." in out


# ── The wait shown ────────────────────────────────────────────────────────────

def test_the_spinner_leaves_the_screen_as_it_found_it(monkeypatch):
    """The spinner wipes itself: the screen still ends on the menu's blank line,
    so a first launch (which reads a catalogue) spaces its menus like the next."""
    import threading

    class FakeTty(io.StringIO):
        def isatty(self):
            return True

    stream = console._Watcher(FakeTty())
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(interactive.screen, "_SPINNER_PERIOD", 0.01)
    print("a menu left behind\n")   # a menu closes on a blank line
    before = stream.tail

    worker = threading.Thread(target=lambda: time.sleep(0.05))
    worker.start()
    interactive.screen._spin_while_alive(worker, "Catalogue...")

    assert stream.tail == before
    assert console.ends_blank()


# ── Loop of the interactive mode (main) ───────────────────────────────────────

def test_main_returns_to_menu_after_command(monkeypatch):
    from kotogen import cli
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    runs = []
    monkeypatch.setattr(cli, "_run", lambda argv, **kwargs: runs.append(argv))
    # Vocab with no send; then "b" from the vocab menu, and quit.
    feed(monkeypatch, ["2", "1", "食べる", "", "b", "q"])
    cli.main()
    assert runs == [["vocab", "食べる"]]


def test_main_survives_command_error(monkeypatch):
    """A command that fails (sys.exit of a generator) brings one back to the menu."""
    from kotogen import cli
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    runs = []

    def failing_run(argv, **kwargs):
        runs.append(argv)
        raise SystemExit("No cards generated.")

    monkeypatch.setattr(cli, "_run", failing_run)
    # The failure hands back to the vocab menu: no "2" of the main menu to type
    # again before the second card.
    feed(monkeypatch, ["2", "1", "食べる", "", "1", "飲む", "", "b", "q"])
    cli.main()  # must not propagate SystemExit
    assert runs == [["vocab", "食べる"], ["vocab", "飲む"]]


def test_a_finished_command_reopens_its_own_menu(monkeypatch, capsys):
    """A finished command reopens its own menu, not the welcome screen, on the
    line chosen there: listing the backups again takes a single Enter."""
    from kotogen import cli
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    runs = []
    monkeypatch.setattr(cli, "_run", lambda argv, **kwargs: runs.append(argv))
    feed(monkeypatch, ["8", "3", "3", "b", "q"])
    cli.main()

    assert runs == [["backup", "--list"], ["backup", "--list"]]
    out = capsys.readouterr().out
    # The backup menu three times (two lists, then back), the main menu twice (in
    # and out).
    assert out.count("Backup - what to do?") == 3
    assert out.count("Look after a deck") == 2
    assert "> [3]" in out                  # reopened on "List the backups"


def test_the_main_menu_reopens_on_the_command_one_comes_out_of(monkeypatch, capsys):
    from kotogen import cli
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    monkeypatch.setattr(cli, "_run", lambda argv, **kwargs: None)
    feed(monkeypatch, ["8", "3", "b", "q"])
    cli.main()

    # The first main menu has no default (a bare ">"); the one quit from
    # offers the eighth line, the one just closed.
    assert "> [8]" in capsys.readouterr().out


def test_equivalent_command_stays_quiet_by_default(monkeypatch, capsys):
    from kotogen import cli
    from kotogen.generators import vocab

    monkeypatch.setattr(vocab, "run_vocab", lambda a: None)
    cli._run(["vocab", "食べる"], recap=True)
    assert "Equivalent command" not in capsys.readouterr().out


def test_verbose_brings_back_the_equivalent_command(monkeypatch, capsys):
    from kotogen import cli
    from kotogen.generators import vocab

    monkeypatch.setattr(prefs, "_verbose", True)
    monkeypatch.setattr(vocab, "run_vocab", lambda a: None)
    cli._run(["vocab", "食べる"], recap=True)
    assert "Equivalent command: kotogen vocab 食べる" in capsys.readouterr().out


def test_menu_key_toggles_verbose(monkeypatch):
    # settings; "v" toggles verbose mode; back; vocab
    feed(monkeypatch, ["s", "v", "b", "2", "1", "食べる", ""])
    assert interactive_argv() == ["vocab", "食べる"]
    assert prefs.verbose() is True


def test_footer_recaps_the_command(capsys):
    """Interactive mode: the equivalent command closes the run, right under the
    command's last line, with no blank line of its own."""
    from kotogen import ai_client, cli
    ai_client.reset_run_usage()
    console.watch()
    print("the last line of the command")
    cli._print_footer(["vocab", "食べる 猫"])
    # Arguments with spaces are quoted again: the line is pasted back as it is.
    assert capsys.readouterr().out.endswith(
        'command\nEquivalent command: kotogen vocab "食べる 猫"\n')


def test_footer_silent_outside_the_wizard(capsys):
    """On the command line (recap absent), with no AI call and no wait, nothing to
    say."""
    from kotogen import ai_client, cli
    ai_client.reset_run_usage()
    cli._print_footer(None)
    assert capsys.readouterr().out == ""


def test_footer_never_times_a_command_without_ai(monkeypatch, capsys):
    """A duration is only printed beside the tokens and the price: alone, as after
    a `backup`, it compares to nothing."""
    from kotogen import ai_client, cli
    clock = iter([0.0, 92.0])
    monkeypatch.setattr(ai_client.time, "monotonic", lambda: next(clock))
    ai_client.reset_run_usage()
    cli._print_footer(None)
    assert capsys.readouterr().out == ""


def test_a_failed_command_without_ai_reports_nothing(monkeypatch, capsys):
    from kotogen import ai_client, cli
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(ai_client.time, "monotonic", lambda: next(clock))
    ai_client.reset_run_usage()
    cli._print_footer(None)
    assert capsys.readouterr().out == ""


def test_a_failed_command_still_reports_what_it_spent(monkeypatch, capsys):
    """The calls made are paid for, so the bill shows even after a failure."""
    from kotogen import ai_client, cli
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(ai_client.time, "monotonic", lambda: next(clock))
    ai_client.reset_run_usage()
    ai_client.run_usage().add(12_000, 3_400, 0.0182)
    cli._print_footer(None)
    assert "1 AI call (" in capsys.readouterr().out


# ── Compatibility with the CLI parser ─────────────────────────────────────────

@pytest.mark.parametrize("answers", [
    ["1", "1", "学生", "y"],                     # kanji of a word
    ["1", "3", "", "", "y"],                    # kanji of a JLPT level
    ["2", "1", "食べる", "y"],                  # vocab + --send
    ["2", "4", "https://www3.nhk.or.jp/news/easy/k1/k1.html", "8", ""],  # vocab, NHK URL
    ["2", "2", "3", "", ""],                    # vocab from a JLPT level
    ["2", "3", "9", "fruits", "", "", ""],      # vocab from a theme typed
    ["3", "1", "〜たら", "3", "y"],             # full grammar
    ["3", "2", "", "", "", ""],                 # grammar from a JLPT level
    ["4", "", "", "6", "", "2", ""],            # audio nhk, customised
    ["4", "", "", "", "150", "", ""],           # audio nhk with a max duration
    ["5", "", "", "", "", "4", "y"],            # reading nhk
    ["6", "2", "red leech", "red"],             # maintain auto on a single target
    ["6", "2", "all", "all"],                   # maintain, everything automatic
    ["6", "2", "", ""],                         # maintain, everything by hand
])
def test_generated_argv_is_parseable(monkeypatch, answers):
    feed(monkeypatch, answers)
    argv = interactive_argv()
    args = build_parser().parse_args(argv)  # must not raise SystemExit
    assert args.command in ("kanji", "vocab", "grammar", "audio", "reading", "maintain")


@pytest.mark.parametrize("answers, command", [
    (["2", "5", "{doc}", "50", "", ""], "vocab"),    # bounded (+ default batch)
    (["5", "5", "{doc}", "", "", ""], "reading"),    # a local PDF
])
def test_pdf_argv_are_parseable(monkeypatch, tmp_path, answers, command):
    doc = tmp_path / "course.pdf"
    doc.write_bytes(b"%PDF-1.7")
    feed(monkeypatch, [a.format(doc=doc) for a in answers])
    args = build_parser().parse_args(interactive_argv())
    assert args.command == command


# ── The two columns of a long list ──────────────────────────────

def _column_of(page, rights):
    """The screen column each right-hand part begins at, one per line."""
    return {console.width(label[:label.index(right)])
            for (_key, label), right in zip(page, rights)}


def test_a_page_lines_its_second_column_up_in_screen_columns():
    # A kana takes two columns where `len` counts one: the reason the page is laid
    # out here rather than padded at the call site.
    rights = ["Copule", "Ceci", "Adjectifs"]
    page = interactive.lists._laid_out([("a", "だ", rights[0]),
                                  ("b", "これ", rights[1]),
                                  ("c", "い-Adjectives", rights[2])])
    assert len(_column_of(page, rights)) == 1


def test_the_column_is_taken_from_the_page_and_not_from_the_list():
    # The same entry, alone and then beside a long one: its meaning moves, and
    # that is what keeps a page of short rules narrow.
    narrow = interactive.lists._laid_out([("a", "だ", "Copule")])
    wide = interactive.lists._laid_out([("a", "だ", "Copule"),
                                  ("b", "これはとても長い", "Long")])
    assert (max(_column_of(narrow, ["Copule"]))
            < max(_column_of(wide, ["Copule"])))
    assert len(_column_of(wide, ["Copule", "Long"])) == 1


def test_an_entry_in_one_part_goes_through_untouched():
    # The free entry of a search that found nothing is a sentence, not a line
    # of a table.
    assert interactive.lists._laid_out([("k", "Work on it anyway")]) == [
        ("k", "Work on it anyway")]


def test_a_rule_is_searched_by_its_meaning_as_well_as_by_its_name(monkeypatch):
    # The column separates the two on screen; it separates nothing here.
    entries = [("slug", "  N5  だ", "Être (copule)"),
               ("other", "  N5  これ", "Ceci")]
    feed(monkeypatch, ["1"])
    assert interactive.lists._tickable_pages("T", entries) == ["slug"]


def test_a_menu_line_from_the_web_cannot_drive_the_terminal():
    """A Tadoku or 青空文庫 title is written by a web page: an ESC in it would
    clear the screen or retitle the window."""
    from kotogen import menu

    view = menu.compose("青空文庫\x1b]0;owned\x07", [("w1", "ごん狐\x1b[2J"), (None, "棚\x9b")],
                        extras=[("s", "Search\x1b[31m")])
    assert not any(char in line for line in view.lines for char in "\x1b\x07\x9b")
    assert any("ごん狐[2J" in line for line in view.lines)


class _Probe:
    """A thread still probing: `join` records its timeout, and may raise."""

    def __init__(self, raising: BaseException | None = None, turns: int = 2):
        self.raising, self.turns, self.joins = raising, turns, []

    def is_alive(self) -> bool:
        return self.turns > 0

    def join(self, timeout=None):
        self.joins.append(timeout)
        self.turns -= 1
        if self.raising is not None:
            raise self.raising


def test_a_probe_waited_for_outside_a_terminal_lets_ctrl_c_through(monkeypatch):
    """A bare `join()` holds Ctrl+C back on Windows until the probe ends."""
    probe = _Probe()
    interactive.screen._spin_while_alive(probe, "Anki...")
    assert probe.joins and None not in probe.joins


def test_a_probe_cut_by_ctrl_c_takes_its_frame_off_the_line(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    with pytest.raises(KeyboardInterrupt):
        interactive.screen._spin_while_alive(_Probe(KeyboardInterrupt()), "Anki...")
    assert "\r" + " " * (console.width("Anki...") + 2) + "\r" in capsys.readouterr().out
