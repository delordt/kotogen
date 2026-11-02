"""Bringing the program up to date: what it takes, what it renews, what it
refuses to touch.

A fast-forward that does not apply leaves the working copy as it was and says
why in one line, never opening a merge. An absent extra stays absent (Whisper
weighs a gigabyte). `pip install -e .` runs only when `pyproject.toml` moved.
Moved sources call for a relaunch: the running process keeps its modules.
"""

from __future__ import annotations

import pytest

from kotogen import prerequisites, update
from kotogen.cli import build_parser

# A fetch from an absent repository, as git and ssh state it: the cause first,
# then git's conclusion and its advice.
_UNREACHABLE = ("ssh: connect to host 192.0.2.1 port 22: Connection refused\n"
                "fatal: Could not read from remote repository.\n"
                "\n"
                "Please make sure you have the correct access rights\n"
                "and the repository exists.")

# What git answers a fast-forward it cannot make, the working copy holding a
# change one of the incoming commits touches.
_IN_THE_WAY = ("error: Your local changes to the following files would be "
               "overwritten by merge:\n\tsrc/kotogen/anki/backup.py")


class FakeGit:
    """A repository that answers what the test says, and remembers the asking.

    Commands are recognised by their first words; an unexpected one raises
    rather than getting a default answer.
    """

    def __init__(self, *, upstream: str = "origin/develop",
                 waiting: int = 0, changed: tuple[str, ...] = (),
                 fetch: tuple[bool, str] = (True, ""),
                 merge: tuple[bool, str] = (True, "Fast-forward")):
        self.upstream = upstream
        self.waiting = waiting
        self.changed = changed
        self.fetch = fetch
        self.merge = merge
        self.head = "70cd4a6"
        self.asked: list[str] = []

    def __call__(self, root, *args: str, asking: bool = True) -> tuple[bool, str]:
        line = " ".join(args)
        self.asked.append(line if asking else f"{line} [asking nothing]")
        if line.startswith("rev-parse --abbrev-ref"):
            return ((True, self.upstream) if self.upstream
                    else (False, "fatal: no upstream configured"))
        if line == "config --get core.sshCommand":
            return False, ""
        if line.startswith("fetch"):
            # A list answers one go at a time: the fetch alone may be sent twice,
            # again with the terminal free when the remote wants a password.
            return self.fetch.pop(0) if isinstance(self.fetch, list) else self.fetch
        if line.startswith("rev-list --count"):
            return True, str(self.waiting)
        if line.startswith("rev-parse --short"):
            return True, self.head
        if line.startswith("merge "):
            if self.merge[0]:
                self.head = "dabd617"
            return self.merge
        if line.startswith("diff "):
            return True, "\n".join(self.changed)
        raise AssertionError(f"git command nobody expected: {line}")

    def took_anything(self) -> bool:
        """True if a command that writes into the working copy was sent."""
        return any(line.startswith("merge ") for line in self.asked)


@pytest.fixture
def git(monkeypatch, tmp_path):
    """A real working copy, and a git that answers instead of running.

    The repository sits two folders above `PACKAGE`, where the module looks.
    """
    root = tmp_path / "kotogen"
    (root / ".git").mkdir(parents=True)
    monkeypatch.setattr(update, "PACKAGE", root / "src" / "kotogen")
    monkeypatch.setattr(update.shutil, "which", lambda name: "git")
    fake = FakeGit()
    monkeypatch.setattr(update, "_git", fake)
    return fake


@pytest.fixture
def modules(monkeypatch):
    """pip left out of it: what the update would have asked of it, recorded."""
    done: list[str] = []
    monkeypatch.setattr(prerequisites, "installed",
                        lambda: [prerequisites.EXTRAS["youtube"]])
    monkeypatch.setattr(prerequisites, "upgrade",
                        lambda extras: done.append("upgrade") or [])
    monkeypatch.setattr(prerequisites, "reinstall",
                        lambda root: done.append("reinstall"))
    return done


def _run(check: bool = False) -> bool:
    """The command as the command line builds it, options included."""
    return update.run_update(build_parser().parse_args(
        ["update", "--check"] if check else ["update"]))


def test_an_installation_that_is_no_working_copy_says_where_it_looked(
        monkeypatch, tmp_path):
    """A wheel, a folder copied by hand: the message names the folder it looked in."""
    monkeypatch.setattr(update, "PACKAGE", tmp_path / "site-packages" / "kotogen")
    with pytest.raises(SystemExit) as stopped:
        _run()
    assert "site-packages" in str(stopped.value)


def test_a_branch_that_follows_nothing_stops_before_reaching_the_network(git):
    """With no remote branch to follow, no fetch is even tried."""
    git.upstream = ""
    with pytest.raises(SystemExit):
        _run()
    assert not any(line.startswith("fetch") for line in git.asked)


def test_an_unreachable_repository_is_one_line_and_not_a_trace(git, capsys):
    """What is shown is the cause, which git states first, not the advice it ends on."""
    git.fetch = (False, _UNREACHABLE)
    with pytest.raises(SystemExit):
        _run()
    said = capsys.readouterr().err
    assert "Connection refused" in said
    assert "correct access rights" not in said
    assert not git.took_anything()


def test_a_remote_that_wants_a_password_is_asked_again_with_the_terminal_free(
        git, modules, capsys):
    """The go behind the spinner forbids prompts, or ssh would ask unseen and the
    program would look hung. A remote that wants a password gets a second go,
    allowed to ask."""
    git.fetch = [(False, "git@192.0.2.1: Permission denied (publickey,password)."),
                 (True, "")]
    git.waiting = 1
    _run()
    fetches = [line for line in git.asked if line.startswith("fetch")]
    assert len(fetches) == 2
    assert fetches[0].endswith("[asking nothing]")
    assert not fetches[1].endswith("[asking nothing]")
    assert git.took_anything()


def test_a_remote_that_is_simply_absent_is_not_asked_twice(git, modules, capsys):
    """A second go would only wait for the same refusal."""
    git.fetch = [(False, _UNREACHABLE)]
    with pytest.raises(SystemExit):
        _run()
    assert len([line for line in git.asked if line.startswith("fetch")]) == 1


def test_nothing_waiting_takes_nothing_and_renews_all_the_same(git, modules, capsys):
    """The modules age even when the sources do not: yt-dlp follows YouTube."""
    _run()
    assert not git.took_anything()
    assert modules == ["upgrade"]
    assert "up to date" in capsys.readouterr().out


def test_what_is_waiting_is_counted_then_taken(git, modules, capsys):
    """Counted, not listed (the changelog says what changed), then the commit
    landed on is named."""
    git.waiting = 2
    _run()
    out = capsys.readouterr().out
    assert "2 commits" in out
    assert "now at dabd617" in out
    assert git.took_anything()


def test_an_update_that_moved_the_sources_says_the_session_is_the_old_one(
        git, modules, capsys):
    """The running process keeps the modules it started with: only a relaunch
    runs the new code."""
    git.waiting = 1
    assert _run()
    assert "Launch kotogen again" in capsys.readouterr().out


def test_an_update_that_took_nothing_asks_for_no_relaunch(git, modules, capsys):
    """Nothing was taken: a relaunch line would only be noise at every check."""
    assert not _run()
    assert "Launch kotogen again" not in capsys.readouterr().out


@pytest.mark.parametrize("renewed, menus", [(True, 1), (False, 2)])
def test_the_menu_session_ends_once_the_sources_moved(monkeypatch, renewed, menus):
    """Its modules are the old version's and the files on disk the new one's:
    the session ends on the line that says to launch kotogen again."""
    import sys

    from kotogen import cli

    shown = []
    monkeypatch.setattr(sys, "argv", ["kotogen"])
    monkeypatch.setattr(cli, "_assistant_can_open", lambda: True)
    monkeypatch.setattr(cli, "_getting_started", lambda: False)
    monkeypatch.setattr("kotogen.interactive.interactive_argv", lambda banner=True: (
        shown.append(banner) or (["update"] if len(shown) == 1 else None)))
    monkeypatch.setattr(update, "run_update", lambda args: renewed)
    cli.main()
    assert len(shown) == menus


def test_a_check_says_what_is_waiting_and_touches_nothing(git, modules, capsys):
    """The fetch alone answers: neither the working copy nor the environment moves."""
    git.waiting = 3
    _run(check=True)
    assert "3 commits" in capsys.readouterr().out
    assert not git.took_anything()
    assert modules == []


def test_a_fast_forward_refused_leaves_the_sources_and_the_modules_alone(
        git, modules, capsys):
    """The work in progress belongs to its author: git says why it stopped, and
    the modules of a version not taken are not renewed."""
    git.waiting = 1
    git.merge = (False, _IN_THE_WAY)
    with pytest.raises(SystemExit):
        _run()
    assert "would be overwritten" in capsys.readouterr().err
    assert modules == []


def test_the_project_is_laid_down_again_when_its_declaration_moved(
        git, modules, capsys):
    """A dependency added to `pyproject.toml` needs the editable install again."""
    git.waiting = 1
    git.changed = ("pyproject.toml", "src/kotogen/update.py")
    _run()
    assert modules == ["reinstall", "upgrade"]


def test_the_project_is_not_laid_down_again_for_commits_that_ask_nothing(
        git, modules, capsys):
    """The rebuild takes seconds, and a template change needs nothing of pip."""
    git.waiting = 1
    git.changed = ("templates/vocab/front.html",)
    _run()
    assert modules == ["upgrade"]


def test_card_models_taken_say_what_carries_them_into_anki(git, modules, capsys):
    """The pull reaches only the folder: `deck install` carries the models into Anki."""
    git.waiting = 1
    git.changed = ("templates/vocab/front.html",)
    _run()
    assert "kotogen deck install" in capsys.readouterr().out


def test_an_update_that_moved_no_card_model_does_not_name_deck_install(
        git, modules, capsys):
    """Said at every update, the line would be noise."""
    git.waiting = 1
    git.changed = ("src/kotogen/update.py",)
    _run()
    assert "deck install" not in capsys.readouterr().out


def test_an_extra_left_out_stays_out(git, monkeypatch, capsys):
    """Only what is installed is renewed: an absent extra was declined, and a
    gigabyte of Whisper is not taken in passing."""
    asked: list[list[str]] = []
    monkeypatch.setattr(prerequisites, "upgrade",
                        lambda extras: asked.append([e.name for e in extras]) or [])
    monkeypatch.setattr(prerequisites, "present",
                        lambda extra: extra.name == "youtube")
    _run()
    assert asked == [["youtube"]]


def test_pip_saying_nothing_is_pip_having_found_nothing_to_do():
    """`--upgrade` on packages already up to date installs and says nothing:
    that silence is read as nothing to do, not as a failure."""
    assert prerequisites._renewed("Requirement already satisfied: yt-dlp") == []
    assert prerequisites._renewed(
        "Collecting yt-dlp\nSuccessfully installed yt_dlp-2026.9.14"
    ) == ["yt_dlp-2026.9.14"]


# ── The ssh of the user ───────────────────────────────────────────────────────
# The go behind the spinner forbids ssh to prompt (BatchMode), on top of how the
# user reaches the remote: never in its place.

def _quiet(monkeypatch, tmp_path, configured: str = "", **variables) -> dict:
    """The environment of a git run that may not ask, `core.sshCommand` set to
    `configured`; git itself is faked."""
    for name in ("GIT_SSH_COMMAND", "GIT_SSH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)

    class Done:
        def __init__(self, ok, out):
            self.returncode, self.stdout, self.stderr = (0 if ok else 1), out, ""

    seen = {}

    def run(command, env=None, **kwargs):
        if command[3:] == ["config", "--get", "core.sshCommand"]:
            return Done(bool(configured), configured)
        seen.update(env or {})
        return Done(True, "")

    monkeypatch.setattr(update.subprocess, "run", run)
    update._git(tmp_path, "fetch", "--quiet", asking=False)
    return seen


def test_no_ssh_of_the_user_gets_one_that_cannot_prompt(monkeypatch, tmp_path):
    env = _quiet(monkeypatch, tmp_path)
    assert env["GIT_SSH_COMMAND"] == "ssh -o BatchMode=yes"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_the_ssh_command_of_the_user_is_kept_and_told_not_to_prompt(monkeypatch, tmp_path):
    env = _quiet(monkeypatch, tmp_path, GIT_SSH_COMMAND="ssh -i ~/.ssh/other")
    assert env["GIT_SSH_COMMAND"] == "ssh -i ~/.ssh/other -o BatchMode=yes"


@pytest.mark.parametrize("configured", [
    "ssh -i ~/.ssh/work",
    "C:/Windows/System32/OpenSSH/ssh.exe",
    '"C:/Program Files/OpenSSH/ssh.exe" -i "C:/my keys/id"',
], ids=["plain", "windows", "quoted"])
def test_the_configured_ssh_command_is_kept_and_told_not_to_prompt(monkeypatch, tmp_path,
                                                                   configured):
    """`core.sshCommand` is taken as it stands: GIT_SSH_COMMAND, which outranks it,
    carries it with BatchMode added, or the fetch would prompt under the spinner."""
    env = _quiet(monkeypatch, tmp_path, configured)
    assert env["GIT_SSH_COMMAND"] == configured + " -o BatchMode=yes"


@pytest.mark.parametrize("configured, variables", [
    ("", {"GIT_SSH": "plink"}),
    ("", {"GIT_SSH_COMMAND": '"C:/Program Files/PuTTY/plink.exe" -batch'}),
    ("TortoisePlink.exe", {}),
    ("/usr/local/bin/ssh-wrapper", {}),
], ids=["GIT_SSH", "plink", "TortoisePlink", "wrapper"])
def test_an_ssh_that_does_not_read_options_is_left_as_it_is(monkeypatch, tmp_path,
                                                            configured, variables):
    """`-o` means nothing to plink, and GIT_SSH names a program, not a command."""
    env = _quiet(monkeypatch, tmp_path, configured, **variables)
    assert env.get("GIT_SSH_COMMAND", "") == variables.get("GIT_SSH_COMMAND", "")
    assert not update._prompts_held(tmp_path)


def test_a_host_key_not_known_yet_is_asked_about_in_the_clear(git, modules, capsys):
    """ssh asks the user to accept a new host key: behind the spinner it could not."""
    git.fetch = [(False, "Host key verification failed.\nfatal: Could not read from "
                         "remote repository."), (True, "")]
    _run()
    fetches = [line for line in git.asked if line.startswith("fetch")]
    assert len(fetches) == 2
    assert not fetches[1].endswith("[asking nothing]")


@pytest.mark.parametrize("terminal", [True, False], ids=["terminal", "no terminal"])
def test_an_ssh_that_could_not_be_silenced_gets_a_second_go_on_any_failure(
        git, modules, monkeypatch, terminal):
    """plink's password prompt says nothing git recognises: with a terminal to
    answer it, the failure is tried again in the clear rather than taken as final."""
    monkeypatch.setenv("GIT_SSH", "plink")
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.setattr(update.system, "can_ask", lambda: terminal)
    git.fetch = [(False, "FATAL ERROR: Disconnected: No supported authentication "
                         "methods available"), (True, "")]
    if terminal:
        _run()
    else:
        with pytest.raises(SystemExit):
            _run()
    fetches = [line for line in git.asked if line.startswith("fetch")]
    assert len(fetches) == (2 if terminal else 1)


def test_an_ssh_told_not_to_prompt_is_not_asked_twice_for_nothing(git, modules,
                                                                  monkeypatch):
    """BatchMode in force, a failure that is no question is final."""
    monkeypatch.delenv("GIT_SSH", raising=False)
    monkeypatch.delenv("GIT_SSH_COMMAND", raising=False)
    monkeypatch.setattr(update.system, "can_ask", lambda: True)
    git.fetch = [(False, _UNREACHABLE)]
    with pytest.raises(SystemExit):
        _run()
    assert len([line for line in git.asked if line.startswith("fetch")]) == 1


def test_a_changed_host_key_says_its_warning_and_not_its_frame(git, capsys):
    """ssh frames the warning in rows of `@`: the first line is one of them."""
    frame = "@" * 59
    git.fetch = (False, f"{frame}\n@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!"
                        f"     @\n{frame}\nHost key verification failed.\n"
                        "fatal: Could not read from remote repository.")
    with pytest.raises(SystemExit):
        _run()
    said = capsys.readouterr().err
    assert "WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!" in said
    assert "@@@" not in said
