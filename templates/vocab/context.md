# Context

Anki vocabulary card. `Recognition` shows a Japanese word on the front, then the word and its
translation on the back; `Production` asks the other way round.

The card content follows the language of the cards (`all.lang`), English by default. The
field and tag names below do not: they are the names of the note type in Anki.

## Fields

- `Expression`: the Japanese word or expression, with furigana
- `Translation`: the translation of the word or expression
- `Context` (optional): what tells apart two words with the same translation (`To wear`:
  着る, 被る...). Shown with the question on the `Production` front, and with the answer on
  the `Recognition` back
- `Notes` (optional): an extra note or hint about the expression
- `Example` (optional): a sentence using the word
- `ExampleTranslation`: the translation of the example
- `Audio` (optional): a recording of the word, as Anki's editor inserts it (`[sound:...]`).
  The generator never fills it: it is there for a recording you add. Both backs show its
  player at the bottom of the screen. Without a recording, the system voice reads the word,
  but only with `vocab.tts=yes` (off by default)

## Tags

None, or one or more of these:

- `Adjective` (with the sub-categories `Adjective::い` and `Adjective::な`)
- `Adverb` (sub-categories: `Affirmation`, `Connection`, `Degree`, `Frequency`, `Place`,
  `Manner`, `Negation`, `Quantity`, `Question`, `Time`)
- `Counter` (sub-categories: `SmallAnimals`, `Drinks`, `Books`, `Machines`,
  `GeneralObjects`, `LongObjects`, `SmallObjects`, `Occasions`, `People`, `Time`,
  `Age`, `Floors`)
- `Date` (sub-categories: `DaysOfMonth`, `DaysOfWeek`, `Months`)
- `Expression`
- `Noun` (sub-categories: `Animals`, `Concepts`, `Body`, `Colour`, `Events`,
  `Fruit`, `Places`, `Weather`, `Nature`, `Food`, `Objects`, `People`, `Health`,
  `Time`, `Clothing`)
- `Onomatopoeia`
- `Verb` (sub-categories: `一段動詞`, `不規則動詞`, `五段動詞`)
- `Register` (`敬語::尊敬語`, `敬語::謙譲語`, `丁寧語`, `改まった語`, `文章語`, `口語`, `俗語`,
  `蔑称`, `古語`), `Speaker` (`男性語`, `女性語`) and `Dialect` (`関西弁`): only when
  the word is restricted to that use. Most words carry none

The program also adds `Level::N5` to `Level::N1` when its JLPT table knows the word.

## Example

- `Expression`: 涼[すず]しい
- `Translation`: `Cool`
- `Notes`: `Pleasantly cool, never cold`
- `Example`: 涼[すず]しいですね
- `ExampleTranslation`: `It's nice and cool, isn't it?`
- Tags: `Adjective::い Level::N5`

## The class of the word

The backs read the class of the word from its tags: the three verb groups
(`Verb::一段動詞`, `Verb::五段動詞`, `Verb::不規則動詞`), the two kinds of adjectives
(`Adjective::い`, `Adjective::な`), and the other words: `Noun`, with `Counter` and `Date`
in its colour, `Adverb`, with `Onomatopoeia` in its colour, and `Expression`. The class is a
badge under the word (一段動詞, 名詞...), and its colour is that of the whole card: the
ending that conjugates, the badge, the forms and the box of the example. The script is at
the bottom of both backs, the same on each, and the colours are in the palette of
`style.css` (`--verb-...`, `--adj-...`, `--noun`, `--adverb`, `--expression`). The badge
and each family of colours can be removed separately (`vocab.badge`, `vocab.verb-colours`,
`vocab.adjective-colours`, `vocab.other-colours`); a class without its colour takes that of
the text.

## The forms

A verb or an adjective shows three of its forms in a strip on the back, and three more when
you touch the strip: ない, ます, て, then 可能, 意向, ば for a verb; the negative, the past,
て, then the past negative, the adverb and the conditional for an い-adjective; the form
before a noun, the adverb and the negative, then the past, て and the conditional for a
な-adjective. The script computes them from the word and its tag, readings included, with
these exceptions written in: 行って, ない for ある, 〜います for the five honorific verbs,
問うて, よくない for いい, the forms of 来る (whose kanji changes its reading) and of する
(whose potential is できる), and a する verb on a single kanji, which gets its own potential
(属しうる, 愛せる) or a dash where none is in use (値する).

A word the script cannot conjugate safely, such as one whose tag does not fit its ending,
gets no strip, and its ending keeps the colour of the text. The coloured ending is what every
form of the strip takes off the word: one kana as a rule, the whole する of a する verb, the
くる of a くる written in kana, the いい of いい. A な-adjective gets a な after it instead,
the form it takes before a noun.

## The example

The word is highlighted in its example in whatever form the sentence gives it: the part that
does not change, and the kana that carries the conjugation (帰り of 帰りたい). A sentence
that writes the word differently, in kana where the word has kanji for example, has nothing
highlighted.

## Register badges

The `Register::`, `Speaker::` and `Dialect::` tags are printed beside the class, the way a
Japanese dictionary marks a word: 尊敬, 謙譲, 丁寧, 改, 文, 口, 俗, 蔑, 古, 男, 女, 関西,
each in the colour of its family (formal, casual, marked). The table of signs is in the
script at the bottom of both backs. They are on both backs and never on a front: on
`Recognition`, 謙譲 would give half the meaning away, and on `Production` the context already
tells words such as 友達 and 友人 apart. `vocab.register` removes them from both backs.
