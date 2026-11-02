"""The `duplicate` action on the cards that are not words.

The vocabulary keeps its pass in `flag_pass`. Two grammar cards are duplicates when
they ask the same question, or confusable when the hints of one lead as well to
the form the other hides (ながら / つつ under one "while"): those are told apart
by their hints. A reading or listening card is duplicated by its passage, in the
deck twice, or by another question of that passage asking the same thing.

Nothing is deleted without the user, `--yes` included: automatic mode tells
apart and renews, and leaves a deletion to a run by hand, flag kept. What looks
alike, and the model's verdict, is the library's (`maintenance.duplicates`).
"""

from __future__ import annotations

from kotogen import console
from kotogen.ai_client import AIAuthError, AIClient
from kotogen.anki.maintain.flag_pass import _forget_notes, _resolve_flag_only, unmark
from kotogen.anki.maintain.marks import (
    ai_failed,
    apply_changes,
    apply_to_passage,
    delete_notes,
    passage_of,
    show_diff,
    tally,
)
from kotogen.exporter import ask_choice, choose, short
from kotogen.i18n import _, convention, counted, listed, quoted
from kotogen.maintenance import kinds
from kotogen.maintenance.duplicates import (
    CONFUSABLE,
    DUPLICATE,
    _telling,
    grammar_candidates,
    judge_grammar,
    same_questions,
    twin_passages,
)
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.review import (
    _field,
    _normalise_proposal,
    auto_line,
    card_name,
    propose_changes,
    sharing,
)


def process(client: AIClient, card_id: int, note: dict, all_notes: list[dict],
            kind: CardKind, auto: bool, known: dict[int, dict]) -> tuple[int, int]:
    """Handles one turquoise card of a kind that is not words.

    Hands back (changes applied, flags removed), as the other passes do.
    """
    start = tally.start()
    if kind is kinds.GRAMMAR:
        _grammar(client, card_id, note, all_notes, auto)
    else:
        _passage(client, card_id, note, all_notes, kind, auto, known)
    return tally.since(start)


def _settle(card_id: int, note: dict, auto: bool, acted: bool, pending: bool,
            what: str) -> None:
    """The end of a card's examination: its flag, and the one line that says so.

    A deletion left pending keeps the flag, for the run that decides it. Any
    other end removes it, asking first only by hand when nothing was done.
    """
    if pending:
        if auto:
            auto_line("!", note, _("deletion to be decided by hand, flag kept"))
        return
    if acted or auto:
        unmark(card_id)
        tally.cleared += 1
        if auto and not acted:
            auto_line("=", note, what)
        return
    console.space()
    _resolve_flag_only(card_id)


def _delete(note: dict, label: str) -> bool:
    """A deletion, confirmed a second time, as everywhere in `maintain`."""
    if ask_choice(_("Delete {label} (note {note}) for good? [y] yes  [n] no").format(
            label=label, note=note["id"]), "yn") != "y":
        print("   " + _("deletion cancelled"))
        return False
    delete_notes([note["id"]])
    tally.changed += 1
    print("   " + _("note deleted"))
    return True


def _grammar(client: AIClient, card_id: int, note: dict, all_notes: list[dict],
             auto: bool) -> None:
    candidates = grammar_candidates(note, all_notes)
    if not auto:
        print("   " + _("Flagged card: {card}").format(card=card_name(note)))
    try:
        verdicts = judge_grammar(client, note, candidates) if candidates else {}
    except AIAuthError:
        raise
    except Exception as exc:
        ai_failed(exc, note if auto else None)
        return

    acted = pending = False
    gone: list[int] = []
    for index, (other, reasons) in enumerate(candidates):
        verdict = verdicts.get(index, {})
        kind_of = verdict.get("verdict")
        why = (console.clean(str(verdict.get("reason", ""))).strip()
               or listed(_(r) for r in reasons))
        if kind_of == DUPLICATE:
            if auto:
                pending = True
                continue
            console.space()
            print("   ── " + _("potential DUPLICATE") + " ──────────")
            print("   " + _("Card 1 (flagged): {card}").format(card=card_name(note)))
            print("   " + _("Card 2: {card}").format(card=card_name(other)))
            print("   " + _("AI verdict: {verdict}").format(verdict=why))
            choice = choose([("1", _("keep card 1")), ("2", _("keep card 2")),
                             ("n", _("keep both"))])
            if choice == "1" and _delete(other, _("card 2")):
                gone.append(other["id"])
                acted = True
            elif choice == "2" and _delete(note, _("card 1 (flagged)")):
                _forget_notes(all_notes, [*gone, note["id"]])
                return   # the flag went with the note
        elif kind_of == CONFUSABLE:
            mine, theirs = _telling(note, verdict.get("card")), _telling(other, verdict.get("other"))
            if not mine and not theirs:
                continue
            if not auto:
                console.space()
                print("   ── " + _("told apart by their hints") + " ──────────")
                print("   " + _("Distinction proposed: {reason}").format(reason=why))
                colon = convention("colon", ": ")
                for label, target, changes in ((_("Card 1"), note, mine),
                                               (_("Card 2"), other, theirs)):
                    print(f"   {label}{colon}{card_name(target)}")
                    for name, new in changes.items():
                        print(f"      {name}{colon}{short(_field(target, name)) or _('(empty)')}"
                              f"  →  {short(new)}")
                if ask_choice(_("Apply? [y] yes  [n] cancel"), "yn") != "y":
                    continue
            for target, changes in ((note, mine), (other, theirs)):
                if changes:
                    apply_changes(target["id"], changes, [], [])
                    tally.changed += 1
            acted = True
            if auto:
                auto_line("✓", note, _("told apart from {names}").format(
                    names=card_name(other)))
    _forget_notes(all_notes, gone)
    if not auto and not acted and not pending:
        print("   → " + (_("No duplicate confirmed by the AI.") if candidates
                         else _("No potential duplicate found in the deck.")))
    _settle(card_id, note, auto, acted, pending,
            _("no duplicate confirmed, flag removed"))


def _passage(client: AIClient, card_id: int, note: dict, all_notes: list[dict],
             kind: CardKind, auto: bool, known: dict[int, dict]) -> None:
    acted = pending = False
    if not auto:
        print("   " + _("Flagged card: {card}").format(card=card_name(note)))

    # The passage first: a question duplicated inside a passage that is itself
    # in the deck twice would be settled for nothing.
    for twin in twin_passages(note, all_notes, kind).values():
        if auto:
            pending = True
            continue
        console.space()
        print("   ── " + counted(len(twin),
                                 "the same text is in the deck twice: {count} card "
                                 "elsewhere",
                                 "the same text is in the deck twice: {count} cards "
                                 "elsewhere").format(count=len(twin)) + " ──────────")
        for other in twin[:5]:
            print(f"      - {card_name(other)}")
        choice = choose([("1", _("keep this passage")),
                         ("2", _("keep the other one")), ("n", _("keep both"))])
        if choice == "n":
            continue
        doomed = twin if choice == "1" else [note, *passage_of(note, kind, known)]
        ids = [n["id"] for n in doomed]
        if ask_choice(counted(len(ids),
                              "Delete this note for good? [y] yes  [n] no",
                              "Delete these {count} notes for good? [y] yes  [n] no").format(
                           count=len(ids)), "yn") != "y":
            print("   " + _("deletion cancelled"))
            continue
        delete_notes(ids)
        tally.changed += len(ids)
        _forget_notes(all_notes, ids)
        print("   " + counted(len(ids),
                              "{count} note deleted",
                              "{count} notes deleted").format(count=len(ids)))
        acted = True
        if choice == "2":
            return   # the flagged card went with its passage

    done, held, gone = _same_questions(client, note, kind, auto, known)
    if gone:
        return   # the flag went with the note
    _settle(card_id, note, auto, acted or done, pending or held,
            _("no duplicate confirmed, flag removed"))


def _same_questions(client: AIClient, note: dict, kind: CardKind, auto: bool,
                    known: dict[int, dict]) -> tuple[bool, bool, bool]:
    """Hands back (something done, the flag to keep, the flagged card deleted).

    The flag is kept when the model could not answer: the card was not examined.
    """
    others = passage_of(note, kind, known)
    if not others:
        return False, False, False
    try:
        doubles = same_questions(client, note, kind, others)
    except AIAuthError:
        raise
    except Exception as exc:
        ai_failed(exc, note if auto else None)
        return False, True, False
    if not doubles:
        if not auto:
            print("   → " + _("No other question of the passage asks the same thing."))
        return False, False, False

    if auto:
        # Renewing the flagged question is a rewrite, which `--yes` makes;
        # deleting one of the two would wait for the user, flag kept.
        renewed = _renew(client, note, kind, auto=True, known=known)
        return bool(renewed), not renewed, False

    for other, reason in doubles:
        console.space()
        print("   ── " + _("the same question twice") + " ──────────")
        print("   " + _("Card 1 (flagged): {card}").format(card=card_name(note)))
        print("   " + _("Card 2: {card}").format(card=card_name(other)))
        if reason:
            print("   " + _("AI verdict: {verdict}").format(verdict=console.clean(reason)))
        choice = choose([("r", _("ask card 1 something else")),
                         ("1", _("keep card 1")), ("2", _("keep card 2")),
                         ("n", _("keep both"))])
        if choice == "r":
            renewed = _renew(client, note, kind, auto=False, known=known)
            if renewed is None:
                return False, True, False
            if renewed:
                return True, False, False
            continue
        if choice == "1" and _delete(other, _("card 2")):
            return True, False, False
        if choice == "2" and _delete(note, _("card 1 (flagged)")):
            return True, False, True
    return False, False, False


def _renew(client: AIClient, note: dict, kind: CardKind, auto: bool,
           known: dict[int, dict]) -> bool | None:
    """A new question on the same passage, through the `renew` action of the kind.

    True once written, False when nothing was proposed or it was declined, None
    when the model failed.
    """
    try:
        proposal = propose_changes(client, "renew", note, kind)
    except AIAuthError:
        raise
    except Exception as exc:
        ai_failed(exc, note if auto else None)
        return None
    refused: list[str] = []
    fields, add, remove, reason = _normalise_proposal(note, proposal, kind, refused)
    if not fields:
        if not auto:
            print("   → " + _("The AI proposed no new question."))
        return False
    passage = (passage_of(note, kind, known)
               if any(name in kind.shared for name in fields) else [])
    if not auto:
        show_diff(note, fields, add, remove, reason,
                  reached=len(sharing(note, kind, fields, passage)), refused=refused)
        if ask_choice(_("Apply? [y] yes  [n] cancel"), "yn") != "y":
            return False
    # The card, and the cards of its passage the shared fields reached.
    tally.changed += 1 + apply_to_passage(note, kind, fields, add, remove, passage)
    if auto:
        auto_line("✓", note, _("asked something else: {question}").format(
            question=quoted(short(fields.get("Question", "")))))
    return True
