"""Backing up the Japanese decks: a net under the commands that write.

Anki's own backups restore the whole collection, as it was when the profile last
closed. Here a snapshot is taken just before `maintain`, `ask` or `deck install`
writes (generation only adds): the fields, tags, scheduling and templates of the
note types, in a JSON file that `diff` compares and `restore` puts back note by
note, never deleting a note created since.

The `.apkg` archive (`export_packages`), media included, is made on request for
a lost deck and restored by hand: reimported, Anki only updates a note whose
imported copy is the more recent, which a backup never is.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from kotogen import console, settings, system
from kotogen.anki.connect import request as anki
from kotogen.cli import DECK_COMMANDS, deck_config, skipped_commands
from kotogen.i18n import _, convention, counted, listed, quoted as _quoted

# Format version: a snapshot from a later version is refused rather than misread.
SNAPSHOT_VERSION = 1

# The scheduling kept of a card: what `setSpecificValueOfCard` can put back, and
# what `forgetCards` (the reset of a leech) overwrites.
SCHEDULE_KEYS = ("type", "queue", "due", "ivl", "factor", "reps", "lapses")

# `cardsInfo` also returns each card's rendered faces, tens of megabytes on a
# large deck: it is asked in batches.
_CARDS_CHUNK = 250

# Retention: one snapshot per `maintain` (about 5 MB for 10,000 notes) adds up, so the
# most recent are kept whole, then one a day, and none past the quarter.
KEEP_RECENT = 10
KEEP_DAYS = 90

# The `.apkg` archives carry the media, hundreds of megabytes: the last two
# archivings are kept, in case the last will not read back.
KEEP_FULL = 2


# -- Location -----------------------------------------------------------------

def backup_dir() -> Path:
    """Backup folder: `KOTOGEN_BACKUP_DIR` if it is set, otherwise the data
    folder of the platform (never the cache, see `system`)."""
    return settings.folder("KOTOGEN_BACKUP_DIR") or system.data_dir() / "backups"


def enabled() -> bool:
    """False if `KOTOGEN_BACKUP=0` cuts the automatic backup off.

    `kotogen backup` run by hand ignores it.
    """
    return settings.flag("KOTOGEN_BACKUP")


def targets(only: list[str] | None = None) -> list[str]:
    """Commands to back up: the Japanese decks, filtered by `--only`.

    Without `--only`, the commands in `KOTOGEN_SKIP` drop out, their note type
    being absent from the profile; `--only` brings them back, as in `deck install`.
    """
    wanted = [name.strip().lower() for name in (only or []) if name.strip()]
    if wanted:
        return [command for command in DECK_COMMANDS if command in wanted]
    skipped = skipped_commands()
    return [command for command in DECK_COMMANDS if command not in skipped]


# -- Reading the state of Anki -------------------------------------------------

def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _schedule(cards: list[int]) -> tuple[dict[int, dict], dict[int, list[int]]]:
    """Scheduling of the given cards, and which note each one belongs to.

    A key Anki does not return is left out rather than zeroed, so that a
    restoration never writes a `lapses = 0` it was not given.
    """
    out: dict[int, dict] = {}
    by_note: dict[int, list[int]] = {}
    for batch in _chunks(cards, _CARDS_CHUNK):
        for card in anki("cardsInfo", cards=batch) or []:
            out[card["cardId"]] = {k: card[k] for k in SCHEDULE_KEYS if k in card}
            by_note.setdefault(card["note"], []).append(card["cardId"])
    return out, by_note


def _notetype_state(notetype: str, deck: str) -> dict:
    """All that is backed up of a note type: its notes and its templates.

    Queried by note type rather than deck, so that a card moved by hand to another
    deck stays covered; the deck is kept to know where to recreate a deleted note.
    """
    note_ids = anki("findNotes", query=f'"note:{notetype}"') or []
    notes = anki("notesInfo", notes=note_ids) if note_ids else []

    # Only recent versions of the addon give `cards` in `notesInfo`; otherwise
    # the cards are found by note type, and `cardsInfo` names their notes.
    from_notes = {note["noteId"]: list(note.get("cards") or []) for note in notes}
    card_ids = [cid for cards in from_notes.values() for cid in cards]
    if not card_ids and note_ids:
        card_ids = anki("findCards", query=f'"note:{notetype}"') or []
    schedule, from_cards = _schedule(card_ids)
    by_note = from_notes if card_ids and all(from_notes.values()) else from_cards

    return {
        "deck": deck,
        "templates": _templates(notetype),
        "notes": [
            {
                "id": note["noteId"],
                # The GUID identifies a note across collections: unused here, kept
                # for a snapshot read elsewhere.
                "guid": note.get("guid", ""),
                "fields": {name: value.get("value", "")
                           for name, value in (note.get("fields") or {}).items()},
                "tags": sorted(note.get("tags") or []),
                "cards": {str(cid): schedule[cid]
                          for cid in by_note.get(note["noteId"], []) if cid in schedule},
            }
            for note in notes
        ],
    }


def _templates(notetype: str) -> dict:
    """Templates of a note type: its fields, its cards, its CSS.

    What `deck install` rewrites, which a snapshot of notes alone would not cover.
    """
    return {
        "fields": anki("modelFieldNames", modelName=notetype) or [],
        "cards": anki("modelTemplates", modelName=notetype) or {},
        "css": (anki("modelStyling", modelName=notetype) or {}).get("css", ""),
    }


def snapshot(commands: list[str], *, reason: str = "manual") -> dict:
    """Snapshot of the note types asked for, ready to be written on disk.

    Raises ConnectionError if Anki is closed. A note type absent from the profile
    is skipped: it has no notes to lose.
    """
    from kotogen.anki.connect import UNREACHABLE, status as anki_status

    state = anki_status(refresh=True)
    if not state.connected:
        raise ConnectionError(_(UNREACHABLE))

    notetypes: dict[str, dict] = {}
    for command in commands:
        deck, notetype = deck_config(command)
        if notetype not in state.notetypes:
            continue
        notetypes[notetype] = _notetype_state(notetype, deck)
    return {
        "version": SNAPSHOT_VERSION,
        "created": time.time(),
        "reason": reason,
        "profile": state.profile,
        "notetypes": notetypes,
    }


def note_count(snap: dict) -> int:
    return sum(len(state["notes"]) for state in snap["notetypes"].values())


# -- Writing, reading back, tidying up ------------------------------------------

def fingerprint(snap: dict) -> str:
    """Fingerprint of the CONTENT of a snapshot, its date and its reason excluded.

    So that a snapshot identical to the last one is not written again.
    """
    payload = json.dumps(snap["notetypes"], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def stamp_now() -> str:
    """Sortable timestamp, in local time: `2026-08-17_143012`.

    No `:`, which Windows refuses in a file name; easy to type after `--restore`.
    """
    return time.strftime("%Y-%m-%d_%H%M%S")


def parse_name(path: Path) -> tuple[str, str]:
    """(timestamp, reason) of a backup file name."""
    stamp, _sep, reason = path.stem.rpartition("-")
    return (stamp, reason) if stamp else (path.stem, "")


def snapshots() -> list[Path]:
    """Snapshots present, from the most recent to the oldest."""
    try:
        found = list(backup_dir().glob("*.json"))
    except OSError:
        return []
    return sorted(found, key=lambda p: p.name, reverse=True)


def packages() -> list[Path]:
    """`.apkg` archives present, from the most recent to the oldest."""
    try:
        found = list(backup_dir().glob("*.apkg"))
    except OSError:
        return []
    return sorted(found, key=lambda p: p.name, reverse=True)


def latest() -> Path | None:
    found = snapshots()
    return found[0] if found else None


def load(path: Path) -> dict:
    """Reads a snapshot back. Raises ValueError if it is unreadable or too recent."""
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(_("unreadable backup ({name}): {error}")
                         .format(name=path.name, error=exc)) from exc
    if not isinstance(snap, dict) or "notetypes" not in snap:
        raise ValueError(_("unreadable backup ({name}): unexpected format")
                         .format(name=path.name))
    if int(snap.get("version", 0)) > SNAPSHOT_VERSION:
        raise ValueError(_(
            "{name} was written by a more recent version of kotogen "
            "(format {found}, known up to {known})."
        ).format(name=path.name, found=snap["version"], known=SNAPSHOT_VERSION))
    return snap


# What designates the most recent snapshot: `latest`, which `--diff` and
# `--restore` pass when given no stamp, and an empty stamp.
_LATEST_NAMES = ("", "latest")


def find(stamp: str) -> Path:
    """Snapshot designated by a timestamp, possibly abbreviated.

    `2026-08-17` designates the one of that day if it is alone; several matches
    raise rather than pick one.
    """
    found = snapshots()
    if not found:
        raise ValueError(_("no backup in {folder}.").format(folder=backup_dir()))
    if stamp in _LATEST_NAMES:
        return found[0]
    matches = [path for path in found if parse_name(path)[0].startswith(stamp)]
    if not matches:
        raise ValueError(_("no backup starts with {stamp}.")
                         .format(stamp=_quoted(stamp)))
    if len(matches) > 1:
        listing = listed(parse_name(path)[0] for path in matches)
        raise ValueError(_("{stamp} designates {count} backups: {listing}.")
                         .format(stamp=_quoted(stamp), count=len(matches),
                                 listing=listing))
    return matches[0]


def _prunable(paths: list[Path], keep_recent: int, keep_days: int) -> list[Path]:
    """Files to erase: beyond the N most recent, one per day only.

    The most recent are all kept, to go back past two runs in a row; anything
    older than `keep_days` goes.
    """
    now = time.time()
    doomed: list[Path] = []
    seen_days: set[str] = set()
    for index, path in enumerate(paths):
        stamp, _reason = parse_name(path)
        day = stamp[:10]
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age > keep_days * 86400:
            doomed.append(path)
        elif index >= keep_recent and day in seen_days:
            doomed.append(path)
        seen_days.add(day)
    return doomed


def _prunable_packages(paths: list[Path], keep: int) -> list[Path]:
    """Archives to erase: every file of the archivings past the Nth.

    An archiving is one `.apkg` per deck under one timestamp, kept or erased
    whole: counted by files, the last one would lose some of its own.
    """
    stamps: list[str] = []
    for path in paths:
        stamp = parse_name(path)[0]
        if stamp not in stamps:
            stamps.append(stamp)
    doomed = set(stamps[keep:])
    return [path for path in paths if parse_name(path)[0] in doomed]


# A snapshot is written from a daemon thread (`take`): stopped at the exit by a
# Ctrl+C, it leaves its temporary of `system.write_whole` behind. One older than
# this is no write in progress, a run's or another command's.
_LEFTOVER_AGE = 600


def _leftovers() -> list[Path]:
    """The temporaries of snapshot writes nobody finished."""
    try:
        found = list(backup_dir().glob("*.json.*.tmp"))
    except OSError:
        return []
    now = time.time()
    stale = []
    for path in found:
        try:
            if now - path.stat().st_mtime > _LEFTOVER_AGE:
                stale.append(path)
        except OSError:
            continue
    return stale


def prune() -> list[Path]:
    """Applies the retention, and clears what an interrupted write left.

    Gives back the list of what has been erased.
    """
    doomed = (_prunable(snapshots(), KEEP_RECENT, KEEP_DAYS)
              + _prunable_packages(packages(), KEEP_FULL) + _leftovers())
    removed = []
    for path in doomed:
        try:
            path.unlink()
        except OSError:
            continue  # file open elsewhere, read-only folder: never mind
        removed.append(path)
    return removed


def save(snap: dict, *, stamp: str | None = None) -> Path | None:
    """Writes a snapshot, unless it is identical to the last one.

    Gives back the path written, or None when nothing has changed: identical
    copies would push older, different ones out of the retention.
    """
    previous = latest()
    if previous is not None:
        try:
            if fingerprint(load(previous)) == fingerprint(snap):
                return None
        except ValueError:
            pass  # previous backup unreadable: we write the new one

    stamp = stamp or stamp_now()
    reason = str(snap.get("reason") or "manual").replace("-", "_")
    path = backup_dir() / f"{stamp}-{reason}.json"
    # Whole or not at all: `before` writes from a thread a Ctrl+C does not wait
    # for, and a truncated file would stand as the latest snapshot.
    system.write_whole(path, json.dumps(snap, ensure_ascii=False))
    prune()
    return path


# -- Complete archive (.apkg) ---------------------------------------------------

# Zipping thousands of MP3s takes well past the client's default minute; the
# timeout only lets a stuck Anki hand control back.
_EXPORT_TIMEOUT = 1800


def export_packages(commands: list[str], *, stamp: str | None = None) -> list[Path]:
    """Exports one `.apkg` per deck, scheduling and media included.

    By deck, as `exportPackage` only exports decks: a card moved by hand to another
    deck is missing, unlike in the snapshot. A deck that fails does not stop the
    others.
    """
    stamp = stamp or stamp_now()
    directory = backup_dir()
    directory.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    colon = convention("colon", ": ")
    for command in commands:
        deck, _notetype = deck_config(command)
        path = directory / f"{stamp}-{command}.apkg"
        try:
            # AnkiConnect writes the file itself, hence the absolute path; a
            # missing deck gives False rather than an error.
            done = anki("exportPackage", timeout=_EXPORT_TIMEOUT,
                        deck=deck, path=str(path.resolve()), includeSched=True)
        except ConnectionError as exc:
            # Anki closed mid-export: every following deck would fail the same way.
            print(f"   !! {console.reason(exc, console.ALONE)}")
            break
        except RuntimeError as exc:
            print(f"   !! {deck}{colon}{console.reason(exc, console.ALONE)}")
            continue
        if done:
            written.append(path)
        else:
            print(f"   !! {deck}{colon}" + _("export refused (does the deck exist?)"))
    prune()
    return written


# -- Comparison ----------------------------------------------------------------

@dataclass
class NoteChange:
    """A note the snapshot and Anki do not say the same thing about."""

    notetype: str
    note_id: int
    label: str
    fields: dict[str, tuple[str, str]] = field(default_factory=dict)  # name: (before, after)
    added_tags: list[str] = field(default_factory=list)     # tags appeared since
    removed_tags: list[str] = field(default_factory=list)   # tags gone since
    cards: dict[int, tuple[dict, dict]] = field(default_factory=dict)  # cardId: (before, after)

    def __bool__(self) -> bool:
        return bool(self.fields or self.added_tags or self.removed_tags or self.cards)


@dataclass
class Diff:
    """What has moved between a snapshot and the current state of the deck."""

    changed: list[NoteChange] = field(default_factory=list)
    deleted: list[tuple[str, dict]] = field(default_factory=list)  # (note type, note)
    created: list[tuple[str, dict]] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # note types gone from the profile

    def __bool__(self) -> bool:
        return bool(self.changed or self.deleted or self.created
                    or self.templates or self.missing)

    @property
    def total(self) -> int:
        return len(self.changed) + len(self.deleted) + len(self.created)


def _label(note: dict) -> str:
    """Which card is being talked about: the value of the first field, truncated.

    In every note type of the repository the first field (`Expression`,
    `Sentence`...) is the one that identifies the card.
    """
    from kotogen.exporter import short

    for value in (note.get("fields") or {}).values():
        if value:
            return short(value, 40)
    return _("note {id}").format(id=note.get('id') or note.get('noteId'))


def _compare_notes(notetype: str, before: dict, after: dict) -> NoteChange:
    change = NoteChange(notetype, before["id"], _label(before))
    for name, old in (before.get("fields") or {}).items():
        new = (after.get("fields") or {}).get(name, "")
        if new != old:
            change.fields[name] = (old, new)
    old_tags, new_tags = set(before.get("tags") or []), set(after.get("tags") or [])
    change.added_tags = sorted(new_tags - old_tags)
    change.removed_tags = sorted(old_tags - new_tags)
    for cid, old_sched in (before.get("cards") or {}).items():
        new_sched = (after.get("cards") or {}).get(cid)
        if new_sched is not None and new_sched != old_sched:
            change.cards[int(cid)] = (old_sched, new_sched)
    return change


def diff(snap: dict, current: dict) -> Diff:
    """Compares a snapshot to another one (in practice: to the state of the moment).

    Notes are matched by `noteId`, stable within a collection.
    """
    out = Diff()
    for notetype, before in snap["notetypes"].items():
        after = current["notetypes"].get(notetype)
        if after is None:
            out.missing.append(notetype)
            continue
        if before.get("templates") and after.get("templates") \
                and before["templates"] != after["templates"]:
            out.templates.append(notetype)

        now_by_id = {note["id"]: note for note in after["notes"]}
        for note in before["notes"]:
            twin = now_by_id.pop(note["id"], None)
            if twin is None:
                out.deleted.append((notetype, note))
                continue
            change = _compare_notes(notetype, note, twin)
            if change:
                out.changed.append(change)
        out.created += [(notetype, note) for note in now_by_id.values()]
    return out


# -- Restoration ----------------------------------------------------------------

@dataclass
class Restored:
    """Report of a restoration: what has been put back, what resisted."""

    fields: int = 0
    tags: int = 0
    cards: int = 0
    recreated: int = 0
    templates: int = 0
    failures: list[str] = field(default_factory=list)


def _restore_schedule(card_id: int, values: dict) -> None:
    """Puts the scheduling of a card back (interval, ease, repetitions...).

    The only undo for the reset of a real leech. `setSpecificValueOfCard`
    demands that the danger be acknowledged (`warning_check`).
    """
    keys = [k for k in SCHEDULE_KEYS if k in values]
    if not keys:
        return
    result = anki(
        "setSpecificValueOfCard",
        card=card_id,
        keys=keys,
        newValues=[values[k] for k in keys],
        warning_check=True,
    )
    for entry in result if isinstance(result, list) else []:
        if isinstance(entry, (list, tuple)) and not entry[0]:
            raise RuntimeError(str(entry[1]))


def _recreate(notetype: str, deck: str, note: dict) -> int:
    """Recreates a deleted note, its scheduling with it if that still fits.

    The note gets a new id. `allowDuplicate`, or a twin still in the deck would
    block it. The scheduling is laid back only when the card count matches: a
    note type changed since would put an interval on the wrong card.
    """
    note_id = anki("addNote", note={
        "deckName": deck,
        "modelName": notetype,
        "fields": note.get("fields") or {},
        "tags": note.get("tags") or [],
        "options": {"allowDuplicate": True},
    })
    saved = note.get("cards") or {}
    info = anki("notesInfo", notes=[note_id]) or []
    fresh = list((info[0].get("cards") if info else None) or [])
    if len(fresh) == len(saved):
        for card_id, values in zip(fresh, saved.values()):
            _restore_schedule(card_id, values)
    return note_id


def restore(snap: dict, changes: Diff, *, deck_of: dict[str, str] | None = None) -> Restored:
    """Puts the snapshot back. Never deletes anything.

    `changes` comes from `diff(snap, current state)`, so only what moved is
    touched; the notes created since (`changes.created`) are left in place.
    """
    deck_of = deck_of or {name: state.get("deck", "")
                          for name, state in snap["notetypes"].items()}
    out = Restored()

    for change in changes.changed:
        try:
            if change.fields:
                anki("updateNoteFields", note={
                    "id": change.note_id,
                    "fields": {name: old for name, (old, _new) in change.fields.items()},
                })
                out.fields += 1
            if change.added_tags:
                anki("removeTags", notes=[change.note_id], tags=" ".join(change.added_tags))
            if change.removed_tags:
                anki("addTags", notes=[change.note_id], tags=" ".join(change.removed_tags))
            if change.added_tags or change.removed_tags:
                out.tags += 1
            for card_id, (old, _new) in change.cards.items():
                _restore_schedule(card_id, old)
                out.cards += 1
        except (ConnectionError, RuntimeError) as exc:
            out.failures.append(f"{change.label}{convention('colon', ': ')}"
                                f"{console.reason(exc, console.ALONE)}")

    for notetype, note in changes.deleted:
        try:
            _recreate(notetype, deck_of.get(notetype, ""), note)
            out.recreated += 1
        except (ConnectionError, RuntimeError) as exc:
            out.failures.append(_("{label} (recreation): {error}")
                                .format(label=_label(note), error=console.reason(exc)))

    for notetype in changes.templates:
        saved = snap["notetypes"][notetype].get("templates") or {}
        try:
            if saved.get("cards"):
                anki("updateModelTemplates",
                     model={"name": notetype, "templates": saved["cards"]})
            anki("updateModelStyling",
                 model={"name": notetype, "css": saved.get("css", "")})
            out.templates += 1
        except (ConnectionError, RuntimeError) as exc:
            out.failures.append(_("templates of {notetype}: {error}")
                                .format(notetype=notetype, error=console.reason(exc)))

    return out


# -- Automatic backup ------------------------------------------------------------

def before(reason: str, *, only: list[str] | None = None) -> Path | None:
    """Snapshot taken just before a command that writes, unless `KOTOGEN_BACKUP=0`.

    Never raises: a failure does not block the command, but is said on a `!!` line.
    """
    return take(reason, only=only) if enabled() else None


def take(reason: str, *, only: list[str] | None = None) -> Path | None:
    """A snapshot of the decks as they stand, said on one line; None if it failed.

    The latest snapshot when nothing moved since, as it holds the same state.
    Never raises: a failure is said on a `!!` line.
    """
    commands = targets(only)
    if not commands:
        return None
    # Reading a large collection takes a while: the wait turns on a line of its
    # own, dropped for the report, which leads with a stamp known only once saved.
    # Not opened outside a terminal, where it would stay as a second line.
    def take() -> tuple[dict, Path | None]:
        snap = snapshot(commands, reason=reason)
        return snap, save(snap)

    if sys.stdout.isatty():
        console.open_line(f"{_('Backup')}…")
    try:
        snap, path = console.while_working(take)
    except (ConnectionError, RuntimeError, ValueError, OSError) as exc:
        console.drop_line()
        print("!! " + _("Backup impossible ({error})").format(error=console.reason(exc)))
        return None
    console.drop_line()

    if path is None:
        previous = latest()
        print(_("Backup unchanged since {stamp}").format(
            stamp=parse_name(previous)[0] if previous else "?"))
        return previous
    # The stamp leads the line: it is what gets typed after `--restore`.
    print(_("Backup {stamp} ({notes}{covered})").format(
        stamp=parse_name(path)[0], notes=_notes(note_count(snap)),
        covered=listed(["", *snap["notetypes"]]) if snap["notetypes"] else ""))
    return path


# -- Display ---------------------------------------------------------------------
# One line per fact; the explanations are in the docs.

def _notes(count: int) -> str:
    """The count and its noun, agreed: "1 note", "3 notes"."""
    return f"{count} {console.plural(count, 'note')}"


def _age(seconds: float) -> str:
    """Relative age of a backup, whose name already carries the date."""
    if seconds < 90:
        return _("just now")
    if seconds < 3600:
        return _("{count} min ago").format(count=int(seconds // 60))
    if seconds < 86400:
        return _("{count} h ago").format(count=int(seconds // 3600))
    days = int(seconds // 86400)
    # "Yesterday" is one day, whatever the language makes of the number one: in
    # Russian 21 takes the form of 1, and is not yesterday.
    if days == 1:
        return _("yesterday")
    return counted(days, "{count} day ago", "{count} days ago").format(count=days)


def _print_listing() -> None:
    found = snapshots()
    print(_("Backups ({folder}):").format(folder=backup_dir()))
    if not found:
        print("   " + _("none."))
        return

    archives = {parse_name(path)[0] for path in packages()}
    now = time.time()
    for path in found:
        stamp, reason = parse_name(path)
        try:
            snap = load(path)
            count = _notes(note_count(snap))
        except ValueError:
            count = _("unreadable")
        try:
            age = _age(now - path.stat().st_mtime)
        except OSError:
            age = ""
        full = "   + " + _("archive .apkg") if stamp in archives else ""
        count = " " * max(0, 12 - console.width(count)) + count
        print(f"   {stamp}   {console.pad(reason, 9)} {count}   {age}{full}")


def _print_diff(changes: Diff, *, limit: int = 20) -> None:
    """What has moved, note by note, the fields truncated: enough to recognise it."""
    from kotogen.exporter import short

    if not changes:
        print("   " + _("Nothing has moved."))
        return

    colon = convention("colon", ": ")
    for notetype in changes.missing:
        print(f"   !! {notetype}{colon}" + _("note type gone from the profile"))
    for notetype in changes.templates:
        print(f"   !! {notetype}{colon}" + _("templates modified"))

    empty = _("(empty)")
    for change in changes.changed[:limit]:
        console.space()
        print(f"   {change.label}   " + _("[note {id}]").format(id=change.note_id))
        for name, (old, new) in change.fields.items():
            print(f"      {name}{colon}{short(old, 45) or empty}"
                  f"  →  {short(new, 45) or empty}")
        if change.added_tags:
            print(f"      + {' '.join(change.added_tags)}")
        if change.removed_tags:
            print(f"      - {' '.join(change.removed_tags)}")
        for old, new in change.cards.values():
            print(f"      ivl {old.get('ivl', '?')} → {new.get('ivl', '?')},"
                  f" reps {old.get('reps', '?')} → {new.get('reps', '?')}")
    if len(changes.changed) > limit:
        console.space()
        print("   " + _("... and {count} others.")
              .format(count=len(changes.changed) - limit))

    if changes.deleted:
        console.space()
        print("   " + _("Deleted ({count}):").format(count=len(changes.deleted)))
        for _notetype, note in changes.deleted[:limit]:
            print(f"      - {_label(note)}")
    if changes.created:
        console.space()
        print("   " + _("Added ({count}):").format(count=len(changes.created)))
        for _notetype, note in changes.created[:limit]:
            print(f"      + {_label(note)}")


def _print_restored(out: Restored) -> None:
    said = [text.format(count=count) for count, text in (
        (out.fields, counted(out.fields, "{count} note put back",
                             "{count} notes put back")),
        (out.tags, counted(out.tags, "{count} note retagged", "{count} notes retagged")),
        (out.cards, counted(out.cards, "{count} card rescheduled",
                            "{count} cards rescheduled")),
        (out.recreated, counted(out.recreated, "{count} note recreated",
                                "{count} notes recreated")),
        (out.templates, counted(out.templates, "{count} template put back",
                                "{count} templates put back")),
    ) if count]
    console.space()
    print(_("Restored: {what}.").format(what=listed(said) or _("nothing")))
    for failure in out.failures:
        print(f"   !! {failure}")


# -- Main entry point --------------------------------------------------------------

def _commands_of(snap: dict) -> list[str]:
    """The commands whose note types this snapshot carries.

    Not `--only`: a narrower scope would make the rest pass for deleted.
    """
    return [command for command in DECK_COMMANDS
            if deck_config(command)[1] in snap["notetypes"]]


def _current(snap: dict) -> dict:
    """Current state of the note types this snapshot carries."""
    return snapshot(_commands_of(snap), reason="comparison")


def _run_diff(stamp: str) -> None:
    path = find(stamp)
    snap = load(path)
    print(_("Since {stamp} ({notes}):").format(
        stamp=parse_name(path)[0],
        notes=_notes(note_count(snap))))
    _print_diff(diff(snap, _current(snap)))


def _run_restore(stamp: str, *, assume_yes: bool) -> None:
    from kotogen.exporter import ask_choice

    path = find(stamp)
    snap = load(path)
    current = _current(snap)
    # Note ids are those of one collection: another profile's notes would all
    # pass for deleted, and be recreated there.
    taken_in, open_now = snap.get("profile") or "", current.get("profile") or ""
    if taken_in and open_now and taken_in != open_now:
        raise ValueError(_("{stamp} was taken in the Anki profile {saved}, and the "
                           "profile open is {current}: open {saved} in Anki to "
                           "restore it.").format(stamp=parse_name(path)[0],
                                                 saved=_quoted(taken_in),
                                                 current=_quoted(open_now)))
    changes = diff(snap, current)
    print(_("Restoring {stamp} ({notes}):").format(
        stamp=parse_name(path)[0],
        notes=_notes(note_count(snap))))
    _print_diff(changes)
    if not changes.changed and not changes.deleted and not changes.templates:
        console.space()
        print(_("Nothing to restore."))
        return

    said = [text.format(count=count) for count, text in (
        (len(changes.changed), counted(len(changes.changed), "{count} note modified",
                                       "{count} notes modified")),
        (len(changes.deleted), counted(len(changes.deleted), "{count} note to recreate",
                                       "{count} notes to recreate")),
        (len(changes.templates), counted(len(changes.templates), "{count} template",
                                         "{count} templates")),
    ) if count]
    console.space()
    print(_("To put back: {what}.  Nothing will be deleted.")
          .format(what=listed(said)))
    if not assume_yes and ask_choice(_("Restore? [y] yes  [n] no"), "yn") != "y":
        print(_("Cancelled."))
        return
    # The state about to be overwritten is a snapshot like any other, so that
    # the restore can itself be undone: taken whatever KOTOGEN_BACKUP says, and
    # nothing is overwritten without it.
    console.space()
    if take("restore", only=_commands_of(snap)) is None:
        sys.exit(_("Nothing was restored: the deck as it stands could not be backed "
                   "up first."))
    _print_restored(restore(snap, changes))


def run_backup(args) -> None:
    """`kotogen backup`: take, list, compare, restore."""
    import sys

    try:
        if args.list:
            _print_listing()
            return
        if args.diff is not None:
            _run_diff(args.diff)
            return
        if args.restore is not None:
            _run_restore(args.restore, assume_yes=args.yes)
            return

        commands = targets(args.only)
        if not commands:
            sys.exit(_("No deck to back up: --only designates nothing known "
                       "({known}), or KOTOGEN_SKIP hides them all.")
                     .format(known=listed(DECK_COMMANDS)))
        snap = snapshot(commands, reason="manual")
        stamp = stamp_now()
        path = save(snap, stamp=stamp)
        if path is None:
            # Unchanged deck: the archive takes the stamp of the last snapshot,
            # which describes the same state, so `--list` shows both on one line.
            previous = latest()
            stamp = parse_name(previous)[0] if previous else stamp
            print(_("Unchanged since {stamp}.").format(stamp=stamp))
        else:
            print(_("Backed up: {notes} → {path}").format(
                notes=_notes(note_count(snap)), path=path))

        if args.full:
            # Archived even when the snapshot is unchanged: the archive carries
            # the media.
            print("   " + _("archiving (several minutes)..."))
            written = export_packages(commands, stamp=stamp)
            total = 0.0
            for archive in written:
                try:
                    size = archive.stat().st_size / (1024 * 1024)
                except OSError:
                    print(f"   !! {archive.name}{convention('colon', ': ')}"
                          + _("announced written, not found"))
                    continue
                total += size
                print(f"   {archive.name}  {size:.0f} " + _("MB"))
            if total:
                print(f"   = {total:.0f} " + _("MB"))
    except ConnectionError as exc:
        sys.exit(console.reason(exc, console.ALONE))
    except (RuntimeError, ValueError) as exc:
        sys.exit(_("Backup: {error}").format(error=console.reason(exc, console.ALONE)))
