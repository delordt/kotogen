"""The kinds of card `maintain` goes through, and what each one is made of.

An action (`error`...) is the same on every kind; a kind, one per command that
owns a note type, holds what differs: its fields, the Japanese its `text`
action corrects, the one that names a card on screen, the tags the model may
touch, the actions that apply. What an action means for a kind is in its instruction
(`maintain_flag_<command>`). A flag a kind has no action for is counted by the
survey and the summary, and left where it is.
"""

from __future__ import annotations

from dataclasses import dataclass

# The tags of the vocabulary, as the model is asked to lay them. Never translated
# with the cards: tag names are the collection's schema.
VOCAB_TAXONOMY = """\
- Adjective::い | Adjective::な
- Adverb::Affirmation | Connection | Degree | Frequency | Place | Manner | Negation | Quantity | Question | Time (otherwise Adverb)
- Counter::SmallAnimals | Drinks | Books | Machines | GeneralObjects | LongObjects | SmallObjects | Occasions | People | Time | Age | Floors (otherwise Counter)
- Date::DaysOfMonth | DaysOfWeek | Months
- Noun::Animals | Concepts | Body | Colour | Events | Fruit | Places | Weather | Nature | Food | Objects | People | Health | Time | Clothing (otherwise Noun)
- Verb::一段動詞 | Verb::五段動詞 | Verb::不規則動詞
- Expression | Onomatopoeia"""

# The tags that restrict a word to one use, apart because only `error` reads
# them: a wrong one is a badge that teaches something false, a missing one does
# no harm, and `enrich` would find one to lay on almost any word.
VOCAB_USES = """\
- Register::敬語::尊敬語 | Register::敬語::謙譲語 | Register::丁寧語 | Register::改まった語 | Register::文章語 | Register::口語 | Register::俗語 | Register::蔑称 | Register::古語
- Speaker::男性語 | Speaker::女性語
- Dialect::関西弁
(Register, Speaker and Dialect only when the word is RESTRICTED to that use: a word
that serves in every register, for everyone, everywhere, carries none of them.)"""
USE_TAGS = ("Register::", "Speaker::", "Dialect::")

# The registers, the only tags of a grammar card the model may touch: the
# program lays the rule and the level (see `generators.grammar._REGISTERS`).
GRAMMAR_TAXONOMY = (
    "- Register::常体 | Register::丁寧体 | Register::敬語::尊敬語 | Register::敬語::謙譲語")

# The actions that correct the card they are laid on, through the instruction
# of its kind. `derive` and `duplicate` have passes of their own.
CORRECTING = frozenset({"error", "simplify", "enrich", "text", "renew"})


@dataclass(frozen=True)
class CardKind:
    """One kind of card, as the maintenance sees it."""

    command: str                # vocab, grammar, reading, audio
    fields: tuple[str, ...]     # sent to the model, and the only ones it may write
    # The Japanese the `text` action corrects, whose bare kanji the model is told
    # of. Which fields get readings is the export's rule (`exporter.plain_field`).
    furigana: frozenset[str]
    label: str                  # the field that names a card on screen
    actions: frozenset[str]     # the actions that mean something for this kind
    leech: bool = False         # whether a real leech can be reworked
    # Fields shown to the model for what they say, never written: the rule a
    # grammar card tests is what the card is FOR, not something to correct.
    shown: tuple[str, ...] = ()
    # Fields held one sentence per line and paired by rank (a text, its
    # translation, its timecodes): sent numbered, handed back as arrays, and a
    # change of their count is refused, as the paired fields would slide.
    lines: tuple[str, ...] = ()
    # Fields every card of one passage carries alike (reading, listening): a
    # correction of one of them is a correction of the passage.
    shared: tuple[str, ...] = ()
    # The tags the model may add or remove, by prefix: "" is any tag, and an
    # empty tuple none - the tags of a reading card are the program's own.
    tags: tuple[str, ...] = ()
    # What the model reads the tags against, with the two actions that tag.
    taxonomy: str = ""
    # The tags that restrict a card to one use, by prefix, and what they are read
    # against: `error` reads them on top of the taxonomy, `enrich` neither reads
    # nor touches them (see `VOCAB_USES`).
    use_tags: tuple[str, ...] = ()
    uses: str = ""
    # The checks that belong to a deck of words: a lone kanji that is not one,
    # a card that is not vocabulary at all.
    words: bool = False
    # The actions that have a pass of their own rather than a section of the
    # instruction: they are more than one call, or no correction of the card.
    passes: frozenset[str] = frozenset({"derive", "duplicate"})

    @property
    def notetype(self) -> str:
        """Name of the note type, settings included."""
        from kotogen.cli import deck_config  # late import (cli drags the whole program)

        return deck_config(self.command)[1]

    def taxonomy_for(self, action: str) -> str:
        """What the model reads the tags against under that action, "" for nothing.

        A wrong tag is a mistake and a missing one a gap, so `error` and `enrich`
        read it - and `error` alone reads the tags of a use.
        """
        if action == "error":
            return "\n".join(part for part in (self.taxonomy, self.uses) if part)
        return self.taxonomy if action == "enrich" else ""

    def may_tag(self, tag: str, action: str = "") -> bool:
        """Whether the model may lay or lift that tag on this kind, under that action."""
        if action == "enrich" and tag.startswith(self.use_tags):
            return False
        return any(tag.startswith(prefix) for prefix in self.tags)


VOCAB = CardKind(
    command="vocab",
    fields=("Expression", "Translation", "Context", "Notes", "Example",
            "ExampleTranslation"),
    # `Context` is not one: it holds the language of the card, like the
    # `Translation` and the `ExampleTranslation`.
    furigana=frozenset({"Expression", "Example"}),
    label="Expression",
    actions=CORRECTING | {"derive", "duplicate", "audio"},
    leech=True,
    tags=("",),
    taxonomy=VOCAB_TAXONOMY,
    use_tags=USE_TAGS,
    uses=VOCAB_USES,
    words=True,
)

GRAMMAR = CardKind(
    command="grammar",
    fields=("Sentence", "Translation", "Target", "Hint", "Nuance", "Explanation"),
    furigana=frozenset({"Sentence", "Hint"}),
    label="Sentence",
    actions=CORRECTING | {"duplicate", "derive"},
    leech=True,
    shown=("Rule",),
    tags=("Register::",),
    taxonomy=GRAMMAR_TAXONOMY,
)

# The `text` action corrects the text alone, as its instruction says; the
# question and its choices get their readings as every field written does.
READING = CardKind(
    command="reading",
    fields=("Text", "Translation", "Question", "Answer", "Decoy1", "Decoy2",
            "Decoy3", "KeyLine"),
    furigana=frozenset({"Text"}),
    label="Question",
    actions=CORRECTING | {"duplicate", "derive"},
    leech=True,
    lines=("Text", "Translation"),
    shared=("Text", "Images", "Translation"),
)

LISTENING = CardKind(
    command="audio",
    fields=("Transcript", "Translation", "Question", "Answer", "Decoy1", "Decoy2",
            "Decoy3", "KeyLine"),
    furigana=frozenset({"Transcript"}),
    label="Question",
    actions=CORRECTING | {"duplicate", "derive", "audio"},
    leech=True,
    passes=frozenset({"derive", "duplicate", "audio"}),
    lines=("Transcript", "Translation", "Timecodes"),
    shared=("Audio", "Video", "Transcript", "Translation", "Timecodes"),
)

# In the order of `notetypes.SPECS`, which is the order of every other screen
# that lists the note types.
KINDS: dict[str, CardKind] = {kind.command: kind
                              for kind in (VOCAB, GRAMMAR, LISTENING, READING)}


def of_note(note: dict) -> CardKind:
    """The kind a note belongs to, read off its fields.

    For the places that hold a note, not its kind, and only need its label (the
    report of automatic mode, the screens shared with `ask`). Vocabulary when
    no kind fits.
    """
    fields = note.get("fields") or {}
    for kind in KINDS.values():
        if kind.label in fields and all(name in fields for name in kind.fields):
            return kind
    return VOCAB


def selected(commands: list[str] | None = None) -> list[CardKind]:
    """The kinds a run goes through.

    Those `--type` names, in the order of `KINDS`; otherwise all but the
    commands this profile declares unused (`KOTOGEN_SKIP`).
    """
    if commands:
        wanted = set(commands)
        return [kind for command, kind in KINDS.items() if command in wanted]
    from kotogen.cli import skipped_commands  # late import (see `notetype`)

    skipped = skipped_commands()
    return [kind for command, kind in KINDS.items() if command not in skipped]
