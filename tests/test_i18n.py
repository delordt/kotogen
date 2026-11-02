"""The table the screen is read through (`kotogen/i18n.py`).

A string with no entry comes out in English, which makes an incomplete table
harmless. Only the head of a key is reserved: "#" for a convention, "|" for a
context. A contexted lookup falls back on the English, never on the plain key:
"light" is `claire` for a palette but `légère` for a compression, and an English
word beats a wrong French one.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from kotogen import audio_quality, i18n
from kotogen.anki import templates as card_templates

# Every table but the source's, so a language added later is checked too.
TRANSLATED = [name for name in i18n.available() if name != i18n.SOURCE]


@pytest.fixture(autouse=True)
def restore_language():
    """The language is resolved once and held in a global: hand it back."""
    was_language, was_catalogue = i18n._language, i18n._catalogue
    yield
    i18n._language, i18n._catalogue = was_language, was_catalogue


@pytest.fixture
def french(monkeypatch):
    """A table of our own, so no test depends on what `fr.json` says today."""
    monkeypatch.setattr(i18n, "_language", "fr")
    monkeypatch.setattr(i18n, "_catalogue", {
        "light": "claire",
        "palette|light": "claire",
        "compression|light": "légère",
        "a | b": "a | b (translated)",
        "#quote_open": "« ",
    })


def test_the_source_language_has_no_table_and_hands_the_string_back():
    i18n.use("en")
    assert i18n._("Downloading {name}...") == "Downloading {name}..."
    assert i18n._("light", "compression") == "light"


def test_a_string_with_no_entry_comes_out_in_english(french):
    """The whole reason the table is keyed by the source text."""
    assert i18n._("No card generated.") == "No card generated."


def test_a_context_picks_the_entry_the_word_means_there(french):
    assert i18n._("light", "palette") == "claire"
    assert i18n._("light", "compression") == "légère"
    assert i18n._("light") == "claire"


def test_a_context_with_no_entry_does_not_fall_back_on_the_plain_key(french):
    """`claire` of a palette must not be handed to a compression: the English is
    the fallback, here as everywhere."""
    assert i18n._("light", "encoder") == "light"


# -- The form a sentence takes at a count ------------------------------------
# `#plural_rule` gives a language's forms in the CLDR's words. `counted` keys
# them by the two English forms (`one` under the singular, the last under the
# plural, any other under the plural with its name at the head); `agreed` keys a
# fragment English writes alike at every count by the form's name alone.

# Russian, as the CLDR writes it for whole numbers: 1 карта, 2 карты, 5 карт,
# and 21 takes the form of 1.
RUSSIAN = ("one: n % 10 = 1 and n % 100 != 11; "
           "few: n % 10 = 2..4 and n % 100 != 12..14; many")


@pytest.fixture
def agreeing(monkeypatch):
    """A table of our own: one English fragment, several French forms."""
    monkeypatch.setattr(i18n, "_language", "fr")
    monkeypatch.setattr(i18n, "_catalogue", {
        "#plural_rule": "one: n = 0,1; many",
        "one|, {count} dropped": ", {count} écartée",
        "many|, {count} dropped": ", {count} écartées",
        "episode|one|, {count} handled": ", {count} traité",
        "episode|many|, {count} handled": ", {count} traités",
        "reading|one|, {count} handled": ", {count} traitée",
        "reading|many|, {count} handled": ", {count} traitées",
        "{count} card": "{count} carte",
        "{count} cards": "{count} cartes",
    })


@pytest.fixture
def russian(monkeypatch):
    """Three forms, the middle one keyed under the English plural."""
    monkeypatch.setattr(i18n, "_language", "ru")
    monkeypatch.setattr(i18n, "_catalogue", {
        "#plural_rule": RUSSIAN,
        "{count} card": "{count} карта",
        "few|{count} cards": "{count} карты",
        "{count} cards": "{count} карт",
        "one|, {count} dropped": "one",
        "few|, {count} dropped": "few",
        "many|, {count} dropped": "many",
    })


def test_an_agreed_form_follows_the_count(agreeing):
    assert i18n.agreed(1, ", {count} dropped") == ", {count} écartée"
    assert i18n.agreed(3, ", {count} dropped") == ", {count} écartées"


def test_an_agreed_form_parts_company_where_the_language_says_it_does(agreeing):
    """French writes `0 écartée`, English "0 dropped": the table decides, not a
    `> 1` at the call site.
    """
    assert i18n.agreed(0, ", {count} dropped") == ", {count} écartée"


def test_a_context_agrees_one_sentence_with_each_thing_it_serves(agreeing):
    """One English fragment over an episode and a reading, two French forms."""
    assert i18n.agreed(2, ", {count} handled", "episode") == ", {count} traités"
    assert i18n.agreed(2, ", {count} handled", "reading") == ", {count} traitées"


def test_an_agreed_form_with_no_entry_comes_out_in_english(agreeing):
    """The fallback of the whole module holds here too."""
    assert i18n.agreed(2, ", {count} skipped") == ", {count} skipped"
    assert i18n.agreed(2, ", {count} dropped", "podcast") == ", {count} dropped"


def test_the_source_language_hands_an_agreed_form_back_untouched():
    i18n.use("en")
    assert i18n.agreed(3, ", {count} dropped") == ", {count} dropped"
    assert i18n.agreed(1, ", {count} handled", "episode") == ", {count} handled"


def test_a_counted_sentence_takes_the_form_the_language_gives_the_count(agreeing):
    """French parts the two forms after one, English at one."""
    assert [i18n.counted(n, "{count} card", "{count} cards") for n in (0, 1, 2)]         == ["{count} carte", "{count} carte", "{count} cartes"]
    i18n.use("en")
    assert [i18n.counted(n, "{count} card", "{count} cards") for n in (0, 1, 2)]         == ["{count} cards", "{count} card", "{count} cards"]


def test_a_third_form_is_an_entry_beside_the_english_pair(russian):
    """The form's name keys what the two English sentences cannot."""
    said = [i18n.counted(n, "{count} card", "{count} cards").format(count=n)
            for n in (1, 3, 5, 11, 21, 22, 25, 111)]
    assert said == ["1 карта", "3 карты",
                    "5 карт", "11 карт",
                    "21 карта", "22 карты",
                    "25 карт", "111 карт"]
    assert [i18n.agreed(n, ", {count} dropped") for n in (1, 2, 5)] == ["one", "few", "many"]


def test_the_keys_a_count_needs_are_one_per_form(russian):
    """What the catalogue scan claims of a table: as many entries as forms."""
    table = i18n._catalogue
    assert i18n.counted_keys("{count} card", "{count} cards", table=table) == [
        "{count} card", "few|{count} cards", "{count} cards"]
    assert i18n.counted_keys("x", "xs", "ctx", table=table) == ["ctx|x", "ctx|few|xs", "ctx|xs"]
    assert i18n.agreed_keys(", {count} dropped", table=table) == [
        "one|, {count} dropped", "few|, {count} dropped", "many|, {count} dropped"]
    assert i18n.counted_keys("x", "xs", table={}) == ["x", "xs"]


@pytest.mark.parametrize("rule", [
    "one n = 1; many",        # no colon
    "one: n = 1",             # nothing left for the other counts
    "many; one: n = 1",       # a form after the one that takes everything
    "one: n = one; many",     # a value that is not a number
    "One: n = 1; many",       # a name the heads would not match
])
def test_a_rule_that_does_not_read_counts_the_english_way(monkeypatch, rule):
    """A rule mistyped costs the agreement, never the run."""
    monkeypatch.setattr(i18n, "_language", "xx")
    monkeypatch.setattr(i18n, "_catalogue", {"#plural_rule": rule})
    assert i18n.forms() == ("one", "many")
    assert [i18n.form(n) for n in (0, 1, 2)] == ["many", "one", "many"]


@pytest.mark.parametrize("lang", i18n.available())
def test_every_table_counts_by_a_rule_that_reads(lang):
    """A rule that does not read silently counts the English way."""
    table = i18n._load(lang)
    assert "#plural_rule" in table or lang == i18n.SOURCE
    assert i18n._parse_rule(table.get("#plural_rule", i18n.DEFAULT_RULE)) is not None


def test_only_the_head_of_a_key_is_reserved(french):
    """A sentence carrying "|" is keyed as it stands, context or no context."""
    assert i18n._("a | b") == "a | b (translated)"


def test_a_convention_is_applied_and_not_translated(french):
    assert i18n.convention("quote_open", '"') == "« "
    assert i18n.convention("colon", ": ") == ": "


def test_a_list_and_a_sentence_close_the_way_the_language_does(monkeypatch):
    """Japanese runs a list on 「、」 and ends on 「。」: an ASCII ", " glued between
    two Japanese phrases reads as a typo."""
    monkeypatch.setattr(i18n, "_language", "ja")
    monkeypatch.setattr(i18n, "_catalogue", {"#list_separator": "、", "#full_stop": "。"})
    assert i18n.sentence(i18n.listed(["登録済み 3件", "識別子なし 2件"])) == (
        "登録済み 3件、識別子なし 2件。")
    i18n.use(i18n.SOURCE)
    assert i18n.sentence(i18n.listed(["3 known", "2 with no id"])) == "3 known, 2 with no id."


def test_the_japanese_table_lists_and_ends_its_own_way():
    table = i18n._load("ja")
    assert (table.get("#list_separator"), table.get("#full_stop")) == ("、", "。")


def test_an_unknown_language_falls_back_on_the_source():
    """A typo in a setting must not stop anyone from generating cards."""
    assert i18n.use("klingon") == i18n.SOURCE
    assert i18n._("light", "palette") == "light"


# -- Tables translated at the display site -------------------------------------
# English words held in a table and translated at the display site: the
# catalogue scan finds no `_("literal")` for them, so each table is checked here.

@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_position_of_a_contexted_setting_has_its_french(lang):
    table = i18n._load(lang)
    wanted = [f"{setting.context}|{setting.shown.get(position, position)}"
              for setting in card_templates.SETTINGS if setting.context
              for position in setting.positions]
    assert wanted, "no setting declares a context any more"
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_template_setting_says_itself_in_french(lang):
    """The rest of `templates.SETTINGS`: the labels, what the `deck` summary says
    of a position, and the positions of the settings with no context."""
    table = i18n._load(lang)
    wanted = []
    for setting in card_templates.SETTINGS:
        wanted.append(setting.label)
        wanted += list(setting.changes.values())
        if not setting.context:
            wanted += [setting.shown.get(position, position)
                       for position in setting.positions]
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_flag_of_maintain_says_its_colour_and_its_action_in_french(lang):
    """The colours, the actions and the relations of `derive` are held in tables
    and translated where a header or a proposal shows them."""
    from kotogen.anki.maintain import marks
    from kotogen.maintenance import derive

    table = i18n._load(lang)
    wanted = ([colour.capitalize() for _emoji, colour in marks.FLAG_COLOURS.values()]
              + list(marks.ACTIONS.values()) + list(derive.RELATIONS.values()))
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_line_of_the_main_menu_has_its_french(lang):
    """The names, descriptions and subheadings of the main menu, and the short
    labels of the card commands."""
    from kotogen import interactive

    table = i18n._load(lang)
    wanted = [text for _key, name, description in interactive.status.MAIN_MENU
              for text in (name, description) if text]
    wanted += [label for _key, label in interactive.status.CARD_COMMANDS]
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_step_of_the_getting_started_screen_has_its_french(lang):
    """The steps are translated under the `step` context: `Anki` alone means
    something else in a sentence."""
    from kotogen import getting_started

    table = i18n._load(lang)
    wanted = [f"step|{text}" for _key, name, title in getting_started._STEPS
              for text in (name, title)]
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_provider_and_every_way_out_of_a_dimmed_entry_has_its_french(lang):
    """What the model screen says of each provider, and what a dimmed entry of the
    main menu lacks and where to get it."""
    from kotogen import interactive

    table = i18n._load(lang)
    wanted = [note for _provider, note in interactive.models.PROVIDER_NOTES]
    wanted += [text for pair in (*interactive.status._WAYS_OUT.values(),
                                 interactive.status._KEY_REFUSED) for text in pair]
    # Under a context: the French carries the partitive "a besoin d'Anki" asks for.
    wanted += [f"needs|{need}" for need in interactive.status._NEEDS.values()]
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_notch_of_the_audio_compression_has_its_french(lang):
    table = i18n._load(lang)
    missing = [f"compression|{level.label}" for level in audio_quality.LEVELS
               if f"compression|{level.label}" not in table]
    assert not missing, missing


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_name_of_the_media_sent_with_the_cards_has_its_forms(lang):
    """The exporter counts the media under an English name its callers pass in
    `media_label` ("file", "image", "audio", "media"), unseen by the scan."""
    table = i18n._load(lang)
    wanted = [key for label in ("file", "image", "audio", "media")
              for key in i18n.counted_keys(label, f"{label}s", table=table)]
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_optional_module_says_what_it_allows_in_french(lang):
    """What a module allows, held in `prerequisites.EXTRAS`, is the line read
    before choosing to download it."""
    from kotogen import prerequisites

    table = i18n._load(lang)
    wanted = [extra.what for extra in prerequisites.EXTRAS.values()]
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_category_a_card_is_reported_under_has_its_french(lang):
    """What a card that is not vocabulary really is, held in
    `maintenance.review.CATEGORY_LABELS` and shown by `lone_kanji`."""
    from kotogen.maintenance import review

    table = i18n._load(lang)
    wanted = list(review.CATEGORY_LABELS.values())
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_action_a_flag_can_take_says_what_it_does_in_french(lang):
    """`maintenance.review.ACTION_DESCRIPTIONS`, shown beside each action on the
    screen that gives a flag its action."""
    from kotogen.maintenance import review

    table = i18n._load(lang)
    wanted = list(review.ACTION_DESCRIPTIONS.values())
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_face_and_place_of_a_note_type_has_its_french(lang):
    """The faces a changed card names, and where in the type a change lies
    (`notetypes._PLACE`), translated where `deck install` says them."""
    from kotogen.anki import notetypes

    table = i18n._load(lang)
    wanted = [notetypes.FRONT, notetypes.BACK, *notetypes._PLACE.values()]
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_word_of_ankiconnect_failing_has_its_french(lang):
    """Held in English in `anki.connect` and translated where it is raised."""
    from kotogen.anki import connect

    table = i18n._load(lang)
    wanted = [connect.UNREACHABLE, connect.BAD_KEY, connect.EDITOR_OPEN]
    assert [key for key in wanted if key not in table] == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_refusal_of_an_ai_service_has_its_french(lang):
    """`ai_client.FATAL_AUTH_CODES`, the line that ends a command on a dead key."""
    from kotogen import ai_client

    table = i18n._load(lang)
    wanted = list(ai_client.FATAL_AUTH_CODES.values())
    assert [key for key in wanted if key not in table] == []


def _duplicate_signals() -> set[str]:
    """Every signal a duplicate search appends to its `reasons`, read in the code.

    Held in English and translated where the screen shows them
    (`flag_pass._signals(reasons, _)`, `duplicates`): a new signal is found here
    without anyone listing it.
    """
    from kotogen.maintenance import review

    found = {review._DISTINCT_CONTEXTS}
    for path in Path(i18n.__file__).parent.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "reasons"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                found.add(node.args[0].value)
    return found


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_signal_of_a_possible_duplicate_has_its_french(lang):
    """The signals of the duplicate searches, and the marker of a context that
    already tells two cards apart, shown beside each candidate."""
    table = i18n._load(lang)
    wanted = _duplicate_signals()
    assert {"same reading", "same sentence", "same rule"} <= wanted, \
        "the scan no longer finds the signals"
    assert sorted(key for key in wanted if key not in table) == []


@pytest.mark.parametrize("lang", TRANSLATED)
def test_every_genre_of_the_press_sites_has_its_french(lang):
    """The genre column of the article screen (`press.GENRES`)."""
    from kotogen.generators import press

    table = i18n._load(lang)
    wanted = [*press.GENRES, *(site.genre for site in press.SITES.values())]
    assert [key for key in wanted if key not in table] == []


# -- The catalogue, against the code that reads it -----------------------------
# A shipped language needs an entry for every literal the code translates, or a
# French screen shows English with nothing to report it. The scan only sees
# literals: a string held in a variable is checked table by table instead.
#
# Unused entries are deliberately not reported: many are reached through a
# variable, and a scan of the literals would call them dead.

# What agrees with a count needs one entry per form, and the forms are the
# table's own (`#plural_rule`): the keys are asked of `i18n` against the table
# being checked.
def _keys_of(called: str, node: ast.Call, table: dict[str, str]) -> list[str]:
    """The keys the call `node` reads in `table`, or [] if it is not one that
    reads literals."""
    args = node.args
    context = next((keyword.value.value for keyword in node.keywords
                    if keyword.arg == "context" and isinstance(keyword.value, ast.Constant)),
                   "")

    def text(rank: int) -> str | None:
        if len(args) > rank and isinstance(args[rank], ast.Constant) \
                and isinstance(args[rank].value, str):
            return args[rank].value
        return None

    if called in ("_", "translate"):
        context = text(1) or context
        return [f"{context}|{text(0)}" if context else text(0)] if text(0) else []
    if called == "agreed":
        context = text(2) or context
        return i18n.agreed_keys(text(1), context, table) if text(1) else []
    if called == "counted":
        context = text(3) or context
        if text(1) and text(2):
            return i18n.counted_keys(text(1), text(2), context, table)
        return []
    if called == "plural":
        if text(1) is None or (len(args) > 2 and text(2) is None):
            return []
        return i18n.counted_keys(text(1), text(2) or f"{text(1)}s", context, table)
    return []


def _shown(table: dict[str, str]) -> list[tuple[str, str]]:
    """Every catalogue key the literals of the sources read in `table`.

    As (key, where it is written), the key composed as `i18n` does: context,
    form name, source text.
    """
    found = []
    for path in sorted(Path(i18n.__file__).parent.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            called = (node.func.id if isinstance(node.func, ast.Name)
                      else node.func.attr if isinstance(node.func, ast.Attribute)
                      else "")
            found += [(key, f"{path.name}:{node.lineno}")
                      for key in _keys_of(called, node, table)]
    return found


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_screen_string_has_its_french(lang):
    """A sentence shown to the user has to exist in every language shipped."""
    table = i18n._load(lang)
    shown = _shown(table)
    assert shown, "no call site found: the scan is looking in the wrong place"
    missing = sorted({f"{where} {key!r}" for key, where in shown if key not in table})
    assert not missing, f"{lang}: {len(missing)} with no entry, e.g. {missing[:3]}"


@pytest.mark.parametrize("path", sorted(
    [*i18n.LOCALES.glob("*.json"), *i18n.LOCALES.parent.glob("prompts/*/wording.json")]),
    ids=lambda path: f"{path.parent.name}/{path.name}")
def test_no_key_is_written_twice(path):
    """JSON silently keeps the last of two equal keys: correcting the first
    changes nothing on screen."""
    twice: list[str] = []

    def pairs(items):
        keys = [key for key, _value in items]
        twice.extend(key for rank, key in enumerate(keys) if key in keys[:rank])
        return dict(items)

    json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    assert not twice, f"{path.name}: written twice: {twice}"


# -- The quotation mark, which is a convention and not a sentence --------------
# Never in a key: a name, a fixed label or a command goes into a placeholder,
# quoted by `i18n.quoted` or built by the code, or the same name comes out quoted
# two ways on one screen and a shell command in guillemets. A translation that
# quotes all the same spells the pair as `#quote_open` / `#quote_close` do (a
# narrow no-break space in French), not with whatever space was at hand.

# A double quotation mark of any script, or a pair of single ones around a word:
# an apostrophe (`Anki's`) is not one.
_QUOTATION = re.compile(r"""["“”«»「」]|(?:^|[\s(])'[^'\s][^']*'(?=[\s).,:;]|$)""")


def test_no_key_carries_quotation_marks():
    guilty = sorted({f"{where} {key!r}" for key, where in _shown({})
                     if _QUOTATION.search(key)})
    assert not guilty, (f"{len(guilty)} screen strings quote inside their key: "
                        f"{guilty[:3]} - a placeholder, quoted by `i18n.quoted`")

@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_a_language_quotes_the_way_it_says_it_quotes(lang):
    table = i18n._load(lang)
    opening, closing = table.get("#quote_open"), table.get("#quote_close")
    if not (opening and closing):
        pytest.skip(f"{lang} declares no guillemet of its own")
    head, tail = opening[0], closing[-1]
    guilty = []
    for key, value in table.items():
        if key.startswith("#"):
            continue
        for mark, spelling in ((head, opening), (tail, closing)):
            for index in (i for i, c in enumerate(value) if c == mark):
                seen = value[index:index + len(spelling)] if mark == head \
                    else value[index - len(spelling) + 1:index + 1]
                if seen != spelling:
                    guilty.append(f"{key!r}: {seen!r} for {spelling!r}")
    assert not guilty, (f"{lang} spells its own quotation mark "
                        f"{len(guilty)} other ways: {guilty[:3]} - "
                        f"see `i18n.quoted`")


# The same rule, read in the code: a placeholder between quotation marks is a
# runtime value, which belongs to `quoted`.
_QUOTED_VALUE = re.compile(r"""(['"“«])\s*\{[a-z_]*\}\s*(['"”»])""")


def test_a_value_is_quoted_by_the_language_and_not_by_the_sentence():
    guilty = [f"{where} {key!r}" for key, where in _shown({})
              if _QUOTED_VALUE.search(key)]
    assert not guilty, (f"{len(guilty)} screen strings quote a value themselves: "
                        f"{guilty[:3]} - the pair belongs to `i18n.quoted`")


# -- The number, which is a convention and not a sentence ----------------------
# A call site that picks the form itself (`> 1`, `== 1`) applies one language's
# rule to all, and gives two forms to a language with three: the count goes down
# to `i18n.counted` instead. Only a choice between two lookups, or two keys of
# one, is flagged: not a threshold against "", nor a value picked by count.

def _lookup(node: ast.expr) -> bool:
    """Whether `node` is a catalogue lookup, `.format()`ed or not."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "format":
        node = node.func.value
    return (isinstance(node, ast.Call) and bool(node.args)
            and isinstance(node.func, ast.Name) and node.func.id == "_")


def _small_count(node: ast.expr) -> bool:
    """Whether `node` weighs something against 0, 1 or 2."""
    return (isinstance(node, ast.Compare) and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
            and node.comparators[0].value in (0, 1, 2))


def test_a_count_is_agreed_by_the_language_and_not_by_the_call_site():
    guilty = []
    for path in sorted(Path(i18n.__file__).parent.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            # `_("P") if n > 1 else _("S")`
            if isinstance(node, ast.IfExp) and _small_count(node.test) \
                    and _lookup(node.body) and _lookup(node.orelse):
                guilty.append(f"{path.name}:{node.lineno}")
            # `_(forms[1] if n > 1 else forms[0])`
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "_" and node.args \
                    and isinstance(node.args[0], ast.IfExp) \
                    and _small_count(node.args[0].test):
                guilty.append(f"{path.name}:{node.lineno}")
    assert not guilty, (f"{len(guilty)} call sites agree a count themselves: "
                        f"{guilty[:3]} - the boundary belongs to `i18n.counted`")


def test_no_call_site_asks_the_language_for_a_yes_or_no():
    """A `takes_plural` answering "plural or not" would allow two forms only."""
    assert not hasattr(i18n, "takes_plural")


# -- The plural of the noun, in English ---------------------------------------
# `console.plural` adds an "s" to an English noun given no plural: a noun the "s"
# makes wrong (`entrys`, `matchs`) must pass its own.
_NO_PLAIN_S = re.compile(r"([sxz]|ch|sh|[^aeiou]y)$")


def _counted_nouns() -> list[tuple[str, str]]:
    """Every noun handed to `plural()` with no second form, and where."""
    found = []
    for path in sorted(Path(i18n.__file__).parent.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and len(node.args) == 2
                    and getattr(node.func, "attr", getattr(node.func, "id", "")) == "plural"):
                continue
            noun = node.args[1]
            if isinstance(noun, ast.Constant) and isinstance(noun.value, str):
                found.append((noun.value, f"{path.name}:{node.lineno}"))
    return found


def test_a_noun_the_s_cannot_pluralise_carries_its_own_plural():
    nouns = _counted_nouns()
    assert nouns, "no counted noun found: the scan is looking in the wrong place"
    guilty = sorted({f"{where} {noun!r}" for noun, where in nouns
                     if _NO_PLAIN_S.search(noun)})
    assert not guilty, (f"{len(guilty)} English nouns an \"s\" cannot pluralise: "
                        f"{guilty[:3]} - hand `console.plural` the plural form")


# The single-letter menu keys stay English in every language: `ask_choice` gets
# the accepted letters as a literal (`"yndc"`), so `[o] oui` on a French screen
# would announce a key nothing accepts.
def _keys(text: str) -> list[str]:
    """The single-letter keys a prompt announces, in order.

    `[1-{last}]` is a range the caller builds, not a key.
    """
    return re.findall(r"\[(\w)\]", text)


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_a_translated_menu_announces_the_english_keys(lang):
    table = i18n._load(lang)
    guilty = [f"{source!r} -> {said!r}" for source, said in table.items()
              if _keys(source) and _keys(source) != _keys(said)]
    assert not guilty, (
        f"{lang}: {len(guilty)} prompt(s) announcing a key that is not the one "
        f"`ask_choice` accepts: {guilty[:3]} - translate the word, keep the letter")


# A question typed as a line announces translated letters (the way back of
# `_ask`, a yes/no question): a table must list its own letter among the answers
# it adds (`i18n.answers`), or the screen offers a key nothing accepts.
_ANNOUNCED = (
    (" (b = back)", re.compile(r"\s*\((\w+) ="), "i18n.BACK_ANSWERS", "back"),
    ("(y/n)", re.compile(r"\((\w+)/"), "screen._YES_ANSWERS", "yes"),
)


@pytest.mark.parametrize("lang", i18n.available())
def test_a_question_takes_the_letter_it_announces(lang):
    from kotogen.interactive import screen

    i18n.use(lang)
    holders = {"i18n": i18n, "screen": screen}
    guilty = []
    for source, pattern, english, name in _ANNOUNCED:
        where, table = english.split(".")
        letter = pattern.match(i18n._(source)).group(1)
        if not i18n.means(letter, getattr(holders[where], table), name):
            guilty.append(f"{source!r} announces {letter!r}")
    assert not guilty, (f"{lang}: {guilty} - list the letter under "
                        f"`#<name>_answers` in its table")
