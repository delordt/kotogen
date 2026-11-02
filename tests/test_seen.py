"""History of the sources already handled: partitioning, damage, forgetting.

The file does not rebuild itself: read wrong, it comes back empty, and the next
pass pays again in AI calls for everything already done.
"""

from __future__ import annotations

import pytest

from kotogen import seen


@pytest.fixture
def history(tmp_path, monkeypatch):
    """A throwaway path: the machine's history is never touched."""
    monkeypatch.setattr(seen, "FILE", tmp_path / "seen.json")
    return tmp_path


# ── Writing and reading ───────────────────────────────────────────────────────

def test_mark_then_load(history):
    assert seen.load("audio", "nhk") == {}
    seen.mark("audio", "nhk", "ne2026071201", "Title")
    assert seen.load("audio", "nhk") == {"ne2026071201": "Title"}


def test_marking_without_a_title_keeps_the_one_already_known(history):
    seen.mark("audio", "teppei", "guid-1", "Episode 500")
    seen.mark("audio", "teppei", "guid-1")
    assert seen.load("audio", "teppei") == {"guid-1": "Episode 500"}


def test_marking_without_an_identifier_writes_nothing(history):
    seen.mark("audio", "nhk", "", "Title")
    assert seen.load("audio", "nhk") == {}
    assert not seen.FILE.exists()


def test_every_mode_has_its_name_in_every_table():
    """The history screen names the modes through a variable, which the scan of
    `_("literal")` misses; `reading` takes a context, being a count elsewhere."""
    from kotogen import i18n

    for lang in i18n.available():
        table = i18n._load(lang)
        assert not [mode for mode in seen.MODES.values()
                    if table and f"mode|{mode}" not in table], lang


def test_a_mark_cut_short_keeps_what_was_already_known(history, monkeypatch):
    """A truncated file reads as empty, and everything in it would be paid again."""
    import os

    seen.mark("audio", "nhk", "ne2026071201", "Title")
    replace = os.replace

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        seen.mark("audio", "nhk", "ne2026071202", "Another")
    monkeypatch.setattr(os, "replace", replace)
    assert seen.load("audio", "nhk") == {"ne2026071201": "Title"}


def test_the_sources_do_not_mix(history):
    # Two sources may share an identifier: unpartitioned, one hides the other.
    seen.mark("audio", "nhk", "same-id", "Article")
    seen.mark("audio", "teppei", "same-id", "Episode")
    assert seen.load("audio", "nhk") == {"same-id": "Article"}
    assert seen.load("audio", "teppei") == {"same-id": "Episode"}


def test_the_modes_do_not_mix(history):
    seen.mark("audio", "nhk", "ne2026071201", "Title")
    assert seen.load("vocab", "nhk") == {}


# ── Damaged files ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("content", ['{"broken": ', '[]', '"text"', ''])
def test_an_unreadable_file_gives_an_empty_history(history, content):
    # A lost history costs AI calls; it must not also stop the command.
    seen.FILE.write_text(content, encoding="utf-8")
    assert seen.load("audio", "nhk") == {}


# ── Inventory and forgetting ──────────────────────────────────────────────────
# Looking at the history and forgetting a source are commands, not hand edits
# of the JSON.

def test_the_inventory_aggregates_the_modes_of_one_source(history):
    seen.mark("audio", "nhk", "ne1", "A")
    seen.mark("reading", "nhk", "ne2", "B")
    seen.mark("vocab", "nhk", "ne3", "C")
    assert seen.inventory() == [
        seen.Trace("nhk", 3, ("vocabulary", "listening", "reading"))]


def test_the_inventory_puts_the_best_stocked_source_first(history):
    seen.mark("audio", "teppei", "guid-1", "One")
    for number in range(4):
        seen.mark("audio", "nhk", f"ne{number}", "Article")
    assert [trace.source for trace in seen.inventory()] == ["nhk", "teppei"]


def test_the_inventory_of_an_empty_history_is_empty(history):
    assert seen.inventory() == []
    assert seen.describe() == "empty"


def test_describe_agrees_its_plurals(history):
    seen.mark("audio", "nhk", "ne1", "A")
    assert seen.describe() == "1 entry, 1 source"
    seen.mark("audio", "teppei", "guid-1", "One")
    assert seen.describe() == "2 entries, 2 sources"


def test_forgetting_a_source_takes_it_out_of_every_mode(history):
    seen.mark("audio", "nhk", "ne1", "A")
    seen.mark("reading", "nhk", "ne2", "B")
    seen.mark("audio", "teppei", "guid-1", "One")
    assert seen.forget("nhk") == 2
    assert seen.load("audio", "nhk") == {}
    assert seen.load("reading", "nhk") == {}
    # And does not touch the others: one programme is forgotten, not the history.
    assert seen.load("audio", "teppei") == {"guid-1": "One"}


def test_forgetting_without_a_source_empties_everything(history):
    seen.mark("audio", "nhk", "ne1", "A")
    seen.mark("audio", "teppei", "guid-1", "One")
    assert seen.forget() == 2
    assert seen.inventory() == []


def test_forgetting_an_unknown_source_writes_nothing(history):
    assert seen.forget("never-seen") == 0
    assert not seen.FILE.exists()
