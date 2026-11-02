"""What differs from one system to the next: XDG folders and installation hints.

`sys.platform` and the home folder are faked, so the Linux behaviour is checked
on Windows too, not only in CI.
"""

import ast
import os
from pathlib import Path

import pytest

from kotogen import system


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A faked home folder, with an empty ~/.config.

    `$HOME` is set too: it is what expands the `$HOME/Bureau` of the XDG file.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    for var in ("XDG_DESKTOP_DIR", "XDG_DOWNLOAD_DIR", "XDG_DOCUMENTS_DIR"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".config").mkdir()
    return tmp_path


def write_user_dirs(home: Path, content: str) -> None:
    (home / ".config" / "user-dirs.dirs").write_text(content, encoding="utf-8")


# ── XDG user folders ──────────────────────────────────────────────────────────

def test_the_environment_variable_wins(monkeypatch, home):
    """A session that sets the variable knows better than the file."""
    monkeypatch.setenv("XDG_DESKTOP_DIR", str(home / "Elsewhere"))
    write_user_dirs(home, 'XDG_DESKTOP_DIR="$HOME/Bureau"\n')
    assert system.xdg_user_dir("XDG_DESKTOP_DIR") == home / "Elsewhere"


def test_a_french_desktop_is_read_from_the_xdg_file(home):
    """On a French session the desktop is called `Bureau`, not `Desktop`."""
    write_user_dirs(home, '# written by xdg-user-dirs\nXDG_DESKTOP_DIR="$HOME/Bureau"\n')
    assert system.xdg_user_dir("XDG_DESKTOP_DIR") == home / "Bureau"


def test_each_folder_is_read_independently(home):
    write_user_dirs(home, (
        'XDG_DESKTOP_DIR="$HOME/Bureau"\n'
        'XDG_DOWNLOAD_DIR="$HOME/Téléchargements"\n'
        'XDG_DOCUMENTS_DIR="$HOME/Documents"\n'
    ))
    assert system.xdg_user_dir("XDG_DOWNLOAD_DIR") == home / "Téléchargements"
    assert system.xdg_user_dir("XDG_DOCUMENTS_DIR") == home / "Documents"


def test_an_absolute_path_is_kept_as_is(home, tmp_path):
    """A path outside the home folder (a mounted data disk) stays whole.

    Built from tmp_path, since `/mnt/data` is only absolute under POSIX.
    """
    elsewhere = tmp_path / "data" / "docs"
    write_user_dirs(home, f'XDG_DOCUMENTS_DIR="{elsewhere}"\n')
    assert system.xdg_user_dir("XDG_DOCUMENTS_DIR") == elsewhere


def test_an_empty_declaration_means_no_such_folder(home):
    """`XDG_DESKTOP_DIR=""` is the XDG way of saying "no desktop here"."""
    write_user_dirs(home, 'XDG_DESKTOP_DIR=""\n')
    assert system.xdg_user_dir("XDG_DESKTOP_DIR") is None


def test_a_missing_file_concludes_nothing(home):
    """macOS and minimal Linuxes have no such file: the caller falls back."""
    assert system.xdg_user_dir("XDG_DESKTOP_DIR") is None


def test_an_unknown_variable_concludes_nothing(home):
    write_user_dirs(home, 'XDG_MUSIC_DIR="$HOME/Musique"\n')
    assert system.xdg_user_dir("XDG_DESKTOP_DIR") is None


def test_the_config_home_setting_is_honoured(monkeypatch, home, tmp_path):
    elsewhere = tmp_path / "my-own-config"
    elsewhere.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(elsewhere))
    (elsewhere / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Bureau"\n',
                                              encoding="utf-8")
    assert system.xdg_user_dir("XDG_DESKTOP_DIR") == home / "Bureau"


def test_a_directory_in_place_of_the_file_is_survived(home):
    """Reading impossible: conclude nothing, do not raise."""
    (home / ".config" / "user-dirs.dirs").mkdir()
    assert system.xdg_user_dir("XDG_DESKTOP_DIR") is None


# ── The FFmpeg installation hint ──────────────────────────────────────────────

@pytest.mark.parametrize("platform, expected", [
    ("win32", "winget"),
    ("darwin", "brew"),
    ("linux", "apt"),
])
def test_ffmpeg_is_installed_the_way_this_system_does_it(monkeypatch, platform, expected):
    monkeypatch.setattr(system.sys, "platform", platform)
    assert expected in system.ffmpeg_hint()


# ── Chromium (Playwright) ─────────────────────────────────────────────────────

def test_linux_pulls_the_system_libraries_with_chromium(monkeypatch):
    """Without --with-deps, Chromium installs and then refuses to start."""
    monkeypatch.setattr(system.sys, "platform", "linux")
    assert system.chromium_hint() == "playwright install --with-deps chromium"


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_elsewhere_the_browser_alone_is_enough(monkeypatch, platform):
    monkeypatch.setattr(system.sys, "platform", platform)
    assert system.chromium_hint() == "playwright install chromium"


def test_a_stale_browser_is_recognised():
    """The common case: pip upgrades the package, not the browser build on disk."""
    exc = RuntimeError(
        "BrowserType.launch_persistent_context: Executable doesn't exist at "
        "C:\\ms-playwright\\chromium_headless_shell-1234\\chrome-headless-shell.exe")
    assert system.missing_chromium(exc)


def test_the_playwright_invitation_to_install_is_recognised():
    assert system.missing_chromium(RuntimeError("Please run playwright install"))


def test_an_ordinary_failure_is_not_taken_for_a_missing_installation():
    """A page that does not load must come back as it stands, not disguised."""
    assert not system.missing_chromium(RuntimeError("Timeout 30000ms exceeded"))


# ── The clipboard ─────────────────────────────────────────────────────────────

@pytest.fixture
def tools(monkeypatch):
    """Replaces `subprocess.run`: what was called, and what exists.

    A utility not added to `present` raises FileNotFoundError, as if not installed.
    """
    import subprocess

    calls: list[tuple[tuple[str, ...], bytes]] = []
    present: set[str] = set()

    def fake_run(command, *, input, check, stdout, stderr):
        calls.append((tuple(command), input))
        if command[0] not in present:
            raise FileNotFoundError(command[0])

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls, present


def test_the_first_tool_that_answers_is_the_one_reported(monkeypatch, tools):
    """The utility that answered is named: a copy seen to happen, not a blind send."""
    calls, present = tools
    monkeypatch.setattr(system.sys, "platform", "linux")
    present.add("xclip")

    assert system.copy("kotogen vocab 食べる") == "xclip"
    # wl-copy first, xclip after: a Wayland session often carries both, and
    # wl-copy is the one that talks to the right server there.
    assert [name for (name, *_), _ in calls] == ["wl-copy", "xclip"]


def test_windows_gets_its_utf16(monkeypatch, tools):
    """Fed UTF-8, `clip` copies `を` as mojibake."""
    calls, present = tools
    monkeypatch.setattr(system.sys, "platform", "win32")
    present.add("clip")

    assert system.copy("を") == "clip"
    assert calls == [(("clip",), "を".encode("utf-16-le"))]


def test_no_tool_and_no_terminal_copies_nothing(monkeypatch, tools):
    """Outside a terminal, the OSC 52 sequence would only pollute a redirected output."""
    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(system.sys.stdout, "isatty", lambda: False, raising=False)
    assert system.copy("kotogen deck install") == ""


def test_without_a_tool_the_terminal_is_asked_itself(monkeypatch, tools, capsys):
    """OSC 52 crosses a remote session but confirms nothing: the name returned
    lets the caller say so."""
    import base64

    monkeypatch.setattr(system.sys, "platform", "linux")
    monkeypatch.setattr(system.sys.stdout, "isatty", lambda: True, raising=False)

    assert system.copy("kotogen backup --list") == system.OSC52
    payload = base64.b64encode(b"kotogen backup --list").decode("ascii")
    assert capsys.readouterr().out == f"\033]52;c;{payload}\a"


def test_only_this_module_tests_the_platform():
    """The rest of the program asks `system.windows()` or `system.macos()`."""
    package = Path(system.__file__).parent
    found = []
    for path in sorted(package.rglob("*.py")):
        if path == Path(system.__file__):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and (node.value.id, node.attr) in {("sys", "platform"), ("os", "name")}):
                found.append(f"{path.relative_to(package).as_posix()}:{node.lineno}")
    assert found == []


# ── Running a program by its bare name ───────────────────────────────────────

@pytest.mark.parametrize("on_windows", [True, False])
def test_windows_leaves_the_current_folder_out_of_a_bare_name(monkeypatch, on_windows):
    """An `ffmpeg.exe` planted in the folder kotogen is run from is not run."""
    monkeypatch.setattr(system, "windows", lambda: on_windows)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    system.ignore_current_folder()
    assert ("NoDefaultCurrentDirectoryInExePath" in system.os.environ) is on_windows


# ── Writing a file whole ─────────────────────────────────────────────────────

def _interrupted(*args, **kwargs):
    raise KeyboardInterrupt


def test_a_write_cut_short_leaves_the_old_content(monkeypatch, tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"old": 1}', encoding="utf-8")
    monkeypatch.setattr(os, "replace", _interrupted)
    with pytest.raises(KeyboardInterrupt):
        system.write_whole(path, '{"new": 2}')
    assert path.read_text(encoding="utf-8") == '{"old": 1}'
    assert list(tmp_path.iterdir()) == [path]


def test_two_writers_at_once_do_not_share_a_temporary(monkeypatch, tmp_path):
    """A second write landing in the middle of the first, as two threads or two
    commands may: neither takes the other's temporary away."""
    path = tmp_path / "history.json"
    replace = os.replace

    def overlapped(source, target):
        monkeypatch.setattr(os, "replace", replace)
        system.write_whole(path, "second")
        replace(source, target)

    monkeypatch.setattr(os, "replace", overlapped)
    system.write_whole(path, "first")
    assert path.read_text(encoding="utf-8") == "first"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name == "nt", reason="Windows has no mode bits to close a file")
def test_a_private_file_is_closed_to_the_other_accounts(tmp_path):
    path = tmp_path / "secrets.env"
    system.write_whole(path, "KEY=1\n", private=True)
    assert path.stat().st_mode & 0o777 == 0o600


def test_a_whole_write_ends_its_lines_on_a_line_feed(tmp_path):
    path = tmp_path / "cards.tsv"
    system.write_whole(path, "a\nb\n")
    assert path.read_bytes() == b"a\nb\n"


def test_a_whole_write_replaces_the_file_and_creates_its_folder(tmp_path):
    path = tmp_path / "new" / "history.json"
    system.write_whole(path, "猫\n")
    assert path.read_bytes() == "猫\n".encode()


@pytest.mark.parametrize("on_windows", [True, False], ids=["Windows", "elsewhere"])
def test_a_replace_refused_for_an_instant_is_tried_again_on_windows(monkeypatch, tmp_path,
                                                                    on_windows):
    """OneDrive or an indexer holds the file for an instant: Windows refuses the
    replace, and the next try goes through. Elsewhere a refusal is no such thing."""
    path = tmp_path / "cards.tsv"
    path.write_text("old\n", encoding="utf-8")
    replace, refusals = os.replace, []

    def busy_once(source, target):
        if not refusals:
            refusals.append(target)
            raise PermissionError(13, "Access is denied", str(target))
        replace(source, target)

    monkeypatch.setattr(os, "replace", busy_once)
    monkeypatch.setattr(system, "windows", lambda: on_windows)
    monkeypatch.setattr(system.time, "sleep", lambda seconds: None)
    if on_windows:
        system.write_whole(path, "new\n")
        assert path.read_text(encoding="utf-8") == "new\n"
    else:
        with pytest.raises(PermissionError):
            system.write_whole(path, "new\n")
    assert list(tmp_path.iterdir()) == [path]


# ── The terminal ──────────────────────────────────────────────────────────────

def test_the_null_device_is_no_terminal():
    """Windows answers `isatty` for NUL as for a console: `kotogen < NUL` would
    pass for somebody at the keyboard, and mark the guide as seen."""
    with open(os.devnull, encoding="utf-8") as nul:
        assert not system.terminal(nul)


def test_a_stand_in_with_no_device_is_taken_at_its_word():
    """The tests fake a terminal on a stream that has no descriptor."""
    class Claims:
        def isatty(self):
            return True

        def fileno(self):
            raise OSError("no descriptor")

    assert system.terminal(Claims())


def test_a_stream_that_cannot_say_is_no_terminal():
    class Closed:
        def isatty(self):
            raise ValueError("I/O operation on closed file")

    assert not system.terminal(Closed())
