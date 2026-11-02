"""The dialogue of `kotogen kanji`: which kanji, then what to keep of them."""

from __future__ import annotations

from kotogen.i18n import _
from kotogen.interactive.screen import (
    JLPT_LEVELS,
    _ask,
    _ask_file,
    _ask_int,
    _ask_url,
    _columns,
    _menu,
)


def _kanji_source() -> str:
    """Which kanji: typed, those of the vocabulary, of a level, or of a text.

    The vocabulary comes second and not last: it is the source the card is made
    for - the kanji of words already learnt, each card tying them together.
    """
    return _menu(_("Kanji cards - which kanji?"), _columns([
        ("typed", _("Kanji or words"), _("学, 学生, or a kanji described: gaku, study...")),
        ("deck", _("Your vocabulary"), _("the kanji of your words that have no card yet")),
        ("jlpt", _("A JLPT level"), _("the kanji of the level the deck lacks")),
        ("url", _("A URL"), _("the kanji of a web page")),
        ("file", _("A local file"), _("the kanji of a text")),
    ]), default=1, allow_back=True, memory="kanji")


def _kanji_options(source: str) -> list[str]:
    if source == "typed":
        return ["kanji", _ask(_("Kanji, word or description"), back=True)]
    if source == "deck":
        argv = ["kanji", "deck"]
    elif source == "jlpt":
        argv = ["kanji", "jlpt"]
    elif source == "url":
        argv = ["kanji", _ask_url()]
    else:
        argv = ["kanji", "--file", str(_ask_file(_("Path of the text file")))]
    # A level to fill is the question of the JLPT source; the others take every
    # level by default, the easiest first.
    levels = [(level, level) for level in JLPT_LEVELS] + [("auto", _("All levels"))]
    level = _menu(_("Which level to fill in?") if source == "jlpt" else _("Which level?"),
                  levels, default=1 if source == "jlpt" else len(levels), allow_back=True)
    if level != "auto":
        argv += ["--level", level]
    count = _ask_int(_("Number of kanji to make"), 20)
    if count != 20:
        argv += ["--count", str(count)]
    return argv
