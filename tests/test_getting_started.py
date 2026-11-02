"""The guide a newcomer meets before the menu: when it opens, how it goes from
page to page, and what each page sets."""

import re
import sys

import pytest

from kotogen import cli, getting_started, i18n, interactive, menu, prerequisites
from kotogen.anki import templates as card_templates
from kotogen.anki.connect import AnkiStatus
from menus import *  # the fixtures every menu test starts from, and its helpers


@pytest.fixture(autouse=True)
def modules_installed(monkeypatch):
    """Every optional module there, FFmpeg included, whatever the machine has:
    the tests that want some missing say so."""
    monkeypatch.setattr(prerequisites, "missing", lambda: [])
    monkeypatch.setattr(prerequisites, "ffmpeg_missing", lambda: False)


@pytest.fixture
def terminal(monkeypatch):
    """Somebody in front of the screen: the only case the guide opens in."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)


@pytest.fixture
def written(monkeypatch):
    """What the guide lays down for the next launches."""
    held: list = []
    monkeypatch.setattr("kotogen.settings.write",
                        lambda name, value: held.append((name, value)))
    return held


@pytest.fixture
def language_set(monkeypatch):
    """The first page done, so that the guide opens on the one under test."""
    monkeypatch.setenv("KOTOGEN_LANG", "en")


def _missing_types(monkeypatch) -> None:
    """Anki open on a new profile: two note types are not there yet."""
    state = AnkiStatus(connected=True, profile="Test", decks=CONNECTED.decks,
                       notetypes=CONNECTED.notetypes - {"Kanji", "Vocabulary"})
    monkeypatch.setattr("kotogen.interactive.status.anki_status", _fake_status(state))


def _pages(out: str) -> list[str]:
    """The titles of the pages shown, in order: the line two below the mark."""
    lines = out.splitlines()
    return [lines[i + 2] for i, line in enumerate(lines)
            if line.strip() == getting_started._HERE]


# -- When it opens ------------------------------------------------------------

def test_a_launch_in_a_terminal_is_the_first_until_one_has_been(terminal):
    assert getting_started.first_launch()


def test_a_script_never_meets_it(monkeypatch):
    """Without a terminal there is nobody to set anything."""
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert not getting_started.first_launch()


def test_a_launch_after_the_first_is_not_one(monkeypatch, terminal):
    anki_down(monkeypatch)
    monkeypatch.setenv(getting_started.ENV_VAR, "0")
    assert not getting_started.first_launch()


def test_it_is_needed_without_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert getting_started.needed()


def test_it_is_needed_without_a_model(monkeypatch):
    monkeypatch.delenv("KOTOGEN_MODEL")
    assert getting_started.needed()


def test_it_is_not_needed_once_the_key_and_anki_are_there():
    """The language does not hold it open: English writes nothing, and with a key
    and a deck there is nothing left to set up."""
    assert not getting_started.needed()


def test_it_is_needed_while_anki_is_silent(monkeypatch):
    anki_down(monkeypatch)
    assert getting_started.needed()


def test_it_is_needed_while_a_note_type_is_missing(monkeypatch):
    _missing_types(monkeypatch)
    assert getting_started.needed()


def test_its_probe_asks_nothing_about_the_note_types(monkeypatch, capsys):
    """The guide installs them all at once, not with the menu's question per type."""
    _missing_types(monkeypatch)
    feed(monkeypatch, [])  # a question would find no answer and raise
    getting_started.needed()
    assert "does not exist in this profile" not in capsys.readouterr().out


# -- The bar ------------------------------------------------------------------

_SEQUENCE = re.compile(r"\x1b\[[0-9;]*m")


@pytest.mark.parametrize("ansi", [False, True])
def test_the_bar_fills_by_what_is_done(monkeypatch, language_set, ansi):
    """The half-tone sequences print nothing: the mark is placed by what is
    seen, here with them on (every terminal outside Windows) and off."""
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setattr(menu, "ansi_ready", lambda: ansi)
    names, bar, mark = getting_started._bar(1)
    names, bar = _SEQUENCE.sub("", names), _SEQUENCE.sub("", bar)
    first = len("Language") + getting_started._GAP
    second = len("API key") + getting_started._GAP
    assert bar.strip().startswith(getting_started._FULL * first
                                  + getting_started._EMPTY * second)
    # The mark sits under the page one is on, the second here.
    assert mark.index(getting_started._HERE) == names.index("API key") + len("API key") // 2


def test_a_step_done_has_its_name_in_half_tone(monkeypatch, language_set):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setattr(menu, "ansi_ready", lambda: True)
    names = getting_started._bar(0)[0]
    assert menu.dim("Language") in names
    assert menu.dim("API key") not in names


# -- From page to page --------------------------------------------------------

def test_it_opens_on_the_first_step_to_do(monkeypatch, capsys, language_set):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    feed(monkeypatch, ["m"])
    getting_started.run()
    assert _pages(capsys.readouterr().out) == ["API key"]


def test_a_step_skipped_moves_on(monkeypatch, capsys):
    feed(monkeypatch, ["2", "m"])
    getting_started.run()
    assert _pages(capsys.readouterr().out) == ["Language", "API key"]


def test_back_goes_to_the_page_before(monkeypatch, capsys, language_set):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    feed(monkeypatch, ["b", "m"])
    getting_started.run()
    assert _pages(capsys.readouterr().out) == ["API key", "Language"]


def test_back_from_the_first_page_leaves_for_the_menu(monkeypatch):
    feed(monkeypatch, ["b"])  # one more question would find no answer
    getting_started.run()


def test_the_last_page_leaves_for_the_menu(monkeypatch, capsys, language_set):
    monkeypatch.setattr(prerequisites, "ffmpeg_missing", lambda: True)
    feed(monkeypatch, ["1"])  # skip: one more question would find no answer
    getting_started.run()
    assert _pages(capsys.readouterr().out) == ["Optional modules"]


# -- What each page sets ------------------------------------------------------

def test_the_language_sets_the_screens_then_the_cards_on_the_same_answer(
        monkeypatch, written, templates_profile):
    """Enter alone on the second list takes the language just picked for the
    screens: the likeliest answer, and still only an offer."""
    # choose; French, by its rank among the tables of `locales/`; Enter on the
    # cards; the menu, from the next page
    feed(monkeypatch, ["1", str(i18n.available().index("fr") + 1), "", "m"])
    getting_started.run()
    assert ("KOTOGEN_LANG", "fr") in written
    assert card_templates.value("all.lang") == "fr"


def test_leaving_the_screens_language_stays_on_the_page(monkeypatch, capsys, written,
                                                        templates_profile):
    feed(monkeypatch, ["1", "b", "m"])
    getting_started.run()
    assert written == []
    assert card_templates.value("all.lang") == "en"
    assert _pages(capsys.readouterr().out) == ["Language", "Language"]


def test_the_key_page_says_where_to_get_one(monkeypatch, capsys, language_set):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    feed(monkeypatch, ["m"])
    getting_started.run()
    assert "https://openrouter.ai/keys" in capsys.readouterr().out


def test_a_key_entered_moves_on(monkeypatch, capsys, written, language_set):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "sk-or-new")
    feed(monkeypatch, ["1", "m"])
    getting_started.run()
    assert ("OPENROUTER_API_KEY", "sk-or-new") in written
    assert _pages(capsys.readouterr().out) == ["API key", "AI model"]


def test_the_model_page_opens_the_model_screen_and_moves_on(monkeypatch, capsys, written,
                                                            language_set):
    """None is built in: the page sends to the providers, and a model taken
    there moves on."""
    from kotogen import catalogue

    monkeypatch.delenv("KOTOGEN_MODEL")
    monkeypatch.setattr(catalogue, "load", lambda *, refresh=False, timeout=10:
                        catalogue.Catalogue([{"id": "cheap/model", "name": "", "prompt": 1e-7,
                                              "completion": 5e-7, "cache": False,
                                              "context": 0}], 1.0))
    # choose; OpenRouter; its model; the menu, from the next page
    feed(monkeypatch, ["1", "1", "1", "m"])
    getting_started.run()
    out = capsys.readouterr().out
    assert "None is built in" in out
    assert _pages(out) == ["AI model", "Anki"]
    assert ("KOTOGEN_MODEL", "cheap/model") in written


def test_anki_creates_every_missing_note_type_in_one_install(monkeypatch, capsys,
                                                            language_set):
    _missing_types(monkeypatch)
    installs: list = []
    monkeypatch.setattr(interactive.status, "_install_notetypes",
                        lambda missing: installs.append(dict(missing)) or True)
    feed(monkeypatch, ["1", "m"])
    getting_started.run()
    assert installs == [{"kanji": "Kanji", "vocab": "Vocabulary"}]
    assert "Note types to create: Kanji, Vocabulary" in capsys.readouterr().out


def test_a_silent_anki_is_told_what_to_put_in_place(monkeypatch, capsys, language_set):
    """The add-on and its code are given where they are needed, not left to the README."""
    anki_down(monkeypatch)
    feed(monkeypatch, ["m"])
    getting_started.run()
    out = capsys.readouterr().out
    assert getting_started.ANKICONNECT_CODE in out
    assert "restart Anki" in out


def test_the_modules_page_lists_what_is_missing_and_installs_it(
        monkeypatch, capsys, language_set):
    pdf = prerequisites.EXTRAS["pdf"]
    monkeypatch.setattr(prerequisites, "missing", lambda: [pdf])
    installs: list = []
    monkeypatch.setattr(prerequisites, "install_now", lambda: installs.append(True))
    feed(monkeypatch, ["1", "m"])
    getting_started.run()
    out = capsys.readouterr().out
    assert pdf.what in out
    assert f"Install it ({prerequisites.weight(pdf)})" in out
    assert installs == [True]


# -- Where it sits in the launch ----------------------------------------------

def test_the_guide_holds_the_modules_question_of_the_first_run(monkeypatch):
    """The modules are its last page: they are not asked in front of it."""
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    monkeypatch.setattr(getting_started, "first_launch", lambda: True)
    monkeypatch.setattr(getting_started, "needed", lambda: True)
    monkeypatch.setattr(getting_started, "run", lambda: None)
    monkeypatch.setattr(prerequisites, "on_first_run",
                        lambda: pytest.fail("modules asked before the guide"))
    monkeypatch.setattr("kotogen.interactive.interactive_argv",
                        lambda banner=True: None)
    cli.main()


def test_ctrl_c_in_the_guide_quits_as_at_the_main_menu(monkeypatch, written, capsys):
    """A word and the prompt back, not a traceback; nor does the menu open."""
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    monkeypatch.setattr(getting_started, "first_launch", lambda: True)
    monkeypatch.setattr(getting_started, "needed", lambda: True)

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(getting_started, "run", interrupted)
    monkeypatch.setattr("kotogen.interactive.interactive_argv",
                        lambda banner=True: pytest.fail("the menu opened after Ctrl+C"))
    try:
        cli.main()
    except KeyboardInterrupt:
        pytest.fail("Ctrl+C in the guide ended in a traceback")
    assert "Cancelled." in capsys.readouterr().out


def test_it_opens_once_then_the_launches_go_to_the_menu(monkeypatch, written):
    """Most launches find Anki closed, so the guide cannot open on that. It is
    marked as met before it runs, so a Ctrl+C inside it counts too."""
    monkeypatch.setattr(getting_started, "first_launch", lambda: True)
    monkeypatch.setattr(getting_started, "needed", lambda: True)
    monkeypatch.setattr(getting_started, "run",
                        lambda: written.append("run"))
    assert cli._getting_started()
    assert written == [(getting_started.ENV_VAR, "0"), "run"]


def test_a_first_launch_with_nothing_to_set_up_is_had_all_the_same(monkeypatch,
                                                                    written):
    """A key and Anki at the first launch: the guide never opens, not even on the
    first day Anki is closed."""
    monkeypatch.setattr(getting_started, "first_launch", lambda: True)
    monkeypatch.setattr(getting_started, "needed", lambda: False)
    monkeypatch.setattr(getting_started, "run",
                        lambda: pytest.fail("guide opened with nothing to set up"))
    assert not cli._getting_started()
    assert written == [(getting_started.ENV_VAR, "0")]


def test_a_launch_after_the_first_writes_nothing_and_asks_nothing(monkeypatch,
                                                                  written):
    """Not even Anki: the probe is the menu's to make, at its own pace."""
    monkeypatch.setattr(getting_started, "first_launch", lambda: False)
    monkeypatch.setattr(getting_started, "needed",
                        lambda: pytest.fail("Anki probed after the first launch"))
    assert not cli._getting_started()
    assert written == []


def test_a_command_typed_in_full_never_meets_it(monkeypatch):
    """Nor uses it up: the first launch of the menu is still to come."""
    monkeypatch.setattr(sys, "argv", ["kotogen", "--version"])
    monkeypatch.setattr(getting_started, "first_launch",
                        lambda: pytest.fail("guide considered for a command"))
    with pytest.raises(SystemExit):
        cli.main()
