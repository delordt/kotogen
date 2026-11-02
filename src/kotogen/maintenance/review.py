"""What maintenance proposes for one card: the logic, and nothing around it.

A card (`{"id", "fields", "tags"}`, from a deck or a file) and an action go to
the model through the instruction of the card's kind; the answer is checked
against what the card can carry and handed back as a proposal. The search for
duplicates lives here too. Nothing here reads or writes a collection or asks
anyone: `kotogen.anki.maintain` does that around these functions for Anki, and
`kotogen.rework` writes the proposals into a file.
"""

from __future__ import annotations

import difflib
import html
import re
import unicodedata
from collections.abc import Callable

from kotogen import console, prompts
from kotogen.ai_client import AIAuthError, AIClient
from kotogen.exporter import plain_field, safe_tag, safe_text, short
from kotogen.furigana import (
    bare_kanji,
    get_tagger,
    process_furigana,
    reading_key,
    strip_furigana,
    surface_key,
)
from kotogen.i18n import _, convention, listed
from kotogen.known import card_field
from kotogen.maintenance import kinds
from kotogen.maintenance.kinds import CardKind

# Action key -> what it aims at. The key is English everywhere: code, setting,
# instruction and `--only`. The label is translated where it is displayed: a
# module-level `_()` would run before the settings are loaded.
ACTIONS: dict[str, str] = {
    "error": "possible mistake",
    "simplify": "to simplify",
    "enrich": "to enrich",
    "text": "text mistake",
    "derive": "to derive",
    "duplicate": "possible duplicate",
    "audio": "audio mistake",
    "renew": "to renew",
}

# What each action does, for the screen where one assigns them.
ACTION_DESCRIPTIONS: dict[str, str] = {
    "error": "correct the mistakes, the wrong tags included",
    "simplify": "lighten a card that is too heavy",
    "enrich": "add what is missing, the tags included",
    "text": "correct the writing of the Japanese",
    "derive": "propose new cards around this one",
    "duplicate": "find the duplicates, tell apart the same translations",
    "audio": "check the reading the speech synthesis says",
    "renew": "write a new example sentence",
}



def flag_prompt(kind: CardKind) -> str:
    """The instruction of that kind of card, in the language of the cards.

    One section per action; the user message only names the action. One literal
    per kind, not a name built from the command: the test that pairs every
    instruction with its caller reads the calls.
    """
    if kind.command == "grammar":
        return prompts.load("maintain_flag_grammar")
    if kind.command == "reading":
        return prompts.load("maintain_flag_reading")
    if kind.command == "audio":
        return prompts.load("maintain_flag_audio")
    return prompts.load("maintain_flag_vocab")


# ── Reading the cards / notes ─────────────────────────────────────────────────

# Words a translation carries without saying anything, per language of the CARDS
# (`prompts.language`), unaccented like the tokens: only those no gloss is made
# of alone (`sth`, not "something", which glosses 何か). The Japanese list holds
# the tagger's dictionary forms (為る for する); particles need none (`_TAGGED`).
_STOP_WORDS: dict[str, frozenset[str]] = {
    "fr": frozenset({"le", "la", "les", "un", "une", "des", "de", "du", "d",
                     "l", "a", "au", "aux", "en", "et", "ou", "se", "s",
                     "qqch", "qqn"}),
    "en": frozenset({"the", "a", "an", "of", "to", "be", "is", "and", "or",
                     "s", "sth", "sb", "oneself"}),
    "ja": frozenset({"為る", "有る", "居る", "成る", "事", "物", "様", "為",
                     "或る", "此の", "其の", "彼の"}),
}

# Languages of the cards written without spaces, whose glosses the tagger cuts
# (`furigana.get_tagger`), keeping the words of meaning. Without it, runs of
# kanji and katakana stand for the words, the hiragana between them for grammar.
_TAGGED = frozenset({"ja"})
_MEANINGFUL = frozenset({"名詞", "形状詞", "連体詞", "副詞", "動詞", "形容詞", "感動詞"})
_WORD_RUN_RE = re.compile(r"[㐀-䶿一-鿿々〆ヵヶ]+|[ァ-ヺー]+")


def _stop_words() -> frozenset[str]:
    """The list for the language the cards are written in.

    Empty for a language without one, whose glosses then compare a little less
    exactly.
    """
    return _STOP_WORDS.get(prompts.language(), frozenset())


def _tokens(text: str) -> set[str]:
    """Meaningful words of a translation (lower case, no accents or punctuation).

    In the language of the cards, which `Translation` is written in.
    """
    if prompts.language() in _TAGGED:
        return _tagged_tokens(text)
    text = "".join(c for c in unicodedata.normalize("NFD", text.lower())
                   if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    stop = _stop_words()
    return {t for t in text.split() if t and t not in stop}


def _tagged_tokens(text: str) -> set[str]:
    """The words of meaning of a Japanese gloss, by their dictionary form.

    たべる and 食べる are one word. Markup and readings (`漢字[かな]`) go first;
    the NFD of `_tokens` is skipped, as it would strip the kana of their dakuten.
    """
    plain = strip_furigana(html.unescape(re.sub(r"<[^>]*>", " ", text)))
    stop = _stop_words()
    tagger = get_tagger()
    if tagger is None:
        return {run for run in _WORD_RUN_RE.findall(plain) if run not in stop}
    words = set()
    for word in tagger(plain):
        if word.feature.pos1 not in _MEANINGFUL:
            continue
        lemma = (getattr(word.feature, "lemma", None) or word.surface).split("-")[0]
        if lemma and lemma != "*" and lemma not in stop:
            words.add(lemma)
    return words


def _similar(a: str, b: str) -> float:
    """Similarity ratio 0..1 between two strings."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def _field(card: dict, name: str) -> str:
    """One field of a card, "" when it has none (see `known.card_field`)."""
    return card_field(card, name)


def _laid_out(field: str, value: str) -> str:
    """One field of a card, laid out for the model: `Expression: 猫`.

    The field name is schema and stays; the colon follows the language of the
    CARDS (`prompts.say`), tight in English, spaced in French.
    """
    return prompts.say("{field}: {value}").format(field=field, value=value)


# ── Duplicate detection (multi-signal + AI judgement) ─────────────────────────

# Glued onto the last signal when a `Context` already tells the two cards apart,
# since it qualifies that signal only.
_DISTINCT_CONTEXTS = " (distinct contexts)"


def _signals(reasons: list[str], into) -> str:
    """The signals of a candidate, in the language `into` speaks.

    `into` is `_` for a screen, `prompts.say` for a user message. The marker is
    translated apart, or the catalogue would need one entry per signal and marker.
    """
    out = []
    for reason in reasons:
        base, marker, _rest = reason.partition(_DISTINCT_CONTEXTS)
        out.append(into(base) + (into(marker) if marker else ""))
    # The model reads its list as the prompts write it; a screen, as its language does.
    return listed(out) if into is _ else ", ".join(out)


def _find_duplicate_candidates(note: dict, all_notes: list[dict]) -> list[tuple[dict, list[str], int]]:
    """Looks in the whole deck for potential duplicates through several signals.

    Same or close reading, spelling and translation add up to a score. Hands
    back [(note, reasons, score)], the likeliest first: a broad filter, which the
    model and then the user settle.
    """
    nid = note["id"]
    rk, sk = reading_key(_field(note, "Expression")), surface_key(_field(note, "Expression"))
    tr = _tokens(_field(note, "Translation"))
    ctx = _tokens(_field(note, "Context"))

    out: list[tuple[dict, list[str], int]] = []
    for other in all_notes:
        if other["id"] == nid:
            continue
        ork = reading_key(_field(other, "Expression"))
        osk = surface_key(_field(other, "Expression"))
        otr = _tokens(_field(other, "Translation"))
        octx = _tokens(_field(other, "Context"))
        # Held in English and translated where used: by `_()` on screen, by
        # `prompts.say` for the model (see `_signals`), whose languages may differ.
        reasons: list[str] = []
        score = 0

        if rk and rk == ork:
            reasons.append("same reading"); score += 100
        elif rk and ork and _similar(rk, ork) >= 0.8:
            reasons.append("close reading"); score += 40

        if sk and sk == osk and sk != rk:
            reasons.append("same spelling"); score += 80
        elif sk and osk and sk != osk and _similar(sk, osk) >= 0.82:
            reasons.append("close spelling"); score += 35

        # Contexts that already tell the two cards apart cut the translation
        # signal to a third, not to nothing: a context can be badly chosen.
        if tr and tr == otr:
            reasons.append("same translation"); weight = 60
        elif tr and otr and (tr & otr) and len(tr & otr) / min(len(tr), len(otr)) >= 0.5:
            reasons.append("close translation"); weight = 30
        else:
            weight = 0
        if weight:
            if ctx and octx and ctx != octx:
                reasons[-1] += _DISTINCT_CONTEXTS
                weight //= 3
            score += weight

        if reasons:
            out.append((other, reasons, score))

    out.sort(key=lambda x: -x[2])
    return out[:25]


def _judge_duplicates(client: AIClient, note: dict, candidates: list[tuple[dict, list[str], int]]) -> dict[int, tuple[str, str]]:
    """Asks the AI to rank the candidates. Hands back {index: (verdict, reason)}.

    On an AI failure, hands back {} (one falls back on the deterministic signals).
    """
    def describe(n: dict) -> str:
        # The `Context` is part of the question: it may already tell the two apart.
        ctx = _field(n, "Context")
        shown = [(name, _field(n, name)) for name in ("Expression", "Translation")]
        if ctx:
            shown.append(("Context", ctx))
        return " | ".join(_laid_out(name, value) for name, value in shown)

    lines = [prompts.say("Target card - ") + describe(note),
             "", prompts.say("Candidates:")]
    for i, (cand, reasons, _score) in enumerate(candidates):
        lines.append(f"{i}. {describe(cand)} | " + prompts.say("signals: ")
                     + _signals(reasons, prompts.say))
    try:
        result = client.chat_json(prompts.load("maintain_duplicate"), "\n".join(lines))
    except AIAuthError:
        raise
    except Exception:
        return {}
    verdicts: dict[int, tuple[str, str]] = {}
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and "index" in item:
                verdicts[int(item["index"])] = (
                    str(item.get("verdict", "")).strip().lower(),
                    str(item.get("reason", "")).strip(),
                )
    return verdicts


def _propose_differentiation(client: AIClient, note1: dict, note2: dict) -> dict:
    """Asks the AI how to tell two close cards apart. Hands back the raw dict."""
    empty = prompts.say("(empty)")

    def describe(label, n):
        # `Context` included: the distinction mostly goes there, and the model
        # must see the one already written.
        return (f"{label}Expression={_field(n, 'Expression')} | "
                f"Translation={_field(n, 'Translation')} | "
                f"Context={_field(n, 'Context') or empty} | "
                f"Notes={_field(n, 'Notes') or empty}")
    card = prompts.say("Card {n}: ")
    user = "\n".join([describe(card.format(n=1), note1),
                      describe(card.format(n=2), note2)])
    result = client.chat_json(prompts.load("maintain_differentiate"), user)
    return result if isinstance(result, dict) else {}


# ── AI generation ─────────────────────────────────────────────────────────────

# How Anki separates the lines of a field: the export writes `<br>`, and the
# editor may have left a `<br/>` or a newline behind.
_LINE_BREAK_RE = re.compile(r"<br\s*/?>|\n", re.IGNORECASE)


def field_lines(value: str) -> list[str]:
    """The lines of a field held one sentence per line. An empty field has none."""
    return _LINE_BREAK_RE.split(value) if value.strip() else []


def _card_for_model(note: dict, kind: CardKind) -> list[str]:
    """The card laid out for the model, field by field (see `_laid_out`).

    A field held one sentence per line goes numbered: the model names the key
    line by its number, and hands the field back as an array of as many lines.
    """
    out: list[str] = []
    for name in kind.shown + kind.fields:
        value = _field(note, name)
        if name not in kind.lines:
            out.append(_laid_out(name, value))
            continue
        out.append(_laid_out(name, "").rstrip())
        out += [f"{i}. {line}" for i, line in enumerate(field_lines(value), 1)]
    return out


def _bare_kanji_report(note: dict, kind: CardKind | None = None) -> str:
    """Bare kanji (no reading) of the fields `text` corrects, e.g. 'Expression: 字'. '' if none."""
    kind = kind or kinds.of_note(note)
    parts = []
    for f in (name for name in kind.fields if name in kind.furigana):
        runs = bare_kanji(_field(note, f))
        if runs:
            parts.append(_laid_out(f, "、".join(runs)))
    return prompts.say("; ").join(parts)


def propose_changes(client: AIClient, action: str, note: dict,
                    kind: CardKind | None = None) -> dict:
    """Asks the AI for the correction of one card according to the flag action."""
    kind = kind or kinds.of_note(note)
    # For the model: in the language of the cards (`prompts.say`), the field and
    # action names aside, which are schema.
    lines = [prompts.say("Action: {action}").format(action=action)]
    # The taxonomy, being tag names and so schema, is appended rather than
    # written into each language's instruction.
    taxonomy = kind.taxonomy_for(action)
    if taxonomy:
        lines += [prompts.say("Taxonomy:"), taxonomy]
    lines += ["", prompts.say("Card:"), *_card_for_model(note, kind)]
    lines.append(prompts.say("Current tags: ")
                 + (" ".join(note.get("tags", [])) or prompts.say("(none)")))
    if action == "text":
        bare = _bare_kanji_report(note, kind)
        if bare:
            lines.append(prompts.say(
                "Automatic detection: kanji WITHOUT a reading - {bare}. Add their "
                "furigana (an answer of changed=false would be wrong).")
                .format(bare=bare))
    result = client.chat_json(flag_prompt(kind), "\n".join(lines))
    if not isinstance(result, dict):
        raise ValueError(_("unexpected AI answer: {kind}").format(kind=type(result)))
    return result


def _normalise_proposal(note: dict, proposal: dict, kind: CardKind | None = None,
                        refused: list[str] | None = None, action: str = "",
                        ) -> tuple[dict, list[str], list[str], str]:
    """Filters the proposal: keeps the real changes only. Normalises the furigana.

    Hands back (changed fields, add_tags, remove_tags, reason). What was turned
    down on the way is said in `refused`, for the screen. `action` is the one the
    proposal answers, for the tags it may not touch.
    """
    kind = kind or kinds.of_note(note)
    reason = str(proposal.get("reason", "")).strip()
    fields = _changed_fields(note, proposal.get("fields") or {}, kind, refused)
    current = set(note.get("tags", []))

    # The model never touches the `Category::…` tags, the program's trace of a
    # decision (see below), nor those the kind keeps from it (`kind.may_tag`: a
    # grammar card's rule and level, a use under `enrich`).
    def allowed(tag) -> bool:
        return (isinstance(tag, str) and bool(tag) and tag not in CATEGORY_TAGS
                and kind.may_tag(tag, action))

    add = [safe_tag(t) for t in (proposal.get("addTags") or []) if allowed(t)]
    add = [t for t in add if t and t not in current]
    remove = [t for t in (proposal.get("removeTags") or []) if allowed(t) and t in current]
    return fields, add, remove, reason


def _capitalize_first(text: str) -> str:
    """Puts a capital on the 1st letter, without touching the rest (!= str.capitalize)."""
    return text[0].upper() + text[1:] if text else text


def _as_text(value) -> str:
    """A field value as the model handed it back: text, or an array of lines."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "<br>".join(str(line).strip() for line in value)
    return str(value)


def _line_pass(name: str, kind: CardKind) -> Callable[[str], str]:
    """What each line of a field the model writes goes through (see `safe_text`).

    The furigana pass, unless the export writes that field plain on that kind of
    card (`exporter.plain_field`): a corrected field carries the readings of a
    generated one, so an answer does not stand out among its decoys.
    """
    return str if plain_field(name, kind.command) else process_furigana


def _changed_fields(note: dict, raw_fields: dict, kind: CardKind | None = None,
                    refused: list[str] | None = None) -> dict[str, str]:
    """Keeps only the fields really changed, with the readings of the export laid
    line by line (`_line_pass`; MeCab reads one sentence at a time) and a one-line
    `Translation` capitalised.

    Every field comes out as text the card can only display (`safe_text`): the
    model writes from a page nobody here has read. Compared with entities read,
    as a field may hold a bare `"` where the model's copy holds `&quot;`. What
    the kind cannot carry is dropped and said in `refused` (`_hold_together`).
    """
    kind = kind or kinds.of_note(note)
    refused = [] if refused is None else refused
    fields: dict[str, str] = {}
    for name, value in raw_fields.items():
        if name not in kind.fields:
            continue
        new = safe_text(_as_text(value), _line_pass(name, kind))
        if name == "Translation" and name not in kind.lines:
            new = _capitalize_first(new)
        if html.unescape(new) != html.unescape(_field(note, name)):
            fields[name] = new
    _hold_together(note, kind, fields, refused)
    return fields


def _hold_together(note: dict, kind: CardKind, fields: dict[str, str],
                   refused: list[str]) -> None:
    """Drops from `fields`, in place, what the card could not carry, and adds
    what the program computes from what changed."""
    colon = convention("colon", ": ")

    def turn_down(name: str, why: str) -> None:
        fields.pop(name, None)
        refused.append(f"{name}{colon}{why}")

    if kind.lines:
        # The count every paired field is held to: that of the text itself, as
        # the note carries it - a text is corrected line for line, never re-cut.
        expected = len(field_lines(_field(note, kind.lines[0])))
        for name in [n for n in fields if n in kind.lines]:
            given = len(field_lines(fields[name]))
            if expected and given != expected:
                turn_down(name, _("{given} lines for {expected}, turned down").format(
                    given=given, expected=expected))
        rank = fields.get("KeyLine", "").strip()
        if rank:
            from kotogen.generators import key_line

            if not key_line.rank(rank, expected):
                turn_down("KeyLine", _("no line {rank}, turned down").format(rank=rank))
            else:
                fields["KeyLine"] = rank

    if kind is kinds.GRAMMAR:
        _hold_gap(note, fields, turn_down)


def _hold_gap(note: dict, fields: dict[str, str], turn_down) -> None:
    """A grammar card keeps one gap, and what the program draws from it.

    The gap is normalised as at generation and the answer worked out again; a
    `Target` the translation does not contain is dropped, as the card colours it
    INSIDE the translation.
    """
    from kotogen.generators import grammar

    if "Sentence" in fields:
        if len(grammar._CLOZE_RE.findall(fields["Sentence"])) != 1:
            turn_down("Sentence", _("a gap card holds one gap exactly, turned down"))
        else:
            hint = fields.get("Hint", _field(note, "Hint"))
            (card,) = grammar._normalise_cloze([{"Sentence": fields["Sentence"],
                                                  "Hint": hint}])
            fields["Sentence"] = card["Sentence"]
            if card["Hint"] != hint:
                fields["Hint"] = card["Hint"]
            answer = grammar._to_type(card["Sentence"])
            if answer != _field(note, "Answer"):
                fields["Answer"] = answer
            if fields["Sentence"] == _field(note, "Sentence"):
                del fields["Sentence"]

    if "Target" in fields or "Translation" in fields:
        target = fields.get("Target", _field(note, "Target")).strip()
        kept = grammar._target_kept({
            "Target": target,
            "Translation": fields.get("Translation", _field(note, "Translation"))})
        if kept != target:
            if "Target" in fields:
                turn_down("Target", _("not found in the Translation, turned down"))
            elif _field(note, "Target"):
                # The translation moved and left the old target behind: it would
                # colour nothing, so it goes, in plain sight in the change.
                fields["Target"] = ""


# ── The cards of one passage ──────────────────────────────────────────────────
# A reading text or a listening extract makes one note per question, each holding
# the text, its translation and its media. Their identifiers share a stem and
# end on a rank (`RC_<name>_<fingerprint>_001`, `<media>_002`).

_ID_RANK_RE = re.compile(r"^(.+)_\d+$")


def _passage_stem(note: dict) -> str:
    match = _ID_RANK_RE.match(_field(note, "ID").strip())
    return match.group(1) if match else ""


def sharing(note: dict, kind: CardKind, fields: dict[str, str],
            passage: list[dict]) -> list[dict]:
    """The notes of the passage a change of shared fields reaches as well.

    Those that still carry what the flagged card carries: a sibling edited by
    hand since holds something else, and is left to it.
    """
    shared = [name for name in fields if name in kind.shared]
    return [other for other in passage
            if any(_field(other, name) == _field(note, name) for name in shared)]


# ── Display ───────────────────────────────────────────────────────────────────

def card_name(note: dict) -> str:
    """What names a card on screen: its word, its gap sentence, its question."""
    return short(_field(note, kinds.of_note(note).label)) or _("(no expression)")


def auto_line(mark: str, note: dict, detail: str) -> None:
    """Report of one card in one line, not a block: the automatic mode of
    `maintain`, and `rework`, which decides nothing either.

    With nothing to decide, the model's reason and the before/after would only
    drown which card and what moved.
    """
    print(f"   {mark} {card_name(note)}{convention('colon', ': ')}{detail}")


def _change_summary(fields: dict, add_tags: list[str], remove_tags: list[str]) -> str:
    """Telegraphic summary of a change, e.g. "Translation, Example, +2 tags"."""
    def tags(sign: str, names: list[str]) -> str:
        # The catalogue already keys "tag" as the VERB of the proofreading
        # menu: the tags of a note are keyed apart under their own context.
        return f"{sign}{len(names)} {console.plural(len(names), 'tag', context='note')}"

    parts = list(fields)
    if add_tags:
        parts.append(tags("+", add_tags))
    if remove_tags:
        parts.append(tags("-", remove_tags))
    return listed(parts)


# ── Card out of category ──────────────────────────────────────────────────────
# A vocabulary deck also collects grammar rules (〜ながら), whole sentences and
# fragments with no standalone use: reported and offered, never deleted outright.
# A decision put off leaves the card untouched and flagged, for the next run.
# The verdict travels in the SAME answer as the correction (key `category`), so
# every card worked on is asked about at no extra cost.

# The trace of a decision: without it, a report turned down would come back on
# every pass (laid by `anki.maintain.lone_kanji`, read by `read_category`). Anki tags, so the
# same in EVERY language of the cards: a search must not change with a setting.
CATEGORY_TAG_TODO = "Category::ToReview"   # reported, decision pending
CATEGORY_TAG_KEPT = "Category::Kept"    # you settled it: do not report it again
CATEGORY_TAGS = (CATEGORY_TAG_TODO, CATEGORY_TAG_KEPT)


# Type handed back by the AI -> what the card really is. Held in English and
# translated where it is displayed.
CATEGORY_LABELS: dict[str, str] = {
    "grammar": "grammar rule: its place is in the grammar deck",
    "sentence": "whole sentence: a reading card, or a word to draw from it",
    "fragment": "fragment with no standalone use: nothing to review on it",
}

# How to remake it in the right place, when a command answers that.
CATEGORY_HINTS: dict[str, str] = {
    "grammar": 'kotogen grammar "{expr}"',
}


def read_category(note: dict, proposal: dict) -> tuple[str, str] | None:
    """"Out of category" verdict of an AI answer: (type, reason), or None.

    None as soon as the key is missing, its type unknown, or the note already
    carries `Category::Kept`: a decision taken is not asked for again.
    """
    raw = proposal.get("category")
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type", "")).strip().lower()
    if kind not in CATEGORY_LABELS:
        return None
    if CATEGORY_TAG_KEPT in (note.get("tags") or []):
        return None
    return kind, str(raw.get("reason", "")).strip()


def _proposed_deletion(proposal: dict) -> int:
    """Card the AI proposes to delete: 1, 2, or 0 when it proposes none.

    The model writes sometimes `1`, sometimes `"card2"`: only the final digit
    counts. Any other answer (absent, "none", null...) is worth "delete nothing".
    """
    raw = str(proposal.get("delete", "")).strip()
    return int(raw[-1]) if raw and raw[-1] in "12" else 0


# ── Translation group: the cards that ask the same question ──────────────────
# The duplicate flag also covers confusion: two different words with one
# translation (勤労, 仕事) must be told apart. The whole batch sharing it is
# decided in one call, since contexts only make sense read against each other.

def _translation_key(note: dict) -> str:
    """What the translation -> Japanese front really asks: the translation as it reads.

    Case, spacing and markup aside, nothing is taken out: unlike `_tokens`, it
    keeps `Salé` apart from `Sale`.
    """
    text = html.unescape(re.sub(r"<[^>]*>", " ", _field(note, "Translation")))
    return " ".join(unicodedata.normalize("NFC", text.lower()).split())


def _translation_group(note: dict, all_notes: list[dict]) -> list[dict]:
    """The cards of the deck asking the SAME question as this one, its own included.

    Identical translations, not close ones, as the front shows only `Translation`
    and `Context`. The flagged card comes first.
    """
    key = _translation_key(note)
    if not key:
        return [note]
    return [note] + [n for n in all_notes
                     if n["id"] != note["id"] and _translation_key(n) == key]


def _identical_words(group: list[dict]) -> list[list[dict]]:
    """Cards of the batch that are mechanically the SAME word, in bunches of 2 or more.

    Same reading and spelling once the furigana are removed (仕[し]事[ごと] and
    仕事[しごと]), so no call is needed. Settled BEFORE the batch is told apart,
    which would invent a difference between them.
    """
    clusters: dict[tuple[str, str], list[dict]] = {}
    for n in group:
        expr = _field(n, "Expression")
        key = (reading_key(expr), surface_key(expr))
        if not any(key):
            continue
        clusters.setdefault(key, []).append(n)
    return [c for c in clusters.values() if len(c) > 1]


def _propose_group_contexts(client: AIClient, group: list[dict]) -> dict:
    """Asks in ONE call for the `Context` of each card of the batch. Hands back the raw dict."""
    # For the model: in the language of the cards (`prompts.say`).
    empty = prompts.say("(empty)")
    lines = [prompts.say("Translation they share: ") + _field(group[0], "Translation"),
             "", prompts.say("Cards:")]
    for i, n in enumerate(group, 1):
        badges = " ".join(t for t in n.get("tags") or [] if t.startswith(REGISTER_TAGS))
        lines.append(f"{i}. Expression={_field(n, 'Expression')} | "
                     f"Context={_field(n, 'Context') or empty} | "
                     f"Notes={_field(n, 'Notes') or empty}"
                     + (f" | Tags={badges}" if badges else ""))
    result = client.chat_json(prompts.load("maintain_group_context"), "\n".join(lines))
    return result if isinstance(result, dict) else {}


# Tags a vocabulary card shows as badges on both backs, never with the question:
# the model is told them so that a context can say the register. Schema, not text.
REGISTER_TAGS = ("Register::", "Speaker::", "Dialect::")

# What the batch may touch: what tells cards apart, and the `Translation` of a
# card translated too broadly, which the right one takes out of the batch. The
# `Expression` has its own flags.
_GROUP_FIELDS = ("Translation", "Context", "Notes")

# What a vocabulary translation never holds: a bracket, a semicolon, a slash.
_LISTED_OR_QUALIFIED = re.compile(r"[()（）;；/／]")


def _still_told_apart(group: list[dict],
                      changes: list[tuple[dict, dict]]) -> list[tuple[dict, dict]]:
    """The changes, their contexts taken back if the batch would stop telling apart.

    Checks what the instruction asks: no second card without a context, no two
    reading the same on the `Production` front (a card given a new translation
    leaves the batch). On failure every context goes back, with the notes of a
    card whose context was reworded, since the new context took from them.
    """
    changed = {n["id"]: f for n, f in changes}
    staying = [n for n in group if "Translation" not in changed.get(n["id"], {})]

    def face(note: dict, applied: bool) -> str:
        fields = changed.get(note["id"], {}) if applied else {}
        context = fields.get("Context", _field(note, "Context"))
        return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", context)).lower().split())

    before = [face(n, False) for n in staying]
    after = [face(n, True) for n in staying]
    bare = lambda faces: sum(1 for text in faces if not text)
    if bare(after) <= max(1, bare(before)) and len(set(after)) >= len(set(before)):
        return changes
    kept = []
    for note, fields in changes:
        fields = dict(fields)
        if fields.pop("Context", ""):
            fields.pop("Notes", None)
        if fields:
            kept.append((note, fields))
    return kept


def _read_group_proposal(group: list[dict],
                         proposal: dict) -> tuple[list[tuple[dict, dict]], list[list[dict]]]:
    """Strips the answer down: ([(note, changed fields)], [bunches of duplicates]).

    The numbers outside the batch are ignored: better to apply what is usable than
    to reject the whole answer over one faulty index.
    """
    def card(n) -> dict | None:
        try:
            i = int(n)
        except (TypeError, ValueError):
            return None
        return group[i - 1] if 1 <= i <= len(group) else None

    changes: list[tuple[dict, dict]] = []
    for item in proposal.get("cards") or []:
        if not isinstance(item, dict):
            continue
        note = card(item.get("n"))
        if note is None:
            continue
        fields = _changed_fields(note, {k: v for k, v in item.items() if k in _GROUP_FIELDS})
        # A qualifier in brackets or two senses side by side is a context moved
        # into the question, not a translation set right; the rest still holds.
        if _LISTED_OR_QUALIFIED.search(fields.get("Translation", "")):
            del fields["Translation"]
        if fields:
            changes.append((note, fields))
    changes = _still_told_apart(group, changes)

    clusters: list[list[dict]] = []
    for raw in proposal.get("duplicates") or []:
        notes = [c for c in map(card, raw) if c is not None] if isinstance(raw, list) else []
        if len(notes) > 1:
            clusters.append(notes)
    return changes, clusters


def _probable_duplicates(candidates: list[tuple[dict, list[str], int]],
                         verdicts: dict[int, tuple[str, str]]) -> list[int]:
    """Indices of the candidates judged duplicate/variant, the most likely first."""
    rank = {"duplicate": 0, "variant": 1}
    return sorted(
        (i for i in range(len(candidates)) if verdicts.get(i, ("", ""))[0] in rank),
        key=lambda i: (rank[verdicts[i][0]], -candidates[i][2]),
    )
