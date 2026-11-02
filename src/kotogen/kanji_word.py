"""Lone kanji: spotting an Expression reduced to ONE kanji that is not a
vocabulary word on its own (語, 的, 勉...), in order to offer to drop it.

Such a kanji (a suffix, an element of a compound) makes a card that cannot be
tested: it is offered for removal at generation time and when reviewing a deck.
`is_single_kanji` picks the candidates for free, then one AI call (`judge`)
tells 木, a word, from 語, a suffix. An AI failure or an incomplete answer gives
no verdict, and nothing is offered.
"""

from __future__ import annotations

import re

from kotogen import console, prompts
from kotogen.furigana import KANJI_RE
from kotogen.i18n import _, quoted

# The `[かな]` reading and the HTML tags of a field are not part of the written word.
_FURI_RE = re.compile(r"\[[^\]]*\]")
_TAG_RE = re.compile(r"<[^>]+>")


def bare_expression(text: str) -> str:
    """The bare written form: HTML tags, furigana and spaces removed."""
    text = _TAG_RE.sub("", str(text))
    text = _FURI_RE.sub("", text)
    return re.sub(r"\s+", "", text).strip()


def plain_expression(text: str) -> str:
    """The readable form: HTML tags and furigana removed, spaces kept.

    The display twin of `bare_expression`: without its spaces, an entry typed
    in romaji would read as one block.
    """
    text = _TAG_RE.sub("", str(text))
    text = _FURI_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def is_single_kanji(expression: str) -> bool:
    """True if the expression reduces to ONE kanji (no okurigana, no kana)."""
    bare = bare_expression(expression)
    return len(bare) == 1 and bool(KANJI_RE.match(bare))


def judge(client, kanji_list: list[str]) -> dict[str, tuple[bool, str, str]]:
    """Ask the AI about a list of lone kanji.

    Returns `{kanji: (is_a_word, reason, example)}`. A kanji absent from the
    answer, or an AI failure ({}), means unknown: the caller offers nothing. The
    instruction (`prompts/structure/kanji_word.md`) and its keys are English: it
    asks for structure, never card text.
    """
    if not kanji_list:
        return {}
    user = (
        "Are these kanji vocabulary words in their own right?\n"
        + "\n".join(f"- {k}" for k in kanji_list)
    )
    try:
        result = client.chat_json(prompts.load("kanji_word"), user)
    except Exception as exc:
        console.failed(_("{check} check unavailable: {error}").format(
            check=quoted(_("lone kanji")), error=console.reason(exc)))
        return {}

    if isinstance(result, dict):
        result = [result]
    if not isinstance(result, list):
        return {}

    verdicts: dict[str, tuple[bool, str, str]] = {}
    for item in result:
        if not isinstance(item, dict):
            continue
        kanji = str(item.get("kanji", "")).strip()
        if kanji not in kanji_list:
            continue
        verdicts[kanji] = (
            bool(item.get("word", True)),  # missing key -> "it is a word" (caution)
            str(item.get("reason", "")).strip(),
            str(item.get("example", "")).strip(),
        )
    return verdicts


def not_words(client, expressions: list[str]) -> dict[str, tuple[str, str]]:
    """Among these Expressions, those reduced to a kanji that is NOT a word.

    Returns `{expression: (reason, example)}` - empty if there is no candidate,
    if the AI did not answer, or if every candidate is a real word. One single
    AI call for the whole batch.
    """
    candidates: dict[str, list[str]] = {}
    for expr in expressions:
        if is_single_kanji(expr):
            candidates.setdefault(bare_expression(expr), []).append(expr)
    if not candidates:
        return {}

    verdicts = judge(client, sorted(candidates))
    flagged: dict[str, tuple[str, str]] = {}
    for kanji, exprs in candidates.items():
        verdict = verdicts.get(kanji)
        if verdict is None or verdict[0]:  # unknown, or a real word -> offer nothing
            continue
        for expr in exprs:
            flagged[expr] = (verdict[1], verdict[2])
    return flagged


# The example goes on the question line up to this many screen columns: it is
# meant as one everyday word, and a longer answer would crowd the question out.
EXAMPLE_COLUMNS = 12


def explained(reason: str, example: str) -> str:
    """What the model said of a lone kanji, for the line that asks about it.

    Its reason, then its example word when short; "" without a reason. The
    reason is English whatever the screen (`prompts/structure/kanji_word.md`).
    """
    if not reason:
        return ""
    if example and console.width(example) <= EXAMPLE_COLUMNS:
        return _("{reason}, e.g. {example}").format(reason=reason, example=example)
    return reason
