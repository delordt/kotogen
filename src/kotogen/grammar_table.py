"""Table of the JLPT grammar points: which level holds what, and what each means.

Shipped as `data/jlpt_grammar.tsv`, corrected by hand and read offline, it names
a rule however it is typed (「〜ながら」, 「ながら」 and 「と思う」 in kana are one
point) and says what a level holds, for `grammar jlpt`. Levels are settled by
consensus, each at most its usual share of the 110 / 250 / 450 / 650 points
counted from N5 up, N1 the rest. A point's name is its identity, carried by the
`Rule` field and tag, so a form heading several points carries its category
(のに（逆接）, のに（目的）). Glosses are read through `meaning()` only.
"""

from __future__ import annotations

import re
from pathlib import Path

from kotogen.jlpt import LEVELS

# One point per line: level, tier, name, then one gloss column per language.
DATA_FILE = Path(__file__).parent / "data" / "jlpt_grammar.tsv"

# The gloss columns, in the order the file writes them.
MEANING_LANGUAGES = ("en", "fr", "ja")

# The gloss language to fall back on, as `i18n.SOURCE` and `prompts.SOURCE`.
SOURCE = "en"

# How central a point is within its level: 1 the backbone, 2 common, 3 finer.
# A line without a readable tier takes the last one rather than being dropped.
TIERS = ("1", "2", "3")

# Spaces and brackets, which tell no two rules apart.
_STRIP_RE = re.compile(r"[\s　（）()「」【】]")
# The linking 〜, in its three spellings.
_TILDE_RE = re.compile(r"[〜～~]")
_EDGE_TILDES_RE = re.compile(r"^[〜～~]+|[〜～~]+$")
# The category heading a homonym: のに（逆接）.
_CATEGORY_RE = re.compile(r"[（(][^（）()]*[）)]$")
# Variant separators inside one name: ように・ような
_ALT_SEP_RE = re.compile(r"[・／/,、]")
# Trailing copula: the table names つもり / はず where one types つもりだ / はずだ
_COPULA_RE = re.compile(r"(だ|です)$")
# The `base[reading]` group produced by furigana.fill_missing, cut to its reading
_READING_RE = re.compile(r"[^\s\[\]]+?\[([^\[\]]+)\]")
# A slot a name joins to its rule with ＋, alone or among alternatives
# (辞書形・ない形＋つもりだ), and the 〜 that may already stand for it.
_SLOT = (r"(?:動詞)?(?:辞書形|ます形)|普通形|意向形|(?:[てたば]|ない)形"
         r"|[いな]形容詞(?:語幹)?|名詞|動詞|疑問詞|数量詞|助数詞|助詞")
_SLOT_RE = re.compile(rf"[〜～~]?(?:{_SLOT})(?:・(?:{_SLOT}))*＋")
# The ending a form is named after: て形 ends on て.
_SLOT_ENDING_RE = re.compile(r"([てたば]|ない)形")


def _read_table() -> list[dict[str, str]]:
    """The table shipped with the package. An empty list if the file is missing.

    The file being edited by hand, a malformed line is skipped silently, and a
    missing gloss column leaves the point without that language.
    """
    try:
        lines = DATA_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []  # an incomplete installation

    points: list[dict[str, str]] = []
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        level, tier, title = (p.strip() for p in parts[:3])
        if level not in LEVELS or not title:
            continue
        point = {"title": title, "level": level,
                 "tier": tier if tier in TIERS else TIERS[-1]}
        for lang, gloss in zip(MEANING_LANGUAGES, parts[3:]):
            point[f"meaning_{lang}"] = gloss.strip()
        points.append(point)
    return points


def meaning(point: dict[str, str], lang: str) -> str:
    """The gloss of a point, in `lang`.

    The rules list asks in the language of the screen (`i18n.language()`), a
    series in that of the cards (`prompts.language()`). A missing gloss falls
    back on `SOURCE`, then on any other: the wrong language beats a blank.
    """
    for name in (lang, SOURCE):
        text = point.get(f"meaning_{name}", "").strip()
        if text:
            return text
    return next((text for key, text in point.items()
                 if key.startswith("meaning_") and text.strip()), "")


_memo: list[dict[str, str]] | None = None


def load() -> list[dict[str, str]]:
    """The grammar points, in the order of the file."""
    global _memo
    if _memo is None:
        _memo = _read_table()
    return _memo


def key(rule: str) -> str:
    """Comparable form of a rule name: no 〜 at its ends, no space, no bracket.

    A homonym's category stays (のに（逆接） and のに（目的） are two keys), and so
    does an inner 〜, written one way: it holds a slot (つ〜つ is not つつ).
    """
    bare = _EDGE_TILDES_RE.sub("", _STRIP_RE.sub("", rule.strip()))
    return _TILDE_RE.sub("〜", bare).lower()


def _variants(text: str) -> set[str]:
    """The forms a name answers to: itself, each of its `・` variants, each
    without its category, its copula or its inner 〜."""
    bare = _CATEGORY_RE.sub("", text.strip())
    forms = {key(text), key(bare)}
    forms |= {key(part) for part in _ALT_SEP_RE.split(bare)}
    forms |= {_COPULA_RE.sub("", f) for f in forms}
    # たり〜たりする is typed たりたりする as often as not.
    forms |= {_TILDE_RE.sub("", f) for f in forms}
    return {f for f in forms if f}


def _to_kana(text: str) -> str:
    """Kana reading of a form written in kanji (と思う -> とおもう), through MeCab.

    The table names some points in kana where one types kanji. Without MeCab,
    the text comes back as it is.
    """
    from kotogen import furigana  # late import: MeCab is loaded only when needed

    if not furigana.KANJI_RE.search(text):
        return text
    return _READING_RE.sub(lambda m: m.group(1), furigana.fill_missing(text))


def _kana_variants(text: str) -> set[str]:
    """Like `_variants`, but after turning the kanji into kana."""
    return _variants(_to_kana(text))


def _typed(text: str) -> set[str]:
    """The forms a name joined by ＋ is typed in: each slot a 〜, ＋ dropped.

    て形＋ください is typed 〜てください, ます形＋やすい 〜やすい. A slot keeps the
    ending its form is named after, or not: ない形＋なくて is typed 〜なくて.
    """
    bare = _CATEGORY_RE.sub("", text.strip())
    if "＋" not in bare:
        return set()

    def ending(slot: re.Match) -> str:
        named = _SLOT_ENDING_RE.search(slot.group(0))
        return "〜" + (named.group(1) if named else "")

    forms: set[str] = set()
    for typed in (_SLOT_RE.sub("〜", bare), _SLOT_RE.sub(ending, bare)):
        forms |= _variants(typed.replace("＋", ""))
    return forms


def _match(points: list[dict[str, str]], rule: str,
           forms_of) -> tuple[dict[str, str] | None, bool]:
    """Best point according to `forms_of`: exact, else the most generic prefix.

    Handed back with whether it was exact. Equality tolerates the trailing
    copula (つもり / つもりだ, そうです / そうだ), but the prefix does not: without
    that, `ところだ` would catch `ところが` through `ところ`.
    """
    exact = {t for t in (rule, _COPULA_RE.sub("", rule)) if t}
    prefix: list[dict[str, str]] = []
    for point in points:
        forms = forms_of(point["title"])
        if exact & forms:
            return point, True
        if any(f.startswith(rule) for f in forms):
            prefix.append(point)
    if not prefix:
        return None, False
    # The shortest name is the most generic: はず over はずだ, はずがない.
    return min(prefix, key=lambda p: len(key(p["title"]))), False


def find(rule: str, index: list[dict[str, str]] | None = None) -> dict[str, str] | None:
    """The grammar point matching `rule`, or None.

    A form shared by several points (のに) gives the first of them in level
    order; the full name (のに（目的）) gives the one it names. A rule typed
    without its slot (てください for て形＋ください) gives the one name typed
    so, and None when several are (ほうがいい): the model settles those.
    """
    points = points_of("auto") if index is None else index
    target = key(rule)
    if not points or not target:
        return None

    hit, exact = _match(points, target, _variants)
    if hit is None:
        kana_target = key(_to_kana(target))
        if kana_target != target:  # else nothing to convert, no point going round again
            hit, exact = _match(points, kana_target, _kana_variants)
    if exact:
        return hit

    # Below a name written out, kana included, but above a prefix: てから is
    # て形＋から, not てからでないと.
    wanted = {t for t in (target, _COPULA_RE.sub("", target)) if t}
    slotted = [point for point in points if wanted & _typed(point["title"])]
    if slotted:
        return slotted[0] if len(slotted) == 1 else None
    return hit


def points_of(level: str = "auto") -> list[dict[str, str]]:
    """The points of a level, in the order they are best learnt: the file's.

    The file orders a level by tier, then by frequency, but no point comes before
    one it rests on, so a point may stand ahead of its tier (な形容詞 before
    な形容詞＋名詞): sorting on the tier would undo that. A line added by hand
    goes at the end of its tier. Any other level ("auto") gives every point,
    easiest level first.
    """
    points = load()
    if level in LEVELS:
        return [p for p in points if p["level"] == level]
    # Stable sort: the order of the file is kept WITHIN each level.
    return sorted(points, key=lambda p: LEVELS.index(p["level"]))
