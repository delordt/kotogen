"""The pass of one mark over one kind of card: a change asked for each card, shown, applied.

On vocabulary, the `duplicate` action is here too: a copy too many deleted, and
the words a translation makes alike told apart by their `Context`.
"""

from __future__ import annotations

from kotogen import console
from kotogen.ai_client import AIAuthError
from kotogen.anki.connect import EditorOpen, request as anki
from kotogen.anki.deck import card as as_card
from kotogen.anki.maintain import lone_kanji, marks
from kotogen.anki.maintain.lone_kanji import DELETED, KEPT
from kotogen.anki.maintain.marks import MARKED_TAG, STAR, Quit, ai_failed, tally
from kotogen.exporter import ask_choice, choose, short
from kotogen.i18n import _, convention, counted, listed, quoted
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.review import (
    _bare_kanji_report,
    _change_summary,
    _changed_fields,
    _field,
    _find_duplicate_candidates,
    _identical_words,
    _judge_duplicates,
    _normalise_proposal,
    _probable_duplicates,
    _propose_differentiation,
    _propose_group_contexts,
    _proposed_deletion,
    _read_group_proposal,
    _signals,
    _translation_group,
    auto_line,
    card_name,
    propose_changes,
    read_category,
    sharing,
)

# The mark the running pass takes off (see `unmark`); 0 outside a pass, where
# `ask` clears flags only.
_pass_mark = 0


def unmark(card_id: int) -> None:
    """Takes off the mark the running pass handles: the flag of the card, or the
    star of its note."""
    if _pass_mark != STAR:
        marks.clear_flag(card_id)
        return
    info = anki("cardsInfo", cards=[card_id]) or []
    if info:
        anki("removeTags", notes=[info[0]["note"]], tags=MARKED_TAG)


# ── Handling one flag ─────────────────────────────────────────────────────────

def _sense(note: dict) -> str:
    """Readable translation, followed by the `Context` when there is one.

    The `Context` is what tells 着る from 被る, both "To wear".
    """
    translation = short(_field(note, "Translation").replace("<br>", " / "))
    ctx = _field(note, "Context")
    return f"{translation} ({short(ctx)})" if ctx else translation


def _card_text(note: dict) -> str:
    """A card on one line: its expression, its sense and the note it lives in."""
    return (f"{_field(note, 'Expression')} - {_sense(note)}   "
            + _("[note {note}]").format(note=note["id"]))


def _show_card_line(label: str, note: dict) -> None:
    print(f"   {label}" + convention("colon", ": ") + _card_text(note))


def _offer_deletion(note: dict, cand: dict, drop: int, reason: str, auto: bool) -> str:
    """Deletion proposed by the AI: double confirmation, and never automatically.

    Hands back the outcome in the sense of `_differentiate`.
    """
    if auto:
        return "pending"  # nothing gets deleted without you (report in _auto_duplicate)

    doomed, label = ((note, _("card 1 (flagged)")) if drop == 1
                     else (cand, _("card 2")))
    print("   → " + _("Nothing to tell apart according to the AI: {label} has no "
                      "place.").format(label=label))
    if reason:
        print("   " + _("Reason: {reason}").format(reason=console.clean(reason)))
    _show_card_line(_("To delete"), doomed)
    if ask_choice(_("[d] delete  [k] keep both"), "dk") != "d":
        return "none"
    if ask_choice(_("Delete note {note} for good? [y] yes  [n] no").format(
            note=doomed["id"]), "yn") != "y":
        return "none"
    marks.delete_notes([doomed["id"]])
    tally.changed += 1
    print("   " + _("{label} deleted").format(label=label))
    return "deleted_target" if drop == 1 else "deleted_other"


def _differentiate(client, note: dict, cand: dict, auto: bool) -> str:
    """Proposes a distinction between two cards - or the deletion of the one too many.

    Through the `Context` when the translations match, as the translation ->
    Japanese front shows nothing else; the `Notes` for a finer nuance. Hands back
    "none", "applied", "deleted_other" / "deleted_target" (the flagged card is
    gone), or "pending" (a deletion proposed in automatic mode, left to you).
    """
    try:
        proposal = _propose_differentiation(client, note, cand)
    except AIAuthError:
        raise
    except Exception as exc:
        ai_failed(exc)
        return "none"
    reason = str(proposal.get("reason", "")).strip()
    drop = _proposed_deletion(proposal)
    if drop:
        return _offer_deletion(note, cand, drop, reason, auto)
    c1 = _changed_fields(note, proposal.get("card1") or {})
    c2 = _changed_fields(cand, proposal.get("card2") or {})
    if not c1 and not c2:
        if not auto:
            print("   → " + _("The AI proposed no usable distinction."))
        return "none"
    if not auto:
        print("   " + _("Distinction proposed: {reason}").format(
            reason=console.clean(reason)))
        empty = _("(empty)")
        colon = convention("colon", ": ")
        for label, n, changes in ((_("Card 1"), note, c1), (_("Card 2"), cand, c2)):
            for name, new in changes.items():
                print(f"   {label} / {name}{colon}{short(_field(n, name)) or empty}"
                      f"  →  {short(new)}")
        if ask_choice(_("Apply? [y] yes  [n] cancel"), "yn") != "y":
            return "none"
    if c1:
        marks.apply_changes(note["id"], c1, [], [])
        tally.changed += 1
    if c2:
        marks.apply_changes(cand["id"], c2, [], [])
        tally.changed += 1
    if not auto:
        print("   " + _("distinction applied"))
    return "applied"


def _keep_one(cluster: list[dict]) -> list[int]:
    """The same word in several copies: keep one, delete the others.

    Hands back the ids of the notes deleted, `[]` when you settled nothing -
    "later" is always an answer, and it is the one a redirected input keeps.
    """
    console.space()
    print("   ── " + _("Same word twice") + " ──────────")
    # Past 9 the menu has no key left: the rest waits for the next round.
    cluster = cluster[:9]
    choice = choose([(str(i), _card_text(n)) for i, n in enumerate(cluster, 1)]
                    + [("l", _("later"))], _("Which one to keep?"))
    if choice == "l":
        print("   " + _("left as it is"))
        return []
    kept = cluster[int(choice) - 1]
    doomed = [n for n in cluster if n["id"] != kept["id"]]
    ids = [n["id"] for n in doomed]
    listing = listed(_field(n, "Expression") for n in doomed)
    if ask_choice(_("Delete {names} for good? [y] yes  [n] no").format(
            names=listing), "yn") != "y":
        print("   " + _("deletion cancelled"))
        return []
    marks.delete_notes(ids)
    tally.changed += len(ids)
    print("   " + counted(len(ids),
                          "{count} note deleted, {kept} kept",
                          "{count} notes deleted, {kept} kept").format(
        count=len(ids), kept=quoted(_field(kept, "Expression"))))
    return ids


def _show_group(group: list[dict]) -> None:
    """The batch at a glance: who fights over the question, with which context.

    The cards that are the same word are marked here, as they are settled first.
    """
    doubles = {n["id"] for c in _identical_words(group) for n in c}
    console.space()
    print("   ── " + _("{count} cards fight over {translation}").format(
        count=len(group),
        translation=quoted(short(_field(group[0], "Translation")))) + " ──────────")
    for i, n in enumerate(group, 1):
        ctx = _field(n, "Context")
        mark = "  ! " + _("same word twice") if n["id"] in doubles else ""
        print(f"      {i}. {_field(n, 'Expression')}"
              f"{'  → ' + short(ctx) if ctx else '  ' + _('(no context)')}{mark}")


def _resolve_group(client, group: list[dict], auto: bool) -> tuple[int, list[int], bool]:
    """Tells apart in one go every card of the same translation.

    Hands back (cards changed, ids of the notes deleted, batch settled); settled,
    the batch's flags can fall. A duplicate left pending settles nothing: two
    copies of one word would take two contexts.
    """
    deleted: list[int] = []
    clusters = _identical_words(group)
    if clusters and auto:
        # A deletion is never automatic, and contexts laid over a duplicate would
        # set it in the deck: the whole batch waits for you.
        auto_line("!", group[0], _("same word twice in the batch - to be settled by "
                                   "hand, flag kept"))
        return 0, [], False
    for cluster in clusters:
        deleted += _keep_one(cluster)
    if deleted:
        group = [n for n in group if n["id"] not in deleted]
    if _identical_words(group):
        print("   → " + _("duplicate left in place: the contexts will wait for it "
                          "to be settled."))
        return 0, deleted, False
    if len(group) < 2:
        if not auto:
            print("   → " + _("no rival left: nothing to tell apart."))
        return 0, deleted, True

    try:
        proposal = _propose_group_contexts(client, group)
    except AIAuthError:
        raise
    except Exception as exc:
        ai_failed(exc)
        return 0, deleted, False

    changes, ai_clusters = _read_group_proposal(group, proposal)
    if ai_clusters:
        # The model sees one word in two spellings (仕事 / しごと): the contexts,
        # which assumed two words, are not laid.
        if auto:
            auto_line("!", group[0], _("duplicate reported by the AI in the batch - "
                                       "to be settled by hand, flag kept"))
            return 0, deleted, False
        print("   → " + _("The AI sees the same word twice in the batch."))
        for cluster in ai_clusters:
            deleted += _keep_one(cluster)
        print("   → " + _("contexts to lay again on the next pass over this batch."))
        return 0, deleted, False

    if not changes:
        if not auto:
            print("   → " + _("The AI proposes nothing to change: the batch already "
                              "tells itself apart."))
        return 0, deleted, True

    if not auto:
        reason = str(proposal.get("reason", "")).strip()
        if reason:
            print("   " + _("Distinction proposed: {reason}").format(
                reason=console.clean(reason)))
        empty = _("(empty)")
        colon = convention("colon", ": ")
        for note, fields in changes:
            print(f"   {_field(note, 'Expression')}" + colon.rstrip())
            for name, new in fields.items():
                print(f"      {name}{colon}{short(_field(note, name)) or empty}"
                      f"  →  {short(new) or empty}")
        if ask_choice(_("Apply? [y] yes  [n] cancel"), "yn") != "y":
            return 0, deleted, False

    for note, fields in changes:
        marks.apply_changes(note["id"], fields, [], [])
        tally.changed += 1
        if auto and "Translation" in fields:
            # A card changing translation leaves the batch: in automatic mode, the
            # one change worth a line of its own.
            auto_line("✓", note, _("translated {new} instead of {old}").format(
                new=quoted(short(fields["Translation"])),
                old=quoted(short(_field(note, "Translation")))))
    if not auto:
        print("   " + counted(len(changes),
                              "{count} card told apart",
                              "{count} cards told apart")
              .format(count=len(changes)))
    return len(changes), deleted, True


def _forget_notes(all_notes: list[dict], ids: list[int]) -> None:
    """Removes deleted notes from the deck held in memory, in place.

    Otherwise the next card would be compared with notes that no longer exist.
    """
    if ids:
        all_notes[:] = [n for n in all_notes if n["id"] not in set(ids)]


def _auto_duplicate(card_id: int, note: dict, all_notes: list[dict], client,
                    done: set[int]) -> tuple[int, int]:
    """Turquoise flag in automatic mode: tell apart, never delete.

    Only `Context` and `Notes` change, in one line of report. The flag goes once
    the card is examined, unless a deletion is at stake, left to a pass by hand.
    """
    start = tally.start()
    candidates = _find_duplicate_candidates(note, all_notes)
    verdicts = _judge_duplicates(client, note, candidates) if candidates else {}

    distinguished: list[str] = []
    pending = False
    for i in _probable_duplicates(candidates, verdicts):
        cand = candidates[i][0]
        outcome = _differentiate(client, note, cand, auto=True)
        if outcome == "applied":
            distinguished.append(_field(cand, "Expression"))
        elif outcome == "pending":
            pending = True

    # The batch of identical translation: "no duplicate" is not "nothing to do".
    group = _translation_group(note, all_notes)
    settled = True
    if len(group) > 1:
        a, _deleted, settled = _resolve_group(client, group, auto=True)
        if settled:
            done.update(n["id"] for n in group)
            if a:
                told = counted(a,
                               "{count} card told apart on {translation}",
                               "{count} cards told apart on {translation}")
                auto_line("✓", note, told.format(
                    count=a,
                    translation=quoted(short(_field(note, "Translation")))))

    if distinguished:
        auto_line("✓", note, _("told apart from {names}").format(
            names=listed(distinguished)))
    if pending or not settled:
        if pending:
            auto_line("!", note, _("deletion proposed by the AI - to be decided by "
                                   "hand, flag kept"))
        return tally.since(start)
    if not tally.since(start)[0]:
        auto_line("=", note, _("no duplicate confirmed, nothing to tell apart, flag "
                               "removed"))
    unmark(card_id)
    tally.cleared += 1
    return tally.since(start)


def _process_duplicate(card_id: int, note: dict, all_notes: list[dict], client, auto: bool,
                       done: set[int] | None = None) -> tuple[int, int]:
    """Turquoise flag: looks for duplicates in the whole deck and proposes actions.

    Two opposite problems, in turn: the duplicate (signals and the model's
    verdict; keep either card, tell them apart, or nothing), then distinct words
    sharing a translation, told apart together by `Context` (see `_resolve_group`)
    and added to `done`. Automatic mode: see `_auto_duplicate`. Hands back
    (actions applied, flags removed).
    """
    if done is None:
        done = set()
    if auto:
        return _auto_duplicate(card_id, note, all_notes, client, done)

    start = tally.start()
    print("   " + _("Flagged card: {expression} - {sense}").format(
        expression=_field(note, "Expression"), sense=_sense(note)))
    candidates = _find_duplicate_candidates(note, all_notes)
    verdicts = _judge_duplicates(client, note, candidates) if candidates else {}
    probable = _probable_duplicates(candidates, verdicts)
    other = [i for i in range(len(candidates)) if i not in probable]

    resolved = False  # a substantive action was taken
    gone: list[int] = []  # notes deleted along the way

    if not candidates:
        print("   → " + _("No potential duplicate found in the deck."))
    elif not probable:
        print("   → " + _("No duplicate confirmed by the AI."))
    # The labels and the choices padded to the widest, in whatever language.
    flagged, second = _("Card 1 (flagged)"), _("Card 2")
    labels = max(console.width(flagged), console.width(second))
    keep_1, keep_2, apart = _("keep card 1"), _("keep card 2"), _("tell apart")
    keys = max(console.width(keep_1), console.width(keep_2), console.width(apart))
    for i in probable:
        cand, reasons, _score = candidates[i]
        verdict, why = verdicts.get(i, ("", ""))
        console.space()
        print("   ── " + (_("potential DUPLICATE") if verdict == "duplicate"
                          else _("potential variant")) + " ──────────")
        _show_card_line(console.pad(flagged, labels), note)
        _show_card_line(console.pad(second, labels), cand)
        print("   " + _("AI verdict: {verdict}").format(
            verdict=console.clean(why) or _signals(reasons, _)))

        choice = choose([
            ("1", console.pad(keep_1, keys) + "  " + _("(delete card 2)")),
            ("2", console.pad(keep_2, keys) + "  " + _("(delete card 1)")),
            ("3", console.pad(apart, keys) + "  "
             + _("(the AI distinguishes the two, or turns down the one too many)")),
            ("4", _("do nothing")),
        ])

        # A flagged card deleted takes its flag with it: the pass ends there.
        if choice == "1":
            if ask_choice(_("Delete card 2 (note {note})? [y] yes  [n] no").format(
                    note=cand["id"]), "yn") == "y":
                marks.delete_notes([cand["id"]])
                tally.changed += 1
                resolved = True
                gone.append(cand["id"])
                print("   " + _("card 2 deleted"))
        elif choice == "2":
            if ask_choice(_("Delete the flagged card 1 (note {note})? [y] yes  "
                            "[n] no").format(note=note["id"]), "yn") == "y":
                marks.delete_notes([note["id"]])
                tally.changed += 1
                gone.append(note["id"])
                _forget_notes(all_notes, gone)
                print("   " + _("card 1 (flagged) deleted - the flag went with the note"))
                return tally.since(start)
        elif choice == "3":
            outcome = _differentiate(client, note, cand, auto)
            if outcome == "deleted_target":
                gone.append(note["id"])
                _forget_notes(all_notes, gone)
                print("   " + _("the flag went with the note"))
                return tally.since(start)
            if outcome == "deleted_other":
                gone.append(cand["id"])
            if outcome != "none":
                resolved = True

    _forget_notes(all_notes, gone)

    # Then the confusion: distinct words their translation makes alike on the
    # front, told apart all together.
    group = [n for n in _translation_group(note, all_notes) if n["id"] not in set(gone)]
    if len(group) > 1:
        _show_group(group)
        _a, deleted, settled = _resolve_group(client, group, auto)
        gone += deleted
        _forget_notes(all_notes, deleted)
        if settled:
            done.update(n["id"] for n in group if n["id"] not in set(deleted))
            if note["id"] in set(deleted):
                return tally.since(start)
            # Settled: the other flags of the batch fall without being examined,
            # or paid for, again.
            resolved = True

    # The batch has had its pass; what is left are near matches (close reading,
    # neighbouring translation), shown for information only.
    seen = {n["id"] for n in group} | set(gone)
    remaining = [i for i in other if candidates[i][0]["id"] not in seen]
    if remaining:
        console.space()
        print("   " + _("Other matches (judged different by the AI):"))
        for i in remaining:
            cand, reasons, _score = candidates[i]
            print(f"      - {_field(cand, 'Expression')} - {_sense(cand)}"
                  f"  ({_signals(reasons, _)})")

    if resolved:
        unmark(card_id)
        tally.cleared += 1
        return tally.since(start)
    console.space()
    _resolve_flag_only(card_id)
    return tally.since(start)


def _resolve_flag_only(card_id: int) -> bool:
    """Only offers to remove (or keep) the flag (interactive mode); True if it went.

    In automatic mode the flag goes unasked (see `_auto_duplicate`), so that the
    card is not examined, and paid for, again.
    """
    if ask_choice(_("Remove the flag? [y] yes  [n] keep it"), "yn") == "y":
        unmark(card_id)
        tally.cleared += 1
        return True
    return False


def process_flag(client, flag: int, kind: CardKind, auto: bool, all_notes: list[dict],
                 named: bool = False) -> tuple[int, int]:
    """Handles every card of one mark on one kind of card. Hands back (changes
    applied, marks removed).

    `named` puts the note type in the head of the pass, for a run through several.
    """
    global _pass_mark
    _pass_mark = flag
    start = tally.start()
    try:
        _process_flag(client, flag, kind, auto, all_notes, named)
    finally:
        _pass_mark = 0
    return tally.since(start)


def _process_flag(client, flag: int, kind: CardKind, auto: bool,
                  all_notes: list[dict], named: bool = False) -> None:
    action = marks.flag_actions()[flag]
    notetype = kind.notetype
    card_ids = marks.find_flagged(notetype, flag)
    console.space()
    print(f"{marks.flag_header(flag, notetype if named else '')} - {len(card_ids)} "
          f"{console.plural(len(card_ids), 'card')}"
          + (_("   [automatic]") if auto else ""))
    if not card_ids:
        return

    # The fields and tags come from notesInfo, read as the library reads a card.
    cards = anki("cardsInfo", cards=card_ids)
    note_ids = list({c["note"] for c in cards})
    notes_by_id = {n["id"]: n for n in map(as_card, anki("notesInfo", notes=note_ids))}

    # Deriving has its own pass, which gathers every card's words first. A lone
    # kanji is not offered for deletion there: 日本語 and 英語 derive from 語.
    if action == "derive":
        from kotogen.anki.maintain import derive  # late import (derive reads flag_pass)
        derive.process(client, cards, notes_by_id, kind, auto)
        return
    # A pass of its own, which hears each passage once however many of its cards
    # are flagged.
    if action == "audio" and "audio" in kind.passes:
        from kotogen.anki.maintain import listening  # late import (it reads flag_pass)
        listening.process(client, cards, notes_by_id, kind, auto)
        return

    # Notes settled with their batch of identical translation (turquoise), in one
    # call: not examined, nor paid for, again.
    settled: set[int] = set()
    for card in cards:
        note = notes_by_id.get(card["note"])
        if note is None:
            continue
        if note["id"] in settled:
            unmark(card["cardId"])
            tally.cleared += 1
            auto_line("=", note, _("already told apart with its batch, flag removed"))
            continue
        if not auto:
            console.space()
            print("── " + _("note {id}").format(id=note['id']) + " ──────────────────────────────────")

        # A lone kanji that is not a word is moved or deleted, not corrected. A
        # note deleted, here or below, takes its flag with it.
        outcome = lone_kanji.offer_lone_kanji(client, note, auto) if kind.words else KEPT
        if outcome == DELETED:
            tally.changed += 1
        if outcome != KEPT:
            continue

        if action == "duplicate" and not kind.words:
            from kotogen.anki.maintain import duplicates  # late import (it reads flag_pass)
            duplicates.process(client, card["cardId"], note, all_notes, kind, auto,
                               notes_by_id)
            continue
        if action == "duplicate":
            _process_duplicate(card["cardId"], note, all_notes, client, auto, settled)
            continue

        try:
            proposal = propose_changes(client, action, note, kind)
        except AIAuthError:
            raise  # key/quota: the following cards would all fail the same way
        except Exception as exc:
            # In automatic mode the note has no header: the card is named here.
            ai_failed(exc, note if auto else None)
            continue

        # The same answer says, at no extra cost, when the card is not vocabulary.
        verdict = read_category(note, proposal) if kind.words else None
        outcome = lone_kanji.offer_category_fix(note, verdict, auto) if verdict else KEPT
        if outcome == DELETED:
            tally.changed += 1
        if outcome != KEPT:
            continue

        refused: list[str] = []
        fields, add_tags, remove_tags, reason = _normalise_proposal(
            note, proposal, kind, refused, action)
        has_change = bool(fields or add_tags or remove_tags)

        missed = _bare_kanji_report(note, kind) if action == "text" else ""

        if not has_change:
            if auto:
                # The verdict is followed unless known wrong: a kanji left
                # without a reading, or a change turned down, keeps the flag.
                if missed:
                    auto_line("!", note, _("kanji without furigana ({missed}) - flag "
                                           "kept").format(missed=missed))
                    continue
                if refused:
                    auto_line("!", note, _("change turned down ({reason}) - flag "
                                           "kept").format(reason=listed(refused)))
                    continue
                unmark(card["cardId"])
                tally.cleared += 1
                auto_line("=", note, _("nothing to correct, flag removed"))
                continue
            colon = convention("colon", ": ")
            print(f"   {kind.label}{colon}{card_name(note)}"
                  + (f" - {short(_field(note, 'Translation'))}" if kind.words else ""))
            print("   " + _("Nothing to correct. {reason}").format(
                reason=console.clean(reason)))
            for line in refused:
                print("   ! " + line)
            if missed:
                print("   !! " + _("The AI missed it: kanji without furigana - "
                                   "{missed}.").format(missed=missed))
            # A card with nothing to correct may still be one to delete.
            choice = choose([("r", _("remove the flag")),
                             ("d", _("delete the note")),
                             ("k", _("keep the flag"))])
            if choice == "d":
                if marks.offer_manual_deletion(note):
                    tally.changed += 1
                continue
            if choice == "r":
                unmark(card["cardId"])
                tally.cleared += 1
            continue

        # The passage is read only when a shared field changes.
        passage = (marks.passage_of(note, kind, notes_by_id)
                   if any(name in kind.shared for name in fields) else [])
        if not auto:
            marks.show_diff(note, fields, add_tags, remove_tags, reason,
                            reached=len(sharing(note, kind, fields, passage)),
                            refused=refused)
            # A reflex Enter skips the card; the EOF of a script still stops the
            # pass, which is why "quit" stays last.
            accept = choose([("a", _("accept")), ("d", _("delete the note")),
                             ("s", _("skip")), ("q", _("quit"))], start="s")
            if accept == "q":
                raise Quit
            if accept == "d":
                if marks.offer_manual_deletion(note):
                    tally.changed += 1
                continue
            if accept == "s":
                continue

        try:
            reached = marks.apply_to_passage(note, kind, fields, add_tags, remove_tags, passage)
            # Counted before the flag goes: the change is in Anki even when the
            # flag is refused.
            tally.changed += 1 + reached
            unmark(card["cardId"])
            tally.cleared += 1
            if auto:
                summary = _change_summary(fields, add_tags, remove_tags)
                if reached:
                    summary += " (" + marks.passage_summary(reached) + ")"
                auto_line("✓", note, summary)
            else:
                print("   " + _("applied, flag removed"))
        except (ConnectionError, EditorOpen):
            raise  # Anki closed or an editor open: every following card would fail the same way
        except Exception as exc:
            console.failed(_("Applying failed: {error}").format(error=console.reason(exc)))
