# Kanji (`kotogen kanji`)

One card per kanji: its meaning, its readings, and words that carry each of them, taken
from your own vocabulary first. As far as possible, the words on the card are words the
deck already holds.

```bash
# One kanji, several, or the kanji of a word
kotogen kanji 学
kotogen kanji "学 語 読"
kotogen kanji 学生                     # a card for 学 and one for 生

# A kanji named without being written: the model says which one
kotogen kanji gaku

# The kanji of your vocabulary that have no card yet
kotogen kanji deck
kotogen kanji deck --level N4 --count 30

# The kanji of a JLPT level the deck does not hold yet
kotogen kanji jlpt --level N5

# The kanji of a page or of a text file
kotogen kanji https://ja.wikipedia.org/wiki/寿司
kotogen kanji --file lesson3.txt
```

## Options

| Option | Effect |
|---|---|
| `--file FILE`, `-f` | A text file whose kanji to make cards for - a list or a running text alike |
| `--count N`, `-n` | `deck`, `jlpt`, a page or a file: how many kanji at most, the easiest first (default: 20) |
| `--level N4`, `-l` | `deck`, `jlpt`, a page or a file: that level only (default: `auto`, every level, easiest first) |
| `--force` | Make cards even for the kanji that already have one (dropped by default, before any call) |
| `--batch-size N` | Kanji per request to the AI (default: 8) |
| `--jobs N`, `-j` | Batches generated in parallel (default: 4; `1` = one at a time) |

The options shared by every command (`--send`, `--output`, `--model`...) are in
[Global options](global-options.md). The card itself, its fields and its appearance
settings are described in [Card templates](card-templates.md).

## What comes from where

The facts on a card never come from the model. They are read from tables shipped with
kotogen (`src/kotogen/data/`, each saying at its head how it was made):

| Fact | Source |
|---|---|
| The readings, and which of them are rare | The official Joyo kanji table (常用漢字表, 2010) |
| The words read as a whole (今日 is きょう), in `Notes` when your deck holds them | Its appendix (付表) |
| The JLPT level | A consensus table of the Joyo kanji |
| The number of strokes | A consensus table, counted the Japanese way and in the forms of the 2010 table |

The model writes what no table holds: the meaning in the language of the cards, the words
when your deck has none for a reading, what the kanji is made of, what it is mistaken for,
and three kanji close in shape. It is given the facts of each kanji, and its answer is
checked against them:

- **A word must carry one of the kanji's readings.** 学校 (がっこう) carries ガク: the sound
  changes of a reading inside a word are allowed for. A word labelled with the wrong reading
  is filed under the one it carries when that is clear, and left out otherwise. A word that
  carries none of the common readings the table gives is left out.
- **A word read as a whole illustrates nothing** (今日 for 今): it is left out.
- **The readings shown are the ones the words carry.** The other common readings go into
  `OtherReadings`, which the card leaves out unless `kanji.other-readings` says otherwise
  (生 has twelve common readings). The readings the table sets back as special or rare are
  on no card.
- **A decoy may not make a real word.** 先 in place of 学 in 学生 reads 先生: a decoy that
  makes a word of the JLPT vocabulary table or of your deck is left out, or the card that
  will ask you to pick the kanji among four would have two right answers.
- **Composition and look-alikes stay short, and name a kanji.** Past 80 characters they are
  left out, and so is one that names no other kanji or component: "a single horizontal
  stroke" only describes the drawing already on the card.
- **The notes are the words read as a whole that you have met**: the words of the appendix
  written with the kanji and present in your vocabulary deck, three at most, the easiest
  first. 今日[きょう] goes on the card of 今 once 今日 is in your deck, not before. The model
  writes nothing there.

What is left out of a card that still stands (a word, a field) is left out silently. A card
with no word left is not written, and the run says why.

## Your words first

For each kanji, the model receives up to eight words of your vocabulary deck written with
it, the easiest first and taken in turn from each of its readings, and picks among them
before looking for others. With Anki closed, the words come from the copy of the deck kept
at its last reading, without their translations: the model then translates them.

## Which kanji

What goes to the model is decided before any call:

- **A kanji you type** is made even when no table lists it. One outside the Joyo table (鞄)
  has no readings in the tables: the model gives them, and the card is tagged
  `Check::Reading` so that you can find it again.
- **`deck`, `jlpt`, a page or a file** only take kanji of the Joyo table, since a page also
  carries kanji used in names (伊, 翔) and rare kanji with their furigana. The easiest level
  comes first; for `deck`, within a level, the kanji written in the most of your words come
  first, as their card links the most words. A PDF is refused: give its text, a page or the
  kanji themselves.
- **A kanji that already has a card** is dropped before the call (`--force` to make it
  again). `jlpt` needs to know which ones: Anki open, or a copy of the deck.

Every Joyo kanji has a level. The JLPT has published no official list since 2010, so the
levels are a consensus: each level holds at most its usual share of the 100 / 300 / 650 /
1,000 kanji the levels are said to ask for, and N1 holds the rest of the table. A kanji
outside the table carries no `Level::` tag, and is not dropped for that.

## Cost

One call per batch of 8 kanji, whatever the source: choosing the kanji, reading their facts
and checking the answer cost nothing. `--count` caps the cost of a whole level or of your
whole vocabulary, and running the command again takes the next ones.
