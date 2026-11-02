# Card templates (`kotogen deck install`)

`kotogen deck install` creates and updates in Anki the note types the program fills
(`Kanji`, `Vocabulary`, `Grammar`, `Listening`, `Reading`) from the templates in
`templates/`, so you do not copy them into Anki screen by screen. It needs **AnkiConnect**
(Anki open).

```bash
# Create the missing note types, offer to update the others
kotogen deck install

# Say what differs between the repository and Anki, without changing anything
kotogen deck install --check

# Stick to some types, overwrite without asking
kotogen deck install --only vocab grammar --yes

# Unfold the full diff of every difference, instead of the count
kotogen deck install --check --diff
```

> **Names are fixed; the content follows the language.** Note types, fields (`Vocabulary`,
> `Translation`, `Decoy1`...) and **tags** (`Level::N4`, `Check::Reading`) have the same
> names in every language and are never renamed: renaming one in an existing collection
> would split it in two, and a search such as `tag:Check::Reading` must find the same cards
> whatever the language. What a card says follows
> [the language setting](#the-language-of-the-cards), **English by default**: `all.lang=fr`
> asks the model for French translations and French decoys, under the same names. The
> templates have no language of their own.

## Options

| Option | Effect |
|---|---|
| `--check` | Say what differs between the repository and Anki, without changing anything |
| `--only TARGET...` | Note types handled (default: all): `kanji`, `vocab`, `grammar`, `audio`, `reading`. E.g.: `--only vocab grammar` |
| `--yes`, `-y` | Rewrite without asking every face the question is about, faces edited on both sides included (missing types are always created without a question) |
| `--diff` | Unfold the full diff of every difference, instead of the count |
| `--add-cards` | Also add the cards the repository has and the note type lacks |
| `--overwrite-edits` | Also offer to put the repository back over the faces edited in Anki alone, which are otherwise kept |

No AI option: installing a note type calls no model.

The fields created are exactly the ones the program writes (the `FIELDS` of each
generator), not guessed from the HTML, so a note type installed here accepts every card the
program produces. A command whose note type is missing carries a `(!)` in the home menu,
which offers to install it.

What the command does depends on who changed what:

| Situation | What the command does |
|---|---|
| Note type missing | **Created** without asking |
| A face (front, back or CSS) changed in kotogen alone: Anki still holds what kotogen last wrote there | **Rewritten** without asking: it only overwrites kotogen's own output |
| A face edited in Anki alone: the repository still holds what kotogen last wrote | **Kept**, and reported as `kept as edited in Anki` (`--overwrite-edits` to be asked about it) |
| A face changed on both sides | **Asked**, `no` by default, so that pressing Enter does not erase your edit. `d` shows each side's diff |
| A face that differs, with no record of what kotogen wrote there | **Asked** before overwriting: the HTML in Anki may hold edits that are not in the repository (`--yes` to skip the question) |
| Generator field missing from the type | **Added** without asking (it arrives empty and overwrites nothing), then moved to its rank in `FIELDS`. A send (`--send`) does the same before sending its notes, and says so: AnkiConnect drops without an error the value of a field the type lacks |
| Extra field in the type | **Kept** and reported: removing it would erase its content on every note |
| Repository card missing from the type | **Asked**: add it, stop reporting it, or later. Adding it creates one card to review per existing note, and the command shows how many (`--add-cards` to add it without a question) |
| Cards that cannot be paired (Anki has more cards than kotogen, under other names) | Their HTML is neither compared nor written: rename the cards in Anki to line them up |

**Order of the fields.** `modelFieldAdd` puts an added field **at the end of the list**,
so the command moves it to its rank in `FIELDS`, the order of a type created from scratch.
Review does not depend on the order (the templates call fields by **name**), but a TSV
import matches its columns to the fields by **rank**: a field out of place would shift
every following column into the wrong field, without an error. Anki moves the field with
its content.

Cards are paired by name, or by position when the names differ: a type set up by hand whose
card is called `Japanese to English` receives the HTML of `recognition/`, instead of getting
a second card added beside it.

## What kotogen wrote last

Comparing the repository with Anki cannot tell why a face differs: a `git pull` brought a
new template, a setting of the Appearance screen changed, the face was edited in Anki, or
several of these. So the command keeps a third version: the text it wrote on each face the
last time. The table above relies on it. For a face changed on both sides, `d` shows two
diffs, each from that text; a single diff from Anki to the repository would mix your edit
with the release:

```
   edited in Anki:
      @@ -1,4 +1,4 @@
       .word {
      -  font-size: 2em;
      +  font-size: 2.6em;
         color: var(--ink);
       }
   changed in kotogen:
      @@ -4,4 +4,4 @@
       }
       .hint {
      -  margin-top: 1em;
      +  margin-top: 0.6em;
       }
```

The record is a file on this machine, `installed.json` in the data folder
(`%LOCALAPPDATA%\kotogen\` on Windows, `~/Library/Application Support/kotogen/` on macOS,
`~/.local/share/kotogen/` on Linux), filed by Anki profile and by note type ID: the name of
a type can change in the settings, its ID does not. Nothing is added to the collection. The
record is written when a type is created, when a face is rewritten, and whenever the command
finds a face identical to the repository's, so a type with no record yet, or set up by
hand, gets one at its first install.

A face is rewritten without asking only when Anki holds exactly what the record says
kotogen wrote there. So a second machine whose record is out of date (the first one
installed since, and the collection was synchronised) keeps the newer text or asks, and
never puts an older template back without asking. Deleting the record makes the next
install ask about every difference.

After a `kotogen update` that brought new templates, the update says so and names
`kotogen deck install` as the step left.

## What the command shows

The output has three parts, never mixed: the state of every type, the question, then what
was written. Lines about a type start with its name, so a type can be followed from one
part to the next.

```
Kanji        up to date
Vocabulary   up to date
Grammar      up to date
Listening    8 lines on the front, 40 on the back, 3 in the CSS, 1 field added
Reading      8 lines on the front, 40 on the back, 3 in the CSS, 1 field added

Update Listening and Reading?
  y. yes
  n. no
  d. detail
  c. choose type by type

Backup 2026-10-01_091500 (5000 notes, Kanji, Vocabulary, Grammar, Listening, Reading)
Listening    updated
Reading      updated

Remember to synchronise Anki (it may ask for a full sync: that is normal).
```

The count is **per piece** (front, back, CSS), not per diff, to show what is rewritten and
on what scale. The card is named only when several
cards of the same type are touched (`40 lines on the back of "Recognition"`). Everything
that differs on a type is on its line, fields included. The changelog names the fields a
release adds; the install only counts them.

One question covers everything to rewrite, **`yes` by default**: that is what you run the
install for. Once you accept, a backup is taken before the first rewrite is written, so it
can be undone; what needs no question (below) holds nothing of yours and is done without
one. When a face changed on both sides, the default is `no` (see
[What kotogen wrote last](#what-kotogen-wrote-last)). `d` shows every diff before you
answer, face by face and card by card; `c`, offered when several types are asked about,
asks type by type instead, on the line of each type. When a single type is asked about, a
short difference (three lines or fewer) is shown at once; with several types it would
break up the summary. `--diff` shows every diff in full. Answering `n` writes nothing more.

What needs no question is done on the line that announces it: a missing type is created
(`Grammar  created: 9 fields, card Grammar`), a missing field added, a face changed in
kotogen alone rewritten (`Listening  updated: 40 lines on the back`). When the faces of one
type changed in different ways, each way gets its own line under the name of the type, so
what waits for an answer is kept apart from what was done:

```
Vocabulary   updated: 12 lines on the back
             kept as edited in Anki: 1 line in the CSS
```

The last part names only the types that were written to.

After any write, the command reminds you to **synchronise Anki**: Anki may ask for a full
synchronisation on the next sync, which is normal after templates have been rewritten.

## Not installing the whole repository

The repository holds every card type, including some you may not review, such as the
vocabulary `Production` card. Two [settings](global-options.md#where-the-settings-live) say
what **your** profile installs, without removing anything from the repository:

| Variable | Effect |
|---|---|
| `KOTOGEN_VOCAB_CARDS=Recognition` | Allow-list of the cards of this note type. The other cards are neither created, nor compared, nor reported |
| `KOTOGEN_SKIP=grammar,audio` | Commands you do not use: their entry leaves the menu, and `deck install` without `--only` skips them. `kotogen grammar` typed by hand still works |

Both are set in the assistant, in the "Templates" menu under **Decks and types**, which
also holds the Anki deck and the note type name of each command. Pick a note type (the list
shows the deck it goes to, or `not installed`), then its settings; the `Cards installed`
line appears only for a type with several cards:

```
     1. Kanji                     Japanese::Kanji
     2. Vocabulary                Japanese::Vocabulary
     3. Grammar                   Japanese::Grammar
     4. Listening                 not installed
     5. Reading                   Japanese::Reading
```

```
     1. Installed                 yes
     2. Cards installed           Recognition
     3. Anki deck                 Japanese::Vocabulary
     4. Note type                 Vocabulary
```

Two safeguards apply there. You cannot untick the last card of a note type: an empty list
means "all of them", the opposite of what you asked; `Installed: no` is the way to say it.
And changing the **name of the note type** renames nothing in Anki: the command then aims
at another type, and the old one stays with all its notes. The screen says so before you
type.

Both settings are also written when you answer a question at the moment the issue shows
up: `deck install` offers `no, and stop reporting it` for a missing card, and the home menu
offers `install it now` or `hide the command` for a command whose note type does not exist.
An unknown name in either variable stops `deck install` with an error instead of being
ignored.

## Customising the cards

The repository ships every block of every card; what you keep is set apart, so that a
`git pull` does not undo it and `deck install` does not report it as a difference.

It is set in the assistant, in the "Templates" menu. Its first group is about what the
cards look like, its second about what Anki holds; appearance settings reach Anki at the
next **Install**:

```
Templates - what to do?

  Your cards
    1. Preview            see them in the browser, set them on the spot
    2. Appearance         the same settings, in the terminal

  In Anki
    3. Install            create what is missing, ask before overwriting
    4. Compare            what differs, without changing anything
    5. Decks and types    what your profile installs, and where
```

**Preview**, which opens from this menu only, shows the cards with their switches beside
them (see [The preview](#the-preview)). **Appearance** holds the same settings in the
terminal. It lists the cards first, each with what you changed on it, and nothing beside
the cards you left as they are, so the list answers "what have I changed?" without opening
them. The palette, which applies to all five cards, is toggled on the same list:

```
  Card by card
    1. Kanji
    2. Vocabulary                TTS added
    3. Grammar
    4. Listening
    5. Reading                   2 changes

  All the cards
    6. Palette                   dark

    w. Write the templates to disk
    z. Put everything back to default
```

Behind each card are its settings. Each entry toggles in place, the screen stays open, and
the value beside it shows the current position:

```
   1. Writing of the word       kanji, furigana on the back
   2. Grammar badge             yes
   3. Verb colours              yes
   4. Adjective colours         yes
   5. Other word colours        yes
   6. Register badge            yes
   7. Context                   yes
   8. Notes                     yes
   9. Example sentence          yes
  10. Speech synthesis (TTS)    yes
  11. Tags on the back          no
```

```
   1. Furigana of the statement always
   2. Hint in the gap           yes
   3. Answer                    in your head
   4. Translation               at once
   5. Register badge            yes
   6. Nuance                    yes
   7. Level badge               yes
   8. Link to the entry         yes
   9. Explanation of the rule   yes
  10. Tags on the back          no
```

The settings come in the order the card shows what they touch, front before back and top
before bottom, so the panel of the preview reads down the card beside it. A setting that
affects the whole card, like the writing of the word, comes where it first shows.

**`z`** appears only when there is something to put back, and lists it before asking. Like
**`w`**, it is on the list of cards rather than on a card's screen: both act on all five
note types, including those you have not opened.

### The preview

**Preview** opens the cards in the browser, rendered with your settings. It shows one card
at a time, picked by two rows of tabs: the note type at the top, and below it the example,
when the type has several. The page opens on the first card. The terminal shows the page's
address and waits: press Enter there to close the preview.

| Tab | Examples |
|---|---|
| `Kanji` | one card, so no second row |
| `Vocabulary` | `Recognition`, `Production`: the two cards of one set of fields |
| `Grammar` | one card, so no second row |
| `Listening` | a sound extract, a video extract |
| `Reading` | a text, a mini-book, a composed document |

Front and back are side by side. They are the real templates, read the way `deck install`
reads them and filled with example fields and media: what breaks there breaks in Anki. That
includes the vocabulary `{{tts}}` once the setting turns it on: it shows as in Anki, as a
round play button at the bottom of the card, and clicking it reads the word with the
browser's voice. That button, and the room it takes, is the only visible effect of the
"Speech synthesis" setting.

The switches on the left are those of the card shown, plus those that apply to all cards.
Toggling one redraws the card without writing anything. **Apply** writes the settings of
every tab at once, including those set on other tabs, so you can try settings without
going back and forth into Anki.

The three buttons that act on every card sit together at the top right, beside the count of
settings left to apply: **Put everything back to default**, **Back to my settings** (what
the file holds) and **Apply**. They are kept out of the panel, which only shows the
switches of the current card.

**The language of the cards has no switch**: it changes no template (see
[The language of the cards](#the-language-of-the-cards)), so a switch would change nothing
on screen. It is set in the settings menu (`g`), with the other generation choices, or on
the language page of the getting-started guide. The
examples do follow it: with French cards, the preview shows French questions and decoys,
chosen when the page opens. **Apply** writes the language back unchanged.

The page itself stays dark when the palette is light, so that only the card changes. In
`auto`, the card is shown as Anki shows it by day, in light colours; the `dark` position
shows what night mode looks like.

**Desktop** and **Mobile** render the card in a window 900 px or 390 px wide. Each card is
rendered in its own window at that width, not zoomed, so the layout rules of the template
apply as on a device.

The preview is served on `127.0.0.1` while you look at it, and stops when you leave the
screen. Refreshing the page reads `templates/` again, which makes it a working loop when
you edit a template; `python tests/card_bench.py` opens the same page without the
assistant.

One thing the preview cannot show, since each face gets a window of its own: Anki desktop
keeps **one page** from card to card and runs every script of a face in it again, the
front's a second time on the back through `{{FrontSide}}`. So every script of the templates
is wrapped whole in `(function () { ... })();`: a `let` at the top of a script would stop
the whole script on its second run. And a listener on the document or the window is added
once, under a flag on `window`, and finds the card on screen when it fires: added by every
face, it would pile up, each copy acting on the card that added it.
`tests/test_templates.py` checks both on the shipped templates.

Nor does it show the page Anki desktop lays around a card. Its own sheets dress every
button, the card's included (margins, a font size per platform, rounded corners, a shadow, a
gradient on hover), and paint their own background in night mode: `templates/common.css`
takes all of that back, and the sheets of the cards write the rules of their buttons under
`.card`, which outranks Anki's. Anki desktop sets the classes of the page (`.card`, night
mode) only after the scripts of a face have run, so on the first card of a session a script
that measures, like the one that shrinks a word too wide for the screen, measures again once
they are set, and whenever the screen turns. And whether the scripts of `{{FrontSide}}` run a
second time on the back is up to the client: each back carries the scripts it needs, and a
script leaves alone what one before it has done. With Playwright and its Chromium installed
(the `[nhk]` extra), `tests/test_templates.py` shows the cards in a copy of Anki desktop's
page and checks all of this; without them, those tests are skipped.

The settings are written to one file, `templates.env`, next to the
[settings](global-options.md#where-the-settings-live) (`%APPDATA%\kotogen\` on Windows,
`~/Library/Application Support/kotogen/` on macOS, `~/.config/kotogen/` on Linux, or
`$XDG_CONFIG_HOME/kotogen/` when that variable is set), or next
to the repository `.env` if a `templates.env` is already there. It holds only the
**differences** from the default, so it reads as the answer to "what have I changed?", and it
is deleted when nothing differs any more. You can also edit it by hand.

What can be removed, written `=no`:

| Line | What it removes |
|---|---|
| `vocab.badge=no` | The grammar badge under the word (一段動詞, 名詞...), on both backs |
| `vocab.verb-colours=no` | The colour of the three verb groups (一段, 五段, 不規則) |
| `vocab.adjective-colours=no` | The colour of い- and な-adjectives |
| `vocab.other-colours=no` | The colour of the other words: nouns (counters and dates with them), adverbs (onomatopoeia with them), expressions |
| `vocab.notes=no` | The notes at the foot of both backs (a nuance, a limitation, a second sense) |
| `vocab.context=no` | The gloss that tells two words of one translation apart, on the back of `Recognition` only |
| `vocab.register=no` | The register badge beside the grammar badge (謙譲, 口, 男...), on both backs |
| `grammar.hint=no` | What is written in the gap on the front (a person, a tense, the form to conjugate), and the line of the back that sets it against the answer |
| `grammar.explanation=no` | The explanation under the name of the rule, on the back, and the neighbouring rule it sets apart (≠) |
| `grammar.register=no` | The register badge (常体, 丁寧体, 尊敬語, 謙譲語) over the sentence |
| `grammar.nuance=no` | The nuance, the line under the register badge |
| `grammar.badge=no` | The level of the rule (`Grammar::N4::…`), at the foot of the back |
| `grammar.link=no` | The link to the reference page, at the foot of the back |
| `audio.badge=no` | The level over the question of the listening card (`Level::N4`) |
| `audio.source=no` | Where the extract comes from, at the foot of the card |
| `reading.badge=no` | The level over the question of the reading card |
| `reading.key-line=no` | The bar the back sets against the line the answer comes from, and the page a mini-book opens at |
| `reading.source=no` | Where the text comes from, at the foot of the card |
| `kanji.badge=no` | The level and the number of strokes, under the kanji on its back |
| `kanji.word-readings=no` | The reading at the end of each word; the kanji in the word keeps its colour |
| `kanji.composition=no` | What the kanji is made of (構成) |
| `kanji.lookalikes=no` | The kanji it is mistaken for (≠) |
| `kanji.notes=no` | The words read as a whole you have met (熟字訓) |

Each line removes the block and the style rules that go with it, so no unused CSS is left
behind. The verb and the adjective colours have separate switches: the group of a verb
(一段 or 五段) decides how it conjugates, while an い- or な-adjective can be told from
the word itself.

Four settings work the other way: their block is left out by default, and `=yes` adds it.

| Line | What it adds |
|---|---|
| `vocab.tts=yes` | The speech synthesis (`{{tts}}`) of the two vocabulary backs, on a note with no recording of its own (see [The pronunciation of a word](#the-pronunciation-of-a-word)) |
| `vocab.tags=yes` | The line of tags at the foot of the two vocabulary backs |
| `grammar.tags=yes` | The line of tags at the foot of the back |
| `kanji.tags=yes` | The line of tags at the foot of the back |

A tag files a card (`Level::N4`, `Check::Reading`); it is not something to learn, and what
a tag could teach is already on the card: the class and the register of a word as badges,
the name of a grammar rule at the head of the back, the level of a kanji under it. The tags
stay on the note either way, and Anki's browser shows them.

And what can be swapped, the first position being the default:

| Line | Positions |
|---|---|
| `vocab.furigana=` | `yes`: the kanji alone on the front, the readings on the back. `no`: no readings on the back either. `kana`: no kanji on the card - the word, its example and its notes in kana, on both sides; the note keeps its kanji, and another position brings them back |
| `vocab.example=` | `yes`: the example sentence and its translation. `untranslated`: the sentence alone. `no`: neither |
| `audio.player=` | `drawn`: the card draws its own player - play, a bar with a tick where each sentence starts, the time and the speed (1×, ¾×, ½×). `native`: the system's player, with its speed in its own menu |
| `audio.choices=` | `four`: the listening card shows its four choices. `two`: the right one and one decoy. `none`: you answer in your head. `alternate`: one card in two, by its rank |
| `audio.transcript=` | `folded`: the transcript opens on click. `unfolded`: it is open |
| `audio.translation=` | `on-click`: the 訳 button is there, off. `at-once`: on. `never`: no button, and the translation stays hidden |
| `audio.click=` | `sentence`: a clicked sentence plays to its end, then stops. `continue`: playback goes on after the clicked sentence |
| `reading.translation=` | The same three positions, for the 訳 button the back sets beside the ふ of the reading card |
| `reading.choices=` | The same four positions, for the reading card |
| `reading.markers=` | `letters`: A, B, C, each in a ring. `digits`: 1, 2, 3. `none`: no marker before the choices |
| `reading.order=` | `daily`: the choices are shuffled again every review day. `fixed`: the same order every time |
| `reading.furigana=` | `button`: a ふ button shows them. `always`: the text carries them. `never`: the kanji alone. `back`: the front without, the answer with |
| `grammar.answer=` | `recall`: you form the answer in your head and turn the card over, like a vocabulary card. `type`: an input box under the sentence, and the back compares character by character |
| `grammar.translation=` | `at-once`: the translation is under the sentence, and the part that renders the gap under the gap. `on-click`: a 訳 button under the gap reveals both, so you can try from the Japanese first; a note with no part to hang under the gap has the button where the translation will show |
| `grammar.furigana=` | `always`: the sentence carries its readings on both sides. `back`: the front without, the answer with. `never`: the kanji alone |
| `kanji.onyomi=` | `katakana`: the on readings as dictionaries write them (ガク). `hiragana`: as a word reads them (がく). Their colour tells them from the kun readings in both positions |
| `kanji.other-readings=` | `no`: the common readings no word of the card illustrates are left out. `folded`: they wait behind 他, a tab on the strip of readings. `shown`: on a row of that strip. The readings the Joyo table marks as rare are on no card |
| `kanji.words=` | `yes`: each word with its translation. `untranslated`: the word alone, read in Japanese |

Three settings change the exercise, not only what is shown: `reading.furigana=back` (you
read the text without readings, and the answer shows them), `choices` below `four` (you
answer from memory instead of recognising the right choice among four) and
`grammar.answer=type` (you type the form instead of only thinking it). The grammar card
fills its `Answer` field in both positions, with the gap stripped of its readings (you type
`降れば`, not `降[ふ]れば`), so switching needs no new cards.

`choices` sets the **maximum** number of choices shown. The note always holds four
(generation asks for them on every card), so the setting can change without new AI calls.
A note with an empty `Decoy1` field (a card filled in by hand, or a model that did not
follow the instruction) is answered from memory in every position. At `two`, the draw that
shuffles the choices also picks which of the three decoys stays, so front and back show the
same one. `alternate` reads the rank of the card from its ID: odd ranks show their choices,
even ranks are answered from memory.

There is no `audio.translation=always`: it would match `at-once`, except that the
translation could not be hidden again.

`audio.click` only changes what a **click on a sentence** does. At `sentence`, the play
button still plays the whole recording; a clicked sentence stops at its end, so you can
replay a difficult sentence several times without cutting it by hand. At `continue`,
playback goes on after the clicked sentence, as if you had moved the playhead. The end of a
sentence is the **start of the next one** (the transcript only holds start times), so the
setting needs no regeneration and applies to the cards already in the deck. The playhead is
checked at every screen refresh, so the stop is accurate to a frame. A sentence that
generation could not place has no start time of its own: clicking the sentence before it
plays both.

There is no `grammar.translation=never` either. On the listening and reading cards the
translation is a help; on a grammar card it is **the question**, since it tells you what to
put in the gap, and without it the card could not be answered. `on-click` lets you try from
the Japanese first.

`grammar.furigana` only affects the **sentence**. The conjugation hint and the explanation
on the back keep their readings in every position: they are there to help, not to test.

These settings remove what a card shows beyond its question, never the question itself.
Three blocks look removable but are part of the question:

- the **context of a `Production` card**, on the front: 「着[き]る」, 「履[は]く」 and
  「被[かぶ]る」 all translate as "To wear", and "upper body" is what leaves one answer.
  `vocab.context=no` therefore removes it from the back of `Recognition`, where it follows
  the answer, and leaves it on `Production`, where it asks. The **register badge** is on
  no front: on `Recognition` 謙譲 would give half of the meaning away, and on `Production`
  the context does that job: 友達 and 友人 are both "Friend", and the context of the
  second says *more formal than 友達*;
- the **figure of a listening card**, the drawing of a JLPT past-paper item: the recording
  says 「この絵を見てください」 and the four pictures are the choices;
- the **name of the rule** on a grammar back: it names the point, and the link points at
  it. `grammar.explanation=no` removes the prose under it and keeps the name.

Removing a block deletes nothing: the `Example`, `Notes`, `Context`, `Hint`, `Nuance`,
`Explanation`, `KeyLine` and `KeyPage` fields are written into every note whatever the
settings, like the four choices. Changing a setting needs no new AI calls, and applies to
cards generated before.

`deck install` and `deck install --check` end the line of a type that differs with the
number of these settings it carries, which explains a difference when nobody touched the
repository. A type that is up to date only says so; the Appearance screen lists the
settings themselves.

```
Vocabulary   12 lines on the back, 1 customisation
Reading      up to date
```

### Getting the templates out without Anki

The "Templates" screens work **with Anki closed**: the settings, the preview and
`templates.env` read `templates/` on disk and never talk to AnkiConnect. Only **Install**
and **Compare** need the connection, and they are dimmed without it. Two ways remain to get
what you have set and paste it by hand into Anki's card editor.

**In the preview**, the **Source** button replaces the cards with their source: the fields
to create, in order, the front, the back and the style sheet, each with a **Copy** button
and the name of the Anki box it goes into. It is the rendered source, your settings
included, so there is nothing to trim before pasting. The `{{Field}}` and `{{FrontSide}}`
tags stay in it, unlike on the card shown: they are Anki's syntax, and Anki fills them in.
Toggling a switch while reading the source updates it at once. Cards and source are
rendered by the same rule, and the page warns at the top if that rule disagrees with what
`deck install` would write.

**On a machine without a browser**, where the preview does not open, the **`w`** entry
writes the same thing into a folder, `templates/` under the
[output folder](global-options.md#output-folder-of-the-tsv-files):

```
templates/
   README.txt                     what goes where in Anki, and what to create first
   Vocabulary/
      fields.txt                  the seven fields, in order
      style.css
      Recognition/front.html, back.html
      Production/front.html, back.html
   Grammar/
      fields.txt, style.css, front.html, back.html
```

The folders carry the names **Anki** shows (the note type as your profile names it, the
card as Anki's editor calls it), not those of the repository (`vocab/recognition`), since
you will have Anki in front of you. A type that
[`KOTOGEN_SKIP`](#not-installing-the-whole-repository) leaves out is not written, nor is a
card the settings do not keep, and a type with a single card gets no card subfolder.

### The pronunciation of a word

Both vocabulary backs play the word at the foot of the screen, from one of two sources:

- **A recording**, in the `Audio` field of the note. kotogen leaves it empty for a sound
  you add yourself in Anki's editor: its microphone records one, its paper clip attaches a
  file. A note that holds one plays it, whatever the setting says.
- **The system voice**, `{{tts ja_JP:kana:Expression}}`, which Anki asks of the machine.
  It is off by default; `vocab.tts=yes` turns it on, and it then speaks only on a note
  whose `Audio` is empty: the recording is the better voice, and two players would sit on
  top of each other.

The system voice is off by default because it needs a Japanese voice the machine may not
have. Anki desktop has none on Linux, and on Windows it finds none until the Japanese
speech pack is installed (Settings > Time & language > Language). Without one, every back
shows `no player found for TTSTag(...)`. The note type is synced, so the setting applies on
every device: turning it on for a phone, where a Japanese voice is usually present, turns
it on for the computer too.

### The language of the cards

`all.lang=fr` asks for all five note types in French: like the palette, the language is
one setting for every note type.

It is the counterpart of the [interface language](global-options.md#the-two-languages),
and the two sit one under the other in the settings menu: `l` for the screens, `g` for the
cards. The language page of the getting-started guide sets both, the cards right after the
screens. It changes no template, so the Appearance screen does not show it, and its **Put
everything back to default** leaves it as it is. The two languages are independent: a
French interface filling an English deck is a valid setup.

| Line | Positions |
|---|---|
| `all.lang=` | `en`: the default, the cards written in English. `fr`: the cards written in French. `ja`: the cards written in Japanese, for whoever learns Japanese in Japanese |

The setting picks the folder of instructions given to the model, `prompts/en/`,
`prompts/fr/` or `prompts/ja/`, which makes the card content English, French or Japanese.
Only the twenty-two instructions that ask for card text exist once per language. The
thirteen that hand back structure (where to cut an audio file, how a PDF is laid out) live
in `prompts/structure/` and are used whatever the setting, because they answer in JSON and
write nothing in the language of the cards. See [the instructions](prompts.md).

**The templates do not change with it.** A card prints no prose of its own: its words come
from the note, and its own markings are signs: 本文 and 訳 on the listening card, ふ and 訳
on the reading card, the chevrons of the mini-book, 音, 訓 and 他 on the kanji card, the
arrow from a word to the form a grammar rule makes of it. The same templates serve a
French, an English and a Japanese reader. Signs also work where a label's tooltip would
not: a tooltip never shows on AnkiDroid. What a screen reader says of a button drawn as a
sign is Japanese too, and as short: 前のページ, 全画面, 参照.

A Japanese card holds Japanese under `Translation`, the `Decoy` fields and the `Answer` shown
among them, its meanings and questions included. The export lays readings on that text (all but the `Translation` of a grammar card, which
stays plain) and the templates show it through the furigana filter, so a word above the
level of the card can still be read. In the other languages these fields carry no readings
and show as they are.

The setting is read only when cards are written, never by `deck install`: the same
templates are installed whatever the language, and switching `all.lang` takes effect at the
next generation, with nothing to reinstall.

### The palette

`all.palette=light` switches all five note types to light colours. Like `all.lang`, it
belongs to no single card, hence the `all.` prefix.

| Line | Positions |
|---|---|
| `all.palette=` | `dark`: the default palette. `light`: dark text on a light background. `auto`: follows Anki - light by day, dark in night mode |

`auto` suits a collection reviewed both ways, for example at a desk by day and on a phone
in night mode. Anki signals night mode by marking the card `.nightMode` (`.night_mode` on an older
AnkiDroid), and that is all the automatic palette reads: the light colours apply by
default, the dark ones wherever the card carries that class.

The colours every card shares (the background, the surfaces, the levels of text, the green
of the answer, the accent of what can be pressed) are written once, in
`templates/common.css`, which `deck install` puts at the head of the style of each note
type. A note type's own sheet comes after it and holds only the colours of that card: the
registers of grammar, the on and kun readings of the kanji, the classes of the vocabulary.
Each sheet writes its dark colours once, opened by `:root` in the dark palette or by Anki's
night mode in the automatic one, and its light colours once. The shared sheet opens them on
the card too (`.card`, `.card.nightMode`), with the `color-scheme` that draws the native
controls: Anki desktop's night mode declares its own above `:root`, and would otherwise
draw the system's player and the typing box of a light card dark.

Green marks the answer and nothing else: the revealed gap, the right choice, the line the
answer was read in. What only acts (a switch, the focus, a hovered link) takes the accent
colour, so on a back the eye goes straight to the green.

The colours are written as `R, G, B` components rather than `#rrggbb`, so the same variable
serves for a solid colour on a text or a border and for a translucent background in that
colour:

```css
:root {
  --correct: 76, 175, 80;        /* the green of the right answer */
  --verb-一段動詞: 255, 235, 59;
}
```

The light palette is not the dark one inverted: a yellow that reads on black is unreadable
on white, so its bright colours are darker and less saturated. In both palettes, every
level of text has a contrast ratio of at least 4.5 (the AA threshold) on the card's
background, and so does the reading over the word highlighted in an example. The card keeps
that background in Anki desktop's night mode, which would otherwise paint its own.

One surface stays dark in every palette: the mini-book in full screen, black like an image
reader. The shared sheet keeps its dark colours in every palette for it, opened on the
`.is-full-screen` class the card's script lays whichever way full screen was reached, so
the colours are written once. Its question shows in white on a dark band, and its page
controls sit on a dark band too.

For another palette, edit the colours in `templates/`, as for the rest of the templates.

---

[Documentation index](../README.md#documentation)
