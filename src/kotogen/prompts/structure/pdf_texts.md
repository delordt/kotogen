You spot in a PDF document (Japanese course, JLPT past paper, textbook...) the
JAPANESE READING TEXTS: running passages (article, story, dialogue, e-mail,
notice...) and composed documents (poster, table, timetable, memo...) worth
setting reading comprehension questions on.

## The two natures

Each text kept carries a "kind", and it is the LAYOUT that decides it, never the
subject:

- `"text"`: the reading happens in lines that follow one another. An article, a
  story, a letter, an e-mail, a 作文 - boxed or illustrated all the same: if it
  can be read aloud from beginning to end without losing anything, it is a text.
- `"document"`: the reading happens by LOOKING. A poster, a notice, a table of
  columns, a timetable, a map, a diagram, a leaflet, a handwritten memo.
  Flattened into lines, these documents lose what matters: which value goes with
  which column, which price with which time, where an arrow starts from. This is
  the JLPT 情報検索 question type.

When hesitating, ask yourself what would be lost by someone hearing nothing but
the text read aloud. If they would lose the answer, it is a `"document"`.

## Rules
- Examine the whole document, scanned texts and texts in image form included.
- Keep only real reading supports: NOT the exam instructions, NOT the lists of
  multiple-choice options, NOT the isolated sentences of vocabulary or grammar
  exercises. A `"text"` holds at least 3 linked sentences; a `"document"` need
  hold none - a timetable has no sentences, and that is exactly why it is read as
  a picture.
- Transcribe each text FAITHFULLY, without simplifying or correcting it. For a
  `"document"`, transcribe what the boxes, the columns and the captions carry as
  well: that transcription will not replace the picture, it goes with it on the
  back of the card, and it serves to find the page the document is printed on.
- Add the furigana: `漢字[かな]` notation, with an ASCII space before each group of
  kanji (e.g. `彼[かれ]は 学校[がっこう]に 行[い]く。`).
- Cut each text into lines: one sentence or one short paragraph per line. In a
  `"document"`, one line per line of the document (a table row, a list entry),
  the cells separated by an ideographic space `　`.
- "title": the title of the passage if the document has one, otherwise a short
  title you write yourself (in simple Japanese, with the same furigana).

{{include:pdf_error_contract}}

If there is NO reading text at all in the document (e.g. a pure vocabulary list),
return `{"error": "no reading text in this document"}`.

## Answer format
ONLY a JSON array, with no text around it:
```json
[{"kind": "text", "title": "山田[やまだ]さんの 手紙[てがみ]", "lines": ["first sentence...", "second..."]},
 {"kind": "document", "title": "「夏[なつ]の 町[まち]まつり」", "lines": ["名前[なまえ]（料金[りょうきん]）　月[つき]・日[ひ]　場所[ばしょ]・時間[じかん]", "① おどりの 会[かい]（300円[えん]）　7/20（土[ど]）　東公園[ひがしこうえん] 10時[じ]〜12時[じ]"]}]
```
