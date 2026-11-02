# Context - Grammar deck (cloze sentences)

Anki cards to **review Japanese grammar**: a **Japanese sentence with a gap**, the gap falling
exactly on the **targeted rule**. A **single note type** (a **cloze** note type), one exercise
per card.

The card content follows the language of the cards (`all.lang`), English by default. The
field and tag names below do not: they are the names of the note type in Anki.

The deck is for **working on one rule in depth**: you ask for several cards for one rule
(`--count`, 5 by default) and get as many different situations for it.

The front shows the **register** badge and, under it, the **nuance**, when they decide
something; then the sentence with its gap, the **word to conjugate** in the gap and, under
it, **the part of the translation that renders the gap**; then the input box in `type` mode,
and the **translation**. The back shows the same with the answer in green in the gap, then
the rule: its **name**, the word to conjugate set against the answer (`降る → 降れば`), its
**explanation**, the neighbouring rule last and smaller, its **level** and its **reference
page**, and the tags with `grammar.tags=yes` (off by default). The front does not name the
targeted rule.

---

## Goals

- Practise **producing** a rule in varied contexts (active recall: you form the content of
  the gap in your head, or type it, then reveal it).
- **Accompany** a grammar course taken in parallel: same rules, different sentences.
- Stay JLPT-compatible **without** depending on an official list.

---

## The exercise model (a single one)

A sentence has **a single gap** `{{c1::...}}`. The gap covers the **target grammatical
form**, conjugated or inserted as it appears in the sentence, never vocabulary. The back
reveals it in green, with the translation and the rule. **`Translation`, `Target`, `Hint`,
`Nuance` and the register** together must leave **one natural answer** (accepted variants
are listed in `Explanation`).

### Two ways of answering

The `grammar.answer` setting (in the assistant, the "Templates" menu then "Appearance")
decides how the card asks, without changing what the note contains:

- `recall` (default): you form the gap in your head, then turn the card over.
- `type`: an input box (`{{type:Answer}}`) under the sentence, and the back compares what
  you typed character by character.

Two other settings decide what the **front** gives:

- `grammar.translation`: `at-once` (default), or `on-click`, a 訳 button that shows the
  translation in one touch. **There is no `never`**: the translation is the main clue here,
  and without it the gap could not be worked out. The back always shows it.
- `grammar.furigana`: `always` (default), `back` (none on the front, readings with the
  answer) or `never`. It only touches the `Sentence`: `Hint` and `Explanation` keep their
  readings in all three positions.

---

## Fields (cloze note type `Grammar`)

1. `Sentence`: the sentence with its gap, in cloze format `{{c1::...}}`. A single gap, no
   inline hint (no second `::` in the gap) and **no punctuation inside it**, which would be
   revealed in green on the back and have to be typed. The generator turns every gap into
   `c1`, moves an inline hint to `Hint`, and moves punctuation out of the gap
   (`{{c1::降れば、}}` -> `{{c1::降れば}}、`). First field of the note type: Anki uses it to
   detect duplicates on import (there is no ID field).
2. `Translation`: an idiomatic translation of the whole sentence. **Required**: it is the
   main hint on the front.
3. `Target` *(optional)*: the **exact part** of `Translation` that renders the expected
   Japanese form (`I do my homework while listening to music.` -> `while listening`). The
   card writes it **under the gap** and marks it in the translation, on both faces. Empty
   when no part of the translation renders the rule alone. A target the generator cannot
   find in the translation (case and curly apostrophes aside) is **erased**, with a `!` line.
4. `Hint` *(optional)*: when the gap asks you to conjugate a given word, that word in
   **dictionary form** (answer `食[た]べれば` -> `Hint` `食[た]べる`). Shown **in the gap** on
   the front. On the back, it is set against the answer under the name of the rule
   (`食べる → 食べれば`): what the two share keeps the colour of the text, what the word loses
   fades, what the rule adds is in green. Empty if the gap is a particle or an expression
   inserted as it is.
5. `Nuance` *(optional)*: a short hint at the meaning that does not name the rule
   (`while also… (simultaneity)`, `regret ("I should have")`). Filled in when the translation
   alone would leave several rules plausible.
6. `Rule`: the name of the grammar point, **filled in by the program**, not by the call that
   writes the cards: the name the JLPT table gives the rule (`ば`) or, for a rule the table
   does not know, the name the analysis of the rule returned, with a `〜` when it attaches to
   another word (`〜てください`). It is the name in the tag, and it heads the rule on the
   back.
7. `Explanation`: 2-3 sentences, **always**: what the rule expresses, how it is built, why
   this form here, and a contrast with a neighbouring rule (`≠ 〜たら: …`) when relevant. The
   **first sentence stands on its own**: the back sets it right under the rule and its form.
   The card takes the contrast out of the text and sets it **last**, smaller, after the sign
   ≠.
8. `Answer`: the content of the gap **without its readings or spaces** (`降[ふ]れば` ->
   `降れば`), filled in by the program. It is what you type in `type` mode: `{{type:...}}`
   compares character by character, and nobody types brackets. It is filled in both modes,
   so switching modes does not call the AI again.
9. `URL` *(optional)*: the reference page given with `--url`, shown as its **domain** at the
   bottom of the rule on the back, beside the level.

### Nothing moves when the card turns

The front holds, unseen, the room of the answer in the slot of the gap, and the back holds
the room of the word to conjugate, so the slot is as wide on both faces and the back fills
it without moving a line. An answer too long for the line shrinks with its slot (down to
60%), by the same ratio on both faces; one still too long at 60% wraps inside its slot,
on lines tall enough for the readings of the back. The punctuation after it stays beside
it. The meaning under the gap keeps its room too when the translation waits behind 訳
(`on-click`): the button covers it. As a result, the width of the slot hints at the length
of the answer.

### Furigana convention (Anki format)

- Write the furigana in the `漢字[かな]` form.
- Put **one (half-width ASCII) space** just **before each group of kanji** that carries
  furigana.
  - E.g. `彼[かれ]の 提案[ていあん]は 正解[せいかい]です。`
  - E.g. okurigana: `分[わ]かる`, `食[た]べます`, `読[よ]んでいる`
- Do **not** put a space before a word that has **no** furigana.
- Use **ASCII spaces** only (no full-width spaces, no NBSP).
- Anki's filter takes that space as the start of the group and shows none. In a line of
  Latin prose (an English or French `Explanation`), where a space also has to show before
  the Japanese word, the export doubles it (`condition:  降[ふ]る`): the model writes one.
- The `Sentence` (inside the gap too), `Hint` and `Rule` fields and the Japanese words
  quoted in `Explanation` follow **exactly** the same convention.
- The translated fields (`Translation`, `Target`, `Nuance`) carry none, and neither does
  `Answer`, which is typed rather than read.

#### Do / Don't
- YES `彼[かれ]は 今日[きょう] 学校[がっこう]に 行[い]く。`
- NO `彼[かれ]は今日[きょう]学校[がっこう]に行[い]く。` *(missing spaces)*
- NO `彼 [かれ] は 今日 [きょう] …` *(spaces around the brackets)*

---

## Tags

- **Grammar** (the level, then the name of the rule, without readings):
  `Grammar::N4::ながら` / `Grammar::N3::に対して` / `Grammar::N5::て形＋ください` ...

- **Register** *(optional, only when needed)*:
  The AI returns a `Register` value that the generator turns into a tag, and the card reads
  the tag to show its **badge** on the front. Only when the rule is limited to one register,
  or when the form to produce **depends on** the register. Otherwise **none**: a badge that
  teaches nothing clutters the card.
  - `Register::常体` *(plain)*
  - `Register::丁寧体` *(polite です/ます)*
  - `Register::敬語::尊敬語` *(honorific)*
  - `Register::敬語::謙譲語` *(humble)*

> No other kind of tag is needed here.

---

## Writing rules

- **Vocabulary**: frequent words (about N5-N4), at most one word per sentence the learner
  may not know.
- **Length**: 8-15 Japanese words. **A single rule** targeted per card.
- **Situations**: everyday ones (shop, office, home, school, train, restaurant), in sentences
  people really say.
- **Register**: consistent and natural (常体 or 丁寧体 depending on the card), with or
  without a register tag.
- **Variety**: from one card to the next, change the situation, the vocabulary and the
  position of the gap: the situation and the **facet practised** change, never the rule (see
  "The series" below).
- **A single natural answer** given the hints; variants go in `Explanation`.
- **The gap can be typed**: no punctuation inside it, nothing that cannot be written with a
  Japanese IME. The space before a furigana group at the start of the gap is not part of
  the typed `Answer`.
- **URL**: the page given with `--url`, empty otherwise.

---

## The series

The N cards of a request are **a series** that covers the grammar of ONE rule, **from the
most central use to the most peripheral**. That is the order of the TSV, and so the order of
import into Anki.

1. The **canonical** use, in the most frequent construction.
2. The **other constructions the rule allows**: verb, い-adjective, な-adjective, noun, and
   only those it really allows.
3. The **conjugations that change the shape of the gap**: negative, past.
4. From the 3rd card on, at least one where a **neighbouring rule would be tempting**: the
   `Nuance` is enough to tell them apart, and the `Explanation` says why (`≠ 〜たら: …`).
   This card teaches the most: the translation alone does not tell the two forms apart.
5. Beyond that: particular registers, set expressions, edge uses.

A narrow rule (〜に対して: noun only, no conjugation) does not have ten facets. Past what it
offers, the series **revisits the useful facets in other situations**, and never invents a
construction the rule does not allow to reach the count: a wrong card costs more than a
missing one.

---

## Examples

### A) Conjugation asked for (〜ば, N4)
- `Sentence`: `この 薬[くすり]を{{c1:: 飲[の]めば}}、 元気[げんき]になりますよ。`
- `Translation`: `If you take this medicine, you'll feel better.`
- `Target`: `If you take`
- `Hint`: `飲[の]む`
- `Nuance`: *(empty: the translation and the hint are enough)*
- Register: *(empty: the rule does not depend on the register)*
- `Explanation`: `〜ば expresses a general condition "if A, then B": 飲[の]む →
  飲[の]めば (the -eba form). Here the speaker states an expected, natural result.
  ≠ 〜たら: possible too, but 〜ば stresses the logical link between condition and result.`
- `Rule` / `Answer` *(set by the program)*: `ば` / `飲めば`
- Tags: `Grammar::N4::ば`

### B) Expression inserted as it is (〜に対して, N3)
- `Sentence`: `彼[かれ]の 提案[ていあん]{{c1::に 対[たい]して}}、 反対[はんたい]の 意見[いけん]が 出[で]ました。`
- `Translation`: `Opposing views were expressed regarding that proposal.`
- `Target`: `regarding`
- `Hint`: *(empty: nothing to conjugate)*
- `Nuance`: `target of a reaction`
- Register: *(empty)*
- `Explanation`: `〜に対して marks the target of an action or a reaction ("towards,
  regarding"). It attaches directly to the noun. ≠ 〜について: that one would bear on the
  topic being discussed, not on the target the reaction aims at.`
- `Rule` / `Answer`: `に 対[たい]して` / `に対して`
- Tags: `Grammar::N3::に対して`

### C) Register tagged (〜てもよろしいでしょうか, 敬語)
- `Sentence`: `こちらの 資料[しりょう]を{{c1:: 拝見[はいけん]してもよろしいでしょうか}}。`
- `Translation`: `May I have a look at these documents?`
- `Target`: `May I have a look at`
- `Hint`: `拝見[はいけん]する`
- `Nuance`: `asking permission`
- Register: `謙譲語`
- `Explanation`: `〜てもよろしいでしょうか is the humble, very polite version of
  〜てもいいですか for asking permission. 拝見[はいけん]する is the humble (謙譲語) verb for
  見[み]る: the speaker lowers their own action towards the person they address.`
- `Rule` / `Answer`: `てもよろしいでしょうか` / `拝見してもよろしいでしょうか`
- Tags: `Grammar::N3::てもよろしいでしょうか Register::敬語::謙譲語`
