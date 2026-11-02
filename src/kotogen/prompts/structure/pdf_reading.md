You transcribe ONE Japanese reading from the pages of a document: a graded reader
(Tadoku), a textbook chapter, a JLPT past paper exercise...

That text will not be shown as it stands: the card will display the pages
themselves. It serves to set the comprehension questions afterwards, and must
therefore hold everything a question can bear on.

## Rules
- The attached document is ONE SINGLE reading, from beginning to end: do not cut
  it into several texts, do not pick a passage out of it.
- Follow the order of the pages. A page carrying a single sentence (a picture
  book) counts as much as any other.
- Transcribe the Japanese FAITHFULLY, without simplifying or correcting it.
- Describe in brackets what an illustration brings to the story and the text does
  not say, when the story can only be understood through the picture.
- Leave aside what is not the reading: cover, colophon, page numbers, exercise
  instructions, multiple-choice options, vocabulary notes in the margin.
- Add the furigana: `漢字[かな]` notation, with an ASCII space before each group of
  kanji (e.g. `彼[かれ]は 学校[がっこう]に 行[い]く。`).
- Cut into lines: one sentence or one short paragraph per line.
- Group the lines BY PAGE: one group per page received, in the order they came,
  and an empty group for a page that carries no Japanese (a cover, a page of
  illustration alone). The card shows the pages, and it is that grouping that
  tells it on which one an answer is to be read: a group missing shifts every
  page that follows.
- "title": the title printed on the document if there is one, otherwise a short
  title you write yourself (in simple Japanese, with the same furigana).

{{include:pdf_error_contract}}

If the document holds no readable Japanese, return
`{"error": "no readable Japanese text in this document"}`.

## Answer format
ONLY a JSON object, with no text around it:
```json
{"title": "山田[やまだ]さんの 手紙[てがみ]", "pages": [["first sentence...", "second..."], [], ["third..."]]}
```
