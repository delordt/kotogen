"""The dialogue of `kotogen grammar`: where the rule comes from, then the
rules of a level to tick and the number of cards each one gets."""

from __future__ import annotations

from kotogen import console, grammar_table, i18n, memory
from kotogen.cli import deck_config
from kotogen.i18n import _
from kotogen.interactive.lists import FREE, _tickable_pages
from kotogen.interactive.screen import (
    JLPT_LEVELS,
    _ask,
    _ask_file,
    _ask_int,
    _ask_url,
    _Back,
    _columns,
    _header,
    _menu,
)


def _grammar_source() -> str:
    """Where the rule comes from - and not "where the text comes from".

    The input is always a rule one knows: typed, drawn from a level, a file or
    the page that documents it. A text is not offered: its rules come from its
    reading card, through the pink flag of the corrections (see
    `grammar.run_grammar`).
    """
    return _menu(_("Grammar cards - where does the rule come from?"), _columns([
        ("rule", _("One precise rule"),
         _("typed as it comes: のに, younitanomu...")),
        ("jlpt", _("A JLPT level"), _("the rules of the level the deck lacks")),
        ("sheet", _("A grammar page"),
         _("the address of a page that explains ONE rule")),
        ("list", _("A file of rules"), _("one per line, like a list of words")),
    ]), default=1, allow_back=True, memory="grammar")


def _grammar_options(source: str) -> list[str]:
    if source == "rule":
        # The label of the menu already gives examples.
        argv = ["grammar", _ask(_("Rule to work on"), back=True)]
    elif source == "jlpt":
        return _grammar_jlpt_options()
    elif source == "sheet":
        # The page names the rule and becomes the reference page of the cards.
        argv = ["grammar", "--url", _ask_url(_("URL of the grammar page"))]
    else:
        argv = ["grammar", "--file", str(_ask_file(_("Path of the file of rules")))]
    count = _ask_int(_("Number of cards") if source in ("rule", "sheet")
                     else _("Number of cards per rule"), 5)
    if count != 5:
        argv += ["--count", str(count)]
    return argv


def _grammar_jlpt_options() -> list[str]:
    """The level, then its rules, to tick - the ones already done included.

    A list rather than "the first three", as the teaching order of the table
    opens N5 on を and の. Rules done are marked, not hidden, so that the list
    says where one stands and they can be taken again. The rules ticked leave
    as arguments, found again in the table (see `grammar._detect_info`).
    """
    from kotogen.generators import grammar  # late: the assistant starts light

    level = _menu(_("Which level to fill in?"), [
        (level, level) for level in JLPT_LEVELS
    ] + [("auto", _("All levels"))],
        default=1, allow_back=True)

    # The whole syllabus in one call, which reads the deck: the level is shown,
    # the rest searched.
    all_rules = grammar.rules_of_level("auto", deck_config("grammar")[1], memory.known())
    if not all_rules:
        _header()
        print("   " + _("Rule table unavailable: cannot say what"
                        " {level} holds.").format(level=grammar.level_label(level)))
        raise _Back
    chosen_level = level if level in JLPT_LEVELS else ""
    rules = [rule for rule in all_rules
             if not chosen_level or rule.point["level"] == chosen_level]
    # Other levels are not shown, but a search reaches them, and a rule chosen
    # there keeps its own level.
    elsewhere = [rule for rule in all_rules
                 if chosen_level and rule.point["level"] != chosen_level]

    done = sum(1 for rule in rules if rule.done)
    # The mark leads the line, as after the meaning it read as part of it. A
    # rule done ticks like the others.

    def row(rule) -> tuple[str, str, str]:
        # Keyed by the name, unique in the table, which also leaves as the
        # argument. The gloss is in the language of the screen, the cards having
        # theirs. The meaning stays apart for the list to lay out in screen
        # columns (see `_laid_out`), a kana taking two; the mark and the level,
        # of a fixed width, can be padded here.
        return (rule.title,
                f"{'✓' if rule.done else ' '} {rule.point['level']:<4}"
                f"{rule.title}",
                grammar_table.meaning(rule.point, i18n.language()))

    chosen = _tickable_pages(
        _("{level} - {done}/{total} done").format(
            level=grammar.level_label(level), done=done, total=len(rules)),
        [row(rule) for rule in rules], unit=lambda n: console.plural(n, "rule"), locate=False,
        elsewhere=[row(rule) for rule in elsewhere],
        free=_("Work on {name} anyway"))
    if not chosen:
        raise _Back
    # A typed rule the table does not know leaves as typed, for the analysis to
    # name and place.
    return (["grammar", *(key.removeprefix(FREE) for key in chosen)]
            + _grammar_cards_per_rule())


def _grammar_cards_per_rule() -> list[str]:
    """The number of cards per rule, common to both paths of the JLPT level."""
    count = _ask_int(_("Number of cards per rule"), 5)
    return ["--count", str(count)] if count != 5 else []
