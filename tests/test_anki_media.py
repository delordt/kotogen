"""Anki's media library: finding it, and putting files into it.

AnkiConnect is replaced: by a fake of `urlopen` where the address of the
profile is asked of it, by fakes of its answers where files are put down.
"""

import fnmatch
import os
from pathlib import Path

import pytest

from kotogen.anki import connect, media
from kotogen.anki.connect import AnkiStatus


@pytest.fixture(autouse=True)
def no_status_cache(monkeypatch):
    """The state cache must not leak from one test to the next."""
    monkeypatch.setattr(connect, "_status_cache", None)


def fake_requests(monkeypatch, answers: dict) -> list[str]:
    """Replaces request(): gives back answers[action], or raises if absent."""
    calls: list[str] = []

    def request(action, *, timeout=60, **params):
        calls.append(action)
        if action not in answers:
            raise ConnectionError("unreachable")
        return answers[action]

    monkeypatch.setattr(connect, "request", request)
    monkeypatch.setattr(media, "anki", request)
    return calls


# ── media_dir() ───────────────────────────────────────────────────────────────

def test_media_dir_env_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("KOTOGEN_MEDIA_DIR", str(tmp_path))
    assert media.media_dir() == tmp_path


def test_media_dir_from_ankiconnect(monkeypatch, tmp_path):
    monkeypatch.delenv("KOTOGEN_MEDIA_DIR", raising=False)
    fake_requests(monkeypatch, {
        "version": 6, "deckNames": [], "modelNames": [],
        "getMediaDirPath": str(tmp_path / "collection.media"),
    })
    assert media.media_dir() == tmp_path / "collection.media"


def test_media_dir_picks_the_most_recent_profile(monkeypatch, tmp_path):
    monkeypatch.delenv("KOTOGEN_MEDIA_DIR", raising=False)
    fake_requests(monkeypatch, {})  # Anki closed: local detection
    for name, mtime in (("Old", 1_000_000), ("Recent", 2_000_000)):
        profile = tmp_path / name
        (profile / "collection.media").mkdir(parents=True)
        collection = profile / "collection.anki2"
        collection.write_bytes(b"")
        os.utime(collection, (mtime, mtime))
    monkeypatch.setattr(media, "_anki_base_dirs", lambda: [tmp_path])
    assert media.media_dir() == tmp_path / "Recent" / "collection.media"


def test_media_dir_none_without_any_profile(monkeypatch, tmp_path):
    monkeypatch.delenv("KOTOGEN_MEDIA_DIR", raising=False)
    fake_requests(monkeypatch, {})
    monkeypatch.setattr(media, "_anki_base_dirs", lambda: [tmp_path])
    assert media.media_dir() is None


# ── Where the profiles are, per system ────────────────────────────────────────

@pytest.fixture
def linux(monkeypatch, tmp_path):
    """A faked Linux system, with the home folder in tmp_path."""
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    return tmp_path


def test_linux_looks_at_the_native_install_and_the_flatpak(linux):
    """Anki installs both ways under Linux, and the Flatpak confines its HOME."""
    assert media._anki_base_dirs() == [
        linux / ".local" / "share" / "Anki2",
        linux / ".var" / "app" / "net.ankiweb.Anki" / "data" / "Anki2",
    ]


def test_the_data_home_setting_is_honoured(monkeypatch, linux, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert media._anki_base_dirs()[0] == tmp_path / "data" / "Anki2"


def test_a_flatpak_profile_is_found(monkeypatch, linux):
    """The concrete case: Anki installed as a Flatpak, closed, media to copy."""
    monkeypatch.delenv("KOTOGEN_MEDIA_DIR", raising=False)
    fake_requests(monkeypatch, {})  # Anki closed: local detection
    profile = linux / ".var" / "app" / "net.ankiweb.Anki" / "data" / "Anki2" / "User 1"
    (profile / "collection.media").mkdir(parents=True)
    (profile / "collection.anki2").write_bytes(b"")
    assert media.media_dir() == profile / "collection.media"


@pytest.mark.parametrize("platform, expected", [
    ("win32", "%APPDATA%"),
    ("darwin", "Library/Application Support"),
    ("linux", ".local/share"),
])
def test_the_media_hint_speaks_the_language_of_this_system(
        monkeypatch, platform, expected):
    monkeypatch.delenv("KOTOGEN_MEDIA_DIR", raising=False)
    fake_requests(monkeypatch, {})
    monkeypatch.setattr(media, "_anki_base_dirs", list)
    monkeypatch.setattr("sys.platform", platform)
    assert expected in media.media_dir_hint()


def test_the_media_hint_gives_the_real_path_when_it_is_known(monkeypatch, tmp_path):
    """Detection succeeded: say the path on the disk, not a typical location."""
    monkeypatch.setenv("KOTOGEN_MEDIA_DIR", str(tmp_path / "collection.media"))
    assert media.media_dir_hint() == str(tmp_path / "collection.media")


# ── Installing the media ──────────────────────────────────────────────────────

def anki(monkeypatch, connected: bool, answer=None) -> None:
    monkeypatch.setattr(connect, "status", lambda **kw: AnkiStatus(connected=connected))
    if answer is not None:
        monkeypatch.setattr(media, "anki", answer)


def test_an_open_anki_goes_through_ankiconnect(monkeypatch, tmp_path):
    stored = []
    anki(monkeypatch, True, lambda action, **p: stored.append(p["filename"]))
    source = tmp_path / "ne1.mp3"
    source.write_bytes(b"x")
    assert media.install_media_files([source]) == []
    assert stored == ["ne1.mp3"]


def test_a_closed_anki_is_copied_into_directly(monkeypatch, tmp_path):
    folder = tmp_path / "collection.media"
    folder.mkdir()
    anki(monkeypatch, False)
    monkeypatch.setattr(media, "media_dir", lambda: folder)
    source = tmp_path / "ne1.mp3"
    source.write_bytes(b"x")
    assert media.install_media_files([source]) == []
    assert (folder / "ne1.mp3").read_bytes() == b"x"


def test_an_unfound_media_library_gives_the_files_back(monkeypatch, tmp_path):
    """The caller says what to copy by hand: nothing is lost in silence."""
    anki(monkeypatch, False)
    monkeypatch.setattr(media, "media_dir", lambda: None)
    source = tmp_path / "ne1.mp3"
    assert media.install_media_files([source]) == [source]


def test_the_name_anki_kept_is_the_one_that_comes_back(monkeypatch, tmp_path):
    """Anki lower-cases the names: `store_media_files` notes it instead of
    ignoring it."""
    anki(monkeypatch, True, lambda action, **p: p["filename"].lower())
    source = tmp_path / "N5_問題1_01_e61b5e30.mp3"
    source.write_bytes(b"x")
    renamed: dict[str, str] = {}
    assert media.install_media_files([source], renamed) == []
    assert renamed == {"N5_問題1_01_e61b5e30.mp3": "n5_問題1_01_e61b5e30.mp3"}


def test_a_file_already_there_is_asked_for_under_its_own_case(monkeypatch, tmp_path):
    """Stored earlier as `n3_…`, the file is answered as the `N3_…` offered:
    Windows finds it either way, a phone does not. The folder has the name."""
    def answer(action, **p):
        if action == "storeMediaFile":
            return p["filename"]
        return [name for name in ["n3_問題1_01_6d729c7a.mp3", "other.mp3"]
                if fnmatch.fnmatchcase(name, p["pattern"])]

    anki(monkeypatch, True, answer)
    source = tmp_path / "N3_問題1_01_6d729c7a.mp3"
    source.write_bytes(b"x")
    renamed: dict[str, str] = {}
    assert media.install_media_files([source], renamed) == []
    assert renamed == {"N3_問題1_01_6d729c7a.mp3": "n3_問題1_01_6d729c7a.mp3"}


def test_a_name_kept_as_it_stands_renames_nothing(monkeypatch, tmp_path):
    anki(monkeypatch, True, lambda action, **p: p["filename"])
    source = tmp_path / "already_lower.mp3"
    source.write_bytes(b"x")
    renamed: dict[str, str] = {}
    assert media.install_media_files([source], renamed) == []
    assert renamed == {}


def test_a_file_already_in_place_is_not_erased(monkeypatch, tmp_path):
    """`deleteExisting=False`: the earlier cards still call for that file."""
    seen = []
    anki(monkeypatch, True, lambda action, **p: seen.append(p) or p["filename"])
    source = tmp_path / "a.mp3"
    source.write_bytes(b"x")
    media.install_media_files([source])
    assert seen[0]["deleteExisting"] is False


def test_a_cut_ankiconnect_gives_the_remaining_files_back(monkeypatch, tmp_path):
    def boom(action, **params):
        raise ConnectionError("Anki closed along the way")

    anki(monkeypatch, True, boom)
    files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    assert media.install_media_files(files) == files
