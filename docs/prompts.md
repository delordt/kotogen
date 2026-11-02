# Adjusting the instructions sent to the model

The prompts are not in the Python code: each instruction is a markdown file under
`src/kotogen/prompts/`. To change a generation rule, edit its `.md` and run again. There are
no quotes to escape, and the diff stays apart from the diff of the code.

An instruction that asks for card text is written in the language of the cards, so there is
one folder per language, `en/`, `fr/` and `ja/`. The setting that picks one is `all.lang`,
described with the [Card templates](card-templates.md). It changes no template, only what
the model is asked for.

`en/`, `fr/` and `ja/` hold the same twenty-two instructions, and **none stands in for
another**. An instruction that asks for card text and is missing from the language of the
cards raises an error, like any other missing file: the installation is broken. Falling
back on another language would silently fill the deck with paid cards in the wrong
language.

In `ja/`, the language of the cards is the language being learned. Where the other two
translate, it rewords: a word is explained in Japanese simpler than itself, an example or a
text is said again line by line in simpler words, and the questions of a listening or a
reading card are asked in Japanese, as the JLPT asks them. What it writes is held to the
level of the card, since the learner reads the explanation to understand the word.

The thirteen instructions that hand back **structure** sit apart, in `structure/`: where to
cut an audio, which rule a page teaches, whether a lone kanji is a word, how a PDF is laid
out. They answer in JSON, and nothing they write is in the language of the cards (the
Japanese of a PDF transcription or of a text written on the deck is Japanese whatever the
cards are written in). So they have a single copy, in English like the code around them.
`structure/` is a folder of instructions, not a language: `all.lang` cannot be set to it,
and the menu that asks what a deck is written in does not offer it.

So `load` looks in the language of the cards, then in `structure/`, then fails. If
`all.lang` names a language that has no folder at all, the cards are asked for in English.

What does NOT change with the language: the JSON keys the model answers with, which are the
Anki field names (`Translation`, `Decoy1`) and so the schema of the note type; the tags; and
the protocol values the code compares against (`duplicate`, `grammar`). A French deck holds
French text under the same field names. Each instruction that asks for card text in JSON
tells the model so, in its own language, and the tests check both: the keys are the same in
every folder, and each instruction carries that sentence.

What the code BUILDS around an instruction is instruction too: the user message, the limit
stated in words, the fields laid out for the model. Those fragments are written in English
at their call site and translated through `src/kotogen/prompts/<lang>/wording.json`, the
same way the screens are translated through `locales/`. The two tables are never mixed:
`locales/` follows the language of the screens, `wording.json` the language of the deck.

`yes` in the last column means the file is in `en/`, `fr/` and `ja/`; `-` means it is the
single copy in `structure/`.

| File | Used for | Asks for card text |
|---|---|---|
| `vocab_card.md` | the vocabulary card (format, dictionary form and usual spelling, tags, furigana) | yes |
| `vocab_fields.md` | the rules of `Context`, `Notes` and the register tags, included by the five instructions that write them | yes |
| `vocab_extract.md` | picking the useful words of a text | - |
| `vocab_theme.md` | the words of a theme (`vocab --theme`) | - |
| `grammar_card.md` | the cloze sentences | yes |
| `grammar_detect.md` | canonical name + JLPT level of a rule | - |
| `grammar_page.md` | the rule a reference page teaches (`grammar --url` without a rule) | - |
| `reading_card.md` | the reading comprehension questions | yes |
| `reading_compose.md` | a Japanese text written on what the deck is learning (`reading deck`) | - |
| `audio_card.md` | the listening multiple-choice questions on a recording (every listening source but NHK Easy) | yes |
| `audio_split.md` | cutting a recording into self-contained passages, and what to drop | - |
| `kanji_card.md` | the kanji card (meaning, the words that carry each reading, composition, look-alikes, decoys) | yes |
| `nhk_card.md` | translation + multiple-choice questions of an NHK Easy article (listening card) | yes |
| `pdf_vocab.md`, `pdf_texts.md` | the PDF extractions (vision): words, reading texts | - |
| `pdf_reading.md` | the pages of a mini-book read as ONE single reading | - |
| `pdf_arbitration.md` | a scanned document: read it as a book or as text, then transcribe it | - |
| `pdf_items.md` | the map of a JLPT listening booklet (where each item starts, its illustration) | - |
| `pdf_error_contract.md` | the error contract shared by the PDF prompts, included by the others | - |
| `kanji_word.md` | judging whether an isolated kanji is a word | - |
| `maintain_flag_vocab.md`, `maintain_flag_grammar.md`, `maintain_flag_reading.md`, `maintain_flag_audio.md` | fixing a card according to its flag, one per note type `maintain` handles (all but `Kanji`), one section per action | yes |
| `maintain_derive.md` | the words a flagged word calls for (pink) | yes |
| `maintain_derive_grammar.md` | the rules a flagged grammar card calls for (pink) | yes |
| `maintain_derive_passage.md` | the words and the grammar a flagged reading or listening card's text calls for (pink) | yes |
| `maintain_duplicate.md`, `maintain_differentiate.md`, `maintain_group_context.md` | duplicates of a word (turquoise) | yes |
| `maintain_duplicate_grammar.md` | duplicates of a grammar card, and the cards its hints do not tell apart (turquoise) | yes |
| `maintain_audio_transcript.md` | the transcript of a listening extract heard again (purple) | yes |
| `maintain_duplicate_questions.md` | the questions of one passage that ask the same thing (turquoise) | yes |
| `leech_simplify.md` | rewriting a leech more simply | yes |
| `ask.md` | carrying out a request written in the user's own words | yes |

A prompt can include another one, on a line of its own. The PDF prompts share their error
contract that way, and the five instructions that write a vocabulary `Context` or `Notes`
(`vocab_card`, `maintain_flag_vocab`, `maintain_differentiate`, `maintain_group_context`,
`leech_simplify`) share one set of rules for them, `vocab_fields`, so that generation and
`kotogen maintain` write those fields the same way.

```markdown
{{include:pdf_error_contract}}
```

The files ship with the package: a non-editable install carries them along.

---

[Documentation index](../README.md#documentation)
