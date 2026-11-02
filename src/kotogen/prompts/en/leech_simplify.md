You are reworking a Japanese vocabulary card that is a LEECH: the English-speaking learner
fails on it over and over. Rewrite it so that it is EASIER to remember next time, WITHOUT
changing the word or its central meaning.

## Fields (key "fields")
- `Expression`: the word in furigana `漢字[かな]`. Do NOT change it (correct a wrong furigana only).
- `Translation`: English. Keep ONE sense, the commonest, in 1 to 2 words. Drop the secondary
  senses: that is often the source of confusion behind the failure.
- `Context`: fill it in if the word is confused with another of the same translation -
  that is often what the leech is. See the rules below.
- `Notes`: add a SHORT memory hint if useful (a distinctive nuance, a common trap): on a
  leech, that is a reason to write a note. Otherwise empty.
  Do NOT put the help on the kanji here (that goes in "kanji_help").
- `Example` + `ExampleTranslation`: a VERY short, concrete, everyday sentence that anchors the word.
  Replace an example that is too long or too abstract. Both together, or both empty.

## Context, Notes, register

{{include:vocab_fields}}

The field names are the note type's schema: use them exactly as they stand, never
renamed and never translated. What you write under them is English.

## Kanji help (key "kanji_help") - the MEANING of the kanji, nothing else
If the `Expression` is written with SEVERAL kanji, give the meaning of each, in the order of
the word. No sentence, no "story" - a few words: `学 study + 生 life`.
- NEVER break a kanji down into components or radicals: the shape of a kanji is the business
  of its card in the kanji deck, not of the word's.
- The meaning of the KANJI, in one word, not that of the whole word: `生 life`, not "student".
- ONE single kanji (`橋`, `食[た]べる`): `kanji_help` = "". Its meaning is the translation,
  already on the card.
- Kanji chosen for their sound (ateji: `寿司`, `珈琲`): `kanji_help` = "". Their meaning
  would mislead.
- Do NOT repeat the word itself at the start (it is already in the `Expression`): begin
  straight away with the first kanji, with no "漢字 = " prefix.
- Do NOT repeat the meaning or translation of the word (already on the card): no "→ …"
  conclusion.
- NO line of confusion and no "≠ …": the meaning of the kanji only.
**1 short line** (~50 characters). Otherwise `kanji_help` = "".

## Furigana convention
`漢字[かな]` with an ASCII space before each group of kanji (`今日[きょう]は 暑[あつ]い`).

## Card out of category (key "category", optional)
This deck holds **vocabulary** only, and a card that is not vocabulary often explains the
repeated failure. If the `Expression` is not vocabulary, add the key `category`:

- `grammar`: a rule, a bare particle (は, が, を…), a suffix or a turn of phrase (〜ている, 〜たら, 〜ながら).
- `sentence`: a whole sentence or a clause, where a word is expected.
- `fragment`: a piece that is never used on its own (part of a compound word, orphan okurigana).

The three values are the protocol and stay exactly as they are; the `reason` beside them
is written in English, and stays very short.

When in DOUBT, **leave the key out**: a set phrase, a compound word, an onomatopoeia, a
counter, a common proper noun are vocabulary. A word that is merely difficult is not out of
category. This key does not replace the simplification: answer normally as well.

## Answer
ONLY JSON, with no text around it. Include in "fields" only the fields REALLY changed:
```json
{"reason": "what makes the card simpler", "fields": {"Translation": "…"}, "kanji_help": "...",
 "category": {"type": "grammar", "reason": "verb suffix, not a word"}}
```
