"""The settings: where they get written, what they are worth, what they do not
lose.

Guarded here: a setting written where the next launch reads it, an API key
readable by its owner alone, and a write that, interrupted, never leaves a
truncated file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from kotogen import settings, system

# The real search for the `.env`, captured before `conftest.py` neutralises it.
_real_repo_env = settings.repo_env


@pytest.fixture
def elsewhere(tmp_path, monkeypatch):
    """A machine with no repository: no `.env` around, no existing configuration.

    The case of a wheel installed outside the clone. The source root, where the
    `.env` is looked for, moves to a folder with no `pyproject.toml`, as a wheel
    has: the real one may hold the real key.
    """
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setattr(system, "config_dir", lambda: home)
    monkeypatch.setattr(settings, "ROOT", tmp_path / "site-packages")
    monkeypatch.setattr(settings, "repo_env", _real_repo_env)
    monkeypatch.chdir(work)
    return home


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A cloned repository, with its `.env` at the root and the current folder
    inside it."""
    root = tmp_path / "kotogen"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    (root / ".env").write_text("KOTOGEN_CURRENCY=EUR\n", encoding="utf-8")
    monkeypatch.setattr(system, "config_dir", lambda: tmp_path / "home")
    monkeypatch.setattr(settings, "ROOT", root)
    monkeypatch.setattr(settings, "repo_env", _real_repo_env)
    monkeypatch.chdir(root / "src")  # from a subfolder, as in daily use
    return root


# ── Where the setting lands ───────────────────────────────────────────────────

def test_outside_a_repo_the_keys_have_their_own_file(elsewhere):
    """An API key and a display currency are not filed in the same place."""
    assert settings.path_for("OPENROUTER_API_KEY") == elsewhere / "secrets.env"
    assert settings.path_for("KOTOGEN_CURRENCY") == elsewhere / "settings.env"


def test_outside_a_repo_the_setting_does_not_follow_the_current_folder(
        elsewhere, tmp_path):
    """Written from one folder, read back from another: a file in the current
    folder would be lost to the next launch elsewhere."""
    written = settings.write("KOTOGEN_CURRENCY", "JPY")
    assert written == elsewhere / "settings.env"
    assert not list(Path.cwd().glob("*.env"))

    another = tmp_path / "elsewhere-again"
    another.mkdir()
    os.chdir(another)
    settings.load()
    assert settings.text("KOTOGEN_CURRENCY") == "JPY"


def test_inside_a_repo_only_the_keys_go_into_the_env(repo, tmp_path):
    """A `.env` carries secrets; a display currency is not one of them."""
    assert settings.path_for("OPENROUTER_API_KEY") == repo / ".env"
    assert settings.path_for("KOTOGEN_MODEL") == tmp_path / "home" / "settings.env"


def test_a_setting_already_set_by_hand_is_rewritten_in_place(repo):
    """`KOTOGEN_CURRENCY=EUR` is active in that `.env`: it is rewritten there.

    The `.env` is read first: written elsewhere, its stale value would win.
    """
    assert settings.path_for("KOTOGEN_CURRENCY") == repo / ".env"
    settings.write("KOTOGEN_CURRENCY", "JPY")
    assert "KOTOGEN_CURRENCY=JPY" in (repo / ".env").read_text(encoding="utf-8")


def test_a_commented_out_line_does_not_hold_the_setting(repo, tmp_path):
    """`.env.example` copied to `.env` carries thirty settings, all commented
    out: following the README must not pull every setting into the key file."""
    (repo / ".env").write_text("# KOTOGEN_MODEL=example\n", encoding="utf-8")
    assert settings.path_for("KOTOGEN_MODEL") == tmp_path / "home" / "settings.env"


def test_the_repo_env_is_read_wherever_the_command_is_typed(repo, tmp_path):
    """The `.env` of the program's sources is read wherever it is launched."""
    settings.load()
    assert settings.raw("KOTOGEN_CURRENCY") == "EUR"

    os.environ.pop("KOTOGEN_CURRENCY")
    os.chdir(tmp_path)
    settings.load()
    assert settings.raw("KOTOGEN_CURRENCY") == "EUR"


def test_the_env_of_the_current_folder_is_not_ours(elsewhere):
    """Another project's `.env` is neither read nor written: a key typed in the
    menu would land in a file that project may commit."""
    (Path.cwd() / ".env").write_text(
        "KOTOGEN_CURRENCY=EUR\nOPENROUTER_API_KEY=theirs\n", encoding="utf-8")
    assert settings.repo_env() is None
    settings.load()
    assert settings.raw("KOTOGEN_CURRENCY") == ""
    assert settings.raw("OPENROUTER_API_KEY") == ""
    assert settings.path_for("OPENROUTER_API_KEY") == elsewhere / "secrets.env"


def test_a_line_outside_the_registry_stays_in_its_file(repo, monkeypatch):
    """The environment of the process is the one pip and git are launched in:
    a `PIP_INDEX_URL` read from a file would choose where pip installs from."""
    monkeypatch.delenv("PIP_INDEX_URL", raising=False)
    (repo / ".env").write_text(
        "PIP_INDEX_URL=https://example.invalid/simple\nKOTOGEN_CURRENCY=EUR\n",
        encoding="utf-8")
    settings.load()
    # Taken out before the check, so that a failure leaves nothing behind it.
    leaked = os.environ.pop("PIP_INDEX_URL", None)
    assert leaked is None
    assert settings.raw("KOTOGEN_CURRENCY") == "EUR"


# ── What wins over what ───────────────────────────────────────────────────────

def test_the_real_environment_beats_the_file(elsewhere, monkeypatch):
    """An `export` in the shell wins, and that is the expected rule of a `.env`."""
    settings.write("KOTOGEN_MODEL", "from-the-file")
    monkeypatch.setenv("KOTOGEN_MODEL", "from-the-shell")
    settings.load()
    assert settings.text("KOTOGEN_MODEL") == "from-the-shell"


def test_both_files_of_the_profile_are_read(elsewhere):
    """Settings and secrets are separate, but loaded together."""
    settings.write("KOTOGEN_CURRENCY", "GBP")
    settings.write("OPENROUTER_API_KEY", "sk-or-secret")
    settings.load()
    assert settings.raw("KOTOGEN_CURRENCY") == "GBP"
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-secret"


# ── What a setting is worth ───────────────────────────────────────────────────

def test_the_registry_default_serves_when_nothing_is_set():
    assert settings.text("KOTOGEN_PROVIDER") == "openrouter"
    assert settings.text("KOTOGEN_VOCAB_DECK") == "Japanese::Vocabulary"


@pytest.mark.parametrize("value, expected", [
    ("1", True), ("yes", True), ("ON", True), ("true", True),
    ("0", False), ("no", False), ("off", False), ("False", False),
])
def test_the_booleans_speak_the_same_language_everywhere(monkeypatch, value, expected):
    """Yes and no read the same in every module."""
    monkeypatch.setenv("KOTOGEN_AUTO_SEND", value)
    monkeypatch.setenv("KOTOGEN_BACKUP", value)
    assert settings.flag("KOTOGEN_AUTO_SEND") is expected
    assert settings.flag("KOTOGEN_BACKUP") is expected


def test_an_unreadable_boolean_gives_the_default(monkeypatch):
    """`KOTOGEN_BACKUP=maybe` lets the command through, safeguard included.

    A value not understood flips neither a safeguard (backup) nor a switch (send).
    """
    monkeypatch.setenv("KOTOGEN_BACKUP", "maybe")
    monkeypatch.setenv("KOTOGEN_AUTO_SEND", "maybe")
    assert settings.flag("KOTOGEN_BACKUP") is True
    assert settings.flag("KOTOGEN_AUTO_SEND") is False


def test_a_list_is_read_without_its_spaces(monkeypatch):
    monkeypatch.setenv("KOTOGEN_SKIP", " grammar , ,audio ")
    assert settings.items("KOTOGEN_SKIP") == ["grammar", "audio"]


def test_a_setting_outside_the_registry_shows_at_once():
    """A typo in the code, not a user error: it has to shout."""
    with pytest.raises(KeyError):
        settings.text("KOTOGEN_MADE_UP")


# ── Writing without losing anything ───────────────────────────────────────────

def test_the_commented_line_is_the_one_that_gets_switched_on(elsewhere):
    """That is how an example becomes a setting: no duplicate left behind."""
    path = elsewhere / "settings.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# KOTOGEN_CURRENCY=EUR\nKOTOGEN_MODEL=x\n", encoding="utf-8")
    settings.write("KOTOGEN_CURRENCY", "JPY")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == ["KOTOGEN_CURRENCY=JPY", "KOTOGEN_MODEL=x"]


def test_a_neighbouring_setting_is_not_wiped(elsewhere):
    """`KOTOGEN_CURRENCY` must not take `KOTOGEN_CURRENCY_RATE` with it."""
    settings.write("KOTOGEN_CURRENCY_RATE", "0.86")
    settings.write("KOTOGEN_CURRENCY", "EUR")
    content = (elsewhere / "settings.env").read_text(encoding="utf-8")
    assert "KOTOGEN_CURRENCY_RATE=0.86" in content
    assert "KOTOGEN_CURRENCY=EUR" in content


def test_an_interrupted_write_does_not_destroy_the_file(elsewhere, monkeypatch):
    """The file stays the old one, complete: the write goes through a rename."""
    settings.write("OPENROUTER_API_KEY", "sk-or-the-real-one")
    path = elsewhere / "secrets.env"
    before = path.read_bytes()

    def interrupted_replace(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted_replace)
    with pytest.raises(KeyboardInterrupt):
        settings.write("OPENROUTER_API_KEY", "sk-or-the-new-one")

    assert path.read_bytes() == before
    assert not list(elsewhere.glob("*.tmp")), "the temporary has to be picked up"


def test_no_temporary_survives_a_successful_write(elsewhere):
    settings.write("KOTOGEN_CURRENCY", "EUR")
    settings.write("KOTOGEN_CURRENCY", "JPY")
    assert [p.name for p in elsewhere.iterdir()] == ["settings.env"]


@pytest.mark.skipif(sys.platform == "win32",
                    reason="chmod only toggles read-only under Windows")
def test_the_secrets_are_readable_by_their_owner_alone(elsewhere):
    """An API key in 0644 is a key given to every account on the machine."""
    path = settings.write("OPENROUTER_API_KEY", "sk-or-secret")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(elsewhere.stat().st_mode & 0o777) == "0o700"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="chmod only toggles read-only under Windows")
def test_writing_into_a_repo_does_not_close_the_repo(repo):
    """The file closes, not the folder around it: our configuration folder goes
    0700, a repository root does not."""
    before = repo.stat().st_mode & 0o777
    path = settings.write("OPENROUTER_API_KEY", "sk-or-secret")
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert repo.stat().st_mode & 0o777 == before
