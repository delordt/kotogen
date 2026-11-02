"""What this profile keeps of the repository's card templates.

The repository ships every block, and `templates.env` holds this profile's
differences (`kotogen.choices` says where it is and how it reads). The rendering
can only REMOVE a block already in the template: a setting with several
positions has its variants side by side, each marked with its values, and all
but one go. With every setting at its default, the rendering is what the
repository installs. The markers are comments, and stay with a block kept:
`<!-- kotogen:tts -->` ... `<!-- /kotogen:tts -->` in HTML, `/* kotogen:tts */`
in CSS. `all.lang` alone marks nothing: it decides what the model is asked for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from kotogen import choices as choices_file, prompts, settings
from kotogen.choices import GLOBAL
from kotogen.i18n import _, convention, quoted

# `GLOBAL` prefixes the settings shared by every note type, such as the palette.


# -- The settings declared ----------------------------------------------------

@dataclass(frozen=True)
class Setting:
    """A template setting: what it is worth, and what it removes when it changes.

    `key` carries its command (`vocab.tts`), `marker` does not. `positions[0]` is
    the default; a marker with no value keeps its block while the setting is
    "yes", and the blocks shipped off (tags, TTS) are marked `=yes`.
    """

    key: str                     # vocab.tts
    marker: str                  # tts
    label: str                   # "Speech synthesis (TTS)", for the screen
    positions: tuple[str, ...]   # the first one is the default
    changes: dict[str, str]      # value -> what the `deck` summary says of it
    # Position -> what the screen shows of it, when the value written in the
    # file does not read as it stands (`at-once` is shown "at once"). Absent,
    # the position is shown as written, through the catalogue.
    shown: dict[str, str] = field(default_factory=dict)
    # What these values qualify, as their catalogue context (see `i18n.translate`):
    # French translates "none" or "light" differently from one setting to another.
    # Empty when the values are unambiguous.
    context: str = ""

    @property
    def command(self) -> str:
        """The command whose templates this setting touches (vocab, reading...)."""
        return self.key.split(".", 1)[0]

    @property
    def default(self) -> str:
        return self.positions[0]

    def show(self, position: str) -> str:
        """The position, as it is displayed."""
        return _(self.shown.get(position, position), self.context)


# The English name of each language of the cards, keyed by its folder under
# `prompts/` and translated under the `language` context (`language|French`). A
# folder with no name here is shown as its bare code.
LANGUAGE_NAMES = {"en": "English", "fr": "French", "ja": "Japanese"}


SETTINGS: tuple[Setting, ...] = (
    # In the order of the screens: the note types as in the menus
    # (`interactive.status.CARD_COMMANDS`), each one's settings as the card shows
    # what they touch, front before back, top before bottom; the global ones last.

    # The kanji's level and stroke count, under it on the back: facts one may
    # not want to read at every review.
    Setting("kanji.badge", "badge", "Level and strokes", ("yes", "no"),
            {"no": "kanji level and strokes removed"}),
    # Katakana for on readings is a dictionary convention; hiragana is how they
    # are read in a word. The colours tell on from kun either way.
    Setting("kanji.onyomi", "onyomi", "On readings", ("katakana", "hiragana"),
            {"hiragana": "on readings in hiragana"}),
    # The common readings no word of the card illustrates (生 has twelve). Off
    # by default; "folded" hangs them behind a tab on the strip. The readings the
    # table marks as rare are never on the card.
    Setting("kanji.other-readings", "other-readings", "Other readings",
            ("no", "folded", "shown"),
            {"folded": "other readings folded", "shown": "other readings shown"},
            context="readings"),
    # The same choice as `vocab.example`: the words are read in Japanese.
    Setting("kanji.words", "words", "Words", ("yes", "untranslated"),
            {"untranslated": "kanji words without their translation"},
            {"untranslated": "without their translation"}),
    # The reading of the kanji each word illustrates, at the end of its line.
    # The kanji in the word keeps the colour of that reading without it.
    Setting("kanji.word-readings", "word-readings", "Reading of each word",
            ("yes", "no"), {"no": "reading of each kanji word removed"}),
    Setting("kanji.composition", "composition", "Composition", ("yes", "no"),
            {"no": "kanji composition removed"}),
    Setting("kanji.lookalikes", "lookalikes", "Look-alike kanji", ("yes", "no"),
            {"no": "look-alike kanji removed"}),
    Setting("kanji.notes", "notes", "Notes", ("yes", "no"),
            {"no": "kanji notes removed"}),
    # Off by default, like the vocabulary's: the level they carry is a badge.
    Setting("kanji.tags", "tags", "Tags on the back", ("no", "yes"),
            {"yes": "kanji tags shown"}),

    # "yes": kanji alone on the front, readings with the answer; "no": no
    # readings on either side; "kana": no kanji at all, on both sides. The field
    # keeps its kanji and its readings in every position.
    Setting("vocab.furigana", "furigana", "Writing of the word", ("yes", "no", "kana"),
            {"no": "vocabulary furigana removed", "kana": "vocabulary in kana alone"},
            {"yes": "kanji, furigana on the back", "no": "kanji alone",
             "kana": "kana alone"}),
    # The class of the word under it on both backs (一段動詞, 名詞...). Its
    # colour is the business of the three settings below, and holds without it.
    Setting("vocab.badge", "badge", "Grammar badge", ("yes", "no"),
            {"no": "grammar badge removed"}),
    # The colour of the class (conjugating ending, badge, forms, example box),
    # one switch per family: verbs (一段, 五段, 不規則), adjectives (い, な), the
    # other words. Without its colour, a class takes that of the text.
    Setting("vocab.verb-colours", "verb-colours", "Verb colours",
            ("yes", "no"), {"no": "verb colours removed"}),
    Setting("vocab.adjective-colours", "adjective-colours", "Adjective colours",
            ("yes", "no"), {"no": "adjective colours removed"}),
    Setting("vocab.other-colours", "other-colours", "Other word colours",
            ("yes", "no"), {"no": "other word colours removed"}),
    # The register of the word (謙譲, 口, 男...), read from its tags, beside the
    # badge on both backs. Never on a front: on `Recognition` it gives half the
    # meaning away, and on `Production` the context tells 友達 from 友人.
    Setting("vocab.register", "register", "Register badge", ("yes", "no"),
            {"no": "register badge removed"}),
    # Written into the note whatever the settings, so a toggle costs no call. The
    # context leaves `Recognition` only: on `Production` it is the question.
    Setting("vocab.context", "context", "Context", ("yes", "no"),
            {"no": "vocabulary context removed"}),
    Setting("vocab.notes", "notes", "Notes", ("yes", "no"),
            {"no": "vocabulary notes removed"}),
    # "untranslated" keeps the sentence and drops its translation: the example is
    # read in Japanese.
    Setting("vocab.example", "example", "Example sentence",
            ("yes", "untranslated", "no"),
            {"untranslated": "example without its translation",
             "no": "example removed"},
            {"untranslated": "without its translation"}),
    # The system voice, where the note holds no recording of the word. Off by
    # default: Anki desktop has no Japanese voice on Linux, nor on Windows without
    # its Japanese speech pack, and without one every back prints Anki's error.
    Setting("vocab.tts", "tts", "Speech synthesis (TTS)", ("no", "yes"),
            {"yes": "TTS added"}),
    # Off by default on the three cards that have them: a tag files the card
    # (`Level::N4`), and what it could teach is already a badge.
    Setting("vocab.tags", "tags", "Tags on the back", ("no", "yes"),
            {"yes": "vocabulary tags shown"}),

    # On the statement only: the conjugation hint and the explanation on the
    # back keep their readings in every position.
    Setting("grammar.furigana", "furigana", "Furigana of the statement",
            ("always", "back", "never"),
            {"back": "grammar furigana on the back",
             "never": "grammar furigana removed"},
            {"back": "on the back"}),
    # What is written in the gap on the front (a person, a tense, the plain form
    # to conjugate). Without it the card is harder but solvable, and the back
    # loses the line that sets that word against the answer (降る → 降れば).
    Setting("grammar.hint", "hint", "Hint in the gap", ("yes", "no"),
            {"no": "grammar hint removed"}),
    # How the card asks: "recall" is answered in one's head, "type" puts Anki's
    # input box under the sentence. The `Answer` field is written either way.
    Setting("grammar.answer", "answer", "Answer", ("recall", "type"),
            {"type": "grammar answer typed"},
            {"recall": "in your head", "type": "at the keyboard"}),
    # Here the translation is the main clue, unlike on listening and reading
    # cards: no "never", which would make the card unsolvable.
    Setting("grammar.translation", "translation", "Translation",
            ("at-once", "on-click"), {"on-click": "grammar translation on click"},
            {"at-once": "at once", "on-click": "on click"}),
    Setting("grammar.register", "register", "Register badge", ("yes", "no"),
            {"no": "register badge removed"}),
    # The line under the register badge: a sentence written for this card alone,
    # where the register is one of four fixed words.
    Setting("grammar.nuance", "nuance", "Nuance", ("yes", "no"),
            {"no": "nuance removed"}),
    # The level the rule is filed under (`Grammar::N4::ば`), at the foot of
    # the rule on the back.
    Setting("grammar.badge", "badge", "Level badge", ("yes", "no"),
            {"no": "grammar level badge removed"}),
    Setting("grammar.link", "link", "Link to the entry", ("yes", "no"),
            {"no": "grammar link removed"}),
    # The prose under the name of the rule on the back, with the neighbour it
    # sets the rule against (`≠ 〜たら: …`). The name stays: the link points at it.
    Setting("grammar.explanation", "explanation", "Explanation of the rule",
            ("yes", "no"), {"no": "grammar explanation removed"}),
    # Off by default, like the vocabulary's: the rule they name heads the back.
    Setting("grammar.tags", "tags", "Tags on the back", ("no", "yes"),
            {"yes": "grammar tags shown"}),

    # The level the deck files the note under (`Level::N4`), over the
    # question. A note filed under no level shows no badge in either position.
    Setting("audio.badge", "badge", "Level badge", ("yes", "no"),
            {"no": "listening level badge removed"}),
    # The bar the card draws drives the element of the `Audio` field, which keeps
    # its controls until the script has run; "native" keeps the system's player.
    Setting("audio.player", "player", "Audio player", ("drawn", "native"),
            {"native": "system audio player"},
            {"drawn": "drawn by the card", "native": "the system's"}),
    # How many of the four choices, always written into the note, are shown.
    # "alternate": the rank of the card reads off its ID, and an even rank is
    # answered in one's head.
    Setting("audio.choices", "choices", "Number of choices",
            ("four", "two", "none", "alternate"),
            {"two": "two choices when listening",
             "none": "open questions when listening",
             "alternate": "alternating choices when listening"},
            {"alternate": "alternating"}, context="choices"),
    Setting("audio.transcript", "transcript", "Transcript",
            ("folded", "unfolded"), {"unfolded": "transcript unfolded"}),
    # No "always, with no switch": it would be "at once" without folding back.
    Setting("audio.translation", "translation", "Interlinear translation",
            ("on-click", "at-once", "never"),
            {"at-once": "translation at once", "never": "listening translation removed"},
            {"on-click": "on click", "at-once": "at once"}),
    # What a click on a sentence does: at "sentence", playback stops where the
    # next one starts (the transcript holds only starts), so the setting applies
    # to the cards already in the deck.
    Setting("audio.click", "click", "Click on a sentence", ("sentence", "continue"),
            {"continue": "click continued past the sentence"},
            {"continue": "the rest follows on", "sentence": "stops at the end"}),
    Setting("audio.source", "source", "Source of the extract", ("yes", "no"),
            {"no": "listening source removed"}),

    Setting("reading.badge", "badge", "Level badge", ("yes", "no"),
            {"no": "reading level badge removed"}),
    # "back": the text is read without readings, and the answer gives them.
    Setting("reading.furigana", "furigana", "Furigana of the text",
            ("button", "always", "never", "back"),
            {"always": "text furigana always shown",
             "never": "text furigana removed",
             "back": "text furigana on the back"},
            {"button": "on a button", "back": "on the back"}),
    Setting("reading.translation", "translation", "Interlinear translation",
            ("on-click", "at-once", "never"),
            {"at-once": "translation at once", "never": "reading translation removed"},
            {"on-click": "on click", "at-once": "at once"}),
    # The bar the back sets against the line the answer was drawn from (on a
    # mini-book, the page it opens at). Without it the answer is given, but not
    # where it was.
    Setting("reading.key-line", "key-line", "Where the answer is", ("yes", "no"),
            {"no": "answer no longer pointed at"}),
    Setting("reading.choices", "choices", "Number of choices",
            ("four", "two", "none", "alternate"),
            {"two": "two choices when reading",
             "none": "open questions when reading",
             "alternate": "alternating choices when reading"},
            {"alternate": "alternating"}, context="choices"),
    Setting("reading.markers", "markers", "Markers of the choices",
            ("letters", "digits", "none"),
            {"digits": "markers as digits", "none": "choice markers removed"},
            context="markers"),
    Setting("reading.order", "order", "Order of the choices", ("daily", "fixed"),
            {"fixed": "fixed order of the choices"},
            {"daily": "shuffled each day"}),
    Setting("reading.source", "source", "Source of the text", ("yes", "no"),
            {"no": "reading source removed"}),

    # No template marks it, on purpose: it picks the folder of `prompts/` the
    # model writes the cards from, and the cards name their parts in signs.
    Setting(f"{GLOBAL}.lang", "lang", "Language of the cards",
            tuple(prompts.languages()), {}, dict(LANGUAGE_NAMES),
            context="language"),

    # The mini-book in full screen stays black whatever the palette: it frames
    # images. "auto" follows Anki's night mode, which Anki marks on the card as
    # `.nightMode` (`.night_mode` on an older AnkiDroid).
    Setting(f"{GLOBAL}.palette", "palette", "Palette", ("dark", "light", "auto"),
            {"light": "light palette",
             "auto": "palette following Anki's night mode"},
            {"auto": "follows Anki"}, context="palette"),
)


# The language of the cards, which the rest of the program reads by name rather
# than by a key spelled by hand.
LANGUAGE = next(s for s in SETTINGS if s.key == choices_file.LANGUAGE)


def language_label(code: str) -> str:
    """The name of a language of the cards, as the screens say it.

    Translated (`en` is `anglais` on a French screen); an unknown code is shown
    as it is written.
    """
    return LANGUAGE.show(code)


def describe_language() -> str:
    """What the settings screen shows facing the language of the cards.

    The code and the name, shaped like `i18n.describe` for the screens. Its name
    is in the language of the screen (`en - anglais`), where `i18n` names a
    language in itself: the language of the cards is a property of the deck.
    """
    code = value(LANGUAGE.key)
    return f"{code} - {language_label(code)}"


def _by_marker(command: str, marker: str) -> Setting:
    # Its command first, so a setting of the note type wins over a global one.
    for scope in (command, GLOBAL):
        for setting in SETTINGS:
            if setting.command == scope and setting.marker == marker:
                return setting
    raise RuntimeError(
        f"template: marker \"kotogen:{marker}\" unknown for {command}. "
        f"A tagged block must have its setting in kotogen/anki/templates.py, "
        f"otherwise nobody knows whether to keep it.")


# -- The file of choices ------------------------------------------------------
# Only the differences from the repository are written in it: where it is and
# how it reads are `kotogen.choices`.

def value(key: str) -> str:
    """What this setting is worth: the file, or the repository default.

    An unknown value (the file corrected by hand) falls back on the default
    rather than stopping the command; the screen then shows the value kept.
    """
    setting = next(s for s in SETTINGS if s.key == key)
    chosen = choices_file.values().get(key, setting.default)
    return chosen if chosen in setting.positions else setting.default


def set_one(key: str, choice: str) -> Path:
    """Write a difference, or erase it when going back to the repository default."""
    setting = next(s for s in SETTINGS if s.key == key)
    if choice not in setting.positions:
        raise ValueError(f"{key}: \"{choice}\" is not a known position "
                         f"({', '.join(setting.positions)})")
    current = choices_file.values()
    if choice == setting.default:
        current.pop(key, None)
    else:
        current[key] = choice
    return _write(current)


def set_all(choices: dict[str, str]) -> Path:
    """Set every setting at once: what the preview applies when it is confirmed.

    The file then says exactly this dictionary, not its old content plus it: a
    setting absent from here goes back to the repository. The preview sends
    them all, `all.lang` included.
    """
    differences = {}
    for setting in SETTINGS:
        position = choices.get(setting.key, setting.default)
        if position not in setting.positions:
            raise ValueError(f"{setting.key}: \"{position}\" is not a known "
                             f"position ({', '.join(setting.positions)})")
        if position != setting.default:
            differences[setting.key] = position
    return _write(differences)


def _write(choices: dict[str, str]) -> Path:
    """File the differences, or remove the file when there are none left.

    Never an empty file: nothing customised and no file are one state.
    """
    target = choices_file.file()
    # A line saying the default can only be left behind by a default that moved:
    # it goes at the next write, and with it the file if it was the last.
    choices = {s.key: choices[s.key] for s in SETTINGS
               if s.key in choices and choices[s.key] != s.default}
    if not choices:
        target.unlink(missing_ok=True)
    else:
        lines = [
            "# " + _("What your cards keep of the default templates (the {menu} menu).")
            .format(menu=quoted(_("Templates"))),
            "# " + _("Only the changes are written here: the rest follows `templates/`."),
            "",
        ]
        # In the order the settings are declared, not that of the writes.
        lines += [f"{s.key}={choices[s.key]}" for s in SETTINGS if s.key in choices]
        settings.write_private(target, "\n".join(lines) + "\n")
    return target


def reset() -> Path:
    """Erase every difference at once: this profile follows the repository again.

    The language of the cards stays: it is what they are generated in, not a
    look, and the Appearance screen does not show it.
    """
    return _write({LANGUAGE.key: value(LANGUAGE.key)})


def is_default() -> bool:
    """True if the templates of this profile follow the repository from end to
    end - the language of the cards aside, which changes none of them."""
    return not any(value(s.key) != s.default for s in SETTINGS
                   if s is not LANGUAGE)


def differences(command: str | None = None) -> list[str]:
    """What differs from the repository, spelled out, for the `deck` summary.

    `command` narrows to one note type or to the global settings, as the
    templates screen shows facing each card. The language of the cards is left
    out: it changes no template, and this is what `reset` would undo.
    """
    said = []
    for setting in SETTINGS:
        if setting is LANGUAGE:
            continue
        if command is not None and setting.command != command:
            continue
        current = value(setting.key)
        if current != setting.default:
            said.append(_(setting.changes.get(current, ""))
                        or _(setting.label) + convention("colon", ": ") + setting.show(current))
    return said


# -- The rendering ------------------------------------------------------------

# An opening marker, with its values if it has any, and the line it occupies, so
# a block removed leaves no empty line. HTML, CSS or JavaScript comment syntax:
# the closing delimiter is optional because `//` has none.
_OPENING = re.compile(
    r"[ \t]*(?:<!--|/\*|//)[ \t]*kotogen:(?P<name>[\w-]+)(?:=(?P<values>[\w|-]+))?"
    r"[ \t]*(?:-->|\*/)?[ \t]*\n?")


def _closing(name: str) -> re.Pattern[str]:
    return re.compile(r"[ \t]*(?:<!--|/\*|//)[ \t]*/kotogen:" + re.escape(name)
                      + r"[ \t]*(?:-->|\*/)?[ \t]*\n?")


def markers(text: str) -> set[str]:
    """The marker names placed in this template (for the tests)."""
    return {m.group("name") for m in _OPENING.finditer(text)}


def variants(text: str) -> dict[str, set[str]]:
    """Marker name -> values it carries in this template, for the tests.

    Only the groups of variants: a block with no value does not appear.
    """
    groups: dict[str, set[str]] = {}
    for marker in _OPENING.finditer(text):
        if marker.group("values"):
            groups.setdefault(marker.group("name"), set()).update(
                marker.group("values").split("|"))
    return groups


def render(text: str, command: str) -> str:
    """The template as this profile wants it: minus the blocks left out.

    The markers of the blocks kept stay in place. Even at every default, the
    variants of other positions and the blocks shipped off go: only a template
    with neither comes back as the repository's file.
    """
    position = 0
    while (opening := _OPENING.search(text, position)) is not None:
        name = opening.group("name")
        expected = opening.group("values")
        closing = _closing(name).search(text, opening.end())
        if closing is None:
            raise RuntimeError(f"template: the block \"kotogen:{name}\" is never "
                               f"closed (\"/kotogen:{name}\" is missing).")
        current = value(_by_marker(command, name).key)
        # A block may hold for several positions (`=on-click|at-once`) rather
        # than be written twice.
        keep = (current in expected.split("|") if expected
                else current == "yes")
        if keep:
            # Kept with its markers: search on from its opening's end, or the loop
            # would find it again for ever.
            position = opening.end()
        else:
            text = text[:opening.start()] + text[closing.end():]
            position = opening.start()
    return text
