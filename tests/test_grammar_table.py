"""Tests of the grammar table: reading the file, resolving a rule typed loosely
to its point, and the order a level is offered in."""

import re

from kotogen import grammar_table
from kotogen.jlpt import LEVELS

# Cut down to what the lookups need, in the shape `_read_table` hands back.
INDEX = [
    {"title": "ながら", "level": "N4", "tier": "1"},
    {"title": "ように・ような", "level": "N4", "tier": "2"},
    {"title": "はず", "level": "N4", "tier": "1"},
    {"title": "はずがない", "level": "N3", "tier": "2"},
    {"title": "ところが", "level": "N3", "tier": "3"},
    {"title": "とおもう", "level": "N4", "tier": "1"},
    {"title": "のに（逆接）", "level": "N4", "tier": "1"},
    {"title": "のに（目的）", "level": "N3", "tier": "2"},
]


def test_tilde_prefix_is_ignored():
    assert grammar_table.find("〜ながら", INDEX)["title"] == "ながら"


def test_exact_name_match():
    assert grammar_table.find("ながら", INDEX)["title"] == "ながら"


def test_alternative_form_of_a_composite_name():
    assert grammar_table.find("〜ような", INDEX)["title"] == "ように・ような"


def test_trailing_copula_still_matches():
    assert grammar_table.find("〜はずだ", INDEX)["title"] == "はず"


def test_ambiguous_prefix_picks_the_most_generic_point():
    """はずが gives はずがない, the only point it opens; はず is a point itself."""
    assert grammar_table.find("はずが", INDEX)["title"] == "はずがない"
    assert grammar_table.find("はず", INDEX)["title"] == "はず"


def test_prefix_does_not_match_across_the_copula():
    """ところだ must not catch ところが through ところ."""
    assert grammar_table.find("〜ところだ", INDEX) is None


def test_kanji_rule_matches_kana_name():
    # One types と思う, the table names it とおもう: the MeCab reading bridges them.
    assert grammar_table.find("〜と思う", INDEX)["title"] == "とおもう"


def test_the_bare_form_of_a_homonym_gives_the_first_and_the_full_name_its_own():
    assert grammar_table.find("のに", INDEX)["title"] == "のに（逆接）"
    assert grammar_table.find("のに（目的）", INDEX)["title"] == "のに（目的）"
    assert grammar_table.find("〜のに（目的）", INDEX)["title"] == "のに（目的）"


def test_unknown_or_empty():
    assert grammar_table.find("〜まったくnonexistent", INDEX) is None
    assert grammar_table.find("〜ながら", []) is None
    assert grammar_table.find("", INDEX) is None


def test_the_key_keeps_the_category_and_drops_the_decoration():
    assert grammar_table.key("〜のに（目的）") == grammar_table.key("のに (目的)")
    assert grammar_table.key("のに（目的）") != grammar_table.key("のに（逆接）")
    assert grammar_table.key("〜ば") == grammar_table.key("ば")


def test_an_inner_tilde_holds_a_slot_and_tells_two_rules_apart():
    """つ〜つ (行きつ戻りつ) is not つつ: only the 〜 at an end is decoration."""
    assert grammar_table.key("つ〜つ") != grammar_table.key("つつ")
    assert grammar_table.key("しか～ない") == grammar_table.key("〜しか〜ない")
    index = [{"title": "たり〜たりする", "level": "N5", "tier": "1"},
             {"title": "つつ", "level": "N2", "tier": "2"},
             {"title": "つ〜つ", "level": "N1", "tier": "3"}]
    # Typed without it, the name is still found.
    assert grammar_table.find("たりたりする", index)["title"] == "たり〜たりする"
    assert grammar_table.find("つつ", index)["title"] == "つつ"
    assert grammar_table.find("つ～つ", index)["title"] == "つ〜つ"


def test_a_name_with_a_slot_is_found_by_the_rule_typed_alone():
    """て形＋ください is typed 〜てください: each slot a 〜, with or without the
    ending its form is named after."""
    index = [{"title": "て形＋ください", "level": "N5", "tier": "1"},
             {"title": "て形＋から", "level": "N5", "tier": "1"},
             {"title": "た形＋ほうがいい", "level": "N5", "tier": "1"},
             {"title": "名詞＋まで", "level": "N5", "tier": "2"},
             {"title": "名詞＋より名詞＋のほうが", "level": "N5", "tier": "2"},
             {"title": "ます形＋やすい", "level": "N4", "tier": "2"},
             {"title": "辞書形・ない形＋つもりだ", "level": "N4", "tier": "1"},
             {"title": "ない形＋なくてはならない", "level": "N4", "tier": "2"},
             {"title": "ない形＋ほうがいい", "level": "N4", "tier": "2"},
             {"title": "まで（程度）", "level": "N3", "tier": "2"},
             {"title": "てからでないと", "level": "N1", "tier": "3"}]
    for typed, title in (("〜てください", "て形＋ください"), ("やすい", "ます形＋やすい"),
                         ("〜つもりだ", "辞書形・ない形＋つもりだ"),
                         ("ないつもり", "辞書形・ない形＋つもりだ"),
                         ("〜なくてはならない", "ない形＋なくてはならない"),
                         ("〜より〜のほうが", "名詞＋より名詞＋のほうが"),
                         ("たほうがいい", "た形＋ほうがいい"),
                         # The rule typed, not a longer name it opens.
                         ("てから", "て形＋から"),
                         # A name written out comes first.
                         ("まで", "まで（程度）")):
        assert grammar_table.find(typed, index)["title"] == title, typed
    # Two names are typed so: the model settles it, as for a rule the table lacks.
    assert grammar_table.find("ほうがいい", index) is None


def test_a_level_keeps_the_order_of_the_file(monkeypatch):
    """The file is in learning order, a prerequisite sometimes ahead of its tier:
    sorting by tier would put it back behind the point resting on it."""
    monkeypatch.setattr(grammar_table, "load", lambda: INDEX)
    assert [p["title"] for p in grammar_table.points_of("N4")] == [
        "ながら", "ように・ような", "はず", "とおもう", "のに（逆接）"]
    everything = grammar_table.points_of("auto")
    # Every level, from the easiest to the hardest.
    assert [p["level"] for p in everything] == ["N4"] * 5 + ["N3"] * 3
    assert everything[-1]["title"] == "のに（目的）"


def test_the_file_is_read_leniently(tmp_path, monkeypatch):
    table = tmp_path / "grammar.tsv"
    table.write_text(
        "# a comment\n"
        "N4\t1\tのに（逆接）\tAlthough\tBien que\n"
        "N4\t?\tやすい\tEasy to\n"          # no tier, no French: still read
        "N9\t1\tだ\tTo be\tÊtre\n"           # no such level: skipped
        "N5\t1\n",                           # too short: skipped
        encoding="utf-8")
    monkeypatch.setattr(grammar_table, "DATA_FILE", table)
    points = grammar_table._read_table()
    assert [p["title"] for p in points] == ["のに（逆接）", "やすい"]
    assert points[1]["tier"] == "3"
    assert grammar_table.meaning(points[1], "fr") == "Easy to"


def test_the_gloss_is_read_in_the_language_asked_for():
    point = {"title": "のに（逆接）", "meaning_en": "Although", "meaning_fr": "Bien que"}
    assert grammar_table.meaning(point, "fr") == "Bien que"
    assert grammar_table.meaning(point, "en") == "Although"
    # A language the table does not gloss falls back on the source, then on
    # whatever gloss there is.
    assert grammar_table.meaning(point, "de") == "Although"
    assert grammar_table.meaning({"meaning_fr": "Bien que"}, "de") == "Bien que"
    assert grammar_table.meaning({"title": "x"}, "en") == ""


# -- The shipped table --------------------------------------------------------

def test_the_shipped_table_names_every_point_once_in_japanese():
    """The name is a point's identity: a duplicate would mark the other done, and
    a Latin letter, a space or a number says nothing on a card or breaks the tag."""
    points = grammar_table._read_table()
    assert len(points) > 800
    names = [grammar_table.key(p["title"]) for p in points]
    assert len(names) == len(set(names))
    for point in points:
        assert not re.search(r"[A-Za-z0-9０-９\s　①-⑳]", point["title"]), point
        assert point["level"] in LEVELS
        assert all(point.get(f"meaning_{lang}")
                   for lang in grammar_table.MEANING_LANGUAGES), point


def test_the_shipped_names_with_a_slot_answer_to_the_rule_typed_alone():
    """〜てください, the first example of the documentation, costs no call."""
    for typed, title in (("〜てください", "て形＋ください"), ("〜やすい", "ます形＋やすい"),
                         ("にくい", "ます形＋にくい"), ("〜てから", "て形＋から")):
        assert grammar_table.find(typed)["title"] == title, typed


def test_a_level_opens_on_its_most_frequent_points():
    """The backbone of a level comes first, not the kana order, which would put
    お〜する and かもしれない ahead of ば and たら."""
    n5 = [p["title"] for p in grammar_table.points_of("N5")]
    assert {"を", "の（所有）", "だ"} <= set(n5[:5])
    n4 = [p for p in grammar_table.points_of("N4")]
    assert {"ば", "使役形"} <= {p["title"] for p in n4[:5]}
    assert all(p["tier"] == "1" for p in n4[:5])


def _named(title: str) -> str:
    """A name without the category of its homonym: て形（接続） -> て形."""
    return re.sub(r"（[^（）]*）$", "", title)


def test_no_point_comes_before_a_form_its_name_rests_on():
    """て形＋から rests on the te-form: within a level, it comes after the first
    point naming it. A form first named at an easier level binds nothing."""
    points = grammar_table.points_of("auto")
    first_level = {}
    for point in points:
        first_level.setdefault(_named(point["title"]), point["level"])
    for level in LEVELS:
        seen: set[str] = set()
        for point in grammar_table.points_of(level):
            title = point["title"]
            if "＋" in title:
                forms = re.split(r"[・＋〜]", title.rsplit("＋", 1)[0])
                for form in forms:
                    if first_level.get(form) == level:
                        assert form in seen, f"{title} comes before {form}"
            seen.add(_named(title))
