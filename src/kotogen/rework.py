"""`kotogen rework`: the maintenance of a JSON Lines file, written down.

The middle of `kotogen maintain` (`kotogen.maintenance`) on a file: each card
goes through the task named, and what the model proposes is written to another
file under the same `id`. Nothing is sent or changed, neither the file read nor
any deck. The tasks: `simplify`; `reading` (the `text` action); `leech`, as
`maintain` reworks a leech, with `kanji_help` for a word; `derive`, the words
and rules a card calls for, less those the file holds.

The file written opens on a header saying it holds proposals, not cards, and
gets one line per card as the run goes, so a run stopped halfway keeps what it
paid for.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kotogen import console, exporter
from kotogen.ai_client import AIAuthError, AIClient
from kotogen.i18n import _, counted, listed, quoted
from kotogen.known import JsonlFile, Nothing
from kotogen.maintenance import derive, kinds, leech, review
from kotogen.maintenance.kinds import CardKind

# What the file written is: proposals, under a format of their own.
FORMAT = "kotogen-proposals"
VERSION = 1

# The action of a kind's instruction each task asks for. `derive` has a pass of
# its own, and so has the leech of a word (`leech._propose_simpler`).
ACTIONS = {"simplify": "simplify", "reading": "text", "leech": "simplify"}


def output_path(cards: Path, task: str) -> Path:
    """Where the proposals go when nobody said: beside the cards, named after the task."""
    return cards.with_name(f"{cards.stem}.{task}.jsonl")


def read_ids(path: Path) -> list[str]:
    """The ids written in a file, one per line; blank lines and `#` comments skipped."""
    ids = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [card_id for card_id in ids if card_id and not card_id.startswith("#")]


def header(task: str, cards: Path) -> dict:
    """The first line of the file of proposals: what it is, and what made it -
    said as a file of cards says it (`exporter.provenance`)."""
    return {"format": FORMAT, "version": VERSION, "task": task,
            "cards": cards.name} | exporter.provenance()


def propose(client, task: str, card: dict, kind: CardKind,
            held: derive.Held | None = None, taken: set[str] | None = None) -> dict:
    """What the model proposes for one card: its line in the file of proposals.

    `held` and `taken` serve `derive`: what the collection holds, and what an
    earlier card of the run proposed, so that a word is proposed once.
    """
    line: dict = {"id": card.get("id"), "kind": kind.command}
    if task == "derive":
        new, already = derive.fresh(derive.propose(client, card, kind),
                                    held if held is not None else derive.Held(Nothing()),
                                    taken if taken is not None else set())
        if taken is not None:
            taken.update(proposal.word for proposal in new)
        line["derive"] = [{"word": p.word, "relation": p.relation, "gloss": p.gloss,
                           "kind": p.target} for p in new]
        if already:
            line["already"] = [p.word for p in already]
        return line

    refused: list[str] = []
    if task == "leech":
        proposal = (leech._propose_simpler(client, card) if kind.words
                    else review.propose_changes(client, ACTIONS[task], card, kind))
        # A leech is rewritten, never emptied: a field the model would clear
        # stays as it is, as it does in the deck. Its tags are left alone.
        fields = {name: value for name, value in
                  review._changed_fields(card, proposal.get("fields") or {}, kind,
                                         refused).items() if str(value).strip()}
        add, remove, reason = [], [], str(proposal.get("reason", "")).strip()
        kanji_help = leech._clean_kanji_help(str(proposal.get("kanji_help", "")).strip())
        if kind.words and kanji_help and leech._several_kanji(review._field(card, "Expression")):
            line["kanji_help"] = kanji_help
    else:
        proposal = review.propose_changes(client, ACTIONS[task], card, kind)
        fields, add, remove, reason = review._normalise_proposal(card, proposal, kind,
                                                                 refused, ACTIONS[task])
    line |= {"fields": fields, "add_tags": add, "remove_tags": remove, "reason": reason}
    if refused:
        line["refused"] = refused
    verdict = review.read_category(card, proposal) if kind.words else None
    if verdict:
        line["category"] = {"type": verdict[0], "reason": verdict[1]}
    return line


def _said(line: dict) -> tuple[str, str]:
    """The mark and the detail of a card's line on screen."""
    if "error" in line:
        return "!", line["error"]
    if "derive" in line:
        words = "、".join(item["word"] for item in line["derive"])
        return ("+", words) if words else ("=", _("nothing new to derive"))
    change = review._change_summary(line["fields"], line["add_tags"], line["remove_tags"])
    if line.get("kanji_help"):
        change = listed(filter(None, [change, _("kanji help")]))
    return ("✓", change) if change else ("=", _("nothing to change"))


def _cannot_read(path: Path, exc: Exception) -> str:
    return _("Cannot read {path}: {error}").format(path=quoted(str(path)),
                                                   error=console.reason(exc))


def run_rework(args: argparse.Namespace) -> None:
    """Work the task through the cards of a file, writing what is proposed."""
    cards_path = Path(args.cards)
    # Checked before any model call: a file of proposals was paid for, and the
    # cards are the input.
    out = Path(args.output) if args.output else output_path(cards_path, args.task)
    if out.exists() and cards_path.exists() and out.samefile(cards_path):
        sys.exit(_("The proposals would overwrite the cards they are made from: "
                   "name another file with --output."))
    if out.exists():
        sys.exit(_("{path} already exists, and the proposals it holds would be lost: "
                   "name another file with --output, or move it away.").format(
                       path=quoted(str(out))))
    if not out.parent.is_dir():
        sys.exit(_("The folder of {path} does not exist: create it, or name another "
                   "file with --output.").format(path=quoted(str(out))))
    try:
        read = exporter.read_cards(cards_path)
    except OSError as exc:
        sys.exit(_cannot_read(cards_path, exc))
    except exporter.NotCards as exc:
        sys.exit(console.reason(exc, console.ALONE))

    console.title(cards_path.name)
    chosen = read.cards
    if args.ids:
        try:
            wanted = read_ids(Path(args.ids))
        except (OSError, ValueError) as exc:
            sys.exit(_cannot_read(Path(args.ids), exc))
        present = {card.get("id") for card in chosen}
        absent = [card_id for card_id in wanted if card_id not in present]
        chosen = [card for card in chosen if card.get("id") in set(wanted)]
        if absent:
            console.aside(counted(len(absent),
                                  "{count} id is not in {path}: {ids}",
                                  "{count} ids are not in {path}: {ids}").format(
                count=len(absent), path=cards_path.name, ids=listed(absent[:5])
                + (f"... (+{len(absent) - 5})" if len(absent) > 5 else "")))
    # A card is worked on when the task means something for its kind: no task
    # reworks a kanji card, nor a card of a field list no generator writes.
    workable = [(card, kinds.KINDS[card["kind"]]) for card in chosen
                if card.get("kind") in kinds.KINDS and card.get("id") is not None]
    left = len(chosen) - len(workable)
    if read.unreadable:
        console.aside(counted(read.unreadable,
                              "{count} line does not read, left out",
                              "{count} lines do not read, left out").format(
            count=read.unreadable))
    if left:
        console.aside(counted(left,
                              "{count} card of a kind no task reworks, left out",
                              "{count} cards of a kind no task reworks, left out").format(
            count=left))
    if not workable:
        sys.exit(_("No card of {path} to rework.").format(path=quoted(cards_path.name)))
    console.item(counted(len(workable),
                         "{count} card to rework ({task})",
                         "{count} cards to rework ({task})").format(
        count=len(workable), task=args.task))

    client = AIClient(provider=args.provider, model=args.model)
    held, taken = derive.Held(JsonlFile(cards_path)), set()
    failed = 0
    console.space()
    try:
        # "x": a file that appeared since the check is not truncated either. A
        # bare line feed, as every file of cards ends its lines.
        f = open(out, "x", encoding="utf-8", newline="\n")
    except OSError as exc:
        sys.exit(_("Cannot write {path}: {error}").format(
            path=quoted(str(out)), error=console.reason(exc)))
    with f:
        f.write(json.dumps(header(args.task, cards_path), ensure_ascii=False) + "\n")
        for card, kind in workable:
            try:
                line = propose(client, args.task, card, kind, held, taken)
            except AIAuthError:
                raise  # key/quota: the next cards would all fail the same way
            except Exception as exc:
                line = {"id": card.get("id"), "kind": kind.command,
                        "error": console.reason(exc)}
                failed += 1
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
            f.flush()
            mark, detail = _said(line)
            review.auto_line(mark, card, detail)

    console.space()
    lines = [counted(len(workable),
                     "{count} proposal -> {path}",
                     "{count} proposals -> {path}").format(count=len(workable), path=out)]
    if failed:
        lines.append("   " + counted(failed,
                                     "{count} card failed: its line says why",
                                     "{count} cards failed: their line says why").format(
            count=failed))
    print("\n".join(lines))
