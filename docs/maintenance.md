# Deck maintenance (`kotogen maintain`)

`kotogen maintain` looks after an existing deck. Its targets, named by `--only`, are the
seven colour **flags** of Anki, the star and the **`leech`** tag. Without `--only`, every
target that has an action is handled, in every note type the profile uses (vocabulary,
grammar, listening and reading, minus the commands in `KOTOGEN_SKIP`); `--type` narrows the
note types. For each card, the AI proposes a correction, you see the change, and once you
accept it the card is updated and its mark removed. Requires **AnkiConnect** (Anki open).

```bash
# Look: flags + leeches in one and the same count (read only)
kotogen maintain --scan

# Handle everything, in every note type in use
kotogen maintain

# Only the grammar and listening cards
kotogen maintain --type grammar audio

# Only some targets (colours and/or leech; numbers 1-7 accepted)
kotogen maintain --only red blue leech

# Accept everything without card-by-card validation
kotogen maintain --yes

# Automatic on some targets only, the rest validated by hand
kotogen maintain --yes red green
```

## The survey (`--scan`)

`--scan` lists what the deck carries, target by target, without changing anything. It is the
list the menu offers targets from, with the counts added; a target with no count has nothing
waiting.

```
Maintenance of "Vocabulary":

  🔴 red         possible mistake      3
  🟠 orange      to simplify           2
  🟢 green       to enrich            10
  🔵 blue        text mistake
  🌸 pink        to derive
  🩵 turquoise   possible duplicate
  🟣 purple      audio mistake
     leech       failed over and over  5
                 3 mastered cards (ivl >= 21): the "leech" tag comes off in bulk
                 2 to rework (ivl < 21): rewriting then reset
  = 20 cards to handle
```

With work in several note types, each one gets a column:

```
Maintenance of "Vocabulary", "Grammar", "Listening", "Reading":

                                    Vocabulary  Listening
  🔴 red         possible mistake            3          2
  🟠 orange      to simplify                 2
  ...
  ! 2 Grammar cards under purple: nothing handles that for this type, left as they are
```

A flag whose action does not apply to a note type is left alone there (purple checks the
audio, and a grammar card has none): its cards are counted under the list and again after
the summary of a run, and keep their flag.

The `leech` count covers two jobs: false leeches (mature cards) lose the tag in bulk, with no
AI call; the others are rewritten one by one. `--only` narrows the survey, and with `--yes`
the targets it would automate are marked `[automatic]`.

## Options

| Option | Effect |
|---|---|
| `--type TYPE...` | Note types to go through, named by their command: `vocab grammar reading audio` (default: every one in use, see `KOTOGEN_SKIP`) |
| `--only TARGET...` | Targets to handle (default: every target that has an action): `red orange green blue pink turquoise purple` (or the numbers 1-7), `star`, the name of an action (`renew`: the flag that triggers it), and/or `leech` |
| `--scan` | Show the survey, then exit: no AI call, no change |
| `--yes [TARGET...]`, `-y` | Apply without card-by-card validation, everywhere or on the listed targets only. Never deletes a note |
| `--tag NAME` | Name of the leech tag (default: `leech`) |
| `--mature-ivl DAYS` | Interval in days from which a leech counts as mastered (default: 21) |

`maintain` writes straight into Anki: it has no `--send` or `--output`. `--provider` and
`--model` work as everywhere ([Global options](global-options.md)). For a job no target
covers, make the request in your own words with `kotogen ask` (see [Asking](ask.md)).

## The net

`maintain` can delete notes, rewrite fields in bulk and reset leeches, so it first takes a
**snapshot** of your Japanese decks, after the survey and before the first AI call:

```
Backup 2026-08-17_143012 (1284 notes, Vocabulary)
```

The snapshot holds the fields, the tags and the **scheduling** of every card, so it also
covers the reset of a real leech. `--scan` takes none, nor does a run with nothing to do.
`kotogen backup --diff` then shows what the run changed, which helps most after `--yes`. See
[Backup](backup.md).

**A correction Anki refuses** is a single `!! Applying failed:` line: the card keeps its
flag (or its leech tag), and the run goes on. So does an AI error on one card. **If Anki
closes during a run**, an editor window blocks the writes, Anki refuses any other write
(taking a flag off, for one), or the AI refuses the key, `maintain` stops there: it prints
its summary, which counts what was really done, then `Maintenance interrupted:` and the
reason.

Ctrl+C prints `Interrupted by the user.` and the summary, then leaves with the exit code
130 (see [When a command stops](global-options.md#when-a-command-stops)). `[q]` prints
`Interrupted by the user.` too, then the summary, and leaves with the exit code 0. The lone
kanji still move to the kanji deck after `[q]`; after Ctrl+C or a stop, the move waits for
the next run.

## Automatic mode (`--yes`)

`--yes` applies the corrections without asking for each one. Alone, it covers every target
handled; followed by targets (`--yes red green`), it covers only those, and the other targets
still ask you. A target given to `--yes` but not to `--only` is ignored.

| Target | In automatic mode |
|---|---|
| Flags 1-4, 7 | The correction is applied and the flag removed. With nothing to correct, the flag is removed too, so that the card is not examined (and paid for) again at every run. The flag stays when a kanji is still without furigana (the AI missed it), or when every change was turned down. |
| 🌸 Pink | Every new word or rule the AI proposes is generated and sent to Anki. A created card is easy to delete, which is why this goes further than turquoise. |
| 🩵 Turquoise | The distinctions are applied, over the whole batch sharing the translation too: contexts, notes, or a translation that is too broad. **Nothing is deleted**: when the AI proposes a deletion, or the batch holds the same word twice, the flag stays for a run by hand, and in the second case the batch gets no contexts until then. |
| False leeches | Tag removed and cards unsuspended, in bulk, without confirmation. |
| True leeches | Rewrite (with kanji help when the AI gives some), unsuspend and **full reset** of the progress: the heaviest change, to automate knowingly. When the AI proposes nothing, the card is left as it is. |
| Lone kanji that is not a word | With a kanji deck, the kanji gets its card there if it has none. With or without one, the note is held under `Category::ToReview`, neither corrected nor deleted; the next run by hand only asks about the deletion. |
| Out-of-category card | Tagged `Category::ToReview` and left as it is, flag included. |

## Flags

Each flag triggers an **action**, which answers one question about the card: a translation
that says something else is red, badly written Japanese is blue.

| Flag | `--only` | Action | The question | What it does |
|---|---|---|---|---|
| 🔴 Red | `red` (1) | `error` | Is it **wrong**? | Minimal correction of the meaning, the translation, the furigana, the example, and of the tags that do not fit the word |
| 🟠 Orange | `orange` (2) | `simplify` | Is it too **hard**? | A lighter card: the main sense, concise notes, a shorter example |
| 🟢 Green | `green` (3) | `enrich` | Is it **incomplete**? | Adds what is missing: example, note, context, tags of the taxonomy. Never a register, speaker or dialect tag: only red corrects those, since a word without one is still right but a wrong one shows as a badge at every review |
| 🔵 Blue | `blue` (4) | `text` | Is the Japanese badly **written**? | Furigana (missing, wrong, badly cut), typos, spacing, punctuation, without changing what the text says |
| 🌸 Pink | `pink` (5) | `derive` | What **new** cards does it call for? | Proposes related words, then generates the ones you keep (see [Deriving](#deriving-pink)) |
| 🩵 Turquoise | `turquoise` (6) | `duplicate` | Does it exist **already**? | Searches the whole deck for duplicates, then [tells apart the batch sharing its translation](#the-batch-sharing-a-translation) |
| 🟣 Purple | `purple` (7) | `audio` | Is it badly **heard**? | Checks that the kana reading the TTS speaks is right and not ambiguous |

**`renew`** has no flag by default. For a card you recognise by its example sentence rather
than by its word, it writes a new example in another situation and keeps the word and its
translation. The table describes vocabulary cards; the other note types get the same actions.

A field the AI corrects gets the readings a generated card gets: MeCab fills in those it
left out, except in the fields a generated card carries without them, such as the `Answer`
you type on a grammar card or the `Context` of a word.

### Grammar, reading and listening cards

| Action | Grammar | Reading | Listening |
|---|---|---|---|
| `error` | a gap that does not hold the form of the rule, a wrong sentence or translation, a target the translation does not contain, a wrong register tag | an answer the text does not support, a decoy that is also right, a mistranslated line, a key line on the wrong line | the same, against the transcript, and a question that names a speaker `A` or `B`, which the front cannot show |
| `simplify` | a long sentence, a gap open to several answers (narrowed by the nuance, the hint or the register) | a twisted question, an answer too long to recall, decoys too close to it - never the text | the same - never the transcript |
| `enrich` | an empty explanation, target, nuance or hint, a missing register tag | a missing translation, fewer than three decoys, an empty key line | the same |
| `text` | the furigana and writing of the sentence and the hint, punctuation moved out of the gap | the furigana and writing of the text, line by line | the same for the transcript, and its speaker labels |
| `renew` | a new sentence for the same rule | a new question on the same text | a new question on the same extract |
| `duplicate` | the same card twice, or two cards whose hints lead to the same answer | the same text twice, or two questions that ask the same thing | the same extract twice, or two questions that ask the same thing |
| `derive` | the rules learned with this one (see [Deriving](#deriving-pink)) | the words and the grammar of the text | the words and the grammar of the transcript |
| `audio` | - | - | the extract heard again (see [below](#hearing-a-listening-card-again-purple)) |

A grammar or reading card has no sound: purple on one is counted and left in place (see
[the survey](#the-survey---scan)).

Whatever the model answers:

- **A grammar card keeps one gap.** A sentence with no gap or two is turned down, and the
  answer to type is worked out again from the gap. The card colours the `Target` inside the
  translation, so a `Target` the translation does not contain is turned down, and an old
  one that a new translation no longer contains is emptied.
- **A text keeps its lines.** A reading text, a transcript and their translations are
  paired line by line, with the key line and with the instant each line starts. A
  correction that changes their number of lines is turned down (the change shown says so);
  the rest of it goes through.
- **The model does not touch the tags**, except the register tags of a grammar card.
- **A passage is corrected whole.** Each question on a text or an extract is a note of its
  own, carrying the same text. A correction of the text, the transcript or the translation
  goes to every card of the passage that still carries the same text, and the change shown
  says how many. The question, the choices and the tags stay each card's own.

### Hearing a listening card again (purple)

On a word, purple checks the reading the speech synthesis says. On a listening card it
checks the card against the sound, for three faults: an extract cut mid-sentence, a
transcript that differs from the audio, and a line that does not land on its sentence when
clicked.

- **Finding the recording.** The name of the extract carries the name of the file it was
  cut from, which is looked for in the cache where kotogen keeps its downloads (podcasts,
  YouTube, textbooks, past papers). For a file of your own, you are asked for the file or
  its folder; a folder is searched again for the later passages of the run.
- **Hearing it.** Whisper (the `medium` model, as in `kotogen audio`) hears the extract with
  fifteen seconds on either side. A sentence the old cut went through is taken whole, and
  the new cuts go in the silence before the first sentence and after the last, as the
  split lays them.
- **Rewriting it.** The model writes the transcript of what is heard, in furigana, one
  sentence per line, with its translation and the key line of each question of the
  passage. The instant of each line is worked out again from Whisper's timestamps, even
  when the transcript was right.
- **Showing it.** You see the old and new bounds, the lines that come and go, and the
  questions that lose their answer. Once you accept, the new extract goes into Anki and onto
  every card of the passage, with its new bounds in `Source`. The old file stays in the media
  folder, so that a `kotogen backup --restore` puts back a card that still plays; Anki's
  **Tools > Check Media** deletes it once no note plays it.

Without the recording, the extract is heard as it stands: its transcript and timing are
checked, but its bounds cannot move, and the screen says so. Automatic mode never asks for a
recording. With `--yes`, a change that would leave a question without its answer is not
made, and the card keeps its flag, as it does when the extract is missing from Anki's media
folder.

### Duplicates beyond words

- **Grammar.** The candidates have the same or a close sentence (readings and punctuation
  aside) or the same translation; the same rule on another sentence is not one, since a
  rule is learned on several sentences. The model calls each candidate `duplicate` (the
  same question twice: you keep one) or `confusable` (fronts that do not tell the two
  apart: the `Nuance` and `Hint` of one card or both are adjusted, and nothing else).
- **Reading and listening.** First the passage: the same text under another identifier, or
  for listening the same media file, is the same passage added twice. It is found without
  an AI call; you keep one, and deleting a passage deletes all its cards. Then the
  questions: one call reads the passage and names the questions that ask what the flagged
  one asks. You keep one of the two, or ask the flagged card something else (`renew`).
- **With `--yes`**, confusable grammar cards are told apart and a flagged question asked
  twice gets a new question; a deletion waits for you, and the card keeps its flag.

### Choosing what each mark asks for

The flag table above is the default. **Corrections > Marks** in the menu gives any flag
another action, or none; a flag with no action is left alone and leaves the survey. The star
is there too: it is Anki's mark of the **note** (Ctrl+K in the browser). It has no action by
default, as it often marks favourites; given one, it is handled like a flag, one card per
note, and comes off the note once the card is settled.

```
    1. 🔴 Red          possible mistake
    ...
    5. 🌸 Pink         to derive
    ...
    8. ⭐ Star         to renew

    9.    Leech        to rework
```

The leech is apart: Anki lays it after too many lapses, so it is only handled or not. With no
action, `maintain` leaves the `leech` tag alone and the target leaves the survey.

An action belongs to one flag at most: giving it to a flag takes it from the flag that held
it, which gets the first flag's old action in exchange. The setting is `KOTOGEN_FLAGS`, and
it holds only the differences from the default (`pink=renew,star=derive`, `none` for no
action, `leech=none` for the leeches), so a flag you never changed follows the default of
later releases.

`--only` accepts an action name as well as a colour: `kotogen maintain --only renew` handles
whichever flag triggers `renew`, and stops with a message if none does.

### Deriving (pink)

Pink adds cards rather than correcting the flagged one. For a word, the AI proposes up to
four words best learned with it, each with a short gloss: its **antonym**, its **transitive
or intransitive twin** (開ける / 開く), a word of the **same family** (語 -> 日本語), a word of
**close meaning** to tell apart, a **set phrase** built on it. Words the deck holds, or that
an earlier card of the run called for, are listed apart and not offered.

```
── note 1712345678901 ──────────────────────────────────
   Expression: 開[あ]ける - To open
   already in the deck: 閉める
   Create 開く - to open (by itself) (transitive or intransitive twin)? [y] yes  [n] no
```

The words you keep go through the generation of `kotogen vocab` (known words turned down,
levels and readings checked), batched for the whole pass, into the deck of the flagged card.
The flag comes off once Anki has taken them, and also when every card was turned down, which
a new run would only pay to do again. If a call or the send fails, the flags stay. A lone
kanji is not offered for deletion here: 語 is the card 日本語 and 英語 derive from.

- **A grammar card** calls for up to three rules: a neighbouring rule to **tell apart**
  (ながら / つつ), one of the **same family** (ば / たら / と / なら), the **next step** built
  on it (ている / てある). Each rule kept goes through `kotogen grammar`, three cards to
  start with, into the deck of the flagged card.
- **A reading or listening card** calls for what its text holds: up to six words and two
  grammar points, in one list that says which is which. The words go to the vocabulary
  deck, the rules to the grammar deck. The text is read once, however many of its cards are
  flagged.

Rules the grammar deck holds are left out like words: by their reference entry when they
have one, by their name otherwise. A card whose proposals went into two batches (words and
rules) keeps its flag until both are in Anki.

**The [`Context`](vocabulary.md#the-context-field) field**, which tells apart two words with
the same translation, has two flags of its own:

**🟢 Green.** The AI finds what is missing (an example, a useful note, a context) and adds
only that. It adds a context **only** when the word can be confused with another of the same
translation (着る / 被る for `To wear`). With nothing useful to add, the card stays as it is,
so you can set green whenever in doubt.

**🩵 Turquoise.** The distinction goes into the contexts, over the whole batch sharing the
translation (see [the batch sharing a translation](#the-batch-sharing-a-translation)). The
plainest card of the batch keeps an empty context, since the contexts of the others point
away from it; a second bare card would not be told apart. The notes hold a nuance too long
for a short phrase. Two cards whose contexts already differ rank much lower among the
duplicate candidates.

Red corrects a wrong context like any other mistake, and the rewrite of a real leech fills
in the context when confusion with another word makes it fail.

**Lone kanji:** before any correction, flag or leech, a card whose expression is a single
kanji that is not a word on its own (語, 的, 勉...) is reported: there is nothing to review on
it as a word. What it teaches is the kanji, which the [kanji cards](kanji.md) are for, so
moving it there is offered first:

```
!! 語: lone kanji, not a vocabulary word on its own (suffix, e.g. 日本語)
     m. move it to the kanji deck
     d. delete the card
     k. keep it and review it
```

These menus work as in the [interactive mode](interactive.md): `↑` `↓` and Enter, or the
letter then Enter. A letter only moves the highlight, and the highlight starts on the last
line, the safest, so neither a wrong key nor a reflex Enter deletes anything. Outside a
terminal, you type the letter.

`m` asks for confirmation, then waits for the end of the run: the cards of all the kanji
moved are made in one batch, the way `kotogen kanji` makes them (readings from the tables,
words of your vocabulary first). The vocabulary note is deleted once Anki has taken the card
of its kanji; a card turned down or a failed send leaves the note and its flag for the next
run.

The move is not offered when the kanji already has its card (deleting the note then loses
nothing), nor without a kanji deck (the `Kanji` note type not installed, or `kanji` in
`KOTOGEN_SKIP`). For automatic mode, see [the table above](#automatic-mode---yes).

`k`, like a "no" to a confirmation, keeps the card and goes on to its correction. A card an
automatic run held under `Category::ToReview` loses that tag: the decision is taken.

**Out-of-category cards:** a vocabulary card that is really a **grammar rule** (〜ながら, a
particle on its own), a **whole sentence** or a **fragment** with no use on its own is
reported the same way, flag or leech, with what to do with it:

```
!! 〜ながら: this card has no place in the vocabulary
   grammar rule: its place is in the grammar deck
   → to remake with: kotogen grammar "〜ながら"
     d. delete the note
     k. keep it (stop reporting it)
     l. later
```

These cards are **reported, never deleted outright**: a rule or a sentence may hold content
worth keeping. A tag keeps your answer: `Category::Kept` closes the matter (no more reports,
and the card is corrected like the others), `Category::ToReview` puts the decision off. A
card put off is **left as it is**: not corrected, flag kept, and not reworked as a leech, so
the next run reports it again. Automatic mode puts off every such card, and the run ends by
saying how many wait:

```
! 2 cards wait for your decision: kotogen maintain, or tag:Category::ToReview in Anki
```

The passes that correct tags (red, green) cannot remove these two tags. The check costs **no
extra AI call**: the verdict comes in the answer that corrects the card.

**Deleting a card yourself:** the checks above miss cases, and the AI stays silent when in
doubt, so the correction menu always offers `delete the note`, with or without a correction:

```
     a. accept
     d. delete the note
     s. skip
     q. quit

     r. remove the flag
     d. delete the note
     k. keep the flag
```

The first menu starts on `skip`, so a reflex Enter skips the card. `quit` stays last because
a script whose input runs out picks the last line, which stops the run instead of paying for
every card left. A deletion asks for confirmation (`[y] yes / [n] no`) and takes every card
of the note; automatic mode never deletes.

**Duplicates (turquoise):** the whole deck is searched on several signals (reading,
spelling, translation, each exact or close), the AI gives a verdict (`duplicate`, `variant`
or `different`), and you choose: keep one card, tell the two apart, or do nothing. When you
ask to tell them apart and one card has no place in the deck (a wrong spelling, a malformed
word, nothing to review) while the other is good, the AI may ask for its deletion instead of
inventing a nuance; you confirm it or keep both.

The translation signal ignores the empty words (articles, `de`/`of`, `qqch`/`sth`) of **the
language of the cards** (`all.lang`, see [Card templates](card-templates.md#the-language-of-the-cards));
in Japanese, a tagger keeps only the words that carry meaning. A language with no such list
keeps every word, which makes this one signal a little less accurate; the reading and
spelling signals are unaffected.

Tags are never translated (`Category::Kept`, `Check::Reading`, `Level::N4`): an Anki search
finds the same cards whatever the language of the cards.

### The batch sharing a translation

Turquoise also covers the opposite of a duplicate, which is more frequent: two different
words with the same translation. You flag 勤労 because `Work` already leads to 仕事, and the
AI rightly answers that they are different words. They still have to be told apart, since
they ask the same question on the `Production` front.

So the flag extends to the **batch**: every card of the deck with an **identical**
translation (case, spacing and markup aside), the flagged one included. Close translations
do not count: `Work` and `Co-worker` already differ on the front.

With five cards translated `Work`, telling 勤労 from 仕事 without seeing 作業 or 労働 gives
contexts that overlap, so the AI decides the whole batch **in a single call**, which also
costs less than one call per pair. A card that is in the batch only because its translation
is too broad gets the right translation instead, which takes it out of the batch.

The same word twice in the batch is settled **first**: 仕[し]事[ごと] and 仕事[しごと] only
differ by how the furigana are split, and two contexts would invent a difference. Spotting
it costs no AI call (same reading, same spelling), and the menu asks which card to keep;
`later` is always an answer, and the contexts then wait for the next run. The AI can also
report the same word under two spellings (仕事 / しごと): the menu asks the same way, and the
contexts are laid on the next pass.

Once the batch is settled, the turquoise flag comes off all its cards, so the batch is not
paid for again.

```
   ── 5 cards fight over "Work" ──────────
      1. 勤労[きんろう]  (no context)
      2. 仕[し]事[ごと]  (no context)  ! same word twice
      3. 仕事[しごと]  (no context)  ! same word twice
      4. 作業[さぎょう]  (no context)
      5. 労働[ろうどう]  (no context)
```

## Leeches (`--only leech`)

The cards tagged `leech` are sorted by their **current interval** (mature from `ivl >= 21`
days, set with `--mature-ivl`):

- **False leeches** (mature): the card is known. After one confirmation, the tag is removed
  and the cards are unsuspended, in bulk.
- **True leeches** (still hard): the AI rewrites the card to be easier to memorise, and you
  see the change first. A word of two kanji or more also gets kanji help: the meaning of
  each kanji (`学 study + 生 life`), never its components. Another note type goes through
  its `simplify` action. Then the tag is removed, the card unsuspended and **fully reset**
  (interval, reviews and ease: out of "ease hell"). The menu also offers `delete the note`.
  When the AI finds nothing to simplify, it offers to reset the card as it is, to delete the
  note or to skip; a card that even the AI cannot make easier is the first one to delete.

The interval only sorts. A card halfway to maturity (from `ivl 10` with the default
threshold) may be known and just caught by a bad week, so its menu adds `mastered`: the tag
comes off, the card is unsuspended and **nothing else changes** (no rewrite, no reset). Its
figures are on its line:

```
── note 1462 ──────────────────────
   Card: 憧れる - to long for  (ivl 12, 2 lapses)
   Why simpler: the example says nothing of the word
   ...
     a. accept (rewrite + reset)
     m. mastered
     d. delete the note
     s. skip
     q. quit
```

Below that interval, `mastered` and the figures are not shown. `mastered` is also offered
when the AI finds nothing to simplify. `skip` leaves the tag, so the card comes back at every
run; `mastered` settles it and counts with the false leeches in the summary. It is never
automatic: `--yes` rewrites.

`--tag` changes the name of the tag.

## A file of cards (`kotogen rework`)

`kotogen rework` asks the same questions of the cards of a JSON Lines file (the file
`--format json` writes) and writes what the AI proposes for each card into another file,
under the card's `id`. It sends and changes nothing, neither the file it reads nor any deck:
Anki need not be open, or even installed.

```bash
# Every card of the file, made lighter
kotogen rework cards.jsonl --task simplify --output proposals.jsonl

# The Japanese of a few cards written right, readings first
kotogen rework cards.jsonl --task reading --ids to-check.txt
```

`--task` names the question:

- `simplify`: a lighter card (the orange flag);
- `reading`: the Japanese written right, readings first (the blue flag);
- `leech`: the card reworked like a real leech, no field ever emptied; a word of two kanji
  or more also gets the meaning of each (`kanji_help`);
- `derive`: the words and rules the card calls for (the pink flag); those the file holds,
  or that an earlier card of the run called for, are listed apart (`already`).

`--ids` names the cards to work on: a file with one `id` per line (blank lines and `#`
comments skipped). Without it, every vocabulary, grammar, reading and listening card is
worked on; no task covers kanji cards. `--output` names the file written (default:
`<cards>.<task>.jsonl` beside the cards). A file that already exists is refused before any
AI call, the cards file among them: proposals already paid for are never written over.

The file opens on a header line: `"format": "kotogen-proposals"`, the task, the file of
cards, then, as in a [file of cards](global-options.md#json-lines-output), the language of
the cards, the kotogen release, the model and the time. Then comes one line per card,
written as the run goes:

```json
{"id": "vocab:涼しい:すずしい", "kind": "vocab", "fields": {"Translation": "Cool"}, "add_tags": [], "remove_tags": [], "reason": "one sense"}
```

`fields` holds only the fields that change, empty when the AI finds nothing to change. A line
may also carry `refused` (what was turned down of the answer, and why), `category` (a word
that is not vocabulary) or `kanji_help`; a `derive` line carries `derive` and `already`
instead of the fields. A card whose AI call failed carries `error`, and the run goes on.

---

[Documentation index](../README.md#documentation)
