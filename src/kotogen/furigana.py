"""Furigana in one place: completion, normalisation and spacing of `漢字[かな]`.

Anki's `{{furigana::Field}}` renders a well-formed notation; the faults come from
upstream (missing readings, a base holding more than kanji, stray spaces,
irregular counters), and `process_furigana()` corrects them. MeCab only fills
bare kanji, never an existing reading.
"""

from __future__ import annotations

import re

from kotogen import console
from kotogen.i18n import _

# -- Unicode ranges -----------------------------------------------------------

# Kanji and the marks treated as kanji. Public: the maintenance modules reuse it.
KANJI_CHARS = "㐀-䶿一-鿿豈-﫿々〆〇ヵヶ"
# Kana (hiragana + katakana + the ー prolongation + the small kana).
_KANA = "぀-ゟ゠-ヿー"

KANJI_RE = re.compile(f"[{KANJI_CHARS}]")
_KANJI_RUN_RE = re.compile(f"[{KANJI_CHARS}]+")
# Public: kana are what tells Japanese from Chinese, which shares its ideographs
# and writes none (see `subtitles`).
KANA_RE = re.compile(f"[{_KANA}]")

# A furigana group: a base (no space, no bracket) followed by [reading].
_BRACKET_RE = re.compile(r"([^\s\[\]]+?)\[([^\[\]]+)\]")

# A kanji group stuck to a character that is not an anchor, to be given a space.
# Anki's filter only takes an ASCII space or a ">" as an anchor: an ideographic
# space, a newline or a tab would end up in the base of the ruby.
_KANJI_GROUP_RE = re.compile(f"([^ >{KANJI_CHARS}])([{KANJI_CHARS}]+\\[)")

# The speaker prefix at the head of a line (男：/女：/A：/B：): a label, which the
# audio transcripts never give furigana. The key line is a field of its own, so
# no marker precedes the label here.
_SPEAKER_RE = re.compile(r"^\s*(?:[男女]|[A-Za-zＡ-Ｚ])\s*[：:]\s*")

# One MeCab warning at most per run.
_mecab_warned = False


def _is_kana(ch: str) -> bool:
    return bool(KANA_RE.match(ch))


def kata_to_hira(s: str) -> str:
    """Turn katakana into hiragana (ー and everything else pass through)."""
    out = []
    for ch in s:
        o = ord(ch)
        # A 0x60 shift over 30A1-30F6, ァ to ヶ (ヵ ヶ become ゕ ゖ): the bound
        # spares ー (30FC) and ヷ-ヺ, katakana with no hiragana equivalent.
        if 0x30A1 <= o <= 0x30F6:
            out.append(chr(o - 0x60))
        else:
            out.append(ch)
    return "".join(out)


# -- Comparison keys ----------------------------------------------------------
# Shared by the duplicate search and the filter of known words, so that they
# agree on what "the same word" is.

# -- Romanisation -------------------------------------------------------------
# For searching, never for display: a menu filters にくい on "niku" without a
# Japanese keyboard. Approximate Hepburn is enough there: a missed long vowel
# costs one more keystroke, where an exact table would be ten times the size.

# The digraphs first: they read over two characters and take precedence.
_ROMAJI_DIGRAPHS = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "しゃ": "sha", "しゅ": "shu",
    "しょ": "sho", "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "にゃ": "nya",
    "にゅ": "nyu", "にょ": "nyo", "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo",
    "みゃ": "mya", "みゅ": "myu", "みょ": "myo", "りゃ": "rya", "りゅ": "ryu",
    "りょ": "ryo", "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo", "じゃ": "ja",
    "じゅ": "ju", "じょ": "jo", "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo", "ふぁ": "fa", "ふぃ": "fi",
    "ふぇ": "fe", "ふぉ": "fo", "てぃ": "ti", "でぃ": "di", "うぃ": "wi",
    "うぇ": "we", "ちぇ": "che", "しぇ": "she", "じぇ": "je",
}

_ROMAJI = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa",
}


def to_romaji(text: str) -> str:
    """The Latin reading of the kana of a text; the rest passes through.

    Katakana read as hiragana. A small っ doubles the next consonant (かっこ ->
    kakko), and ー repeats the vowel before it (ラーメン -> raamen, as typed).
    """
    kana = kata_to_hira(text)
    out: list[str] = []
    i = 0
    while i < len(kana):
        pair = kana[i:i + 2]
        if pair in _ROMAJI_DIGRAPHS:
            out.append(_ROMAJI_DIGRAPHS[pair])
            i += 2
            continue
        char = kana[i]
        if char == "っ":
            # With nothing after it, the small tsu doubles nothing and is dropped.
            following = kana[i + 1:i + 3]
            sound = _ROMAJI_DIGRAPHS.get(following) or _ROMAJI.get(kana[i + 1:i + 2], "")
            if sound:
                out.append(sound[0])
            i += 1
            continue
        if char == "ー":
            out.append(out[-1][-1] if out and out[-1] else "")
            i += 1
            continue
        out.append(_ROMAJI.get(char, char))
        i += 1
    return "".join(out)


_FURI_RE = re.compile(r"\[[^\]]*\]")
# A group of kanji followed by its reading: 漢字[かな] -> かな
_FURI_GROUP_RE = re.compile(f"[{KANJI_CHARS}]+\\[([^\\]]*)\\]")

# A run of Japanese characters: isolates the word in a raw entry mixing
# Japanese, romaji and a translation ("* 走る hashiru, to run" -> 走る).
JP_RUN_RE = re.compile(f"[{KANJI_CHARS}{_KANA}]+")


def strip_furigana(text: str) -> str:
    """The text rid of the readings in brackets (食[た]べる -> 食べる)."""
    return _FURI_RE.sub("", text)


def reading_key(text: str) -> str:
    """A comparison key based on the READING, not on the written form.

    `食[た]べる`, `たべる` and `タベル` all give `たべる`. Homophones (橋/箸) share
    a key too: whether that is acceptable is for the caller to decide.
    """
    text = _FURI_GROUP_RE.sub(lambda m: m.group(1), text)  # 漢字[かな] -> かな
    text = strip_furigana(text)                            # brackets left over
    text = re.sub(r"\s+", "", text)
    return kata_to_hira(text).strip()


def surface_key(text: str) -> str:
    """A key on the WRITTEN form: furigana and spaces removed, kanji kept."""
    return re.sub(r"\s+", "", strip_furigana(text)).strip()


# -- Stray spaces -------------------------------------------------------------

# The Japanese context for removing spaces: kanji, kana, CJK punctuation
# (U+3001-303F, the ideographic space aside) and the full- and half-width forms
# (U+FF01-FF9F). Not Latin: "JLPT N3 レベル" keeps its spaces.
_JA_CTX = KANJI_CHARS + _KANA + "、-〿！-ﾟ"
# "]", the end of a furigana group, counts as Japanese on the left
# (「今日[きょう] です」).
_JA_SPACE_RE = re.compile(f"(?<=[{_JA_CTX}\\]])[ 　]+(?=[{_JA_CTX}])")

# What follows a legitimate anchor: a word holding a kanji and a `[かな]` group
# (「お茶[おちゃ]」).
_ANCHOR_AHEAD_RE = re.compile(f"[^\\s\\[\\]]*[{KANJI_CHARS}][^\\s\\[\\]]*\\[")

# A run of spaces holding an ideographic one (U+3000): Japanese typography, never
# content, removed even beside a non-Japanese neighbour (「地震　35人」).
_IDEO_SPACE_RE = re.compile("[ 　]*　[ 　]*")


def _keep_or_drop_space(m: re.Match) -> str:
    """Keep an ASCII anchor before a furiganised word, remove everything else."""
    return " " if _ANCHOR_AHEAD_RE.match(m.string, m.end()) else ""


# A content space: one space between a non-Japanese character and a Japanese word
# that will carry furigana. Anki's filter eats it anyway, gluing the Japanese to
# the word before (「of擬音語」). The word must start with Japanese, and after an
# opener (bracket, quote, apostrophe) a space can only be an anchor.
_OPENERS = "([{«\"'/"
_CONTENT_SPACE_RE = re.compile(
    f"(?<=[^\\s>\\]{_OPENERS}{_JA_CTX}]) (?! )"
    f"(?=[{_JA_CTX}])(?=[^\\s\\[\\]]*[{KANJI_CHARS}])"
)

# In a Japanese line a space before a word with a reading is an anchor, except
# after an arrow or a relation sign (U+2190-22FF, `=`), where the line shows it.
_SIGN_SPACE_RE = re.compile(
    f"(?<=[←-⋿=]) (?! )(?=[{_JA_CTX}])(?=[^\\s\\[\\]]*[{KANJI_CHARS}])"
)

# Latin letters against Japanese characters, to tell the language of a line.
_LATIN_RE = re.compile(r"[A-Za-zÀ-ÿ]")
_JA_CHAR_RE = re.compile(f"[{KANJI_CHARS}{_KANA}]")


def _is_latin_line(text: str) -> bool:
    """True if the line is Latin text quoting Japanese, and not the other way round.

    A space before Japanese is content in such a line ("the whole set of 擬音語"),
    and an anchor laid by `fix_furigana_spacing` in a Japanese one (「CD屋」). The
    readings do not count, so every pass gets the same answer.
    """
    body = strip_furigana(text)
    return len(_LATIN_RE.findall(body)) > 2 * len(_JA_CHAR_RE.findall(body))


def protect_content_spaces(text: str) -> str:
    """Double the space a line shows before a Japanese word that will carry a reading.

    Anki's filter eats one and HTML shows the other: in a Latin line any space
    before Japanese, in a Japanese line the one after a sign (`降る → 降れば`). To be
    applied BEFORE any anchor is laid (`fix_furigana_spacing`), while the spaces
    are the source's.
    """
    return (_CONTENT_SPACE_RE if _is_latin_line(text) else _SIGN_SPACE_RE).sub("  ", text)


def strip_japanese_spaces(text: str) -> str:
    """Remove the spaces (ASCII or U+3000) between two Japanese characters.

    Such a space is an anchor or a stray from the model. Anchors stay: laid back
    later, they would come after `normalise_brackets` had let a base overflow
    onto the particle before it. A second pass takes the ideographic spaces NHK
    also puts before digits (「地震　35人」).
    """
    text = _JA_SPACE_RE.sub(_keep_or_drop_space, text)
    return _IDEO_SPACE_RE.sub(_keep_or_drop_space, text)


# The space preceding a furiganised word, removed for a console, which shows no
# ruby.
_ANCHOR_RE = re.compile(f"[ 　]+(?={_ANCHOR_AHEAD_RE.pattern})")


def without_readings(text: str) -> str:
    """The text as it reads: without the readings or the spaces that anchored them.

    For the screen, never for a card. `strip_furigana` alone leaves the anchors:
    「台風[たいふう]13 号[ごう]」 would read 「台風13 号」.
    """
    return strip_furigana(_ANCHOR_RE.sub("", text))


# -- Spacing ------------------------------------------------------------------

def fix_furigana_spacing(text: str) -> str:
    """Guarantee a space before every `漢字[かな]` group.

    Anki's filter takes everything back to the previous space as the base of the
    ruby, then consumes that space.
    """
    return _KANJI_GROUP_RE.sub(r"\1 \2", text)


# -- Numbers + counters -------------------------------------------------------

# The readings of the last digit of a number: Sino-Japanese first, then the
# liaisons before a counter (1分=いっぷん) and the native readings (1人=ひとり).
_DIGIT_READINGS = {
    0: ["れい", "ぜろ"],
    1: ["いち", "いっ", "ひと"],
    2: ["に", "ふた"],
    3: ["さん", "みっ", "み"],
    4: ["よん", "し", "よっ", "よ"],
    5: ["ご", "いつ"],
    6: ["ろく", "ろっ", "むっ", "む"],
    7: ["なな", "しち"],
    8: ["はち", "はっ", "やっ", "や"],
    9: ["きゅう", "く", "ここの"],
}
_TEN_SINO = ["じゅう", "じゅっ", "じっ"]

_FW_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _number_readings(digits: str) -> list[str]:
    """The possible kana readings of a number written in digits (0-99).

    To recognise a reading covering the number AND its counter (7時=しちじ).
    Beyond 99 (years), the model reads the kanji alone: [] is returned.
    """
    n = int(digits.translate(_FW_DIGITS))
    if n > 99:
        return []
    if n < 10:
        return list(_DIGIT_READINGS[n])
    tens, unit = divmod(n, 10)
    tens_part = "" if tens == 1 else _DIGIT_READINGS[tens][0]
    if unit == 0:
        readings = [tens_part + v for v in _TEN_SINO]
        if n == 10:
            readings.append("とお")           # 10日=とおか
        if n == 20:
            readings += ["はつ", "はた"]      # 20日=はつか, 20歳=はたち
        return readings
    return [tens_part + "じゅう" + v for v in _DIGIT_READINGS[unit]]


# After fix_furigana_spacing: a number in digits, a space, then a `漢字[かな]`
# group. The `( ?)` captures any anchor already present before the number.
_NUMBER_GROUP_RE = re.compile(
    f"( ?)([0-9０-９]+) ([{KANJI_CHARS}]+)\\[([^\\[\\]]+)\\]"
)


def _anchor_before(m: re.Match, lead: str) -> str:
    """The space that will anchor the base of the merged ruby.

    Empty at the start of a field or after a ">", already boundaries for Anki.
    """
    if lead:
        return lead
    return "" if m.start() == 0 or m.string[m.start() - 1] == ">" else " "


def _bind_one_number(m: re.Match) -> str:
    lead, digits, kanji, reading = m.groups()
    for num in _number_readings(digits):
        if reading.startswith(num) and len(reading) > len(num):
            # A compound reading: the number goes into the base of the ruby.
            return f"{_anchor_before(m, lead)}{digits}{kanji}[{reading}]"
    return m.group(0)  # kanji-only reading (2026年[ねん]): separation kept


def bind_number_groups(text: str) -> str:
    """Attach a number in digits to its counter when the reading covers it.

    `fix_furigana_spacing` parts them (「7 時[しちじ]」); a reading that starts
    with a reading of the number belongs over the whole of 「7時」.
    """
    return _NUMBER_GROUP_RE.sub(_bind_one_number, text)


# -- The computed reading of the counters -------------------------------------
#
# `bind_number_groups` needs a reading that already covers the number, and the
# irregular counters get none: MeCab reads the counter alone (３ + 日[か]) and
# the model gets it wrong (３日[にち]). So it is computed here.

# The default Sino-Japanese readings of a lone digit.
_SINO = ["れい", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう"]

# A counter: its reading, the irregular "digit + counter" keyed by the units digit
# so that 28分 reads like 8分 (10 for round tens), and the whole numbers that do
# not compose (二十歳). Of two readings in use, the one textbooks teach.
_COUNTERS: dict[str, tuple[str, dict[int, str], dict[int, str]]] = {
    # Time and dates
    "日": ("にち", {4: "よっか", 7: "しちにち", 9: "くにち"},
           {1: "いちにち", 2: "ふつか", 3: "みっか", 4: "よっか", 5: "いつか",
            6: "むいか", 7: "なのか", 8: "ようか", 9: "ここのか", 10: "とおか",
            20: "はつか"}),
    "日間": ("にちかん", {4: "よっかかん"},
             {2: "ふつかかん", 3: "みっかかん", 4: "よっかかん", 5: "いつかかん",
              6: "むいかかん", 7: "なのかかん", 8: "ようかかん", 9: "ここのかかん",
              10: "とおかかん", 20: "はつかかん"}),
    "月": ("がつ", {4: "しがつ", 7: "しちがつ", 9: "くがつ"}, {}),   # month name
    "ヶ月": ("かげつ", {1: "いっかげつ", 6: "ろっかげつ", 8: "はっかげつ",
                       10: "じゅっかげつ"}, {}),
    "ヶ国": ("かこく", {1: "いっかこく", 6: "ろっかこく", 8: "はっかこく",
                       10: "じゅっかこく"}, {}),
    "ヶ所": ("かしょ", {1: "いっかしょ", 6: "ろっかしょ", 8: "はっかしょ",
                       10: "じゅっかしょ"}, {}),
    "年": ("ねん", {4: "よねん"}, {}),
    "年間": ("ねんかん", {4: "よねんかん"}, {}),
    "週": ("しゅう", {1: "いっしゅう", 8: "はっしゅう", 10: "じゅっしゅう"}, {}),
    "週間": ("しゅうかん", {1: "いっしゅうかん", 8: "はっしゅうかん",
                           10: "じゅっしゅうかん"}, {}),
    "時": ("じ", {4: "よじ", 7: "しちじ", 9: "くじ"}, {}),
    "時間": ("じかん", {4: "よじかん", 9: "くじかん"}, {}),
    "分": ("ふん", {1: "いっぷん", 3: "さんぷん", 4: "よんぷん", 6: "ろっぷん",
                   8: "はっぷん", 10: "じゅっぷん"}, {}),
    "分間": ("ふんかん", {1: "いっぷんかん", 3: "さんぷんかん", 4: "よんぷんかん",
                         6: "ろっぷんかん", 8: "はっぷんかん", 10: "じゅっぷんかん"}, {}),
    "秒": ("びょう", {}, {}),
    "泊": ("はく", {1: "いっぱく", 3: "さんぱく", 4: "よんぱく", 6: "ろっぱく",
                   8: "はっぱく", 10: "じゅっぱく"}, {}),
    "度": ("ど", {}, {}),
    "回": ("かい", {1: "いっかい", 6: "ろっかい", 8: "はっかい", 10: "じゅっかい"}, {}),
    # People
    "人": ("にん", {4: "よにん", 7: "しちにん"}, {1: "ひとり", 2: "ふたり"}),
    "名": ("めい", {4: "よんめい"}, {}),
    "歳": ("さい", {1: "いっさい", 8: "はっさい", 10: "じゅっさい"}, {20: "はたち"}),
    "才": ("さい", {1: "いっさい", 8: "はっさい", 10: "じゅっさい"}, {20: "はたち"}),
    # Objects
    "本": ("ほん", {1: "いっぽん", 3: "さんぼん", 6: "ろっぽん", 8: "はっぽん",
                   10: "じゅっぽん"}, {}),
    "枚": ("まい", {}, {}),
    "冊": ("さつ", {1: "いっさつ", 8: "はっさつ", 10: "じゅっさつ"}, {}),
    "個": ("こ", {1: "いっこ", 6: "ろっこ", 8: "はっこ", 10: "じゅっこ"}, {}),
    "台": ("だい", {}, {}),
    "杯": ("はい", {1: "いっぱい", 3: "さんばい", 6: "ろっぱい", 8: "はっぱい",
                   10: "じゅっぱい"}, {}),
    "匹": ("ひき", {1: "いっぴき", 3: "さんびき", 6: "ろっぴき", 8: "はっぴき",
                   10: "じゅっぴき"}, {}),
    "足": ("そく", {1: "いっそく", 3: "さんぞく", 8: "はっそく", 10: "じゅっそく"}, {}),
    "着": ("ちゃく", {1: "いっちゃく", 8: "はっちゃく", 10: "じゅっちゃく"}, {}),
    "軒": ("けん", {1: "いっけん", 3: "さんげん", 6: "ろっけん", 8: "はっけん",
                   10: "じゅっけん"}, {}),
    "階": ("かい", {1: "いっかい", 3: "さんがい", 6: "ろっかい", 8: "はっかい",
                   10: "じゅっかい"}, {}),
    "円": ("えん", {4: "よえん"}, {}),
    "点": ("てん", {1: "いってん", 8: "はってん", 10: "じゅってん"}, {}),
    "番": ("ばん", {}, {}),
    "番目": ("ばんめ", {}, {}),
}

# The six spellings of the 「か」 of ヶ月, ヶ国 and ヶ所, brought back to ヶ so that
# each counter has one entry in the table.
_KA_PREFIXES = "ヶヵケカか箇"
_KA_COUNTERS = ("月", "国", "所")


def _normalise_counter(counter: str) -> str:
    """Bring 「か月」, 「ヵ月」, 「箇月」... back to the table key 「ヶ月」."""
    if counter[:1] in _KA_PREFIXES and counter[1:] in _KA_COUNTERS:
        return "ヶ" + counter[1:]
    return counter


# 一日 is いちにち (a duration) or ついたち (a day of the month): a month just
# before it decides (「五月一日」).
_DATE_EXACT = {"日": {1: "ついたち"}, "日間": {1: "いちにちかん"}}

# The kanji digits accepted before a counter. Not 百 or 千: 八百屋 and 千円 are
# not "number + counter" pairs to recompose.
_KANJI_DIGITS = "〇零一二三四五六七八九十"
_KANJI_VALUE = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9}


def _kanji_number(s: str) -> int | None:
    """The value of a number written in kanji (0-99), None if unrecognised."""
    head, sep, tail = s.partition("十")
    if not sep:                                   # 三 (no tens)
        return _KANJI_VALUE.get(s) if len(s) == 1 else None
    if "十" in tail or len(head) > 1 or len(tail) > 1:
        return None
    tens = 1 if not head else _KANJI_VALUE.get(head)   # 十 = 1 ten
    unit = 0 if not tail else _KANJI_VALUE.get(tail)
    if not tens or unit is None:                  # 〇十 is not a number
        return None
    return tens * 10 + unit


def _counter_reading(n: int, counter: str, *, date: bool = False) -> str | None:
    """The reading of "n + counter", None if the counter is unknown or n is out of
    the table.

    Nothing past 99: the reading of 「2026年」 is left as the model wrote it.
    """
    spec = _COUNTERS.get(_normalise_counter(counter))
    if spec is None or n > 99:
        return None
    base, tail, exact = spec
    if date and n in _DATE_EXACT.get(counter, {}):
        return _DATE_EXACT[counter][n]
    if n in exact:
        return exact[n]
    if n < 10:
        return tail.get(n) or _SINO[n] + base
    tens, unit = divmod(n, 10)
    prefix = "" if tens == 1 else _SINO[tens]
    if unit == 0:
        return prefix + (tail.get(10) or "じゅう" + base)
    return prefix + "じゅう" + (tail.get(unit) or _SINO[unit] + base)


# A number (digits, or kanji with a possible reading), the space
# `fix_furigana_spacing` may have laid, and a `counter[reading]` group whose
# counter may open on a kana 「か」 (か月, ケ月), parted from it by the spacing.
_COUNTER_GROUP_RE = re.compile(
    f"( ?)(?:([0-9０-９]+)|([{_KANJI_DIGITS}]+)(?:\\[[^\\[\\]]*\\])?)"
    f" ?([かカケ]? ?[{KANJI_CHARS}]+)\\[([^\\[\\]]+)\\]"
)

# A month right before the group: 「8月1日」 / 「五月一日」 -> a day of the month.
_MONTH_BEFORE_RE = re.compile(
    f"(?:[0-9０-９]+|[{_KANJI_DIGITS}]+)(?:\\[[^\\[\\]]*\\])? ?月(?:\\[[^\\[\\]]*\\])?[ 　]*$"
)


# What an old base can hold glued in front of its number, read backwards: the
# stretch back to a space, a tag, a bracket or punctuation (前3回[ぜんさんかい]).
_STRETCH_BACKWARDS_RE = re.compile(f"[0-9０-９{KANJI_CHARS}{_KANA}]+")
# A number + counter closing that stretch (the 1日 of 1日3回, the 5月 of 5月3日).
_PAIR_END_RE = re.compile(f"([0-9０-９]+)([かカケ]?[{KANJI_CHARS}]+)$")
_DIGIT_RE = re.compile("[0-9０-９]")


def _anchor_after(done: str) -> str:
    """The space a group needs after `done`: none at the start, after a space or a tag."""
    return "" if not done or done[-1] in " >" else " "


def _share_before(reading: str, n: int, counter: str, full: str) -> str:
    """What `reading` holds in front of the number + counter, "" if it cannot be told.

    The old reading of the pair may be wrong (くねん for 9年): a reading of the
    number before the counter's own still marks where the pair starts.
    """
    base = _COUNTERS[_normalise_counter(counter)][0]
    ends = [len(tail) for tail in [full] + [v + base for v in _number_readings(str(n))]
            if reading.endswith(tail)]
    return reading[:-max(ends)] if ends else ""


def _read_stretch(stretch: str, share: str, done: str) -> str:
    """The stretch an old base held in front of its number, read on its own.

    `share` is its part of the old reading, "" if it cannot be told; `done` is the
    text before it. A number + counter closing it is read by the table, the rest
    by `share` when no digit is left in it, otherwise by MeCab.
    """
    pair = _PAIR_END_RE.search(stretch)
    if pair:
        n = int(pair.group(1).translate(_FW_DIGITS))
        rest = stretch[:pair.start()]
        full = _counter_reading(
            n, pair.group(2), date=bool(_MONTH_BEFORE_RE.search(done + rest)))
        if full:
            read = _read_stretch(rest, _share_before(share, n, pair.group(2), full), done)
            return f"{read}{_anchor_after(done + read)}{pair.group(0)}[{full}]"
    if share and not _DIGIT_RE.search(stretch):
        # Spaced before the filling, so that MeCab gets what the share leaves bare.
        read = fill_missing(fix_furigana_spacing(_normalise_one(stretch, share)))
    else:
        read = _furiganize_plain(stretch)
    return fix_furigana_spacing(done[-1:] + read)[len(done[-1:]):]


def fix_counter_readings(text: str) -> str:
    """Recompute the reading of a known number + counter pair, and merge them.

    The existing reading is overwritten, MeCab's and the model's being wrong
    alike for these counters. A counter outside the table is left to
    `bind_number_groups`. What the old base held in front of the number keeps
    its share of the old reading.
    """
    out, last = "", 0
    for m in _COUNTER_GROUP_RE.finditer(text):
        lead, digits, kanji_num, counter, reading = m.groups()
        counter = counter.replace(" ", "")            # 「か 月」 -> 「か月」
        n = int(digits.translate(_FW_DIGITS)) if digits else _kanji_number(kanji_num)
        if n is None:
            continue
        # 十分[じゅうぶん] ("amply"), 三分[さんぶん]の一: a reading in ぶん is not
        # the counter for minutes.
        if counter.startswith("分") and reading.endswith("ぶん"):
            continue
        full = _counter_reading(
            n, counter, date=bool(_MONTH_BEFORE_RE.search(text[:m.start()]))
        )
        if full is None:
            continue
        before = text[last:m.start()]
        glued = _STRETCH_BACKWARDS_RE.match(before[::-1]) if not lead else None
        if glued:
            # Told by the reading, not by a space: `fix_furigana_spacing` has
            # parted the number from its counter. A number with a reading of its
            # own (三[さん]) cut the old base there.
            share = "" if m.group(0).count("[") > 1 else _share_before(reading, n, counter, full)
            start = len(before) - glued.end()
            before = before[:start] + _read_stretch(before[start:], share, out + before[:start])
        out += before
        out += f"{lead or _anchor_after(out)}{digits or kanji_num}{counter}[{full}]"
        last = m.end()
    return out + text[last:]


# -- Spotting bare kanji ------------------------------------------------------

def bare_kanji(text: str) -> list[str]:
    """Groups of kanji WITHOUT a `[かな]` reading right after them (bare kanji).

    A deterministic net for maintenance: the model misses a lone kanji in a kana
    word (消しゴム). The speaker prefix is skipped. In order of appearance.
    """
    if not text or not KANJI_RE.search(text):
        return []
    m = _SPEAKER_RE.match(text)
    if m:
        text = text[m.end():]
    return [g.group(0) for g in _KANJI_RUN_RE.finditer(text)
            if not text.startswith("[", g.end())]


# -- Normalising the brackets (base = kanji only) -----------------------------

def _normalise_one(base: str, reading: str) -> str:
    """Realign a single `base[reading]` so that the base is kanji only.

    Kana at either end of the base that the reading shares (a kana prefix,
    okurigana) move out of it. Returns the recomposed text.
    """
    reading = kata_to_hira(reading)
    pre, post = "", ""

    # Leading kana common to the base and the reading (お茶 / おちゃ -> お comes out).
    while base and reading and _is_kana(base[0]) and base[0] == reading[0]:
        pre += base[0]
        base = base[1:]
        reading = reading[1:]

    # Trailing kana in common (okurigana; 食べる / たべる -> べる comes out).
    while base and reading and _is_kana(base[-1]) and base[-1] == reading[-1]:
        post = base[-1] + post
        base = base[:-1]
        reading = reading[:-1]

    # Trailing kana with no counterpart in the reading: okurigana the model left
    # in the base (頑張って[がんば] -> 頑張[がんば]って). Left before "[", they deny
    # the group its kanji anchor, and Anki spreads the reading over what precedes.
    while base and _is_kana(base[-1]):
        post = base[-1] + post
        base = base[:-1]

    if not base:                      # it was all kana: no ruby at all
        return pre + post
    if not reading or not KANJI_RE.search(base):
        return pre + base + post
    return f"{pre}{base}[{reading}]{post}"


def normalise_brackets(text: str) -> str:
    """Apply `_normalise_one` to every `base[reading]` group of the text."""
    return _BRACKET_RE.sub(lambda m: _normalise_one(m.group(1), m.group(2)), text)


# -- Completion through MeCab (an optional safety net) ------------------------

_tagger = None


def get_tagger():
    """Lazily load the fugashi/unidic-lite tagger. None if unavailable.

    Public: the proofreading of readings (`dictionary`) shares it rather than
    loading the dictionary twice.
    """
    global _tagger, _mecab_warned
    if _tagger is not None:
        return _tagger
    try:
        import fugashi  # type: ignore
        _tagger = fugashi.Tagger()
    except Exception as exc:  # ImportError, or a missing dictionary
        if not _mecab_warned:
            console.failed(_(
                "MeCab (fugashi + unidic-lite) unavailable: the kanji the AI "
                "forgot will stay without furigana."))
            console.failed(f"pip install fugashi unidic-lite ({console.reason(exc)})")
            _mecab_warned = True
        _tagger = False  # the "already tried, failed" sentinel
    return _tagger or None


def _reading_of(word) -> str:
    """The reading (hiragana) of a fugashi token, or '' if unknown."""
    feat = word.feature
    # unidic: `kana` carries the reading, `pron` (the pronunciation) is the
    # fallback; an unknown word has neither.
    for attr in ("kana", "pron"):
        val = getattr(feat, attr, None)
        if val and val != "*":
            return kata_to_hira(val)
    return ""


def _furiganize_token(surface: str, reading: str) -> str:
    """Produce `漢字[かな]` for a token (surface + reading), okurigana aligned."""
    if not reading or not KANJI_RE.search(surface):
        return surface
    return _normalise_one(surface, reading)


def _furiganize_plain(text: str) -> str:
    """Add the furigana to a fragment WITHOUT brackets, through MeCab.

    MeCab drops whitespace from its surfaces: what it skipped is put back, or a
    Latin field holding a kanji would come back glued ("Informal,usedforthe").
    """
    if not KANJI_RE.search(text):
        return text
    tagger = get_tagger()
    if tagger is None:
        return text
    out = []
    consumed = 0
    for word in tagger(text):
        start = text.find(word.surface, consumed)
        if start < 0:                       # surface not found: we do not guess
            start = consumed
        out.append(text[consumed:start])    # whitespace skipped by the tokenizer
        out.append(_furiganize_token(word.surface, _reading_of(word)))
        consumed = start + len(word.surface)
    out.append(text[consumed:])             # trailing whitespace, tied to no token
    # Spaced here, while MeCab's word boundaries are known: `normalise_brackets`
    # would read 「に日本[にっぽん]」 as base 「に日本」 -> 日本[っぽん].
    return fix_furigana_spacing("".join(out))


def fill_missing(text: str) -> str:
    """Fill in the bare kanji (outside the existing brackets) with MeCab.

    Only the raw stretches go to MeCab: existing readings are never touched.
    """
    if not KANJI_RE.search(text):
        return text
    out = []
    last = 0
    for m in _BRACKET_RE.finditer(text):
        out.append(_furiganize_plain(text[last:m.start()]))  # raw text before the bracket
        out.append(m.group(0))                               # existing bracket, intact
        last = m.end()
    out.append(_furiganize_plain(text[last:]))
    return "".join(out)


# -- The entry point ----------------------------------------------------------

def process_furigana(text: str) -> str:
    """The whole pipeline: de-spacing -> completion -> normalisation -> spacing
    -> counter readings -> reattaching the numbers.

    Idempotent on a clean notation; text with no Japanese comes back as it is.
    """
    if not text:
        return text
    # Before the no-kanji exit: an all-kana sentence loses its stray spaces too.
    text = strip_japanese_spaces(text)
    if not KANJI_RE.search(text):
        return text
    # Before any anchor is laid, while the spaces are still the source's.
    text = protect_content_spaces(text)
    # The speaker prefix is a label: set aside, then put back intact.
    m = _SPEAKER_RE.match(text)
    prefix, body = (m.group(0), text[m.end():]) if m else ("", text)
    body = fill_missing(body)
    body = normalise_brackets(body)
    # Spaced with the prefix back, or Anki takes 「男：学生」 as the base. The known
    # counters come first: `bind_number_groups` only glues back a right reading.
    return bind_number_groups(fix_counter_readings(fix_furigana_spacing(prefix + body)))
