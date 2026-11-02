"""The kanji tables, held to the counts their sources announce.

Each file is extracted once, then only read: these tests catch a hand edit that
drops a reading or a tab that shifts a column.
"""

import re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "src" / "kotogen" / "data"

_ON = re.compile(r"[ァ-ヶー]+")
_KUN = re.compile(r"[ぁ-ゖー]+(\.[ぁ-ゖー]+)?")


def _rows(name: str) -> list[list[str]]:
    lines = (DATA / name).read_text(encoding="utf-8").splitlines()
    return [line.split("\t") for line in lines if not line.startswith("#")]


def test_the_table_holds_every_kanji_and_every_reading():
    rows = _rows("joyo_kanji.tsv")
    kanji = {row[0] for row in rows}
    on = [row for row in rows if _ON.fullmatch(row[1])]
    kun = [row for row in rows if _KUN.fullmatch(row[1])]
    assert (len(kanji), len(rows), len(on), len(kun)) == (2136, 4388, 2352, 2036)


def test_every_row_has_its_six_columns():
    rows = _rows("joyo_kanji.tsv")
    assert {len(row) for row in rows} == {6}
    assert {row[2] for row in rows} == {"common", "narrow"}
    assert all(len(row[0]) == 1 for row in rows)


def test_the_readings_of_one_kanji_stand_together():
    """In the order of the table: a kanji met again further down would be a
    row shifted from its neighbour."""
    seen, previous = set(), None
    for row in _rows("joyo_kanji.tsv"):
        if row[0] != previous:
            assert row[0] not in seen, row[0]
            seen.add(row[0])
            previous = row[0]


def test_an_example_is_written_with_its_kanji():
    missing = [(row[0], word) for row in _rows("joyo_kanji.tsv")
               for word in row[3].split("、") if word and row[0] not in word]
    assert missing == []


def test_the_okurigana_are_marked():
    readings = {(row[0], row[1]) for row in _rows("joyo_kanji.tsv")}
    assert {("学", "まな.ぶ"), ("生", "う.まれる"), ("承", "うけたまわ.る"),
            ("明", "あき.らか"), ("嵐", "あらし")} <= readings


def test_the_appendix_holds_its_hundred_and_sixteen_words():
    rows = _rows("joyo_special_readings.tsv")
    assert len(rows) == 116
    assert all(re.fullmatch(r"[ぁ-ゖ]+", row[0]) and row[1] for row in rows)
    assert ["きょう", "今日", ""] in rows


def test_the_jlpt_levels_keep_their_sizes():
    """100 / 300 / 650 / 1,000 kanji counted from N5 up, and N1 the rest of
    the Joyo table."""
    rows = _rows("jlpt_kanji.tsv")
    sizes = {level: sum(row[0] == level for row in rows)
             for level in ("N5", "N4", "N3", "N2", "N1")}
    assert sizes == {"N5": 100, "N4": 200, "N3": 350, "N2": 350, "N1": 1136}
    assert {len(row) for row in rows} == {2}


def test_a_kanji_has_one_level():
    kanji = [row[1] for row in _rows("jlpt_kanji.tsv")]
    assert len(kanji) == len(set(kanji))
    assert all(len(k) == 1 for k in kanji)


def test_the_levels_are_those_of_the_joyo_kanji_every_one():
    """Every Joyo kanji has a level, once, and nothing else has one."""
    joyo = {row[0] for row in _rows("joyo_kanji.tsv")}
    jlpt = [row[1] for row in _rows("jlpt_kanji.tsv")]
    assert sorted(jlpt) == sorted(joyo)


def test_every_kanji_of_the_other_tables_has_its_strokes():
    strokes = dict(_rows("kanji_strokes.tsv"))
    joyo = {row[0] for row in _rows("joyo_kanji.tsv")}
    jlpt = {row[1] for row in _rows("jlpt_kanji.tsv")}
    assert (joyo | jlpt) - strokes.keys() == set()
    assert all(count.isdigit() and int(count) > 0 for count in strokes.values())


def test_the_strokes_are_counted_the_japanese_way():
    """花 has 7 strokes in Japan and 8 in a Chinese count; 収 and 遡 are
    counted in the forms the 2010 Joyo table prescribes."""
    strokes = dict(_rows("kanji_strokes.tsv"))
    assert {k: strokes[k] for k in "学花海収遡𠮟"} == {
        "学": "8", "花": "7", "海": "9", "収": "4", "遡": "14", "𠮟": "5"}
