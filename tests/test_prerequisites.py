"""The pass that installs what is missing: what it offers, and when it stays
silent.

Guarded here: a question put once only, never outside a terminal (its default
would start a gigabyte download), and a table that covers every extra of
`pyproject.toml`.
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

import pytest

from kotogen import console, prerequisites, system

ROOT = Path(__file__).resolve().parent.parent

# The real pass, captured before `conftest.py` neutralises it for every test.
_real_pass = prerequisites.on_first_run

# Left out of the table: `dev` is for developing the program, not using it.
_OUT_OF_TABLE = {"dev"}


@pytest.fixture
def run_pass(tmp_path, monkeypatch):
    """The real pass, on a fresh environment: nothing installed, a terminal.

    The memory goes to a throwaway folder (`conftest` isolates the cache and
    the configuration, not the data); the screen is declared interactive, or
    the pass would stay silent.
    """
    monkeypatch.setattr(system, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(prerequisites, "_interactive", lambda: True)
    monkeypatch.setattr(prerequisites, "obstacle", lambda: "")
    monkeypatch.setattr(prerequisites, "ffmpeg_missing", lambda: False)
    return _real_pass


@pytest.fixture
def missing(monkeypatch):
    """Declares which extras are missing, without touching the environment."""
    def declare(*names: str) -> None:
        monkeypatch.setattr(prerequisites, "missing",
                            lambda: [prerequisites.EXTRAS[n] for n in names])
    return declare


@pytest.fixture
def installed(monkeypatch):
    """Holds on to what the pass asked to install, without running pip."""
    asked: list[list[str]] = []
    monkeypatch.setattr(prerequisites, "install",
                        lambda extras: asked.append([e.name for e in extras]) or extras)
    return asked


@pytest.fixture
def answers(monkeypatch):
    """Fixes the answer to the question, without reading the keyboard."""
    def give(answer: str) -> None:
        monkeypatch.setattr("kotogen.exporter.ask_choice",
                            lambda *a, **k: answer)
    return give


# ── The table and the metadata ────────────────────────────────────────────────

def _declared_packages() -> dict[str, list[str]]:
    """The extras of `pyproject.toml` and the packages of each, bounds left out.

    Read from the file, not the metadata, which an editable install only
    refreshes on the next install; by hand, as `tomllib` is missing from 3.10.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = text.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    return {name: re.findall(r'"([A-Za-z0-9._-]+)', body)
            for name, body in re.findall(r"^([a-z][a-z0-9-]*) = \[(.*?)\]",
                                         section, re.MULTILINE | re.DOTALL)}


def _declared_extras() -> set[str]:
    """The extras of `pyproject.toml`, read the same way."""
    return set(_declared_packages())


def test_the_table_covers_every_extra():
    """An extra of pyproject enters the table, or `_OUT_OF_TABLE` on purpose."""
    forgotten = _declared_extras() - set(prerequisites.EXTRAS) - _OUT_OF_TABLE
    assert not forgotten, f"extras absent from prerequisites.EXTRAS: {sorted(forgotten)}"


def test_the_table_declares_nothing_that_does_not_exist():
    assert set(prerequisites.EXTRAS) <= _declared_extras()


def test_the_table_installs_what_pyproject_declares():
    """The bare names of the table are the packages pyproject puts in the extra.

    They are installed when the metadata is missing, and a stale editable install
    lacks a package added since: only a fresh installation would show the drift.
    """
    declared = _declared_packages()
    drifted = {name: (list(extra.packages), declared[name])
               for name, extra in prerequisites.EXTRAS.items()
               if list(extra.packages) != declared[name]}
    assert not drifted, f"prerequisites.EXTRAS against pyproject: {drifted}"


def test_every_extra_knows_what_it_installs():
    """Metadata up to date or not, every extra gives back enough to run pip.

    Metadata older than an extra declares nothing for it: without the fallback
    on the bare names, the pass would install nothing and report a success.
    """
    for name, extra in prerequisites.EXTRAS.items():
        assert prerequisites.requirements(extra), f"{name}: nothing to install"


def test_the_requirements_keep_the_version_bounds():
    """What is given to pip is what pyproject declared, bounds included.

    A bare name (`pypdfium2`) would accept a version too old for the code.
    """
    wanted = prerequisites.requirements(prerequisites.EXTRAS["pdf"])
    assert [e.split(">=")[0] for e in wanted] == _declared_packages()["pdf"], (
        "the installed metadata is older than pyproject: pip install -e . again")
    assert any(">=" in e for e in wanted)


def test_the_requirements_fall_back_on_the_bare_names(monkeypatch):
    """With no metadata (the program launched from the sources), it installs all
    the same."""
    def absent(_name):
        raise metadata.PackageNotFoundError("kotogen")
    monkeypatch.setattr(prerequisites.metadata, "requires", absent)
    assert prerequisites.requirements(prerequisites.EXTRAS["pdf"]) == _declared_packages()["pdf"]


def test_the_requirements_ignore_the_other_extras():
    for name, extra in prerequisites.EXTRAS.items():
        wanted = " ".join(prerequisites.requirements(extra))
        assert "pytest" not in wanted, f"{name} carries off the dev extra"


# ── What the screen learns of an installation that lasts ──────────────────────

@pytest.mark.parametrize("line, expected", [
    ("Downloading torch-2.4.0-cp312-win_amd64.whl (198.4 MB)", "torch 198.4 MB"),
    ("  Downloading fugashi-1.3.0.tar.gz (337 kB)", "fugashi 337 KB"),
    ("Collecting openai-whisper", "openai-whisper"),
    ("Installing collected packages: pillow, pypdfium2", "installing"),
    ("Using cached numpy-2.1.0.whl", ""),
    ("", ""),
])
def test_the_detail_keeps_only_what_can_be_read(line, expected):
    """The end of the action line says where things stand, in plain words, or
    says nothing."""
    assert prerequisites._detail(line) == expected


@pytest.mark.parametrize("line, expected", [
    (("Downloading Chromium 151.0.7922.34 (playwright build v1234) from "
      "https://cdn.playwright.dev/builds/chromium/1234/chromium-linux.zip"),
     "Chromium 151.0.7922.34"),
    (("Downloading Chrome Headless Shell 151.0.7922.34 (playwright build v1234) "
      "from https://cdn.playwright.dev/builds/chromium/1234/shell-linux.zip"),
     "Chrome Headless Shell 151.0.7922.34"),
    ("Chromium 151.0.7922.34 downloaded to /home/x/.cache/ms-playwright", ""),
    ("", ""),
])
def test_the_browser_detail_gives_neither_url_nor_build(line, expected):
    """Playwright's output is not pip's, and is read apart.

    Read as pip, its "Downloading ... from https://..." would put the whole URL
    on the action line, which overflows the terminal and breaks the spinner.
    """
    assert prerequisites._browser_detail(line) == expected


def test_chromium_reads_the_output_of_playwright(monkeypatch):
    """The browser downloads with its own reader, not with pip's."""
    seen: list = []
    monkeypatch.setattr(prerequisites, "_run",
                        lambda command, detail=None: (seen.append((command, detail)),
                                                      (True, ""))[1])
    prerequisites._chromium()
    command, detail = seen[0]
    assert "playwright" in command
    assert detail is prerequisites._browser_detail


def test_why_keeps_the_error_of_pip():
    """A failure is told by the pip line that explains it, not by the last one."""
    log = ("Collecting yt-dlp\n"
           "ERROR: Could not find a version that satisfies yt-dlp\n"
           "\n"
           "[notice] A new release of pip is available\n")
    assert prerequisites._why(log).startswith("ERROR: Could not find")


@pytest.mark.parametrize("megabytes, expected", [(10, "10 MB"), (1200, "1.2 GB")])
def test_the_weight_announces_the_order_of_magnitude(megabytes, expected):
    assert prerequisites._megabytes(megabytes) == expected


# ── The pass ──────────────────────────────────────────────────────────────────

def test_nothing_to_do_says_nothing(run_pass, missing, capsys):
    """The case of every launch but the first: the pass is silent."""
    missing()
    run_pass()
    assert capsys.readouterr().out == ""


def test_it_installs_what_is_missing_once_agreed(run_pass, missing, installed, answers,
                                                 capsys):
    missing("pdf", "audio")
    answers("i")
    run_pass()
    assert installed == [["pdf", "audio"]]


def test_a_refusal_installs_nothing(run_pass, missing, installed, answers):
    missing("pdf")
    answers("n")
    run_pass()
    assert installed == []


def test_a_refusal_is_not_asked_again(run_pass, missing, installed, answers, capsys):
    """The answer is held per environment: the question is put once."""
    missing("pdf")
    answers("n")
    run_pass()
    capsys.readouterr()

    answers("i")  # even a yes has no occasion left to serve
    run_pass()
    assert installed == []
    assert capsys.readouterr().out == ""


def test_always_ignores_the_memory(run_pass, missing, installed, monkeypatch):
    """"always" tries again without asking: it is the way to catch up on a
    network failure."""
    missing("pdf")
    monkeypatch.setenv(prerequisites.ENV_VAR, "always")
    run_pass()
    run_pass()
    assert installed == [["pdf"], ["pdf"]]


def test_never_touches_anything(run_pass, missing, installed, monkeypatch, capsys):
    missing("pdf")
    monkeypatch.setenv(prerequisites.ENV_VAR, "never")
    run_pass()
    assert installed == []
    assert capsys.readouterr().out == ""


def test_an_extra_added_later_puts_its_question(run_pass, missing, installed, answers):
    """What is held is what was OFFERED: the rest keeps its turn."""
    missing("pdf")
    answers("n")
    run_pass()

    missing("pdf", "youtube")
    answers("i")
    run_pass()
    assert installed == [["youtube"]]


def test_silent_outside_a_terminal(run_pass, missing, installed, monkeypatch, capsys):
    """Nobody to answer: nothing is asked, and nothing is downloaded."""
    missing("audio")
    monkeypatch.setattr(prerequisites, "_interactive", lambda: False)
    run_pass()
    assert installed == []
    assert capsys.readouterr().out == ""


def test_always_works_even_outside_a_terminal(run_pass, missing, installed, monkeypatch):
    """"always" is an order already given: there is nothing to ask."""
    missing("audio")
    monkeypatch.setenv(prerequisites.ENV_VAR, "always")
    monkeypatch.setattr(prerequisites, "_interactive", lambda: False)
    run_pass()
    assert installed == [["audio"]]


def test_outside_a_venv_it_says_the_command_without_running_it(run_pass, missing,
                                                               installed, monkeypatch,
                                                               capsys):
    """The system Python is not installed into (PEP 668): the command is given
    to type, with the declared version bounds."""
    missing("pdf")
    monkeypatch.setattr(prerequisites, "obstacle",
                       lambda: "outside a virtual environment")
    run_pass()
    output = capsys.readouterr().out
    assert installed == []
    assert "pip install pypdfium2" in output
    assert "outside a virtual environment" in output


def test_a_missing_ffmpeg_is_said_once(run_pass, missing, monkeypatch, capsys):
    """FFmpeg, which the program cannot install, is said once, at start-up
    rather than in the middle of a transcription."""
    missing()
    monkeypatch.setattr(prerequisites, "ffmpeg_missing", lambda: True)
    run_pass()
    assert "FFmpeg" in capsys.readouterr().out

    run_pass()
    assert capsys.readouterr().out == ""


def test_the_memory_is_per_environment(run_pass, missing, installed, answers,
                                       monkeypatch):
    """Filed under the running environment's root: a refusal in one venv is no
    answer for another."""
    missing("pdf")
    answers("n")
    run_pass()

    monkeypatch.setattr(prerequisites.sys, "prefix", sys.prefix + "-other")
    answers("i")
    run_pass()
    assert installed == [["pdf"]]


def test_an_interruption_does_not_carry_the_program_off(run_pass, missing, answers,
                                                        monkeypatch, capsys):
    """Ctrl+C during the download stops the installation, not the program."""
    missing("audio")
    answers("i")

    def cut(_extras):
        raise KeyboardInterrupt

    monkeypatch.setattr(prerequisites, "install", cut)
    run_pass()
    assert "interrupted" in capsys.readouterr().out


def test_a_module_that_did_not_install_is_spaced_by_the_language(run_pass, missing,
                                                                 answers, monkeypatch,
                                                                 capsys):
    """French spaces its colon: the line names the module and the command to type."""
    from kotogen import i18n

    i18n.use("fr")
    missing("pdf")
    answers("i")
    monkeypatch.setattr(prerequisites, "install", lambda extras: [])
    run_pass()
    said = i18n._(prerequisites.EXTRAS["pdf"].what) + i18n.convention("colon", ": ")
    assert f"! {said}pip install" in capsys.readouterr().out


def test_the_installation_counts_what_it_announces(monkeypatch, capsys):
    """The modules the question listed, at the start and at the end: not the four
    packages pip is handed for them on one side and the two modules on the other."""
    monkeypatch.setattr(prerequisites, "_run", lambda *args, **kwargs: (True, ""))
    monkeypatch.setattr(prerequisites, "present", lambda extra: True)
    extras = [prerequisites.EXTRAS["pdf"], prerequisites.EXTRAS["audio"]]
    assert prerequisites.install(extras) == extras
    out = capsys.readouterr().out
    assert "Installing 2 modules" in out
    assert "(2 out of 2)" in out


# ── Where the pass sits in the start-up ───────────────────────────────────────

def test_the_assistant_lets_the_pass_be_read(monkeypatch):
    """The assistant clears the screen on opening: when the pass spoke, it
    pauses first, or the message would vanish at once."""
    from kotogen import cli, interactive, prerequisites as real

    pauses: list[str] = []
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    monkeypatch.setattr(real, "on_first_run", lambda: print("this is missing"))
    monkeypatch.setattr(interactive.screen, "_pause", lambda message: pauses.append(message))
    monkeypatch.setattr(interactive, "interactive_argv", lambda banner=True: None)
    cli.main()
    assert pauses, "the pass spoke, and the screen was cleared without waiting"


def test_the_assistant_does_not_wait_for_nothing(monkeypatch):
    """A silent pass, the usual case, adds no key to press."""
    from kotogen import cli, interactive, prerequisites as real

    pauses: list[str] = []
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    monkeypatch.setattr(real, "on_first_run", lambda: None)
    monkeypatch.setattr(interactive.screen, "_pause", lambda message: pauses.append(message))
    monkeypatch.setattr(interactive, "interactive_argv", lambda banner=True: None)
    cli.main()
    assert pauses == []


# ── The spinner ───────────────────────────────────────────────────────────────

def test_the_wait_gives_the_line_back_intact(monkeypatch, capsys):
    """The wait erases itself entirely: the action closes as it would without
    it.

    A spinner tail left on the line would sit between the label and its result.
    """
    import threading

    monkeypatch.setattr(console.sys.stdout, "isatty", lambda: True, raising=False)
    console.action("Installing 2 modules")
    work = threading.Thread(target=lambda: None)
    work.start()
    console.animate(work, lambda: "torch 198.4 MB")
    console.done("2 of 2")

    line = capsys.readouterr().out.rsplit("\r", 1)[-1]
    assert line == "   Installing 2 modules… (2 of 2)\n"


def test_the_wait_does_not_overflow_the_terminal(monkeypatch, capsys):
    """A detail longer than the screen is cut, not wrapped.

    A carriage return does not go back up a wrapped line: each frame would land
    under the previous one, and the erasing would only clear the last.
    """
    import threading

    monkeypatch.setattr(console.sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(console, "columns", lambda: 40)
    over = threading.Event()
    console.action("Playwright browser (170 MB)")
    work = threading.Thread(target=over.wait)
    work.start()
    timer = threading.Timer(0.2, over.set)
    timer.start()
    console.animate(work, lambda: "x" * 300)
    timer.cancel()
    console.done()

    frames = [part for part in capsys.readouterr().out.split("\r") if part.strip()]
    assert frames, "the spinner wrote nothing"
    for frame in frames:
        assert "\n" not in frame.rstrip("\n"), "a frame wrapped"
        assert console.width(frame.rstrip("\n")) < 40
