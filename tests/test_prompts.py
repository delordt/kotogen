"""Loading the instructions sent to the model.

A missing or truncated prompt breaks nothing visible, the model just answers
worse: every instruction must exist, arrive whole, and be asked for. Every
language folder carries the same twenty-two and never stands in for another; the
thirteen that hand back structure live in `structure/`. The fragments the code
composes around an instruction are checked in both directions.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from kotogen import prompts
from kotogen.anki import templates as card_templates

SRC = Path(__file__).resolve().parent.parent / "src" / "kotogen"

# The twenty-two that ask the model for CARD TEXT, which every language carries.
# `ask` is one, though it declares no JSON answer: its writes land on a card.
CARD_TEXT = {
    "vocab_card", "grammar_card", "reading_card", "audio_card", "nhk_card",
    "kanji_card", "leech_simplify", "maintain_flag_vocab", "maintain_flag_grammar",
    "maintain_flag_reading", "maintain_flag_audio", "maintain_derive",
    "maintain_derive_grammar", "maintain_derive_passage", "maintain_audio_transcript",
    "maintain_duplicate", "maintain_duplicate_grammar", "maintain_duplicate_questions",
    "maintain_differentiate", "maintain_group_context", "ask", "vocab_fields",
}

# Included only (`{{include:}}`): the vocabulary field rules shared by the five
# instructions writing a `Context` or a `Notes`. It declares no answer.
FRAGMENTS = {"vocab_fields"}

# The thirteen that hand back STRUCTURE, in `structure/`. Listed by hand: a set
# read off the folders would agree with a file moved between them.
STRUCTURAL = {
    "audio_split", "grammar_detect", "grammar_page", "kanji_word",
    "pdf_arbitration", "pdf_error_contract", "pdf_items",
    "pdf_reading", "pdf_texts", "pdf_vocab", "reading_compose", "vocab_extract",
    "vocab_theme",
}


def _asked_for() -> set[str]:
    """Every instruction something asks for, by name.

    Read off the `prompts.load` calls and the `{{include:}}` of the instructions
    themselves: `pdf_error_contract` only arrives that way.
    """
    found = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "load"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "prompts"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                found.add(node.args[0].value)
    # `structure/` too, as `names()` walks it: the PDF extractions there include
    # the contract, which the languages alone would leave orphaned.
    for name in [*prompts.languages(), prompts.STRUCTURE]:
        for path in prompts.folder(name).glob("*.md"):
            found |= set(prompts._INCLUDE_RE.findall(path.read_text(encoding="utf-8")))
    return found


def test_every_instruction_is_shipped_and_asked_for():
    """No orphan file, no call without a file."""
    assert _asked_for() == set(prompts.names())


@pytest.mark.parametrize("name", sorted(prompts.names()))
def test_no_instruction_is_empty_or_truncated(name):
    text = prompts.load(name)
    assert len(text) > 200, "instruction suspected of truncation"
    assert "{{include:" not in text, "include not resolved"


def test_a_missing_instruction_says_so(monkeypatch, tmp_path):
    """A missing instruction raises: an empty prompt would go out to the model."""
    monkeypatch.setattr(prompts, "DIR", tmp_path)
    prompts._read.cache_clear()
    with pytest.raises(RuntimeError) as excinfo:
        prompts.load("absent")
    assert "not found" in str(excinfo.value)
    prompts._read.cache_clear()


def test_an_include_is_resolved(monkeypatch, tmp_path):
    """The PDF extractions share their error contract rather than copy it."""
    folder = tmp_path / prompts.language()
    folder.mkdir()
    (folder / "part.md").write_text("the shared piece\n", encoding="utf-8")
    (folder / "whole.md").write_text(
        "before\n{{include:part}}\nafter\n", encoding="utf-8")
    monkeypatch.setattr(prompts, "DIR", tmp_path)
    prompts._read.cache_clear()
    try:
        # The include line goes as one block, line break included: no empty line.
        assert prompts.load("whole") == "before\nthe shared piece\nafter\n"
    finally:
        prompts._read.cache_clear()


def test_the_error_contract_really_is_in_every_pdf_prompt():
    contract = prompts.load("pdf_error_contract")
    for name in ("pdf_vocab", "pdf_texts", "pdf_reading"):
        assert contract in prompts.load(name)


# ── One folder per language of the cards ─────────────────────────────────────

def test_the_two_folders_account_for_every_instruction():
    assert set(prompts.names()) == CARD_TEXT | STRUCTURAL
    assert set(prompts.names(prompts.STRUCTURE)) == STRUCTURAL


def test_structure_is_not_offered_as_a_language_of_the_cards():
    """Listed, it would show in the language menu; `all.lang=structure` means
    nothing."""
    assert prompts.STRUCTURE not in prompts.languages()
    assert prompts.languages()[0] == prompts.SOURCE


@pytest.mark.parametrize("lang", prompts.languages())
def test_a_language_carries_the_card_text_instructions_and_only_those(lang):
    """EVERY language is the twenty-two that ask for card text, the same ones.

    Not one more: a structural copy is a second file to keep in step. Not one
    fewer: card text asked for in the wrong language is what the split stops.
    """
    assert set(prompts.names(lang)) == CARD_TEXT


def test_an_instruction_is_read_in_the_language_of_the_cards():
    prompts.use("en")
    assert prompts.load("grammar_card") == (
        prompts.folder("en") / "grammar_card.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("lang", prompts.languages())
def test_a_structural_instruction_is_read_from_the_structure_folder(lang):
    """No language holds `audio_split.md`: all read the one in `structure/`."""
    prompts.use(lang)
    assert prompts.load("audio_split") == (
        prompts.folder(prompts.STRUCTURE) / "audio_split.md").read_text(encoding="utf-8")


def test_a_card_text_instruction_never_comes_back_in_the_other_language(
        monkeypatch, tmp_path):
    """`fr/` has the instruction, `en/` does not, and the cards are asked for in
    English: it raises rather than fill an English deck with French cards."""
    (tmp_path / "en").mkdir()
    (tmp_path / "en" / "nhk_card.md").write_text("x" * 300, encoding="utf-8")
    (tmp_path / "fr").mkdir()
    (tmp_path / "fr" / "vocab_card.md").write_text("consigne", encoding="utf-8")
    monkeypatch.setattr(prompts, "DIR", tmp_path)
    prompts._read.cache_clear()
    try:
        prompts.use("en")
        with pytest.raises(RuntimeError) as excinfo:
            prompts.load("vocab_card")
        assert "not found" in str(excinfo.value)
    finally:
        prompts._read.cache_clear()


def test_an_unknown_language_falls_back_on_the_source_language():
    """English, as a missing screen string shows its English key."""
    assert prompts.use("kl") == prompts.SOURCE


def test_the_language_of_the_cards_comes_from_the_template_setting(monkeypatch):
    """`all.lang` picks the folder of the instructions, and so what the cards
    are asked for in; it marks no template block, a card printing no prose."""
    card_templates.set_one("all.lang", "fr")
    monkeypatch.setattr(prompts, "_language", None)
    assert prompts.language() == "fr"
    card_templates.set_one("all.lang", "en")
    monkeypatch.setattr(prompts, "_language", None)
    assert prompts.language() == "en"


def test_a_profile_that_names_no_language_gets_the_source_one(monkeypatch):
    monkeypatch.setattr(prompts, "_language", None)
    assert prompts.language() == prompts.SOURCE


# Protocol names: a JSON key, or a verdict written like one
# (`- "duplicate": same word`). Both are a quoted name and a colon.
_PROTOCOL_RE = re.compile(r'"(\w+)"\s*:')


@pytest.mark.parametrize("name", sorted(CARD_TEXT))
@pytest.mark.parametrize(
    "lang", [name for name in prompts.languages() if name != prompts.SOURCE])
def test_a_translated_instruction_asks_for_the_same_protocol(lang, name):
    """The JSON the model answers with does NOT move with the language.

    A translated key (`"Traduction"` for `"Translation"`) still parses, but every
    field asked for is missing and the card comes out empty.
    """
    def protocol(folder):
        return set(_PROTOCOL_RE.findall(
            (folder / f"{name}.md").read_text(encoding="utf-8")))

    theirs = protocol(prompts.folder(lang))
    ours = protocol(prompts.folder(prompts.SOURCE))
    assert theirs == ours, (
        f"{lang}/{name}.md: {ours - theirs} dropped, {theirs - ours} invented")


# Each card-text instruction tells the model, in its own language, to keep the
# keys: a model reading a French sample would otherwise answer in French. One
# wording per language, by hand, as no scan matches a sentence across languages.
PROTOCOL_SAID = {
    "en": ("the protocol", "the note type's schema"),
    "fr": ("le protocole", "le schéma du type de notes"),
    "ja": ("プロトコル", "ノートタイプのスキーマ"),
}

# `ask` has no protocol to protect: it drives tools, and the field names it
# writes into come from `deck_scope` at run time.
NO_PROTOCOL = {"ask"}


@pytest.mark.parametrize("lang", sorted(prompts.languages()))
def test_every_language_of_the_cards_says_how_it_names_the_protocol(lang):
    """A language with no entry would skip the test under this one."""
    assert lang in PROTOCOL_SAID, (
        f"{lang}: add the wording its instructions name the protocol with")


@pytest.mark.parametrize("name", sorted(CARD_TEXT - NO_PROTOCOL - FRAGMENTS))
@pytest.mark.parametrize("lang", sorted(prompts.languages()))
def test_a_card_text_instruction_tells_the_model_to_keep_the_protocol(lang, name):
    """Said to the model, in the language the instruction is written in."""
    text = " ".join((prompts.folder(lang) / f"{name}.md")
                    .read_text(encoding="utf-8").split())
    assert any(said in text for said in PROTOCOL_SAID[lang]), (
        f"{lang}/{name}.md says nothing about the keys staying as they are "
        f"(expected one of {PROTOCOL_SAID[lang]})")


# ── What the code composes around an instruction ─────────────────────────────

# Fragments held in a table rather than at their call site (no module-level
# `prompts.say`): listed by hand, as the call site passes a name.
def _table_driven() -> set[str]:
    from kotogen.generators import audio, deck_story
    from kotogen.maintenance import review

    return ({audio.CHOICE_INSTRUCTION, audio.FIGURE_INSTRUCTION, audio.CHOICE_QUESTION}
            | {"same reading", "close reading", "same spelling", "close spelling",
               "same translation", "close translation", review._DISTINCT_CONTEXTS,
               "same sentence", "close sentence", "same rule"}
            # The shapes a deck text names itself by in `Source`: from `--shape`.
            | set(deck_story.SHAPES))


def _said() -> set[str]:
    """Every `prompts.say("literal")` of the sources."""
    found = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "say"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "prompts"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                found.add(node.args[0].value)
    return found


@pytest.mark.parametrize(
    "lang", [name for name in prompts.languages() if name != prompts.SOURCE])
def test_every_composed_fragment_has_its_entry(lang):
    missing = sorted((_said() | _table_driven()) - set(prompts._wording(lang)))
    assert not missing, f"{lang}: fragments with no entry: {missing[:3]}"


@pytest.mark.parametrize(
    "lang", [name for name in prompts.languages() if name != prompts.SOURCE])
def test_no_entry_is_left_behind_by_its_call_site(lang):
    """The other direction: an entry nothing asks for, left by a reworded
    fragment."""
    stale = sorted(set(prompts._wording(lang)) - (_said() | _table_driven()))
    assert not stale, f"{lang}: entries nothing asks for: {stale[:3]}"


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize(
    "lang", [name for name in prompts.languages() if name != prompts.SOURCE])
def test_a_translated_fragment_carries_the_same_placeholders(lang):
    """A `{count}` lost in translation is a KeyError at generation time."""
    guilty = [key for key, value in prompts._wording(lang).items()
              if set(_PLACEHOLDER_RE.findall(key)) != set(_PLACEHOLDER_RE.findall(value))]
    assert not guilty, f"{lang}: placeholders that do not match: {guilty[:3]}"


def test_a_fragment_with_no_entry_comes_out_in_the_source_language():
    """The same fallback as the screen: a sentence, never a key."""
    prompts.use("fr")
    assert prompts.say("nothing keys this") == "nothing keys this"


def test_the_source_language_hands_the_fragment_back_untouched():
    prompts.use("en")
    assert prompts.say("Text:") == "Text:"


def test_a_fragment_is_said_in_the_language_of_the_cards():
    prompts.use("fr")
    assert prompts.say("Text:") == "Texte :"


def test_the_instructions_ship_with_the_package():
    """Package data: a non-editable installation has to carry them along.

    Read without `tomllib`, missing from Python 3.10.
    """
    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
        encoding="utf-8")
    section = text.split("[tool.setuptools.package-data]", 1)[1].split("\n[", 1)[0]
    declared = re.search(r'^"kotogen\.prompts" = \[(.*)\]$', section, re.MULTILINE)
    assert declared, "the instructions are not declared as package data"
    assert '"*/*.md"' in declared.group(1)
    assert '"*/*.json"' in declared.group(1), (
        "the table of composed fragments ships with the instructions")


def test_the_table_is_valid_json():
    """Read with `json.loads`: `_wording` swallows a truncated file, and the
    translation would silently go."""
    for lang in prompts.languages():
        path = prompts.folder(lang) / "wording.json"
        if path.exists():
            assert isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
