# Global options

These options apply to every generation command (`kanji`, `vocab`, `grammar`, `audio`,
`reading`); the options specific to each command are documented on its own page.
`--provider` and `--model` also apply to `maintain`, `ask` and `rework`.

| Option | Description |
|---|---|
| `--provider anthropic\|openai\|openrouter` | AI provider (default: `KOTOGEN_PROVIDER`, else `openrouter`) |
| `--model MODEL` | Model, as the provider names it (default: `KOTOGEN_MODEL`, when the provider is the one chosen with it). None is built in: see [AI model](../README.md#ai-model) |
| `--output FILE`, `-o` | Path of the output file: TSV, or JSON Lines if its name ends in `.jsonl` |
| `--format tsv\|json` | Write the cards as a TSV for Anki or as JSON Lines for any other tool (default: `KOTOGEN_FORMAT`, else `tsv`; see [JSON Lines output](#json-lines-output)) |
| `--send` | Send the cards into Anki through AnkiConnect (the default with `KOTOGEN_AUTO_SEND=1`) |
| `--no-send` | Send nothing, even with `KOTOGEN_AUTO_SEND=1` (TSV only) |
| `--proofread ask\|keep\|tag\|drop` | What to do with the cards the model returned damaged (see [Cards to proofread](#cards-to-proofread)) |
| `--yes`, `-y` | Ask nothing: each question takes the answer it takes outside a terminal (see [Asking nothing](#asking-nothing)) |

## Where the settings live

Settings are kept in text files, one line per setting (`KOTOGEN_CURRENCY=EUR`), read at
every start. They are **never** written to the system's environment variables: nothing is
added to your `~/.bashrc`, your PowerShell profile or your session.

Settings and API keys are kept apart:

| What | Where |
|---|---|
| The **settings** | `~/.config/kotogen/settings.env` |
| The **API keys** (and `KOTOGEN_ANKICONNECT_KEY`) | the `.env` at the root of the repository if there is one, else `~/.config/kotogen/secrets.env` |

On macOS the folder is `~/Library/Application Support/kotogen/`, on Windows
`%APPDATA%\kotogen\`. On Linux it follows `XDG_CONFIG_HOME` when that variable is set. On
Linux and macOS the files are written with mode `0600`: only your account can read them.

A setting chosen in the interactive menu is written to its file at once, without a
confirmation question. If the write fails, the menu says so and the setting holds for the
current session only. To change a single command, use the command-line options
(`--provider`, `--output`, `--audio-quality`...): they write nothing and take precedence
over the files.

The repository's `.env.example` lists every setting, with comments. It is a reference,
not a file to fill in whole.

A setting that already has a line in one of the files is rewritten there. This keeps a
line written by hand in the repository's `.env`, which is read first, from overriding what
the menu writes. To move a setting to its own file, delete its line from the `.env`: the
menu writes it in the right place next time.

A variable exported in the shell takes precedence over the files:

```bash
export KOTOGEN_MODEL=publisher/model
```

This is useful for a one-off test. Left in `~/.bashrc` and forgotten, it overrides at
every start the setting the menu writes to the file. `env | grep KOTOGEN` shows what the
shell sets.

The files only carry kotogen's settings: a line naming anything not in `.env.example`
(`PIP_INDEX_URL`, `GIT_SSH_COMMAND`...) is ignored, since the program runs pip and git and
their configuration belongs to the shell. The `.env` read is the one at the root of the
repository the program runs from, wherever you type the command, never the `.env` of
another project in the current folder.

## The two languages

There are two language settings, and both default to **English**:

| Question | Setting | Where it is written | Menu key |
|---|---|---|---|
| What the **screens** say | `KOTOGEN_LANG=fr`, `KOTOGEN_LANG=ja` | the settings file, like every other variable | `l` |
| What the **cards** say | `all.lang=fr`, `all.lang=ja` | `templates.env`, with the other choices about the cards | `g` |

They are independent: a French screen can fill an English deck. The two keys sit one
under the other in the settings menu (see [Settings](interactive.md#the-settings)).

### The screens

`KOTOGEN_LANG=fr` switches them to French, `KOTOGEN_LANG=ja` to Japanese:

```dotenv
KOTOGEN_LANG=fr
```

In the menu, press `s` for the settings, then `l`: each language is listed by its code and
its own name, and the screens switch as soon as you choose.

The code is written in English, and every other language is a table under
`src/kotogen/locales/`. A sentence missing from a table shows in English rather than as a
placeholder, so a language can be translated a part at a time. The
[preview page](card-templates.md#the-preview) follows this setting too: it has no table of
its own, and receives its words, already translated, with the cards.

The `--help` of the command line stays in English: the option names and their values
(`--audio-quality light`) are what you type, and they are English in every language.

### The cards

`all.lang` sets the language of the instructions sent to the model, and so of what a card
says: translations, questions, decoys, explanations. It does not change how a card looks:
the templates print no prose.

It is kept in `templates.env` with the other card settings, not in the settings file. Set
it with the `g` key of the settings or on the language page of the getting-started guide;
the Appearance screen does not show it (see [Card
templates](card-templates.md#the-language-of-the-cards)).

The **schema** does not follow it: deck names, note types, fields and tags (`Translation`,
`Decoy1`, `Check::Reading`) are the same in every language of the cards, and a French card
holds French text under them. That is what lets one note type serve every language.

The meanings in the JLPT rules table follow both settings: the list of rules shows them in
the language of the screens, and the same meaning goes to the model in the language of the
cards (see [The rules table](grammar.md#the-rules-table)).

## Optional modules

The core of the program needs no optional module: the default provider is called with the
standard library. Everything else is a pip extra: the native Anthropic and OpenAI
providers, PDF pages rendered as images, Whisper transcription, NHK capture and YouTube
videos.

**On the first run in an environment**, the program lists what is missing with its
download size, and installs it if you accept:

```
2 optional modules missing (first run):
   20 MB   the pages of a document as images (Reading as a mini-book)
   1.2 GB  transcribing local audio files (Whisper)
   [i] install (1.2 GB)  [n] not now

Installing 2 modules (1.2 GB)… (2 out of 2)
```

Asking at the start avoids finding a module missing after a paid AI call: without
`pypdfium2`, a `reading` run could pay for the call that decides a PDF is a mini-book,
then fail to render its pages.

When the [getting-started guide](interactive.md#getting-started) opens on the first
launch, this question is its last page instead; if you skip it there, it is asked at the
start of the next run.

The answer is remembered **per environment**: a refusal is not asked again, and two venvs
on the same disk keep separate answers. A module added to the program later has never
been offered, so it is asked about on its own. Outside a terminal (CI, a script,
redirected output), nothing is asked or installed unless `KOTOGEN_INSTALL=always`.

The `KOTOGEN_INSTALL` setting in the [settings](#where-the-settings-live) takes three
values:

| Value | What it does |
|---|---|
| `ask` | The default: the question is asked once per environment, and the answer is remembered |
| `always` | Whatever is missing is installed without a question, at every run. Use it to try again after a network failure |
| `never` | Nothing is installed |

With any value, a command that needs a missing module still says which one to install, as
the command to type in the kotogen folder (`pip install -e ".[youtube]"`).

Two things are not installed this way:

- **FFmpeg** is a system package, not a pip package, and installing it needs
  administrator rights. The program tells you early, with the command for your platform
  (`winget install ffmpeg`, `sudo apt install ffmpeg`, `brew install ffmpeg`). After
  `winget`, open a new terminal: the one it ran in may not see `ffmpeg` on its PATH yet.
- **The weights of the Whisper models** are downloaded by Whisper itself on the first
  transcription, for the model you ask for.

Outside a virtual environment nothing is installed: the distributions refuse installs into
the system Python ([PEP 668](https://peps.python.org/pep-0668/)). The `pip install`
commands are shown for you to type instead.

## Cost of each run

Every command ends with what it consumed, including when it fails or is interrupted (the
calls already made are paid for):

```
7 AI calls ($0.02, 1 min 12 s)
```

The duration is the whole wait: it starts once the command is settled (after the
interactive dialogue) and stops when the cards are delivered, network, batches and sending
into Anki included. When comparing two models, look at it as well as the cost: the
cheapest model is sometimes the slowest. A command that makes no AI call (`backup`,
`deck`) prints no cost line.

In interactive mode with verbose mode on (the `v` key, or `KOTOGEN_VERBOSE=1`), the
equivalent command line is printed just above it.

The cost is the amount OpenRouter bills for the model actually served, not a local
estimate. The native `anthropic` and `openai` providers return no price, so the line
shows the tokens instead, rather than a "$0.00" that would suggest the run was free:

```
29 AI calls (5,102,400 tokens, 1 h 04 min)
```

In interactive mode, the same line also appears under the status line of the menu, where
it totals the commands of the session. The line that closes `kotogen ask` covers the
whole conversation.

The amount is rounded to the cent; below half a cent the line says `< $0.01` rather than
`$0.00`. Only the price column of the [model catalogue](interactive.md#the-lists-of-models)
keeps more decimals: rounded to the cent, the cheaper models would all show the same
price.

## Display currency

The bill is in dollars, but the costs can be shown in another currency. Choose it with
the `c` setting of the interactive menu, or in the [settings](#where-the-settings-live):

```dotenv
KOTOGEN_CURRENCY=EUR
```

Any currency the ECB quotes works (`EUR`, `JPY`, `GBP`, `CHF`, `SEK`...). Its symbol is
shown when it is known, otherwise its code (`12.30 SEK`). The setting applies to the
end-of-command summary **and** to the price column of the model catalogue.

The rate is shown once, when you choose the currency:

```
The amounts will show in EUR €. ($1 = €0.8626)
```

It is the day's ECB reference rate, served by [frankfurter.app](https://frankfurter.app),
a public service that needs no key and spends no AI tokens. It is cached for a day
(`exchange-rates.json` in the cache folder). **In dollars, the default, no request is
made**: the amount shown is the amount billed.

The conversion never makes a command fail. Offline, the last known rate is used, then a
built-in rate (for `EUR`, `JPY`, `GBP`, `CHF` and `CAD`). A currency with no known rate (a
code that does not exist) leaves the amounts in dollars rather than putting a `€` on an
unconverted figure, and the `c` setting says so.

To use a fixed rate instead of the day's rate (an expense report keeps to one rate), give
it per dollar:

```dotenv
KOTOGEN_CURRENCY_RATE=0.86
```

The conversion only changes the display: the costs are counted in dollars.

## Caching of the system prompt

The instructions sent to the model run to several thousand characters and go out
unchanged with every batch: a PDF of 200 words sends them twenty times. The program
therefore asks the provider to cache them, and the re-reads are billed at a fraction of
the price. Measured on the vocabulary prompt (1,941 tokens), with a model of Anthropic's
through OpenRouter:

| Call | Tokens sent | Of which cached | Cost |
|---|---|---|---|
| 1st (cache write) | 1,941 | 0 | $0.00899 |
| following (re-read) | 1,940 | 1,918 | **$0.00229** |

There is nothing to set. Caching is asked for only:

- from the models that need the request: `anthropic/*` and `google/*` on OpenRouter, and
  `claude-*` with the native `anthropic` provider (OpenAI caches by itself);
- for system prompts of at least 3,000 characters, since Anthropic caches nothing under
  1,024 tokens.

**If the model refuses the request, the call is replayed without caching and the command
goes on**, with caching off for the rest of the command.

## When the AI falters

The cards are written to the file batch by batch, so those already generated stay there
if the AI fails along the way. With OpenRouter, a call that fails on the network, on a
rate limit (HTTP 429) or on a server error is tried three times, 5 then 15 seconds apart.
If it still fails, the batch in progress is dropped and generation goes on. A refused key,
exhausted credit or a model the key has no right to stops everything at once, with a line
that says what to correct (the service's own answer is added with `KOTOGEN_DEBUG=1`).

An answer **cut off** at the token limit (a batch too big, a high `--batch-size`) is
recognised as such instead of coming out as invalid JSON. For `vocab` and `kanji`, the
batch is then asked for again in two halves, and so on until each part fits. The same
batch is never replayed unchanged: it would be cut at the same place, and paid for again.

A listening passage cannot be split that way: its **card cap** is halved instead, and the
passage is sent once more. There is a single retry, shown at the end of its line:

```
   Generating the cards (passage 1/4, 00:53 → 04:56)… - retried shorter (3 cards)
```

If it is cut off again, the passage is given up (`(given up)`) and the following ones go
on: a third call would be paying to guess.

## Cards to proofread

The model sometimes returns a card that is **worth keeping but faulty**: a translation
that does not have the line count of the text (it is then dropped whole, since a
translation shifted by one line would read as if it were right), a missing transcript, or
the right answer repeated among the decoys. The question is sound and the card is paid
for, but it goes out with an empty field or a duplicated choice.

The output tells these cards apart from the cards set aside on purpose:

| mark | what it says | the card |
|---|---|---|
| `!` | the work got done: surplus decoys trimmed, entry already known | good, or already gone |
| `!!` | something is broken | kept, with its defect |

**A card kept under a `!!` is a card to proofread.** The `KOTOGEN_PROOFREAD` setting (the
`p` key of the interactive settings, labelled "Doubtful cards", or `--proofread` on the
command line) says what is done with them:

| value | what happens |
|---|---|
| `ask` (default) | a question, once, just before sending - and only if there are cards to settle |
| `keep` | they go out as they are |
| `tag` | they go out, marked `Check::...` |
| `drop` | they leave the file **and** the deck |

```
   Generating the cards (text 5/5, 東京駅で 会った 人, passage 2/2)…
   !! translation not lined up (9 lines vs 11) - Translation field left empty.
   Generating the cards (text 5/5, 東京駅で 会った 人, passage 2/2)… (5 cards)

   5 cards to proofread (translation not lined up)
     d. drop them
     k. keep them
›    t. tag them

18 cards in "Japanese::Reading"
   5 cards to proofread, tagged "Check::Translation" (translation not lined up)
```

If you answer `k`, the last line says `kept without a tag`: it is then the only place
where those cards are named.

**Tagging is a choice of its own**, not something `keep` does by default. The tag records
a **generation** accident (an empty field, a duplicated decoy), and a tag nobody asked for
would stay in Anki's tag tree for months. The [dictionary](vocabulary.md) tags without
asking because its tags are about the **content** of the card: a doubtful reading is a fact
about the word, still true long after the generation. Both use the same family of tags:
`Check::Translation`, `Check::Transcript`, `Check::Choices`, `Check::Reading`,
`Check::Word`.

A tag is used rather than a list of note IDs: cards that go through the TSV have no ID,
nor does a duplicate Anki refuses; `tag:Check::*` is one search where thirty numbers
would have to be copied; and the tag comes off in one move (Notes > Remove Tags) once the
card is proofread.

The tag is set **at sorting time** only, after the question: the file is written as the
run goes, and a run interrupted before the question must not leave tagged cards nobody
asked for. The lines of those cards are then rewritten in the file, and the lines of
dropped cards removed, since the file is what gets imported. Only those lines change:
`--output` can name a file that also holds the cards of an earlier run.

Outside a terminal (redirected output, a script), and under [`--yes`](#asking-nothing),
the question answers itself by **tagging**: the cards are paid for, and since nobody read
the `!!` lines, the tag is the only trace left.

## Asking nothing

`--yes` (`-y`) runs a generation command to the end without stopping on a question. Each
question takes the answer it takes outside a terminal (a script, a redirected input, a
scheduled task), and is still shown, with its answer written after it as if typed:

```
   !! 語[ご] - language: lone kanji, not a vocabulary word (suffix, e.g. 日本語)
   [r] remove (do not create the card)  [c] create anyway r
      → card turned down
```

| question | under `--yes` | to have the other answer |
|---|---|---|
| [Cards to proofread](#cards-to-proofread) | tagged `Check::...` | `--proofread keep` or `drop` |
| [Keeping the picture](listening.md#keeping-the-picture---video) of a video (`audio`) | the sound track alone | `--video` |
| [A lone kanji](vocabulary.md#lone-kanji) that is not a word (`vocab`) | turned down | none |
| [The words of an expression](vocabulary.md#an-expression-also-yields-its-words) (`vocab`) | generated | `--no-decompose` |

These are the cautious answers: nothing paid for disappears without a trace, and nothing
is downloaded or encoded that was not asked for. An option that settles a question in
advance still wins over `--yes`, and so does a setting other than `ask` (`KOTOGEN_VIDEO`,
`KOTOGEN_PROOFREAD`): there is no question left to answer.

The `--yes` of [`maintain`](maintenance.md), [`ask`](ask.md),
[`deck install`](card-templates.md) and [`backup --restore`](backup.md) is a different
option: it accepts what those commands would otherwise ask you to confirm, and a deletion
is still asked for.

## When a command stops

A command typed in the shell can stop before its end in three ways:

- **Ctrl+C** prints `Command interrupted.` and leaves with the exit code 130, the one a
  shell expects of a program stopped that way. [`maintain`](maintenance.md) and
  [`ask`](ask.md) print `Interrupted by the user.` and their summary first, so you see
  what reached the deck. At the prompt of `ask`, Ctrl+C only ends the conversation, with
  the exit code 0.
- **A question that waits for typed text, with nobody to type it** (the input piped from a
  file that ran out, or closed), stops the command with `The input ended before a question
  was answered: run the command in a terminal, or with --yes where it takes one.` A yes/no
  or letter question does not stop it: it takes its cautious answer, the one it takes
  [outside a terminal](#asking-nothing).
- **An unexpected error** (the network, an answer nobody foresaw) prints its first line,
  `Stopped by an unexpected error: message (Kind)`, then `To see where it happened, run the
  command again with KOTOGEN_DEBUG=1.`, and leaves with the exit code 1. With
  `KOTOGEN_DEBUG=1` in the [settings](#where-the-settings-live), the full traceback is
  printed above the first line, and the second is left out. `maintain` prints its summary
  first. `ask` prints its report, then `Interrupted:` and the reason; with
  `KOTOGEN_DEBUG=1`, its report, then the traceback and the first line.

In the assistant, none of these ends the session: the menu comes back (see [Moving around
the menus](interactive.md#moving-around-the-menus)).

## Output folder of the TSV files

The TSV files (and the media files written beside them) go to the first of these that
applies: `--output FILE`, then the **cache** when the cards go straight into Anki, then
the `KOTOGEN_OUTPUT_DIR` setting (set in the [settings](#where-the-settings-live) or with
the `o` setting of the interactive menu), otherwise the **current folder**.

The cache (`%LOCALAPPDATA%\kotogen\runs\` on Windows, `~/.cache/kotogen/runs/` on Linux
and macOS) comes before the setting because `o` chooses where the files **to import**
land. When Anki takes the cards itself, there is nothing to import: the TSV is only a
backup in case of a crash during generation, and the media are already in Anki's media
folder. To keep the files somewhere else anyway, use `--output`.

The cache keeps the files of the three previous runs, TSV and media together; older ones
are deleted when a new run that sends to Anki starts. A video run can leave hundreds of
megabytes there.

The Desktop, Downloads and Documents folders offered by `o` are asked from the system
rather than guessed under `~`: Windows often redirects them to OneDrive, and on Linux
their names follow the session language, as declared by XDG (`~/Bureau`, `~/Escritorio`).

## JSON Lines output

The TSV is the file Anki imports. To use the cards elsewhere (a script, a database,
another program), `--format json` writes them as **JSON Lines** instead: one JSON object
per line, in a `.jsonl` file named and placed like the TSV would have been, with the
media beside it. `KOTOGEN_FORMAT=json` in the [settings](#where-the-settings-live) makes it
the default; `--format tsv` goes back to the TSV for one run.

```jsonl
{"format": "kotogen", "version": 2, "deck": "Japanese::Vocabulary", "notetype": "Vocabulary", "fields": ["Expression", "Translation", "Context", "Notes", "Example", "ExampleTranslation", "Audio"], "lang": "en", "kotogen": "1.0.0", "model": "publisher/model", "generated_at": "2026-10-12T14:03:22+02:00"}
{"id": "vocab:涼しい:すずしい", "kind": "vocab", "fields": {"Expression": "涼[すず]しい", "Translation": "cool (temperature)", "Context": "", "Notes": "", "Example": "...", "ExampleTranslation": "...", "Audio": ""}, "tags": ["Level::N5"], "media": []}
```

- **The first line** says what the file is and where its cards were meant to go, like the
  `#deck` and `#notetype` lines of the TSV. It then gives what the cards hold (the
  `fields` of the note type, in order, and the [language of the cards](#the-cards) in
  `lang`) and what wrote them: the `kotogen` release, the `model`, and the time
  (`generated_at`, ISO 8601, with the offset of the local clock). Only the run that
  creates the file writes this line: a run that adds cards later leaves it as it is.
- **`version`** changes when a reader of one layout would misread the other: a key renamed
  or moved, or a new key a reader may rely on. A field added to a note type is neither,
  and only adds a key to `fields`. kotogen writes version 2 and reads every version it has
  written. A reader should skip a key it does not know and refuse a version it does not
  know. kotogen does both, and adds no card to a
  file of a version it does not know.
- **Every other line** is a card: its `id`, its `kind` (`vocab`, `grammar`, `kanji`,
  `audio` or `reading`: the command that made it), its fields in the order of the note
  type and under its field names (see [Decks and note types](#decks-and-note-types)), its
  tags, then its `media`.
- **`id` names the card**: the same matter generated twice gets the same `id`, so a tool
  that already holds a card can tell it from a new one without asking Anki. Treat it as
  opaque: compare it whole, do not take it apart. It is derived from the fields of the
  line, so it can be derived again from a note read out of Anki:

  | Kind | Drawn from |
  |---|---|
  | `vocab` | the expression as written and as read (`vocab:食べる:たべる`); the written form alone when its kanji have no reading |
  | `grammar` | the rule named in the `Rule` field, then a fingerprint of the sentence taken without its cloze markup, readings or spaces |
  | `kanji` | the character, which is the whole of its note (`kanji:学`) |
  | `audio`, `reading` | the fingerprint of the matter and the rank of the question, read off the `ID` field; the name of the source is left out, since renaming a file changes it and not the matter |

  It identifies what was **generated**: a note edited in Anki afterwards (a reading
  corrected, a sentence reworded) may no longer give the same `id`. The vocabulary and
  grammar note types get no `ID` field for it: it would not be the first field, the one
  Anki checks for duplicates, and the notes already in a collection would hold it empty.
- **The values are those of the TSV**, column for column: furigana in the `漢字[かな]`
  notation, line breaks as `<br>`, and a media file as the HTML tag that plays or shows it
  (`<audio controls src="...">`, `<img src="...">`), the file sitting beside the `.jsonl`.
- **`media` lists the files the card plays or shows**, each once, in the order its fields
  name them: the names Anki's media library would keep them under, and an empty list for a
  card that has none.

The file is written **as the run goes**, like the TSV: a run interrupted halfway leaves
the cards it had already paid for, and every line written is complete. That is why the
format is JSON Lines and not one JSON document, which could only be closed at the end.
Cards the run then drops or tags for [proofreading](#cards-to-proofread) are removed or
retagged in it the same way.

A JSON Lines file is not for Anki, so nothing is sent: `--send` is refused with
`--format json`, `KOTOGEN_AUTO_SEND` does not apply, and the interactive menu does not
ask. A name given with `--output` sets the format by itself: `cards.jsonl` is JSON Lines,
any other name a TSV, and a `--format` that disagrees is refused rather than guessed at,
since cards appended to an existing file have to match what is already in it.

A JSON run does not compare with your deck either. To avoid paying twice, kotogen skips
what the deck holds (a word, a rule) and what this machine's history has handled (an
article, an episode), and a set made for another tool has seen neither. The file named by
`--output` stands for both instead:

- **its cards stand for the deck**: a word or a rule already in the file is not generated
  again, and `vocab jlpt` or `grammar jlpt` list what the file lacks, whether Anki is open
  or not;
- **`<name>.seen.json`, beside it, stands for the history** (`cards.seen.json` for
  `cards.jsonl`): the latest articles, episodes or passages are the ones this file has not
  had yet.

Delete both and the set starts over. A JSON run with no `--output` remembers nothing,
since every run writes a new file: the same "latest" items come back every time. Nothing
a JSON run makes is written into the history of your deck.

## Decks and note types

Each command has a default deck and note type (`Japanese::Kanji`/`Kanji`,
`Japanese::Vocabulary`/`Vocabulary`, `Japanese::Grammar`/`Grammar`,
`Japanese::Listening`/`Listening`, `Japanese::Reading`/`Reading`), which the
[settings](#where-the-settings-live) can override. They are a **schema**, not a language,
like the fields (see [Card templates](card-templates.md)): a French deck holds French text
under these same names.

```dotenv
KOTOGEN_KANJI_DECK=Japanese::Kanji
KOTOGEN_KANJI_NOTETYPE=Kanji
KOTOGEN_VOCAB_DECK=Japanese::Vocabulary
KOTOGEN_VOCAB_NOTETYPE=Vocabulary
KOTOGEN_GRAMMAR_DECK=Japanese::Grammar
KOTOGEN_GRAMMAR_NOTETYPE=Grammar
KOTOGEN_AUDIO_DECK=Japanese::Listening
KOTOGEN_AUDIO_NOTETYPE=Listening
KOTOGEN_READING_DECK=Japanese::Reading
KOTOGEN_READING_NOTETYPE=Reading
```

The [backup](backup.md) covers the notes of these five note types, and nothing else in the
collection.

**A fresh install creates these names whatever language the cards are written in.** Half a
schema translated (French deck names over `Translation` and `Decoy1`) reads worse than
none, and there is no second set of defaults to pick from. To use your own names, write
them here (or under Templates > Decks and types in the menu) **before the first
`kotogen deck install`**. A deck can be renamed later at no cost, but renaming a note type
renames nothing in Anki: kotogen then aims at another note type, and your notes stay in
the old one.

## Connection to Anki

The AnkiConnect add-on listens on `http://127.0.0.1:8765` by default, and there is
nothing to set as long as it does. Its configuration (in Anki: **Tools > Add-ons >
AnkiConnect > Config**) can change that, through `webBindAddress`, `webBindPort` and
`apiKey`, typically when port 8765 is already taken. Two settings follow it:

```dotenv
# Where the add-on listens, if its configuration moved it (the scheme is optional)
KOTOGEN_ANKICONNECT_URL=http://127.0.0.1:8766

# The key, if the `apiKey` setting of the add-on requires one
KOTOGEN_ANKICONNECT_KEY=...
```

**`localhost` costs two seconds per request on Windows**, where it first resolves to
`::1`: AnkiConnect does not listen on the IPv6 loopback, and the refusal takes that long
before the fallback to IPv4. Write the address in digits (`127.0.0.1`), as the default
does.

**An address on another machine does not carry the media.** The media files are handed to
Anki by their **local path** (`storeMediaFile`), which Anki reads from its own disk: a
remote Anki would get the cards but not their media. These settings are for reaching the
Anki of this machine, not another one.

With the key missing or wrong, the add-on **answers but refuses every request**. The
program tells this apart from a closed Anki: the settings screen shows `key refused`
against the connection, and the main menu shows a warning naming
`KOTOGEN_ANKICONNECT_KEY`, instead of a "not connected" that would send you to reopen an
Anki already open.

## Backing up the deck

`maintain` and `ask` take a snapshot before they change the deck: the fields, the tags,
the scheduling of every card and the templates of the note types. `deck install` takes
one once you have accepted a change to an existing note type (a face rewritten, a card
added), before writing it. What it does without asking (a note type created, a field
added, a face only kotogen changed) holds nothing of yours, and takes none. The commands
that only add cards take none either. The details are in [Backup](backup.md); two
settings apply:

```dotenv
# Never back up automatically (`kotogen backup` by hand still obeys, and a restore
# still backs up what it overwrites)
KOTOGEN_BACKUP=0

# File the backups somewhere other than the data folder of the platform
KOTOGEN_BACKUP_DIR=C:\Users\me\backups\kotogen
```

---

[Documentation index](../README.md#documentation)
