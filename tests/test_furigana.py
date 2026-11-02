"""Tests of the furigana pipeline (pure logic, no network or AI call)."""

import re

import pytest

from kotogen.furigana import (
    bare_kanji,
    bind_number_groups,
    fix_counter_readings,
    fix_furigana_spacing,
    normalise_brackets,
    process_furigana,
    strip_japanese_spaces,
    without_readings,
)

# ── strip_japanese_spaces ─────────────────────────────────────────────────────

def test_strip_removes_space_between_japanese_chars():
    assert strip_japanese_spaces("あの ガキは うるさい。") == "あのガキはうるさい。"


def test_strip_removes_ideographic_space():
    assert strip_japanese_spaces("はい、　そうです。") == "はい、そうです。"


def test_strip_removes_space_after_furigana_group():
    # `]` counts as Japanese on the left: the space after a furigana group is
    # not an anchor (Anki only eats the one BEFORE the base).
    assert strip_japanese_spaces("今日[きょう] です") == "今日[きょう]です"


def test_strip_keeps_anchor_before_furiganized_word():
    # That space is the word boundary normalise_brackets needs: without it the
    # base of the group spills onto が (学校[っこう]).
    assert strip_japanese_spaces("私[わたし]が 学校[がっこう]へ") == "私[わたし]が 学校[がっこう]へ"


def test_strip_keeps_spaces_around_latin():
    assert strip_japanese_spaces("JLPT N3 レベル") == "JLPT N3 レベル"


def test_strip_keeps_a_latin_line_as_it_is():
    text = "Café (the place, not the drink)"
    assert strip_japanese_spaces(text) == text


# ── without_readings (console display) ────────────────────────────────────────

def test_a_title_reads_in_one_piece():
    """A title in the console loses its brackets and the spaces that anchored
    them: `strip_furigana` alone would leave `第2 回`."""
    title = ("第[だい]2 回[かい]の 料理[りょうり] 大会[たいかい]が "
             "公園[こうえん]で 開[ひら]かれた")
    assert without_readings(title) == "第2回の料理大会が公園で開かれた"


def test_a_space_of_content_stays_a_space():
    """An anchor precedes a kanji word with furigana; `N3 レベル` is not one."""
    assert without_readings("JLPT N3 レベルの 練習[れんしゅう]") == "JLPT N3 レベルの練習"


# ── fix_furigana_spacing ──────────────────────────────────────────────────────

def test_spacing_inserts_space_before_kanji_group():
    assert fix_furigana_spacing("女：今日[きょう]") == "女： 今日[きょう]"


def test_spacing_is_idempotent():
    text = "彼[かれ]は 学校[がっこう]に 行[い]く。"
    assert fix_furigana_spacing(text) == text


def test_spacing_does_not_split_kanji_group():
    assert fix_furigana_spacing("を卒業[そつぎょう]") == "を 卒業[そつぎょう]"


def test_spacing_anchors_after_ideographic_space():
    # Anki only recognises the ASCII space as an anchor: a 　 (U+3000) would let
    # the reading spread over `はい、　今日`.
    assert fix_furigana_spacing("はい、　今日[きょう]") == "はい、　 今日[きょう]"


def test_spacing_treats_html_tag_end_as_anchor():
    # `>` is already a boundary for the Anki filter: no superfluous space.
    text = "<b>今日[きょう]</b>"
    assert fix_furigana_spacing(text) == text


# ── normalise_brackets ────────────────────────────────────────────────────────

def test_normalise_moves_okurigana_out_of_base():
    assert normalise_brackets("食べる[たべる]") == "食[た]べる"


def test_normalise_moves_kana_prefix_out_of_base():
    assert normalise_brackets("お茶[おちゃ]") == "お茶[ちゃ]"


def test_normalise_converts_katakana_reading():
    assert normalise_brackets("茶[チャ]") == "茶[ちゃ]"


def test_normalise_drops_bracket_when_base_is_pure_kana():
    assert normalise_brackets("たべる[たべる]") == "たべる"


def test_normalise_keeps_wellformed_notation():
    assert normalise_brackets("学校[がっこう]") == "学校[がっこう]"


def test_normalise_moves_unmatched_okurigana_out_of_base():
    # The model may read the kanji alone and leave the okurigana in the base:
    # unaligned, the reading would spread over the punctuation before it.
    assert normalise_brackets("頑張って[がんば]") == "頑張[がんば]って"
    assert normalise_brackets("分かった[わ]") == "分[わ]かった"


# ── bare_kanji ────────────────────────────────────────────────────────────────

def test_bare_kanji_finds_lone_kanji_in_kana_word():
    # 字 in ローマ字: a kanji the model can leave without a reading.
    assert bare_kanji("ローマ字") == ["字"]


def test_bare_kanji_empty_when_all_covered():
    assert bare_kanji("彼[かれ]は 今日[きょう] 学校[がっこう]に 行[い]く") == []
    assert bare_kanji("たべる") == []
    assert bare_kanji("") == []


def test_bare_kanji_reports_uncovered_groups_in_order():
    assert bare_kanji("勉強[べんきょう]する事が大切") == ["事", "大切"]


def test_bare_kanji_ignores_speaker_label():
    # 男 is a kanji, but the speaker label never carries furigana.
    assert bare_kanji("男：学生です") == ["学生"]
    assert bare_kanji("男：学生[がくせい]です") == []


# ── process_furigana (the whole pipeline) ─────────────────────────────────────

def test_process_passthrough_without_kanji():
    assert process_furigana("Hello, this is plain text.") == "Hello, this is plain text."
    assert process_furigana("") == ""


def test_process_keeps_speaker_label_out_of_ruby():
    out = process_furigana("男：学生[がくせい]です")
    # The label stays intact, a space anchors the base of the ruby after the ：
    assert out == "男： 学生[がくせい]です"


def test_process_is_idempotent():
    once = process_furigana("A：お茶[おちゃ]を食べる[たべる]。")
    assert process_furigana(once) == once


def test_process_anchors_group_after_punctuation():
    # The reading must never spread over the 、 before it.
    out = process_furigana("はい、頑張って[がんば]ください。")
    assert out == "はい、 頑張[がんば]ってください。"
    assert process_furigana(out) == out


def test_process_strips_spaces_in_kana_only_text():
    # With no kanji, the spaces of the model's segmentation must still go.
    assert process_furigana("あの ガキは うるさい。") == "あのガキはうるさい。"


def test_process_strips_ideographic_space_before_ascii_digits():
    # The 　 of NHK titles goes even when its right-hand neighbour is ASCII.
    out = process_furigana("地震[じしん]　35 人[にん]が")
    assert out == "地震[じしん] 35人[さんじゅうごにん]が"
    assert process_furigana(out) == out


def test_process_strips_stray_spaces_but_keeps_anchors():
    # Every model space goes; only the anchors before a 漢字[かな] group come
    # back (the one after きょう] serves no purpose).
    out = process_furigana("彼[かれ]は 今日[きょう] とても 元気[げんき]だ。")
    assert out == "彼[かれ]は 今日[きょう]とても 元気[げんき]だ。"
    assert process_furigana(out) == out


def test_process_binds_number_when_reading_covers_it():
    # しちじ covers the 7 too: the number goes into the base of the ruby, or
    # else the reading would spread over 時 alone.
    out = process_furigana("毎朝[まいあさ]7時[しちじ]に起[お]きます。")
    assert out == "毎朝[まいあさ] 7時[しちじ]に 起[お]きます。"
    assert process_furigana(out) == out


def test_process_binds_number_with_sandhi():
    # The じゅっ sandhi, and no false space at the very start of the field.
    assert process_furigana("10分[じゅっぷん]") == "10分[じゅっぷん]"


def test_process_binds_native_number_readings():
    assert process_furigana("1人[ひとり]で") == "1人[ひとり]で"
    assert process_furigana("3日[みっか]") == "3日[みっか]"
    assert process_furigana("20歳[はたち]") == "20歳[はたち]"


def test_process_keeps_number_out_when_reading_is_kanji_only():
    # ねん covers 年 only: the digits/kanji split is the right one (the Anki
    # filter eats the space, nothing shows on the card).
    out = process_furigana("2026年[ねん]")
    assert out == "2026 年[ねん]"
    assert process_furigana(out) == out


def test_bind_keeps_kanji_only_reading_after_number():
    # MeCab style: the reading of the kanji alone (ふん), the number left out.
    assert bind_number_groups("10 分[ふん]") == "10 分[ふん]"


def test_bind_handles_fullwidth_digits():
    assert bind_number_groups("１０ 分[じゅっぷん]") == "１０分[じゅっぷん]"


# ── fix_counter_readings ──────────────────────────────────────────────────────

def test_counter_fixes_native_date_reading():
    # ３日 reads みっか, which neither the model (３日[にち]) nor MeCab
    # (３ + 日[か]) gives: it is computed.
    assert fix_counter_readings("３日[にち]") == "３日[みっか]"
    assert fix_counter_readings("３ 日[か]") == "３日[みっか]"


def test_counter_composes_beyond_ten():
    assert fix_counter_readings("14 日[にち]") == "14日[じゅうよっか]"
    assert fix_counter_readings("20 日[にち]") == "20日[はつか]"
    # The irregular tail holds inside a compound too: はっぷん -> にじゅうはっぷん.
    assert fix_counter_readings("30 分[ふん]") == "30分[さんじゅっぷん]"
    assert fix_counter_readings("28 分[ふん]") == "28分[にじゅうはっぷん]"


@pytest.mark.parametrize("written, read", [
    ("1 点[てん]", "1点[いってん]"),
    ("8 点[てん]", "8点[はってん]"),
    ("10 点[てん]", "10点[じゅってん]"),
    ("6 点[てん]", "6点[ろくてん]"),
    ("4 泊[はく]", "4泊[よんぱく]"),
    ("3 泊[はく]", "3泊[さんぱく]"),
])
def test_the_sound_changes_of_the_points_and_the_nights(written, read):
    """A score and a stay are read the way the exercise says them aloud: いちてん
    or よんはく would be learnt as they stand."""
    assert fix_counter_readings(written) == read


@pytest.mark.parametrize("written, read", [
    ("第3回[だいさんかい]", "第[だい] 3回[さんかい]"),
    ("約5分[やくごふん]", "約[やく] 5分[ごふん]"),
    ("毎3日[まいみっか]", "毎[まい] 3日[みっか]"),
    ("各3回[かくさんかい]", "各[かく] 3回[さんかい]"),
    ("全3回[ぜんさんかい]", "全[ぜん] 3回[さんかい]"),
    ("計3回[けいさんかい]", "計[けい] 3回[さんかい]"),
    ("同3年[どうさんねん]", "同[どう] 3年[さんねん]"),
    ("翌3日[よくみっか]", "翌[よく] 3日[みっか]"),
    # MeCab alone reads 前 as まえ: the old reading says ぜん.
    ("前3回[ぜんさんかい]", "前[ぜん] 3回[さんかい]"),
    ("前３回[ぜんさんかい]", "前[ぜん] ３回[さんかい]"),
    ("昭和3年[しょうわさんねん]", "昭和[しょうわ] 3年[さんねん]"),
    ("昭和9年[しょうわくねん]", "昭和[しょうわ] 9年[きゅうねん]"),
    ("平成3年[へいせいさんねん]", "平成[へいせい] 3年[さんねん]"),
    ("令和7年[れいわななねん]", "令和[れいわ] 7年[ななねん]"),
    ("午前9時[ごぜんくじ]", "午前[ごぜん] 9時[くじ]"),
    ("午後4時[ごごよじ]", "午後[ごご] 4時[よじ]"),
    ("第三回[だいさんかい]", "第[だい] 三回[さんかい]"),
    ("第３回[だいさんかい]", "第[だい] ３回[さんかい]"),
    ("毎日3回[まいにちさんかい]", "毎日[まいにち] 3回[さんかい]"),
    ("月曜日3時[げつようびさんじ]", "月曜日[げつようび] 3時[さんじ]"),
    ("毎年4月[まいとししがつ]", "毎年[まいとし] 4月[しがつ]"),
    ("延べ3日[のべみっか]", "延[の]べ 3日[みっか]"),
    ("その第3回[だいさんかい]", "その 第[だい] 3回[さんかい]"),
    ("今年[ことし]の第3回[だいさんかい]", "今年[ことし]の 第[だい] 3回[さんかい]"),
    ("<b>第3回[だいさんかい]</b>", "<b>第[だい] 3回[さんかい]</b>"),
])
def test_a_prefix_keeps_its_share_of_the_old_reading(written, read):
    """The counter's reading is recomputed on the number alone: what the old base
    held in front of it takes the rest of the old reading, whatever the spacing
    laid between the number and its counter."""
    assert process_furigana(written) == read
    assert process_furigana(read) == read


@pytest.mark.parametrize("written, read", [
    ("1日3回[いちにちさんかい]", "1日[いちにち] 3回[さんかい]"),
    ("5月3日[ごがつみっか]に", "5月[ごがつ] 3日[みっか]に"),
    ("4月1日[しがつついたち]", "4月[しがつ] 1日[ついたち]"),
    ("12月25日[じゅうにがつにじゅうごにち]", "12月[じゅうにがつ] 25日[にじゅうごにち]"),
    ("3年2か月[さんねんにかげつ]", "3年[さんねん] 2か月[にかげつ]"),
    ("2時間30分[にじかんさんじゅっぷん]", "2時間[にじかん] 30分[さんじゅっぷん]"),
    ("薬[くすり]は1日3回[いちにちさんかい]飲[の]んでください",
     "薬[くすり]は 1日[いちにち] 3回[さんかい] 飲[の]んでください"),
])
def test_a_prefix_that_is_a_number_and_a_counter_is_read_as_one(written, read):
    """The 日 of 1日 is no prefix of its own: read alone, it would come out ひ."""
    assert process_furigana(written) == read
    assert process_furigana(read) == read


@pytest.mark.parametrize("written, read", [
    ("同じ3日[みっか]", "同[おな]じ 3日[みっか]"),
    ("最初の3日[みっか]", "最初[さいしょ]の 3日[みっか]"),
    ("昭和9年[ねん]", "昭和[しょうわ] 9年[きゅうねん]"),
    ("2026年4月1日[にせんにじゅうろくねんしがつついたち]",
     "2026 年[ねん] 4月[しがつ] 1日[ついたち]"),
])
def test_a_prefix_whose_share_cannot_be_told_is_read_by_mecab(written, read):
    """No kanji the old base held is left bare, which the next pass would fill."""
    pytest.importorskip("fugashi")
    assert process_furigana(written) == read
    assert process_furigana(read) == read


def test_a_number_with_a_reading_of_its_own_cut_the_old_base():
    """The share of 第 is in `第三[だいさん]`, where the reading of 回 cannot tell it."""
    pytest.importorskip("fugashi")
    assert fix_counter_readings("第三[だいさん] 回[かい]") == "第[だい] 三回[さんかい]"


@pytest.mark.parametrize("text", [
    "三回[さんかい]", "十分[じゅうぶん]", "3日[みっか]", "1人[ひとり]で", "8月[はちがつ] 1日[ついたち]",
])
def test_a_counter_with_nothing_in_front_is_left_as_it_reads(text):
    assert process_furigana(text) == text


@pytest.mark.parametrize("written, read", [
    ("9年[くねん]", "9年[きゅうねん]"),
    ("19年間[じゅうくねんかん]", "19年間[じゅうきゅうねんかん]"),
    ("九年[くねん]", "九年[きゅうねん]"),
])
def test_nine_years_are_read_kyuunen(written, read):
    """くねん is no reading of nine years: the table must not overwrite the right one."""
    assert fix_counter_readings(written) == read


def test_counter_handles_kanji_numbers():
    # MeCab splits 三日 into 三[みっ] + 日[か]: two rubies instead of one.
    assert fix_counter_readings("三[みっ] 日[か]") == "三日[みっか]"
    assert fix_counter_readings("一[いち] 週間[しゅうかん]") == "一週間[いっしゅうかん]"
    assert fix_counter_readings("二十[にじゅう] 歳[さい]") == "二十歳[はたち]"


def test_counter_accepts_kana_ka_forms():
    # After spacing, the kana か sits outside the base (`3か 月[げつ]`) and the
    # digit still needs its reading. All six spellings of the か are equivalent.
    assert fix_counter_readings("3か 月[げつ]") == "3か月[さんかげつ]"
    assert fix_counter_readings("3ヵ月[かげつ]") == "3ヵ月[さんかげつ]"
    assert fix_counter_readings("1ケ 月[げつ]") == "1ケ月[いっかげつ]"
    assert fix_counter_readings("6か 国[こく]") == "6か国[ろっかこく]"
    assert fix_counter_readings("3か 所[しょ]") == "3か所[さんかしょ]"


def test_counter_reads_first_of_month_from_context():
    # 一日 = いちにち (a duration) except behind a month, where it is the day.
    assert fix_counter_readings("1 日[にち]") == "1日[いちにち]"
    assert fix_counter_readings("8 月[がつ]1 日[にち]") == "8月[はちがつ] 1日[ついたち]"


def test_counter_ignores_unknown_counter():
    # Outside the table (匙) or the range (2026): no reading is invented.
    assert fix_counter_readings("2026 年[ねん]") == "2026 年[ねん]"
    assert fix_counter_readings("3 匙[さじ]") == "3 匙[さじ]"


def test_counter_leaves_bun_readings_alone():
    # 十分[じゅうぶん] ("amply") and 三分の一 are not minutes.
    assert fix_counter_readings("十分[じゅうぶん]") == "十分[じゅうぶん]"
    assert fix_counter_readings("三[さん] 分[ぶん]の 一[いち]") == "三[さん] 分[ぶん]の 一[いち]"


def test_process_fixes_counter_case():
    # `３日みっか` on the card, not `３日にち`.
    out = process_furigana(
        "マリア：はい。一週間[いっしゅうかん]に３日[にち]泳[およ]いでいます。"
    )
    assert out == "マリア：はい。 一週間[いっしゅうかん]に ３日[みっか] 泳[およ]いでいます。"
    assert process_furigana(out) == out


def test_process_fixes_ka_getsu_case():
    # Not `1年いちねん3かげつ` on the card, the 3 with no reading.
    out = process_furigana("B：1年3か月です。")
    assert out == "B： 1年[いちねん] 3か月[さんかげつ]です。"
    assert process_furigana(out) == out


def test_process_keeps_particle_out_of_base():
    # The base must not swallow the particle before it, whose kana would then
    # drop out of the reading (学校[っこう]).
    out = process_furigana("私[わたし]が 学校[がっこう]へ 行[い]きます。")
    assert out == "私[わたし]が 学校[がっこう]へ 行[い]きます。"


def test_process_fills_missing_readings_with_mecab():
    pytest.importorskip("fugashi")
    out = process_furigana("彼は行く")
    assert "彼[" in out and "行[" in out


def test_process_keeps_spaces_of_latin_text_around_kanji():
    # A field in the language of the cards carrying a kanji goes to MeCab, which
    # drops the spaces between tokens: they must come back.
    pytest.importorskip("fugashi")
    out = process_furigana("Informal, used for the 犬 and the cat.")
    assert out.startswith("Informal, used for the ")
    assert out.endswith(" and the cat.")
    assert "犬[いぬ]" in out


def test_process_keeps_trailing_space_of_furiganized_text():
    # The trailing space belongs to no token: MeCab loses it too.
    pytest.importorskip("fugashi")
    assert process_furigana("the word 本 ") == process_furigana("the word 本") + " "


# ── The NHK route: ruby HTML to export ────────────────────────────────────────

def test_nhk_ruby_dump_is_cleaned_at_export():
    # The NHK HTML carries spaces between tags, ideographic spaces and rubies
    # whose base includes a number (２０日=はつか): the export sets them straight.
    from kotogen.exporter import _clean_field
    from kotogen.generators.nhk import ruby_html_to_furigana

    html = ("<p>　<ruby>東京<rt>とうきょう</rt></ruby>では "
            "<ruby>２０日<rt>はつか</rt></ruby>、 <ruby>雪<rt>ゆき</rt></ruby>が　"
            "<ruby>降<rt>ふ</rt></ruby>りました。</p>")
    out = _clean_field(ruby_html_to_furigana(html))
    assert out == "東京[とうきょう]では ２０日[はつか]、 雪[ゆき]が 降[ふ]りました。"
    assert _clean_field(out) == out


def test_nhk_lines_are_finalized_at_extraction():
    # The NHK extraction gives the card's final text: the console shows what Anki gets.
    from kotogen.exporter import _clean_field
    from kotogen.generators.nhk import finalize_lines, ruby_html_to_furigana

    raw = ruby_html_to_furigana(
        "<ruby>大阪<rt>おおさか</rt></ruby>の<ruby>大会<rt>たいかい</rt></ruby>　"
        "48<ruby>人<rt>にん</rt></ruby>が<ruby>走<rt>はし</rt></ruby>った"
    )
    title, lines = finalize_lines(raw, [raw])
    assert title == "大阪[おおさか]の 大会[たいかい] 48人[よんじゅうはちにん]が 走[はし]った"
    assert lines == [title]
    assert _clean_field(title) == title  # the export has nothing left to fix


def test_nhk_keeps_site_readings_over_mecab():
    # MeCab reads 日本 as にっぽん: the site's reading, made by hand, wins.
    pytest.importorskip("fugashi")
    from kotogen.generators.nhk import finalize_lines

    _, lines = finalize_lines("", ["日本[にほん]の 会社[かいしゃ]"])
    assert lines == ["日本[にほん]の 会社[かいしゃ]"]


# ── Japanese quoted inside a Latin line ───────────────────────────────────────

def _anki_furigana(field: str) -> str:
    """What Anki's `{{furigana::...}}` filter shows of the field.

    Its rule: the base runs back from the bracket to a space, which is eaten.
    """
    return re.sub(r" ?([^ >]+?)\[(.+?)\]", r"\1", field)


def test_latin_line_keeps_its_space_before_japanese():
    # The Anki filter must not eat the sentence's space before 擬音語 as an anchor.
    pytest.importorskip("fugashi")
    out = process_furigana("What is the whole set of 擬音語 and 擬態語 called?")
    assert _anki_furigana(out) == "What is the whole set of 擬音語 and 擬態語 called?"
    assert process_furigana(out) == out


def test_latin_line_does_not_space_out_an_opening_bracket():
    # The space laid after `(` is an anchor, not text: it has to be eaten.
    pytest.importorskip("fugashi")
    out = process_furigana("Informal (擬音語) in Japanese")
    assert _anki_furigana(out) == "Informal (擬音語) in Japanese"
    assert process_furigana(out) == out


def test_japanese_line_still_eats_the_anchor_after_latin():
    # In a Japanese sentence that space is only an anchor: `2026 年` must not show.
    pytest.importorskip("fugashi")
    out = process_furigana("2026年に 卒業[そつぎょう]する")
    assert _anki_furigana(out) == "2026年に卒業する"
    assert process_furigana(out) == out
