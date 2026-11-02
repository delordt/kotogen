# Backing up the deck (`kotogen backup`)

A **snapshot** of the five Japanese decks: the fields and tags of every note, the
**scheduling** of every card (interval, due date, ease, repetitions, lapses) and the
**templates** of the note types. One is taken automatically before `maintain`, `ask` and
`deck install` change what you have in the deck, and kotogen restores it itself, note by
note. Requires **AnkiConnect** (Anki open).

```bash
# Back up now
kotogen backup

# What changed since the last backup
kotogen backup --diff

# The backups already taken, newest first
kotogen backup --list

# Put the deck back in the state it was in then (nothing is ever deleted)
kotogen backup --restore 2026-08-17_143012

# + one .apkg archive per deck, media included
kotogen backup --full
```

## Why, when Anki already backs up

Anki copies the whole collection by itself, some thirty times over, when the profile
closes. That covers losing everything, and kotogen does not redo it. It leaves two gaps:

**Granularity.** Restoring an Anki backup replaces the whole collection. Getting back the
twelve notes a `maintain --yes` rewrote last night would cost everything reviewed since, in
the Japanese decks **and in all the others**.

**Timing.** Anki's copy dates from the last time the profile was closed, not from the
moment before the risky command.

## What triggers an automatic backup

| Command | Backup | Why |
|---|---|---|
| `kotogen maintain` | **yes**, after the survey and before the first AI call | It deletes notes, rewrites fields in bulk under `--yes`, and resets leeches |
| `kotogen ask` | **yes**, at the first accepted write | The AI rewrites fields, tags in bulk and can delete. A request that only looks takes no snapshot |
| `kotogen deck install` | **yes**, once a change to an existing type is accepted (a face rewritten, a card added) and before it is written | A front edited in Anki exists only in Anki, and the repository version is about to overwrite it. What needs no question (a type created, a field added, a face only kotogen changed) holds nothing of yours and takes no snapshot |
| `kotogen backup --restore` | **yes**, once confirmed and before the first write, even with `KOTOGEN_BACKUP=0` | The restore overwrites the current state too: its own snapshot is how it is undone |
| `kotogen maintain --scan`, `kotogen ask --scan`, `deck install --check` | no | They change nothing |
| `vocab`, `grammar`, `audio`, `reading`, `kanji` | no | They only **add**: an extra card can be found and deleted |

If the backup fails (Anki closed in the meantime, disk full), `maintain` and `deck install`
say so on a `!!` line and carry on without a net. `ask` applies no change it could not back
up, and `backup --restore` restores nothing.

A snapshot is written only if its content differs from the previous one: two runs with
nothing changed in between write one file.

## The two layers, and which one is for what

| | JSON snapshot | `.apkg` archive (`--full`) |
|---|---|---|
| Content | Fields, tags, scheduling, templates | The complete Anki deck, **media included** |
| Size | A few MB (about 5 MB for 10,000 notes) | Hundreds of MB: the listening audio and video and the mini-book images travel with it |
| Duration | ~5 s | Several minutes, with Anki frozen meanwhile |
| Taken | Automatically, and on `kotogen backup` | Only on `--full` |
| Restored | By kotogen, note by note (`--restore`) | By hand, from Anki |
| Answers | "undo what the last maintain did" | "the deck is gone" |

The archive cannot undo a change. Imported back, Anki matches its notes by GUID and only
updates a note when the imported version is the more recent, which a backup never is. It is
for a lost deck, restored by hand from Anki.

The two also differ on a collection reorganised by hand. The snapshot works by **note
type**: a card moved into another deck is still in it. The archive works by **deck**,
because AnkiConnect only exports decks, so it misses that card.

## Restoring

`--restore` first compares the backup with the current state, shows the detail, then asks
for confirmation (`--yes` skips it). It can put back:

- the rewritten **fields**, with their value from then;
- the **tags** added or removed since, both ways;
- the **scheduling** of a card. It is the only way to undo the reset of a true leech: its
  fields may be intact while the card has lost months of progress;
- the **deleted notes**, recreated in the deck of their note type. They come back with a
  **new id** (Anki reuses none), and with their scheduling if the note type still has the
  same number of cards;
- the **templates** (cards and CSS) of a note type.

Everything that changed since the snapshot goes back, reviews included: a card reviewed
since the snapshot gets its old scheduling back.

**Nothing is ever deleted.** A note created after the snapshot is listed and left in place.

A note that resists (locked, note type changed in the meantime) is reported at the end, and
the restore goes on with the next ones.

**A restore can be undone.** Once confirmed, and before writing anything, it takes a
snapshot of the state it is about to overwrite, filed under the reason `restore`, even when
`KOTOGEN_BACKUP=0` turns the automatic backups off. If that snapshot cannot be taken, the
restore is refused and nothing is written. The snapshot is then the latest backup, so
`kotogen backup --restore` with no stamp puts back what the restore replaced.

**A backup goes back into the profile it was taken in.** Note ids belong to one collection:
in another profile every note of the backup would pass for deleted and be recreated. A
backup taken in another Anki profile than the one open is refused, the message naming both.

## Options

| Option | Effect |
|---|---|
| `--only TARGET...` | Decks to back up (default: all five, minus those `KOTOGEN_SKIP` lists): `kanji vocab grammar audio reading` |
| `--list` | Lists the backups, newest first, with their reason, note count and age, and whether an `.apkg` archive goes with them |
| `--diff [STAMP]` | What changed since that backup (default: the latest) |
| `--restore [STAMP]` | Puts that backup back (default: the latest) |
| `--full` | Also exports one `.apkg` per deck, scheduling and media included |
| `--yes`, `-y` | Restores without asking for confirmation |

`STAMP` is a timestamp (`2026-08-17_143012`). It can be shortened as long as it designates a
single backup: `2026-08-17` is enough if only one was taken that day. When two match, the
command fails rather than pick one.

`backup` calls no model: neither `--provider` nor `--model`, and **no AI cost**.

## Where they are filed, and for how long

In the **data** folder of the platform, never in the cache: disk cleaners empty caches, and
a backup is the only copy of what a note held before it was changed.

| System | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\kotogen\backups` |
| Linux | `$XDG_DATA_HOME/kotogen/backups` (that is `~/.local/share/...`) |
| macOS | `~/Library/Application Support/kotogen/backups` |

Retention: the **10 most recent snapshots** are all kept, so you can go back past several
runs in a row. Older ones are thinned to one per day, and none is kept past 90 days.

The `.apkg` archives are kept for the last **2 archivings**, an archiving being the archives
written under one timestamp, kept or deleted together. Each weighs several hundred
megabytes; the older one is there in case the latest cannot be read back.

## Settings

To be set in the [settings](global-options.md#where-the-settings-live) file.

```dotenv
# Never back up automatically (kotogen backup asked for by hand still obeys, and a
# restore still backs up what it overwrites)
# KOTOGEN_BACKUP=0

# File the backups elsewhere (an external drive, a synced folder)
# KOTOGEN_BACKUP_DIR=C:\Users\me\backups\kotogen
# KOTOGEN_BACKUP_DIR=/home/me/backups/kotogen
```

---

[Documentation index](../README.md#documentation)
