# Asking (`kotogen ask`)

`kotogen ask` takes a request in plain words, and the AI carries it out on the deck with
the program's tools. It is for what the eight actions of [maintenance](maintenance.md) do
not cover: "take the N4 tag off the cards I already know", "my cooking cards have examples
that are too long". Requires **AnkiConnect** (Anki open).

```bash
# Look without changing anything: the writing tools are not even given to the AI
kotogen ask "which cards have an example without a translation?" --scan

# Act: every change is shown, then validated
kotogen ask "take the N4 tag off the cards whose interval is over 60 days"

# Without one-by-one validation (never for a deletion, see below)
kotogen ask "add the Cooking tag to the food cards" --yes
```

## Options

| Option | Effect |
|---|---|
| `request` | What to do, in your own words. It is the only target of the command: no flag or tag selects notes here |
| `--scan` | Look only: the writing tools are not given to the AI |
| `--yes`, `-y` | Apply each write without confirming it one by one (a deletion is still asked for) |

`ask` writes straight into Anki, so it takes neither `--send` nor `--output`. `--provider`
and `--model` work as for the other commands ([Global options](global-options.md)).

## What the AI may do

The AI does not talk to Anki directly. It calls eight named **tools**: three that look (the
scope, the search, reading notes) and five that write (fixing a note, tagging a batch,
laying a flag, removing a flag, deleting notes). What the tools do not allow, it cannot do:
create cards (that is the generators' job), move a deck, reset progress.

- **A search shows the AI 80 notes at most.** For a larger batch, the tools that tag and
  flag take the search itself, and you confirm the whole batch once: the notes are counted
  and the first eight are named.
- **A flag is laid only when you ask for one**, in the colour you named, on the first card
  of each note. Each colour asks [`maintain`](maintenance.md) for something, so "flag green
  the words with no example" prepares its next pass.
- **A field the AI writes gets the readings a generated card gets**: the AI writes the
  Japanese it knows, and MeCab fills in the readings it left out, except in the fields a
  generated card carries without them, such as the `Answer` you type on a grammar card or
  the `Context` of a word. A media field (`Audio`, `Video`, `Image`, `Images`) can only be
  emptied.

**The scope is the one of the backup.** The note types opened are exactly those the
snapshot covers: the Japanese decks, minus what `KOTOGEN_SKIP` leaves out. So every change
can be restored. The scope is not printed; the run opens on the work itself:

```
What the AI does
   Searching "-tag:*"… (0 notes)
   Searching "Example:"… (1200 notes)
```

The searches are held inside the scope, so a note outside it never appears. A note id that
reaches a tool another way is checked against the scope and refused.

**The snapshot is taken at the first accepted write**, not at launch: a request that only
looks leaves nothing behind. If the snapshot cannot be taken, the change is not applied.
With `KOTOGEN_BACKUP=0`, no snapshot is taken and the changes are applied without one. The
final report ends with the command that undoes everything:

```
Changes applied (6):
   note 1512988: Example, ExampleTranslation
   4 notes: -N4
   1 flag removed
   Go back: kotogen backup --restore 2026-09-06_143012
```

The report and its line come whenever a snapshot was taken, even if no change was counted,
and even when the run stops on Ctrl+C or an error after a write: a write cut short may have
reached the deck in part, and the report says so rather than claim that nothing changed.
Ctrl+C while the AI works leaves with the exit code 130; at the prompt, it ends the
conversation as an empty line does (see [The conversation](#the-conversation)). If Anki
closes, the conversation stops: the AI is not given further turns that could only fail.

See [Backup](backup.md) for what a snapshot holds and how it is restored.

## The conversation

**The AI can ask you a question.** Its instructions tell it to ask as soon as two readings
of your request would give two different decks. When it has finished speaking, you get the
prompt back: answer, and the conversation picks up where it was. The first time, a line
above the prompt says how to go on or finish.

```
The AI answers
   │ Two cards carry "To wear": do I tell the two apart, or delete the most
   │ recent one?

Answer to carry on, Enter alone to finish.
> tell them apart
```

What the AI says sits under a heading of its own, each line behind a bar, so it does not
mix with the lines of the run. The `>` is the prompt of the menus and marks what you type.

To finish, press Enter on an empty line, type `b` or `q`, or press Escape or Ctrl+C. Each
ends the conversation normally, on its report, with the exit code 0. On a line where you
have typed something, Escape erases the line instead, as a Windows console does.

The cost of the conversation is shown once, when it ends, with the rest of the bill
(`7 AI calls (€0.04, 1 min 12 s)`), as at the end of any command.

**What is written on screen is what was done**, one line per tool called:

```
   Searching "tag:N4 prop:ivl>60"… (5 notes)
   Reading the notes… (5 notes)
```

While the model thinks, the line says `Thinking…` with a spinner, and it is erased once the
answer is in. When the output is redirected, the line stays, since it cannot be erased
there.

The commentary the model writes between two tools ("I will first look at the scope,
then...") is not shown: the tool lines already say what happened. Only its final message is
printed, because it is the report. It is folded to the width of the screen and stripped of
markdown, which a console does not render. `KOTOGEN_DEBUG=1` shows the commentary too, to
understand an odd sequence.

## Every write is shown

Each write is shown before it is made, with the text as it will be stored after
normalisation, not as the AI wrote it:

```
A note to change
   食[た]べる
   Reason: the card had no example
   Example
     - (empty)
     + 毎朝[まいあさ] 魚[さかな]を 食[た]べます。
   Apply? [y] yes  [n] no
```

The card is named first, so you know what you are accepting, then the reason the AI gives,
then each field with the old value above the new one, as in [maintenance](maintenance.md):
two Japanese sentences side by side do not fit the width of a terminal.

`--yes` skips that question, **except for a deletion**: no command of the program deletes a
note without confirmation, and `ask` is no exception.

`--scan` does not give the AI the writing tools at all. It is the cheapest way to try the
command, and it cannot change anything.

## Two limits

`ask` requires **`--provider openrouter`** (the default): it is the only provider whose
tool calls the program drives, and OpenRouter serves the models of every publisher. When
the settings name another provider, the command takes `--model` as well, the model of the
settings belonging to that provider, and the menu dims **Corrections > Ask** until the model
screen picks an OpenRouter model.

The conversation stops when the model has taken **20 turns** on its own without handing the
prompt back to you; the count starts again every time you answer. Past that, the model is
going round in circles and every turn is paid for. When the limit is reached, the run says
so; the request may be half done, and the report lists exactly what was applied.
