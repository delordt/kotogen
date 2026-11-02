"""A command typed in the shell: what reaches the screen when it stops early."""

import sys

import pytest

from kotogen import cli


@pytest.fixture
def typed(monkeypatch):
    """`kotogen vocab` typed in the shell, its run replaced by what is raised."""
    monkeypatch.setattr(sys, "argv", ["kotogen", "vocab"])

    def run_raising(error: BaseException) -> None:
        def run(argv, **kwargs):
            raise error

        monkeypatch.setattr(cli, "_run", run)
        cli.main()

    return run_raising


def test_ctrl_c_ends_a_typed_command_with_a_word_and_code_130(typed, capsys):
    with pytest.raises(SystemExit) as stop:
        typed(KeyboardInterrupt())
    assert stop.value.code == 130
    captured = capsys.readouterr()
    assert "Command interrupted." in captured.out
    assert "Traceback" not in captured.err


def test_a_question_with_no_terminal_to_answer_it_ends_in_a_sentence(typed, capsys):
    with pytest.raises(SystemExit) as stop:
        typed(EOFError())
    assert "in a terminal" in str(stop.value.code)
    assert "Traceback" not in capsys.readouterr().err


def test_an_unforeseen_error_takes_one_line_and_says_how_to_see_more(typed, capsys):
    with pytest.raises(SystemExit) as stop:
        typed(RuntimeError("the answer had no body"))
    first, hint = str(stop.value.code).split("\n")
    assert first == "Stopped by an unexpected error: the answer had no body (RuntimeError)"
    assert "KOTOGEN_DEBUG=1" in hint
    assert "Traceback" not in capsys.readouterr().err


def test_kotogen_debug_keeps_the_traceback_of_a_typed_command(typed, monkeypatch, capsys):
    monkeypatch.setenv("KOTOGEN_DEBUG", "1")
    with pytest.raises(SystemExit) as stop:
        typed(RuntimeError("the answer had no body"))
    assert "Traceback" in capsys.readouterr().err
    assert "KOTOGEN_DEBUG" not in str(stop.value.code)


@pytest.mark.parametrize("code", ["No model chosen.", 2])
def test_the_exit_of_a_command_goes_through_as_it_is(typed, code):
    with pytest.raises(SystemExit) as stop:
        typed(SystemExit(code))
    assert stop.value.code == code


def test_an_unexpected_error_says_its_first_line_cleaned(typed):
    """Below the first line of an invalid answer lies the model's raw answer,
    escapes included: it stays for KOTOGEN_DEBUG."""
    with pytest.raises(SystemExit) as stop:
        typed(ValueError("The AI's answer was not in the form asked for.\n\nRaw answer:\n"
                         "\x1b]0;title\x07\x1b[2Jsecond line"))
    said = str(stop.value.code)
    assert "\x1b" not in said and "second line" not in said
    assert said.splitlines()[0] == ("Stopped by an unexpected error: The AI's answer was "
                                    "not in the form asked for. (ValueError)")


def test_the_menu_net_says_the_first_line_of_an_unexpected_error(monkeypatch, capsys):
    from kotogen import interactive, prerequisites

    commands = iter([["vocab", "x"], None])
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    monkeypatch.setattr(cli, "_getting_started", lambda: False)
    monkeypatch.setattr(prerequisites, "on_first_run", lambda: None)
    monkeypatch.setattr(interactive, "interactive_argv", lambda banner: next(commands))

    def run(argv, **kwargs):
        raise ValueError("first line\n\nRaw answer:\n\x1b[2Jsecond line")

    monkeypatch.setattr(cli, "_run", run)
    cli.main()
    err = capsys.readouterr().err
    assert "!! Stopped by an unexpected error: first line (ValueError)" in err
    assert "second line" not in err and "\x1b" not in err


# ── No model, no work ─────────────────────────────────────────────────────────
# A command that calls the model stops before anything else when none is chosen:
# a PDF downloaded, a browser opened or the deck read would be paid for nothing.

@pytest.mark.parametrize("argv, module, function", [
    (["reading", "https://example.org/book.pdf"], "kotogen.generators.reading",
     "run_reading"),
    (["audio", "nhk"], "kotogen.generators.audio", "run_audio"),
    (["vocab", "猫"], "kotogen.generators.vocab", "run_vocab"),
    (["grammar", "ながら"], "kotogen.generators.grammar", "run_grammar"),
    (["kanji", "学"], "kotogen.generators.kanji", "run_kanji"),
    (["maintain"], "kotogen.anki.maintain.review", "run_maintain"),
    (["ask", "tag the N4 cards"], "kotogen.anki.ask", "run_ask"),
    (["rework", "cards.jsonl", "--task", "simplify"], "kotogen.rework", "run_rework"),
], ids=["reading", "audio", "vocab", "grammar", "kanji", "maintain", "ask", "rework"])
def test_a_command_that_needs_the_model_stops_before_any_work(monkeypatch, argv,
                                                              module, function):
    monkeypatch.delenv("KOTOGEN_MODEL", raising=False)
    monkeypatch.setattr(f"{module}.{function}",
                        lambda args: pytest.fail("the command started its work"))
    with pytest.raises(SystemExit) as stop:
        cli._run(argv)
    assert "No model chosen" in str(stop.value.code)


@pytest.mark.parametrize("argv, module, function", [
    (["maintain", "--scan"], "kotogen.anki.maintain.review", "run_maintain"),
    (["backup", "--list"], "kotogen.anki.backup", "run_backup"),
    (["deck", "install", "--check"], "kotogen.anki.notetypes", "run_deck"),
], ids=["maintain --scan", "backup --list", "deck install --check"])
def test_a_command_that_never_calls_the_model_runs_without_one(monkeypatch, argv,
                                                               module, function):
    monkeypatch.delenv("KOTOGEN_MODEL", raising=False)
    ran = []
    monkeypatch.setattr(f"{module}.{function}", lambda args: ran.append(args.command))
    cli._run(argv)
    assert ran == [argv[0]]


def test_the_pages_option_says_it_takes_a_folder_of_images_too():
    """The pages of a mini-book given as a folder of pictures are bounded as a
    PDF's are."""
    reading = cli.build_parser()._subparsers._group_actions[0].choices["reading"]
    pages = next(action for action in reading._actions if action.dest == "pages")
    assert "image" in pages.help and "PDF only" not in pages.help


def test_ask_with_a_provider_that_drives_no_tools_says_so_before_the_model(monkeypatch):
    """Told to pick a model first, one would pick it for nothing: the next run
    would only learn that `ask` needs another provider."""
    monkeypatch.delenv("KOTOGEN_MODEL", raising=False)
    monkeypatch.setattr("kotogen.anki.ask.run_ask",
                        lambda args: pytest.fail("the command started its work"))
    with pytest.raises(SystemExit) as stop:
        cli._run(["ask", "tag the N4 cards", "--provider", "anthropic"])
    said = str(stop.value.code)
    assert "drives tools" in said and "No model chosen" not in said


def test_an_error_that_says_nothing_is_named_by_its_kind(typed):
    """`ConnectionError()` has an empty message: the reason would be blank."""
    with pytest.raises(SystemExit) as stop:
        typed(ConnectionError())
    first = str(stop.value.code).splitlines()[0]
    assert first == "Stopped by an unexpected error (ConnectionError)"


# ── The assistant needs a terminal ────────────────────────────────────────────

def test_the_assistant_outside_a_terminal_says_so_in_one_line(monkeypatch, capsys):
    """`kotogen < NUL` or in a pipe: no menu drawn for nobody, and neither the
    guide nor the first-run offer used up."""
    from kotogen import getting_started, interactive

    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli.system, "can_ask", lambda: False)
    monkeypatch.setattr(getting_started, "met",
                        lambda: pytest.fail("the guide was marked as seen"))
    monkeypatch.setattr(interactive, "interactive_argv",
                        lambda banner: pytest.fail("the menu was drawn"))
    with pytest.raises(SystemExit) as stop:
        cli.main()
    said = str(stop.value.code)
    assert "terminal" in said and "\n" not in said
    assert capsys.readouterr().out == ""
