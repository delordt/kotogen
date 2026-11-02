"""Grammar card generator."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

from kotogen import console, furigana, grammar_table, jlpt, memory, prompts, seen
from kotogen.ai_client import AIAuthError, AIClient
from kotogen.exporter import append_cards, finish, resolve_output_path, short
from kotogen.i18n import _, agreed, convention, counted, listed, quoted
from kotogen.jlpt import LEVELS as JLPT_LEVELS
from kotogen.known import Known, card_field

# ── Before the AI call: level detection + canonical name ─────────────────────

def _detect_info(client: AIClient, rule: str) -> dict[str, str]:
    """Canonical name and level of a rule: the table first, the AI otherwise.

    The table costs no call, and gives the syllabus level where the model would
    estimate it. The model names the forms the table does not know
    ("younitanomu", a rule outside the JLPT).
    """
    point = grammar_table.find(rule)
    if point is not None:
        # The gloss goes to the model (see `_generate_cards`), so it is read in
        # the language of the cards, not of the screen.
        return {"level": point["level"],
                "rule_tag": _without_spaces(point["title"]),
                "meaning": grammar_table.meaning(point, prompts.language())}

    # In English, like the instruction it travels with: `grammar_detect` hands
    # back structure, never card text, so it lives in `prompts/structure/` alone.
    user_msg = f'Grammar rule: "{rule}"'
    result = client.chat_json(prompts.load("grammar_detect"), user_msg)
    if not isinstance(result, dict):
        raise ValueError(_("unexpected JSON structure: {kind}").format(
            kind=type(result).__name__))

    level = result.get("level", "N5")
    if level not in JLPT_LEVELS:
        level = "N5"

    # Normalised once: the tag, the screen and the history all take it from here.
    rule_tag = _without_spaces(_table_spelling(str(result.get("rule_tag") or rule)))
    return {"level": level, "rule_tag": rule_tag or _without_spaces(rule), "meaning": ""}


# The fields, in the order the card reads them. `Sentence` comes first: Anki
# checks duplicates on the first field. `Rule`, `Answer` (see `_to_type`) and
# `URL` are filled by the program, not asked of the model.
FIELDS = [
    "Sentence",
    "Translation",
    "Target",
    "Hint",
    "Nuance",
    "Rule",
    "Explanation",
    "Answer",
    "URL",
]

# The rule the usage lines type, quoted for the shell as it is typed: the screen's
# quotation marks (`i18n.quoted`) would not run.
EXAMPLE_RULE = '"〜てください"'

# A cloze marker {{cN::…}} (content without the braces).
_CLOZE_RE = re.compile(r"\{\{c\d+::(.+?)\}\}")


# Punctuation belongs to the sentence, not to the hole: inside it, the back would
# colour 「降れば、」 comma included, and the typed answer would need the comma.
# Opening marks move in front of the hole, closing ones behind it.
_PUNCTUATION_BEFORE = "「『（(【〈《"
_PUNCTUATION_AFTER = "。、．，！？!?」』）)】〉》…・"


def _tighten(answer: str) -> tuple[str, str, str]:
    """The hole separated from the punctuation around it: (before, hole, after).

    A leading space stays in the hole, anchoring its first furigana group
    (` 聞[き]きながら`); a trailing one leaves with the punctuation.
    """
    before, after = "", ""
    while answer and answer[0] in _PUNCTUATION_BEFORE:
        before, answer = before + answer[0], answer[1:]
    while answer and (answer[-1] in _PUNCTUATION_AFTER or answer[-1].isspace()):
        after, answer = answer[-1] + after, answer[:-1]
    return before, answer, after


def _normalise_cloze(cards: list[dict]) -> list[dict]:
    """Validates and normalises the hole of each card.

    Every marker becomes `c1` (one note, one card); an inline hint
    (`{{c1::answer::hint}}`) moves to `Hint`, as furigana would nest brackets
    Anki cannot read; the hole is tightened (`_tighten`); a card with no hole is
    dropped.
    """
    kept: list[dict] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        statement = str(card.get("Sentence", ""))
        if not _CLOZE_RE.search(statement):
            console.aside(_("card with no hole turned down: {statement}").format(
                statement=short(statement, 60)))
            continue

        def move_hint(m: re.Match, card=card) -> str:
            answer, sep, hint = m.group(1).partition("::")
            if sep and not str(card.get("Hint", "")).strip():
                card["Hint"] = hint.strip()
            before, answer, after = _tighten(answer)
            # A hole of punctuation alone is left as it came, for the
            # proofreading to judge the card.
            if not answer.strip():
                return m.group(0)
            return before + "{{c1::" + answer + "}}" + after

        card["Sentence"] = _CLOZE_RE.sub(move_hint, statement)
        kept.append(card)
    return kept


def _generate_cards(
    client: AIClient,
    rule: str,
    level: str,
    count: int,
    meaning: str = "",
) -> list[dict[str, str]]:
    # The count also sets how far the series goes into the rule (the `The series`
    # section of the instructions), so the message states it. In the language of
    # the cards: `prompts.say`, never `_()`.
    user_msg = prompts.say(
        "Generate exactly {count} gapped sentences for the rule **{rule}** "
        "(level {level}).\n"
        "It is ONE series, not {count} draws: cover the surface of the rule in "
        "the prescribed order, the most central card first, and invent no "
        "construction the rule does not admit in order to reach the count.\n"
        "Hand back a JSON array of {count} objects."
    ).format(count=count, rule=rule, level=level)
    if meaning:
        # One form can carry several uses (ている: an action under way, a
        # resulting state), and the meaning keeps the series on one: in the
        # language of the cards from the table, in English from `grammar_page`.
        user_msg += "\n\n" + prompts.say(
            "It is the \"{meaning}\" use of this rule that is aimed at."
        ).format(meaning=meaning)
    result = client.chat_json(prompts.load("grammar_card"), user_msg)
    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))
    return _normalise_cloze(result)


# ── Post-processing: rule, answer, target, URL, tags ─────────────────────────

# The four registers as the AI names them, and the tag of each. Both halves of
# 敬語 are filed under it (`Register::敬語::尊敬語`), to be found together in Anki.
_REGISTERS = {
    "常体": "Register::常体",
    "丁寧体": "Register::丁寧体",
    "尊敬語": "Register::敬語::尊敬語",
    "謙譲語": "Register::敬語::謙譲語",
}

# Case and apostrophes (often curly from the model) do not tell two spellings
# apart. One character for one: the card's script folds alike to find the target
# in the translation, and keeps its positions.
_APOSTROPHES = str.maketrans("’ʼ", "''")


def _fold(text: str) -> str:
    return text.translate(_APOSTROPHES).lower()


def _without_spaces(rule: str) -> str:
    """A rule name such as an Anki tag can carry it.

    Anki splits tags on spaces: 「くらい （程度）」 would make two tags.
    """
    return "".join(rule.split())


def _table_spelling(rule: str) -> str:
    """A rule name the model gave, spelt as the table spells its own.

    No 〜 at either end (ながら, not 〜ながら): the name becomes the tag, which a
    search finds as it is written. A 〜 inside holds a slot and stays.
    """
    return rule.strip().strip("〜～~").strip()


def _to_type(statement: str) -> str:
    """The content of the hole, as it is typed on the keyboard.

    Without readings or the spaces anchoring them: `{{type:Answer}}` compares to
    the character.
    """
    hole = _CLOZE_RE.search(statement)
    return furigana.without_readings(hole.group(1)).strip() if hole else ""


def _target_kept(card: dict) -> str:
    """The part of the translation the card colours, if it is found in it.

    An extract, not a gloss: one the translation lacks would colour nothing, and
    gives "". The caller reports those once for the batch (`_post_process`).
    """
    target = str(card.get("Target", "")).strip()
    if target and _fold(target) not in _fold(str(card.get("Translation", ""))):
        return ""
    return target


def _post_process(cards: list[dict], level: str, rule: str, url: str) -> list[dict]:
    """Completes each card with what the program already knows: rule, answer to
    type, the page given with `--url`, tags.

    No ID field: Anki deduplicates on `Sentence`, the first field.
    """
    tag_base = f"Grammar::{level}::{_without_spaces(rule)}"
    dropped: list[str] = []

    for card in cards:
        card["URL"] = url
        card["Rule"] = rule
        card["Answer"] = _to_type(str(card.get("Sentence", "")))
        before = str(card.get("Target", "")).strip()
        card["Target"] = _target_kept(card)
        if before and not card["Target"]:
            dropped.append(before)

        # The register becomes a tag, which Anki filters on and the card reads
        # for its badge. An unknown register is dropped rather than tagged.
        register = _REGISTERS.get(str(card.get("Register", "")).strip())
        existing = [t for t in str(card.get("Tags", "")).split()
                    if t.startswith("Register::")]
        card["Tags"] = " ".join(dict.fromkeys(
            [tag_base] + ([register] if register else []) + existing))

    # One line for the batch, never one per card: a single target is named,
    # several are counted.
    if len(dropped) == 1:
        console.aside(_("target outside the translation, ignored: {target}").format(
            target=short(dropped[0], 40)))
    elif dropped:
        console.aside(counted(len(dropped),
                              "{count} target outside the translation, ignored",
                              "{count} targets outside the translation, ignored")
                      .format(count=len(dropped)))

    return cards


# ── Public entry point ────────────────────────────────────────────────────────


def run_grammar(args: argparse.Namespace) -> None:
    """Routing: what was given says what has to be done with it.

    The input is always a rule: typed, several in a row, drawn from a level, read
    in a file, or read on the page documenting it. A text is refused: the rules
    of a text one has read come from its reading card, through the pink flag of
    `maintain`, filtered against the deck.
    """
    from kotogen.generators import sources  # late import (avoids an import cycle)

    rules = [rule.strip() for rule in (args.rule or []) if rule.strip()]

    if args.file and rules:
        sys.exit(_("Give a rule file (--file) OR some rules, not both."))
    if args.file:
        _run_grammar_list(args, _read_rules(args.file), args.file.name)
        return
    if not rules:
        # A page with no rule: the page says which one (see `_run_grammar_entry`).
        if args.url:
            _run_grammar_entry(args)
            return
        sys.exit(_(
            "Grammar: give it something to work on.\n"
            "  kotogen grammar {rule}            (one rule, typed as it comes)\n"
            "  kotogen grammar jlpt --level N4          (the N4 rules the deck lacks)\n"
            "  kotogen grammar --url https://…          (the rule an entry documents)\n"
            "  kotogen grammar --file rules.md          (one rule per line)")
            .format(rule=EXAMPLE_RULE))
    if len(rules) > 1:
        # Several rules in a row, worked as a file would be. None of them is a
        # source: "jlpt" comes alone, and a path is not mixed with rules.
        _run_grammar_list(args, rules, "")
        return

    source = rules[0]
    if sources.is_pdf(source) or sources.is_nhk(source) or sources.is_text(source):
        # A text is refused rather than taken for a rule: "nhk" or an address
        # would otherwise be analysed as a rule name (see the docstring above).
        sys.exit(_(
            "Grammar: a text is not a source of rules - give the rule, or the "
            "level.\n"
            "  kotogen grammar {rule}       (one precise rule)\n"
            "  kotogen grammar jlpt --level N4   (the N4 rules the deck lacks)\n"
            "  kotogen grammar --url https://…   (the rule a page documents)\n"
            "The rules of a text you have read: make it a reading card, and its "
            "pink flag in kotogen maintain proposes them."
        ).format(rule=EXAMPLE_RULE))
    if jlpt.is_keyword(source):
        _run_grammar_jlpt(args)
        return

    client = AIClient(provider=args.provider, model=args.model)

    # ── Step 1: level detection + canonical name + URL ──────────────────────
    console.title(source)
    console.action(_("Analysing the rule"))
    try:
        info = _detect_info(client, source)
    except AIAuthError:
        raise
    except Exception as exc:
        console.close_line()
        sys.exit(_("Cannot analyse the rule: {error}").format(
            error=console.reason(exc, console.ALONE)))
    rule_tag = info["rule_tag"]

    level = info["level"]
    url = args.url or ""
    # The analysis line closes on the tag, which holds the level and the canonical
    # name (not always the one typed), then on the page, if any.
    console.done(f"Grammar::{level}::{rule_tag}" + (f", {url}" if url else ""))

    # ── Step 2: generating the cards ─────────────────────────────────────────
    out_path = resolve_output_path(args, "grammar")

    console.action(_("Generating the cards"),
                   among=agreed(args.count, "{count} with a hole").format(count=args.count))

    try:
        cards = _generate_cards(
            client,
            rule=rule_tag,
            level=level,
            count=args.count,
            meaning=info["meaning"],
        )
    except Exception as exc:
        # "Cannot generate" rather than "Generation error": the assistant already
        # prefixes the line with "Error:".
        console.close_line()
        sys.exit(_("Cannot generate: {error}").format(
            error=console.reason(exc, console.ALONE)))

    if not cards:
        console.done(_("no card"))
        sys.exit(_("No card generated."))

    # ── Step 3: post-processing ──────────────────────────────────────────────
    cards = _post_process(cards, level, rule_tag, url)
    console.done(f"{len(cards)} {console.plural(len(cards), 'card')}")

    # Saved at once, with the history: the rule counts as worked once its cards
    # are written, sent to Anki or not.
    append_cards(out_path, cards, FIELDS, args.deck, args.notetype)
    _mark_done(rule_tag)

    preview = [
        f"  {i:2}. {short(card.get('Sentence', ''), 70)}"
        for i, card in enumerate(cards, 1)
    ]
    if url:
        preview.append("  " + _("Shared URL: {url}").format(url=url))
    preview.append("  " + _("Tags: {tags}").format(
        tags=f"Grammar::{level}::{rule_tag}"))

    finish(cards, FIELDS, args, out_path, preview=preview)


# ── Multi-rule modes: a list, a JLPT level ───────────────────────────────


def _cards_for_rules(
    client: AIClient,
    rules: list[dict],
    args: argparse.Namespace,
    out_path,
    all_cards: list[dict],
    tags_done: list[str],
    failed: list[str] | None = None,
) -> bool:
    """Generates and saves the cards of each rule kept, whatever chose the rules.

    Feeds all_cards / tags_done in place, and `failed` with the rules whose call
    failed; hands back True when at least one card was produced. --count applies
    PER rule.
    """
    produced = False
    for info in rules:
        rule = info["rule"]
        level = info["level"]
        # The page given with --url, or the one the rule was read from.
        url_ref = args.url or info.get("url", "")
        console.action(_("Generating the cards"), among=f"{rule}, {level}")
        try:
            cards = _generate_cards(
                client,
                rule=rule,
                level=level,
                count=args.count,
                meaning=info.get("meaning", ""),
            )
        except AIAuthError:
            raise  # key/quota: the following rules would all fail the same way
        except Exception as exc:
            console.failed(_("cannot generate: {reason}").format(
                reason=console.reason(exc)))
            if failed is not None:
                failed.append(rule)
            continue
        cards = _post_process(cards, level, rule, url_ref)
        if cards:
            append_cards(out_path, cards, FIELDS, args.deck, args.notetype)
            _mark_done(rule)
            all_cards.extend(cards)
            tags_done.append(f"Grammar::{level}::{rule}")
            produced = True
        console.done(f"{len(cards)} {console.plural(len(cards), 'card')}")
    return produced


def _finish_multi_rules(all_cards: list[dict], tags_done: list[str],
                        out_path, args: argparse.Namespace) -> None:
    """Final summary of the rule list, the JLPT level and the `--url` entry."""
    if not all_cards:
        sys.exit(_("No card generated."))

    preview = [
        f"  {i:2}. {short(card.get('Sentence', ''), 70)}"
        for i, card in enumerate(all_cards[:20], 1)
    ]
    if len(all_cards) > 20:
        preview.append("  " + _("... and {count} others").format(
            count=len(all_cards) - 20))
    preview.append("  " + _("Tags: {tags}").format(tags=listed(tags_done)))

    finish(all_cards, FIELDS, args, out_path, preview=preview)


# ── The "jlpt" source: the rules of the level the deck lacks ─────────────────
# The rules of the level in the table, less those the deck holds, with no model
# call: what `vocab jlpt` does with words.

# One call and `--count` cards per rule: a whole level (110 to 295 points) would
# be a surprise bill. `--rules` asks for more, and a rerun takes the next ones,
# those generated being in the deck.
JLPT_DEFAULT_RULES = 3


# The tag naming the rule of a card: "Grammar::N4::ながら".
_RULE_TAG_RE = re.compile(r"^Grammar::N[1-5]::(.+)$")


# ── What is already done ─────────────────────────────────────────────────────
# Two memories: the deck (with Anki closed, the copy kept of it), which knows a
# rule once its cards are imported, and the local history, as soon as they are
# written. Neither forbids anything: a rule done stays on offer, marked as such.

RULES_SOURCE = "rules"


def _mark_done(rule: str) -> None:
    """Records that this rule has just been worked, under its canonical name."""
    seen.mark("grammar", RULES_SOURCE, grammar_table.key(rule), rule)


def _rules_seen() -> set[str]:
    """The names already kept by the local history."""
    return set(seen.load("grammar", RULES_SOURCE))


def _is_done(point: dict[str, str], names: set[str], seen_ids: set[str]) -> bool:
    """Has this point already been worked, here or in the deck?"""
    name = grammar_table.key(point["title"])
    return name in names or name in seen_ids


def _deck_rules(known: Known, notetype: str) -> set[str]:
    """The names of the rules the deck already carries.

    Read from the `Rule` field and from the tag, which every card carries where
    the field may be empty. Names are unique in the table (のに（逆接）,
    のに（目的）) and matched by canonical form (`grammar_table.key`).
    """
    names: set[str] = set()
    for card in known.cards(notetype):
        rule = card_field(card, "Rule")
        if rule:
            names.add(grammar_table.key(rule))
        for tag in card.get("tags") or []:
            named = _RULE_TAG_RE.match(tag)
            if named:
                names.add(grammar_table.key(named.group(1)))
    return names


def knows_rule(rule: str, deck_rules: set[str]) -> bool:
    """Whether the deck, or the local history, already holds this rule.

    For `maintain`, with no model call: under the name given, or under the one
    the table gives a form typed loosely. The first counts on its own, as a card
    may carry a name the table spells otherwise (〜てください, て形＋ください).
    `deck_rules` is `_deck_rules` of the grammar note type, read once per pass.
    """
    seen_ids = _rules_seen()
    name = grammar_table.key(rule)
    if name in deck_rules or name in seen_ids:
        return True
    point = grammar_table.find(rule)
    return point is not None and _is_done(point, deck_rules, seen_ids)


def deck_rules(known: Known, notetype: str) -> set[str]:
    """What the deck carries, for `knows_rule`."""
    return _deck_rules(known, notetype)


def generate_into(client: AIClient, rules: list[str], deck: str, notetype: str,
                  count: int) -> bool | None:
    """Generates the cards of these rules and sends them straight into Anki.

    For the `derive` action of `maintain`: the pipeline of a rule list, with the
    send already decided. True when Anki took the send, False when it or a call
    failed, None when no card came out and nothing failed.
    """
    args = argparse.Namespace(output=None, send=True, format=None, deck=deck,
                              notetype=notetype, url=None, count=count)
    kept: list[dict] = []
    failed: list[str] = []
    for rule in rules:
        console.action(_("Analysing the rule"), among=short(rule, 40))
        try:
            info = _detect_info(client, rule)
        except AIAuthError:
            raise  # key/quota: the next ones would all fail the same way
        except Exception as exc:
            console.failed(_("cannot analyse: {reason}").format(
                reason=console.reason(exc)))
            failed.append(rule)
            continue
        console.done(f"{info['rule_tag']}, {info['level']}")
        kept.append({"rule": info["rule_tag"], "level": info["level"], "meaning": info.get("meaning", "")})
    all_cards: list[dict] = []
    if kept:
        out_path = resolve_output_path(args, "grammar")
        _cards_for_rules(client, kept, args, out_path, all_cards, [], failed)
    if not all_cards:
        return False if failed else None
    return finish(all_cards, FIELDS, args, out_path, preview=[]) is not None


def level_label(level: str) -> str:
    """How the level is named on screen: "N4", or "every level"."""
    return level if level in JLPT_LEVELS else _("every level")


@dataclass(frozen=True)
class Rule:
    """A point of the syllabus, and what is known of it: has it been worked?"""

    point: dict[str, str]
    done: bool

    @property
    def title(self) -> str:
        return self.point["title"]


def rules_of_level(level: str, notetype: str, known: Known) -> list[Rule]:
    """The whole level, the most central rule first, each marked done or not.

    Done rules included, for the assistant to show where one stands and to come
    back to one; the command line takes the first ones not done
    (`_run_grammar_jlpt`).
    """
    names = _deck_rules(known, notetype)
    seen_ids = _rules_seen()
    return [Rule(point, _is_done(point, names, seen_ids))
            for point in grammar_table.points_of(level)]


def rule_from_point(point: dict[str, str]) -> dict[str, str]:
    """A point of the table, as the generation expects it.

    With its level and meaning, which the model is not asked again; the meaning
    in the language of the cards, as it goes to the model.
    """
    return {"rule": _without_spaces(point["title"]),
            "level": point["level"],
            "meaning": grammar_table.meaning(point, prompts.language())}


def _run_grammar_jlpt(args: argparse.Namespace) -> None:
    """Pipeline of the JLPT level: what the deck lacks, the most central first."""
    # Without the deck the whole level would be generated, so the connection is
    # checked; an empty deck is a valid answer. A JSON run compares with its own
    # file, which always answers (see `memory`).
    known = memory.known()
    if not known.reachable(args.notetype):
        sys.exit(_(
            "{source} source: Anki has to be open (AnkiConnect) to know which "
            "rules you are missing - otherwise it is the whole level that would "
            "be generated.").format(source=quoted(jlpt.KEYWORD)))

    label = level_label(args.level)
    console.title(_("JLPT grammar missing from {deck}").format(
        deck=quoted(known.name(args.deck))))

    rules = rules_of_level(args.level, args.notetype, known)
    if not rules:
        sys.exit(_("Rule table unavailable: cannot say what {label} holds. Give "
                   "the rule yourself.").format(label=label))
    missing = [rule.point for rule in rules if not rule.done]
    done = len(rules) - len(missing)
    # Each fragment agrees with its own count.
    console.item(_("{label}: {total} rules on the syllabus, {done}, {left}").format(
        label=label, total=len(rules),
        done=agreed(done, "{count} already done").format(count=done),
        left=agreed(len(missing), "{count} missing").format(count=len(missing))))
    if not missing:
        console.item(_("Nothing to generate: every rule of {label} is already "
                       "done. Name one to come back to it.").format(label=label))
        return

    limit = args.rules if args.rules is not None else JLPT_DEFAULT_RULES
    if len(missing) > limit:
        console.item("→ " + _("the first {count} are generated (--rules to ask "
                               "for more, replay for the next batch)").format(count=limit))

    to_generate = [rule_from_point(point) for point in missing[:limit]]

    client = AIClient(provider=args.provider, model=args.model)
    out_path = resolve_output_path(args, "grammar")
    all_cards: list[dict] = []
    tags_done: list[str] = []

    _cards_for_rules(client, to_generate, args, out_path, all_cards, tags_done)
    _finish_multi_rules(all_cards, tags_done, out_path, args)


# ── Several rules: given in a row, or read in a file ─────────────────────────
# What `vocab --file` does with words.

def _read_rules(path_arg) -> list[str]:
    """The rules of a file, one per line.

    Each line is read as a typed rule, in any form; blank lines and `#` comments
    are skipped.
    """
    from kotogen.generators import text_source

    path = text_source.clean_path(str(path_arg))
    if not path.is_file():
        sys.exit(_("File not found: {path}").format(path=path))
    lines = [line.strip() for line in
             text_source.decode(path.read_bytes()).splitlines()]
    rules = [line for line in lines if line and not line.startswith("#")]
    if not rules:
        sys.exit(_("No rule in {name} - one per line.").format(name=quoted(path.name)))
    return rules


def _run_grammar_list(args: argparse.Namespace, rules: list[str],
                      title: str) -> None:
    """Each rule is analysed then worked, as though it were alone.

    The analysis is the one extra call per rule; the generation is that of the
    JLPT level (`_cards_for_rules`).
    """
    client = AIClient(provider=args.provider, model=args.model)
    if title:
        console.title(title)
        console.item(counted(len(rules),
                             "{count} rule read",
                             "{count} rules read").format(count=len(rules)))

    kept: list[dict] = []
    for rule in rules:
        console.action(_("Analysing the rule"), among=short(rule, 40))
        try:
            info = _detect_info(client, rule)
        except AIAuthError:
            raise  # key/quota: the next ones would all fail the same way
        except Exception as exc:
            console.failed(_("cannot analyse: {reason}").format(
                reason=console.reason(exc)))
            continue
        console.done(f"{info['rule_tag']}, {info['level']}")
        kept.append({"rule": info["rule_tag"], "level": info["level"], "meaning": info.get("meaning", "")})

    if not kept:
        sys.exit(_("No usable rule."))

    out_path = resolve_output_path(args, "grammar")
    all_cards: list[dict] = []
    tags_done: list[str] = []
    _cards_for_rules(client, kept, args, out_path, all_cards, tags_done)
    _finish_multi_rules(all_cards, tags_done, out_path, args)


# ── The rule an entry documents (--url with no rule) ─────────────────────────
# Next to a rule, `--url` names its reference page; alone, the page names the
# rule, and stays the card's `URL`.


def _run_grammar_entry(args: argparse.Namespace) -> None:
    """Pipeline of the entry: the page says which rule, the cards get made."""
    from kotogen.generators import text_source

    url = args.url.strip()
    console.title(url)
    client = AIClient(provider=args.provider, model=args.model)

    console.action(_("Reading the entry"))
    try:
        page_title, text = text_source.page_text(url)
        read = client.chat_json(prompts.load("grammar_page"),
                                f'Page "{page_title}":\n\n{text}')
    except AIAuthError:
        raise
    except Exception as exc:
        console.close_line()
        sys.exit(_("Entry: {reason}").format(reason=console.reason(exc, console.ALONE)))
    if not isinstance(read, dict) or read.get("error") or not read.get("rule"):
        # The reason comes back in English, as with the PDF contract: it joins a
        # sentence written here in English and translated at this site.
        console.close_line()
        sys.exit(_("This page does not document one rule in particular")
                 + (convention("colon", ": ")
                    + console.reason(str(read["error"]), console.ALONE)
                    if isinstance(read, dict) and read.get("error")
                    else "."))
    level = str(read.get("level", "")).strip().upper()
    rule = {"rule": _without_spaces(_table_spelling(str(read["rule"]))),
            "level": level if level in JLPT_LEVELS else "N5",
            "meaning": str(read.get("meaning", "")).strip(),
            "url": url}
    console.done(f"{rule['rule']}, {rule['level']}")

    out_path = resolve_output_path(args, "grammar")
    all_cards: list[dict] = []
    tags_done: list[str] = []
    _cards_for_rules(client, [rule], args, out_path, all_cards, tags_done)
    _finish_multi_rules(all_cards, tags_done, out_path, args)
