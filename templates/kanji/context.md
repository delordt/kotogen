# Context

Anki kanji card. It shows a kanji alone on the front; the back gives its meaning, its
readings, and words that use each of them. The words are taken from your vocabulary deck
where possible, so the card links words you already know.

The card content follows the language of the cards (`all.lang`), English by default. The
field and tag names below do not: they are the names of the note type in Anki.

## Fields

- `Kanji`: the character, alone. First field: Anki looks for duplicates on it, one note per
  kanji
- `Meaning`: a keyword, and at most two more senses after a comma (`study, learning`)
- `Onyomi`: the on readings the card's words illustrate, in katakana, separated by `、`
  (`ガク`)
- `Kunyomi`: the kun readings the card's words illustrate, in hiragana, with a dot where the
  okurigana starts (`まな.ぶ`)
- `Words`: two to four words, one per line (`<br>` between them), each written
  `word[furigana]|translation|reading`: `学生[がくせい]|student|ガク`. The reading is the one
  of the kanji this word illustrates, written as in `Onyomi` or `Kunyomi`
- `Strokes`: the number of strokes
- `OtherReadings` (optional): the common readings no word of the card illustrates, on and kun
  mixed. Filled from the tables, never by the model; most kanji have none
- `Composition` (optional): what the kanji is made of, in a few words
  (`⺍ + 冖 + 子 - a child under a roof`). No story, and empty when there is nothing to take
  apart (山, 木)
- `LookAlikes` (optional): the kanji it is mistaken for, and what tells them apart. Empty
  unless the confusion is real
- `Notes` (optional): up to three words read as a whole that are written with the kanji (今日
  read きょう), from the appendix of the Joyo table, never from the model, and only those your
  vocabulary deck holds with that reading
- `Decoy1`, `Decoy2`, `Decoy3`: up to three kanji close in shape, for a card still to come
  that will ask you to pick the kanji among four. Not shown by `Recognition`

For a kanji of the Joyo table, the readings come from the table (`kanji_table`), never from
the model, and the readings the table marks as special or rare are on no card. A kanji
outside the table, which only gets a card when you type it, takes its readings from the
model's words, and its card is tagged `Check::Reading`.

## Tags

- `Level::N5` to `Level::N1`: the JLPT level of the kanji, when the lists place it. A kanji
  the lists leave out carries none
- `Check::Reading`: a kanji outside the Joyo table, whose readings no table checked

## The back

Drawn like the vocabulary card: on the page itself, without boxes. The kanji stays where the
front showed it, so nothing moves when the card turns. Under it the back adds two badges (the
level, read from the tag, and the number of strokes), then its blocks, starting with the
meaning.

Then the readings, in a strip between two rules like the forms of the vocabulary card: a
cell for the on readings and one for the kun readings, with their sign (音, 訓) under them.
The other readings are left out by default; folded, they hang behind 他, a tab on the lower
rule of the strip, and open inside it; shown, they take a row of the strip. On and kun
readings each have their colour (`--on`, `--kun` in the palette of `style.css`), and each
word shows the kanji in the colour of the reading it gives it. Then the words, and the
composition (構成), the look-alikes (≠) and the notes (熟字訓) close the card, in small
print, their signs in one column.

The script at the bottom of `back.html` draws the readings and the words from the fields:
the okurigana after the dot in a lighter tone, the furigana of each word as ruby.

## Settings

All are declared in `src/kotogen/anki/templates.py`, and each removes blocks written in the
template: `kanji.badge`, `kanji.onyomi` (katakana or hiragana), `kanji.other-readings` (`no`,
`folded` or `shown`), `kanji.words` (with or without their translation),
`kanji.word-readings`, `kanji.composition`, `kanji.lookalikes`, `kanji.notes`,
`kanji.tags`. Two of them change what the script draws rather than a block of the page:
they keep or remove a hidden element the script looks for (`kanji-word-readings`,
`kanji-on-in-hiragana`).
