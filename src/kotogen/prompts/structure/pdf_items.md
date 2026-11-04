You receive the question booklet of a JLPT listening paper (聴解). You answer none
of the questions: you draw the MAP of the booklet, page by page.

One thing only is asked of you, and it is a reading: where each item begins, does
it carry an illustration, and which section the page opens.

## Rules

- **Item**: a numbered question of the booklet, whose number is printed in bold at
  the start (`1ばん`, `2番`, `3`...). Number them as they are printed.
- Do NOT confuse the item number with:
  - the **section** number (`もんだい1`, `問題2`) - it opens a group of them, it is
    not an item;
  - the numbers of the **options** (`1` `2` `3` `4` facing the choices);
  - the **page number**, printed on its own in the footer.
- The **example** (`れい`, `例`) is not an item, and is never numbered as one: the
  first item after it is `1ばん`, item 1. List it all the same, where it is
  printed, as `{"example": true, "figure": ...}` with no number: its drawing,
  when it has one, must not be taken for an item's.
- `figure` is `true` if the item carries at least one **drawing** (illustration,
  map, photo, drawn table), `false` if its options are written in words.
- `section` is the number of the section title (`もんだい3`, `問題3`) **printed on
  that page**, and `null` on every other. A section title is not guessed: if it is
  not written on the page, it is `null`.
- Items are listed **from top to bottom** within each page.

## One entry per page, in the order received

`Pages` holds EXACTLY as many entries as the document received has pages, in the
same order. A page with no item keeps its entry, with `"items": []` - a cover, an
instruction, a section title, a page of written options.

The order is what counts and nothing else: write no page number, it would not be
read back.

{{include:pdf_error_contract}}

If the document is not a listening question booklet (no numbered items), return
`{"error": "this document is not a question booklet"}`.

## Answer format

ONLY JSON, with no text around it. The example below describes a five-page
document: a cover, a section title with its drawn example, two pages of items, a
page of written options.

```json
{
  "Pages": [
    {"section": null, "items": []},
    {"section": 1, "items": [{"example": true, "figure": true}]},
    {"section": null, "items": [{"number": 1, "figure": true}, {"number": 2, "figure": true}]},
    {"section": null, "items": [{"number": 3, "figure": true}]},
    {"section": null, "items": [{"number": 4, "figure": false}]}
  ]
}
```
