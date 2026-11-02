"""Proofreading readings against the MeCab dictionary (unidic-lite).

A card is tagged, never corrected, when its reading is none of the n-best
readings the dictionary gives for its spelling (今日 is きょう as well as
こんにち): permissive on purpose, better a rare mistake let through than a
correct card doubted. A spelling is tagged unknown only when the dictionary
cannot analyse it at all, since it splits even an invented word into known kanji.
"""

from __future__ import annotations

from kotogen.furigana import KANJI_RE, get_tagger, kata_to_hira, reading_key, surface_key
from kotogen.i18n import _, quoted as _quoted

# Tags filed in the user's collection: never translated or renamed, whatever the
# language of the cards, or a collection would split between two tags.
# Tag set on a card whose reading is not recognised.
READING_TAG = "Check::Reading"
# Tag set on a spelling the dictionary cannot analyse.
WORD_TAG = "Check::Word"

# Analyses asked of MeCab: 10 covers words with several readings; more adds only
# fanciful splittings, which would make the check useless.
_NBEST = 10


def _reading_of_parse(tokens) -> str:
    """Reading (hiragana) of a whole analysis, tokens concatenated."""
    parts = []
    for token in tokens:
        kana = getattr(token.feature, "kana", None)
        parts.append(kana if kana and kana != "*" else token.surface)
    return kata_to_hira("".join(parts))


def possible_readings(surface: str) -> set[str]:
    """Every reading the dictionary can produce for this spelling.

    Empty set if MeCab is unavailable: the caller then concludes nothing.
    """
    tagger = get_tagger()
    if tagger is None or not surface:
        return set()
    try:
        parses = tagger.nbestToNodeList(surface, _NBEST)
    except Exception:
        # Some fugashi versions lack nbest: one analysis beats no check.
        parses = [list(tagger(surface))]
    return {r for r in (_reading_of_parse(p) for p in parses) if r}


def best_reading(surface: str) -> str:
    """The likeliest reading according to the dictionary, or "" if it cannot say."""
    tagger = get_tagger()
    if tagger is None or not surface:
        return ""
    return _reading_of_parse(tagger(surface))


def lemma(surface: str) -> str:
    """The entry the dictionary files a spelling under, or "" if it cannot say.

    Two spellings of one word give one entry (出かける and 出掛ける: 出掛ける).
    Out of context a few old spellings are misread (上る as のぼる where it
    stands for 上がる): a caller with another way of telling should try it first.
    """
    tagger = get_tagger()
    if tagger is None or not surface:
        return ""
    tokens = list(tagger(surface))
    lemmas = [getattr(token.feature, "lemma", None) for token in tokens]
    if any(token.is_unk for token in tokens) or not all(lemmas):
        return ""
    return "+".join(lemmas)


def _is_unknown(surface: str) -> bool:
    """True if the dictionary cannot analyse this spelling at all."""
    tagger = get_tagger()
    if tagger is None:
        return False
    return any(token.is_unk for token in tagger(surface))


def check(expression: str) -> tuple[str, str] | None:
    """Check an Expression `漢字[かな]`; return (tag, explanation) or None.

    None means nothing to report, including whenever the check cannot conclude:
    no kanji, no furigana to verify, MeCab absent.
    """
    surface = surface_key(expression)
    reading = reading_key(expression)
    if not surface or not KANJI_RE.search(surface):
        return None  # all kana: no reading to contradict
    if not reading or KANJI_RE.search(reading):
        return None  # furigana absent or partial: fill_missing handles that
    if _is_unknown(surface):
        return WORD_TAG, _("spelling unknown to the dictionary")

    readings = possible_readings(surface)
    if not readings or reading in readings:
        return None
    expected = best_reading(surface)
    if not expected:
        return READING_TAG, _("unexpected reading")
    return READING_TAG, _("unexpected reading (the dictionary reads {reading})").format(
        reading=_quoted(expected))


def tag_card(card: dict) -> str:
    """Check the card, add the right tag to it, and return the explanation.

    Returns "" when there is nothing to report. The card is modified in place.
    """
    found = check(card.get("Expression", ""))
    if not found:
        return ""
    tag, message = found
    tags = str(card.get("Tags", "")).split()
    if tag not in tags:
        tags.append(tag)
    card["Tags"] = " ".join(tags)
    return message
