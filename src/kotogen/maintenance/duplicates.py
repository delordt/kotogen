"""Duplicates among the cards that are not words: what looks alike, and what
the model says of it.

The vocabulary keeps its search in `review`. Two grammar cards may ask the same
question, or be two cards the front cannot tell apart (ながら / つつ under one
"while"), which their hints then separate. A reading or listening passage may
come in twice (found without a call, by its text or its media), and two questions
of one passage may ask the same thing (one call per passage). What to delete or
tell apart is decided in `kotogen.anki.maintain.duplicates`.
"""

from __future__ import annotations

import re

from kotogen import prompts
from kotogen.ai_client import AIClient
from kotogen.furigana import surface_key
from kotogen.maintenance import kinds
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.review import (
    _changed_fields,
    _field,
    _laid_out,
    _passage_stem,
    _similar,
    _tokens,
    field_lines,
)

# A grammar card is compared on its sentence without its gap marker, readings,
# spaces and punctuation.
_CLOZE_MARK_RE = re.compile(r"\{\{c\d+::(.+?)(?:::[^}]*)?\}\}")
_NOT_TEXT_RE = re.compile(r"[\s、。，．！？!?,.「」『』（）()・…]")

# How close two sentences have to be for the model to be asked about them.
_CLOSE_SENTENCE = 0.8

# The candidates one call judges, the likeliest first: past that, the list is
# the rule's whole series and no longer its duplicates.
_CANDIDATES_MAX = 10

# The verdicts of the grammar judgement: the protocol, compared as it stands.
DUPLICATE, CONFUSABLE = "duplicate", "confusable"

# Only the hints tell two confusable cards apart: the sentence and its
# translation are what the card is, and a rewrite of them has its own flags.
_TELLING_FIELDS = ("Nuance", "Hint")


# ── Grammar ───────────────────────────────────────────────────────────────────

def _sentence_key(note: dict) -> str:
    sentence = _CLOZE_MARK_RE.sub(r"\1", _field(note, "Sentence"))
    return _NOT_TEXT_RE.sub("", surface_key(sentence))


def grammar_candidates(note: dict, all_notes: list[dict]) -> list[tuple[dict, list[str]]]:
    """The cards worth asking the model about, with what brought them in.

    A close sentence or the same translation. The same rule alone brings nothing
    in: a rule is learnt on several sentences.
    """
    key = _sentence_key(note)
    translation = _tokens(_field(note, "Translation"))
    found: list[tuple[int, dict, list[str]]] = []
    for other in all_notes:
        if other["id"] == note["id"]:
            continue
        # Held in English and translated where they are shown: `_` on the
        # screen, `prompts.say` in the message.
        reasons: list[str] = []
        score = 0
        other_key = _sentence_key(other)
        if key and key == other_key:
            reasons.append("same sentence"); score += 100
        elif key and other_key and _similar(key, other_key) >= _CLOSE_SENTENCE:
            reasons.append("close sentence"); score += 50
        if translation and translation == _tokens(_field(other, "Translation")):
            reasons.append("same translation"); score += 60
        if not reasons:
            continue
        if _field(other, "Rule") and _field(other, "Rule") == _field(note, "Rule"):
            reasons.append("same rule"); score += 20
        found.append((score, other, reasons))
    found.sort(key=lambda item: -item[0])
    return [(other, reasons) for _score, other, reasons in found[:_CANDIDATES_MAX]]


def _describe_gap(note: dict) -> str:
    return " | ".join(_laid_out(name, _field(note, name))
                      for name in ("Rule", "Sentence", "Translation", "Target", "Hint",
                                   "Nuance") if _field(note, name))


def judge_grammar(client: AIClient, note: dict,
                  candidates: list[tuple[dict, list[str]]]) -> dict[int, dict]:
    """The verdict of the model on each candidate: {index: its answer}."""
    lines = [prompts.say("Target card - ") + _describe_gap(note), "",
             prompts.say("Candidates:")]
    for i, (other, reasons) in enumerate(candidates):
        lines.append(f"{i}. {_describe_gap(other)} | " + prompts.say("signals: ")
                     + ", ".join(prompts.say(reason) for reason in reasons))
    result = client.chat_json(prompts.load("maintain_duplicate_grammar"), "\n".join(lines))
    verdicts = result.get("verdicts") if isinstance(result, dict) else result
    out: dict[int, dict] = {}
    for item in verdicts if isinstance(verdicts, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(candidates):
            item["verdict"] = str(item.get("verdict", "")).strip().lower()
            out[index] = item
    return out


def _telling(note: dict, raw) -> dict[str, str]:
    """The hints proposed to tell a card apart, the hints only."""
    raw = raw if isinstance(raw, dict) else {}
    return _changed_fields(note, {k: v for k, v in raw.items() if k in _TELLING_FIELDS},
                           kinds.GRAMMAR)


# ── Reading and listening ─────────────────────────────────────────────────────

def _text_key(note: dict, kind: CardKind) -> str:
    return _NOT_TEXT_RE.sub("", surface_key(" ".join(
        field_lines(_field(note, kind.lines[0])))))


def twin_passages(note: dict, all_notes: list[dict],
                  kind: CardKind) -> dict[str, list[dict]]:
    """The other passages that carry the same matter: {stem: their notes}.

    The same text, or the same media file, which also catches one recording
    transcribed twice in different words. No call.
    """
    stem = _passage_stem(note)
    key = _text_key(note, kind)
    media = {_field(note, name) for name in ("Audio", "Video") if _field(note, name)}
    twins: dict[str, list[dict]] = {}
    for other in all_notes:
        other_stem = _passage_stem(other)
        if other["id"] == note["id"] or (stem and other_stem == stem):
            continue
        same_media = bool(media & {_field(other, name) for name in ("Audio", "Video")})
        if (key and key == _text_key(other, kind)) or same_media:
            twins.setdefault(other_stem or str(other["id"]), []).append(other)
    return twins


def _questions_message(note: dict, kind: CardKind, questions: list[dict]) -> str:
    """The passage and its questions, numbered, the flagged one named."""
    lines = [_laid_out(kind.lines[0], "").rstrip()]
    lines += [f"{i}. {line}"
              for i, line in enumerate(field_lines(_field(note, kind.lines[0])), 1)]
    lines += ["", prompts.say("Questions:")]
    for i, question in enumerate(questions, 1):
        lines.append(f"{i}. " + " | ".join(
            _laid_out(name, _field(question, name))
            for name in ("Question", "Answer", "KeyLine")))
    lines += ["", prompts.say("Target question: {n}").format(n=1)]
    return "\n".join(lines)


def same_questions(client: AIClient, note: dict, kind: CardKind,
                   others: list[dict]) -> list[tuple[dict, str]]:
    """The questions of the passage that ask what the flagged one asks."""
    questions = [note, *others]
    result = client.chat_json(prompts.load("maintain_duplicate_questions"),
                              _questions_message(note, kind, questions))
    raw = result.get("duplicates") if isinstance(result, dict) else result
    found: list[tuple[dict, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        if 2 <= n <= len(questions):
            found.append((questions[n - 1], str(item.get("reason", "")).strip()))
    return found
