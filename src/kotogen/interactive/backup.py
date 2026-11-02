"""The dialogue of `kotogen backup`: which verb, then which backup."""

from __future__ import annotations

from kotogen import console
from kotogen.i18n import _, counted
from kotogen.interactive.screen import _Back, _entry, _header, _menu, _pause
from kotogen.interactive.status import _missing_for, _still_missing, _why_not

# ── Backup ────────────────────────────────────────────────────────────────────

def _backup_mode() -> str:
    """Five verbs, in the order they come up in: one takes a backup, then one
    makes use of those one has.

    `--full` takes the same snapshot before exporting the decks, hence its place;
    restoring, the only verb that writes into Anki, closes the list. With Anki
    closed only listing is left, as it reads the folder of the backups alone: the
    others, "Compare" included, need the state of the profile.
    """
    choice: int | str = 1
    while True:
        missing = _missing_for(anki=("", "--full", "--diff", "--restore"))
        choice = _menu(_("Backup - what to do?"), [
            ("", _entry(_("Back up"),
                        _("snapshot of the deck: notes, tags and templates"), 13)),
            ("--full", _entry(_("Archive"),
                              _("the same, plus the media (.apkg) - far heavier"), 13)),
            ("--list", _entry(_("List"),
                              _("the existing backups, with their age"), 13)),
            ("--diff", _entry(_("Compare"),
                              _("what has moved since one of them"), 13)),
            ("--restore", _entry(_("Restore"),
                                 _("put the deck back into an earlier state"), 13)),
        ], default=choice, allow_back=True, memory="backup",
            disabled=missing)
        if choice not in missing or not (
                lacking := _still_missing(missing[choice])):
            return str(choice)
        # Dimmed, chosen, and Anki still silent: say what is missing, then redraw.
        _why_not(lacking)
        _header()


def _ask_stamp(action: str) -> str | None:
    """Which backup: a menu of those that exist, the most recent at the head.

    Nothing to choose when there is only one; None when there is none, after
    saying so rather than showing an empty menu.
    """
    from kotogen.anki import backup

    found = backup.snapshots()
    if not found:
        console.space()
        print(_("No backup to compare.") if action == "compare"
              else _("No backup to restore."))
        _pause(_("Enter to come back to the menu..."))
        return None
    if len(found) == 1:
        return backup.parse_name(found[0])[0]

    options = []
    for path in found[:12]:
        stamp, reason = backup.parse_name(path)
        try:
            notes = backup.note_count(backup.load(path))
            count = counted(notes, "{count} note", "{count} notes").format(count=notes)
        except ValueError:
            count = _("unreadable")
        options.append((stamp, f"{stamp}   {console.pad(reason, 9)} {count}"))
    return _menu(_("Which backup to compare?") if action == "compare"
                 else _("Which backup to restore?"),
                 options, default=1, allow_back=True)


def _backup_options(mode: str) -> list[str]:
    if mode in ("--diff", "--restore"):
        stamp = _ask_stamp("compare" if mode == "--diff" else "restore")
        if stamp is None:
            raise _Back
        # The restore itself shows the detail and says it deletes nothing, then
        # asks for confirmation.
        return ["backup", mode, stamp]
    return ["backup"] + ([mode] if mode else [])
