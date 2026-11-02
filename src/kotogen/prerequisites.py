"""What is missing for everything to work, installed on the first run.

PDF page images, Whisper, the NHK capture and YouTube live in pip extras, whose
absence would show only mid-work, sometimes after a paid AI call: they are
offered on the first run in an environment, as `KOTOGEN_INSTALL` says (`MODES`).
FFmpeg and the Whisper weights are not installed from here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path

from kotogen import console, settings, system
from kotogen.i18n import _, convention, counted

ENV_VAR = "KOTOGEN_INSTALL"

# `ask` (the default) asks once per environment and remembers a refusal; `always`
# installs on every run, which is also how to retry after a network failure;
# `never` touches nothing, and the modules' own install messages remain.
MODES = ("ask", "always", "never")

DEFAULT_MODE = MODES[0]



@dataclass(frozen=True)
class Extra:
    """An extra of `pyproject.toml`, as this screen has to speak of it."""

    name: str           # its name in pyproject: `pip install -e ".[pdf]"`
    what: str           # what it allows, in one line, on the user's side
    modules: tuple      # the IMPORT names that prove it is there
    megabytes: int      # the order of magnitude of the download, to announce it
    packages: tuple     # fallback if the package metadata cannot be found


# What the program installs by itself. Import names (`pillow` imports as `PIL`)
# and weights are written by hand; the rest comes from the metadata. `dev` is
# left out on purpose, and a test checks that every other extra is listed. The
# label says what the module ALLOWS: it is all one reads to answer yes or no.
EXTRAS: dict[str, Extra] = {e.name: e for e in [
    Extra("pdf", "the pages of a document as images (Reading as a mini-book)",
          ("pypdfium2", "PIL", "numpy"), 20, ("pypdfium2", "pillow", "numpy")),
    Extra("youtube", "YouTube videos and channels",
          ("yt_dlp",), 5, ("yt-dlp",)),
    Extra("nhk", "the articles of NHK News Web Easy",
          ("playwright",), 45, ("playwright",)),
    Extra("anthropic", "the Anthropic provider directly",
          ("anthropic",), 15, ("anthropic",)),
    Extra("openai", "the OpenAI provider directly",
          ("openai",), 25, ("openai",)),
    # By far the biggest (openai-whisper brings torch), last because it is the
    # one looked at before answering.
    Extra("audio", "transcribing local audio files (Whisper)",
          ("whisper",), 1200, ("openai-whisper",)),
]}

# Playwright's Chromium, not a pip package, which the NHK capture needs as well:
# it follows its extra in the same pass.
CHROMIUM_MEGABYTES = 170


# -- What is missing ----------------------------------------------------------

def present(extra: Extra) -> bool:
    """True if every module of this extra is installed.

    `find_spec` rather than an import: importing `whisper` loads torch, seconds
    at every start.
    """
    for module in extra.modules:
        try:
            if find_spec(module) is None:
                return False
        except (ImportError, ValueError):
            # A half-uninstalled package, a broken import path: when in doubt it
            # is missing, which at worst costs a reinstall.
            return False
    return True


def missing() -> list[Extra]:
    """The extras of which at least one module is missing, in table order."""
    return [extra for extra in EXTRAS.values() if not present(extra)]


def installed() -> list[Extra]:
    """The extras every module of which is there, in table order.

    What `update` renews: an extra not installed was declined, not left to age.
    """
    return [extra for extra in EXTRAS.values() if present(extra)]


def ffmpeg_missing() -> bool:
    """True if FFmpeg is not in the PATH."""
    return shutil.which("ffmpeg") is None


# -- What is handed to pip ----------------------------------------------------

def _without_marker(requirement: str) -> tuple[str, str]:
    """A metadata requirement cut into (what is installed, its marker).

    The metadata writes `playwright>=1.40; extra == "nhk"`: the useful part is
    before the semicolon, the extra it belongs to after it.
    """
    package, _sep, marker = requirement.partition(";")
    return package.strip(), marker.strip()


def requirements(extra: Extra) -> list[str]:
    """What to hand pip for this extra, declared versions included.

    Read from the installed package's metadata, which exists outside the
    repository too and keeps the bounds (`pypdfium2>=5`). The packages rather
    than `kotogen[pdf]`, which depends on how the project was installed. Falls
    back on the bare names without metadata (a `src/` never installed).
    """
    try:
        declared = metadata.requires("kotogen") or []
    except metadata.PackageNotFoundError:
        return list(extra.packages)

    wanted = []
    for requirement in declared:
        package, marker = _without_marker(requirement)
        # Single or double quotes, depending on the tool that built the package.
        if marker in (f'extra == "{extra.name}"', f"extra == '{extra.name}'"):
            wanted.append(package)
    return wanted or list(extra.packages)


# -- What has already been offered --------------------------------------------
# Remembered per environment (keyed by `sys.prefix`), since two venvs hold
# different packages. What is kept is what was OFFERED, so that a refusal is not
# asked again; an extra added later has never been offered, and is asked alone.

MEMORY = "prerequisites.json"


def _memory_path() -> Path:
    return system.data_dir() / MEMORY


def _memory() -> dict:
    """The whole memory, one entry per environment: {prefix: {"offered": [...]}}.

    Empty when absent or unreadable: the question is then put again.
    """
    try:
        content = json.loads(_memory_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return content if isinstance(content, dict) else {}


def _offered() -> set[str]:
    """What has already been offered in THIS environment."""
    entry = _memory().get(sys.prefix)
    if not isinstance(entry, dict):
        return set()
    return set(entry.get("offered", []))


def _remember(names: set[str]) -> None:
    """Add these names to what has been offered in this environment.

    A failed write fails nothing: at worst the question comes back next run.
    """
    content = _memory()
    content = {prefix: {"offered": sorted(entry.get("offered", []))}
               for prefix, entry in content.items() if isinstance(entry, dict)}
    former = set(content.get(sys.prefix, {}).get("offered", []))
    content[sys.prefix] = {"offered": sorted(former | names)}
    path = _memory_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    except OSError:
        pass


# -- The installation ---------------------------------------------------------

def obstacle() -> str:
    """What prevents installing here, or an empty string if nothing does.

    Outside a virtual environment the command is shown rather than run: the
    distributions refuse installs into the system Python (PEP 668).
    """
    if sys.prefix == sys.base_prefix:
        return _("outside a virtual environment")
    if find_spec("pip") is None:
        return _("pip is not available here")
    return ""


def _size_from_pip(text: str) -> str:
    """"198.4 MB" said in the language in use: "198,4 Mo" in French.

    Written like every other size of the output (`console.size`).
    """
    for pip_unit, ours in (("kB", _("KB")), ("MB", _("MB")), ("GB", _("GB"))):
        text = text.replace(pip_unit, ours)
    return text.replace(".", convention("decimal_point", "."))


def _detail(line: str) -> str:
    """What a line of pip teaches whoever watches the screen, or nothing.

    Only what is looked for, what is downloaded (with its weight) and the moment
    the network is done; the rest of pip's output is a log.
    """
    line = line.strip()
    if line.startswith("Downloading "):
        # "Downloading torch-2.4.0-cp312-win_amd64.whl (198.4 MB)"
        rest = line[len("Downloading "):]
        filename, _sep, size = rest.partition(" (")
        name = filename.split("-")[0] or filename
        return f"{name} {_size_from_pip(size.rstrip(')'))}" if size else name
    if line.startswith("Collecting "):
        return line[len("Collecting "):].split(" ")[0]
    if line.startswith("Installing collected packages"):
        return _("installing")
    return ""


def _browser_detail(line: str) -> str:
    """What a line of `playwright install` teaches, or nothing.

    Its lines read "Downloading Chrome Headless Shell 151.0.7922.34 (playwright
    build v1234) from https://...", which `_detail` would misread as pip's: what
    is downloaded is kept, without build number or address.
    """
    line = line.strip()
    if not line.startswith("Downloading "):
        return ""
    what = line[len("Downloading "):]
    return what.split(" from ")[0].split(" (")[0].strip()


def _run(command: list[str],
         detail: Callable[[str], str] = _detail) -> tuple[bool, str]:
    """Run a command while animating the open action line, and return its outcome.

    The output is captured, not shown: `detail` picks what a line teaches for the
    end of the action line (pip's by default, see `_browser_detail`), and the
    whole log comes back to give a failure's reason.
    """
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        # No interpreter, or no right to run it: a failure, not a traceback.
        return False, str(exc)

    log: list[str] = []
    running = [""]

    def read() -> None:
        for line in process.stdout:  # type: ignore[union-attr]
            log.append(line.rstrip())
            if more := detail(line):
                running[0] = more
        process.wait()

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    console.animate(reader, lambda: running[0])
    reader.join()
    return process.returncode == 0, "\n".join(log)


def install(extras: list[Extra]) -> list[Extra]:
    """Install these extras and return those that are there in the end.

    One pip call for the batch, so one resolution and one wait; as one missing
    package fails it all, the result is checked module by module.
    """
    wanted = [requirement for extra in extras for requirement in requirements(extra)]
    # The extras, not the packages: the modules the question listed, and what the
    # result counts.
    console.action(_("Installing {count} {modules} ({size})").format(
        count=len(extras), modules=console.plural(len(extras), "module"),
        size=_megabytes(sum(e.megabytes for e in extras))), margin=True)
    ok, log = _run([sys.executable, "-m", "pip", "install",
                    "--disable-pip-version-check", "--progress-bar", "off",
                    *wanted])
    installed = [extra for extra in extras if present(extra)]
    console.done(_("{done} out of {total}").format(done=len(installed), total=len(extras)))
    if not ok:
        console.failed(_("pip stopped: {why}").format(why=_why(log)))

    if any(extra.name == "nhk" for extra in installed):
        _chromium()
    return installed


def _why(log: str) -> str:
    """The one line of a log that says why it failed, and only it.

    pip's last "ERROR" line if there is one, else the last line of all.
    """
    useful = [line.strip() for line in log.splitlines() if line.strip()]
    errors = [line for line in useful if line.startswith(("ERROR", "error"))]
    return console.reason((errors or useful or [""])[-1], columns=100)


def _chromium() -> None:
    """Fetch Playwright's browser, without which the extra is of no use.

    Never `--with-deps`, even on Linux: it asks for the administrator password,
    which a captured output would hide. `system.chromium_hint` gives the full
    command when Chromium refuses to start.
    """
    console.action(_("Playwright browser ({size})").format(
        size=_megabytes(CHROMIUM_MEGABYTES)))
    ok, log = _run([sys.executable, "-m", "playwright", "install", "chromium"],
                   detail=_browser_detail)
    console.done("" if ok else _("failed"))
    if not ok:
        console.failed(_("{why} → to be run again by hand: {command}").format(
            why=_why(log), command=system.chromium_hint()))


# -- Renewing what is already there -------------------------------------------
# For `update`: the newest version of the modules already installed (`installed`).

# pip's last line when it laid something down, absent when all was up to date:
# the list of what moved. pip's own English, not to be translated.
_LAID_DOWN = "Successfully installed "


def _version(package: str) -> str:
    """The version of that package in this environment, or "" if it is absent."""
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return ""


def _renewed(log: str) -> list[str]:
    """The packages pip put a new version of, each with the version it reached."""
    for line in reversed(log.splitlines()):
        if line.startswith(_LAID_DOWN):
            return line[len(_LAID_DOWN):].split()
    return []


def upgrade(extras: list[Extra]) -> list[str]:
    """Renew these installed extras, and hand back what really moved.

    pip's default `--upgrade` strategy moves only the packages NAMED, their
    dependencies only when required: renewing `openai-whisper` must not fetch
    torch again. Chromium is fetched again only when playwright moved, since a
    new playwright no longer starts the old browser.
    """
    wanted = [requirement for extra in extras for requirement in requirements(extra)]
    # Indented as a step of `update`'s block, where `install` opens a block of
    # its own in the margin.
    console.action(_("Renewing {count} {modules}").format(
        count=len(wanted), modules=console.plural(len(wanted), "module")))
    browser = _version("playwright")
    ok, log = _run([sys.executable, "-m", "pip", "install", "--upgrade",
                    "--disable-pip-version-check", "--progress-bar", "off",
                    *wanted])
    renewed = _renewed(log)
    # One is named, several counted: a list would take a line per package.
    if len(renewed) == 1:
        console.done(renewed[0])
    else:
        console.done(_("{count} renewed").format(count=len(renewed)) if renewed
                     else _("nothing to renew"))
    if not ok:
        console.failed(_("pip stopped: {why}").format(why=_why(log)))
    elif browser and _version("playwright") != browser:
        _chromium()
    return renewed


def reinstall(root: Path) -> None:
    """Lay the project itself down again from its sources: `pip install -e .`.

    For an update that changed `pyproject.toml`: an editable install links the
    code, not the dependencies it gained.
    """
    console.action(_("Installing the sources"))
    ok, log = _run([sys.executable, "-m", "pip", "install",
                    "--disable-pip-version-check", "--progress-bar", "off",
                    "-e", str(root)])
    console.done("" if ok else _("failed"))
    if not ok:
        console.failed(_("pip stopped: {why}").format(why=_why(log)))


# -- The first-run pass -------------------------------------------------------

def _megabytes(mb: int) -> str:
    """An order of magnitude for a download, in MB or GB.

    Not `console.size`, which stops at megabytes: "1224.0 MB" does not read.
    """
    point = convention("decimal_point", ".")
    if mb >= 1000:
        return f"{mb / 1024:.1f}".replace(".", point) + f" {_('GB')}"
    return f"{mb} {_('MB')}"


def to_download(extra: Extra) -> int:
    """What this extra costs to download, browser included.

    Chromium weighs four times the module that brings it, and this is the figure
    one answers on.
    """
    return extra.megabytes + (CHROMIUM_MEGABYTES if extra.name == "nhk" else 0)


def mode() -> str:
    """The mode set, or the default if the setting is absent or badly written.

    Never an error, as in `video_clip.by_mode`: a stale setting must not stop
    the command.
    """
    value = settings.text(ENV_VAR).strip().lower()
    return value if value in MODES else DEFAULT_MODE


def _interactive() -> bool:
    """True if there is somebody in front of the screen to answer the question."""
    return system.can_ask()


def _announce(extras: list[Extra], among: str) -> None:
    """The heading line of the pass: what is missing, and why we speak of it.

    One line: the list that follows and the question carry the weights.
    """
    console.title(counted(len(extras),
                          "{count} optional module missing ({among}):",
                          "{count} optional modules missing ({among}):")
                  .format(count=len(extras), among=among))


def _accepted(extras: list[Extra], total: int) -> bool:
    """Put the question, once, and return the answer.

    The weights come first, in a column, as the figure one answers on; the total
    is repeated only for several modules.
    """
    from kotogen.exporter import ask_choice

    _announce(extras, _("first run"))
    column = max(console.width(_megabytes(to_download(e))) for e in extras)
    for extra in extras:
        size = _megabytes(to_download(extra))
        console.item(f"{console.pad(size, column)}  {_(extra.what)}")
    sum_up = f" ({_megabytes(total)})" if len(extras) > 1 else ""
    return ask_choice(_("[i] install{total}  [n] not now").format(total=sum_up),
                      "in", default="n") == "i"


def on_first_run() -> None:
    """Install what is missing, once per environment. Called at startup.

    Silent when there is nothing to do (every start pays only a few `find_spec`
    calls), and outside a terminal unless the mode is `always`.
    """
    if (choice := mode()) == "never":
        return

    offered = _offered()
    pending = missing()
    if choice != "always":
        pending = [extra for extra in pending if extra.name not in offered]
    no_ffmpeg = ffmpeg_missing() and ("ffmpeg" not in offered or choice == "always")
    if not pending and not no_ffmpeg:
        return
    if choice != "always" and not _interactive():
        return
    _offer(pending, no_ffmpeg, choice)


def install_now() -> None:
    """Install what is missing because somebody asked for it.

    The getting-started guide's "install" answers the first-run question: neither
    the memory of offers nor `KOTOGEN_INSTALL=never` holds it back, and FFmpeg
    is left to the page, which says how it installs.
    """
    if pending := missing():
        _offer(pending, False, "always")


def weight(extra: Extra) -> str:
    """What this extra downloads, as the screens say it."""
    return _megabytes(to_download(extra))


def weight_of(extras: list[Extra]) -> str:
    """What these extras download together."""
    return _megabytes(sum(to_download(extra) for extra in extras))


def _offer(pending: list[Extra], no_ffmpeg: bool, choice: str) -> None:
    """The question, the installation and the FFmpeg line: what both doors share."""
    # Remembered at once, whatever follows; a network failure is retried with
    # `always`, which ignores this memory.
    _remember({extra.name for extra in pending} | ({"ffmpeg"} if no_ffmpeg else set()))

    if pending:
        try:
            _install_if_possible(pending, choice)
        except KeyboardInterrupt:
            # A Ctrl+C stops the installation, not the program: said on the open
            # action line, or on a line of its own if it came at the question.
            if console.is_open():
                console.close_line(_("(interrupted)"), sep=" ")
            else:
                console.item(_("Installation interrupted."))
    if no_ffmpeg:
        # Not a pip package, and installing it needs administrator rights.
        console.aside(_("FFmpeg (sound and video) installs by hand: {command}")
                      .format(command=system.ffmpeg_hint()))


def _install_if_possible(extras: list[Extra], choice: str) -> None:
    """The half that installs: refusal, obstacle and success are said alike."""
    total = sum(to_download(extra) for extra in extras)

    if blocked := obstacle():
        _announce(extras, blocked)
        for extra in extras:
            console.item(f"pip install {' '.join(requirements(extra))}"
                         f"   {_(extra.what)}")
        return

    # A refusal is not acknowledged: a missing module says so when it is needed.
    if choice != "always" and not _accepted(extras, total):
        return

    installed = install(extras)
    for extra in extras:
        if extra not in installed:
            console.aside(_(extra.what) + convention("colon", ": ")
                          + f"pip install {' '.join(requirements(extra))}")
