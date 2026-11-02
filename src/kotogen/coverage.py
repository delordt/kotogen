"""How much of a Japanese text a learner already knows, measured by the dictionary.

A model asked for a text "at N4" is not taken at its word: MeCab cuts the text
and each content word is looked up, counted in occurrences as reading research
does. Grammar words would lift every text to 98%, and proper nouns and numbers
are not learnt as words, so neither counts. As unidic cuts short units
(日本語 is 日本 + 語), a token is first tried joined to the next ones (`_JOIN_MAX`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from kotogen.furigana import get_tagger, strip_furigana

# The parts of speech of unidic that carry meaning (its `pos1`).
CONTENT = frozenset({"名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞"})

# The `pos2` set aside in any context: proper nouns (田中) and numerals (三).
_SET_ASIDE = frozenset({"固有名詞", "数詞"})

# unidic marks 非自立可能 what MAY work as grammar: a noun so marked always does
# here (the こと of ことができる), a verb only after て or で (the いる of ている).
_MAY_BE_GRAMMAR = "非自立可能"
_TIES = frozenset({"て", "で"})

# Verbs that are grammar wherever they stand (the する of 勉強する): counted,
# they would flood the measure with words no deck bothers to hold.
_GRAMMAR_VERBS = frozenset({"する", "ある", "いる", "なる", "できる"})

# What a compound of the deck may be made of: content words and affixes (the 語
# of 日本語 is a suffix to unidic). A particle ends it.
_COMPOUND_PARTS = CONTENT | {"接尾辞", "接頭辞"}

# How many unidic tokens a compound of the deck may span: 3 covers 日本語学校
# (日本 + 語 + 学校); beyond that it is a phrase.
_JOIN_MAX = 3


@dataclass(frozen=True)
class Coverage:
    """What the measure found: how many content words, how many known."""

    words: int
    known: int
    # The words not known, in dictionary form, once each and in text order:
    # what a rewrite has to replace.
    unknown: tuple[str, ...]
    # Every dictionary form met, and the text itself: what `uses` asks.
    bases: frozenset[str]
    text: str = ""

    @property
    def ratio(self) -> float:
        """The share of known words, 1.0 for a text that holds none to count."""
        return self.known / self.words if self.words else 1.0

    def uses(self, word: str) -> bool:
        """True if the text carries this word, in any of its forms.

        By its dictionary form first (食べる in 食べました), then as it is written:
        a compound the dictionary cuts in two is still in the text.
        """
        return word in self.bases or word in self.text


@dataclass(frozen=True)
class _Token:
    surface: str
    base: str
    pos1: str
    counted: bool


def _counted(pos1: str, pos2: str, base: str, before: str) -> bool:
    if pos1 not in CONTENT or pos2 in _SET_ASIDE or base in _GRAMMAR_VERBS:
        return False
    if pos2 == _MAY_BE_GRAMMAR:
        return pos1 == "動詞" and before not in _TIES
    return True


def _tokens(text: str, tagger) -> list[_Token]:
    found = []
    before = ""
    for word in tagger(text):
        feature = word.feature
        pos1 = getattr(feature, "pos1", "") or ""
        pos2 = getattr(feature, "pos2", "") or ""
        base = getattr(feature, "orthBase", "") or ""
        if not base or base == "*":
            base = word.surface
        found.append(_Token(word.surface, base, pos1,
                            _counted(pos1, pos2, base, before)))
        before = word.surface
    return found


def measure(lines: Iterable[str], knows: Callable[[str], bool]) -> Coverage | None:
    """The coverage of these lines for a learner who `knows` the words it says yes to.

    `knows` receives a word in its dictionary form (行く, not 行きました), or a
    compound put back together from several tokens. None with MeCab unavailable.
    """
    tagger = get_tagger()
    if tagger is None:
        return None
    text = "\n".join(strip_furigana(line) for line in lines)
    tokens = [token for line in text.splitlines() for token in _tokens(line, tagger)]

    words = known = 0
    unknown: list[str] = []
    bases: set[str] = set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        bases.add(token.base)
        # A compound first, and from ANY part that can open one: 日本 is a
        # proper noun to unidic and is not counted alone, but 日本語 is a word.
        joined = _compound(tokens, i, knows)
        if joined:
            words += 1
            known += 1
            bases.update(t.base for t in tokens[i:i + joined])
            i += joined
            continue
        if not token.counted:
            i += 1
            continue
        words += 1
        if knows(token.base):
            known += 1
        elif token.base not in unknown:
            unknown.append(token.base)
        i += 1
    return Coverage(words, known, tuple(unknown), frozenset(bases), text)


def _compound(tokens: list[_Token], i: int, knows: Callable[[str], bool]) -> int:
    """How many tokens from `i` make one word the learner knows, or 0.

    Longest first: 日本語学校 before 日本語. The last token is tried in its
    dictionary form too, which is how a compound verb is written in a deck
    (取り出しました -> 取り出す).
    """
    span = 0
    while (span < _JOIN_MAX and i + span < len(tokens)
           and tokens[i + span].pos1 in _COMPOUND_PARTS):
        span += 1
    for size in range(span, 1, -1):
        head = "".join(t.surface for t in tokens[i:i + size - 1])
        last = tokens[i + size - 1]
        if knows(head + last.surface) or knows(head + last.base):
            return size
    return 0
