"""What a kanji is, read from the local tables rather than asked of the AI."""

import pytest

from kotogen import kanji_table

# ── A kanji of the Joyo table ─────────────────────────────────────────────────

def test_a_joyo_kanji_brings_its_readings_level_strokes_and_forms():
    kanji = kanji_table.lookup("学")
    assert [r.text for r in kanji.readings] == ["ガク", "まな.ぶ"]
    assert (kanji.level, kanji.strokes, kanji.forms, kanji.joyo) == ("N5", 8, "（學）", True)
    assert kanji.readings[1].examples == ("学ぶ",)


def test_on_and_kun_readings_are_told_apart():
    kanji = kanji_table.lookup("学")
    assert [r.text for r in kanji.on] == ["ガク"]
    assert [r.text for r in kanji.kun] == ["まな.ぶ"]


def test_a_kun_reading_says_what_the_kanji_itself_reads():
    reading = kanji_table.lookup("学").kun[0]
    assert (reading.kana, reading.own) == ("まなぶ", "まな")


def test_a_reading_the_table_sets_back_is_not_among_the_common_ones():
    """行 アン (行脚) is in the table, set back as special: a card leaves it out."""
    kanji = kanji_table.lookup("行")
    assert "アン" in [r.text for r in kanji.readings]
    assert "アン" not in [r.text for r in kanji.common]


def test_the_remarks_of_a_reading_come_with_it():
    reading = next(r for r in kanji_table.lookup("宛").readings if r.text == "あ.てる")
    assert reading.notes == "⇔当てる、充てる"


def test_the_form_a_keyboard_types_finds_the_form_the_table_prints():
    assert kanji_table.lookup("叱").char == "𠮟"
    assert kanji_table.lookup("頬").joyo


# ── Outside the Joyo table ────────────────────────────────────────────────────

def test_a_kanji_outside_the_joyo_table_is_known_by_what_the_lists_give():
    kanji = kanji_table.lookup("鞄")
    assert (kanji.joyo, kanji.readings, kanji.strokes) == (False, (), 14)


def test_a_name_kanji_is_known_by_its_strokes_alone():
    kanji = kanji_table.lookup("翔")
    assert (kanji.level, kanji.joyo, kanji.readings) == (None, False, ())
    assert kanji.strokes


@pytest.mark.parametrize("char", ["a", "あ", "々", ""])
def test_what_no_table_lists_is_unknown(char):
    assert kanji_table.lookup(char) is None


# ── Levels ────────────────────────────────────────────────────────────────────

def test_a_kanji_outside_the_joyo_table_has_no_level():
    """伊 is used in names: its level is unknown, not guessed."""
    assert not kanji_table.lookup("伊").joyo
    assert kanji_table.level_of("伊") is None
    assert kanji_table.tag_for("伊") == ""


def test_the_level_tag():
    assert kanji_table.tag_for("学") == "Level::N5"


def test_a_level_lists_its_kanji_the_most_frequent_first():
    n5 = kanji_table.of_level("N5")
    assert (len(n5), n5[:3]) == (100, ["日", "年", "人"])
    assert kanji_table.of_level("auto") == []


# ── Words read as a whole ─────────────────────────────────────────────────────

def test_the_words_of_the_appendix_written_with_a_kanji():
    assert kanji_table.special_words("今") == [
        ("今日", "きょう"), ("今朝", "けさ"), ("今年", "ことし")]


def test_a_word_read_as_a_whole():
    assert kanji_table.is_special("今日")
    assert not kanji_table.is_special("今")
    assert not kanji_table.is_special("学生")


# ── The kanji of a text ───────────────────────────────────────────────────────

def test_the_kanji_of_a_text_once_each_in_order():
    assert kanji_table.kanji_in("今日は学校へ行く。学ぶ") == ["今", "日", "学", "校", "行"]


def test_the_marks_among_kanji_are_not_kanji():
    assert kanji_table.kanji_in("時々〆切〇ヶ月") == ["時", "切", "月"]


# ── An incomplete install ─────────────────────────────────────────────────────

def test_absent_tables_break_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(kanji_table, "_tables", None)
    for name in ("JOYO_FILE", "SPECIAL_FILE", "LEVELS_FILE", "STROKES_FILE"):
        monkeypatch.setattr(kanji_table, name, tmp_path / "absent.tsv")
    assert kanji_table.lookup("学") is None
    assert kanji_table.of_level("N5") == []
    assert kanji_table.special_words("今") == []
