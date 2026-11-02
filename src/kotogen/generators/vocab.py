"""Vocabulary card generator."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from itertools import groupby
from pathlib import Path
from threading import Event

from kotogen import console, dictionary, jlpt, kanji_word, memory, prompts
from kotogen.ai_client import AIAuthError, AIClient, AITruncatedError
from kotogen.exporter import append_cards, ask_choice, finish, resolve_output_path
from kotogen.i18n import _, agreed, convention, counted, quoted
from kotogen.known import NO_WORDS, Words, split_known

# ── Examples built on the vocabulary already learned (i+1) ───────────────────
# The examples are built on the words the deck already holds. The list goes in
# the system prompt, which is cached: full price once per run, then 10% per batch.

# Below that, too few words to write a natural sentence with: the prompt goes
# without the section.
KNOWN_WORDS_MIN = 200

# Ceiling, past which context costs more than it brings. The words kept are the
# most basic (by JLPT level, unknown ones last).
KNOWN_WORDS_MAX = 400


def known_words_section(index: Words) -> str:
    """Instruction "build with what they know", or "" when it is impossible.

    Hands back "" when the deck allows no conclusion: no deck to read (Anki closed
    and no copy of it), deck empty, or too few words learned.
    """
    if not index or len(index.surfaces) < KNOWN_WORDS_MIN:
        return ""
    # `sorted` first: `surfaces` is a set, ordered by the process's hash salt, and
    # the stable level sort would truncate a different 400 at every launch,
    # breaking the cache of the system prompt.
    words = jlpt.sort_by_level(sorted(w for w in index.surfaces if w))[:KNOWN_WORDS_MAX]
    # Prompt text: `prompts.say`, never `_()`. The heading is held apart so that no
    # source line starts with a "#", which the language guard reads as a comment.
    heading = prompts.say("## Vocabulary the learner already knows")
    body = prompts.say(
        "Build the **Example** sentences out of those words first, plus the "
        "particles, the numbers and the word of the card itself:"
    )
    tail = prompts.say(
        "An example sentence introducing three unknown words teaches nothing: it "
        "has to read in one go. This is not an absolute ban - a common linking "
        "word off the list passes perfectly well - but the example must stay in "
        "that register. This instruction changes NOTHING about the rest of the "
        "card: the Expression, the Translation and the Notes stay those of the "
        "word asked for."
    )
    return f"\n\n{heading}\n\n{body}\n\n{'、'.join(words)}\n\n{tail}\n"


def _parse_word_file(path: Path) -> list[str]:
    """Read a markdown file and return non-empty, non-header lines."""
    # `utf-8-sig`: the BOM a Windows editor writes would stick to the first word.
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    entries = []
    for line in lines:
        line = line.strip().lstrip("-").lstrip("*").strip()
        if line and not line.startswith("#"):
            entries.append(line)
    return entries


def _generate_cards(client: AIClient, entries: list[str],
                    system: str | None = None) -> list[dict[str, str]]:
    """Call the AI for a batch of entries and return a flat list of card dicts."""
    if not entries:
        return []

    # Written in the language of the cards: `prompts.say`, never `_()`.
    if len(entries) == 1:
        user_msg = (prompts.say("Generate the Anki card for this word/phrase:")
                    + f"\n{entries[0]}")
    else:
        joined = "\n".join(f"- {e}" for e in entries)
        user_msg = (
            prompts.say("Generate the Anki cards for the following {count} "
                        "words/phrases (hand back a JSON array):")
            .format(count=len(entries)) + f"\n{joined}"
        )

    result = client.chat_json(system or prompts.load("vocab_card"), user_msg)

    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))

    return result


def _generate_batch(client: AIClient, entries: list[str], label: str,
                    system: str | None = None, lost: list[str] | None = None,
                    notes: list[tuple[Callable[[str], None], str]] | None = None,
                    ) -> list[dict[str, str]]:
    """Generates one batch, cutting it in two when the answer comes back truncated.

    Truncation is the one failure with a known fix: the same batch would be cut
    again, where half of it fits. Other failures go to the caller, which moves on;
    `lost` receives the entries of a half dropped on the way. `notes` receives
    what is to be said of it, (console function, line), for the caller to say
    under the batch it shows; None says it at once.
    """
    def say(write: Callable[[str], None], line: str) -> None:
        if notes is None:
            write(line)
        else:
            notes.append((write, line))

    try:
        return _generate_cards(client, entries, system)
    except AITruncatedError:
        if len(entries) == 1:
            raise  # nothing left to cut: up to the caller to give this batch up

    half = len(entries) // 2
    say(console.item, counted(len(entries),
                              "Answer truncated, {label} of {count} word replayed in two "
                              "halves ({first} + {second})...",
                              "Answer truncated, {label} of {count} words replayed in two "
                              "halves ({first} + {second})...").format(
                                  label=label, count=len(entries), first=half,
                                  second=len(entries) - half))
    cards: list[dict[str, str]] = []
    for part in (entries[:half], entries[half:]):
        try:
            cards.extend(_generate_batch(client, part, label, system, lost, notes))
        except AIAuthError:
            raise  # key/quota: the next half would fail the same way
        except Exception as exc:
            # A lost half must not take the other, already generated, with it.
            say(console.failed, _("half dropped ({count} {words}): {reason}").format(
                count=len(part), words=console.plural(len(part), "word"),
                reason=console.reason(exc)))
            if lost is not None:
                lost.extend(part)
    return cards


# Why a whole run gives up. Plain English, translated where raised: a module-level
# `_()` would resolve the language at import time.
FATAL_REPORTED = "definitive AI failure reported by another batch"


def _generate_guarded(client: AIClient, entries: list[str], label: str,
                      fatal: Event, system: str | None = None,
                      lost: list[str] | None = None,
                      notes: list[tuple[Callable[[str], None], str]] | None = None,
                      ) -> list[dict[str, str]]:
    """Like `_generate_batch`, but gives up when a definitive failure is known.

    The batches run in parallel: once a key is refused, the calls in flight finish
    but the queued ones do not try.
    """
    if fatal.is_set():
        raise AIAuthError(_(FATAL_REPORTED))
    try:
        return _generate_batch(client, entries, label, system, lost, notes)
    except AIAuthError:
        fatal.set()
        raise


# ── Filtering and deduplicating ───────────────────────────────────────────────

def _filter_and_dedup(
    cards: list[dict],
    seen_expressions: set[str],
) -> tuple[list[dict], list[dict]]:
    """Filters the _skip entries and the duplicates. Hands back (valid, skipped).

    What is not a card at all (a bare string in the list) is dropped, as `kanji`
    does: one stray item must not stop the run before its cards reach Anki.
    """
    valid = []
    skipped = []

    for card in cards:
        if not isinstance(card, dict):
            continue
        # Card the AI itself passed over
        if card.get("_skip"):
            skipped.append(card)
            continue

        # `or ""`: the model may write `"Expression": null`.
        expr = str(card.get("Expression") or "").strip()
        translation = str(card.get("Translation") or "").strip()
        if not expr or not translation:
            skipped.append({**card, "_reason": _("empty Expression/Translation fields")})
            continue

        if expr in seen_expressions:
            skipped.append({**card, "_skip": True, "_reason": _("duplicate")})
            continue

        seen_expressions.add(expr)
        valid.append(card)

    return valid, skipped


# ── Lone kanji (safety net after generation) ─────────────────────────────────

def _review_single_kanji(client: AIClient, cards: list[dict]) -> tuple[list[dict], list[dict]]:
    """Offers to turn down the cards reduced to a kanji that is not a word.

    A second net for the lone kanji (語, 的, 勉...) the prompt's skip instruction
    missed. The user decides; outside a dialogue (a script, redirected input),
    the card is turned down. Hands back (cards kept, cards turned down).
    """
    flagged = kanji_word.not_words(client, [c.get("Expression", "") for c in cards])
    if not flagged:
        return cards, []

    kept: list[dict] = []
    dropped: list[dict] = []
    for card in cards:
        if card.get("Expression", "") not in flagged:
            kept.append(card)
            continue
        why = kanji_word.explained(*flagged[card.get("Expression", "")])
        line = (_("{expression} - {translation}: lone kanji, not a vocabulary word ({why})")
                if why else _("{expression} - {translation}: lone kanji, not a vocabulary word"))
        console.failed(line.format(expression=card.get("Expression", ""),
                                   translation=card.get("Translation", ""), why=why))
        choice = ask_choice(
            _("[r] remove (do not create the card)  [c] create anyway"), "rc", default="r")
        if choice == "c":
            console.item("→ " + _("card created anyway"))
            kept.append(card)
        else:
            console.item("→ " + _("card turned down"))
            dropped.append({**card, "_skip": True,
                            "_reason": _("lone kanji, not a word")})
    return kept, dropped


# ── Breaking an expression down into its words ───────────────────────────────
# A card 「お腹が空いた」 is learned as a block, its words (お腹, 空く) staying
# unknown elsewhere. The model lists them in the same answer as the card, at no
# extra call, and only those the deck lacks are generated after.

COMPONENTS_KEY = "Components"


def _pop_components(cards: list[dict]) -> list[tuple[str, str]]:
    """Drops the `Components` key from the cards; hands back [(word, source expression)].

    Not a note field, so it goes before the TSV and the send, decomposition asked
    or not. A turned-down sentence carries it too, its source being `_input`.
    """
    found: list[tuple[str, str]] = []
    for card in cards:
        raw = card.pop(COMPONENTS_KEY, None)
        if not isinstance(raw, list):
            continue
        source = card.get("Expression") or card.get("_input") or ""
        for word in raw:
            word = str(word).strip()
            if word:
                found.append((word, source))
    return found


def _new_components(pairs: list[tuple[str, str]],
                    seen_expressions: set[str]) -> list[tuple[str, str]]:
    """Keeps only the components that do not already have their card in this run.

    Compared on the bare spelling: components come without furigana (空く), cards
    with (空[す]く). A component that only repeats its source expression falls too.
    """
    seen = {kanji_word.bare_expression(e) for e in seen_expressions}
    fresh: list[tuple[str, str]] = []
    for word, source in pairs:
        bare = kanji_word.bare_expression(word)
        if not bare or bare in seen:
            continue
        seen.add(bare)
        fresh.append((word, source))
    return fresh


def _confirm_components(pairs: list[tuple[str, str]]) -> bool:
    """Shows the words drawn from the expressions (or the sentences) and lets one back out.

    Their number, hence their cost, is only known here, before the call. Outside
    a dialogue (a script, redirected input) they go through: they were asked for.
    """
    console.title(counted(len(pairs),
                          "{count} vocabulary word picked up:",
                          "{count} vocabulary words picked up:").format(count=len(pairs)))
    # One line per source entry. The pairs arrive card by card, already grouped,
    # which `groupby` needs.
    for source, group in groupby(pairs, key=lambda pair: pair[1]):
        words = "、".join(word for word, _unused in group)
        console.item(_("from {source}: {words}").format(
            source=quoted(kanji_word.plain_expression(source)), words=words))
    return ask_choice(_("[y] generate these cards  [n] no thanks"),
                      "yn", default="y") == "y"


def _decompose_wanted(args: argparse.Namespace, *, default: bool) -> bool:
    """`--decompose` / `--no-decompose`, and failing that the behaviour of the source.

    On for words typed by hand or listed in a file, off for bulk sources (PDF,
    article, JLPT level, page), which already give single words: a stray
    expression among 200 entries would add a cost that was not asked for.
    """
    choice = getattr(args, "decompose", None)
    return default if choice is None else bool(choice)


def _decompose(
    client: AIClient,
    pairs: list[tuple[str, str]],
    args: argparse.Namespace,
    out_path,
    seen_expressions: set[str],
    index: Words,
) -> tuple[list[dict], list[dict]]:
    """Generates the cards of the words drawn from the expressions. One depth
    only: a component is never broken down in its turn."""
    fresh = _new_components(pairs, seen_expressions)
    # The deck's words go before the question: the count it announces is the bill.
    known: list[dict] = []
    if not getattr(args, "force", False):
        words, known = _skip_known([word for word, _unused in fresh], index)
        fresh = [pair for pair in fresh if pair[0] in words]
    if not fresh:
        return [], known
    if not _confirm_components(fresh):
        console.item("→ " + _("components dropped"))
        return [], known + [{"_skip": True, "_input": word,
                             "_reason": _("component turned down")}
                            for word, _unused in fresh]
    cards, skipped = _process_entries(client, [word for word, _unused in fresh], args,
                                      out_path, seen_expressions, index)
    return cards, known + skipped


# ── Text extraction (vocab from a page or a file) ────────────────────────────

def _extract_vocab_entries(
    client: AIClient, title: str, lines: list[str], count: int, level: str,
) -> list[str]:
    """Asks the AI for the `count` most useful words of the text."""
    # English, like the `vocab_extract` instruction it goes with: it hands back
    # Japanese words, never card text, and lives in `prompts/structure/` alone.
    level_part = (
        f"Aim first at words of roughly JLPT level {level} "
        "(ignore the markedly easier ones)."
        if level != "auto" else
        "Ignore the ultra-basic words (です, する, 人...) in favour of words that "
        "really enrich the vocabulary."
    )
    numbered = "\n".join(f"{i}. {line}" for i, line in enumerate(lines, 1))
    user_msg = (
        f'Text "{title}":\n\n{numbered}\n\n'
        f"Extract at most {count} words. {level_part}"
    )
    result = client.chat_json(prompts.load("vocab_extract"), user_msg)
    if not isinstance(result, list):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))
    return [str(w).strip() for w in result if str(w).strip()][:count]


# ── The "jlpt" source: the words of the level the deck lacks ─────────────────
# The words of the level in the JLPT table, less those the deck already holds.

# A level holds 654 to 3,299 words, too many for one go. --count asks for more,
# and a rerun takes the next ones, the words generated being in the deck.
JLPT_DEFAULT_COUNT = 20


def _jlpt_entries(level: str, count: int, index: Words) -> list[str]:
    """Words of the level missing from the deck, the most accessible first.

    Says on the way how far the deck has got in the level.
    """
    words = jlpt.words_of(level)
    missing = [w for w in words if not index.has(w)]
    label = level if level in jlpt.LEVELS else _("every level")
    done = len(words) - len(missing)
    console.item(agreed(len(missing),
                        "{label}: {total} words in the reference table, {done}"
                        " already in the deck, {missing} missing").format(
                            label=label, total=len(words), done=done,
                            missing=len(missing)))
    if len(missing) > count:
        console.item("→ " + _("the {count} most accessible ones are generated "
                               "(--count to ask for more, replay for the next batch)").format(
                                   count=count))
    return missing[:count]


# ── The theme source: the words of a field the deck lacks ────────────────────
# No table holds the words of a theme, so the model lists more than asked, for
# the deck to take back what it holds. A rerun takes the next ones.

THEME_DEFAULT_COUNT = 20

# How many words the model is asked for against how many are kept. A closed set
# (the days of the week) hands back fewer, which is fine: it is given whole.
THEME_POOL_FACTOR = 3
THEME_POOL_MIN = 40
THEME_POOL_MAX = 150


def _list_theme_words(client: AIClient, theme: str, pool: int, level: str) -> list[str]:
    """Asks the AI for the vocabulary of a theme, the most useful word first."""
    # Written in English, like `vocab_extract`: the instruction hands back
    # Japanese words, never card text, so it lives in `prompts/structure/`.
    level_part = (
        f"Aim first at words of roughly JLPT level {level} "
        "(leave out the markedly easier ones)."
        if level != "auto" else
        "Start with the words a learner meets first."
    )
    user_msg = f'Theme: "{theme}"\n\nList at most {pool} words. {level_part}'
    result = client.chat_json(prompts.load("vocab_theme"), user_msg)
    if not isinstance(result, list):
        raise ValueError(_("unexpected JSON structure: {kind}").format(kind=type(result).__name__))
    words = [str(w).strip() for w in result if str(w).strip()]
    return list(dict.fromkeys(words))[:pool]


def _theme_entries(client: AIClient, theme: str, count: int, level: str,
                   index: Words) -> list[str]:
    """The words of the theme missing from the deck, the most accessible first.

    Says on the way how many words the theme came to and how many the deck holds.
    """
    pool = min(max(count * THEME_POOL_FACTOR, THEME_POOL_MIN), THEME_POOL_MAX)
    console.action(_("Listing the words of the theme"))
    words = _list_theme_words(client, theme, pool, level)
    if not words:
        raise RuntimeError(_("The AI found no word for this theme."))
    console.done(f"{len(words)} {console.plural(len(words), 'word')}")
    words = _apply_level(words, level)
    missing, known = split_known(words, index)
    console.item(agreed(len(missing),
                        "{total} words in the theme, {done} already in the deck,"
                        " {missing} missing").format(
                            total=len(words), done=len(known), missing=len(missing)))
    if len(missing) > count:
        console.item("→ " + _("the {count} most accessible ones are generated "
                               "(--count to ask for more, replay for the next batch)").format(
                                   count=count))
    return missing[:count]


# ── Generating in batches (shared by direct words / file / NHK) ──────────────

BATCH_SIZE = 10  # default, overridable through --batch-size

# Batches generated in parallel (--jobs). The calls and the cost stay the same,
# except that an interrupted command has paid for every batch in flight.
JOBS = 4

# `Expression` first: Anki sorts and checks duplicates on it; `Context` beside the
# Translation it completes. `Audio`, a recording made in Anki's editor, is never
# written, and last as `deck install` adds it to types that already hold notes.
FIELDS = ["Expression", "Translation", "Context", "Notes", "Example", "ExampleTranslation",
          "Audio"]


def _apply_level(entries: list[str], level: str) -> list[str]:
    """Sorts the extracted words from the most accessible to the hardest, and
    turns down those the JLPT table gives as clearly easier than the level asked
    for.

    The prompt asked for this already; here it is checked, at no cost.
    """
    kept, dropped = jlpt.prepare(entries, level)
    if dropped:
        shown = "、".join(dropped[:8])
        extra = f"... (+{len(dropped) - 8})" if len(dropped) > 8 else ""
        console.aside(counted(len(dropped),
                              "{count} word too easy for {level}: {words}{extra}",
                              "{count} words too easy for {level}: {words}{extra}").format(
                           count=len(dropped), level=level, words=shown, extra=extra))
    return kept


# A register tag the model hung under a category instead of beside it:
# `Verb::五段動詞::Register::敬語::尊敬語` is two tags, and as one it is read by
# neither the badge nor a search.
_HUNG_TAG_RE = re.compile(r"::(?=(?:Register|Speaker|Dialect)::)")


def _split_hung_tags(cards: list[dict]) -> None:
    """Separates the register tags written onto another tag."""
    for card in cards:
        tags = str(card.get("Tags", "")).split()
        split = [part for tag in tags for part in _HUNG_TAG_RE.sub(" ", tag).split()]
        if split != tags:
            card["Tags"] = " ".join(dict.fromkeys(split))


def _tag_levels(cards: list[dict]) -> None:
    """Adds the `Level::NX` tag from the local JLPT table.

    No call: a word absent from the table stays without a level.
    """
    for card in cards:
        tag = jlpt.tag_for(card.get("Expression", ""))
        if not tag:
            continue
        tags = str(card.get("Tags", "")).split()
        if tag not in tags:
            tags.append(tag)
            card["Tags"] = " ".join(tags)


def _check_readings(cards: list[dict]) -> int:
    """Has the readings reread by the dictionary; tags what does not add up.

    Drops and corrects nothing, since a rare reading may be right. Hands back the
    number of cards marked.
    """
    marked = 0
    for card in cards:
        message = dictionary.tag_card(card)
        if message:
            marked += 1
            console.item("?? " + _("{expression} - {translation}: {message}").format(
                expression=card.get("Expression", ""),
                translation=card.get("Translation", ""), message=message))
    return marked


# Marks a skipped entry already known: a flag, since its reason is a translated
# sentence.
KNOWN_FLAG = "_known"


def _skip_known(entries: list[str], index: Words) -> tuple[list[str], list[dict]]:
    """Turns down the entries already in the deck, before any AI call.

    The send would refuse them as duplicates. Hands back (remaining entries,
    entries turned down).
    """
    entries, known = split_known(entries, index)
    if known:
        shown = "、".join(word for _unused, word in known[:8])
        extra = f"... (+{len(known) - 8})" if len(known) > 8 else ""
        console.item(agreed(len(known),
                            "{count} already in the deck, not regenerated:"
                            " {words}{extra}").format(
                                count=len(known), words=shown, extra=extra))
    return entries, [
        {"_skip": True, "_input": entry, KNOWN_FLAG: True,
         "_reason": _("already in the deck ({word})").format(word=word)}
        for entry, word in known
    ]


def _process_entries(
    client: AIClient,
    entries: list[str],
    args: argparse.Namespace,
    out_path,
    seen_expressions: set[str],
    index: Words = NO_WORDS,
    decompose: bool = False,
    failed: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Generates the cards of a list of entries, in batches, with incremental TSV
    saving. Hands back (valid cards, skipped entries).

    `index` turns down the entries the deck holds, unless `args.force` asks for
    them again, and tells the model the words the deck knows either way.
    `failed` receives the entries of the batches whose call failed.
    """
    skipped_all: list[dict] = []
    if not getattr(args, "force", False):
        entries, skipped_all = _skip_known(entries, index)
    batch_size = max(1, getattr(args, "batch_size", None) or BATCH_SIZE)
    batches = [entries[i : i + batch_size] for i in range(0, len(entries), batch_size)]
    jobs = max(1, min(getattr(args, "jobs", None) or JOBS, len(batches) or 1))
    cards: list[dict] = []
    components: list[tuple[str, str]] = []

    # The known words go in the system prompt, which is cached.
    system = prompts.load("vocab_card")
    if getattr(args, "known_words", True):
        system += known_words_section(index)

    # The calls run in parallel but are collected in order, which the
    # deduplication, the lone-kanji question and the TSV depend on.
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        fatal = Event()
        # `failed` is filled from the worker threads too: `list.extend` holds the GIL.
        # What a batch has to say waits for its turn on screen.
        notes: list[list] = [[] for _ in batches]
        futures = [pool.submit(_generate_guarded, client, batch,
                               _("batch {rank}").format(rank=n), fatal, system, failed,
                               notes[n - 1])
                   for n, batch in enumerate(batches, 1)]
        try:
            for batch_num, (batch, future) in enumerate(zip(batches, futures), 1):
                # One action per batch: its rank in the label, its result at the end.
                # A lone entry has just been typed: its count would say nothing.
                among = ("" if len(batches) == 1 and len(batch) == 1
                         else counted(len(batch), "{count} entry", "{count} entries")
                         .format(count=len(batch)))
                if len(batches) > 1:
                    among = _("batch {rank}/{total}, {among}").format(
                        rank=batch_num, total=len(batches), among=among)
                console.action(_("Generating the cards"), among=among)
                try:
                    # The call is already running; the line animates while it ends.
                    raw_cards = console.while_working(future.result)
                except AIAuthError:
                    raise  # key/quota: the following batches would all fail the same way
                except Exception as exc:
                    console.failed(_("batch {rank}: {reason}, the earlier cards are saved.").format(
                        rank=batch_num, reason=console.reason(exc)))
                    if failed is not None:
                        failed.extend(batch)
                    continue
                for write, line in notes[batch_num - 1]:
                    write(line)

                valid, skipped = _filter_and_dedup(raw_cards, seen_expressions)

                for s in skipped:
                    inp = s.get("_input") or s.get("Expression") or "?"
                    # A turned-down sentence that yields its words is not a failure.
                    words = s.get(COMPONENTS_KEY) if decompose else None
                    if words:
                        console.item(
                            counted(len(words),
                                    "{entry}: {reason}, {count} word to draw from it",
                                    "{entry}: {reason}, {count} words to draw from it").format(
                                 entry=inp, reason=s.get("_reason", _("sentence")),
                                 count=len(words)))
                    else:
                        console.aside(_("{entry} skipped ({reason})").format(
                            entry=inp, reason=s.get("_reason", "?")))

                # Last net before writing: the lone kanji that are not words.
                valid, dropped = _review_single_kanji(client, valid)
                skipped.extend(dropped)

                # Popped either way: `Components` is not a note field.
                found = _pop_components(valid) + _pop_components(skipped)
                if decompose:
                    components.extend(found)

                # Local enrichments, with no AI call: JLPT level and readings.
                _split_hung_tags(valid)
                _tag_levels(valid)
                _check_readings(valid)

                cards.extend(valid)
                skipped_all.extend(skipped)

                if valid:
                    append_cards(out_path, valid, FIELDS, args.deck, args.notetype)
                console.done(f"{len(valid)} {console.plural(len(valid), 'card')}")
        finally:
            # Early exit (refused key, Ctrl+C): the queued batches are never sent.
            for future in futures:
                future.cancel()

    # Components last, once every card is known, so that none is made twice.
    if components:
        extra, extra_skipped = _decompose(
            client, components, args, out_path, seen_expressions, index)
        cards.extend(extra)
        skipped_all.extend(extra_skipped)

    return cards, skipped_all


def generate_into(client: AIClient, entries: list[str], deck: str,
                  notetype: str) -> bool | None:
    """Generates the cards of these words and sends them straight into Anki.

    For the `derive` action of `maintain`, which draws its words from a flagged
    card: the pipeline of `kotogen vocab`, with the send already decided. Hands
    back True when Anki took the send, False when it or a call failed, None when
    every word was turned down and nothing failed.
    """
    args = argparse.Namespace(output=None, send=True, format=None,
                              deck=deck, notetype=notetype)
    out_path = resolve_output_path(args, "vocab")
    index = memory.known().words(notetype)
    failed: list[str] = []
    cards, _skipped = _process_entries(client, entries, args, out_path, set(), index,
                                       failed=failed)
    if not cards:
        return False if failed else None
    return finish(cards, FIELDS, args, out_path, preview=[]) is not None


# ── Public entry point ────────────────────────────────────────────────────────


def run_vocab(args: argparse.Namespace) -> None:
    from kotogen.generators import pdf_source, pdf_web, sources

    # A PDF given through --file is a PDF source, not a word file.
    if args.file and str(args.file).lower().endswith(".pdf"):
        args.word, args.file = str(args.file), None

    client = AIClient(provider=args.provider, model=args.model)
    out_path = resolve_output_path(args, "vocab")

    # Read once per run: known entries are turned down (--force regenerates them),
    # and the model is told the deck's words either way.
    known = memory.known()
    force = getattr(args, "force", False)
    index = known.words(args.notetype)
    # Said only with Anki open (an empty deck, a missing note type), as it changes
    # the bill; with Anki closed, the welcome screen has said it already.
    if not index and not force and known.live():
        console.title(_("(Deck empty or unreadable: the words already known will "
                        "not be turned down.)"))

    all_cards: list[dict] = []
    all_skipped: list[dict] = []
    seen_expressions: set[str] = set()

    if args.file:
        if not args.file.exists():
            sys.exit(_("File not found: {path}").format(path=args.file))
        entries = _parse_word_file(args.file)
        if not entries:
            sys.exit(_("No entry found in the file."))
        console.title(args.file.name)
        console.item(counted(len(entries), "{count} entry read",
                             "{count} entries read").format(count=len(entries)))
        all_cards, all_skipped = _process_entries(
            client, entries, args, out_path, seen_expressions, index,
            _decompose_wanted(args, default=True))

    elif jlpt.is_keyword(args.word):
        # Without the deck the whole level would be generated, but an empty deck
        # is a fair answer: the connection is checked, not the index. A JSON run
        # compares with its own file, which always answers (see `memory`).
        if not known.reachable(args.notetype):
            sys.exit(_(
                "{source} source: Anki has to be open (AnkiConnect) to know which "
                "words you are missing - otherwise it is the whole level that "
                "would be generated.").format(source=quoted(jlpt.KEYWORD)))
        count = args.count if args.count is not None else JLPT_DEFAULT_COUNT
        console.title(_("JLPT vocabulary missing from {deck}").format(
            deck=quoted(known.name(args.deck))))
        entries = _jlpt_entries(args.level, count, index)
        if not entries:
            label = args.level if args.level in jlpt.LEVELS else _("the table")
            console.item(_("Nothing to generate: every word of {label} is already "
                           "in the deck.").format(label=label))
            return
        all_cards, all_skipped = _process_entries(
            client, entries, args, out_path, seen_expressions, index,
            _decompose_wanted(args, default=False))

    elif getattr(args, "theme", None):
        # The deck is not required: the model's list is bounded, and without the
        # deck it is generated whole.
        count = args.count if args.count is not None else THEME_DEFAULT_COUNT
        console.title(_("Vocabulary of the theme {theme}").format(theme=quoted(args.theme)))
        try:
            entries = _theme_entries(client, args.theme, count, args.level,
                                     NO_WORDS if force else index)
        except AIAuthError:
            raise
        except Exception as exc:
            console.close_line()
            # A model's error carries its raw answer below the first line.
            sys.exit(console.reason(exc, console.ALONE))
        if not entries:
            console.item(_("Nothing to generate: every word of the theme is already "
                           "in the deck."))
            return
        all_cards, all_skipped = _process_entries(
            client, entries, args, out_path, seen_expressions, index,
            _decompose_wanted(args, default=False))

    elif sources.is_pdf(args.word) or pdf_web.is_pdf_url(args.word):
        # The model reads the PDF in vision and extracts its words in dictionary
        # form; then the usual pipeline. A URL is downloaded first, as `reading` does.
        path = pdf_source.clean_path(args.word)
        count = args.count if args.count is not None else 0  # 0 = the maximum
        console.title(path.name)
        try:
            if pdf_web.is_pdf_url(args.word):
                console.action(_("Downloading"))
                path, _unused = console.while_working(lambda: pdf_web.fetch(args.word))
                console.done(console.size_of([path]))
            console.action(_("Picking up the words"),
                           among=(_("max {count}").format(count=count) if count
                                  else _("as many words as possible")))
            pdf_bytes = pdf_source.load_pdf(path)
            entries = pdf_source.extract_vocab(client, pdf_bytes, path.name, count, args.level)
        except Exception as exc:
            console.close_line()
            sys.exit(f"PDF{convention('colon', ': ')}"
                     f"{console.reason(exc, console.ALONE)}")
        if not entries:
            sys.exit(_("No usable vocabulary word found in this document."))
        console.done(f"{len(entries)} {console.plural(len(entries), 'word')}"
                     + convention("colon", ": ") + "、".join(entries[:15])
                     + (f"... (+{len(entries) - 15})" if len(entries) > 15 else ""))
        entries = _apply_level(entries, args.level)
        if not entries:
            sys.exit(_("Every extracted word is too easy for {level}.").format(
                level=args.level))
        all_cards, all_skipped = _process_entries(
            client, entries, args, out_path, seen_expressions, index,
            _decompose_wanted(args, default=False))

    elif sources.is_text(args.word):
        # A web page or a local file: the model picks its useful words, then the
        # usual pipeline. `text_sources` sends an NHK Easy page to the site's own
        # reader; no feed (`latest=0`): the words come from a text in hand.
        texts = sources.text_sources([args.word], mode="vocab", latest=0)

        def mine_words(source, title: str, lines: list[str]) -> bool:
            count = args.count if args.count is not None else 10
            # The pick-up is an action under the text; the cards follow below it.
            console.action(_("Picking up the words"))
            entries = _extract_vocab_entries(client, title, lines, count, args.level)
            entries = _apply_level(entries, args.level) if entries else entries
            if not entries:
                raise RuntimeError(_("No word kept in this text."))
            console.done(f"{len(entries)} {console.plural(len(entries), 'word')}"
                         + convention("colon", ": ") + "、".join(entries))
            failed: list[str] = []
            cards, skipped = _process_entries(
                client, entries, args, out_path, seen_expressions, index,
                _decompose_wanted(args, default=False), failed)
            all_cards.extend(cards)
            all_skipped.extend(skipped)
            # Handled even if nothing new came of it, its words being in the deck;
            # not when a failed call left some of them unasked.
            return not failed

        sources.each(texts, mine_words)

    else:
        # A word typed by hand is its own source: the block carries its name.
        console.title(args.word)
        all_cards, all_skipped = _process_entries(
            client, [args.word], args, out_path, seen_expressions, index,
            _decompose_wanted(args, default=True))

    # Final summary
    if not all_cards:
        msg = _("No card generated.")
        if all_skipped:
            msg += counted(len(all_skipped),
                           " ({count} entry skipped)",
                           " ({count} entries skipped)").format(count=len(all_skipped))
        # Everything already known is not a failure: said as such, not "no card".
        if all_skipped and all(s.get(KNOWN_FLAG) for s in all_skipped):
            msg = counted(
                len(all_skipped),
                "Nothing to generate: the entry is already in the deck "
                "(--force to regenerate it anyway).",
                "Nothing to generate: the {count} entries are already in the "
                "deck (--force to regenerate them anyway)."
            ).format(count=len(all_skipped))
        sys.exit(msg)

    extras = []
    if all_skipped:
        extras.append("   " + counted(
            len(all_skipped),
            "{count} entry skipped",
            "{count} entries skipped"
        ).format(count=len(all_skipped)))
    flagged = sum(1 for c in all_cards
                  if dictionary.READING_TAG in str(c.get("Tags", ""))
                  or dictionary.WORD_TAG in str(c.get("Tags", "")))
    if flagged:
        extras.append("   " + counted(flagged,
                                      "{count} card to proofread, tagged {tag} "
                                      "(reading not recognised by the dictionary)",
                                      "{count} cards to proofread, tagged {tag} "
                                      "(reading not recognised by the dictionary)").format(
                                     count=flagged, tag=quoted("Check::")))

    finish(all_cards, FIELDS, args, out_path, extras=extras, preview=[
        console.clean(f"  {i:3}. {card.get('Expression', '')} - "
                      f"{card.get('Translation', '')}")
        for i, card in enumerate(all_cards, 1)
    ])
