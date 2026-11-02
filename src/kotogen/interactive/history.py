"""The history of the sources: what it holds, what is picked back up from
the deck, and what is forgotten."""

from __future__ import annotations

from kotogen import console, memory, seen
from kotogen.i18n import _, agreed, counted, listed, quoted, sentence

# Anki is asked through `status`: the menu has one probe, and this screen uses it.
from kotogen.interactive import status
from kotogen.interactive.screen import _ask_yes_no, _Back, _header, _menu, _pause

# ── Source history ────────────────────────────────────────────────────────────
# The file of what has already gone by (`seen`, ~/.kotogen/seen.json) keeps a
# relaunch from paying again for the same cards; `--episode` skips it.

def _entry_count(count: int) -> str:
    """"1 entry", "46 entries": a count read in a menu agrees."""
    return _("{count} {entries}").format(
        count=count, entries=console.plural(count, "entry", "entries"))


def _source_labels(keys: list[str]) -> dict[str, str]:
    """Readable name of each source, its key failing that.

    Both catalogues are read once, as each reads the file of the user's feeds.
    A key in neither (a URL pasted by hand, an alias renamed) shows bare."""
    from kotogen.generators import audio_files, irodori, jlpt_papers, podcast, youtube

    channels, feeds = youtube.catalogue(), podcast.catalogue()
    labels = {}
    for key in keys:
        if key == "nhk":
            labels[key] = "NHK Easy"
        elif key == "tadoku":
            labels[key] = _("Free books (Tadoku)")
        elif key == "aozora":
            labels[key] = "青空文庫"
        elif key.startswith("aozora-"):
            # The progress inside a work, under its number: the title comes from
            # the catalogue, cached.
            labels[key] = _aozora_title(key.removeprefix("aozora-"))
        elif key == "roudoku":
            labels[key] = "青空朗読"
        elif key in channels:
            labels[key] = _("{name} (YouTube)").format(name=channels[key].name)
        elif key in feeds:
            labels[key] = _("{name} (podcast)").format(name=feeds[key].name)
        elif key == audio_files.FILES_SOURCE:
            # Files from any folder share one key, the folder not identifying
            # them (see `audio_files._file_id`); named as the block handling them.
            labels[key] = _("Audio files")
        elif key in irodori.VOLUMES:
            labels[key] = irodori.VOLUMES[key].name
        elif jlpt_papers.is_jlpt_input(key):
            labels[key] = jlpt_papers.resolve(key).name
        else:
            labels[key] = key
    return labels


def _aozora_title(identifier: str) -> str:
    """"ごん狐 (青空文庫)", or the bare number if the catalogue does not know it.

    Called only for a work key in the history, so that the screen does not load
    ten thousand titles for nothing.
    """
    from kotogen.generators import aozora

    for work in aozora.catalogue():
        if work.work_id == identifier:
            return f"{work.title} (青空文庫)"
    return f"青空文庫 {identifier}"


def _pick_up_from_deck() -> None:
    """Fills the local history with what the deck keeps of its sources.

    For a second machine, whose deck is synced and history empty. The sources
    also ask the deck at every pass (`known.Known.sources`); written into the
    file, the history holds with Anki closed.
    """
    console.space()
    if not status.anki_status(refresh=True).connected:
        # Harmless: nothing is written, nothing is lost.
        print("   " + _("Anki is not connected: the deck cannot be read."))
        _pause(_("Enter to come back..."))
        return

    recovery = seen.recover(memory.known())
    labels = _source_labels(list(recovery.added))
    if recovery.total:
        detail = listed(f"{labels[key]} {count}" for key, count
                           in sorted(recovery.added.items(),
                                     key=lambda item: (-item[1], item[0])))
        print("   " + agreed(recovery.total,
                             "{entries} taken back from the deck: {detail}")
              .format(entries=_entry_count(recovery.total), detail=detail))
    else:
        print("   " + _("Nothing to take back: the deck carries no source the"
                        " history does not know."))
    # The rest on one line, zeroes left out.
    rest = []
    if recovery.known:
        rest.append(agreed(recovery.known, "{count} already known")
                    .format(count=recovery.known))
    if recovery.without_id:
        rest.append(_("{count} with no identifier in the card").format(
            count=recovery.without_id))
    if recovery.foreign:
        rest.append(_("{count} outside the sources followed").format(
            count=recovery.foreign))
    if rest:
        print("   " + sentence(listed(rest)))
    if recovery.without_id:
        # A podcast episode, almost certainly: its card does not carry its
        # `guid`, but it is recognised at every pass with Anki open.
        print("   " + _("A podcast episode is not written here (its card does not"
                        " carry its identifier):"))
        print("   " + _("it stays recognised at every pass, with Anki open."))
    if recovery.missing:
        # Sources the history holds and the deck has no card of: said, never
        # forgotten on its own (see `seen.missing`).
        names = _source_labels(list(recovery.missing))
        count = len(recovery.missing)
        print("   ! " + sentence(counted(
            count,
            "{count} source no longer has a card in the deck: {names}",
            "{count} sources no longer have a card in the deck: {names}").format(
                count=count, names=listed(names[key] for key in recovery.missing))))
    _pause(_("Enter to come back..."))


def _forget_the_absent() -> None:
    """Forgets at one go the sources the deck no longer carries a single card of.

    The guards of `seen.missing`, and "no" by default: what is forgotten is paid
    for again in AI calls at the next pass.
    """
    console.space()
    if not status.anki_status(refresh=True).connected:
        print("   " + _("Anki is not connected: the deck cannot be read."))
        _pause(_("Enter to come back..."))
        return
    absent = seen.missing(memory.known())
    if not absent:
        print("   " + _("Nothing to forget: the deck still carries a card of each"
                        " of the sources it can name."))
        _pause(_("Enter to come back..."))
        return
    names = _source_labels(list(absent))
    count = sum(trace.total for trace in seen.inventory()
                if trace.source in absent)
    print("   " + _("No card left in the deck: {names}.").format(
        names=listed(names[key] for key in absent)))
    what = counted(len(absent), "this source",
                   "these {count} sources").format(count=len(absent))
    if not _ask_yes_no(_("Forget {what} ({entries})").format(
            what=what, entries=_entry_count(count))):
        return
    forgotten = sum(seen.forget(key) for key in absent)
    print("   " + agreed(forgotten, "{entries} forgotten, to be offered"
                         " again at the next pass.")
          .format(entries=_entry_count(forgotten)))
    _pause(_("Enter to come back..."))


def _history() -> None:
    """The history of the sources: what it holds, what one takes back, what one forgets.

    The screen reopens after every action, often taken on several sources in a
    row. Forgetting drops identifiers, not files: the audio and transcriptions
    stay cached, so the price paid again is that of the AI calls."""
    while True:
        traces = seen.inventory()
        labels = _source_labels([trace.source for trace in traces])
        _header()
        console.space()
        if traces:
            print(_("Sources already handled: what makes a relaunch not do the"
                    " same cards again."))
            print(_("Forgetting a source means doing - and paying for - its cards"
                    " again at the next pass."))
        else:
            # A new machine: the deck already knows what the others have done.
            print(_("No source handled on this machine: the history is empty."))
            print(_("The deck, for its part, keeps what the other machines have"
                    " done - that is what {key} takes back of it.")
                  .format(key=quoted("d")))
        console.space()
        # A blank line parts the actions on the whole history from the numbered
        # sources, when there are any.
        extras: list[tuple[str | None, str]] = [(None, "")] if traces else []
        extras.append(("d", _("Take back from the deck")))
        if traces:
            # In order of risk: what reads the deck, what acts on it, what reads
            # nothing.
            extras.append(("f", _("Forget those no longer in the deck")))
            extras.append(("a", _("Forget everything")))
        try:
            choice = _menu(
                "",
                # The count follows the name rather than a column, which a
                # Japanese title, wider than its character count, would shift.
                # The modes are `seen.MODES`, English, translated here.
                [(str(rank), f"{labels[trace.source]} - {_entry_count(trace.total)}"
                             f" ({listed(_(mode, 'mode') for mode in trace.modes)})")
                 for rank, trace in enumerate(traces)],
                extras=extras,
                allow_back=True,
            )
        except _Back:
            return  # up to the settings, nothing changed
        if choice == "d":
            _pick_up_from_deck()
            continue
        if choice == "f":
            _forget_the_absent()
            continue
        target = None if choice == "a" else traces[int(choice)].source
        what = (_("the whole history") if target is None
                else _("the history of {name}").format(name=labels[target]))
        count = (sum(trace.total for trace in traces) if target is None
                 else next(trace.total for trace in traces
                           if trace.source == target))
        console.space()
        # Default "no": a forgetting cannot be undone, and costs AI calls.
        if not _ask_yes_no(_("Forget {what} ({entries})").format(
                what=what, entries=_entry_count(count))):
            continue
        forgotten = seen.forget(target)
        print("   " + agreed(forgotten, "{entries} forgotten, to be offered"
                             " again at the next pass.")
              .format(entries=_entry_count(forgotten)))
        _pause(_("Enter to come back..."))
