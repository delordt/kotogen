# From another program

kotogen is two layers in one package:

- The **library** makes cards. It asks the model, lays the furigana, checks what comes back
  against its tables, and writes a TSV or a JSON Lines file. It does not know that Anki
  exists.
- The **Anki adapter**, `kotogen.anki`, is the only part that does. It sends the cards and
  their media into a deck, installs the note types, reads what the deck already holds, and
  looks after it.

The command line and the menu put the two together, so someone working with Anki never
sees the boundary. Another program can use the library without the adapter, from the
command line in any language or from Python, with Anki neither open nor installed.

## From the command line

The command line is the stable interface: a program runs it and reads what it writes. Two
commands make the round trip.

```bash
kotogen vocab --file words.txt --format json --output cards.jsonl
kotogen rework cards.jsonl --task simplify --output proposals.jsonl
```

- The first makes cards and writes them as **JSON Lines**: a first line saying what the
  file holds and what wrote it, then one card per line, under an `id` drawn from its content
  ([the layout](global-options.md#json-lines-output)). Nothing is sent anywhere. Every
  command that generates takes `--format json`, and `KOTOGEN_FORMAT=json` in the
  [settings](global-options.md#where-the-settings-live) makes it the default.
- The second does to those cards what `kotogen maintain` does to a deck, and writes what
  the model proposes for each one into another file, under the same `id` ([the tasks and
  the layout](maintenance.md#a-file-of-cards-kotogen-rework)). It changes nothing: what to
  do with a proposal is up to your program.

The file named by `--output` is also **what the run remembers**. A word or a rule already in
it is not made again, so the same command run on a longer list adds only what is new. The
Anki deck, which the cards may never reach, is not consulted
([what a JSON run remembers](global-options.md#json-lines-output)). Without `--output`, a
JSON run remembers nothing.

To make a card again, run its command on the same input with an `--output` that does not
hold it yet. The `id` is drawn from the content, not from the run: a word, a kanji, or a
question on the same recording or text, made again, comes back under the `id` it had, so a
program that holds the old card can replace it. A grammar card is identified by its sentence
as well as its rule, so a rule made again gives new sentences under new ids. No generator
takes a list of ids; `rework` does (`--ids`), as the one command that starts from cards.

## From Python

Install the package as the [README](../README.md#installation) says. The library imports
without opening a connection or loading anything of Anki: `tests/test_boundary.py` imports
every module of it in a separate process, with the network blocked, and fails if the adapter
is loaded. The model is reached as the command line reaches it, with the same
[key](../README.md#api-key), and the cards are written in the language set by `all.lang`
([the language of the cards](global-options.md#the-cards)).

A card, wherever it comes from, is a dict `{"id", "kind", "fields", "tags"}`, its fields as a
JSON Lines file writes them: furigana in brackets, `<br>` between lines. That is what the
library reads, compares and reworks:

| Module | What it gives |
|---|---|
| `kotogen.exporter` | `read_cards(path)`: the first line and the cards of a JSON Lines file, of any version this release wrote; `outgoing(card, fields)`: a card as the file writes it |
| `kotogen.identity` | `of(kind, fields)`: the `id` of a card, drawn again from its fields |
| `kotogen.known` | `Known`: what a collection already holds, as a run asks it before making a card; `JsonlFile` and `Nothing` answer for a file and for no collection |
| `kotogen.rework` | `propose(client, task, card, kind)`: what the model proposes for one card, as its line in a file of proposals |
| `kotogen.maintenance` | the logic underneath, on cards: which question to ask the model about a card, and what of its answer to keep |
| `kotogen.furigana` | `process_furigana(text)`: the readings of a Japanese text, in Anki's bracket notation |
| `kotogen.ai_client` | `AIClient(provider, model)`: the single entry point to the model |

```python
from pathlib import Path

from kotogen import exporter, rework, settings
from kotogen.ai_client import AIClient
from kotogen.known import JsonlFile
from kotogen.maintenance.kinds import KINDS

cards = exporter.read_cards(Path("cards.jsonl")).cards
print(JsonlFile("cards.jsonl").words("Vocabulary").has("涼しい"))

# Read the settings files and the keys, as the command line does at launch:
# the provider and the model chosen in the menu, since no model is built in.
settings.load()
client = AIClient(provider=settings.text("KOTOGEN_PROVIDER"),
                  model=settings.text("KOTOGEN_MODEL"))
for card in cards:
    if card["kind"] in KINDS:
        proposal = rework.propose(client, "simplify", card, KINDS[card["kind"]])
        print(proposal["id"], proposal["fields"])
```

The generators are commands: `run_vocab(args)` takes what `kotogen vocab` parses from its
command line, so a program that wants cards made runs the command. A program that keeps
cards of its own can still answer the question the generators ask, what already exists, by
subclassing `Known` and implementing `cards`; `memory.follow` is where a run settles which
collection answers it.

## The line between the two

| The library | The Anki adapter, `kotogen.anki` |
|---|---|
| `generators/`, `furigana`, `dictionary`, `jlpt`, `kanji_table`, `grammar_table`, `identity`, `proofreading`, `ai_client`, `prompts/` | `connect`: the AnkiConnect client |
| `known`: what already exists, asked of whichever collection answers | `deck`: the same question, answered by the deck, with the copy it keeps while Anki is closed |
| `exporter`: the TSV and the JSON Lines, written and read back | `send`, `media`: the cards and their media put into the deck |
| `maintenance/`: what to propose for a card | `maintain/`: the notes read, the change shown and confirmed, written, the flag taken off |
| `rework`: the maintenance of a file | `ask`, `backup`, `notetypes`, `installed`, `templates`, `preview` |

The command line and the menu (`cli.py`, `interactive/`, `getting_started.py`) are the only
modules outside `kotogen.anki` allowed to import it, and `tests/test_boundary.py` checks
every import of the library to keep it that way. The adapter needs nothing beyond the
standard library (AnkiConnect is spoken over HTTP) and declares no extra of its own.

---

[Documentation index](../README.md#documentation)
