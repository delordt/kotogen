"""The rework of a leech: a card failed over and over, made easier to learn.

A word goes through `leech_simplify`, which may add the meaning of each of its
kanji; any other kind through the `simplify` action of its own instruction
(see `review.propose_changes`). The result is a proposal, which
`kotogen.anki.maintain.leech` applies and `kotogen rework --task leech` writes
into a file.
"""

from __future__ import annotations

import re

from kotogen import prompts
from kotogen.ai_client import AIClient
from kotogen.exporter import safe_text
from kotogen.furigana import KANJI_RE
from kotogen.maintenance import kinds
from kotogen.maintenance.review import _field, _laid_out

# Drops the end of the line from an arrow "→ meaning" (already on the card) or
# from a confusion line "≠ ..." (not wanted).
_HELP_TAIL_RE = re.compile(r"\s*[→≠].*$")
# Drops the "漢字 = " prefix at the start of the line (the word is already in the
# `Expression`).
_HELP_LEAD_RE = re.compile(r"^[^=]*=\s*")


def _several_kanji(text: str) -> bool:
    """True for a word written with two kanji or more, the only one the kanji
    help serves: a lone kanji's meaning is the word's translation.

    `々` does not count: 人々 is written with one kanji.
    """
    return len(set(KANJI_RE.findall(text)) - {"々"}) >= 2


def _clean_kanji_help(text: str) -> str:
    """Keeps the meanings of the kanji only: drops "→ meaning", the confusion
    line "≠", and the redundant "漢字 = " prefix at the start of the line.

    Made display-only here, since it joins `Notes` past `_changed_fields`, which
    does that for every other field the model writes (see `exporter.safe_text`)."""
    out = []
    for line in text.split("<br>"):
        line = _HELP_TAIL_RE.sub("", line).strip()
        line = _HELP_LEAD_RE.sub("", line).strip()
        if line:
            out.append(line)
    return safe_text("<br>".join(out))


# ── Real leeches (to rework) ──────────────────────────────────────────────────

def _propose_simpler(client: AIClient, card: dict) -> dict:
    """The rework of a vocabulary leech, kanji help included."""
    # For the model, so in the language of the cards (`prompts.say`); the field
    # names are the note type's schema and stay as they are.
    empty = prompts.say("(empty)")
    lines = [prompts.say("Leech card to simplify:")]
    for f in kinds.VOCAB.fields:
        lines.append(_laid_out(f, _field(card, f) or empty))
    result = client.chat_json(prompts.load("leech_simplify"), "\n".join(lines))
    return result if isinstance(result, dict) else {}
