# Vocabulary (`kotogen vocab`)

Makes a clean card (reading, furigana, example, tags) from a rough note. The words come
from what you type, from a file, from a [web page, a text file or a PDF](sources.md), or
from the words of a JLPT level or a theme that the deck is still missing.

```bash
# A single word (free draft: kanji, rōmaji, rough translation...)
kotogen vocab "suzushii - cool (temperature)"
kotogen vocab "涼しい cool/refreshing"

# Markdown file (one entry per line)
kotogen vocab --file my_words.md

# Another model for this run only, sent straight into Anki
kotogen vocab --file words.md --model publisher/model --send

# Vocabulary mined from a page or a text: the most useful words, put back in
# dictionary form (行きました -> 行く), then the usual pipeline
kotogen vocab https://ja.wikipedia.org/wiki/寿司       # 10 words by default
kotogen vocab https://news.web.nhk/news/easy/ne2024XXXX/ne2024XXXX.html --count 8 --level N4
kotogen vocab subtitles.srt

# The words of a JLPT level the deck does not hold yet
kotogen vocab jlpt --level N4          # 20 missing words, the most accessible ones
kotogen vocab jlpt --level N3 --count 50
kotogen vocab jlpt                     # every level, from easiest to hardest

# The words of a theme the deck does not hold yet, named in your own words
kotogen vocab --theme "job interview"  # 20 missing words, the most accessible ones
kotogen vocab --theme fruits --level N3 --count 10

# Vocabulary mined from a PDF document (course, JLPT past paper, scanned textbook...):
# by default, AS MANY useful words of the document as possible
kotogen vocab N4V.pdf
kotogen vocab course.pdf --count 50 --level N4

# An expression also yields a card for each of its words
kotogen vocab "お腹が空いた"          # -> お腹が空く, then お腹 and 空く
kotogen vocab --file phrases.md --no-decompose   # stick to the expressions
kotogen vocab course.pdf --decompose             # decompose a bulk source too

# Generate even the words already in the deck (dropped by default)
kotogen vocab --file words.md --force

# Batches generated one at a time (tight rate limit, or to read the output quietly)
kotogen vocab N4V.pdf --jobs 1
```

## Options

| Option | Effect |
|---|---|
| `--file FILE`, `-f` | File of words, one entry per line (instead of a word as argument) |
| `--theme THEME`, `-t` | The words of a theme the deck is still missing (instead of a word as argument) |
| `--count N`, `-n` | Page/text/PDF/JLPT/theme: maximum number of words extracted (default: 10 per page or text, 20 for `jlpt` and `--theme`, no limit for a PDF) |
| `--level N4`, `-l` | Targeted JLPT level (default: `auto`); for the `jlpt` source, the level to fill in |
| `--force` | Also generate the entries already in the deck (dropped by default) |
| `--decompose` / `--no-decompose` | Force or turn off the decomposition of expressions into words |
| `--batch-size N` | Words sent per AI call (default: 10) |
| `--jobs N`, `-j` | Batches generated in parallel (default: 4; `1` = one at a time) |
| `--no-known-words` | Do not attach the words already learnt to the instructions |

The options shared by every command (`--send`, `--output`, `--model`...) are in
[Global options](global-options.md).

## How a word is written

A card writes its word in its usual spelling: in kanji when Japanese usually writes it in
kanji (行[い]く, 椅子[いす]), in kana when it usually writes it in kana (とても, ちょっと,
たくさん), and never in a rare or old kanji spelling (迚も, 一寸, 沢山), even when the entry
uses one. An entry already in a usual spelling keeps it: 美味しい and おいしい both stay as
they are. `vocab jlpt` uses the spelling that heads the word's row in the reference table.

The template setting `vocab.furigana` (see [Card templates](card-templates.md)) decides how
the card shows the word: the kanji with their readings on the back (the default), the kanji
alone, or the whole card in kana. The note always keeps its kanji and its readings, so
changing the setting later needs no new cards.

## The `Context` field

Several Japanese words share a translation: 着る and 被る both translate as `To wear`,
始まる and 始める both as `To begin`. The front of the `Production` card shows only the
translation, so the question would have several right answers. The **context** narrows it
to one.

> The context answers "**which one?**", never "what does it mean?".

| | |
|---|---|
| Format | A short noun phrase, 1 to 4 words, with no conjugated verb and no sentence |
| When | **Only** if the word could be confused with another one with the same translation (close meanings, transitivity, register). Empty otherwise |
| YES | `To wear` + *upper body* (着る) / *on the head* (被る); `To begin` + *transitive* (始める) |
| NO | `To wear` + *putting a garment on the torso*: a definition, which gives the answer away on the `Production` front and repeats the translation on the `Recognition` back |

Among words that share a translation, the plainest keeps an empty context, since the
contexts of the others set it apart: `Blood` is 血, and 血液 is the *medical term*. Only one
card of such a group may have no context.

The context is what you need **before** answering; the notes are what you read **after**.
So the context shows under the word to translate on the `Production` front, and under the
answer on the `Recognition` back.

On existing cards, [`maintain`](maintenance.md#flags) handles it with the **green** flag
(fill in a missing context) and the **turquoise** flag (tell apart, in one go, all the
cards that share a translation). The AI only writes a context when it judges a confusion
possible.

The card content (translations, context, notes) is written in the language of the cards,
English by default: see [Card templates](card-templates.md#the-language-of-the-cards) for
the setting, and for why the field names stay the same in every language.

## An expression also yields its words

A card for 「お腹が空いた」 is learnt as a block, and its words stay unknown when they turn
up elsewhere. So the model lists them **in the same answer** as the card, in dictionary
form (空いた -> 空く, 忙しくて -> 忙しい): vocabulary only, no particles or grammar patterns,
and no single kanji that is not used as a word (電車 does not yield 電 + 車). This costs
**no extra call**.

```
お腹が空いた
   Generating the cards… (1 card)

2 vocabulary words picked up:
   from "お腹が空く": お腹、空く
   [y] generate these cards  [n] no thanks
```

The run shows how many cards these words would make and asks before generating them. Words
the run has already made and words already in the deck are dropped before the question:
neither is counted nor paid for. A component is not split again. Outside a dialogue, and
under [`--yes`](global-options.md#asking-nothing), the cards are generated.

Decomposition is on for a word typed by hand and for `--file` lists, and off for the other
sources (a PDF, a web page or a text file, `jlpt`, `--theme`), whose entries are already
single words. `--decompose` / `--no-decompose` force it on or off.

### A whole sentence only yields its words

A sentence, typed in Japanese (「女の子と男の人は話しています」) or in approximate rōmaji,
gets **no card of its own**, only cards for its words:

```
onna no ko to otoko no hito ha hanashite imasu
   Generating the cards…
   onna no ko to otoko no hito ha hanashite imasu: sentence, 3 words to draw from it
   Generating the cards… (0 cards)

3 vocabulary words picked up:
   from "onna no ko to otoko no hito ha hanashite imasu": 女の子、男の人、話す
   [y] generate these cards  [n] no thanks
```

The words come in dictionary form (話しています -> 話す), without particles (は, と, の) or
grammar patterns (〜ている, です). With `--no-decompose`, the sentence is skipped.

## Batches in parallel

The words go to the AI in batches of 10 (`--batch-size`), **4 batches at a time**
(`--jobs`), so a PDF of 200 words does not wait for twenty calls in a row. The number of
calls, and so the cost, stays the same.

The results are **collected in batch order**, not in the order the answers arrive, so the
deduplication, the lone-kanji question and the TSV come out as in a sequential run. If the
key is refused, the batches not yet sent are cancelled, but those already in flight still
run: the command stops after a few failed calls rather than one.

## Words already known

Before any AI call, the entries already in the deck are dropped (Anki is read once per run,
through AnkiConnect): Anki would refuse their cards as duplicates anyway. `--force` keeps
them.

The match is made on the spelling (`涼しい` finds `涼[すず]しい`, even when Anki's editor has
wrapped it in HTML), and on the reading for an entry written in kana only (`たべる` finds
`食[た]べる`). A spelling in kanji is matched on its reading only when the deck's spelling
has no kanji (`中々` finds `なかなか`), or writes the same word another way: the same kanji
with other kana (`真中` finds `真[ま]ん中[なか]`), or a kanji in common and one dictionary
entry (`出かける` finds `出掛[でか]ける`). So 箸 is not dropped for 橋, nor 科学 for 化学 (they
read alike and share 学, but are two words). Two spellings with no kanji in common (丸い and
円い) are not matched, as nothing tells them from two homophones. An entry with no Japanese
(a draft in rōmaji) is never dropped, and an entry carrying several words is only dropped
if **all** of them are known.

With Anki closed, the run compares with a **copy of the deck**. Each reading of the deck
keeps one in the cache (only the `Expression` field and the tags, a few hundred kilobytes),
and the cards generated since are added to it, so two runs before an import do not make the
same words twice. The run says which day the copy dates from; the next reading of Anki
replaces it. With no copy yet, nothing is dropped.

## Format of the word file (`--file`)

One entry per line, written as freely as on the command line. A leading `-` or `*` is
removed; blank lines and lines starting with `#` are skipped.

```
涼しい - cool (temperature)
食べる - to eat
- 飲む to drink
* 走る hashiru, to run
```

## JLPT level from a reference table

Every card gets its `Level::NX` tag from a local list of about 9,200 words: no AI call,
always the same answer. A word missing from the list gets no level rather than an
estimate.

The level is read from the **spelling**. The reading is only a fallback for a word written
all in kana, used when the words with that reading all share one level: はし could be 橋 or
箸 (N5), or 端 (N3), so it gets none. A word in kanji missing from the list never takes the
level of a homophone (貴社 does not inherit the N4 of 汽車). A word written several ways is
one row of the list, under its most common spelling (とても rather than 迚も, 面白い in kanji),
with its other spellings beside it: おいしい and 美味しい are one N5 word, and a card written
美味[おい]しい is tagged N5 like one written おいしい.

The same table sorts the words extracted from a page, a text, a PDF or a theme, the most
accessible first. With an explicit `--level`, the words the list places **clearly** below
the target (two levels: N5 when aiming at N3) are dropped before generation, at no cost. A
word missing from the list is never dropped.

## Filling in a level (`vocab jlpt`)

The words of a level that the deck lacks are worked out from the reference table, without
any AI call. The command says where things stand, then generates the missing words, the
most accessible first. Within a level, the table goes from the most frequent word to the
least, so a first batch of N5 holds する, ある and この, each word once, under the spelling
that heads its row:

```
JLPT vocabulary missing from "Japanese::Vocabulary"
   N4: 654 words in the reference table, 623 already in the deck, 31 missing
   → the 20 most accessible ones are generated (--count to ask for more, replay for the next batch)
```

Run it again for the next batch: once the generated cards are in the deck, they no longer
count as missing. It needs **Anki open**, or a [copy of the deck](#words-already-known)
from an earlier run: without the deck, the whole level (650 to 3,400 words) would count as
missing. Without `--level`, every level is taken, from N5 to N1.

> The JLPT has not published an official list since the 2010 overhaul: the levels of the
> table are a consensus, not an official scale. Each level holds at most its usual share
> of the 800 / 1,500 / 3,750 / 6,000 / 10,000 words the levels are said to ask for.

## Filling in a theme (`vocab --theme`)

The JLPT table does not know the words of a job interview or of programming, so the AI
lists them first. A theme can be a field (`fruits`, `mathematics`), a situation (`job
interview`, `at the doctor's`), a closed set (`days of the week`, `cities of Japan`) or a
class of words (`i-adjectives`), typed in any language. The AI is asked for three times as
many words as `--count` (at least 40, at most 150), so that enough are left once the words
already in the deck are removed:

```
Vocabulary of the theme "fruits"
   Listing the words of the theme… (38 words)
   38 words in the theme, 12 already in the deck, 26 missing
   → the 20 most accessible ones are generated (--count to ask for more, replay for the next batch)
```

The words are generated the most accessible first, by the level the reference table gives
them; the words it does not know (most of the jargon of a trade) come last. `--level` aims
the list at a level and drops the words clearly easier than it, as for a page. Run the
command again for more words: the list is drawn again each time, so it is close to the
first one but not identical.

Proper nouns are listed only when the theme is made of them: `cities of Japan` gives 札幌 and
京都, `travel` gives 駅 and 切符 but no station names. The theme is not written into the deck:
the cards are filed by their usual tags (`Noun::Fruit`, `Level::N4`...). Anki need not be
open: without the deck, the whole list is generated, up to `--count`.

## Examples built on what you already know

An example sentence with three unknown words teaches nothing. So the **400 most basic
words** of the deck (sorted by JLPT level) are attached to the instructions, and the AI is
asked to build the examples from them.

```
把握する          WITHOUT: 状況[じょうきょう]を 把握[はあく]する。       (状況 is N3)
                  WITH:    問題[もんだい]の 意味[いみ]を 把握[はあく]しました。
```

The list sits in the **cached** part of the prompt (see
[Caching of the system prompt](global-options.md#caching-of-the-system-prompt)): the first
batch of a run pays for it in full (+1,672 tokens, about +$0.0065), and the following
batches at a fraction of the price. `--no-known-words` turns it off.

The list is left out when there is no deck to read (Anki closed and no copy of the deck),
when the deck is empty, or when it holds fewer than 200 words: too few to write natural
sentences with.

## Readings checked against the dictionary

Before the cards are written, the reading of each card is checked against the readings
unidic-lite (installed for the furigana) gives the same spelling: a local check, with no AI
call. A reading the dictionary cannot produce is reported on screen, and the card gets the
`Check::Reading` tag (`Check::Word` for a spelling it cannot analyse at all):

```
?? 図書館[としょしつ] - Library: unexpected reading (the dictionary reads "としょかん")
```

Nothing is refused or corrected automatically: find the cards with `tag:Check::Reading` in
Anki, or give them the blue flag and run `kotogen maintain --only blue` to rework them. Any
reading of the dictionary's ten likeliest analyses passes, not only the first: 今日[きょう]
and 今日[こんにち], 明日[あした] and 明日[みょうにち] are all accepted. The check judges neither
the translations nor whether a word exists (unidic splits 食飲書 into three known kanji).

## Lone kanji

An entry reduced to a kanji that is not a word on its own (語, 的, 勉...: suffixes and parts
of compound words, common in word lists and course PDFs) is caught before the TSV is
written, and its card is offered for removal (`[r] remove (do not create the card)` /
`[c] create anyway`), with the reason the model gives and a word that uses the kanji.
Outside a dialogue (script, redirected input), and under
[`--yes`](global-options.md#asking-nothing), it is removed. Real one-kanji words (木, 水,
本...) go through without a question. The check costs one AI call, made only for a batch
that holds a one-kanji card.

---

[Documentation index](../README.md#documentation)
