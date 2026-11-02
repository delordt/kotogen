"""Where the choices about the cards are filed, and how the library reads them.

The adapter writes `templates.env` and the library reads it, for the language
of the cards: both have to find the same file, and read it the same way.
"""

from __future__ import annotations

from kotogen import choices, settings, system


def test_the_file_sits_with_the_settings():
    assert choices.file() == system.config_dir() / choices.FILE


def test_a_file_beside_the_repository_env_is_the_one(tmp_path, monkeypatch):
    """A user who keeps their settings in their clone keeps them all there."""
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / choices.FILE).write_text("all.lang=fr\n", encoding="utf-8")
    monkeypatch.setattr(settings, "repo_env", lambda: tmp_path / ".env")
    assert choices.file() == tmp_path / choices.FILE
    assert choices.language() == "fr"


def test_comments_and_blank_lines_are_not_choices():
    choices.file().parent.mkdir(parents=True, exist_ok=True)
    choices.file().write_text("# a note\n\nvocab.tts = yes\nall.lang=fr\nbroken\n",
                              encoding="utf-8")
    assert choices.values() == {"vocab.tts": "yes", "all.lang": "fr"}


def test_a_language_is_read_as_it_is_written():
    """Read as a name: whether it exists is for the instructions to say."""
    choices.file().parent.mkdir(parents=True, exist_ok=True)
    choices.file().write_text("all.lang=kl\n", encoding="utf-8")
    assert choices.language() == "kl"


def test_no_file_names_no_language():
    assert choices.values() == {}
    assert choices.language() == ""


def test_a_file_saved_with_a_bom_is_read_the_same():
    """Notepad and PowerShell 5 open a UTF-8 file on a BOM, which would glue
    itself to the first key and lose its choice."""
    choices.file().parent.mkdir(parents=True, exist_ok=True)
    choices.file().write_text("all.lang=fr\n", encoding="utf-8-sig")
    assert choices.language() == "fr"
