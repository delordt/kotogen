"""Where the words the user reads come from.

The code writes English. Every other language is a table keyed by the exact
English string (`locales/fr.json`), and a missing key falls back on that English,
so an incomplete table shows a sentence, never a placeholder. Placeholders are
named, never positional, so that a translator can reorder them. Only the head of
a key is reserved: "#" for what is applied rather than translated (see
`convention`), and a context before a "|" for a word that means two things (see
`translate`) or for a plural form (`one|`, `many|`, see `counted` and `agreed`).

`KOTOGEN_LANG` picks the table, read once on the first lookup so that a run never
prints half a menu in each language. Tests switch it with `use()`.
"""

from __future__ import annotations

import functools
import json
import os
import re
from pathlib import Path

LOCALES = Path(__file__).resolve().parent / "locales"

# The language the code is written in: no table, a lookup returns the string.
SOURCE = "en"

# The source language's name in itself. Other languages hold theirs under the
# key "#language" (`Français`, not `French`); English has no table to hold it.
SOURCE_NAME = "English"

# The language of the cards belongs to the deck, not to the screen: it is the
# `all.lang` template setting, resolved in `kotogen.prompts`.

_language: str | None = None
_catalogue: dict[str, str] = {}


def available() -> list[str]:
    """Languages that can be picked, source language first."""
    tables = sorted(path.stem for path in LOCALES.glob("*.json"))
    return [SOURCE] + [name for name in tables if name != SOURCE]


def language_name(code: str) -> str:
    """The name of that language, in that language (`fr` -> `Français`).

    A table without a "#language" key, or an unknown code, gives the code itself.
    """
    if code == SOURCE:
        return SOURCE_NAME
    return _load(code).get("#language", code)


def describe() -> str:
    """What the settings screen shows facing the interface language.

    The code, which `KOTOGEN_LANG` takes, and the name, which a reader recognises.
    """
    return f"{language()} - {language_name(language())}"


def language() -> str:
    """The language in use, resolved once from KOTOGEN_LANG.

    An unknown name, a typo say, gives the source language, not a failure."""
    if _language is None:
        use(os.environ.get("KOTOGEN_LANG", "").strip().lower() or SOURCE)
    return _language or SOURCE


def use(name: str) -> str:
    """Switch to `name` and load its table. Returns the language actually used."""
    global _language, _catalogue
    _language = name if name in available() else SOURCE
    _catalogue = _load(_language)
    return _language


def _load(name: str) -> dict[str, str]:
    """The table for `name`, or an empty one for the source language.

    An unreadable table, a truncated file say, is empty rather than a crash."""
    if name == SOURCE:
        return {}
    try:
        data = json.loads((LOCALES / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, str) and value}


def convention(name: str, default: str) -> str:
    """A writing convention of the language in use, rather than a sentence.

    A decimal separator, say (0,07 in French). It is held in the same table,
    under a key prefixed with "#", so that a language ships in one file.
    """
    language()
    return _catalogue.get(f"#{name}", default)


def answers(name: str) -> frozenset[str]:
    """The words the language in use accepts for the answer `name`.

    Read from `#{name}_answers`, comma-separated, on top of the English words the
    caller holds: a French screen announcing `(o/n)` takes its `o`. Empty when
    the table has no such key.
    """
    words = convention(f"{name}_answers", "")
    return frozenset(word.strip().lower() for word in words.split(",") if word.strip())


# The two answers no screen owns: the way out, taken by a question asked in the
# middle of a command as by a menu. Every other table of words lives beside the
# question that shows it.
#
# "\x1b" is Escape: during line entry the terminal buffers it like any other
# character, and it arrives with the Enter after it. The key-driven menus take it
# too, so the same gesture leaves the question that follows. It is announced
# nowhere: "b" is the taught gesture, and the only one every terminal can give.
BACK_ANSWERS = ("b", "back", "\x1b")

# What stands for "leave this screen": the key, and the word written next to it.
QUIT_ANSWERS = ("q", "quit")


def means(answer: str, english: tuple[str, ...], name: str) -> bool:
    """Whether `answer` is one of the words a question takes for `name`.

    The caller's English words hold on every screen; the language in use adds
    its own through `answers`.
    """
    return answer in english or answer in answers(name)


def translate(text: str, context: str = "") -> str:
    """The `text` in the language in use, or `text` itself when untranslated.

    `context` keys apart the meanings of one word: `_("light", "palette")` is
    looked up under `palette|light`, beside `compression|light`. It is never
    shown, and English ignores it. A contexted lookup falls back on the English,
    never on the plain key, which may hold the other meaning.
    """
    if language() == SOURCE:
        return text
    if context:
        return _catalogue.get(f"{context}|{text}", text)
    return _catalogue.get(text, text)


# The gettext name, short for hundreds of call sites.
_ = translate


# -- Counts ---------------------------------------------------------------------
# How many forms a language counts in, and which count takes which, is a
# convention each table states in `#plural_rule`, as the CLDR writes it for whole
# numbers: one clause per form, `name: condition`, the last with no condition. A
# condition is `n` or `n % k`, `=` or `!=`, values and ranges, `and` binding
# closer than `or`: `n % 10 = 2..4 and n % 100 != 12..14`.
#
# `one` is keyed under the English singular, the last form under the English
# plural, and any other form under the plural with its name at the head
# (`few|{count} cards`).

# The English rule, also given to a table whose rule does not read: one apart
# from every other count, zero included.
DEFAULT_RULE = "one: n = 1; many"

_RELATION_RE = re.compile(r"n(?:\s*%\s*(\d+))?\s*(!=|=)\s*(\d+(?:\.\.\d+)?(?:\s*,\s*\d+(?:\.\.\d+)?)*)")


@functools.cache
def _parse_rule(text: str) -> tuple | None:
    """`text` as ((name, conditions), ...), or None if it does not read.

    A condition is a tuple of `or` groups, a group a tuple of `and` relations,
    a relation (modulo, negated, ranges). The last form has no condition.
    """
    clauses = [clause.strip() for clause in text.split(";") if clause.strip()]
    rule = []
    for rank, clause in enumerate(clauses, 1):
        name, colon, condition = (part.strip() for part in clause.partition(":"))
        last = rank == len(clauses)
        if not re.fullmatch(r"[a-z]+", name) or bool(colon) == last:
            return None
        groups = []
        for group in filter(None, condition.split(" or ")):
            relations = []
            for relation in group.split(" and "):
                found = _RELATION_RE.fullmatch(relation.strip())
                if found is None:
                    return None
                modulo, operator, values = found.groups()
                ranges = tuple((int(low), int(high or low)) for low, _dots, high in
                               (value.strip().partition("..") for value in values.split(",")))
                relations.append((int(modulo or 0), operator == "!=", ranges))
            groups.append(tuple(relations))
        rule.append((name, tuple(groups)))
    return tuple(rule) or None


def _rule(table: dict[str, str] | None = None) -> tuple:
    """The rule of `table`, or of the language in use; the English one if it does
    not read - a rule mistyped costs the agreement, never the run."""
    text = (convention("plural_rule", DEFAULT_RULE) if table is None
            else table.get("#plural_rule", DEFAULT_RULE))
    return _parse_rule(text) or _parse_rule(DEFAULT_RULE)


def _holds(relation: tuple, count: int) -> bool:
    modulo, negated, ranges = relation
    value = count % modulo if modulo else count
    return any(low <= value <= high for low, high in ranges) != negated


def form(count: int) -> str:
    """The name of the form `count` takes in the language in use: `one`, `many`,
    or whatever else its `#plural_rule` names."""
    rule = _rule()
    for name, groups in rule[:-1]:
        if any(all(_holds(relation, count) for relation in group) for group in groups):
            return name
    return rule[-1][0]


def forms(table: dict[str, str] | None = None) -> tuple[str, ...]:
    """The names of the forms of `table`, or of the language in use, in order."""
    return tuple(name for name, _groups in _rule(table))


def _counted_entry(name: str, singular: str, plural: str, last: str,
                   context: str) -> tuple[str, str]:
    """The source text and the context the form `name` is looked up under."""
    if name == "one":
        return singular, context
    if name == last:
        return plural, context
    return plural, f"{context}|{name}" if context else name


def counted(count: int, singular: str, plural: str, context: str = "") -> str:
    """The form of a sentence, or of a word, that agrees with `count`.

    The caller gives both English forms and the count; the language picks the
    form by its `#plural_rule`, and may have more than two. `context` keys the
    pair apart as `translate` keys a word.
    """
    name = form(count)
    if language() == SOURCE:
        return singular if name == "one" else plural
    return translate(*_counted_entry(name, singular, plural, forms()[-1], context))


def counted_keys(singular: str, plural: str, context: str = "",
                 table: dict[str, str] | None = None) -> list[str]:
    """The catalogue keys a `counted` pair needs in `table`: one per form."""
    names = forms(table)
    keys = []
    for name in names:
        text, under = _counted_entry(name, singular, plural, names[-1], context)
        key = f"{under}|{text}" if under else text
        if key not in keys:
            keys.append(key)
    return keys


def agreed(count: int, text: str, context: str = "") -> str:
    """`text` in the form the language in use gives it at that count.

    For what agrees although the English shows nothing of it, such as the
    fragments of "3 readings, 2 already handled, 1 too long": the entry is keyed
    under the name of the form (`one|`, `many|`...). `context` names the thing the
    fragment agrees with when one sentence serves several, never a grammatical
    category. English gets the text back untouched.
    """
    head = form(count)
    return translate(text, f"{context}|{head}" if context else head)


def agreed_keys(text: str, context: str = "",
                table: dict[str, str] | None = None) -> list[str]:
    """The catalogue keys an `agreed` fragment needs in `table`: one per form."""
    return [f"{context}|{name}|{text}" if context else f"{name}|{text}"
            for name in forms(table)]


def quoted(name: str) -> str:
    """A name as the language in use quotes it.

    A convention rather than a sentence: quotes keyed into each catalogue line
    could quote one name two ways on one screen.
    """
    return convention("quote_open", '"') + name + convention("quote_close", '"')


def listed(items) -> str:
    """Items of a list in a row, parted as the language in use parts them.

    `#list_separator`: Japanese runs a list on 「、」 where English puts ", ".
    """
    return convention("list_separator", ", ").join(items)


def sentence(text: str) -> str:
    """`text` closed by the full stop of the language in use (`#full_stop`).

    For a sentence the code composes of fragments: one held whole in the
    catalogue carries its own stop.
    """
    return text + convention("full_stop", ".")
