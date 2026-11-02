"""JLPT level read from the local table, instead of being guessed by the AI."""

import pytest

from kotogen import jlpt

# ── The keyword ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry, asks", [
    ("jlpt", True), ("  JLPT ", True),
    # A file, a source or a rule that names the JLPT stays what it is.
    ("jlpt.pdf", False), ("jlpt-n3", False), ("nhk", False), ("〜たら", False),
    ("", False), (None, False),
])
def test_the_keyword_is_recognised_alone_by_every_generator(entry, asks):
    assert jlpt.is_keyword(entry) is asks


# ── Reading the table ─────────────────────────────────────────────────────────

def test_the_table_loads():
    assert len(jlpt._load()) > 5000


@pytest.mark.parametrize("word, level", [
    ("水", "N5"),
    ("食べる", "N5"),
    ("図書館", "N5"),
    ("ゆっくり", "N5"),
    ("コピー", "N5"),
    ("箸", "N5"),
])
def test_common_words_are_placed(word, level):
    assert jlpt.level_of(word) == level


def test_no_spelling_is_cut_short():
    """The kana a spelling ends on end its reading too: a row cut mid-word
    (素晴らし) matches nothing in a deck, and is generated again every time.
    """
    import re

    from kotogen.furigana import KANJI_RE, kata_to_hira

    cut = []
    for line in jlpt.DATA_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.split("	")
        if line.startswith("#") or len(parts) < 3 or not parts[2].strip():
            continue
        reading = kata_to_hira(parts[2].strip())
        others = parts[3].split(jlpt.OTHERS_SEP) if len(parts) > 3 else []
        for spelling in [parts[1], *others]:
            tail = re.search(r"[ぁ-んァ-ン]+$", spelling)
            if "・" in spelling or (KANJI_RE.search(spelling) and tail
                                    and not reading.endswith(kata_to_hira(tail.group()))):
                cut.append(spelling)
    assert cut == []


def test_a_spelling_read_one_way_is_one_word():
    """A word written several ways is one row, its other spellings beside the
    one that heads it: listed on two rows, it would be offered twice."""
    from collections import Counter

    from kotogen.furigana import reading_key

    seen = Counter()
    for line in jlpt.DATA_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.split("	")
        if line.startswith("#") or len(parts) < 2:
            continue
        others = parts[3].split(jlpt.OTHERS_SEP) if len(parts) > 3 else []
        for spelling in [parts[1], *others]:
            reading = parts[2].strip() if len(parts) > 2 and parts[2].strip() else spelling
            seen[(spelling, reading_key(reading))] += 1
    assert [pair for pair, n in seen.items() if n > 1] == []


def test_every_word_has_its_reading():
    """Every row gives the reading of its word, a kana word included: the deck
    is compared on it (`known`), rather than on the dictionary's guess.
    """
    unread = []
    for line in jlpt.DATA_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if line.startswith("#") or len(parts) < 2:
            continue
        if len(parts) < 3 or not parts[2].strip():
            unread.append(parts[1])
    assert unread == []


def test_no_reading_carries_a_suru_its_spelling_lacks():
    """勉強 reads べんきょう: the する that makes a verb of it is in neither column.

    A verb whose own reading ends in する is written with its る (刷る, 擦る).
    """
    from kotogen.furigana import kata_to_hira

    verbal = []
    for line in jlpt.DATA_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if line.startswith("#") or len(parts) < 3:
            continue
        if not kata_to_hira(parts[2].strip()).endswith("する"):
            continue
        others = parts[3].split(jlpt.OTHERS_SEP) if len(parts) > 3 else []
        verbal += [s for s in [parts[1], *others] if not s.endswith("る")]
    assert verbal == []


def test_the_table_gives_the_reading_of_a_spelling():
    assert jlpt.reading_of("入口") == "いりぐち"
    assert jlpt.reading_of("勉強") == "べんきょう"
    assert jlpt.reading_of("伯父") == "おじ"
    assert jlpt.reading_of("躊躇") == ""


def test_a_word_outside_the_table():
    assert jlpt.level_of("躊躇") is None
    assert jlpt.tag_for("躊躇") == ""


@pytest.mark.parametrize("form", ["涼しい", "涼[すず]しい", "涼しい - cool", "すずしい"])
def test_every_form_of_one_entry_finds_the_level(form):
    """Bare spelling, furigana, annotated draft or kana: same word, same level."""
    assert jlpt.level_of(form) == "N5"


# ── Two spellings of one word ─────────────────────────────────────────────────

@pytest.mark.parametrize("kanji, kana", [
    ("美味しい", "おいしい"),
    ("面白い", "おもしろい"),
    ("椅子", "いす"),
    ("醤油", "しょうゆ"),
    ("迚も", "とても"),
])
def test_the_kanji_spelling_of_a_simple_word_keeps_the_level_of_the_word(kanji, kana):
    """One word, one row: a card written 美味[おい]しい, as the model writes it,
    is tagged N5, not the N3 at which its kanji are met."""
    assert jlpt.level_of(kanji) == "N5"
    assert jlpt.level_of(kana) == "N5"


@pytest.mark.parametrize("word, level", [
    ("蕎麦", "N2"),     # そば is N5, but that is the other word ("next to")
    ("賭ける", "N1"),   # かける is N5 (掛ける)
    ("点ける", "N2"),   # つける is N5 (付ける)
])
def test_homophones_do_not_pass_for_variants(word, level):
    """Two words that read alike stay two words, each at its own level."""
    assert jlpt.level_of(word) == level


# ── Homophony ─────────────────────────────────────────────────────────────────

def test_an_absent_word_does_not_inherit_the_level_of_its_homophone():
    """貴社 is not in the list: it does not take the N4 of 汽車."""
    assert jlpt.level_of("貴社") is None
    assert jlpt.level_of("貴社[きしゃ]") is None
    assert jlpt.tag_for("貴社[きしゃ]") == ""


@pytest.mark.parametrize("reading", ["きしゃ", "かみ", "はし"])
def test_a_shared_reading_places_nobody(reading):
    """かみ is 紙 (N5), 神 (N3) or 髪 (N4): no answer is worth more than another."""
    assert jlpt.level_of(reading) is None


def test_an_expression_is_not_reduced_to_one_of_its_words():
    """`気をつける` has the level of the expression, not that of `つける` (N5)."""
    assert jlpt.level_of("気[き]を つける") == "N2"
    assert jlpt.level_of("気[き]を 付[つ]ける") == "N2"


def test_the_easiest_level_is_the_one_kept():
    """A word listed at two levels counts at the level it is first met at."""
    table = {}
    jlpt._keep_easiest(table, "犬", "N2")
    jlpt._keep_easiest(table, "犬", "N5")
    jlpt._keep_easiest(table, "犬", "N3")
    assert table["犬"] == "N5"


def test_an_absent_table_breaks_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(jlpt, "DATA_FILE", tmp_path / "absent.tsv")
    # The side tables too, which the load empties, so later tests find them intact.
    for name in ("_by_reading", "_reading_of", "_place"):
        monkeypatch.setattr(jlpt, name, {})
    monkeypatch.setattr(jlpt, "_by_surface", None)
    assert jlpt.level_of("水") is None


# ── Tags ──────────────────────────────────────────────────────────────────────

def test_the_level_tag():
    assert jlpt.tag_for("水") == "Level::N5"


# ── Sorting ───────────────────────────────────────────────────────────────────

def test_sorting_from_the_most_accessible_to_the_hardest():
    assert jlpt.sort_by_level(["経済", "水"]) == ["水", "経済"]


def test_unknown_words_come_last():
    ordered = jlpt.sort_by_level(["躊躇", "水"])
    assert ordered == ["水", "躊躇"]


def test_the_sort_is_stable_within_one_level():
    """Within one level, the order of usefulness given by the AI must be kept."""
    same = ["食べる", "水", "図書館"]
    assert jlpt.sort_by_level(same) == same


# ── Filtering by the level asked for ──────────────────────────────────────────

def test_auto_drops_nothing():
    kept, dropped = jlpt.prepare(["水", "経済", "躊躇"], "auto")
    assert dropped == []
    assert set(kept) == {"水", "経済", "躊躇"}


def test_one_step_of_difference_stays_within_the_target():
    """Aiming at N3 does not drop N4: "much easier" means two steps."""
    assert not jlpt.is_much_easier("経済", "N3")   # 経済 is N4
    assert jlpt.is_much_easier("水", "N3")         # 水 is N5


def test_an_unknown_level_is_never_dropped():
    kept, dropped = jlpt.prepare(["躊躇"], "N1")
    assert kept == ["躊躇"]
    assert dropped == []


def test_the_filtering_separates_the_two_lists():
    kept, dropped = jlpt.prepare(["水", "経済", "躊躇"], "N3")
    assert "水" in dropped
    assert set(kept) == {"経済", "躊躇"}


# ── Words of one level (the "vocab jlpt" source) ──────────────────────────────

def test_the_words_of_one_level():
    words = jlpt.words_of("N5")
    assert 500 < len(words) < 2000
    assert "水" in words
    assert all(jlpt.level_of(w) == "N5" for w in words[:50])


def test_a_level_lists_its_words_the_most_frequent_first():
    """`vocab jlpt` adds a level in this order, the commonest words first."""
    n5 = jlpt.words_of("N5")
    assert n5[0] == "する"
    assert {"ある", "ない", "この", "言う", "行く", "いい"} <= set(n5[:40])
    assert n5.index("万年筆") > len(n5) // 2


@pytest.mark.parametrize("spellings", [
    ("おいしい", "美味しい"), ("とても", "迚も"), ("ある", "有る", "在る"), ("見つける", "見付ける"),
])
def test_a_word_written_several_ways_is_offered_once(spellings):
    """`vocab jlpt` offers a word under the spelling that heads its row, and
    never its other spellings as words of their own."""
    offered = jlpt.words_of("auto")
    assert sum(spelling in offered for spelling in spellings) == 1


def test_auto_gives_the_whole_table_from_the_easiest_to_the_hardest():
    words = jlpt.words_of("auto")
    assert len(words) == len(set(words)) > 5000
    levels = [jlpt.level_of(w) for w in words]
    ranks = [jlpt.LEVELS.index(lv) for lv in levels if lv]
    assert ranks == sorted(ranks)


def test_the_levels_do_not_overlap():
    """A word listed at two levels must come out at the easier of the two only."""
    n5, n4 = set(jlpt.words_of("N5")), set(jlpt.words_of("N4"))
    assert not (n5 & n4)
