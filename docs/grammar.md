# Grammar (`kotogen grammar`)

Makes cloze cards: a Japanese sentence with a gap on the rule being practised. The command
takes **a rule**: typed, several in a row, drawn from a JLPT level, read from a file, or
read from the page that documents it.

It does not take a text: going through a whole text would return every rule it holds,
including those the deck already has, with cards by the dozen. For the rules of a text you
have **read**, make it a [reading card](reading.md): the pink flag of
[`kotogen maintain`](maintenance.md#deriving-pink) then proposes its rules, minus those the
deck already holds.

```bash
# A rule, typed as it comes: in Japanese, in rōmaji, as a rough draft
kotogen grammar "〜てください" --count 5
kotogen grammar younitanomu           # -> ように頼む, with its level

# Several in a row, or a file of rules (one per line, # for comments)
kotogen grammar "のに" "〜たら" "〜ながら"
kotogen grammar --file rules.md

# The rules of a level the deck does not have yet (--rules per run)
kotogen grammar jlpt --level N4
kotogen grammar jlpt --level N3 --rules 5 --count 3

# The rule a reference page documents: --url WITHOUT a rule, any site
kotogen grammar --url https://www.tofugu.com/japanese-grammar/noni/
kotogen grammar --url https://jlptsensei.com/learn-japanese-grammar/noni --count 3

# The reference page imposed on a rule you name yourself (--url WITH a rule)
kotogen grammar "のに" --count 3 --url https://www.tofugu.com/japanese-grammar/noni/

# Send straight into Anki
kotogen grammar "〜たら" --count 4 --send
```

## Options

| Option | Effect |
|---|---|
| `--file F`, `-f` | File of rules, one per line (`#` for comments) |
| `--count N`, `-n` | Number of cards, per rule as soon as there are several (default: 5) |
| `--rules N` | `jlpt` keyword: maximum number of rules worked on (default: 3) |
| `--level`, `-l` | `jlpt` keyword: which level to fill in (default: `auto`, the easiest first) |
| `--url URL` | Reference page of the cards, written in their `URL` field. **With no rule given**, it is the page that says which rule to work on |

The options shared by every command (`--send`, `--output`, `--model`...) are in
[Global options](global-options.md).

## Where the rule comes from

### Typed, as it comes

`kotogen grammar younitanomu` works: the rule can be written in Japanese, in rōmaji,
abbreviated or as a rough draft. It is first looked up in the **rules table** (see below):
a form the table knows (`のに`, `ながら`, a name copied from a level) gets its name and
level from there, with no AI call. So does a rule typed without the slot its name opens
with: `〜てください` is `て形＋ください`, `やすい` is `ます形＋やすい`. Anything else
(`younitanomu`, a note in your own words, a rule outside the JLPT, a form several names
share such as `ほうがいい`) goes to the model, which returns its canonical name and level,
written as the table writes names: no `〜` at either end.

Several rules can be given in a row (`kotogen grammar "のに" "〜たら"`), or in a file with
`--file`: one per line, blank lines and lines starting with `#` skipped, as `vocab --file`
does with words.

The `URL` field of a card holds the page given with `--url`, and nothing else: kotogen
never searches for a page, and without `--url` the field stays empty.

### From the page that explains it

Given **without a rule**, `--url` also says which rule to work on, and stays the reference
page of the cards.

```bash
kotogen grammar --url https://www.tofugu.com/japanese-grammar/noni/
```

The page is read, and the model says which rule it teaches: one, the main one. A page that
documents no rule in particular (an article, a table of contents) is refused rather than
given an invented rule:

```
This page does not document one rule in particular: it is a table of contents.
```

## Filling in a JLPT level

The **rules table** says what a level contains (110 rules in N5, 140 in N4, up to 295 in
N1), and the deck says which rules you have already worked on. The difference is what is
left to do, worked out **without any AI call**.

```bash
kotogen grammar jlpt --level N4     # the first 3 N4 rules that are missing
kotogen grammar jlpt               # every level, the easiest first
kotogen grammar jlpt --level N2 --rules 10 --count 3
```

```
JLPT grammar missing from "Japanese::Grammar"
   N4: 140 rules on the syllabus, 42 already done, 98 missing
   → the first 3 are generated (--rules to ask for more, replay for the next batch)
```

Run it again for the next batch: the rules already worked on do not come up again. The
keyword needs Anki open, or a copy of the deck kept by an earlier run: without the deck,
every rule of the level would count as missing.

### In the assistant, the whole level can be searched

The assistant shows the whole level rather than the first three: every rule with its
meaning, to tick the ones you want. The table's order puts the backbone of a level first
(を and の open the N5), which may not be the order you want.

```
N4 - 2/140 done, page 1/10
›  1. [ ] ✓ N4  ば                    if, when, provided that (conditional)
   2. [ ] ✓ N4  使役形                force or allow someone to do
   3. [ ]   N4  て形＋しまう・ちゃう  wind up doing, finish completely, regrettably
   4. [ ]   N4  てくれる              to do something for me, someone does me a favour

  type to search, PgUp/PgDn, Space to tick, Escape to go back
```

The meanings come from the rules table, in the language of the screen (see
[The rules table](#the-rules-table)). A ✓ in front of the level marks a rule already done.
Rules already done stay in the list, in their place, and can be ticked again for more
cards.

**Typing searches the list** (see [Searchable lists](interactive.md#searchable-lists)): the
names, their rōmaji and the meanings, so `にく`, `niku` and `diffi` all find にくい.

### The search goes beyond the level

The search covers **the whole table**, not only the level shown. Matches from other levels
come after, with their own level in the column:

```
N4 - 2/140 done - 4 of 140, including 3 outside this list
› 1. [ ]   N4  のに（逆接）            even though, despite, although
  2. [ ]   N3  のに（目的）            for doing, in order to, for the purpose of
  3. [ ]   N1  それなのに              nevertheless, despite that
  4. [ ]   N1  とは比べものにならない  incomparably better than, in a different league from
```

A rule picked this way goes **under its own level**, never under the level on screen: the
table gives its level and meaning, and the level you chose only decides what is shown. The
"2/140 done" count stays that of the level shown.

The example also shows how two rules with one form stay apart: the table heads each with
its grammatical category, as a grammar dictionary does, so every name is unique. That name
is the argument passed to the command (`kotogen grammar のに（目的）`), the card's `Rule`
field and tag (`Grammar::N3::のに（目的）`), and what the deck is compared on. Typed bare,
`のに` finds the first of the two in level order.

### What the table knows nowhere

When the search finds nothing in the whole table, the list offers to work on what you
typed:

```
N4 - 2/140 done - nothing found
› 1. [ ] Work on "zutonaru" anyway
```

Use it for a rule the table lacks or a pattern met elsewhere. It is handled like a rule
typed on the command line: the analysis names it and **gives it its own level**, which may
not be the level on screen.

### What makes a rule "already done"

Two records are checked:

| Record | What it knows | Its limit |
|---|---|---|
| **The deck** | what has been imported, including from another machine | with Anki closed, only the copy kept at its last reading |
| **The history** (`~/.kotogen/seen.json`, source `rules`) | every rule worked on, as soon as its cards are written | only knows this machine |

A card written to a TSV file but not imported yet is not in the deck; the history has it.
On a new machine, the deck knows what the history does not. You can forget the history in
the settings (`h`, the source history): the cards are not touched, and the rules the deck
holds still count as done.

In the deck, a rule is recognised by its **name**, which the table keeps unique: working on
のに（逆接） (N4) does not mark のに（目的） (N3) as done. The name is read from the `Rule`
field and from the `Grammar::N4::ながら` tag, which every card carries even when its `Rule`
field is empty. Names are compared without the `〜` at their ends and without spaces:
「〜ば」 and 「ば」 are one rule.

Neither record blocks anything: name a rule to work on it again
(`kotogen grammar "ながら"`).

## The rules table

`src/kotogen/data/jlpt_grammar.tsv` ships with the package, like the vocabulary table, and
is corrected by hand: a level can be adjusted, a rule added, a line removed. Nothing about
it goes over the network.

```
level<TAB>tier<TAB>rule<TAB>meaning (en)<TAB>meaning (fr)<TAB>meaning (ja)
N4	2	ます形＋やすい	easy to do, tends to happen	facile à faire, a tendance à se produire	〜しやすい、〜になりやすい
```

**The levels are a consensus**, not an official scale: the JLPT has published no list
since the 2010 overhaul. Each level holds at most its usual share of the 110 / 250 / 450 /
650 points counted from N5 up, and N1 holds the rest, so the table may file a point one
level higher than a textbook does.

**The name is the identity of the rule**: the card carries it and the deck is compared on
it, so it is unique. A form that heads several points carries its grammatical category in
full-width brackets, as a grammar dictionary heads its entries: `のに（逆接）` and
`のに（目的）`, `ている（進行）` and `ている（結果）`. Names are Japanese throughout, slots
included (`て形＋から`, `名詞＋まで`), and hold no space, since they become a tag.

**The tier orders a level**: `1` for its backbone, the points met constantly, `2` for the
common ones, `3` for the finer, rarer or more formal ones. `grammar jlpt` offers a level in
that order, the most frequent points first within a tier. No point comes before a point of
its level it rests on (`な形容詞＋名詞` waits for `な形容詞`, `だった・でした` for `です`),
even when that brings a point ahead of its tier. The file is written in that order and read
as it stands, so a line added by hand goes at the end of its tier.

**One gloss column per language** (English, French and Japanese), so that the list of rules
reads in your own language. The glosses are used in two places: the choice screen shows the
meaning in the language of the SCREEN, and the intended use passed to generation, which
tells two uses of one form apart, is in the language of the CARDS. A language the table
does not gloss falls back on English.

## What `--count` really asks for

`--count` asks for **a series** that covers the grammatical surface of the rule, returned
**from the most central card to the most peripheral**, not for N sentences drawn at random.

| Rank | What the card practises |
|---|---|
| 1 | The canonical use, in the most frequent construction of the rule |
| 2... | The other constructions the rule allows: verb, い-adjective, な-adjective, noun |
| ... | The conjugations that change the shape of the gap: negative, past |
| ≥ 3 | At least one card where a **neighbouring rule would be tempting** - that is where the choice between two forms a translation does not tell apart is played out |
| ... | Particular registers, set expressions, edge uses |

So `--count 3` gives the **three cards that matter**, not three edge cases drawn by lot. The
order of the TSV is the order of import, and so the order in which Anki shows the new
cards.

A rule that only attaches to a noun and does not conjugate (〜に対して) does not have ten
facets: past what it offers, the series **revisits the useful facets in other situations**
rather than invent a construction the rule does not allow. `--count 20` on a narrow rule
does not give twenty different exercises.

## Card format

One cloze note type, one rule per card, and as many cards per rule as you want exercises
on it.

**On the front**: the Japanese sentence with a `{{c1::...}}` gap on the target grammatical
form. The word to conjugate sits **on** the gap's line, in dictionary form, and **under**
the line hangs the part of the translation the gap renders, as a reading hangs over a
kanji. Above the sentence: the **register** when it decides the form (常体, 丁寧体, 尊敬語,
謙譲語), and under it a **nuance hint** when the translation alone would leave several rules
plausible. Under the sentence: the whole translation, the main hint.

**On the back**: the same, with the answer in green in the gap, then the rule: its
**name** alone; the line that sets the word to conjugate against the answer (`降る → 降れば`,
what the rule adds in green); the **explanation**; the neighbouring rule it is told from,
last and smaller, after ≠; and at the foot its **level** and the **reference page** given
with `--url`, if any.

Nothing on the front moves when the card turns: the gap keeps room for the answer from the
start, and an answer too long for the line shrinks with its gap on both faces, down to
60% of its size, then wraps inside its gap rather than run off the card.

The rule is **not named** on the front: it is in the tags, and on the back.

## How you answer

Two ways, set in the assistant: the "Templates" menu, then
[Appearance](card-templates.md#customising-the-cards), setting **Answer**.

| Position | What you do |
|---|---|
| `in your head` (default) | You form the gap mentally, then turn the card over, as with a vocabulary card |
| `at the keyboard` | You type the answer in a box under the sentence; the back compares it character by character |

The `Answer` field (the gap without its readings) is written in both cases, so changing
your mind costs no AI call.

Two other settings, in the same place, change what the front gives:

| Setting | Positions |
|---|---|
| **Translation** | `at once` (default): it is under the sentence. `on click`: a 訳 button shows it, so you can try from the Japanese first |
| **Furigana of the statement** | `always` (default): both sides. `on the back`: the front without, the answer with. `never`: the kanji alone |

There is **no** "never" position for the translation: on listening and reading cards it is
a help, but here it is **the question**, and without it the gap could not be guessed. The
furigana setting only touches the sentence: the word to conjugate keeps its readings in all
three positions.

---

[Documentation index](../README.md#documentation)
