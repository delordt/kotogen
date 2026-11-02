"""What a card calls for: the new cards to derive from it.

Unlike the other actions, deriving leaves the card as it is. A word calls for
words (antonym, transitive twin, family), a grammar card for rules (one to tell
apart, its family, the next step), a text for its words and its grammar. What
the collection holds is taken out before anything is shown (`fresh`). The
generators make the cards, `kotogen.anki.maintain.derive` has them chosen and
sent, and `kotogen rework --task derive` writes the proposals into a file.
"""

from __future__ import annotations

from dataclasses import dataclass

from kotogen import kanji_word, prompts
from kotogen.ai_client import AIClient
from kotogen.generators import grammar
from kotogen.i18n import _
from kotogen.known import Known, Words
from kotogen.maintenance import kinds
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.review import _field, _laid_out, field_lines

# Relation handed back by the model -> what it says on screen. The keys are the
# protocol; the labels are translated where displayed. The last two are the
# program's own, for what a text holds: a word or a rule.
RELATIONS: dict[str, str] = {
    "antonym": "antonym",
    "pair": "transitive or intransitive twin",
    "family": "same family",
    "nuance": "close meaning",
    "set phrase": "set phrase",
    "contrast": "rule to tell apart",
    "step": "next step",
    "word": "word of the text",
    "rule": "grammar of the text",
}

# The relations each instruction may hand back: a word does not call for a
# `step`, and a relation of the other list is read as none.
_WORD_RELATIONS = ("antonym", "pair", "family", "nuance", "set phrase")
_RULE_RELATIONS = ("contrast", "family", "step")

# What one card may call for, as the prompts also say: past that, the words are
# a list rather than ones learnt with the card.
MAX_WORDS = 4
MAX_RULES = 3
MAX_TEXT_WORDS = 6
MAX_TEXT_RULES = 2


# Where a derived card goes: the pipeline that makes it.
VOCAB, GRAMMAR = "vocab", "grammar"


@dataclass(frozen=True)
class Proposal:
    """A word or a rule the model proposes to derive from a card."""

    word: str
    relation: str   # a key of RELATIONS, or "" when the model strayed from them
    gloss: str
    target: str = VOCAB   # the pipeline that would make it: vocab or grammar


def _read(raw, key: str, relations: tuple[str, ...], target: str,
          own: str, limit: int) -> list[Proposal]:
    """The proposals of one list of the answer, bare, once each, capped.

    With no `relations` to read, the relation is the list itself: `word` or
    `rule`, what a text proposes it holds.
    """
    found: list[Proposal] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        # Bare, whatever the model wrote: a word with furigana would be a
        # different entry for the generation and for the deck.
        word = kanji_word.bare_expression(str(item.get(key, "")))
        if not word or word == own or word in seen:
            continue
        seen.add(word)
        relation = str(item.get("relation", "")).strip().lower()
        if not relations:
            relation = key
        elif relation not in relations:
            relation = ""
        found.append(Proposal(word, relation, str(item.get("gloss", "")).strip(),
                              target))
    return found[:limit]


def propose(client: AIClient, note: dict, kind: CardKind | None = None) -> list[Proposal]:
    """Asks the model for what this card calls for."""
    kind = kind or kinds.of_note(note)
    if kind is kinds.GRAMMAR:
        return _propose_rules(client, note)
    if kind.lines:
        return _propose_from_text(client, note, kind)
    return _propose_words(client, note)


def _answer(result, key: str):
    raw = result.get(key) if isinstance(result, dict) else result
    if not isinstance(raw, list):
        raise ValueError(_("unexpected AI answer: {kind}").format(kind=type(result)))
    return raw


def _propose_words(client: AIClient, note: dict) -> list[Proposal]:
    """The words a word calls for. The card goes field by field, as the other
    actions send it."""
    lines = [prompts.say("Card:")]
    lines += [_laid_out(name, _field(note, name)) for name in kinds.VOCAB.fields]
    result = client.chat_json(prompts.load("maintain_derive"), "\n".join(lines))
    own = kanji_word.bare_expression(_field(note, "Expression"))
    return _read(_answer(result, "words"), "word", _WORD_RELATIONS, VOCAB, own, MAX_WORDS)


def _propose_rules(client: AIClient, note: dict) -> list[Proposal]:
    """The rules a grammar card calls for."""
    lines = [prompts.say("Card:")]
    lines += [_laid_out(name, _field(note, name))
              for name in ("Rule", "Sentence", "Translation", "Explanation")]
    result = client.chat_json(prompts.load("maintain_derive_grammar"), "\n".join(lines))
    own = kanji_word.bare_expression(_field(note, "Rule"))
    return _read(_answer(result, "rules"), "rule", _RULE_RELATIONS, GRAMMAR, own,
                 MAX_RULES)


def _level(note: dict) -> str:
    """The JLPT level a comprehension card carries in its tags, or ""."""
    for tag in note.get("tags") or []:
        if tag.startswith("Level::"):
            return tag[len("Level::"):]
    return ""


def _propose_from_text(client: AIClient, note: dict, kind: CardKind) -> list[Proposal]:
    """The words and the rules a text calls for, in one call."""
    text = kind.lines[0]
    lines = [_laid_out(text, "").rstrip()]
    lines += [f"{i}. {line}" for i, line in enumerate(field_lines(_field(note, text)), 1)]
    level = _level(note)
    if level:
        lines += ["", prompts.say("Level of the text: {level}").format(level=level)]
    result = client.chat_json(prompts.load("maintain_derive_passage"), "\n".join(lines))
    if not isinstance(result, dict):
        raise ValueError(_("unexpected AI answer: {kind}").format(kind=type(result)))
    return (_read(result.get("words"), "word", (), VOCAB, "", MAX_TEXT_WORDS)
            + _read(result.get("rules"), "rule", (), GRAMMAR, "", MAX_TEXT_RULES))


class Held:
    """What a collection already holds, read once for a pass and only if asked.

    `known` is the deck a pass runs on, or the file being reworked. Words and
    rules are read apart, so that a pass deriving words never reads the rules.
    """

    def __init__(self, known: Known) -> None:
        self.known = known
        self._words: Words | None = None
        self._rules: set[str] | None = None

    def __contains__(self, proposal: Proposal) -> bool:
        if proposal.target == GRAMMAR:
            if self._rules is None:
                self._rules = grammar.deck_rules(self.known, kinds.GRAMMAR.notetype)
            return grammar.knows_rule(proposal.word, self._rules)
        if self._words is None:
            self._words = self.known.words(kinds.VOCAB.notetype)
        return bool(self._words) and self._words.has(proposal.word)


def fresh(proposals: list[Proposal], known, taken: set[str]
          ) -> tuple[list[Proposal], list[Proposal]]:
    """Splits the proposals into (new, already there).

    Already there: in `known` (a `Held`, or the words of a deck), or in `taken`,
    the words picked earlier in the pass (開ける and 閉める both call for 開く).
    """
    new: list[Proposal] = []
    already: list[Proposal] = []
    for proposal in proposals:
        if isinstance(known, Held):
            held = proposal in known
        else:
            held = bool(known) and known.has(proposal.word)
        if proposal.word in taken or held:
            already.append(proposal)
        else:
            new.append(proposal)
    return new, already


def describe(proposal: Proposal) -> str:
    """One proposal on one line: `開く - to open (by itself) (transitive or intransitive twin)`."""
    line = proposal.word
    if proposal.gloss:
        line += f" - {proposal.gloss}"
    if proposal.relation:
        line += f" ({_(RELATIONS[proposal.relation])})"
    return line
