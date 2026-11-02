"""Backing the decks up: snapshot, retention, comparison, restoration.

What is tested is that a backup can be restored, and that a restoration never
undoes work it was not asked to undo, rather than the JSON round trips.
"""

from __future__ import annotations

import json
import time

import pytest

from kotogen.anki import backup

# -- A fake AnkiConnect --------------------------------------------------------

class FakeAnki:
    """Collection in memory, answering only the actions that are used.

    It records the calls, to check that a restoration has NOT called
    `deleteNotes`, which no final state proves.
    """

    def __init__(self, notes: dict[str, list[dict]] | None = None):
        self.notes = notes or {}          # note type -> [AnkiConnect note]
        self.templates: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.next_id = 9000

    # -- the call the module intercepts ---------------------------------------
    def __call__(self, action: str, *, timeout: float = 60, **params):
        self.calls.append((action, params))
        return getattr(self, f"do_{action}", self.do_unknown)(**params)

    def do_unknown(self, **params):
        return None

    def _all(self) -> list[dict]:
        return [note for notes in self.notes.values() for note in notes]

    def _find(self, note_id: int) -> dict | None:
        return next((n for n in self._all() if n["noteId"] == note_id), None)

    def _notetype_of(self, note_id: int) -> str:
        return next(name for name, notes in self.notes.items()
                    if any(n["noteId"] == note_id for n in notes))

    # -- reading ---------------------------------------------------------------
    def do_findNotes(self, query: str):
        notetype = query.split("note:")[1].strip('"')
        return [n["noteId"] for n in self.notes.get(notetype, [])]

    def do_notesInfo(self, notes: list[int]):
        return [n for n in self._all() if n["noteId"] in notes]

    def do_findCards(self, query: str):
        notetype = query.split("note:")[1].strip('"')
        return [c for n in self.notes.get(notetype, []) for c in n["cards"]]

    def do_cardsInfo(self, cards: list[int]):
        out = []
        for note in self._all():
            for card_id in note["cards"]:
                if card_id in cards:
                    out.append({"cardId": card_id, "note": note["noteId"],
                                **note["schedule"][card_id]})
        return out

    def do_modelFieldNames(self, modelName: str):
        return list(self.templates.get(modelName, {}).get("fields", []))

    def do_modelTemplates(self, modelName: str):
        return dict(self.templates.get(modelName, {}).get("cards", {}))

    def do_modelStyling(self, modelName: str):
        return {"css": self.templates.get(modelName, {}).get("css", "")}

    # -- writing ---------------------------------------------------------------
    def do_updateNoteFields(self, note: dict):
        target = self._find(note["id"])
        for name, value in note["fields"].items():
            target["fields"][name] = {"value": value}

    def do_addTags(self, notes: list[int], tags: str):
        for note_id in notes:
            self._find(note_id)["tags"] += tags.split()

    def do_removeTags(self, notes: list[int], tags: str):
        for note_id in notes:
            note = self._find(note_id)
            note["tags"] = [t for t in note["tags"] if t not in tags.split()]

    def do_setSpecificValueOfCard(self, card: int, keys, newValues, **kw):
        for note in self._all():
            if card in note["schedule"]:
                note["schedule"][card].update(dict(zip(keys, newValues)))
        return [True] * len(keys)

    def do_addNote(self, note: dict):
        self.next_id += 1
        fresh = {
            "noteId": self.next_id,
            "guid": f"g{self.next_id}",
            "fields": {k: {"value": v} for k, v in note["fields"].items()},
            "tags": list(note["tags"]),
            "cards": [self.next_id * 10],
            "schedule": {self.next_id * 10: dict(NEW_CARD)},
        }
        self.notes.setdefault(note["modelName"], []).append(fresh)
        return self.next_id

    def do_deleteNotes(self, notes: list[int]):
        for name, kept in self.notes.items():
            self.notes[name] = [n for n in kept if n["noteId"] not in notes]

    def do_updateModelTemplates(self, model: dict):
        self.templates.setdefault(model["name"], {})["cards"] = model["templates"]

    def do_updateModelStyling(self, model: dict):
        self.templates.setdefault(model["name"], {})["css"] = model["css"]


MATURE_CARD = {"type": 2, "queue": 2, "due": 500, "ivl": 90,
               "factor": 2500, "reps": 12, "lapses": 1}
NEW_CARD = {"type": 0, "queue": 0, "due": 0, "ivl": 0,
            "factor": 0, "reps": 0, "lapses": 0}


def _note(note_id: int, expression: str, translation: str, *,
          tags: list[str] | None = None, schedule: dict | None = None) -> dict:
    card_id = note_id * 10
    return {
        "noteId": note_id,
        "guid": f"g{note_id}",
        "fields": {"Expression": {"value": expression},
                   "Translation": {"value": translation}},
        "tags": list(tags or []),
        "cards": [card_id],
        "schedule": {card_id: dict(schedule or MATURE_CARD)},
    }


@pytest.fixture
def anki(monkeypatch, tmp_path):
    """A simulated Anki and a fresh backup folder, set through
    KOTOGEN_BACKUP_DIR as by a user filing their backups elsewhere."""
    fake = FakeAnki({"Vocabulary": [
        _note(1, "食[た]べる", "Manger"),
        _note(2, "飲[の]む", "Boire", tags=["Verb::一段動詞"]),
    ]})
    fake.templates["Vocabulary"] = {
        "fields": ["Expression", "Translation"],
        "cards": {"Recognition": {"Front": "{{Expression}}", "Back": "{{Translation}}"}},
        "css": ".card { font-size: 20px; }",
    }
    monkeypatch.setattr(backup, "anki", fake)
    monkeypatch.setattr(backup, "deck_config",
                        lambda command: (f"Japanese::{command}", "Vocabulary"
                                         if command == "vocab" else command.title()))
    monkeypatch.setattr(backup, "DECK_COMMANDS", ("vocab",))

    class _Status:
        connected = True
        profile = "Test"
        notetypes = frozenset({"Vocabulary"})

    monkeypatch.setattr("kotogen.anki.connect.status", lambda **kw: _Status())
    monkeypatch.setenv("KOTOGEN_BACKUP_DIR", str(tmp_path / "backups"))
    return fake


def _snap(reason: str = "manual") -> dict:
    return backup.snapshot(["vocab"], reason=reason)


# -- The snapshot --------------------------------------------------------------

def test_a_snapshot_holds_fields_tags_scheduling_and_templates(anki):
    """The four things no other layer knows how to put back."""
    snap = _snap()
    state = snap["notetypes"]["Vocabulary"]
    note = state["notes"][0]

    assert note["fields"]["Expression"] == "食[た]べる"
    assert state["notes"][1]["tags"] == ["Verb::一段動詞"]
    assert note["cards"]["10"]["ivl"] == 90
    assert state["templates"]["css"] == ".card { font-size: 20px; }"
    assert state["deck"] == "Japanese::vocab"  # where to recreate a deleted note


def test_an_old_ankiconnect_still_maps_cards_to_their_note(anki, monkeypatch):
    """Without `cards` in notesInfo, the attachment comes from the cards' answer.

    The fallback must neither lose the scheduling nor count it twice for notes
    that do carry their list.
    """
    for note in anki.notes["Vocabulary"]:
        note_cards = note.pop("cards")
        note["_cards"] = note_cards  # kept for do_findCards/do_cardsInfo

    monkeypatch.setattr(anki, "do_findCards",
                        lambda query: [c for n in anki.notes["Vocabulary"]
                                       for c in n["_cards"]])
    monkeypatch.setattr(anki, "do_cardsInfo", lambda cards: [
        {"cardId": cid, "note": n["noteId"], **n["schedule"][cid]}
        for n in anki.notes["Vocabulary"] for cid in n["_cards"] if cid in cards])

    note = _snap()["notetypes"]["Vocabulary"]["notes"][0]
    assert list(note["cards"]) == ["10"]
    assert note["cards"]["10"]["ivl"] == 90


def test_a_notetype_absent_from_the_profile_is_skipped(anki, monkeypatch):
    """A type the profile lacks has nothing to back up: not a failure."""
    monkeypatch.setattr(backup, "DECK_COMMANDS", ("vocab", "grammar"))
    snap = backup.snapshot(["vocab", "grammar"])
    assert list(snap["notetypes"]) == ["Vocabulary"]


def test_no_anki_no_snapshot(anki, monkeypatch):
    """Claiming to have backed up while having read nothing is the worst case."""
    class _Closed:
        connected = False
        profile = ""
        notetypes = frozenset()

    monkeypatch.setattr("kotogen.anki.connect.status", lambda **kw: _Closed())
    with pytest.raises(ConnectionError):
        _snap()


# -- Writing and retention -----------------------------------------------------

def test_an_unchanged_deck_writes_nothing(anki):
    """Identical copies would push the useful ones out of retention."""
    assert backup.save(_snap()) is not None
    assert backup.save(_snap()) is None
    assert len(backup.snapshots()) == 1


def test_a_changed_deck_writes_again(anki):
    backup.save(_snap(), stamp="2026-08-17_100000")
    anki.notes["Vocabulary"][0]["fields"]["Translation"] = {"value": "Consommer"}
    assert backup.save(_snap(), stamp="2026-08-17_110000") is not None
    assert len(backup.snapshots()) == 2


def test_the_name_carries_the_stamp_and_the_reason(anki):
    path = backup.save(_snap("maintain"), stamp="2026-08-17_143012")
    assert path.name == "2026-08-17_143012-maintain.json"
    assert backup.parse_name(path) == ("2026-08-17_143012", "maintain")


def test_retention_keeps_the_recent_ones_then_one_per_day(anki):
    """A mistake is noticed within hours; older history needs one per day."""
    paths = [f"2026-06-{day:02d}_{hour:02d}0000-manual.json"
             for day in (1, 2, 3) for hour in (10, 11, 12, 13)]
    directory = backup.backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for name in paths:
        (directory / name).write_text("{}", encoding="utf-8")

    doomed = backup._prunable(backup.snapshots(), keep_recent=4, keep_days=90)
    kept = sorted(p.name for p in backup.snapshots() if p not in doomed)
    # The 4 most recent ones whole (3 June), then one per day only.
    assert kept == ["2026-06-01_130000-manual.json",
                    "2026-06-02_130000-manual.json",
                    "2026-06-03_100000-manual.json",
                    "2026-06-03_110000-manual.json",
                    "2026-06-03_120000-manual.json",
                    "2026-06-03_130000-manual.json"]


def test_retention_forgets_beyond_the_quarter(anki):
    directory = backup.backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    old = directory / "2020-01-01_120000-manual.json"
    old.write_text("{}", encoding="utf-8")
    import os
    ancient = time.time() - 200 * 86400
    os.utime(old, (ancient, ancient))
    assert old in backup._prunable(backup.snapshots(), keep_recent=0, keep_days=90)


def test_a_write_a_ctrl_c_cut_short_leaves_no_temporary_behind(anki):
    """The snapshot is written from a daemon thread the exit does not wait for:
    its temporary is cleared at the next save, unless it may be a write under way."""
    import os

    directory = backup.backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stale = directory / "2026-06-01_100000-maintain.json.0badc0de.tmp"
    fresh = directory / "2026-06-01_110000-maintain.json.feedf00d.tmp"
    for path in (stale, fresh):
        path.write_text('{"half', encoding="utf-8")
    hour_ago = time.time() - 3600
    os.utime(stale, (hour_ago, hour_ago))
    backup.save(_snap("maintain"), stamp="2026-08-17_143012")
    assert not stale.exists() and fresh.exists()


def test_what_a_restore_did_is_listed_the_way_the_language_lists(anki, monkeypatch,
                                                                 capsys):
    """Japanese runs a list on 「、」, and its counter goes with its noun: each
    count is a whole phrase of the table."""
    from kotogen import i18n

    monkeypatch.setattr(i18n, "_language", "ja")
    monkeypatch.setattr(i18n, "_catalogue", {
        "#list_separator": "、", "{count} notes put back": "もどしたノート {count} 件",
        "{count} notes retagged": "タグを付け直したノート {count} 件",
        "Restored: {what}.": "もとにもどしました：{what}。"})
    backup._print_restored(backup.Restored(fields=3, tags=2))
    assert "もとにもどしました：もどしたノート 3 件、タグを付け直したノート 2 件。" in (
        capsys.readouterr().out)


def test_an_archive_set_is_kept_or_dropped_whole(anki):
    """An archiving is one .apkg per deck under the same timestamp.

    Counted file by file, the newest archiving would be cut in two, and
    `kotogen backup --full` would erase part of what it had just written.
    """
    directory = backup.backup_dir()
    directory.mkdir(parents=True, exist_ok=True)
    for stamp in ("2026-08-15_120000", "2026-08-16_120000", "2026-08-17_120000"):
        for command in ("vocab", "grammar", "audio", "reading"):
            (directory / f"{stamp}-{command}.apkg").write_text("x", encoding="utf-8")

    doomed = backup._prunable_packages(backup.packages(), keep=2)
    survivors = {backup.parse_name(p)[0] for p in backup.packages() if p not in doomed}
    assert survivors == {"2026-08-16_120000", "2026-08-17_120000"}
    # The two archivings kept are whole, four packages each.
    assert len([p for p in backup.packages() if p not in doomed]) == 8


def test_a_snapshot_from_the_future_is_refused_not_misread(anki):
    path = backup.backup_dir()
    path.mkdir(parents=True, exist_ok=True)
    written = path / "2099-01-01_120000-manual.json"
    written.write_text(json.dumps({"version": 99, "notetypes": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="more recent version"):
        backup.load(written)


# -- Designating a backup ------------------------------------------------------

def test_a_day_designates_the_only_snapshot_of_that_day(anki):
    backup.save(_snap(), stamp="2026-08-17_143012")
    assert backup.parse_name(backup.find("2026-08-17"))[0] == "2026-08-17_143012"


def test_an_ambiguous_stamp_is_refused_rather_than_guessed(anki):
    backup.save(_snap(), stamp="2026-08-17_100000")
    anki.notes["Vocabulary"][0]["tags"] = ["marker"]
    backup.save(_snap(), stamp="2026-08-17_180000")
    with pytest.raises(ValueError, match="designates 2 backups"):
        backup.find("2026-08-17")


# -- Comparison ----------------------------------------------------------------

def test_diff_sees_a_rewritten_field(anki):
    snap = _snap()
    anki.notes["Vocabulary"][0]["fields"]["Translation"] = {"value": "Consommer"}
    change = backup.diff(snap, _snap()).changed[0]
    assert change.fields["Translation"] == ("Manger", "Consommer")


def test_diff_sees_a_reset_leech(anki):
    """Lost progress, which no diff of fields would show."""
    snap = _snap()
    anki.notes["Vocabulary"][0]["schedule"][10] = dict(NEW_CARD)
    change = backup.diff(snap, _snap()).changed[0]
    assert change.cards[10][0]["ivl"] == 90 and change.cards[10][1]["ivl"] == 0


def test_diff_separates_what_was_deleted_from_what_was_added(anki):
    snap = _snap()
    anki.do_deleteNotes(notes=[1])
    anki.notes["Vocabulary"].append(_note(3, "見[み]る", "Voir"))
    changes = backup.diff(snap, _snap())
    assert [n["id"] for _t, n in changes.deleted] == [1]
    assert [n["id"] for _t, n in changes.created] == [3]


def test_diff_sees_a_rewritten_template(anki):
    snap = _snap()
    anki.templates["Vocabulary"]["css"] = ".card { font-size: 30px; }"
    assert backup.diff(snap, _snap()).templates == ["Vocabulary"]


def test_an_untouched_deck_diffs_to_nothing(anki):
    assert not backup.diff(_snap(), _snap())


# -- Restoration ---------------------------------------------------------------

def _restore(snap: dict) -> backup.Restored:
    return backup.restore(snap, backup.diff(snap, _snap()))


def test_restoring_puts_the_fields_back(anki):
    snap = _snap()
    anki.notes["Vocabulary"][0]["fields"]["Translation"] = {"value": "Consommer"}
    _restore(snap)
    assert anki.notes["Vocabulary"][0]["fields"]["Translation"]["value"] == "Manger"


def test_restoring_puts_the_tags_back_both_ways(anki):
    snap = _snap()
    anki.notes["Vocabulary"][0]["tags"] = ["Category::ToReview"]   # laid on since
    anki.notes["Vocabulary"][1]["tags"] = []                        # removed since
    _restore(snap)
    assert anki.notes["Vocabulary"][0]["tags"] == []
    assert anki.notes["Vocabulary"][1]["tags"] == ["Verb::一段動詞"]


def test_restoring_puts_the_progress_back(anki):
    """A leech that was reset gets its three months of interval back."""
    snap = _snap()
    anki.notes["Vocabulary"][0]["schedule"][10] = dict(NEW_CARD)
    out = _restore(snap)
    assert anki.notes["Vocabulary"][0]["schedule"][10]["ivl"] == 90
    assert anki.notes["Vocabulary"][0]["schedule"][10]["reps"] == 12
    assert out.cards == 1


def test_restoring_brings_a_deleted_note_back_with_its_progress(anki):
    snap = _snap()
    anki.do_deleteNotes(notes=[1])
    out = _restore(snap)

    returned = [n for n in anki.notes["Vocabulary"]
                if n["fields"]["Expression"]["value"] == "食[た]べる"]
    assert out.recreated == 1 and len(returned) == 1
    # A new identifier (Anki recycles none), but the interval is found again.
    assert returned[0]["noteId"] != 1
    assert list(returned[0]["schedule"].values())[0]["ivl"] == 90


def test_restoring_never_deletes_what_came_after(anki):
    """The property that makes the command safe to launch, even by mistake."""
    snap = _snap()
    anki.notes["Vocabulary"].append(_note(3, "見[み]る", "Voir"))
    _restore(snap)
    assert [n["noteId"] for n in anki.notes["Vocabulary"]] == [1, 2, 3]
    assert not [action for action, _ in anki.calls if action == "deleteNotes"]


def test_restoring_puts_the_templates_back(anki):
    snap = _snap()
    anki.templates["Vocabulary"]["css"] = "overwritten by deck install"
    anki.templates["Vocabulary"]["cards"] = {"Recognition": {"Front": "broken", "Back": ""}}
    out = _restore(snap)
    assert anki.templates["Vocabulary"]["css"] == ".card { font-size: 20px; }"
    assert anki.templates["Vocabulary"]["cards"]["Recognition"]["Front"] == "{{Expression}}"
    assert out.templates == 1


def test_restoring_an_untouched_deck_writes_nothing(anki):
    snap = _snap()
    out = _restore(snap)
    assert (out.fields, out.tags, out.cards, out.recreated) == (0, 0, 0, 0)
    written = {"updateNoteFields", "addTags", "removeTags", "addNote"}
    assert not [action for action, _ in anki.calls if action in written]


def test_a_note_that_resists_does_not_stop_the_others(anki, monkeypatch):
    """A locked note must not stop the restoration of the next ones."""
    snap = _snap()
    for note in anki.notes["Vocabulary"]:
        note["fields"]["Translation"] = {"value": "overwritten"}

    original = anki.do_updateNoteFields

    def refuse(note):
        if note["id"] == 1:
            raise RuntimeError("note locked")
        return original(note)

    monkeypatch.setattr(anki, "do_updateNoteFields", refuse)
    out = _restore(snap)
    assert out.fields == 1 and len(out.failures) == 1
    assert anki.notes["Vocabulary"][1]["fields"]["Translation"]["value"] == "Boire"


def test_a_restore_can_itself_be_undone(anki):
    """What the restore overwrites is a snapshot of its own, the latest: restoring
    that one puts back the state the restore replaced."""
    stamp = backup.parse_name(backup.save(_snap(), stamp="2026-08-17_100000"))[0]
    anki.notes["Vocabulary"][0]["fields"]["Translation"] = {"value": "Dévorer"}

    backup._run_restore(stamp, assume_yes=True)
    assert anki.notes["Vocabulary"][0]["fields"]["Translation"]["value"] == "Manger"
    newest = backup.latest()
    assert backup.parse_name(newest)[1] == "restore"
    saved = backup.load(newest)["notetypes"]["Vocabulary"]["notes"][0]
    assert saved["fields"]["Translation"] == "Dévorer"

    backup._run_restore(backup.parse_name(newest)[0], assume_yes=True)
    assert anki.notes["Vocabulary"][0]["fields"]["Translation"]["value"] == "Dévorer"


def test_a_restore_takes_its_snapshot_with_the_automatic_backup_off(anki, monkeypatch,
                                                                    capsys):
    """`KOTOGEN_BACKUP=0` turns off the backups taken for the user; the one a
    restore takes is how the restore is undone."""
    stamp = backup.parse_name(backup.save(_snap(), stamp="2026-08-17_100000"))[0]
    anki.notes["Vocabulary"][0]["fields"]["Translation"] = {"value": "Edited since"}
    monkeypatch.setenv("KOTOGEN_BACKUP", "0")
    backup._run_restore(stamp, assume_yes=True)
    assert anki.notes["Vocabulary"][0]["fields"]["Translation"]["value"] == "Manger"
    assert backup.parse_name(backup.latest())[1] == "restore"
    # The colon carries its own space, as the language spaces it.
    assert "      Translation: Manger  →  Edited since" in capsys.readouterr().out


def test_a_restore_whose_snapshot_fails_restores_nothing(anki, monkeypatch):
    stamp = backup.parse_name(backup.save(_snap(), stamp="2026-08-17_100000"))[0]
    anki.notes["Vocabulary"][0]["fields"]["Translation"] = {"value": "Edited since"}

    def full(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(backup, "save", full)
    with pytest.raises(SystemExit) as stop:
        backup._run_restore(stamp, assume_yes=True)
    assert "Nothing was restored" in str(stop.value.code)
    assert anki.notes["Vocabulary"][0]["fields"]["Translation"]["value"] == "Edited since"


def test_a_snapshot_of_another_profile_is_not_restored(anki, monkeypatch):
    """Note ids belong to one collection: in another profile every note would pass
    for deleted and be recreated."""
    stamp = backup.parse_name(backup.save(_snap()))[0]

    class _Other:
        connected = True
        profile = "Second"
        notetypes = frozenset({"Vocabulary"})

    monkeypatch.setattr("kotogen.anki.connect.status", lambda **kw: _Other())
    with pytest.raises(ValueError) as refused:
        backup._run_restore(stamp, assume_yes=True)
    assert '"Test"' in str(refused.value) and '"Second"' in str(refused.value)
    assert not [action for action, _params in anki.calls
                if action in ("updateNoteFields", "addNote", "addTags", "removeTags")]
    assert len(backup.snapshots()) == 1


def test_an_interrupted_save_leaves_the_latest_snapshot_whole(anki, monkeypatch):
    """`before` writes from a thread a Ctrl+C does not wait for: the file is
    either all there or not there."""
    import os

    first = backup.save(_snap(), stamp="2026-08-17_100000")
    anki.notes["Vocabulary"][0]["fields"]["Translation"] = {"value": "Dévorer"}
    replace = os.replace

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(KeyboardInterrupt):
        backup.save(_snap(), stamp="2026-08-17_110000")
    monkeypatch.setattr(os, "replace", replace)
    assert backup.latest() == first
    assert backup.load(first)["notetypes"]["Vocabulary"]["notes"]
    assert list(first.parent.iterdir()) == [first]


# -- Automatic backup ----------------------------------------------------------

def test_the_automatic_snapshot_names_its_reason(anki):
    path = backup.before("maintain")
    assert backup.parse_name(path)[1] == "maintain"


def test_the_automatic_snapshot_says_in_one_line_what_it_holds(anki, capsys):
    """The timestamp at the head - it is what gets copied out after `--restore` -
    then what is in it, in brackets and on the same line."""
    path = backup.before("maintain")
    out = capsys.readouterr().out.strip()
    assert out == f"Backup {backup.parse_name(path)[0]} (2 notes, Vocabulary)"


def test_the_automatic_snapshot_can_be_switched_off(anki, monkeypatch):
    monkeypatch.setenv("KOTOGEN_BACKUP", "0")
    assert backup.before("maintain") is None
    assert backup.snapshots() == []


def test_a_failed_backup_warns_but_never_blocks_the_command(anki, monkeypatch, capsys):
    """The command was asked for: a full disk is no reason to refuse it."""
    def explode(*a, **kw):
        raise ConnectionError("Anki closed in the meantime")

    monkeypatch.setattr(backup, "snapshot", explode)
    assert backup.before("maintain") is None
    # One line: the reason, nothing else.
    out = capsys.readouterr().out.strip()
    assert out == "!! Backup impossible (Anki closed in the meantime)"


def test_an_explicit_target_beats_a_stored_preference(anki, monkeypatch):
    """`--only grammar` must back the grammar up, KOTOGEN_SKIP or not."""
    monkeypatch.setattr(backup, "DECK_COMMANDS", ("vocab", "grammar"))
    monkeypatch.setenv("KOTOGEN_SKIP", "grammar")
    assert backup.targets(None) == ["vocab"]
    assert backup.targets(["grammar"]) == ["grammar"]


def test_an_only_that_names_nothing_lists_every_deck(monkeypatch):
    """The decks the message offers are the ones `--only` takes, kanji included."""
    import argparse

    args = argparse.Namespace(list=False, diff=None, restore=None, yes=False,
                              only=["nothing"])
    with pytest.raises(SystemExit) as raised:
        backup.run_backup(args)
    for command in backup.DECK_COMMANDS:
        assert command in str(raised.value)
