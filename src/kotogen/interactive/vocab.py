"""The dialogue of `kotogen vocab`: where the words come from, then what
that source asks - a theme, a JLPT level, a count."""

from __future__ import annotations

from kotogen.i18n import _, quoted
from kotogen.interactive.screen import (
    JLPT_LEVELS,
    _ask,
    _ask_file,
    _ask_int,
    _ask_optional_max,
    _ask_url,
    _columns,
    _menu,
)


def _vocab_source() -> str:
    # Ordered like the other source menus: what one aims at (a word, a level),
    # then the web, then one's files. One entry per route, since the URL picks its
    # reader and the file its format: no site is named, and no feed is followed.
    return _menu(_("Vocabulary cards - where do the words come from?"), _columns([
        ("word", _("A word, an expression"),
         _("kanji, kana, rōmaji, rough translation...")),
        ("jlpt", _("A JLPT level"), _("the words of the level the deck lacks")),
        ("theme", _("A theme"), _("fruits, a job interview, the days of the week...")),
        ("url", _("A URL"), _("any Japanese page")),
        ("file", _("A local file"),
         _("text or PDF, list of words or text to go through")),
    ]), default=1, allow_back=True, memory="vocab")


def _vocab_options(source: str) -> list[str]:
    if source == "jlpt":
        return _jlpt_options()
    if source == "theme":
        return _theme_options()
    if source == "word":
        return ["vocab", _ask(_("Word or expression"), back=True)]
    if source == "url":
        argv = ["vocab", _ask_url()]
        count = _ask_int(_("Number of words to extract"), 10)
        if count != 10:
            argv += ["--count", str(count)]
        return argv

    # The command line's own switch tells a PDF from a text file.
    from kotogen.generators import sources  # late: the assistant starts light

    path = _ask_file(_("Path of the file (text or PDF)"))
    if sources.is_pdf(str(path)):
        argv = ["vocab", str(path)]
        count = _ask_optional_max(_("Max number of words to extract from the document"))
        if count is not None:
            argv += ["--count", str(count)]
    else:
        # A text file may be a list of words or a running text: asked, not guessed.
        kind = _menu(_("What does {name} hold?").format(name=quoted(path.name)), [
            ("list", _("A list of words (one entry per line)")),
            ("text", _("A running text, to draw the useful vocabulary from")),
        ], default=1, allow_back=True)
        if kind == "list":
            argv = ["vocab", "--file", str(path)]
        else:
            argv = ["vocab", str(path)]
            count = _ask_int(_("Number of words to extract"), 10)
            if count != 10:
                argv += ["--count", str(count)]
    batch = _ask_int(_("Words per request to the AI (batch)"), 10)
    if batch != 10:
        argv += ["--batch-size", str(batch)]
    return argv


def _theme_options() -> list[str]:
    """Theme source: the words of a field, a situation or a set the deck lacks.

    The theme travels in the screen's language: the model reads any, and it is
    never written into the deck."""
    other = "other"
    theme = _menu(_("Which theme?"), [
        (_("Food and drink"), _("Food and drink")),
        (_("Animals"), _("Animals")),
        (_("Days, months and dates"), _("Days, months and dates")),
        (_("Work and job interviews"), _("Work and job interviews")),
        (_("Computing and programming"), _("Computing and programming")),
        (_("Video games"), _("Video games")),
        (_("Travel and transport"), _("Travel and transport")),
        (_("Cities of Japan"), _("Cities of Japan")),
        (other, _("Another theme")),
    ], default=1, allow_back=True)
    if theme == other:
        theme = _ask(_("Theme"), back=True)
    # No level asked: a theme has no level of its own, and its words come the
    # easiest first anyway. `--level` stays for whoever skips its basics.
    argv = ["vocab", "--theme", theme]
    count = _ask_int(_("Number of words to generate"), 20)
    if count != 20:
        argv += ["--count", str(count)]
    return argv


def _jlpt_options() -> list[str]:
    """JLPT source: the words of a level the deck does not have yet.

    No welcome text: the entry of the source menu already says it."""
    level = _menu(_("Which level to fill in?"), [
        (level, level) for level in JLPT_LEVELS
    ] + [("auto", _("All levels"))], default=1, allow_back=True)
    argv = ["vocab", "jlpt"]
    if level != "auto":
        argv += ["--level", level]
    count = _ask_int(_("Number of words to generate"), 20)
    if count != 20:
        argv += ["--count", str(count)]
    return argv
