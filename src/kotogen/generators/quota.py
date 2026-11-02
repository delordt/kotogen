"""The number of questions a piece of content justifies.

For reading and listening cards the count is a ceiling, never a target: a quota
on short content breeds redundant or guessable questions. Under `--count auto`
(the default) the ceiling follows the length of the content, computed here with
no AI call rather than left to the model it bounds. Vocabulary and grammar
counts are orders and do not come through here.
"""

from __future__ import annotations

from collections.abc import Iterable

from kotogen import console, furigana, prompts
from kotogen.exporter import short
from kotogen.i18n import _, counted

# One question per this many Japanese characters (6 to 8 for an NHK Easy article),
# generous on purpose: it catches runaway output, where set on the typical case
# it would become the quota.
CHARS_PER_QUESTION = 30

# Pages count for a mini-book, whose pictures carry meaning: a Tadoku album
# would otherwise be worth one question. A page and a half cannot be written
# here: 2 is the step closest to double.
PAGES_PER_QUESTION = 2

# The lowest ceiling: a three-line dialogue sometimes supports several
# questions, and the model is not bound to write them.
FLOOR = 4

# The hard ceiling of auto mode: beyond it one source becomes a whole deck, and
# its call costs as much.
CEILING = 24

# Below this many Japanese characters the model is not called on a block nobody
# chose (`audio_split`): a shadowing line measures 11, the shortest N5 exchange 18.
MIN_CHARS = 16


def japanese_chars(lines: Iterable[str]) -> int:
    """The real weight of the content: its Japanese characters, furigana aside.

    Punctuation and speaker labels (`A：`) do not count either.
    """
    plain = furigana.strip_furigana("\n".join(lines))
    return sum(len(run) for run in furigana.JP_RUN_RE.findall(plain))


def auto_max(lines: Iterable[str], *, pages: int = 0) -> int:
    """The ceiling this content carries by itself, between FLOOR and CEILING."""
    justified = japanese_chars(lines) // CHARS_PER_QUESTION
    if pages:
        justified = max(justified, pages // PAGES_PER_QUESTION)
    return max(FLOOR, min(CEILING, justified))


def carries_a_question(lines: Iterable[str]) -> bool:
    """Does this content justify calling the AI at all?

    Decided here for free: the model can be told to return nothing, but every
    block it drops is a call paid for.
    """
    return japanese_chars(lines) >= MIN_CHARS


def resolve(count: int | None, lines: Iterable[str], *, pages: int = 0) -> int:
    """The effective ceiling: the one asked for (`--count N`), or the content's."""
    return count if count else auto_max(lines, pages=pages)


def instruction(limit: int) -> str:
    """The sentence sent to the model - a ceiling, and said as such.

    Through `prompts.say` rather than `_()`: it follows the language of the
    cards, which may differ from the screen's.
    """
    return prompts.say(
        "Generate AT MOST {limit} card(s): as many as the content really "
        "supports, not one more. It is a ceiling, not a target - do not invent "
        "any question to reach it."
    ).format(limit=limit)


def announce() -> str:
    """The label of the action, without the ellipsis `console.action` adds.

    The ceiling is left out: it is a safety bound, not a promise.
    """
    return _("Generating the cards")


def preview(cards: list[dict]) -> list[str]:
    """The closing block's lines for question cards, listening or reading.

    Handed to `finish`, which calls it on the cards that go out: one set aside
    for proofreading at the last moment (the "p" setting) is not listed.
    """
    return [f"  {i:3}. [{card['ID']}] {short(card.get('Question', ''), 45)}"
            for i, card in enumerate(cards, 1)]


def enforce(cards: list[dict], limit: int) -> list[dict]:
    """Truncate at the ceiling if the model went over it.

    The extra cards are already paid for; kept, they would cost again in reviews.
    """
    if len(cards) <= limit:
        return cards
    console.aside(counted(len(cards) - limit,
                          "{count} cards returned for a ceiling of {limit}: "
                          "the last one is dropped.",
                          "{count} cards returned for a ceiling of {limit}: "
                          "the last {extra} are dropped.")
                  .format(count=len(cards), limit=limit, extra=len(cards) - limit))
    return cards[:limit]
