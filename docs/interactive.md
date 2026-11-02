# Interactive mode

Run `kotogen` **without an argument** to start the assistant: numbered menus, where Enter
accepts the value offered in square brackets, so there are no options to learn. To learn the
command line as you go, turn on the **`v`** setting: it prints the equivalent command at the
end of each run, just above the cost. It is off by default.

Each step is drawn on a cleared screen rather than below the previous output.

## Getting started

On a first launch nothing is set up yet, and the menu would only show it by dimming six of
its eight entries. So if the first launch finds **the AI key, the model, Anki or a note type
missing**, it opens a guide instead, one short page per step, in the order the steps are needed:

```
  Language    API key    Model    Anki    Modules
  ━━━━━━━━━━━━───────────────────────────────────
                 ▲

API key

OPENROUTER_API_KEY: missing
To get one: https://openrouter.ai/keys

    1. Enter the key
    2. Skip this step

    m. Go to the menu
```

The bar fills in as steps are done, and a step that is done has its name dimmed. Steps can be
taken in any order or skipped. The guide opens on the first step still to do, and moves to the
next page once a step is done, so pressing Enter takes you through. **Escape** goes back one
page, **`m`** leaves for the menu at any point, and Ctrl+C quits, as at the main menu.

- **Language** opens the list of the [`l` setting](#the-settings) (the screens), then that of
  `g` (the cards). The second list opens on the language you just picked, as a suggestion.
  The step counts as done once a language is saved, English included.
- **API key** is the `k` setting, with the address of the provider's page that issues keys.
- **Model** is the `m` setting: kotogen comes with no model chosen, so the page sends you to
  the providers and the models each one serves today (see [the `m` entry](#the-settings)).
- **Anki**, while Anki does not answer, says what to set up: the AnkiConnect add-on
  (**Tools > Add-ons > Get Add-ons...**, code `2055492159`), then a restart of Anki, with an
  entry to ask Anki again. If Anki answers but refuses the key, the page says so instead. On a
  profile that lacks note types, the page names them and creates **all of them in one
  install**; the menu asks about them one type at a time.
- **Optional modules** lists the missing modules with their download size, and installs them
  on request. FFmpeg installs by hand: the page gives the command for your system. On the
  launch where the guide opens, the usual [first-run](global-options.md#optional-modules)
  question about modules is not asked before it: the modules come as the guide's last page.

The guide opens **on the first launch or never**. That launch writes
`KOTOGEN_GETTING_STARTED=0` to the [settings](global-options.md#where-the-settings-live),
whether the guide opened or not, and every later launch goes straight to the menu, whose
status line shows what is still missing. Anki is closed at most launches, so a guide that
opened whenever Anki was missing would open almost every day. If the key, the model, Anki and
its note types are already in place at the first launch, you never see the guide, and neither
does a command typed in full or a script. To see it again, delete that line from the settings:
the next launch counts as a first one.

## Moving around the menus

The main menu shows **the commands** under two subheadings, then **`s`** for the settings,
**`u`** for the update and **`q`** to quit. The settings have a screen of their own.

Every command works the same way: **a menu of sources**, then the questions that follow from
the source chosen. **Escape** goes back one step (to the command's menu, then to the main
menu), in the menus and in the questions marked `(b = back)`. In a question, Escape first
clears what you typed, as a Windows console does, and a second Escape goes back, so one stray
key does not lose a URL you have just pasted. Typing `b` also goes back, and it is the only
way back where keys cannot be read one by one. Questions with no way back read the line as the
terminal gives it.

Ctrl+C in a command's dialogue cancels the dialogue and returns to the menu, and Ctrl+C while
a command runs stops it and returns to the menu. At the main menu and in the settings, Ctrl+C
quits, as `q` does.

The source menus of **listening** and **reading** have **five and six lines**, with the
catalogues one level down. The first screen asks **what kind of material** you have, not
which source:

```
Reading cards - where does the text come from?
  1. An article                 NHK Easy and the Japanese press, from N5 to N1
  2. A book                     Tadoku albums, public domain, textbook
  3. Official JLPT past papers  the 読解 texts, by level
  4. A URL                      any Japanese page, or a PDF online
  5. A local file               text, PDF or pictures - manga and albums
  6. A tailored text            the words and grammar you are learning, at your level
```

**An article** shows NHK Easy and the press sites on one screen, ordered by level, from NHK's
easy Japanese to Japanese written for native readers. **A book** groups the Tadoku albums,
青空文庫 and the いろどり textbook; on the listening side, it groups the textbook and 青空朗読,
and **A programme** groups the podcasts and the YouTube channels. On the reading side, the
past papers, a URL and a local file stay on the first screen; on the listening side, NHK Easy,
the past papers and a local file do, and the address of a feed or a video is pasted under **A
programme**. **A tailored text** needs no material from you: it asks for a shape, a level and
a length, and Enter on each gives a short story at the level of the deck. Each of the three
screens remembers its last choice for the session. When you pick a level, the length screen
shows the sizes for that level, and offers no 長文 below N3, where the exam sets none (see
[Reading](reading.md)).

Escape in a second screen **goes back to the first**, not to the main menu.

A menu you come back to **opens on the line you left**. When a command finishes, you return to
**that command's menu**, on the line you chose there, rather than to the main menu. When you
leave that menu (Escape, or `b`), the main menu opens on **the command you are leaving**.

On a terminal that supports it, the menus **also work with the arrow keys**: `↑` `↓` move,
Enter confirms, Escape goes back. Going back is then a key, recalled at the foot of the menu,
rather than a line of the list. **Keys only move the highlight, and Enter opens the
highlighted line.** Typing a **number** highlights that line (`14` goes to the fourteenth),
and Enter opens it, so a mistyped digit opens nothing. Two digits typed in quick succession
make one number; with half a second between them, they are two separate moves. Letters work
the same way: `q` or `s` highlights its line, and Enter opens it.

On a console without ANSI sequences, the menus take numbered input only, with a `b. Back`
line, since Escape cannot be read there. A menu taller than the window also falls back to
numbered input. `KOTOGEN_NO_RAW_KEYS=1` forces numbered input in every menu; the example
below shows that form.

Without a terminal at all (a script, a scheduled task), `kotogen` alone does not open the
assistant: it says that the assistant needs a terminal, and exits. Type the command in full
there, as the other pages show it.

A few lists let you **tick** several lines: the books of a Tadoku level, the articles of a
press feed, the rules of a JLPT level, the authors and works of 青空文庫, and the readings of
青空朗読. Several short books or articles then go in one run. **Space** ticks the highlighted
line and leaves the highlight on it; **Enter** confirms everything ticked. With nothing
ticked, Enter takes the highlighted line, as in any menu. Ticks survive turning the page. In
numbered input, `1 3 5` ticks three lines, and `1 3 n` ticks two and turns the page. A new
page **replaces** the previous one on the screen, and pages turn both ways (`n` for the next
ones, `p` for the previous ones; PgDn and PgUp in the searchable lists below).

```
$ kotogen

 █▄▀ █▀█ ▀█▀ █▀█ █▀▀ █▀▀ █▄ █
 █ █ █▄█  █  █▄█ █▄█ ██▄ █ ▀█

AI [publisher/model via openrouter]   Anki [User 1]

  Make cards
    1. Kanji        the kanji of your words, a JLPT level or a text
    2. Vocabulary   words, a web page, a text file or a PDF
    3. Grammar      one rule, a JLPT level or a grammar page
    4. Listening    multiple-choice comprehension on an audio
    5. Reading      comprehension questions on a text

  Look after a deck
    6. Corrections  marked cards: flags, leeches
    7. Templates    see your cards, set them, install them
    8. Backup       snapshot of the deck, comparison, restore

    s. Settings
    u. Update
    q. Quit

> 3

Grammar cards - where does the rule come from?
  1. One precise rule  typed as it comes: のに, younitanomu...
  2. A JLPT level      the rules of the level the deck lacks
  3. A grammar page    the address of a page that explains ONE rule
  4. A file of rules   one per line, like a list of words
  b. Back

> [1] 1
Rule to work on (b = back): のに
Number of cards [5] (b = back):
Send the cards into Anki as well (AnkiConnect) (y/n) [n]:

のに
   Analysing the rule… (Grammar::N4::のに（逆接）)
   Generating the cards (5 with a hole)… (5 cards)

5 cards in "Japanese::Grammar"
1 AI call (< $0.01, 24 s)
```

### Searchable lists

Long lists are searched rather than scrolled. In the rules of a JLPT level, the Tadoku books,
the authors and works of 青空文庫 and the readings of 青空朗読, **what you type filters the
list**:

```
N3 - 2/200 done - 5 of 200, including 3 outside this list
› 1. [ ]   N3  ます形＋にくい          difficult to do, not easy to
  2. [ ]   N3  なかなか〜ない（困難）  not readily, hard to, doesn't easily (difficulty)
  3. [ ]   N2  ます形＋がたい          hard to do, difficult to (formal expression)
  4. [ ]   N2  かねる                  unable to do, difficult to do (polite refusal)
  5. [ ]   N1  に難くない              not difficult to, easy to surmise

  Search: diffi_, Space to tick, Escape to go back
```

Three spellings find the same rule: the **Japanese** as written (`にく`), its
**romanisation** (`niku`) if you have no Japanese keyboard, and the **meaning** in the
right-hand column (`difficult`), in the language of the screen. Case and accents are ignored.

| Key | Effect |
|---|---|
| a letter, a kana | narrows the list |
| Backspace | erases the last character |
| Escape | clears the search; a second time, goes back |
| ↑ ↓ | move through what is left |
| Space | ticks the highlighted line (ticks are kept when the search changes) |
| PgUp / PgDn | turn the pages |
| a digit | highlights its line, as in every menu |

Digits still move the highlight, since a search is typed in letters. `b` does not go back in
these screens: it is a letter like any other, and only Escape goes back (the foot of the list
says so).

The rules of one JLPT level **also search the other levels**: matches from other levels come
after those of the level, and the title counts them ("including 3 outside this list"). A
search that finds nothing leaves the list as it was rather than emptying it, except on the
grammar rules screen, which then offers to work on what you typed (see
[Grammar](grammar.md#in-the-assistant-the-whole-level-can-be-searched)).

Without key-by-key input (a console without ANSI sequences, `KOTOGEN_NO_RAW_KEYS=1`), these
lists keep their numbered input and their `n` and `p` paging. Shorter menus, such as the list
of podcasts, do not search: arrows and numbers are enough there, and a filter would hide the
entry that takes the URL of a feed.

## The status line

AnkiConnect is probed **once at start-up**, and again just before each send, so an Anki
opened during a generation is still found. A probe can take several seconds (Anki busy, a
firewall), so every other redraw of the menu (going back, changing a setting, returning after
a command) reuses the known state; the **`a`** setting probes again on demand. When a probe
keeps you waiting, a spinner shows until Anki answers, then disappears.

The status line heads the main menu, and only the main menu. It states two facts, the model
that will be called and the open Anki profile, with no marker added: when one side cannot
work, its bracket says so in place of the name. The warnings follow just below it. Once a
command has called the model, a second line gives the running cost of the session.

With Anki open, the bracket names the profile, which is where the cards go. **With Anki
closed, it reads `Anki [not connected]`.** The bracket has only these two states: an
AnkiConnect that refuses its key (`apiKey` setting) also reads `not connected`, and a warning
below names the add-on and the setting, so you are not told to open an Anki that is already
open. The `a` setting tells the three cases apart.

The bracket **does not show the folder** where TSV files land. The folder is named where it
matters: at the end of a generation, in the same sentence as the file name (see
[What the end of a command says](#what-the-end-of-a-command-says)), and in the settings,
under `o`.

**Without an API key, the left bracket reads `AI [key to be set]`** and names neither
provider nor model, since neither will be called. The name of the key's variable appears
where you can act on it: in the settings, next to `API key`; on the screen of a dimmed
command; and in a command typed on the command line, which asks for the key when it needs it
and saves it (outside a terminal, it stops instead, naming the variable to set). **With a key
but no model chosen, it reads `AI [model to be chosen]`**: none is built in, and a command
typed on the command line that calls the AI (`vocab`, `grammar`, `kanji`, `audio`, `reading`,
`maintain`, `ask`, `rework`; `maintain --scan` calls none) stops before doing any work and
says how to choose one. On the first run in an environment, the question about the
[optional modules](global-options.md#optional-modules) still comes first.

A missing deck is created when the cards are sent, but a **missing note type makes the send
fail**. It does not change the bracket, since the profile and the connection are fine.
Instead, the menu entry concerned carries a `(!)`, and a one-line warning under the status
line gives the problem and where to fix it:

```
AI [key to be set]   Anki [User 1]
!! Grammar: note type "Grammar" missing  -> the "Templates" menu

  Make cards
    1. Kanji        the kanji of your words, a JLPT level or a text
    2. Vocabulary   words, a web page, a text file or a PDF
    3. Grammar      one rule, a JLPT level or a grammar page  (!)
```

When a probe first finds a note type missing, the menu asks once per session what to do about
it: install it now, hide the command, or decide later. A hidden command leaves the menu (it is
added to `KOTOGEN_SKIP`), and the status line lists it under `Hidden commands`.

### What is greyed out, and what you read when pressing it

An entry can lack what the status line reports: **the connection to Anki**, **the AI key**
and **the model**. The entry is then dimmed, but it stays in the menu and **keeps its
number**, so the numbers do not move with the state of Anki. Nothing is written next to it:
the status line already says what is missing. **Corrections > Ask** can lack one thing more,
a provider whose tool calls the program drives: it stays dimmed until the model screen picks
an OpenRouter model (see [Asking](ask.md#two-limits)).

**Choosing a dimmed entry says what to do**: what is missing on the left, how to fix it on the
right. Then the menu comes back.

**Choosing it also asks Anki again.** The state shown dates from start-up, and you may have
just opened Anki: the entry probes once more, and if Anki now answers and nothing else is
missing, the command opens. Only if Anki still does not answer is the screen below shown,
asking whether Anki is open with the AnkiConnect add-on installed. If Anki answers but
refuses the key, the screen names the `KOTOGEN_ANKICONNECT_KEY` setting instead.

```
  Make cards
    1. Kanji        the kanji of your words, a JLPT level or a text
    2. Vocabulary   words, a web page, a text file or a PDF
    3. Grammar      one rule, a JLPT level or a grammar page
    4. Listening    multiple-choice comprehension on an audio
    5. Reading      comprehension questions on a text

  Look after a deck
    6. Corrections  marked cards: flags, leeches
    7. Templates    see your cards, set them, install them
    8. Backup       snapshot of the deck, comparison, restore

> 6

Corrections needs Anki.
Anki does not answer  -> is Anki open, with the AnkiConnect add-on installed?
```

**What each command needs.** The five card-making commands call the model, so without a key
or a model they are dimmed; otherwise the command would ask for the key, or stop for the
model, but only after the whole dialogue. With Anki closed they stay available: they write a
TSV to import later. **Corrections** needs Anki, since it reads the deck; without a key or a
model it still opens, since **Look** and **Marks** call no model, and inside it **Handle** and
**Ask** are dimmed until they have what they lack (Ask also wants a provider that drives
tools), each named with its way out. **Templates**
and **Backup** open without either and dim entries inside: with Anki closed, the three
Templates entries that set things rather than act on Anki (`Preview`, `Appearance`, `Decks
and types`) and the list of backups still work.

Dimming is drawn only on a real terminal; elsewhere (redirected output, tests), the line looks
like the others, and choosing it still says what is missing.

The question at the end of a dialogue follows the same rule: **with Anki closed, "Send the
cards into Anki as well" is not asked**, and the end of the generation says where the file
was written. Auto-send (the `s` setting) tries anyway, since Anki may have been opened during
the generation.

## The screen while working

Everything the program prints while it works takes **three forms**, for every source: a
podcast feed, a Tadoku book, an NHK Easy article or a folder of MP3 files.

```
Max number of questions per audio [auto] (b = back):
Send the cards into Anki as well (AnkiConnect) (y/n) [n]: y

NHK ラジオニュース
   Reading the feed… (3 episodes, 12 already handled)
   ニュース 8月30日 (12 min)
   ニュース 8月29日 (11 min)
   ニュース 8月28日 (12 min)

Downloading the episodes… (3 files, 34.2 MB)

[1/3] ニュース 8月30日
   Transcribing… (86 lines)
   Splitting… (6 passages, 2 dropped: 2 too short)
   Generating the cards (passage 1/6, 00:12 → 01:30)… (3 cards)
   ! passage 4/6: 4 min 10 s, beyond 3 min

[2/3] ニュース 8月29日
   Transcribing…
   !! transcription impossible: ffmpeg not found on the PATH

14 cards in "Japanese::Listening", 14 audios in the media library
9 AI calls (€0.42, 3 min 08 s)

Enter to come back to the menu...
```

**The source**, in the margin, names where the material comes from: a programme, a channel, a
site, or `Audio files` for files taken from the disk. What it carries is listed under it,
indented, eight lines at most; beyond that, `... and N more` counts the rest.

**An action** is written `Label…` and **stays open while it runs**: its result is added in
brackets at the end of the same line, so the screen shows what is in progress, then what it
gave. When an action is one of a series (passage 3 of 6 of a collection, batch 2 of 5 of a
word list), its label says so, before the ellipsis. An action **in the margin** applies to the
whole batch (a grouped download) rather than to one item.

**An action that takes time is animated** at the end of its line, and shows its progress:

```
   Transcribing… ⠹ 03:30 of 09:12
```

The spinner shows that the program is working, so a long wait does not look like a crash.
What follows it is the progress, in the unit that suits the job; a wait with no progress to
report shows the spinner alone. Every wait of the program takes this form:

| The wait | What it shows |
|---|---|
| Whisper transcription | the second of the audio it has reached, out of the total length |
| Whisper model to install | `model to download once only, 420 MB of 1.4 GB` |
| Download (file, episode, YouTube video) | the bytes received, out of the announced size |
| ffmpeg re-encoding or extraction | the position in the media, out of the total when the command sets a length |
| Rendering the pages of a document | `page 3 of 12` |
| Call to the model, browser, reading the repository (`update`) | the spinner alone |

The animation erases itself completely: the result of the action takes its place, and anything
printed while it turns (a `!`, a `!!`) starts on a clean line. Outside a terminal (redirected
output, a CI log), nothing is animated.

**The rank**, `[2/3] name`, opens the block of the item being handled. The name is the one the
source listed it under just above, so you can find it in that list. Its title, length and
duration come later, as results of the actions that read them.

Two markers run through every command. **`!`** marks a deliberate sorting (a passage too
long, a card refused): it is part of the work, but left unsaid it would make the final count
look like a bug. **`!!`** marks an incident, and goes to the error output. Neither closes the
action above it: if the action succeeds after all, its line is **printed again in full** with
its result. The vocabulary has a third, **`??`**: a reading or a spelling that the
[dictionary check](vocabulary.md#readings-checked-against-the-dictionary) doubts, on a card
that goes out tagged.

An incident that stops the command is reported **the same way**: `!!`, indented, under the
block where it happened.

Indentation is the only hierarchy, one level deep: what names something is in the margin, and
what belongs to it is indented. **One blank line separates two blocks, never two blank
lines.**

## What the end of a command says

Everything a generation produced is reported **in one block, once**. Its length depends on
what is left for you to do.

When the cards went into Anki, the block is **one line**, followed only by the command's own
notes if it has any (entries skipped, cards to proofread). Audio files and mini-book pages are
counted in the same line, since they went into the media library with the cards. The cost
line follows:

```
12 cards in "Japanese::Listening", 12 audios in the media library
14 AI calls ($0.02, 1 min 12 s)
```

When the cards are left in a TSV, the block gives the **path of the file**, how to import it,
a preview of the cards, and the media to copy yourself. If a send was asked for (auto-send or
`--send`) and Anki did not answer, the first line says so, in the same sentence as the path;
the file is then the backup kept in the cache (see the `s` entry of
[the settings](#the-settings)):

```
Anki was not connected: the 12 cards are in C:\Users\me\AppData\Local\kotogen\runs\vocab_20260818_101112.tsv
   3 entries skipped
   → Anki import: File > Import > select the file

── Preview ──────────────────────────────────────────────────────
    1. 水[みず] - Water
[...]
─────────────────────────────────────────────────────────────────
```

Media files you have to copy yourself are listed one by one, since each needs a copy by hand.
Mini-book pages are the exception: they are counted per folder, which holds them alone and
which you copy whole.

```
   Images to copy into %APPDATA%\Anki2\<profile>\collection.media:
   - 30 images in C:\Users\me\kotogen\reading_pages_20260818_101112
```

## The update

`u` sits under the settings, apart from the commands, because it concerns the program rather
than the deck. It runs `kotogen update`, which fetches the repository the clone follows and
fast-forwards to it, then upgrades the modules already installed. There is no dialogue:
choosing the entry runs the command. When there was nothing new to take, you return to the
main menu; when new commits were taken, the session ends (see below).

```
C:\Users\me\kotogen
   Reading origin/main… ⠹
```

The working copy is in the margin, which tells two clones apart, and each step is an action
under it. New commits are counted, not listed: the changelog says what changed.

The first fetch runs behind the spinner with the prompts turned off: git's
(`GIT_TERMINAL_PROMPT=0`) and, over SSH, ssh's, with `-o BatchMode=yes` added to the ssh
command you configured (`GIT_SSH_COMMAND`, else `core.sshCommand`) when it is OpenSSH, or
`ssh -o BatchMode=yes` when none is set. If the remote wants something typed (a password, a
passphrase, a host key not known yet), the fetch runs again without the spinner, where git or
ssh asks you. An ssh that takes no such option (plink, TortoisePlink, a wrapper, or one set
through `GIT_SSH`) is left as you configured it, and any failure of the first fetch is tried
again the same way. A changed host key is reported by its warning line, not by its frame of
`@`.

```
C:\Users\me\kotogen
   Reading origin/main… (3 commits)
   Taking them… (now at dabd617)
   Renewing 3 modules… (yt_dlp-2026.9.14)

Launch kotogen again to run the new version.
```

An update that took new commits ends the session on that line: Python keeps the modules it
imported at start-up until it stops, so the running session would still be the old version,
even though the new files are on disk. Launch kotogen again to carry on. If the card
templates changed, the update also says to run `kotogen deck install`, which carries them
into Anki. See [Keeping it up to date](../README.md#keeping-it-up-to-date) for what the
update does and does not touch.

## The settings

The settings are on **one screen**, opened with `s` from the main menu. It stays open after
you change a setting, so you can change several in a row. Escape (or `b`) goes back to the
menu. Each setting shows **its current value** in a column, so you see what you are about to
change before opening it.

```
Settings
    k. API key                 OPENROUTER_API_KEY set
    m. AI model                publisher/model via openrouter
    o. TSV folder              C:\Users\me\kotogen
    c. Display currency        USD $
    h. Source history          46 entries, 3 sources
    l. Interface language      en - English
    g. Language of the cards   en - English

    s. Auto-send to Anki       off
    v. Equivalent command      hidden
    q. Audio compression       none
    i. Video picture           ask
    p. Doubtful cards          ask

    a. Connection to Anki      connected to User 1
    b. Back
```

The three groups are **three kinds** of entries, ordered by what the key does: first the seven
that open a screen (a question or a list, with a way back), then the five that **toggle in
place** (one press changes the value shown and you stay on the screen; `q`, `i` and `p` have
more than two positions and cycle through them), and last the one that **acts** without
setting anything, the AnkiConnect probe.

Each letter is the initial of the **word that names the setting** on the screen or in the
files, such as `k` for the API Key, `o` for the Output folder, `s` for auto-Send, `v` for
Verbose, `q` for the audio Quality and `p` for Proofreading. Two are exceptions: `i` stands
for the **image**, because `KOTOGEN_VIDEO` would have needed `v`, which verbose mode uses; and
`g` is the language the cards are **generated** in, because `l` belongs to the interface
language. `q` does not quit here.

The **`k`** entry asks for the key of the current provider, with the address of the page that
issues them. The key shows as stars while you type, an empty Enter cancels, and the key is
saved in the settings.

The **`m`** entry chooses the **AI model**. kotogen comes with none chosen and recommends
none, since models come and go faster than its releases: the entry lists the three providers,
and each one [lists the models it serves today](#the-lists-of-models). OpenRouter shows its
whole catalogue with today's prices; Anthropic and OpenAI show the models they serve to your
key. Any other model can be typed by hand (`a`), at any of the three providers. The choice
applies at once and is saved in the [settings](global-options.md#where-the-settings-live) as
`KOTOGEN_PROVIDER` and `KOTOGEN_MODEL` together, since a model name only means something at
its provider. Like the other settings, it stays out of the equivalent command of verbose
mode, and `--provider` / `--model` still take precedence for one run. If the provider has no
key yet, the screen asks for it at once.

The **`o`** entry chooses the **TSV folder**, where files to import by hand are written: the
**current folder** (the default: the folder the command was launched from), the Desktop,
Downloads, Documents, or any other folder you type. A folder that does not exist is created at
once, after a confirmation, so a typo shows here rather than at the end of a generation. The
choice applies at once and is saved in the
[settings](global-options.md#where-the-settings-live) (`KOTOGEN_OUTPUT_DIR`). It applies only
to cards left for import by hand, whose media files are written beside the TSV. Cards sent
through AnkiConnect leave only a backup TSV in the cache, and their media go into Anki's media
library.

The **`c`** entry chooses the **display currency**: the dollar (the billing currency), the
euro, the yen, or any other code you type. When the exchange rates can be read, a code without
a rate is refused on the spot, with the list of the codes that have one. The settings screen
shows only the currency (`EUR €`); the rate is shown when you choose it:

```
The amounts will show in EUR €. ($1 = €0.8626)
```

The choice applies at once, is saved in the
[settings](global-options.md#where-the-settings-live) (`KOTOGEN_CURRENCY`), and also applies
to the price column of the model catalogue. Where the rate comes from, what happens offline
and how to pin a rate are explained in [Display currency](global-options.md#display-currency).

The **`l`** entry lists the **languages of the screens**, each with its code and its name in
that language (`fr`, `Français`). The code is what `KOTOGEN_LANG` takes; the name is what a
reader looks for. At the keyboard, typing searches the list by code or by name; Escape (or `b`
in numbered input) leaves it without changing anything. The screen redraws in the language
chosen, and so does the rest of this session and the next ones.

The **`g`** entry, just below, lists the **languages of the cards** the same way and shows its
value the same way (`en - English`, `fr - French`), with the names in the language of the
screen. It is the only entry of this screen that is not an environment variable: as a choice
about the cards, it is saved in `templates.env` with the other card choices. It is set here
and on the language page of the [getting-started guide](#getting-started), which offers it
once the language of the screens is chosen; it changes no template, so the Appearance screen
does not show it. The two language settings are easy to confuse: see [The two
languages](global-options.md#the-two-languages).

The next five entries are **toggles**: they open no screen, and one press changes the value
shown. Each change is saved in the [settings](global-options.md#where-the-settings-live) at
once.

The **`s`** entry toggles **auto-send**: the cards go into Anki without a question, and the
TSV is only a backup kept in the cache (`%LOCALAPPDATA%\kotogen\runs\` on Windows,
`~/.cache/kotogen/runs/` on Linux and macOS) instead of the working folder. If the send fails,
the end of the command gives the path of that file. When on, it is saved as
`KOTOGEN_AUTO_SEND=1`; `--no-send` turns it off for one run.

The **`v`** entry turns on **verbose mode**: every command then ends with the `kotogen ...`
line that would launch it, to copy as it is, to run it again or to adjust it. It is off by
default; when on, it is saved as `KOTOGEN_VERBOSE=1`.

With verbose mode on, the pause after a command also accepts **`c`**, which copies that line
to the clipboard: `Enter to come back to the menu, "c" to copy the command...`. The key is
offered only when the line has just been printed, and nothing is copied unless you press it.
The pause then comes back.

kotogen uses the system's clipboard tool (`clip` on Windows, `pbcopy` on macOS, `wl-copy`,
`xclip` or `xsel` on Linux) and names it in the confirmation: "Command copied (xclip)."
Without any of them (a remote session, a bare server), it sends the **OSC 52** escape sequence
to the terminal itself, the only route through SSH, since the clipboard is on the machine that
displays the terminal. Not every terminal accepts it and nothing comes back, so the message
does not claim success: check before pasting.

The **`q`** entry sets the **compression of the audio** that is downloaded or cut. Each press
moves down one notch (`none`, `light`, `medium`, `strong`) and goes back to the first after
the last. The default is no compression: the site's stream is copied as it is. The choice is
saved as `KOTOGEN_AUDIO_QUALITY`, and `--audio-quality` overrides it for one run. Details are
in [Audio compression](listening.md#audio-compression---audio-quality).

The **`i`** entry decides what is kept of a **video source**: its sound track alone (the card
stays a listening card), or its **picture**, in which case every passage is cut again as a
video and the card plays that clip. It has three positions: `ask` (the default), then
`always` and `never`. Each press moves to the next one.

In `ask` mode, the question comes **with the other questions** of the dialogue: for a YouTube
video, just after the channel or URL is chosen; for a local file, just after its path. It is
asked once per command and only **if a video is involved**: an NHK article, a podcast or a
folder of MP3 files never asks it, and `--latest 3` does not ask it three times.

```
Keep the picture (otherwise the sound track alone) (y/n) [n]:
```

It comes before the maximum duration, because the answer decides what that question is about:
"Max duration of the video" or "of the audio". It also comes before the download, because for
a **YouTube video** the answer decides what is **downloaded**: a few megabytes of sound track,
or a few hundred of video. The choice is saved as `KOTOGEN_VIDEO`, and `--video` /
`--no-video` overrides it for one run, without asking. Details are in
[Keeping the picture](listening.md#keeping-the-picture---video).

The **`p`** entry decides what happens to the [cards to
proofread](global-options.md#cards-to-proofread), the ones the model returned damaged, marked
by a `!!` in the output: `ask` (the default) asks once, just before sending and only if there
are any; `keep` exports them as they are; `tag` exports them with a `Check::...` tag; `drop`
leaves them out of the file and the deck. The choice is saved as `KOTOGEN_PROOFREAD`.

The **`a`** entry probes AnkiConnect again, for example after you have opened Anki; its value
then reads `connected to` and the profile, `key refused` or `not connected`.

The **`h`** entry opens the **source history**: what has already been handled, source by
source, with the number of entries and the commands that recorded them. That file
(`~/.kotogen/seen.json`) is what "the latest episodes" and "the latest articles" are measured
against: without it, every run would make the same cards again and pay for them again. This
screen is where you **forget** a source, or everything.

```
Sources already handled: what makes a relaunch not do the same cards again.
Forgetting a source means doing - and paying for - its cards again at the next pass.

    1. NHK Easy - 46 entries (vocabulary, listening, reading)
    2. Nihongo con Teppei 波! (podcast) - 12 entries (listening)
    3. Onomappu (YouTube) - 3 entries (listening)
    4. Free books (Tadoku) - 2 entries (reading)

    d. Take back from the deck
    f. Forget those no longer in the deck
    a. Forget everything
    b. Back
```

Grammar has its own source there, `rules`: each rule worked on is recorded when its cards are
written, whether they go into Anki or not. A rule you have just worked on therefore counts as
done before its cards reach the deck (a TSV not imported yet, or Anki closed): the screen of a
JLPT level marks it. Forgetting `rules` clears that record; rules whose cards are in the deck
still count as done.

Each source is named as it was chosen, not by its key in the file; a key that no catalogue
knows any more (a feed pasted by hand, a renamed alias) is shown as it is. Forgetting only
removes identifiers: the downloaded files and their transcripts stay in the cache, and what
you pay for again is the AI calls, so the question defaults to "no". To redo **one** episode
without forgetting anything, name it (`--episode 12`, or its URL): what you ask for by hand
ignores the history. The free books never skip anything: their catalogue marks the albums
already handled (`(already handled)` after the title) and still lets you tick them.

### The deck, a second memory

The history file only knows **this** machine. The deck is synchronised: on a second computer,
the history is empty while the cards are already there. Listening and reading cards record
where they come from (the `Source` field), and that is enough to avoid paying again for what
the other machine did.

This works in two places, and the first needs nothing from you:

- **on every run**, the "latest articles", "latest episodes" and "latest videos" modes, the
  catalogue of free books, the JLPT past papers, いろどり, 青空文庫, 青空朗読 and the screen of
  the rules of a JLPT level check the deck as well as the file. With Anki open, content
  already in the deck is skipped as if it were in the history, and the screens that say
  "already handled" or "done" count both; with Anki closed, only the file counts;
- **`d. Take back from the deck`** writes into the file what the deck knows, once and for
  all. This makes the history correct on a new machine, and keeps it valid with Anki closed.

```
   14 entries taken back from the deck: NHK Easy 8, Free books (Tadoku) 4, Onomappu (YouTube) 2
   6 already known, 12 with no identifier in the card, 3 outside the sources followed.
```

Taking back **only adds**: a local history that holds more than the deck (cards deleted
since) keeps it. It has two limits, and the screen states the first:

- a **podcast episode** is not written into the file: its card names it (`feed - title`) but
  does not carry its identifier. It is still recognised on every run, with Anki open. A
  **passage of a long reading** is in the same case: it is identified by a fingerprint of its
  text, which the card does not carry;
- **vocabulary** and **grammar** cards have no `Source` field, so they do not record which
  article they came from, and taking back can do nothing for them. Each has its own check
  instead, on every run: a word already in the deck gets no new card (unless `--force`), and a
  rule already worked on is recognised by its name, read from the card's `Rule` field and its
  `Grammar::` tag. That is what puts a check mark before a rule on the screen of a JLPT
  level.

Taking back also reports, in one line, the sources the deck no longer carries, without acting
on them:

```
   ! 1 source no longer has a card in the deck: Onomappu (YouTube).
```

To forget them all at once, use **`f. Forget those no longer in the deck`**: it reads the deck
again, names the sources it no longer finds, and asks before erasing.

```
   No card left in the deck: Onomappu (YouTube).
Forget this source (2 entries) (y/n) [n]:
```

Forgetting never happens on its own: a card is usually deleted because it was bad, and
remaking it (and paying for it again) would not make it better. A source is only concluded
gone when three conditions hold:

- its mode has a `Source` field (otherwise all vocabulary and grammar would look gone);
- the deck answered for that mode (Anki closed, a wrongly set note type or a sync not yet
  done return an empty index, and everything would look gone);
- a card can name the source (the cursor of a long reading, filed under a fingerprint of its
  address, cannot, so its absence from the deck proves nothing).

## The lists of models

On the `m` screen, **OpenRouter** opens its **full catalogue, with today's prices**, read from
the public endpoint of their API (no key needed, no AI tokens spent). The list is long, so the
screen **filters as you type**: every letter narrows the list to the models whose ID contains
what you typed, `↑` `↓` choose, Enter confirms.

```
OpenRouter catalogue of Aug 03, 2026: 98 models able to read a PDF,
as the commands of the project require.
Filter "mini": 4 models.

    model                                       $/generation  cache    context
    publisher-a/model-mini                          0.0064 $  cache  1,048,576
    publisher-b/model-mini                          0.0160 $           400,000
    publisher-a/model-mini-2                        0.0256 $  cache  1,048,576
    publisher-c/model-mini                          0.0960 $  cache    200,000

  filter: mini▌
```

Since letters feed the filter, none of them is a shortcut here: **Escape** clears the filter,
then goes back, and **F5** refreshes the catalogue. Without key-by-key input, the screen falls
back on a numbered list, where `f` asks for the filter and `u` refreshes the catalogue.

The price shown is that of a **typical generation** (40,000 tokens sent, 6,000 received).
Prices are not rounded to the cent like the costs elsewhere, or they would all look the same.
They follow the [display currency](global-options.md#display-currency): in euros, the column
is headed `€/generation` and the amounts are converted at the day's rate. The `cache` column
shows which models cache the system prompt (see [Cost](global-options.md#cost-of-each-run)).
Only models that can read a PDF are listed, since the commands send PDFs, and free variants
are left out: limited to a few requests per minute, they would fail in the middle of a
generation.

The catalogue is cached for a week in the program's cache (`%LOCALAPPDATA%\kotogen\`,
`~/.cache/kotogen/`); **F5** fetches it again at once. Offline, the stale cache is used and
the screen says so; with no cache either, the screen goes back to the providers.

**Anthropic** and **OpenAI** list the models they serve to your key, newest first, on the same
screen without the price columns. They give that list only to a key, so the screen asks for
the key first if it is missing. The list is read again each time it opens, and a key they
refuse is said as such. OpenAI's list leaves out what the Chat Completions API the program
calls does not serve: the models that do not chat (embeddings, voices, transcription,
images, video, moderation, search, realtime), the older completion models, and the families
served only through the Responses API (`codex`, `deep-research`, `computer-use`, the `-pro`
models...), told apart by the family their name carries.

The other pages document the same commands on the command line, for scripts or for speed:
[kanji](kanji.md), [vocabulary](vocabulary.md), [grammar](grammar.md),
[listening](listening.md), [reading](reading.md), [maintenance](maintenance.md),
[card templates](card-templates.md), [backup](backup.md).

---

[Documentation index](../README.md#documentation)
