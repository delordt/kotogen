"""`kotogen update`: bring the sources up to date, then the modules installed.

kotogen is installed from its repository in editable mode, so updating it means
taking what the remote has: a fetch, then a fast-forward. Never a merge: a
working copy that cannot fast-forward is left as it is, since its changes belong
to whoever made them. The modules already installed are renewed next (yt-dlp
ages fast); a missing extra stays missing, which is `prerequisites`' question.

The running process keeps the modules it imported, so an update ends by asking
for a relaunch.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import kotogen
from kotogen import console, prerequisites, system
from kotogen.i18n import _, quoted

# The package Python actually loaded: the only sources this command may touch,
# whatever folder it is typed in.
PACKAGE = Path(kotogen.__file__).resolve().parent


def repository() -> Path | None:
    """The working copy the loaded code comes from, or None (a wheel, a copied folder)."""
    root = PACKAGE.parents[1]
    return root if (root / ".git").exists() else None


def _git(root: Path, *args: str, asking: bool = True) -> tuple[bool, str]:
    """Run git in `root`: whether it worked, and what it said on both streams.

    `asking=False` forbids any prompt: ssh would ask for a password on the
    terminal, behind the spinner, and the program would look hung (see `_fetch`).
    """
    env = None if asking else _unasking(root)
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args], env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        return False, str(exc)
    return done.returncode == 0, f"{done.stdout}\n{done.stderr}".strip()


# What tells ssh not to prompt. Only OpenSSH reads `-o`: plink refuses it, and a
# wrapper may pass it anywhere.
_BATCH = " -o BatchMode=yes"


def _unasking(root: Path) -> dict[str, str]:
    """The environment of a git run that may not prompt.

    The ssh command git would run (GIT_SSH_COMMAND, else `core.sshCommand`) gets
    BatchMode when it is OpenSSH. GIT_SSH and other programs are left as they
    are: `_fetch` then tries again in the clear, whatever the failure.
    """
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    command = env.get("GIT_SSH_COMMAND", "")
    if not command:
        found, configured = _git(root, "config", "--get", "core.sshCommand")
        command = configured if found else ""
    if command:
        if _openssh(command):
            env["GIT_SSH_COMMAND"] = command + _BATCH
    elif not env.get("GIT_SSH"):
        env["GIT_SSH_COMMAND"] = "ssh" + _BATCH
    return env


def _openssh(command: str) -> bool:
    """True if the program this command line starts is OpenSSH's `ssh`.

    Its first word, quoted or not, by its name alone, as git itself tells ssh
    from plink: `C:/Windows/System32/OpenSSH/ssh.exe` is one.
    """
    command = command.strip()
    if command[:1] in ('"', "'"):
        program = command[1:].split(command[0], 1)[0]
    else:
        program = command.split(maxsplit=1)[0] if command else ""
    name = program.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.removesuffix(".exe") == "ssh"


def _prompts_held(root: Path) -> bool:
    """True if the prompt-less run really holds ssh's prompts back (`_unasking`)."""
    return _unasking(root).get("GIT_SSH_COMMAND", "").endswith(_BATCH)


def _must_ask(said: str) -> bool:
    """True if git stopped on a question for the user rather than for want of a remote.

    A password, or a host key ssh does not know yet. Matched on git's and ssh's
    own words, which stay English and are never shown.
    """
    return any(word in said for word in (
        "Permission denied", "Authentication failed", "terminal prompts disabled",
        "could not read Username", "could not read Password",
        "Host key verification failed"))


def _fetch(root: Path, upstream: str) -> tuple[bool, str]:
    """Fetch behind the spinner, and again in the clear if the remote has a question.

    An ssh that could not be told not to prompt (plink, a wrapper) may have
    failed on a question it never showed: any failure gets the second go, when
    there is a terminal to answer it. That go takes the spinner's line off first.
    """
    ok, said = console.while_working(
        lambda: _git(root, "fetch", "--quiet", asking=False))
    if ok or not (_must_ask(said)
                  or (system.can_ask() and not _prompts_held(root))):
        return ok, said
    console.drop_line()
    ok, said = _git(root, "fetch", "--quiet")
    console.action(_("Reading {remote}").format(remote=upstream))
    return ok, said


def _first_said(said: str) -> str:
    """What git and ssh said, from the first line that says something.

    ssh frames a changed host key in rows of `@`: the frame goes, its warning stays.
    """
    for line in said.splitlines():
        if text := line.strip().strip("@").strip():
            return text
    return said


def _upstream(root: Path) -> str:
    """The remote branch the current one follows, or "" if it follows none."""
    ok, said = _git(root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return said if ok else ""


def _head(root: Path) -> str:
    """The commit the working copy sits on, shortened as git shortens it."""
    ok, said = _git(root, "rev-parse", "--short", "HEAD")
    return said if ok else ""


def _waiting(root: Path, upstream: str) -> int:
    """How many commits the remote has that the working copy has not.

    A count rather than their subjects: what changed is read in the changelog.
    """
    ok, said = _git(root, "rev-list", "--count", f"HEAD..{upstream}")
    return int(said) if ok and said.isdigit() else 0


def _changed(root: Path, since: str) -> list[str]:
    """The files the fast-forward moved, by their path in the repository."""
    ok, said = _git(root, "diff", "--name-only", f"{since}..HEAD")
    return said.splitlines() if ok and said else []


def run_update(args) -> bool:
    """`kotogen update`: take the sources, then renew the modules installed.

    True when the sources moved: a running session then holds the modules of the
    old version, and the menu ends it.
    """
    root = repository()
    if root is None:
        sys.exit(_("{path} is not a git working copy: an update goes through "
                   "the repository the program was installed from.")
                 .format(path=quoted(str(PACKAGE))))
    if shutil.which("git") is None:
        sys.exit(_("git is not on the PATH, and the sources are taken with it."))
    upstream = _upstream(root)
    if not upstream:
        # A local branch or a detached HEAD: nothing to be up to date with.
        sys.exit(_("The current branch follows no remote: nothing says where "
                   "an update would come from."))

    # One block named after the working copy, which tells two clones apart, and
    # each step an action under it.
    console.title(str(root))
    console.action(_("Reading {remote}").format(remote=upstream))
    ok, said = _fetch(root, upstream)
    if not ok:
        # The action falls on stderr; the exit code carries the failure on.
        console.failed(_("repository unreachable: {why}")
                       .format(why=console.reason(_first_said(said), columns=100)))
        sys.exit(1)
    waiting = _waiting(root, upstream)
    console.done(_("{count} {commits}").format(
        count=waiting, commits=console.plural(waiting, "commit"))
        if waiting else _("up to date"))

    if args.check:
        # The fetch alone answers the question: nothing in the working copy moves.
        return False

    changed: list[str] = []
    if waiting:
        before = _head(root)
        console.action(_("Taking them"))
        ok, said = _git(root, "merge", "--ff-only", upstream)
        if not ok:
            console.failed(_("the sources have not moved: {why}")
                           .format(why=console.reason(_first_said(said), columns=100)))
            sys.exit(1)
        console.done(_("now at {commit}").format(commit=_head(root)))
        changed = _changed(root, before)

    # Reinstalled only when pyproject.toml moved, pip taking seconds, and before
    # the upgrade: the extras read their bounds in the metadata it rewrites.
    if "pyproject.toml" in changed:
        prerequisites.reinstall(root)
    if installed := prerequisites.installed():
        prerequisites.upgrade(installed)

    if waiting:
        console.space()
        print(_("Launch kotogen again to run the new version."))
    # Said only when the templates moved: `deck install` carries them into Anki.
    if any(path.startswith("templates/") for path in changed):
        print(_("The card templates have changed: `kotogen deck install` carries "
                "them into Anki."))
    return bool(waiting)
