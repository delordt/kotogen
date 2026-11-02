"""The "maintain" mode: assisted maintenance of an existing Anki deck.

For each target (a flag, the star, `leech`; `--only` narrows them), selects the
cards, asks `kotogen.maintenance` for a change and, once it is accepted, applies
it and removes the mark. First, a lone kanji that is not a word (see
`kanji_word`) is offered a move to the kanji deck or deletion, and a card that
is not vocabulary is reported, your decision kept in a `Category::…` tag.
Nothing is deleted without confirmation, nor ever automatically.

Each flag triggers an action, which answers one question about the card:

  1 red       error      is it WRONG? meaning, answer, translation, wrong tags
  2 orange    simplify   is it too HARD? right, but heavy, twisted or ambiguous
  3 green     enrich     is it INCOMPLETE? example, note, context, missing tags
  4 blue      text       is the Japanese badly WRITTEN? furigana, typos, spacing
  5 pink      derive     what NEW cards does it call for? (see derive)
  6 turquoise duplicate  does it exist ALREADY? delete the card too many, or tell
                         apart every card of the same translation
  7 purple    audio      is it badly HEARD? the kana reading the TTS speaks
  leech                  clears the false leeches, reworks the real ones (see leech)

`renew` (a new example for a card known by its sentence) has no flag by default.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from kotogen import console
from kotogen.ai_client import AIClient
from kotogen.anki.maintain import flag_pass, leech as leech_gen, lone_kanji, marks
from kotogen.anki.maintain.marks import ANKI_FLAGS, FLAG_BY_NAME, FLAG_COLOURS, target_lines
from kotogen.i18n import _, counted, listed, quoted, sentence
from kotogen.maintenance import kinds
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.review import ACTIONS, CATEGORY_TAG_TODO

# ── Selecting the tasks ───────────────────────────────────────────────────────

def _parse_targets(tokens: list[str], option: str) -> tuple[set[int], bool]:
    """Translates a list of targets into (marks, leech).

    Accepts mark names, flag numbers 1-7, action names and `leech`. A target that
    triggers nothing stops the run: handling nothing silently would read as a
    clean deck.
    """
    actions = marks.flag_actions()
    by_action = {action: mark for mark, action in actions.items() if action}
    flags: set[int] = set()
    do_leech = False
    for tok in tokens:
        t = tok.strip().lower()
        if t == "leech":
            if not marks.handles_leeches():
                sys.exit(_("{option}: {token} triggers no action - give it one in the "
                           "menu (Corrections > Marks).").format(
                               option=option, token=quoted(tok)))
            do_leech = True
            continue
        if t in FLAG_BY_NAME:
            mark = FLAG_BY_NAME[t]
        elif t.isdigit() and int(t) in ANKI_FLAGS:
            mark = int(t)
        elif t in ACTIONS:
            if t not in by_action:
                sys.exit(_("{option}: no flag triggers {action} - give it one in the "
                           "menu (Corrections > Marks).").format(
                               option=option, action=quoted(t)))
            mark = by_action[t]
        else:
            sys.exit(_(
                "Unknown selector for {option}: {token}. Expected: a flag (red orange "
                "green blue pink turquoise purple, or 1-7), star, an action ({actions}), "
                "and/or leech."
            ).format(option=option, token=quoted(tok), actions=" ".join(ACTIONS)))
        if not actions[mark]:
            sys.exit(_("{option}: {token} triggers no action - give it one in the "
                       "menu (Corrections > Marks).").format(
                           option=option, token=quoted(tok)))
        flags.add(mark)
    return flags, do_leech


def _parse_selection(only: list[str] | None) -> tuple[list[int], bool]:
    """Translates --only into (marks, handle the leeches). Without --only: every
    mark that triggers an action, and the leeches unless they are left alone."""
    if not only:
        return marks.active_marks(), marks.handles_leeches()
    flags, do_leech = _parse_targets(only, "--only")
    return sorted(flags), do_leech


def _parse_auto(yes: list[str] | None, flags: list[int], do_leech: bool) -> tuple[set[int], bool]:
    """Translates --yes into (auto flags, auto leech), restricted to the targets handled.

    Without `--yes`, nothing; `--yes` alone, every target handled; `--yes red
    leech`, those two.
    """
    if yes is None:
        return set(), False
    if not yes:
        return set(flags), do_leech
    auto_flags, auto_leech = _parse_targets(yes, "--yes")
    return auto_flags & set(flags), auto_leech and do_leech


# ── The survey (`--scan`) ─────────────────────────────────────────────────────

@dataclass
class Survey:
    """What the deck carries, target by target and kind by kind.

    One reading of Anki serves the survey, the handling and the dialogue, so that
    their figures agree.
    """

    kinds: list[CardKind]
    # mark -> command -> cards whose action the kind knows how to take
    flags: dict[int, dict[str, int]] = field(default_factory=dict)
    # command -> (false leeches, real leeches), for the kinds that rework them
    leeches: dict[str, tuple[list[int], list[int]]] = field(default_factory=dict)
    # (note type, target, cards): what carries a target nothing handles for its kind
    left: list[tuple[str, str, int]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (sum(sum(by_kind.values()) for by_kind in self.flags.values())
                + sum(len(f) + len(r) for f, r in self.leeches.values()))

    def busy(self) -> list[CardKind]:
        """The kinds with something to handle, in their own order."""
        return [kind for kind in self.kinds
                if any(by_kind.get(kind.command) for by_kind in self.flags.values())
                or any(self.leeches.get(kind.command, ((), ())))]

    def count(self, target: str, kind: CardKind) -> int:
        if target == "leech":
            false_ids, true_ids = self.leeches.get(kind.command, ([], []))
            return len(false_ids) + len(true_ids)
        return self.flags.get(FLAG_BY_NAME[target], {}).get(kind.command, 0)

    def all_leeches(self) -> tuple[list[int], list[int]]:
        false_ids = [c for f, _r in self.leeches.values() for c in f]
        true_ids = [c for _f, r in self.leeches.values() for c in r]
        return false_ids, true_ids


def survey(chosen: list[CardKind], flags: list[int], do_leech: bool,
           tag: str, mature: int) -> Survey:
    """Reads, for every kind chosen, what carries each target.

    A flag whose action means nothing for a kind is still counted, in `left`, and
    reported under the list.
    """
    actions = marks.flag_actions()
    found = Survey(chosen, {f: {} for f in flags})
    for kind in chosen:
        notetype = kind.notetype
        for f in flags:
            count = len(marks.find_flagged(notetype, f))
            if actions[f] in kind.actions:
                found.flags[f][kind.command] = count
            elif count:
                found.left.append((notetype, FLAG_COLOURS[f][1], count))
        if do_leech:
            false_ids, true_ids = leech_gen.find_leeches(notetype, tag, mature)
            if kind.leech:
                found.leeches[kind.command] = (false_ids, true_ids)
            elif false_ids or true_ids:
                found.left.append((notetype, "leech", len(false_ids) + len(true_ids)))
    return found


def left_line(notetype: str, target: str, count: int) -> str:
    """Cards under a target nothing handles for their kind: left as they are."""
    return counted(count,
                   "{count} {notetype} card under {target}: nothing handles that for "
                   "this type, left as it is",
                   "{count} {notetype} cards under {target}: nothing handles that for "
                   "this type, left as they are").format(
        count=count, notetype=notetype, target=target)


def scan_counts(found: Survey) -> tuple[dict[str, int | tuple[int, ...]], list[str] | None]:
    """The figures of the list, and the headers of their columns.

    One column while the work sits in one note type, one per busy type beyond.
    """
    names = [name for name, _number in FLAG_BY_NAME.items()
             if FLAG_BY_NAME[name] in found.flags]
    if found.leeches:
        names.append("leech")
    busy = found.busy()
    if len(busy) < 2:
        return {name: sum(found.count(name, kind) for kind in found.kinds)
                for name in names}, None
    return ({name: tuple(found.count(name, kind) for kind in busy) for name in names},
            [kind.notetype for kind in busy])


def _print_scan(args, found: Survey, auto_flags: set[int], auto_leech: bool) -> None:
    """What the deck carries today, target by target, without changing anything.

    The dialogue's list (`target_lines`), empty targets included. `--only` narrows
    it; `--yes` marks what would go through unconfirmed, inert under `--scan`.
    """
    counts, headers = scan_counts(found)
    automatic = {FLAG_COLOURS[f][1]: _("   [automatic]") for f in auto_flags}
    if found.leeches and auto_leech:
        automatic["leech"] = _("   [automatic]")

    print(_("Maintenance of {notetypes}:").format(
        notetypes=listed(quoted(kind.notetype) for kind in found.kinds)))
    console.space()
    for line in target_lines(counts, only=counts, marks=automatic, headers=headers):
        print(line)
    # The detail after the list, so as not to cut its column of figures in two.
    false_ids, true_ids = found.all_leeches()
    for line in leech_gen.leech_detail(false_ids, true_ids, args.tag, args.mature_ivl):
        print(line)
    for notetype, target, count in found.left:
        print("  ! " + left_line(notetype, target, count))
    # No blank line before the total: it closes the column it adds up.
    print("  = " + _("{count} {cards} to handle").format(
        count=found.total, cards=console.plural(found.total, "card")))


# ── Main entry point ──────────────────────────────────────────────────────────

def run_maintain(args: argparse.Namespace) -> None:
    flags, do_leech = _parse_selection(getattr(args, "only", None))
    yes = getattr(args, "yes", None)
    auto_flags, auto_leech = _parse_auto(yes, flags, do_leech)
    if yes and not auto_flags and not auto_leech:
        print("! " + _("The targets of --yes are not among those handled: "
                       "everything will be confirmed by hand."))

    # What the deck carries, flags and leeches in one same count
    try:
        found = survey(kinds.selected(getattr(args, "type", None)), flags, do_leech,
                       args.tag, args.mature_ivl)
    except (ConnectionError, RuntimeError) as exc:
        sys.exit(console.reason(exc, console.ALONE))
    total = found.total

    # Only `--scan` shows the survey: each task announces its own count as it
    # starts (`process_flag`, and the two halves of the leech).
    if args.scan:
        _print_scan(args, found, auto_flags, auto_leech)
    if args.scan or total == 0:
        # Said even without the survey: a clean deck would otherwise get no word.
        if total == 0:
            print(_("Nothing to do."))
        if not args.scan:
            for notetype, target, count in found.left:
                print("! " + left_line(notetype, target, count))
        return

    # Before the backup: a missing model or key stops the run with nothing done.
    client = AIClient(provider=args.provider, model=args.model)

    # The backup: after the survey, which changes nothing, and before the first
    # model call. This command deletes notes, rewrites fields in bulk and resets
    # leeches, where the rest of the program only adds cards.
    from kotogen.anki import backup
    console.space()
    backup.before("maintain")

    # Load the whole of a note type when its duplicate flag (turquoise) is asked for
    all_notes: dict[str, list[dict]] = {}
    actions = marks.flag_actions()
    for kind in found.kinds:
        if any(actions[f] == "duplicate" and found.flags[f].get(kind.command)
               for f in flags):
            if not all_notes:
                console.space()
                print(_("Loading the deck for the duplicate search..."))
            all_notes[kind.command] = marks.load_notes(kind.notetype)

    marks.tally.reset()
    lone_kanji.held_notes.clear()
    lone_kanji.moving.clear()
    named = len(found.busy()) > 1
    try:
        try:
            for f in flags:
                for kind in found.kinds:
                    if found.flags[f].get(kind.command):
                        flag_pass.process_flag(client, f, kind, f in auto_flags,
                                               all_notes.get(kind.command, []), named)
            for kind in found.kinds:
                false_ids, true_ids = found.leeches.get(kind.command, ([], []))
                if false_ids or true_ids:
                    leech_gen.process_leeches(false_ids, true_ids, args, client,
                                              auto=auto_leech, kind=kind)
        except marks.Quit:
            console.space()
            print(_("Interrupted by the user."))
        # The lone kanji go to the kanji deck in one batch, after a `[q]` too:
        # Ctrl+C and a fatal error leave the moves decided for the next run.
        lone_kanji.move_to_kanji_deck(client)
    except KeyboardInterrupt:
        console.space()
        print(_("Interrupted by the user."))
        _report(found)
        sys.exit(130)  # what a shell expects of a program stopped by Ctrl+C
    except (ConnectionError, RuntimeError) as exc:
        # Said after the summary: the corrections already confirmed are in Anki.
        # A RuntimeError is a key refused, an editor open or a write Anki refused.
        _report(found)
        sys.exit(_("Maintenance interrupted: {error}").format(
            error=console.reason(exc, console.ALONE)))
    except Exception:
        # The unforeseen ends on the program's net, after what reached the deck.
        _report(found)
        raise
    _report(found)


def _report(found: Survey) -> None:
    """The closing tally of the run, then what it left for later."""
    tally = marks.tally
    # Two counts in one sentence: each phrase is agreed on its own, French
    # agreeing the participle too (`1 carte modifiée`, `3 cartes modifiées`).
    changed = counted(tally.changed,
                      "{count} card changed",
                      "{count} cards changed").format(count=tally.changed)
    removed = counted(tally.cleared,
                      "{count} flag removed",
                      "{count} flags removed").format(count=tally.cleared)
    summary = "\n" + _("Done: {changed}, {removed}").format(
        changed=changed, removed=removed)
    if found.leeches:
        false_ones = counted(tally.cleaned,
                             "{count} false leech cleared",
                             "{count} false leeches cleared").format(count=tally.cleaned)
        real_ones = counted(tally.reworked,
                            "{count} real leech reworked",
                            "{count} real leeches reworked").format(count=tally.reworked)
        summary += _(", {false_ones}, {real_ones}").format(
            false_ones=false_ones, real_ones=real_ones)
    print(sentence(summary))
    # Said once, after the count, rather than on every card held.
    if lone_kanji.held_notes:
        held = len(lone_kanji.held_notes)
        print("! " + counted(held,
                             "{count} card waits for your decision: {command}, or "
                             "{search} in Anki",
                             "{count} cards wait for your decision: {command}, or {search} "
                             "in Anki").format(
            count=held, command="kotogen maintain",
            search=f"tag:{CATEGORY_TAG_TODO}"))
    # Then what nothing handles for its kind: part of what the run did not do.
    for notetype, target, count in found.left:
        print("! " + left_line(notetype, target, count))
