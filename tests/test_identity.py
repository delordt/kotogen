"""The identity of a card: the same matter gives the same string, and a change of
form that says nothing new does not give another one."""

import json

import pytest

from kotogen import identity
from kotogen.exporter import append_cards
from kotogen.generators import audio, grammar, reading, vocab


@pytest.mark.parametrize("module, kind", [
    (vocab, "vocab"), (grammar, "grammar"), (audio, "audio"), (reading, "reading")])
def test_the_kind_is_read_off_the_fields(module, kind):
    assert identity.kind_of(module.FIELDS) == kind


def test_fields_no_generator_writes_have_no_kind():
    assert identity.kind_of(["Expression", "Translation"]) is None


# ── Vocabulary ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("expression", [
    "食[た]べる", " 食[た] べる", "<b>食[た]べる</b>"])
def test_a_word_is_its_spelling_and_its_reading(expression):
    assert identity.of("vocab", {"Expression": expression}) == "vocab:食べる:たべる"


def test_homophones_stay_apart():
    assert (identity.of("vocab", {"Expression": "橋[はし]"})
            != identity.of("vocab", {"Expression": "箸[はし]"}))


def test_a_reading_in_katakana_is_the_same_reading():
    assert identity.of("vocab", {"Expression": "タベル"}) == "vocab:タベル:たべる"


def test_kanji_with_no_reading_stand_alone():
    assert identity.of("vocab", {"Expression": "食べる"}) == "vocab:食べる"


# ── Grammar ───────────────────────────────────────────────────────────────────

def test_a_sentence_is_the_same_whatever_its_readings_and_hint():
    plain = identity.of("grammar", {
        "Rule": "ながら", "URL": "",
        "Sentence": "音楽を {{c1::聞きながら::while}} 勉強する。"})
    annotated = identity.of("grammar", {
        "Rule": "〜ながら", "URL": "",
        "Sentence": "音楽[おんがく]を{{c1::聞[き]きながら}}勉強[べんきょう]する。"})
    assert plain == annotated


def test_the_category_tells_apart_two_uses_of_one_form():
    sentence = "早く起きた{{c1::のに}}遅れた。"
    n4 = identity.of("grammar", {"Rule": "のに（逆接）", "Sentence": sentence, "URL": ""})
    n3 = identity.of("grammar", {"Rule": "のに（目的）", "Sentence": sentence, "URL": ""})
    assert n4 != n3


def test_another_sentence_is_another_card():
    def of(sentence):
        return identity.of("grammar", {"Rule": "ながら", "URL": "", "Sentence": sentence})
    assert of("歩き{{c1::ながら}}話す。") != of("食べ{{c1::ながら}}話す。")


# ── Listening and reading ─────────────────────────────────────────────────────

def test_the_readable_name_of_the_source_is_left_out():
    """Renaming the file changes the name, not the matter: the identity keeps the
    fingerprint and the rank only."""
    assert (identity.of("audio", {"ID": "ilbe_nihongo_03_1f4c2a9e_001"})
            == identity.of("audio", {"ID": "renamed_1f4c2a9e_001"})
            == "audio:1f4c2a9e:001")


def test_an_older_prefix_gives_the_same_identity():
    assert (identity.of("reading", {"ID": "RC_nhk_or_jp_k1001_d5a1be77_002"})
            == identity.of("reading", {"ID": "LC_d5a1be77_002"})
            == "reading:d5a1be77:002")


def test_an_id_of_another_shape_is_kept_whole():
    assert identity.of("reading", {"ID": "written_by_hand"}) == "reading:written_by_hand"


# ── In the file ───────────────────────────────────────────────────────────────

def test_every_card_line_carries_its_identity(tmp_path):
    path = tmp_path / "out.jsonl"
    append_cards(path, [{"Expression": "食[た]べる", "Tags": "Level::N5"}],
                 vocab.FIELDS, "Japanese::Vocabulary", "Vocabulary")
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[1])
    assert list(line) == ["id", "kind", "fields", "tags", "media"]
    assert line["id"] == identity.of("vocab", line["fields"])
