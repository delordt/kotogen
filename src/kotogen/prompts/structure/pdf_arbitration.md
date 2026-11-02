You receive the pages of a scanned Japanese document, and you do two things: you
say HOW it is to be read, then you transcribe it accordingly.

## 1. How to read this document
- `book`: the pages themselves carry the reading, and the card will show them.
  Manga, picture book, graded reader (Tadoku), album for young readers: the
  picture tells as much as the text there, and the document forms ONE single
  reading, from beginning to end.
- `text`: only the Japanese counts, the layout brings nothing. Course, JLPT past
  paper, textbook, photocopied article: the document carries one or more
  INDEPENDENT reading passages, surrounded by instructions and exercises.

What settles it is the picture: taken away, a manga can no longer be understood,
a past paper loses nothing. When in doubt, answer `text`.

## 2. What you transcribe
- In `book`: ONE SINGLE text, in the order of the pages. Do not cut it up, do not
  pick a passage. Describe in brackets what an illustration brings to the story
  and the text does not say. Leave aside cover, colophon, page numbers and
  vocabulary notes in the margin. Its lines are handed back GROUPED BY PAGE
  (`pages` key): one group per page received, in the order they came, and an
  empty group for a page carrying no Japanese. The card shows those pages, and
  it is that grouping that tells it on which one an answer is to be read.
- In `text`: one text per reading passage (at least 3 linked sentences). NOT the
  exam instructions, NOT the lists of multiple-choice options, NOT the isolated
  sentences of vocabulary or grammar exercises.

In both cases:
- Transcribe the Japanese FAITHFULLY, without simplifying or correcting it.
- Add the furigana: `漢字[かな]` notation, with an ASCII space before each group of
  kanji (e.g. `彼[かれ]は 学校[がっこう]に 行[い]く。`).
- Cut into lines: one sentence or one short paragraph per line.
- "title": the title printed on the document if there is one, otherwise a short
  title you write yourself (in simple Japanese, with the same furigana).

{{include:pdf_error_contract}}

If there is no readable Japanese at all in the document, return
`{"error": "no readable Japanese text in this document"}`.

## Answer format
ONLY a JSON object, with no text around it. A text carries its `lines` flat, a
book its `pages`:
```json
{"type": "text", "texts": [{"title": "山田[やまだ]さんの 手紙[てがみ]", "lines": ["first sentence...", "second..."]}]}
```
```json
{"type": "book", "texts": [{"title": "山田[やまだ]さんの 手紙[てがみ]", "pages": [["first sentence...", "second..."], [], ["third..."]]}]}
```
