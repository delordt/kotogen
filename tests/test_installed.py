"""The record of what kotogen last wrote into each note type (`installed`).

It tells a release from a touch-up made in Anki, so it never says more than it
knows: per profile, empty when damaged, untouched when a later release wrote it.
"""

from __future__ import annotations

import json

from kotogen.anki import installed


def test_what_is_remembered_is_recalled():
    written = {"cards": {"Recognition": {"Front": "front", "Back": "back"}}, "css": "css"}
    installed.remember("User 1", 1000, written)
    assert installed.recall("User 1", 1000) == written


def test_nothing_recorded_is_an_empty_record():
    """A type installed before the record existed, by hand or from elsewhere."""
    assert installed.recall("User 1", 1000) == {}


def test_each_profile_has_its_own_record():
    """One profile copied from another carries its note types under the same
    IDs: what was written into one says nothing of the other."""
    installed.remember("User 1", 1000, {"css": "one"})
    assert installed.recall("User 2", 1000) == {}
    installed.remember("User 2", 1000, {"css": "two"})
    assert installed.recall("User 1", 1000) == {"css": "one"}


def test_a_new_record_replaces_the_old_one_of_its_type_only():
    installed.remember("User 1", 1000, {"css": "old"})
    installed.remember("User 1", 2000, {"css": "other"})
    installed.remember("User 1", 1000, {"css": "new"})
    assert installed.recall("User 1", 1000) == {"css": "new"}
    assert installed.recall("User 1", 2000) == {"css": "other"}


def test_a_truncated_record_is_read_as_nothing_and_written_over():
    """What it said is lost either way: the next install asks, as it did
    before the record existed, and writes a whole one."""
    path = installed.path()
    path.parent.mkdir(parents=True)
    path.write_text('{"version": 1, "prof', encoding="utf-8")
    assert installed.recall("User 1", 1000) == {}

    installed.remember("User 1", 1000, {"css": "css"})
    assert installed.recall("User 1", 1000) == {"css": "css"}


def test_a_record_written_by_a_later_release_is_neither_read_nor_overwritten():
    """Read, its entries could be misunderstood; overwritten, the release that
    wrote it would lose them."""
    path = installed.path()
    path.parent.mkdir(parents=True)
    later = {"version": installed.VERSION + 1,
             "profiles": {"User 1": {"1000": {"css": "theirs"}}}}
    path.write_text(json.dumps(later), encoding="utf-8")

    assert installed.recall("User 1", 1000) == {}
    installed.remember("User 1", 1000, {"css": "ours"})
    assert json.loads(path.read_text(encoding="utf-8")) == later


def test_no_temporary_file_is_left_behind():
    installed.remember("User 1", 1000, {"css": "css"})
    assert [p.name for p in installed.path().parent.iterdir()] == [installed.FILE]
