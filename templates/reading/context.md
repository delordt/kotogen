# Context - Active reading deck

Anki cards to practise reading comprehension of Japanese texts. Each text gives several
cards, each with a different kind of question.

The card content follows the language of the cards (`all.lang`), English by default. The
field and tag names below do not: they are the names of the note type in Anki. Only the
text is in Japanese, and the card has no TTS.

## Layout

The card has no colour of its own: it uses the colour of its text, as the vocabulary card
does for a word with no class, and green marks only the answer (the right choice, the key
line, the page of the answer). The question is the title of the card, under a badge with the
level the note is filed under (`Level::N4`, read from the tags; a note with no level shows no
badge, and `reading.badge=no` removes it).

The front shows the question at the top, then the Japanese text, in one of two forms:

- When the `Images` field is filled, the mini-book: a viewer for the images of the pages,
  with page turns, zoom and full screen. The `Text` field is then not shown. It is empty for
  a mini-book, but a composite document (a poster, a table) keeps its transcript there, and
  the back shows it under the picture. With a single picture (a reading exercise, an isolated
  page), the viewer hides its arrows, page jumps and counter, and keeps zoom and full screen.
- Otherwise, the `Text` field, with a "ふ" button in its top right corner that shows the
  furigana. They are hidden at first, so that you read without them
  (`reading.furigana=always` always shows them, `never` never does, `back` shows them on the
  back only). The button sits in a pill that the text flows around, and the pill stays at the
  top of the screen while a long text scrolls.

Then come the choices: the decoys and the `Answer`. The note carries them all, and how many
the card shows is the "Number of choices" setting of the "Templates" menu (`reading.choices`:
four, two, none, or alternate), so changing it does not call the AI again. `alternate` shows
the choices on cards of odd rank and asks the cards of even rank from memory, the rank being
read from the `ID`. A card with an empty `Decoy1` never shows choices.

The choices are **shuffled on display**, not at generation. Both faces compute the same
order from the `ID` and `Question` fields and the review day (which starts at 4 a.m., Anki's
default). The order changes every day, so you remember the answer, not its letter
(`reading.order=fixed` keeps one order). The CSS hides the choices until the script has run,
so a failed script shows no choices rather than the fields in their stored order, answer
last.

The back shows the front, with the right answer **highlighted in place** among the choices.
When the front showed no choices, the back writes the answer out in full in a block under
the text. That block is in the template and the script removes it when the choices show, so
a script that does not run still leaves a back that gives the answer.

The back **annotates the text** rather than copying it: it splits the text of the front into
lines, gives the line that supports the answer (the `KeyLine` field) a green rule on the
left (`reading.key-line=no` removes it), and adds a "訳" button to the pill of the "ふ", in
front of it, which shows the translation in small print under each line, as on the listening
card. The button is off when each card opens, so that you read the Japanese again first
(`reading.translation=at-once` starts it on, `never` removes it).

A mini-book card carries no text, so `Translation` and `KeyLine` are empty. It has the
`KeyPage` field instead: the back **opens the book at the page the answer is read on**
rather than at the first page, and the page counter stays green until you turn the page. A
book whose pages were not told apart during the transcription has `KeyPage` empty and opens
at its first page.

## Fields

- `ID`: unique identifier of the card (`RC_ginga_9ee5c28f_001`), first field of the note
  type, which Anki uses to detect duplicates on import. After `RC_` come a short name of the
  source, to recognise the card at a glance, a fingerprint of the **material read** (the
  `Images` of a mini-book, the `Text` field otherwise) and the rank of the card in that text.
  Running the generator again on the same text gives the same IDs, and Anki skips the cards
  it already has
- `Text`: the original text in Japanese, with the furigana between [] (hidden at first by
  the card). Empty for a mini-book; filled in, and shown on the back only, when the `Images`
  carry a composite document
- `Images`: the images of the pages to read (mini-book), one page per image, in reading
  order. The generator fills it in mini-book mode, from a PDF rendered page by page or from
  image files, and the files go into `collection.media`
- `Question`: the question asked about the text
- `Decoy1`, `Decoy2`, `Decoy3`: three wrong answers (fewer when the model returned fewer).
  When `Decoy1` is empty, the card is answered from memory, whatever the setting
- `Answer`: the expected answer to the question, a short sentence that stands on its own,
  since the back writes it out in full when the card shows no choices. The card shuffles it
  in among the decoys; it is never copied into a decoy field
- `Translation`: the translation of the `Text` field, as plain text, **line by line** with it
  (line break = Shift+Enter in Anki's editor). The back sets it under each Japanese line,
  behind the "訳" button. Empty for a mini-book. When the model's translation does not have
  as many lines as the text, the generator leaves the field empty: a translation shifted by
  one line would read as if it were right
- `KeyLine`: rank (from 1) of the line of the `Text` field that best supports the answer.
  A field of its own, as on the listening card, rather than a marker in the `Text`: the text
  is on the front, and a marker would show where to look. Never shown as such: the back
  highlights the line it designates
- `KeyPage`: rank (from 1) of the page of `Images` the answer is read on, for a mini-book
  only (a card that carries its text points at a line instead). The back opens the book
  there; empty, it opens at the first page. Never shown as such
- `Source`: where the text comes from: the address of an NHK Easy article, of a web page or
  of a Tadoku book (kept whole; the card makes a link of it), or the name of the document,
  with the page range when one was asked for (`past_papers_n4.pdf (p. 12-14)`). A long text
  cut into passages adds the passage the card comes from. Shown in small print at the bottom
  of the back (`reading.source=no` removes it)

## Tags

- `Level::N5`, `Level::N4`, `Level::N3`, `Level::N2`, `Level::N1`

## Examples

- `Text`: 昨日[きのう]、 友達[ともだち]と 一緒[いっしょ]に 新[あたら]しいレストランに 行[い]きました。 料理[りょうり]はとても 美味[おい]しくて、 値段[ねだん]も 安[やす]かったです。
- `Translation`: `Yesterday I went to a new restaurant with a friend. The food was delicious, and it was cheap too.`
- `Question`: `What did this person do yesterday?`
- `Answer`: `They went to a new restaurant with a friend`
- `KeyLine`: 1
- Tags: `Level::N4`

## Usage notes

- **Length of the texts**: a text longer than about 400 Japanese characters is cut into
  passages of about 240 (the length of an NHK Easy article), each the text of its own cards
- **Varied sources**: mix formal and informal registers
- **Progression**: start with N5/N4, then bring in N3 and above gradually
- **Frequency**: 1-2 texts a day at most, to avoid overload
