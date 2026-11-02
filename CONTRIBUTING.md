# Contributing

## Kotogen takes no contributions

Kotogen is written by one person, who keeps all of its copyright, and is
published under the [GNU AGPL-3.0-or-later](LICENSE). It therefore accepts no
pull requests and nothing written by someone else: no code, no translation, no
instruction for the model, no data.

Report what you noticed while using it in an
[issue](https://github.com/delordt/kotogen/issues): a bug, a card that came out
wrong, a sentence on a screen that reads badly, an idea. Describe it rather
than send a fix: changes are written here from your description, and a patch
or a translated file posted in an issue is not used. A vulnerability is not
reported in an issue: [SECURITY.md](SECURITY.md) says how.

The rest of this file is about how the repository is written.

# Writing in this repository

Everything written here is English: the code, the names, the comments, the
documentation, the configuration files, the instructions sent to the model and
the commit messages. The program also speaks French and Japanese: its screens
and its cards can be switched to either. French text lives only in the places
listed under "Where French is written, and why", each for a stated reason.
Japanese is what the program teaches, and is written wherever a card, a rule or
a test needs it.

It comes down to three rules.

## 1. A test keeps the code English

`tests/test_language.py` rejects French in comments, docstrings, identifier
names and module filenames, in every Python file under `src/` and `tests/`,
including files added later, with nothing to declare. The same test reads the
documentation, the configuration files, the `context.md` of the templates, the
comments of every template, the preview page, the header lines of the data
tables, `prompts/en/` and `prompts/structure/`.

It skips text between backticks, so a comment can still name a French word or
a tag. A docstring that mentions `légère` must put it in backticks, or the
accent check flags it.

The word check does not cover two conventions, which are punctuation:

- **A colon is spaced by the language that writes it.** English writes
  `Expression: 猫`, French `Expression : 猫`. `i18n.convention` spaces it for
  the screens and `prompts.say` for what is sent to the model; a colon typed
  straight into an f-string bypasses both. `tests/test_language.py` flags a
  French-spaced colon in an English string of `src/`.
- **A dash closing an aside takes no comma after it**, and a percent sign is
  not spaced. No test checks either; they are how the prose here is written.

## 2. What reaches the screen goes through `kotogen.i18n`

Write the English sentence in the code, wrapped in `_()`, and put its
translation in each table of `src/kotogen/locales/` (`fr.json`, `ja.json`),
keyed by that exact English sentence. A missing key falls back to the English,
so an incomplete table shows a sentence, never a placeholder.

```python
from kotogen.i18n import _

console.item(_("Past-paper booklet: {name}").format(name=path.name))
```

Eight things to respect:

- **Never call `_()` at module level.** It would resolve the language at import
  time, before `cli.main()` has loaded the settings that carry it. Hold the
  English in a constant and wrap it where it is raised or printed: see
  `anki.connect.UNREACHABLE`. A class attribute that reaches the screen is the
  same case: `sources.TextSource.loading` is declared in plain English and
  `sources.each()` calls `_()` on it.
- **Named placeholders, never positional.** A translator can reorder
  `_("HTTP {code}, trying again in {delay}s...")`; `%s` cannot be reordered.
- **A count is agreed by the language, never by the call site.** Hand the
  count and both English forms to `i18n.counted(n, singular, plural)`. Which
  form `n` takes, and how many forms there are, comes from the `#plural_rule`
  of the table, written the way the CLDR writes it: `one: n = 1; many` for
  English (`i18n.DEFAULT_RULE`), `one: n = 0,1; many` in French, `many` alone in
  Japanese, three forms in Russian. The English singular keys the `one` form,
  the English plural the last one, and any other form is an entry under the
  plural with its name at the head (`few|{count} cards`). A call site that
  tests `> 1` or `== 1` itself, or picks between two lookups, gives two forms
  to a language that may have three. A difference of meaning rather than of
  form stays at the call site: yesterday is one day (`backup._age`), and a
  single passage is not a run of them.
- **What agrees with the count goes in the entry, not around it.**
  `console.plural(n, "card")` takes the ENGLISH noun and translates it itself,
  forming the English plural with an "s"; a noun that does not follow that rule
  passes its plural (`"entry", "entries"`). Anything else that agrees means the
  whole sentence goes through `counted`, one English sentence per form: see
  `seen.describe`, `proofreading.summary`. Never an `(s)` bolted on.
- **What agrees although the English shows nothing of it** goes through
  `i18n.agreed(count, text, context)`. A summary names its noun once at the
  head and continues in fragments ("3 readings, 2 already handled, 1 too
  long"), and English writes those fragments the same way at every count, so
  there is no second English string to key the other forms. The count keys
  them instead, under the name of its form: `one|` and `many|` in French, one
  more prefix per form in a language that has more. `context` names what the
  fragment agrees WITH when one English sentence serves several kinds of thing.
  It names the thing, never a grammatical category: which categories a
  language has is its own business. `tests/test_i18n.py` requires one entry per
  form of every call, so a missing form fails the suite.
- **Quotation marks are a convention, not a sentence.** `i18n.quoted(name)`
  quotes a name the way the language does. Never put quotes in a catalogue
  key: the same name would come out quoted two ways on one screen.
- **A word that means two things carries a context**, given as the second
  argument: `_("light", "palette")` is looked up under `palette|light`, next to
  `compression|light`. The context is never shown and English ignores it. A
  lookup with a context does NOT fall back on the plain key: preventing that
  fallback is its purpose.
- **A column is counted in screen columns.** A kanji takes two where `len`
  counts one, so a translated label is padded with `console.pad` and measured
  with `console.width`, never with `f"{label:<20}"`, or a Japanese menu loses
  its columns.

What is applied rather than translated (the decimal and thousands separators,
the colon, the quotation marks, the dates, the money format, the plural rule)
goes through `i18n.convention()` and the `#`-prefixed keys of the same table.
So do the words a question accepts on top of its English ones (`#yes_answers`,
`#back_answers`...), read by `i18n.answers()`: the code holds only the English
answers, and a screen that announces `(o/n)` lists `o` in its own table.

The `--help` of the command line stays English in every language, on purpose:
the option names and the values they accept are English, and a help page
translated around them would be half in each language.

### The catalogue is easy to desynchronise

`tests/test_i18n.py` checks that every `_("literal")` of `src/` has its entry
in every table, and that every literal handed to `counted`, `agreed` and
`console.plural` has one entry per form the table counts in. It cannot see a
label held in a constant or a table and translated where it is displayed
(`marks.FLAG_COLOURS`, `audio_split.LABELS`, `audio_split.RANKS`). Those are
listed by hand, each in a test of its own that names the table: the
`test_every_...` tests of `tests/test_i18n.py`, and their equivalents in the
module's own test file. They check every table, not only French, and ask
`i18n.counted_keys` for the keys of a table that agrees. What is sent to the
model is listed in `_table_driven()` of `tests/test_prompts.py`. When you add
such a table, add its test too: nothing else reports a missing entry, and the
suite passes while the screen shows English.

The other direction is not tested, on purpose: many entries are reached
through a variable, and a scan of the literals would report them as unused. An
unused entry costs a line in a file; a missing one leaves part of a screen in
English.

## 3. The schema of the user's collection is English, and so is what it files things under

- **English, in every language of the cards**: note types (`Vocabulary`,
  `Listening`), deck names (`Japanese::Reading`), card names (`Recognition`,
  `Production`) and field names (`Translation`, `Decoy1`, `Answer`). They are
  a schema, not text in a language, and one note type has to serve every
  language, so there is no second set to choose from. Renaming one in Anki
  afterwards renames nothing: kotogen then aims at ANOTHER type, and the notes
  stay in the old one.
- **The tags too** (`Check::Reading`, `Level::N4`, `Grammar::N4::ながら`),
  for one more reason: a card is FILED under its tags, so they must not change
  meaning when a setting changes. `tag:Check::Reading` is a search users type
  from memory, and it must find the same cards on a French screen as on an
  English one. The Japanese inside a tag stays Japanese (`Adjective::な`,
  `Verb::一段動詞`): it is the grammatical category itself, and it is what the
  badge on the card prints.

Only what the screen shows of these is translated. The code of the templates is
not content either: its comments, JavaScript names, classes and CSS properties
are English, and so are the template setting keys and values (`vocab.tts=no`,
`on-click`), even though they live in a file the user reads (`templates.env`).

## What a card says is a third question

It follows the `all.lang` setting, not the language of the screens: a French
screen filling an English deck is a valid setup. The setting selects the
instructions that ask the model for card content, and the trap is that what
the code BUILDS around them is part of the instruction too.

- **An instruction that asks for CARD TEXT** lives in `prompts/en/`,
  `prompts/fr/` and `prompts/ja/` side by side, and everything composed around
  it (the user message, `quota.instruction`, the card laid out by
  `review.propose_changes`) follows the same language. It is written in
  English at the call site and translated through `prompts/<lang>/wording.json`
  by `prompts.say()`, never by `_()`, which answers for the screen. The folders
  hold the same twenty-two names, and **none stands in for another**: an
  instruction missing from `en/` raises an error rather than come back in
  French, because a deck quietly filled in the wrong language costs more than
  a broken install that says so.
- **An instruction that hands back STRUCTURE** (`audio_split`, `pdf_*`,
  `grammar_detect`, `grammar_page`, `vocab_extract`, `vocab_theme`,
  `kanji_word`, `reading_compose`) has one copy only, in English, in
  `prompts/structure/`. It is answered in JSON, so it has no language of the
  cards to follow: what the code composes around it is written in English
  beside it, as a plain literal rather than through `prompts.say()`, and
  `structure/` is not a language (`prompts.languages()` does not list it).
  Nothing it returns is in the language of the cards: the Japanese of a PDF
  transcription, or of a text composed for the deck, is Japanese whatever that
  language is.
- **The protocol is English everywhere**, whatever language the instruction
  around it is written in: the JSON keys the model answers with (`kind`,
  `blocks`, `lines`, `keep`, `cards`, `duplicates`) and the values it puts in
  them (`collection`, `stream`, `exam question`, `duplicate`, `variant`). It is
  schema, like a field name, and the code that compares against it is English.
  Every card-text instruction (except `ask`, which has no protocol, and the
  shared fragment `vocab_fields`) tells the model so in its own language, so
  that a model reading a French sample does not answer with French keys.
  `PROTOCOL_SAID` of `tests/test_prompts.py` holds that wording per language.
  Where such a value reaches the screen it is still translated where it is
  displayed, through `audio_split.LABELS` and the like.
- **A structure instruction that asks for FREE TEXT** rather than a protocol
  value (the `error` of the PDF contract and of `grammar_page`, the `reason` of
  `kanji_word`, the `meaning` of `grammar_page`) gets it in English, the
  language the instruction is written in. That text is shown or sent back as
  it stands, inside a sentence the code wrote in English, so English is what
  reads as a whole. `grammar_page` says "in English" for its `meaning`.

The preview follows the same setting: `preview.SAMPLES` holds the English cards
and, in `overlays`, the same cards in each other language of the cards;
`preview.samples()` picks the one asked for at call time, never at import.

## Note types change by addition

A release may add a field or a card to a note type; it never renames or removes
one. `kotogen deck install` compares each type with its spec
(`notetypes.plan_for`): it adds a missing field on its own and offers to add a
missing card, so an addition reaches a collection that already holds notes
without anyone editing them. A rename has no such path: Anki would see one
field disappear and another appear, and the content of the first would stay
behind.

`tests/test_schema.py` holds what has been shipped (`SHIPPED`) and enforces the
rule. It fails on a note type, field or card removed or renamed, on fields or
cards reordered, on a default deck renamed, on a first field that changes (Anki
checks duplicates on it, and an added field arrives empty), on a type turned
Basic or Cloze, and on an addition it does not list yet. An addition goes into
`SHIPPED` at its rank, with its changelog line below; an entry never leaves it.

A field must not depend on `deck install` alone: the send adds to the note type
the fields its cards carry and the type lacks (`send.complete_fields`), because
AnkiConnect silently drops the value of an unknown field.

Every such change gets a line under the **Note types** heading of
`CHANGELOG.md`, naming the type, the field or card, and what `deck install`
does about it:

```markdown
### Note types

- `Listening`: field `Video` added; `kotogen deck install` creates it.
```

## Comments say why, in a line or two

A comment says what the code cannot: why it is written this way, a quirk of Anki,
of a terminal or of a model, an order that matters, a value chosen for a reason.
What the next line plainly does is not said above it.

- A docstring is a summary line, then at most a short paragraph when the signature
  hides a contract: what None means, a side effect, an argument that is not obvious.
- A comment takes one or two lines; an invariant or a trap may take three.
- A comment describes the code as it is: not what it replaced, not the case that
  led to it.

## Adding a language

The language of the screens and the language of the cards are added
separately (see "What a card says is a third question"). Neither touches a
collection: the note types, fields, decks and tags are English in every
language, and the templates print no prose, so a new language never needs a
migration. Nor is a language declared anywhere: the program finds it by its
files, and the test suite then names what it still lacks.

Ask for a language in an issue, not in a pull request: it is written here, like
every other line of the repository, and a translation sent in a pull request or
posted in an issue is not used. The steps below are the ones the maintainer
follows once a language has been asked for in an issue; they are not a way to
send one. What the language needs from whoever asks is a reader, to say in
issues what reads wrong, in the first translation and in every sentence the
program gains afterwards. Without that reader, a table goes wrong one line per
release and nobody notices.

### The screens

1. Copy `src/kotogen/locales/fr.json` to `src/kotogen/locales/<code>.json` and
   translate the values. The keys stay English: they are the sentences the code
   writes, and the table is looked up by them.
2. Rewrite the `#` entries, which are conventions rather than sentences:
   `#language` (the name of the language in itself, as the list of languages
   shows it), the colon, the quotation marks, the decimal and thousands
   separators, the dates, the money, and the words a question accepts on top of
   its English ones (`#yes_answers`, `#back_answers`...).
3. Set `#plural_rule`. Copy the rule for whole numbers from the CLDR plural
   rules, written with `n`, the only operand the parser reads: one clause per
   form, its name, a colon, its condition, and a last clause with no condition
   that takes every count left -
   `one: n % 10 = 1 and n % 100 != 11; few: n % 10 = 2..4 and n % 100 != 12..14; many`.
   `one` is the form keyed under the English singular, the last form the one
   keyed under the English plural. Any other form needs entries of its own:
   `<form>|<English plural>` beside each pair, and `<form>|<fragment>` for what
   goes through `agreed`. A language without grammatical number names its
   single form `many`.
4. Run `pytest tests/test_i18n.py`. `test_every_screen_string_has_its_french`
   counts, for your code, the entries the table still lacks, form by form, and
   shows the first three; the tests of the hand-listed tables name theirs. The
   single-letter keys of a prompt stay English (`[y]`) whatever the word beside
   them says, and a test checks that too.

The `--help` stays English, as it does in every language.

### The cards

1. Write `src/kotogen/prompts/<code>/`: the twenty-two instructions of
   `prompts/en/`, translated, and `wording.json`, the fragments the code
   composes around them, keyed by their English. The folder IS the language:
   `all.lang` offers it from then on, and no folder stands in for another. The
   protocol stays English (see above): every instruction that asks for card
   text says so to the model in its own words, and those words go into
   `PROTOCOL_SAID` of `tests/test_prompts.py`.
2. Give the language its English name in `templates.LANGUAGE_NAMES`, and that
   name its translation in every screen table, under the `language` context
   (`language|Spanish`).
3. Give `maintenance/review.py` its stop words (`_STOP_WORDS`), the function
   words left out when two translations are compared. A language written
   without spaces between its words needs more than a list: it goes into
   `_TAGGED`, which hands its glosses to a tagger. Japanese uses the one that
   lays the readings (`furigana.get_tagger`).
4. Translate the preview samples: an entry under its code in the `overlays` of
   every sample of `preview.SAMPLES`, for the fields that carry language.
5. Optionally, a gloss column in `data/jlpt_grammar.tsv` and its code in
   `grammar_table.MEANING_LANGUAGES`. Without it a rule is glossed in English,
   which reads worse but leaves no field empty.
6. Run the suite: `test_prompts.py`, `test_templates.py`, `test_preview.py` and
   `test_maintain.py` name what is missing.

No test can check whether a deck written in the language reads well. Generate
cards of each kind and read them.

## Where French is written, and why

Everything below is French on purpose. The language test lets it through
because it sits between backticks, in a fenced block, in a string literal, or
in a file the test does not read.

- **`src/kotogen/locales/fr.json`**, the French interface itself.
- **`src/kotogen/prompts/fr/`**, the instructions that ask for French cards, and
  its `wording.json`, the fragments the code composes around them.
- **The French gloss column of `src/kotogen/data/jlpt_grammar.tsv`**, card
  content read by whoever asks for French cards.
- **The content of the `fr` overlays of the preview samples**: it is card
  content, and a preview of a French collection shows French cards.
- **Test data standing for card content or for a user's typed input.** The suite
  asks for French cards by default (`tests/conftest.py`), so that every test
  that goes through `prompts.say` uses `wording.json`; English would test the
  branch that does nothing. That data is what the code handles, not what the
  code says.

---

Two character ranges look French and are not: the `«` of `furigana._OPENERS`,
which lists opening punctuation in any language, and the `À-ÿ` of
`furigana._LATIN_RE`, the Latin-1 letters that tell whether a line is Latin or
Japanese. The patterns of `tests/test_language.py` itself are the same case.
