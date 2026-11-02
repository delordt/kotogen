"""Leech mode: clears out the false leeches and reworks the real ones.

A leech already mature (`--mature-ivl`, 21 days by default) is a false one: its
tag comes off and it is unsuspended, in bulk. A real one is rewritten simpler by
the model, then reset (unsuspended, forgotten, tag removed). The interval being
only a proxy, a real leech halfway to maturity may be kept as mastered (`[m]`),
a judgement automatic mode never makes. The proposals are `maintenance.leech`'s.
"""

from __future__ import annotations

from kotogen import console
from kotogen.ai_client import AIAuthError, AIClient
from kotogen.anki.connect import EditorOpen, request as anki
from kotogen.anki.deck import card as as_card
from kotogen.anki.maintain.lone_kanji import DELETED, KEPT, offer_category_fix, offer_lone_kanji
from kotogen.anki.maintain.marks import (
    DETAIL,
    Quit,
    ai_failed,
    apply_to_passage,
    offer_manual_deletion,
    passage_of,
    tally,
)
from kotogen.exporter import ask_choice, choose, short
from kotogen.i18n import _, convention, counted, quoted
from kotogen.maintenance import kinds
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.leech import _clean_kanji_help, _propose_simpler, _several_kanji
from kotogen.maintenance.review import (
    _changed_fields,
    _field,
    auto_line,
    card_name,
    propose_changes,
    read_category,
)

# ── Queries ───────────────────────────────────────────────────────────────────

def _find(notetype: str, tag: str, ivl_clause: str) -> list[int]:
    return anki("findCards", query=f'"note:{notetype}" tag:{tag} {ivl_clause}') or []


# ── False leeches (mastered) ──────────────────────────────────────────────────

def _process_false(false_ids: list[int], tag: str, mature_ivl: int, auto: bool,
                   kind: CardKind = kinds.VOCAB) -> int:
    """Removes the leech tag + unsuspends, in bulk after one confirmation."""
    console.space()
    print(_("False leeches (mastered, ivl >= {mature}): {count}").format(
        mature=mature_ivl, count=len(false_ids))
        + (_("   [automatic]") if auto else ""))
    # The preview only serves a decision, which automatic mode has taken.
    if not auto:
        for info in anki("cardsInfo", cards=false_ids[:5]):
            c = as_card({"noteId": info["note"], "fields": info.get("fields")})
            sense = (f" - {short(_field(c, 'Translation').replace('<br>', ' / '))}"
                     if kind.words else "")
            print(f"   - {card_name(c)}{sense}")
        if len(false_ids) > 5:
            print("   " + _("... and {count} more").format(count=len(false_ids) - 5))

        if ask_choice(
            counted(
                len(false_ids),
                "Remove the {tag} tag + unsuspend that card? [y] yes  [n] no",
                "Remove the {tag} tag + unsuspend those {count} cards? [y] yes  [n] no"
            ).format(
                tag=quoted(tag), count=len(false_ids)), "yn"
        ) != "y":
            print("   " + _("skipped"))
            return 0

    note_ids = anki("cardsToNotes", cards=false_ids)
    anki("removeTags", notes=note_ids, tags=tag)
    anki("unsuspend", cards=false_ids)
    tally.cleaned += len(false_ids)
    print("   " + counted(len(false_ids),
                          "{count} card cleared (tag removed, unsuspended)",
                          "{count} cards cleared (tag removed, unsuspended)").format(
        count=len(false_ids)))
    return len(false_ids)


def _show_rework(card: dict, fields: dict, reason: str, kind: CardKind,
                 refused: list[str] | None = None) -> None:
    if reason:
        print("   " + _("Why simpler: {reason}").format(reason=console.clean(reason)))
    empty = _("(empty)")
    colon = convention("colon", ": ")
    for line in refused or []:
        print("   ! " + line)
    for name in kind.fields:
        if name in fields:
            print(f"   {name}{colon}{short(_field(card, name)) or empty}"
                  f"  →  {short(fields[name]) or empty}")
        else:
            cur = _field(card, name)
            if cur:
                print(f"   {name}{colon}{short(cur)}  " + _("(unchanged)"))


def _numbers(card: dict) -> str:
    """`ivl 18, 2 lapses`: what the option of keeping the card leans on.

    `ivl` untranslated: it is the word of the Anki search (`prop:ivl`), as in the
    survey.
    """
    lapses = card.get("lapses", 0)
    return _("ivl {ivl}, {lapses} {word}").format(
        ivl=card.get("interval", 0), lapses=lapses,
        word=console.plural(lapses, "lapse"))


def _rework_choices(offer_kanji: bool, offer_keeping: bool) -> list[tuple[str, str]]:
    """The menu of a rework, as the options `choose` lays out.

    `k` comes with kanji help, `m` when the interval makes the card worth keeping.
    `m` never goes last: `choose` takes the last option on EOF, which must be `q`.
    """
    options = ([("a", _("accept")), ("k", _("accept + kanji help"))] if offer_kanji
               else [("a", _("accept (rewrite + reset)"))])
    if offer_keeping:
        options.append(("m", _("mastered")))
    return options + [("d", _("delete the note")), ("s", _("skip")), ("q", _("quit"))]


def _keep_as_it_is(card: dict, tag: str) -> None:
    """The card is known and the threshold had it wrong: the tag comes off and
    nothing else moves - no rewrite, no reset, the interval stands.

    Counted with the false leeches (see `process_leeches`). A mistake costs
    nothing: Anki tags the card again at its next lapse.
    """
    anki("removeTags", notes=[card["note"]], tags=tag)
    anki("unsuspend", cards=[card["cardId"]])
    tally.cleaned += 1
    print("   " + _("kept: tag removed, unsuspended"))


def _reset(card: dict, tag: str) -> None:
    """What puts a real leech back into the reviews: the tag off, unsuspended,
    and forgotten (interval, reps and ease reset), to be learnt again."""
    anki("removeTags", notes=[card["note"]], tags=tag)
    anki("unsuspend", cards=[card["cardId"]])
    anki("forgetCards", cards=[card["cardId"]])
    tally.reworked += 1


def _process_true(true_ids: list[int], tag: str, client: AIClient, mature_ivl: int,
                  auto: bool, kind: CardKind = kinds.VOCAB) -> tuple[int, int]:
    """Rewrites each real leech (with confirmation), then reset + unsuspend + tag removal.

    Hands back (kept as they stood, reworked). A word goes through
    `leech_simplify`, which can add kanji help; another kind through the
    `simplify` action of its own instruction, as the orange flag does.
    """
    console.space()
    print(_("Real leeches (ivl < {mature}): {count}").format(
        mature=mature_ivl, count=len(true_ids))
        + (_("   [automatic]") if auto else ""))
    cards = anki("cardsInfo", cards=true_ids)
    start = tally.start()
    # Half the maturity threshold, so both move with `--mature-ivl`; a day at
    # least, so a threshold of 1 does not offer to keep a card never remembered.
    keep_ivl = max(1, mature_ivl // 2)

    # cardsInfo hands back no tags; one call brings them all, so that a card
    # tagged `Category::Kept` is not reported again on every pass.
    tags_by_note = {n["noteId"]: n.get("tags", [])
                    for n in (anki("notesInfo", notes=list({c["note"] for c in cards})) or [])}

    for card in cards:
        # `note` is the card as the library reads one; `card` stays what Anki
        # says of it, its interval and lapses.
        note = as_card({"noteId": card["note"], "tags": tags_by_note.get(card["note"], []),
                        "fields": card["fields"]})
        # Halfway to maturity the sorting is least sure: keeping the card as it
        # stands is offered, but never in automatic mode, which rewrites.
        offer_keeping = not auto and card.get("interval", 0) >= keep_ivl
        if not auto:
            console.space()
            print("── " + _("note {id}").format(id=card['note']) + " ──────────────────────────────────")
            # The figures are shown only where they back a choice (`[m]`).
            numbers = f"  ({_numbers(card)})" if offer_keeping else ""
            if kind.words:
                print("   " + _("Card: {expression} - {translation}").format(
                    expression=_field(note, "Expression"),
                    translation=short(_field(note, "Translation").replace("<br>", " / ")))
                    + numbers)
            else:
                print(f"   {kind.label}{convention('colon', ': ')}"
                      f"{card_name(note)}{numbers}")

        # A lone kanji that is not a word often explains the leech: moving it to
        # the kanji deck, or deleting it, is offered before any simplification.
        outcome = offer_lone_kanji(client, note, auto) if kind.words else KEPT
        if outcome == DELETED:
            tally.changed += 1
        if outcome != KEPT:
            continue
        try:
            proposal = (_propose_simpler(client, note) if kind.words
                        else propose_changes(client, "simplify", note, kind))
        except AIAuthError:
            raise  # key/quota: the following leeches would all fail the same way
        except Exception as exc:
            ai_failed(exc, note if auto else None)
            continue

        # A card that is not vocabulary often explains the failure; the verdict
        # comes from the answer just paid for. Anything but "kept" stops here, and
        # the leech is reported again on the run that decides it.
        verdict = read_category(note, proposal) if kind.words else None
        outcome = offer_category_fix(note, verdict, auto) if verdict else KEPT
        if outcome == DELETED:
            tally.changed += 1
        if outcome != KEPT:
            continue

        refused: list[str] = []
        fields = _changed_fields(note, proposal.get("fields") or {}, kind, refused)
        # A rework never empties a field: those the AI would clear stay unchanged.
        fields = {k: v for k, v in fields.items() if str(v).strip()}
        kanji_help = _clean_kanji_help(str(proposal.get("kanji_help", "")).strip())
        offer_kanji = kind.words and kanji_help and _several_kanji(_field(note, "Expression"))

        if not fields and not offer_kanji:
            if auto:
                auto_line("=", note, _("no simplification proposed"))
                continue
            # Nothing to simplify: `[r]` resets the card without a rewrite, and
            # `[m]` and `[d]` are offered too, where `[s]` alone would report the
            # card at every run.
            print("   → " + _("The AI proposed no simplification."))
            choice = choose(([("m", _("mastered"))] if offer_keeping else [])
                            + [("r", _("put back as it is (reset)")),
                               ("d", _("delete the note")), ("s", _("skip"))])
            if choice == "m":
                _keep_as_it_is(card, tag)
            elif choice == "r":
                _reset(card, tag)
                print("   " + _("put back: unsuspended, reset, tag removed"))
            elif choice == "d" and offer_manual_deletion(note):
                tally.changed += 1
            continue

        if auto:
            accept = "k" if offer_kanji else "a"
        else:
            _show_rework(note, fields, str(proposal.get("reason", "")).strip(), kind,
                         refused)
            if offer_kanji:
                print("   " + _("Kanji help (option [k]):"))
                for line in kanji_help.split("<br>"):
                    print(f"      {console.clean(line).strip()}")
            # A reflex Enter skips the card; the EOF of a script still stops the
            # pass, which is why "quit" stays last.
            accept = choose(_rework_choices(offer_kanji, offer_keeping), start="s")
            if accept == "q":
                raise Quit
            if accept == "m":
                _keep_as_it_is(card, tag)
                continue
            if accept == "d":
                if offer_manual_deletion(note):
                    tally.changed += 1
                continue
            if accept == "s":
                continue

        final = dict(fields)
        if accept == "k":
            base_notes = fields.get("Notes", _field(note, "Notes"))
            final["Notes"] = f"{base_notes}<br>{kanji_help}" if base_notes else kanji_help

        try:
            if final:
                # The rework is the card's own; a shared field it touched is the
                # passage's, and the passage follows (see marks.apply_to_passage).
                passage = (passage_of(note, kind)
                           if any(name in kind.shared for name in final) else [])
                # The card itself is counted as reworked (`_reset`); the
                # passage's cards it reached, as changed.
                tally.changed += apply_to_passage(note, kind, final, [], [], passage)
            _reset(card, tag)
            extra = _(" + kanji help") if accept == "k" else ""
            if auto:
                auto_line("✓", note, _("rewritten{extra}, reset, tag removed").format(extra=extra))
            else:
                print("   " + _("rewritten{extra}, unsuspended, reset, tag removed").format(
                    extra=extra))
        except (ConnectionError, EditorOpen):
            raise  # Anki closed or an editor open: every following leech would fail the same way
        except Exception as exc:
            console.failed(_("Applying failed: {error}").format(error=console.reason(exc)))

    return tally.cleaned - start.cleaned, tally.reworked - start.reworked


# ── What the "maintain" mode is offered ───────────────────────────────────────
# One maintenance task among others (see review.run_maintain): the search, the
# survey detail and the processing, with no runner of its own.

def find_leeches(notetype: str, tag: str, mature: int) -> tuple[list[int], list[int]]:
    """Hands back (false leeches, real leeches) by the Anki maturity interval."""
    false_ids = _find(notetype, tag, f"prop:ivl>={mature}")
    true_ids = _find(notetype, tag, f"prop:ivl<{mature}")
    return false_ids, true_ids


def leech_detail(false_ids: list[int], true_ids: list[int], tag: str, mature: int) -> list[str]:
    """What the leech count covers, under its line of the survey.

    The one target whose figure adds up two unrelated jobs, untagging in bulk and
    rewriting one by one; an empty half gets no line.
    """
    lines = []
    if false_ids:
        wording = counted(
            len(false_ids),
            "{count} mastered card (ivl >= {mature}): the {tag} tag comes off in bulk",
            "{count} mastered cards (ivl >= {mature}): the {tag} tag comes off in bulk"
        )
        lines.append(DETAIL + wording.format(
            count=len(false_ids), mature=mature, tag=quoted(tag)))
    if true_ids:
        lines.append(DETAIL + _("{count} to rework (ivl < {mature}): rewriting then reset").format(
            count=len(true_ids), mature=mature))
    return lines


def process_leeches(false_ids: list[int], true_ids: list[int], args,
                    client: AIClient | None = None, auto: bool = False,
                    kind: CardKind = kinds.VOCAB) -> tuple[int, int]:
    """Clears the false leeches and reworks the real ones. Hands back (cleared, reworked).

    Without `client`, one is created only for real leeches, the false ones needing
    no AI. `auto` accepts every proposal, the reset of real leeches included.
    """
    cleaned = reworked = 0
    if false_ids:
        cleaned = _process_false(false_ids, args.tag, args.mature_ivl, auto, kind)
    if true_ids:
        if client is None:
            client = AIClient(provider=args.provider, model=args.model)
        # A leech kept as it stood is a false leech the interval missed, and is
        # counted with them.
        kept, reworked = _process_true(true_ids, args.tag, client, args.mature_ivl,
                                       auto, kind)
        cleaned += kept
    return cleaned, reworked
