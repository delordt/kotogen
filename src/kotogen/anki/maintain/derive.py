"""The `derive` action: the new cards a flagged card calls for.

The flagged card stays as it is. The words or rules the model proposes for it
(`maintenance.derive`), less those the deck holds, go through the generation of
`kotogen vocab` or `kotogen grammar`, in one batch for the whole pass. `--yes`
creates them all: a created card is undone more easily than a deleted one.

The flag comes off once Anki has taken the cards, and when every card was
turned down, which a new run would only pay to do again. A failure leaves it, a
call's or the send's.
"""

from __future__ import annotations

from kotogen import console, memory, settings
from kotogen.ai_client import AIAuthError, AIClient
from kotogen.anki.maintain.flag_pass import _resolve_flag_only, _sense, unmark
from kotogen.anki.maintain.marks import ai_failed, tally
from kotogen.exporter import ask_choice
from kotogen.generators import grammar, vocab
from kotogen.i18n import _, convention
from kotogen.maintenance import kinds
from kotogen.maintenance.derive import GRAMMAR, VOCAB, Held, Proposal, describe, fresh, propose
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.review import _field, _passage_stem, auto_line, card_name

# The cards a derived rule gets: enough to start it, `kotogen grammar` being
# there to lengthen its series.
RULE_CARDS = 3


def pick(proposals: list[Proposal]) -> list[Proposal]:
    """One by one, the ones to create. Refusing is the last choice, hence what an
    EOF keeps: nothing is generated, and paid for, unasked."""
    chosen = []
    for proposal in proposals:
        if ask_choice(_("Create {word}? [y] yes  [n] no").format(
                word=describe(proposal)), "yn") == "y":
            chosen.append(proposal)
    return chosen


def _destination(proposal: Proposal, kind: CardKind, card_deck: str) -> tuple[str, str]:
    """(pipeline, deck) of a derived card, "" for the deck of its command.

    The flagged card's deck when both are of one kind, else its command's: a
    word drawn from a reading text goes where `kotogen vocab` puts it.
    """
    same = ((proposal.target == VOCAB and kind is kinds.VOCAB)
            or (proposal.target == GRAMMAR and kind is kinds.GRAMMAR))
    return proposal.target, card_deck if same else ""


def _generate(client: AIClient, target: str, words: list[str], deck: str) -> bool | None:
    """Sends one batch through its pipeline. True when Anki took it, False when
    something failed, None when every card was turned down."""
    if target == GRAMMAR:
        return grammar.generate_into(
            client, words, deck or settings.text("KOTOGEN_GRAMMAR_DECK"),
            kinds.GRAMMAR.notetype, RULE_CARDS)
    return vocab.generate_into(client, words, deck or settings.text("KOTOGEN_VOCAB_DECK"),
                               kinds.VOCAB.notetype)


def _settle_flag(card_id: int, stem: str, flag_kept: set[str]) -> None:
    """Asks whether the flag comes off. A passage whose first card keeps its flag
    goes into `flag_kept`, for its other cards to keep theirs."""
    if not _resolve_flag_only(card_id) and stem:
        flag_kept.add(stem)


def process(client: AIClient, cards: list[dict], notes_by_id: dict[int, dict],
            kind: CardKind, auto: bool) -> tuple[int, int]:
    """Handles every card of the flag. Hands back (cards changed, flags removed).

    The first figure is always 0: the flagged card is left as it is, and the
    generation has already counted the cards it created.
    """
    start = tally.start()
    known = Held(memory.known())
    words_taken: set[str] = set()
    # (pipeline, deck) -> (what to generate, the cards whose flag it settles)
    pending: dict[tuple[str, str], tuple[list[str], list[int]]] = {}
    # passage -> the batches its first card went into; its other flagged cards
    # follow them rather than asking the text again, and keep their flag when
    # the first card, with no batch, kept its own
    passages: dict[str, list[tuple[str, str]]] = {}
    flag_kept: set[str] = set()
    # Passages whose first card the model failed on: their other cards wait for
    # the next run rather than pay for the same call again.
    failed_passages: set[str] = set()

    for card in cards:
        note = notes_by_id.get(card["note"])
        if note is None:
            continue
        stem = _passage_stem(note) if kind.shared else ""
        if stem and stem in failed_passages:
            continue
        if stem and stem in passages:
            batches = passages[stem]
            for key in batches:
                pending[key][1].append(card["cardId"])
            if not batches and stem not in flag_kept:
                unmark(card["cardId"])
                tally.cleared += 1
            if auto:
                auto_line("=", note, _("derived with its passage"))
            continue

        if not auto:
            console.space()
            print("── " + _("note {id}").format(id=note['id']) + " ──────────────────────────────────")
            if kind is kinds.VOCAB:
                print("   " + _("Expression: {expression} - {translation}").format(
                    expression=_field(note, "Expression"), translation=_sense(note)))
            else:
                print(f"   {kind.label}{convention('colon', ': ')}{card_name(note)}")

        try:
            proposals = propose(client, note, kind)
        except AIAuthError:
            raise  # key/quota: the following cards would all fail the same way
        except Exception as exc:
            ai_failed(exc, note if auto else None)
            if stem:
                failed_passages.add(stem)
            continue

        new, already = fresh(proposals, known, words_taken)
        if already and not auto:
            print("   " + _("already in the deck: {words}").format(
                words="、".join(p.word for p in already)))

        chosen = [] if not new else new if auto else pick(new)
        if stem:
            passages[stem] = []
        if not new:
            if auto:
                unmark(card["cardId"])
                tally.cleared += 1
                auto_line("=", note, _("nothing new to derive, flag removed"))
            else:
                print("   " + _("Nothing new to derive."))
                _settle_flag(card["cardId"], stem, flag_kept)
            continue
        if not chosen:
            _settle_flag(card["cardId"], stem, flag_kept)
            continue
        if auto:
            auto_line("+", note, "、".join(p.word for p in chosen))
        words_taken.update(p.word for p in chosen)
        for proposal in chosen:
            key = _destination(proposal, kind, card.get("deckName", ""))
            words, flagged = pending.setdefault(key, ([], []))
            words.append(proposal.word)
            if card["cardId"] not in flagged:
                flagged.append(card["cardId"])
            if stem and key not in passages[stem]:
                passages[stem].append(key)

    # A card whose proposals went into two batches keeps its flag until both
    # are settled.
    failed: set[int] = set()
    settled: list[int] = []
    for (target, deck), (words, flagged) in pending.items():
        console.space()
        sent = _generate(client, target, words, deck)
        if sent is None:
            print(_("every derived card was turned down, the flags come off"))
        elif not sent:
            print("! " + _("the derived cards did not reach Anki, the flags stay"))
            failed.update(flagged)
            continue
        settled += [c for c in flagged if c not in settled]
    for card_id in settled:
        if card_id not in failed:
            unmark(card_id)
            tally.cleared += 1
    return tally.since(start)
