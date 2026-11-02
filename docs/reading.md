# Reading (`kotogen reading`)

Reading comprehension cards from a Japanese text: an NHK Easy article, a web page or a text
file, a PDF document, a Tadoku book, a work of the 青空文庫, a 読解 booklet of the official
past papers, a lesson of the いろどり textbook, or a text written on what your deck is
learning.

The `Text` field holds the whole text with its furigana: the site's own for NHK Easy and for
web pages that carry `<ruby>`, the model's for a PDF, MeCab's for the rest. MeCab also fills
in the readings the others leave out. By default the card hides the furigana, and the ふ
button shows them (`reading.furigana`).

The model writes the questions in the language of the cards (`all.lang`, see
[The language of the cards](card-templates.md#the-language-of-the-cards)), each with four
choices, along with a line-by-line translation of the text and the line that supports each
answer. A mini-book card shows the pages as pictures in its `Images` field and leaves `Text`
empty. A card made from a composite document (a poster, a timetable) has both: the picture on
the front, its transcript on the back.

The right answer is stored only in the `Answer` field, the wrong ones in `Decoy1` to
`Decoy3`, and the card mixes them on display. By default the order changes every review day,
so that you cannot learn the letter instead of the answer (`reading.order`). The back circles
the right choice in place; when the card shows no choices, the back writes the answer out in
full.

Clicking or tapping a choice highlights it until you pick another, and a second click clears
it. The highlight only helps you think: nothing is recorded, and the back circles only the
right answer. Listening cards work the same way.

## What the back teaches: the translation and the key line

The back annotates the text of the front with two more fields:

- `Translation`: the translation of the text, line by line. The 訳 button, beside the ふ in
  the top right corner, shows each line of it in small print under its Japanese line. It is
  off when the back opens, so that you read the Japanese again first, and it is switched on
  card by card (`reading.translation` changes this).
- `KeyLine`: the number of the line that supports the answer. The back marks that line with a
  green rule on its left (`reading.key-line`).

Both come from the call that writes the questions, at no extra cost. A translation whose line
count does not match the text is dropped, since a shifted translation would pair the wrong
lines: the run says so, and the cards are marked for proofreading (`Check::Translation`, see
[Cards to proofread](global-options.md#cards-to-proofread)).

The key line is a field rather than a mark in the text, as on the listening card (see
[Listening](listening.md)): the text is on the front, and a mark in it would show where to
look before you have read it.

A mini-book card has neither field: it does not carry the text, and the model is not asked
for a translation. It has `KeyPage` instead, the page the answer is read on: the back opens
the book at that page, and the page counter stays marked until you turn the page. The arrows,
jumps and zoom work as usual. When `KeyPage` is empty, the back opens at the first page.

`KeyPage` costs no extra call either: the transcription of the pages groups their lines by
page, so the key line the model gives maps to the page it is printed on. If the
transcription returns a different number of pages than were sent, the map is dropped, since
a shifted map would open the wrong page: the run says so, and the back opens at the first
page.

A composite-document card keeps both fields: the picture is on the front, and the back shows
the transcript under it, with its translation and its key line (see
[Composite documents](#composite-documents-posters-tables-diagrams)).

## How many choices: a setting, not an AI pass

Every card is generated with four choices. How many the card shows is the `reading.choices`
setting of the Templates menu (see [Card templates](card-templates.md#customising-the-cards)),
so you can change it at any time, for the cards already in your deck too, without a new AI
call:

- `four` (default): the full multiple-choice question;
- `two`: the right answer and one decoy, picked with the same seed as the order;
- `none`: every question is answered from memory;
- `alternate`: the odd-numbered cards of a text show their choices, the even-numbered ones are
  answered from memory (the number is read from the `ID`).

The setting is a maximum. A card with an empty `Decoy1` is always answered from memory. The
model is told to give three decoys or to drop the question, so such a card is a defect: it is
kept, since its answer is complete, and the run reports it on a `!` line. Only a new
generation can give it choices. A card that comes back with one or two decoys shows at most
two or three choices, and the run reports that too.

Because a card may show no choices, the model is told to write every answer as a short
sentence you can give from memory, and never to ask a pure recognition question ("Which of
these statements is true?").

```bash
kotogen reading nhk                # the 4 latest articles not handled yet
kotogen reading nhk --latest 2 --count 4   # at most 4 questions per article
kotogen reading https://news.web.nhk/news/easy/ne2024XXXX/ne2024XXXX.html --send

# A PDF document: read as text or as a mini-book depending on what its pages carry
# (--texts bounds the texts extracted from a course or past papers; all by default)
kotogen reading textbook.pdf
kotogen reading past_papers_n4.pdf --texts 2 --send

# The official JLPT past papers: the 読解 booklet of a level
kotogen reading jlpt-n3 --send

# A work of the 青空文庫: running the command again moves forward in the text
kotogen reading https://www.aozora.gr.jp/cards/000329/card4801.html
```

Every card gets a `Level::NX` tag: the JLPT level the model estimates for the text, or the
one given with `--level`. A [web page or a text file](sources.md) is read the same way as an
article.

In [interactive mode](interactive.md), **An article > NHK News Web Easy** asks which article:
press Enter for the latest ones (the `nhk` keyword; the number of articles is asked next), or
paste the address of one article.

## Running again on a text already handled (the `ID` field)

The `ID` is the first field of the note type, which Anki uses to detect duplicates. After
`RC_`, it has three parts: a name drawn from the source, a fingerprint of the material read
(the `Text` field, or the `Images` field when the card has pictures) and the rank of the card
in that text: `RC_ginga_9ee5c28f_001`, `RC_news_web_nhk_ne2024XXXX_9ee5c28f_001`. The name
only helps you recognise the source in Anki's browser or in the TSV; the fingerprint makes
the ID unique.

Running the command again on the same text therefore gives the same IDs. With `--send`, Anki
refuses the cards the deck already has, and the final summary counts them as "duplicates
ignored". Asking for more cards on a text already handled (`--count 6` after a first run at 3)
adds only the cards ranked 4 to 6. The model does not see the questions of the first run, so
a new card may repeat an old question.

The fingerprint covers the text as the card stores it. An NHK Easy article, a web page or a
text file gives the same text on every run, as long as the source does not change. A PDF read
as text is transcribed by the model, and a transcription that differs from one run to the
next gives new IDs. The page images of a mini-book are named after a fingerprint of the PDF
and their page number in it, so the same pages of the same PDF give the same IDs, and two
page ranges of it give different ones.

## Where the text comes from (the `Source` field)

The `Source` field, in small print at the bottom of the back, says where the text comes from:

- an address (an NHK Easy article, a web page, a PDF given by URL, or the record page of a
  Tadoku book rather than its PDF), which the card turns into a link;
- the name of a local file or folder, with the page range when one was asked for:
  `past_papers_n4.pdf (p. 12-14)`;
- the collection and level of the official past papers, or the volume and lesson of いろどり.

`reading.source=no` hides it. `kotogen deck install` adds this field to a note type that lacks
it (see [Card templates](card-templates.md)); existing notes keep it empty.

## Options

| Option | Effect |
|---|---|
| `--count N`, `-n` | **Maximum** number of questions per article, per text or per passage, or `auto` (default) |
| `--texts N` | PDF: maximum number of reading texts extracted (default: all). `deck`: how many texts to write (default: 1) |
| `--shape story\|exam` | `deck`: a story from everyday life, or a text shaped like the JLPT reading section (default: `story`) |
| `--length short\|medium\|long` | `deck`: the 短文, 中文 or 長文 of the level (default: `short`) |
| `--passages N` | Long text: maximum number of passages handled in one run (default: 6); running the command again takes the next ones |
| `--from-passage N` | Long text: start at passage N instead of where you left off, ignoring the history (the counterpart of `--episode`) |
| `--latest N` | `nhk` keyword: number of recent articles handled (default: 4) |
| `--level N4`, `-l` | JLPT level (default: `auto`, estimated) |
| `--read-as auto\|text\|book` | PDF: how to read it (default: `auto`, decided from the pages) |
| `--pages RANGE` | PDF or pictures: pages kept (`3-18`, `12-`, `7` for a single one, or a list such as `1,4,7-9`); default: all |

The options shared by every command (`--send`, `--output`, `--model`...) are in
[Global options](global-options.md).

## A text written on the deck (`deck`)

`deck` has the model write a text around what your deck is learning, then makes reading cards
from it as from any other text.

```bash
kotogen reading deck                                   # one short story
kotogen reading deck --shape exam --length medium      # a 中文 shaped like the JLPT
kotogen reading deck --texts 3 --level N3 --send
```

**What it is written around.** Three to eight vocabulary words (about one per 60 characters
of text) and up to one grammar point (two for a `medium` or `long` text), taken from your
vocabulary and grammar cards in this order: leeches first (cards tagged `leech`), then young
cards (already studied, interval under 21 days), then the rest. Within each group, the
targets never used in a text come first, then those whose last text is the oldest, so that
two runs do not write around the same words; two texts of one run never share a target.
This history is kept with the others, under the source `deck`, and the settings screen
forgets it the same way. With Anki closed, intervals are unknown: the targets come from the
whole deck, leeches still first, and the run says so.

**At which level.** With `--level auto` (the default), each text is written at the JLPT level
most of its targets carry, N4 when none has one. With `--level N3`, the text is at N3, and
the words and grammar points above N3 wait for a later text without losing their place in
the order. The deck must hold vocabulary cards at that level or below. The level is also what
the text is measured against (below): at N2, every word of the N3 list and below counts as
known.

**How long.** The lengths follow the official JLPT guide for the level: `short` is the 短文
(80 characters at N5, 150 to 200 from N4 up), `medium` the 中文 (250 to 500), `long` the 長文
(550 at N3, 900 at N2, 1,000 at N1). N5 and N4 have no 長文, so `long` gives their 中文. A
text written on the deck is never cut into passages.

**What shape.** `story` is a story or a dialogue from everyday life. `exam` follows the
reading section of the JLPT: a notice, an e-mail or a note for a `short` text, an essay or an
opinion piece for a longer one. Neither writes a 情報検索 document (a timetable, a poster):
that exercise depends on its layout, and is read as a picture (see
[Composite documents](#composite-documents-posters-tables-diagrams)).

### Measured, not taken at its word

Before any question is paid for, the text is measured. MeCab splits it into words, and each
content word (noun, verb, adjective, adverb) is checked against what the learner knows.
Particles, proper nouns, numerals, grammar words such as the こと of ことができる, and the
verbs する, ある, いる, なる and できる are not counted. A word is known if it is in the deck or
in the JLPT list of a level below the text: at N4, 食べる (an N5 word) counts as known without
a card, and the N4 words are where the text may bring new ones. A compound the deck holds is
recognised even where MeCab splits it (日本 + 語 is 日本語).

The text must reach 95% known words, counted in occurrences. Below that, the model rewrites
it once, given the words to replace and the targets it left out, and the rewrite is kept
unless its coverage is lower. A text still under 95% is kept: the run says so on a `!!` line,
and its cards are marked for proofreading (`Check::Coverage`, see
[Cards to proofread](global-options.md#cards-to-proofread)).

That makes two calls per text, three with a rewrite: the text, then the questions. Asking for
both at once would pay for a translation and questions about every text that gets rewritten.

The `Source` field of such a card reads `Kotogen - written on the deck (N4, story, 短文)`:
the level, the shape and the length. What follows `Kotogen` is in the language of the cards
(`all.lang`); `Kotogen` itself is never translated, so that the program recognises the field
on a deck in any language.

## A long text is cut into passages

A reading card shows its whole text on the front, and all its questions draw on that text.
That suits an NHK Easy article (180 to 240 Japanese characters), not a chapter or a long web
page.

A text over 400 Japanese characters (furigana and punctuation not counted) is therefore cut
into passages of about 240 characters, the size of an NHK Easy article. Each passage becomes
the text of its own cards, with its own questions and its own cap (see `--count` below). The
title of the text opens every passage, so that a passage from the middle of a chapter still
says what it belongs to. A text of 400 characters or less is not cut: NHK Easy articles,
short web pages and most texts of past papers.

The cut falls between lines, which are already units of meaning (a paragraph of a web page, a
sentence of an article, a line of dialogue of a subtitle file). A line longer than a passage
is first split into sentences; a sentence is never cut. A last passage under 120 characters
joins the one before. The cut depends only on the text, so two runs on the same source give
the same passages and the same IDs.

Each passage costs one AI call, so one run handles at most 6 passages of a text. The line
before the calls says how many:

```
   Long text: passages 1 to 4 of 4, one call per passage
   Generating the cards (passage 1/4)… (7 cards)
```

`--passages N` raises or lowers that cap. When a text has more passages than the cap, the run
takes the first ones not handled yet and says so on a `!` line (see the next section).

The `Source` field of each card says which passage it comes from, in the language of the
cards (`all.lang`): `chapter.txt (passage 2/4)`.

## Resuming a long work where you left off

Running the command again on the same web page, text file or 青空文庫 work takes the next
passages: the history (`~/.kotogen/seen.json`) keeps one entry per work, with the passages
that gave cards. A first run on a work of 19 passages, then a second:

```
[1/1] ごん狐 - 新美 南吉
   Loading the page… (ごん狐 - 61 lines of Japanese)
   ! Long text: passages 1 to 6 of 19 (--passages to take more, replay for the next batch)
```

```
[1/1] ごん狐 - 新美 南吉
   Loading the page… (ごん狐 - 61 lines of Japanese)
   ! Long text: passages 7 to 12 of 19, 6 already handled (--passages to take more, replay for the next batch)
```

`--from-passage N` starts at passage N and ignores the history, like `--episode` for a
podcast: it is how you redo a passage, and `--from-passage 1` reads a work again from the
start. A long text inside a PDF has no history: each run starts again at its first passage,
and `--from-passage` is the way to move on. Its `!` line names the passage to start from:
`(--passages to take more, --from-passage 7 for the next batch)`.

```bash
kotogen reading chapter.txt --from-passage 1        # start again at the beginning
kotogen reading chapter.txt --from-passage 12       # from the twelfth passage on
kotogen reading chapter.txt --passages 12     # twelve passages in one go instead of six
```

### What the cursor remembers: the material, not the rank

The history keeps a fingerprint of each passage rather than its number, since a number shifts
when the text gains or loses a line. An unchanged passage stays handled, a changed passage
comes back, and a text rewritten entirely is read again from the start. A text short enough
for one card has no cursor.

A passage is recorded only once it gave cards: a passage that failed (no answer from the
model, a network error) comes back on the next run.

Forgetting the work in the settings screen of the assistant (see
[The settings](interactive.md#the-settings)) starts it again at its first passage.

### The whole text is read, never truncated

`vocab` reads at most 150 lines and 8,000 characters of a web page or a text file, because it
sends the whole text in one call (see [Sources](sources.md)). `reading` pays one call per
passage, so it reads the whole text, cuts it, and sends only the passages of the run:
`--passages` sets what a run costs.

## How many questions? (`--count`)

`--count` is a maximum, not a target: the model stops when the text supports no further
question on a different part of it, so a three-line text may give a single card.

With `--count auto` (the default), the cap comes from the length of the text, or of the
passage when the text is cut: one question per 30 Japanese characters, between 4 and 24. An
NHK Easy article (180 to 240 characters) gets 6 to 8. A mini-book gets at least one question
per 2 pages, so that an album with many pages and little text is not underrated.

These caps are set above what a text usually supports: they only stop a runaway answer, and
below them the model decides. They are computed locally, without an AI call. If the model
returns more cards than the cap, the extra ones are dropped and the run says so.

## As a mini-book: the pages themselves

A mini-book card shows pages as pictures, one per page in the `Images` field, with page
turns, zoom and full screen. The pages of a PDF are rendered once, at generation, as JPEG
files at most 1400 px wide (about 150 KB a page), since no Anki client shows a PDF reliably.
The pictures travel with the cards like audio files: into the media library with `--send`,
listed for you to copy otherwise.

The model reads the kept pages once, to transcribe the Japanese it writes the questions from;
only the range asked for is sent. The transcription is not stored: the card shows the pages,
and `Text` stays empty.

In full screen, the question and the page bar can be hidden to leave only the page. On a
touch screen, a tap shows or hides them. With a mouse, where a click zooms, they hide after
three seconds without activity, along with the pointer; moving the mouse, clicking,
scrolling or pressing a key brings them back.

**The document decides.** The same command reads a manga as a mini-book and a course as
text, from what its pages carry:

```bash
# An illustrated album = one reading, whose questions bear on the whole story
kotogen reading tadoku_kaeru.pdf

# A course or past papers: the reading texts are extracted from it, each with its own cards
kotogen reading past_papers_n4.pdf

# --pages keeps what is the reading: neither cover nor colophon
kotogen reading tadoku_kaeru.pdf --pages 3-18

# A single page shown as a picture (a reading exercise from a past paper): the card
# puts away the arrows and the counter by itself, and keeps only the zoom and full screen
kotogen reading past_papers_n4.pdf --pages 12 --read-as book

# Pages already as pictures, in the order of their names
kotogen reading ./book_pages --count 8
```

### How the decision is made

A web page or a text file is read as text, and a folder of pictures or a Tadoku book always
as a mini-book. A PDF is measured locally, at no cost, on up to 12 pages spread over the range
kept: how much of each page its images cover, and how many Japanese characters its text layer
holds.

| What is read on the pages | Reading | Why |
|---|---|---|
| Images cover under 60% of the page | text | A course, a past paper, an article: laid-out text |
| Images cover 60% or more, under 250 Japanese characters a page | mini-book | Manga, album, Tadoku book: the pictures tell the story |
| Images cover 60% or more, 250 Japanese characters a page or more | text | A document scanned then OCRed: the layout adds nothing |
| Scanned pages, no text layer | the model decides | A manga page and a photocopied past paper look alike |

In the last case the decision costs nothing extra: the call that transcribes the document
also says how to read it. A single scanned page goes straight to a mini-book.

The run shows the measurement and its decision, and `--read-as text|book` overrides it:

```bash
kotogen reading manga.pdf --read-as text   # the speech bubbles only, without the pages
kotogen reading course.pdf --read-as book  # the page as it is, layout included
```

## Composite documents: posters, tables, diagrams

The JLPT's 情報検索 asks its questions about a poster, a table, a timetable or a route
diagram. There the layout is the exercise: flattened into text, it loses which price goes
with which time, or where an arrow starts.

In a PDF read as text, such a document becomes a picture card, with no extra AI call:

- the model that transcribes the booklet also says which of its texts are composite
  documents;
- the page the document is printed on is found locally, by matching the transcript against
  the text layer of each page (the page numbers the model gives are off by one on the
  official booklets, so they are not used);
- the document is cut out along its frame, without the item number or the questions around
  it, and the picture goes into the media library with the cards.

The card shows the picture on the front and the transcript on the back, with its
line-by-line translation and its key line.

**A document that cannot be found gives no picture.** A document printed as an image in the
booklet, such as a handwritten memo, has nothing in the text layer to match: the run says its
page was not found, and the card is made as text. A scanned booklet, with no text layer at
all, gives no picture either. A card showing the poster of another exercise would be worse
than a card with no picture.

```bash
# 問題6 (情報検索) of a past-paper booklet gives a card on its poster
kotogen reading N4R.pdf
```

### Tadoku's free books, without going through the download

[にほんごたどく](https://tadoku.org/japanese/free-books/) publishes graded readers in
Japanese, free to download. Give the URL of a book's record page: the PDF is downloaded,
rendered as pages and read as a mini-book.

```bash
kotogen reading https://tadoku.org/japanese/book/6346/ --send
kotogen reading https://tadoku.org/japanese/book/6346/ --pages 3-  # without the cover
```

In [interactive mode](interactive.md), **A book > Tadoku** opens the site's catalogue, by
level:

```
Free books from Tadoku - which level? (141 books, free to download)
    1.        Start    19 books
    2.        Level 0  37 books
    3. N5     Level 1  25 books
    4. N4     Level 2  18 books
    5. N3     Level 3  27 books
    6. N3-N2  Level 4  11 books
    7. N2-N1  Level 5   4 books

    8. Another book (paste the URL of its record)
```

In a level, tick books with Space and start with Enter. Ticks survive turning the page
(PgUp/PgDn, or `n` and `p` in numbered input) and searching the list (see
[Searchable lists](interactive.md#searchable-lists)). Several books make several readings in
one command, each with its own cards and pages; with more than one book, the assistant does
not ask for a page range.

A book that gave cards is recorded in the [source history](interactive.md#the-settings)
(`~/.kotogen/seen.json`). The catalogue then marks it `(already handled)`, and the line of
its level counts the books handled:

```
Free books from Tadoku - which level? (141 books, free to download)
    5. N3     Level 3  27 books, 3 already handled

Level 3 (N3) - 27 books
    1. [ ] くるみもち (already handled)
    2. [ ] 色の世界
```

The deck is checked too, so a book handled on another computer is marked as well (see
[The deck, a second memory](interactive.md#the-deck-a-second-memory)). A handled book stays
in the list and can be ticked again, for other pages or other questions. To clear the marks,
forget the **Free books (Tadoku)** source in the settings screen.

The JLPT level on the left is the one [Tadoku gives](https://tadoku.org/japanese/levels/) for
each of its levels. Start and Level 0 are below N5 and have none.

The list is read from the site and kept on disk for a month. Offline, the last list read is
used; if there is none, the assistant asks for the URL of a book's record.

The command also:

- takes the right PDF: a record offers two, the e-book in reading order and a version imposed
  for printing, and the e-book is the one used;
- does not measure the pages: a Tadoku book is always read as a mini-book, while any other
  PDF given by URL is measured like a local file;
- downloads a book once: the PDF is kept in the cache under the name of its site and its own
  name, which includes its version, so another run on the same book (with another page range,
  say) does not download it again, a new version of the book is downloaded afresh, and two
  sites serving a `sample.pdf` keep one each.

A book for sale has no PDF on its record: the command says so and skips it. Give the URL of a
book's record (`tadoku.org/japanese/book/...`), not the URL of the list. These books are under
a CC BY-NC-ND licence: keep them, and the cards you make from them, for personal use.

## Official JLPT past papers

[jlpt.jp](https://www.jlpt.jp/samples/sampleindex.html) publishes three free sample
collections: the 問題例集 of 2009 and the 公式問題集 of 2012 and 2018. The 読解 booklet of a
level is downloaded and read like a local PDF.

```bash
kotogen reading jlpt-n3            # the 読解 texts of the 2018 collection, level N3
kotogen reading jlpt2012-n2 --send
kotogen reading jlpt-n4 --texts 2
```

The level is part of the alias: `jlpt-n3`, not `jlpt --level N3` (`--level` sets the level of
the cards). The collections are `jlpt-nX` (2018), `jlpt2012-nX` and `jlpt2009-nX`; the 2009
booklet holds the whole exam, vocabulary and grammar included. `jlpt` alone lists the
aliases.

A booklet that gave cards is recorded in the history, and the assistant's menu marks it as
already handled for its level, from the local history and from the deck (see
[The deck, a second memory](interactive.md#the-deck-a-second-memory)). The 聴解 sections of
the same collections are a listening source (see
[Listening](listening.md#official-jlpt-past-papers)).

## 青空文庫, the public domain as a catalogue

A work of the 青空文庫 is a web page: it is read like any page, with its original `<ruby>`
furigana, and a long work is followed passage by passage (see
[Resuming a long work](#resuming-a-long-work-where-you-left-off)). The assistant also offers
the collection as a catalogue.

In [interactive mode](interactive.md), **A book > 青空文庫** opens the collection in three
steps: a shelf, an author, then the works you tick.

```
青空文庫 - what to read? (10,634 works in modern spelling)
    1. N3-N2  Children  (1,169 works) - tales and stories for children
    2. N1     Literature  (9,465 works) - novels, short stories and essays

    3. Search by title or by author
```

**Search by title or by author** opens the whole library as one list, searched as you type
(in Japanese, or in rōmaji for what is written in kana), one `title - author` per line. The
children's shelf comes first, and each line starts with the level of its shelf.

```bash
kotogen reading https://www.aozora.gr.jp/cards/000329/card4801.html   # a book card
kotogen reading https://www.aozora.gr.jp/cards/000329/files/4801_14954.html
```

The address of a **book card** (`.../card4801.html`, the page the site links to) is turned
into the address of the page that carries the text, through the index or by reading the
card.

### Three filters at the entrance, one of which is advice

The catalogue keeps only works in the public domain (`作品著作権フラグ` is `なし`), and applies
three more filters:

- **新字新仮名 only.** The other three spellings of the collection (新字旧仮名, 旧字旧仮名,
  旧字新仮名) predate the 1946 reform (けふ for きょう, 舊 for 旧), and a learner has no way to
  notice them. Without them, the collection still holds about ten thousand works.
- **The "著者" role only**, so that a translation does not appear a second time under the name
  of its translator.
- **A published XHTML page**, the only format that carries the furigana as `<ruby>`. The text
  files write their readings as 漢字《かんじ》, a notation the text route does not read and
  that would land on the card as it is.

### The children's shelf is the one worth most here

About 1,100 works are classed `NDC K...`, the class of children's books: short, in modern
spelling, with simple syntax, by authors such as 小川未明, 宮沢賢治 and 楠山正雄. They cover the
N3-N2 step, where Tadoku has only a few dozen titles.

The rest of the collection is adult literature from 1900 to 1940, at N1. The level belongs to
the shelf, not to each work: the index gives none for a single work.

Authors are listed from the most prolific to the least, since 多読 works best when you stay
with one author. A work that gave cards is marked `(already handled)` and stays tickable, like
a Tadoku book; the mark comes from the local history and from the deck (see
[The deck, a second memory](interactive.md#the-deck-a-second-memory)).

The index comes from the file the site publishes for that purpose
(`list_person_all_extended_utf8.zip`, about two megabytes) and is kept on disk for a month.
Offline, the last index read is used; if there is none, the assistant asks for the address of
a work.

## いろどり, the lesson as a PDF

The Japan Foundation's free textbook is also a listening source (see
[Listening](listening.md#いろどり-the-japan-foundations-free-textbook)). Each lesson has a PDF
with its dialogues and texts, which `reading` reads like a local PDF.

```bash
kotogen reading irodori-shokyu2       # the next lesson of the 初級2 volume
kotogen reading irodori-shochukyu --send
```

Each run takes the next lesson of the volume not yet handled in reading. The history is kept
per command, so a lesson done in listening is still to do in reading; the deck is checked as
well (see [The deck, a second memory](interactive.md#the-deck-a-second-memory)). The volumes
are `irodori-nyumon`, `irodori-shokyu1`, `irodori-shokyu2` and `irodori-shochukyu`;
`irodori` alone lists them.

## A press article

In [interactive mode](interactive.md), **An article** lists NHK Easy and a catalogue of
Japanese news sites on one screen, by level then by genre:

```
An article - from which site? (from easy Japanese to native Japanese)
    1. N5-N4  News      NHK News Web Easy
    2. N2-N1  News      時事通信 - jiji.com
    3. N2-N1  Society   nippon.com - Japan seen from the inside
    4. N2-N1  Science   GIGAZINE - science and curiosities
    5. N2-N1  Tech      Impress Watch - essays and columns
    6. N2-N1  Tech      ITmedia NEWS
    7. N2-N1  Practical ライフハッカー・ジャパン - everyday life

    8. Another site (paste the URL of its RSS feed)
```

A site then shows its 15 most recent articles, with their dates. Tick the ones you want: each
is read as a web page. If the feed gives nothing, the assistant asks for the URL of an
article.

These sites write for Japanese adults, at N2-N1: NHK Easy covers the beginner levels, Tadoku
the middle ones, and these sites the step after. A site is listed only if its articles can be
extracted cleanly without a browser; NHK News Web (the main site, not NHK Easy) builds its
articles in JavaScript and gives nothing back.

The list is a shortcut: **Another site** takes the URL of any RSS feed. To add a site for
good, or to correct a feed that moved, write it in `press.json` in the data folder
(`%LOCALAPPDATA%\kotogen\` on Windows, `~/Library/Application Support/kotogen/` on macOS,
`~/.local/share/kotogen/` on Linux):

```json
{
  "asahi": {"name": "朝日新聞", "url": "https://example.test/rss", "genre": "News"}
}
```

Only `url` is required. `name` defaults to the key, and `genre` files the site under a genre
of the menu (News, Society, Science, Tech, Practical; any other comes last). An entry with the
key of a listed site (`jiji`, `nippon`, `gigazine`, `itmedia`, `impress`, `lifehacker`)
replaces it.

### Other free libraries

Other libraries publish free readings, most of them as PDFs. The URL of a PDF works like a
local file: `kotogen reading <url>` downloads it and reads it as text or as a mini-book
according to its pages.

| Library | What you find there |
|---|---|
| [KC よむよむ](https://www.jpf.go.jp/j/kansai/resource/index.html) (Japan Foundation, Kansai) | Readings from A1 to B1, as PDF, several with the audio |
| [読み物いっぱい](http://www17408ui.sakura.ne.jp/tatsum/project/Yomimono/Yomimono-ippai/index.html) | Beginner and intermediate, PDF and audio |
| [多読 日本語学習読本](https://nihongotokuhon.jimdofree.com/) | Portal of easy readings, as PDF |
| [まんがひみつ文庫](https://kids.gakken.co.jp/himitsu/cat_library/) (Gakken) | Documentary manga for children, read online |
| [青空文庫](https://www.aozora.gr.jp/) | Public-domain literature, as HTML with its original furigana |

青空文庫 serves web pages rather than PDFs: they go through the text route, which keeps their
`<ruby>` (see [Sources](sources.md)), and the assistant has its catalogue (see
[above](#青空文庫-the-public-domain-as-a-catalogue)).

Mini-books, `--pages`, the measuring of a PDF and the cutting out of composite documents need
the `pdf` extra (pypdfium2, Pillow, numpy); without it, a PDF can still be read as text. The
program offers to install the extra on its first run (see
[Optional modules](global-options.md#optional-modules)); to install it by hand:

```bash
pip install -e ".[pdf]"
```

> **History per mode**: the record of handled articles (`~/.kotogen/seen.json`) is kept per
> command, so an article done in `audio` is still offered by `kotogen reading nhk`. To handle
> an article again, give its URL; to clear a whole source, forget it in the settings screen
> of the assistant (see [The settings](interactive.md#the-settings)).

---

[Documentation index](../README.md#documentation)
