"""One audio file, several conversations: where to cut, and where to keep nothing.

A collection (a JLPT sample, a shadowing book) is cut into its passages. The
audio produced only holds ranges transcribed as speech and classed as content:
the transcription is a whitelist, so a bell or a jingle never reaches a piece.
Whisper's word timestamps place the speech, ffmpeg's silences the cut, and one
model call reads the numbers and judges the content; the first two are free and
serve without the call (`whole_block`). Nothing displayed quotes the content.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from kotogen import console, prompts
from kotogen.ai_client import AIClient
from kotogen.generators import announcements, cuts, quota
from kotogen.i18n import _, convention, counted, listed

# ── Settings ──────────────────────────────────────────────────────────────────

# Below that, a file cannot be a collection: the call is not paid for.
MIN_SEGMENTS = 4
MIN_DURATION = 45.0

# Attempts at splitting one file. A failure is nearly always one comma too many
# in a right answer, and a retry costs far less than a wasted generation pass;
# three, as the model sometimes makes the same slip twice in a row.
ATTEMPTS = 3

# The attempt's rank in the log, by attempt number (the first is not announced):
# lengthen it with ATTEMPTS. Held in English, translated where it is displayed.
RANKS = ("first", "second", "third", "fourth", "fifth")

# Ceiling of blocks per file, each costing a generation call: a collection rarely
# holds more, a long podcast could give thirty. Same spirit as `quota.enforce`.
MAX_BLOCKS = 12

# On a stream, far tighter: it only has changes of subject, and nothing bounds
# how many passages a generous model could propose. Four extracts of one episode
# already make a good day of reviewing.
MAX_STREAM_BLOCKS = 4

# On a fiction, in between: its scenes bound its passages as exercises do, but a
# twenty-minute episode holds a dozen, too many generation calls for one evening.
MAX_FICTION_BLOCKS = 8

# Duration window announced for a stream passage: without it the model proposes
# three-minute ones, turned down after the splitting call is paid for.
STREAM_MIN_DURATION = 20
STREAM_MAX_DURATION = 90
# Share of the upper bound under which the floor follows it down, so that a tight
# limit never announces "from 20 to 20 s", where the model has nowhere to cut and
# refuses. A roomy limit is untouched (90 s gives 36, 60 s gives 24).
STREAM_MIN_SHARE = 0.4
# Grounds for refusal expected from the model (see prompts/structure/audio_split.md).
# They are the contract: a refusal naming anything else is replaced, since this
# text is displayed and a sentence of the model's could give the content away.
REASONS = {
    "number", "title", "instruction", "exam question",
    "answer options", "transition", "not standalone", "off topic",
    # The trappings of a series, back every week. Whisper takes sung words down
    # too, so a theme song has to be nameable.
    "theme song", "story so far", "next episode",
}

# The reason as displayed, singular then plural, keyed by the protocol term and
# translated at the display site. The table exists for the plural: nothing in a
# term says whether it agrees ("titles", but "off topic" at any count).
LABELS = {
    "number": ("number", "numbers"),
    "title": ("title", "titles"),
    "instruction": ("instruction", "instructions"),
    "exam question": ("exam question", "exam questions"),
    "answer options": ("answer options", "answer options"),
    "transition": ("transition", "transitions"),
    "not standalone": ("not standalone", "not standalone"),
    "off topic": ("off topic", "off topic"),
    "theme song": ("theme song", "theme songs"),
    # Neither of these agrees: two of them are one moment, seen in two episodes.
    "story so far": ("story so far", "story so far"),
    "next episode": ("next episode", "next episode"),
    "outside the content": ("outside the content", "outside the content"),
    "too long": ("too long", "too long"),
    "too short": ("too short", "too short"),
    "past the ceiling": ("past the ceiling", "past the ceiling"),
}

# Kind displayed when no splitting took place (file taken as it is). Held in
# English and translated where it is displayed.
KIND_WHOLE = "whole file"

# The same file, minus the number announcing it: a kind of its own, since `whole`
# answers no and the sound is re-encoded between the computed bounds.
KIND_TRIMMED = "whole file, minus its announcement"

# A file the splitting could not read, turned down rather than handled in one
# piece: a failure, unlike "no usable passage", which is a verdict.
KIND_FAILED = "splitting failed"


# ── What travels ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Segment:
    """A Whisper segment: its line of text, its bounds, its timestamped words."""
    text: str
    start: float
    end: float
    words: tuple[Word, ...] = ()

    @classmethod
    def from_whisper(cls, raw: dict) -> Segment:
        words = tuple(
            Word(str(m.get("word", "")), float(m.get("start", 0.0)), float(m.get("end", 0.0)))
            for m in (raw.get("words") or [])
        )
        return cls(str(raw.get("text", "")).strip(),
                   float(raw.get("start", 0.0)), float(raw.get("end", 0.0)), words)

    def as_dict(self) -> dict:
        """Shape of the disk cache, identical to Whisper's (read back as it is)."""
        return {"text": self.text, "start": self.start, "end": self.end,
                "words": [{"word": m.text, "start": m.start, "end": m.end} for m in self.words]}


@dataclass(frozen=True)
class Block:
    """A passage to keep: its lines (numbered from 1) and its ranges.

    One range per run of contiguous lines, glued together at extraction: a single
    start/end pair would take back what is dropped in the middle.
    """
    lines: tuple[int, ...]
    ranges: tuple[tuple[float, float], ...]
    # The rank of the item, when the sound announced it (「3番」); None otherwise.
    # Unused here: the listening chain draws a past paper's figure from it.
    item: int | None = None
    # The first line as HEARD, when the sound opens after its start (the 「1番」
    # of 「1番 大学で…」 cut off); empty when the line is heard whole.
    opening: str = ""

    @property
    def start(self) -> float:
        return self.ranges[0][0]

    @property
    def end(self) -> float:
        return self.ranges[-1][1]

    @property
    def duration(self) -> float:
        """The sound really produced, gaps deducted."""
        return sum(max(0.0, end - start) for start, end in self.ranges)

    def spans(self) -> list[tuple[float, float]]:
        """Ranges in the (start, duration) shape ffmpeg expects."""
        return [(start, end - start) for start, end in self.ranges]

    def texts(self, segments: list[Segment]) -> list[str]:
        """The lines of the passage, the first one as it is heard.

        What the sound left out leaves the text too: the model writing the card
        would take a line opening on 「1番」 for an announcement and drop it whole.
        """
        texts = [segments[i - 1].text for i in self.lines if 1 <= i <= len(segments)]
        if self.opening and texts:
            texts[0] = self.opening
        return texts


@dataclass(frozen=True)
class Dropped:
    """A passage left outside, and why - without ever quoting its content."""
    start: float
    end: float
    reason: str


@dataclass(frozen=True)
class Split:
    kind: str
    blocks: list[Block]
    dropped: list[Dropped]
    # Blocks the model handed back unusable (index outside the file, overlapping
    # ranges): counted, since the screen only says there were some.
    unreadable: int = 0

    @property
    def whole(self) -> bool:
        """Is the file taken as it is, with nothing extracted nor trimmed?

        One block is not enough: the model may have kept one passage and trimmed a
        title off it, which is an extract to produce.
        """
        return self.kind == KIND_WHOLE

    @property
    def one_piece(self) -> bool:
        """Did the file escape being split into passages?

        Unlike `whole`, which decides whether there is sound to re-encode, this
        decides whether there is a place to name: bounds tell the extracts of a
        collection apart, and a trimmed announcement makes no extract.
        """
        return self.kind in (KIND_WHOLE, KIND_TRIMMED)


# ── The splitting call ────────────────────────────────────────────────────────

def _boundaries(segments: list[Segment],
                silences: list[tuple[float, float]]) -> list[tuple[int, float]]:
    """Long silences falling BETWEEN two lines: (line number, duration).

    A silence inside a line says nothing of a boundary; only the longest between
    segments are given, so as not to swell the prompt with a hundred breaths.
    """
    landmarks: list[tuple[int, float]] = []
    for s0, s1 in silences:
        duration = s1 - s0
        if duration < cuts.BOUNDARY_MIN or math.isinf(duration):
            continue
        previous = [i for i, s in enumerate(segments, 1) if s.end <= s0 + 0.05]
        if previous:
            landmarks.append((previous[-1], duration))
    landmarks.sort(key=lambda r: r[1], reverse=True)
    return sorted(landmarks[:60])


def _duration_instruction(limit: float | None) -> str:
    """What is expected of the LENGTH of the passages, said before splitting.

    The window holds for a stream or a fiction: a collection's passage lasts what
    it lasts. A limit lowers the top of the window rather than standing beside it,
    which the model took for a reserve, and the floor follows
    (`STREAM_MIN_SHARE`); the limit bounds where a passage is cut, never whether
    a subject is kept. English, like the structure instruction it joins.
    """
    top = min(STREAM_MAX_DURATION, int(limit)) if limit else STREAM_MAX_DURATION
    # A limit tighter than the floor takes the floor down with it, rather than
    # closing the window on one value; one second stays the last stop.
    bottom = max(1, min(STREAM_MIN_DURATION, int(top * STREAM_MIN_SHARE)))
    sentence = (f"On a stream or a fiction, aim for passages of {bottom} to "
                f"{top} s. On a collection, the length is that of the passage, "
                "whatever it is.")
    if limit:
        sentence += (f" A passage over {limit:.0f} s will be set aside without "
                     "being generated - but that ceiling bounds where you CUT, "
                     "not what you keep: a subject longer than it is not refused "
                     "for that, a window is taken inside it.")
    return sentence


def _ceiling_instruction() -> str:
    """The number of kept blocks that will be accepted, said before it proposes any.

    The truncation (see MAX_BLOCKS) cuts in the order of the audio, and on a
    podcast the beginning is the weakest part: told, the model picks its best.
    """
    return (f"Hand back at most {MAX_BLOCKS} kept blocks on a collection, "
            f"{MAX_FICTION_BLOCKS} on a fiction, {MAX_STREAM_BLOCKS} on a "
            "stream. Beyond that, the blocks in excess are ignored in the order "
            "of the audio: hand back the best ones, not the first ones.")


def _message(name: str, segments: list[Segment],
             silences: list[tuple[float, float]],
             limit: float | None = None) -> str:
    # English whatever the cards: the answer is where to cut, never card text, so
    # the instruction lives in `prompts/structure/` alone (see `kotogen.prompts`).
    numbered = "\n".join(
        f"{i:>3}  [{s.start:.1f}-{s.end:.1f}]  {s.text}"
        for i, s in enumerate(segments, 1)
    )
    landmarks = _boundaries(segments, silences)
    if landmarks:
        hints = ", ".join(f"after line {n} ({d:.1f} s)" for n, d in landmarks)
    else:
        hints = "none (the file has no clear pause, or they were not measured)"
    return (
        f'File "{name}", {segments[-1].end:.0f} s, {len(segments)} lines.\n\n'
        f"Timestamped Whisper transcript:\n\n{numbered}\n\n"
        f"Silences longer than {cuts.BOUNDARY_MIN} s: {hints}\n\n"
        f"{_duration_instruction(limit)}\n\n"
        f"{_ceiling_instruction()}\n\n"
        "Cut this file according to the rules."
    )


def without_the_announcements(segments: list[Segment], lines: list[int]) -> list[int]:
    """The lines, minus those that are only an announced number, head and tail.

    Filed with the conversation, such a line would reach the sound and the
    transcript sent to the generator; the model often files the NEXT passage's
    number with the one just ended. One line always stays, or an empty
    transcript would pass for a passage.
    """
    lines = list(lines)
    while len(lines) > 1 and announcements.is_marker(segments[lines[0] - 1].text):
        lines.pop(0)
    while len(lines) > 1 and announcements.is_marker(segments[lines[-1] - 1].text):
        lines.pop()
    return lines


def _heard(segment: Segment, attack: float | None) -> str:
    """The text of the line from the attack on, or "" when it is heard whole.

    The attack is laid on the start of a word, so the words it skips are those
    the sound leaves out (the number, 「例」).
    """
    if attack is None or not segment.words:
        return ""
    heard = "".join(word.text for word in segment.words
                    if word.start >= attack - 0.01).strip()
    return heard if heard and heard != segment.text.strip() else ""


def _kept_bounds(answer: dict) -> list[tuple[int, int]]:
    """(first line, last line) of each kept block, in order.

    Read on the whole answer first: the window in which `without_the_question`
    looks for a twin runs from one kept block to the next.
    """
    bounds = []
    for raw in answer.get("blocks") or []:
        if not isinstance(raw, dict) or not raw.get("keep"):
            continue
        ranges = _read_ranges(raw.get("lines"))
        if ranges:
            bounds.append((min(d for d, _ in ranges), max(f for _, f in ranges)))
    return sorted(bounds)


# How far up a kept block goes looking for the line that opens its item, among
# the lines set aside just before it: the announcement with its setting up, then
# the exam question, which can take two lines. Further up is the item before.
OPENING_REACH = 3


def _opens_item(segments: list[Segment], number: int,
                silences: list[tuple[float, float]]) -> bool:
    """Does this line open an item: its announcement glued to it, or said alone
    on the line before (「6番」, then 「ラジオで女の人が…」)? A line nobody said
    opens nothing, nor an announcement nobody said."""
    segment = segments[number - 1]
    if announcements.unheard(segment, silences):
        return False
    if announcements.item_opening(segment) is not None:
        return True
    if number < 2:
        return False
    before = segments[number - 2]
    return (announcements.announced_item(before) is not None
            and announcements.is_marker(before.text)
            and not announcements.unheard(before, silences))


def _rescued_openings(answer: dict, segments: list[Segment],
                      silences: list[tuple[float, float]] = ()) -> dict[int, int]:
    """Kept block (its rank in the answer) -> the line set aside that opens its item.

    Told to drop an item's number and keep its line (`start_word`), the model
    often sets the whole line aside on a past paper, and the card opens on
    reply 1. The line is found by `item_opening` among those set aside just
    before a block that does not open its item, up to a kept block; a question
    between them stays out of the sound.
    """
    blocks = list(answer.get("blocks") or [])
    owner: dict[int, int] = {}
    for rank, raw in enumerate(blocks):
        if isinstance(raw, dict):
            for first, last in _read_ranges(raw.get("lines")):
                # Within the file: a range of the model's can run to a billion.
                for line in range(max(first, 1), min(last, len(segments)) + 1):
                    owner.setdefault(line, rank)
    rescued: dict[int, int] = {}
    for rank, raw in enumerate(blocks):
        if not isinstance(raw, dict) or not raw.get("keep"):
            continue
        ranges = _read_ranges(raw.get("lines"))
        first = min((start for start, _ in ranges), default=0)
        if not 1 <= first <= len(segments) or _opens_item(segments, first, silences):
            continue
        # The lines nobody said do not count in the reach: the blank of the
        # reading time can hold five of them between the item and its start.
        line, reach = first - 1, OPENING_REACH
        while line >= 1 and reach > 0:
            holder = owner.get(line)
            if holder is None or blocks[holder].get("keep"):
                break
            if _opens_item(segments, line, silences):
                rescued[rank] = line
                break
            if not announcements.unheard(segments[line - 1], silences):
                reach -= 1
            line -= 1
    return rescued


def _read_ranges(raw) -> list[tuple[int, int]]:
    """Reads the `lines` field, tolerating the single range given flat.

    `[[4, 11]]` is the contract, `[4, 11]` what a model with one range hands back.
    """
    if not isinstance(raw, list) or not raw:
        return []
    if all(isinstance(v, int) for v in raw) and len(raw) == 2:
        return [(raw[0], raw[1])]
    ranges = []
    for pair in raw:
        if isinstance(pair, list) and len(pair) == 2 and all(isinstance(v, int) for v in pair):
            ranges.append((pair[0], pair[1]))
    return ranges


def _runs(lines: list[int]) -> list[list[int]]:
    """Splits a list of line numbers into contiguous runs.

    `[4, 5, 6, 9, 10]` -> `[[4, 5, 6], [9, 10]]`: two pieces of sound, around what
    the model asked to remove in the middle.
    """
    runs: list[list[int]] = []
    for number in lines:
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return runs


def _read_answer(answer: dict, segments: list[Segment],
                 silences: list[tuple[float, float]],
                 limit: float | None = None) -> Split:
    """Turns the answer of the model into blocks bounded in time.

    Anything doubtful is turned down rather than straightened out: a bad index
    or overlapping ranges say the model lost the thread of the file. `limit` is
    applied here, before the ceiling truncation, so that long blocks do not
    crowd out shorter ones; the generation guard stays for a file taken whole.
    Keys and values follow the English contract of `prompts/structure/audio_split.md`.
    """
    if not isinstance(answer.get("blocks") or [], list):
        raise ValueError("blocks is not a list")
    kind = str(answer.get("kind", "")).strip().lower()
    if kind not in ("collection", "stream", "fiction"):
        kind = "unknown"

    blocks: list[Block] = []
    dropped: list[Dropped] = []
    taken: set[int] = set()
    unreadable = 0
    floor = 0.0
    # Counted over the whole file: a rank is readable only if announced once.
    unique = announcements.unique_items(segments)
    # The item of each kept block stops at the next one: the window in which an
    # exam question repeats itself.
    bounds = _kept_bounds(answer)
    # Lines opening an item but set aside with its number move to the head of
    # the block they open.
    rescued = _rescued_openings(answer, segments, silences) if kind == "collection" else {}
    moved = set(rescued.values())

    for rank, raw in enumerate(answer.get("blocks") or []):
        if not isinstance(raw, dict):
            unreadable += 1
            continue
        ranges = _read_ranges(raw.get("lines"))
        lines: list[int] = []
        for first, last in ranges:
            if not 1 <= first <= last <= len(segments):
                lines = []
                break
            lines.extend(range(first, last + 1))
        if lines:
            lines = [line for line in lines if line not in moved]
            if rank in rescued:
                lines.insert(0, rescued[rank])
            if not lines:
                continue   # a block set aside that held nothing but that line
        if not lines or taken.intersection(lines):
            unreadable += 1
            continue
        taken.update(lines)

        if not raw.get("keep"):
            reason = str(raw.get("pattern", "")).strip()
            dropped.append(Dropped(segments[lines[0] - 1].start, segments[lines[-1] - 1].end,
                                   reason if reason in REASONS else "outside the content"))
            continue

        # Read BEFORE the announcement lines go: the item's rank is written on them.
        item = announcements.block_item(segments, lines, unique)

        # Removed after `taken`, so that no other block claims the number's line.
        lines = without_the_announcements(segments, lines)

        # Unsaid lines go first: the exam question is found by its rank, which
        # they would shift.
        lines = announcements.without_the_unheard(segments, lines, silences)

        # The exam question, on a collection only: on a stream a repeated
        # sentence is not an instruction.
        if kind == "collection":
            before = next((end + 1 for _, end in reversed(bounds) if end < lines[0]), 1)
            after = next((start - 1 for start, _ in bounds if start > lines[-1]),
                         len(segments))
            lines = announcements.without_the_question(segments, lines, (before, after))

        # On a collection, long blanks between lines are reading time, never the passage.
        runs = (announcements.at_the_blanks(_runs(lines), segments, silences)
                if kind == "collection" else _runs(lines))
        lines = [number for run in runs for number in run]

        opening, closing = segments[lines[0] - 1], segments[lines[-1] - 1]

        # The model's `start_word` beats the segment's bound, not the net: it
        # often includes the number (`"4あっ"`), so the later attack wins. A line
        # brought back by `_rescued_openings` ignores it, as it was written for
        # the line that opened the block.
        attack = (None if rank in rescued
                  else cuts.word_moment(opening, str(raw.get("start_word", ""))))
        net = announcements.attack_after_marker(opening, collection=kind == "collection")
        if net is not None and (attack is None or attack < net):
            attack = net
        # The announcement of an item, which `attack_after_marker` lets through
        # when Whisper stretched it or when it is 「例」.
        opened = announcements.item_opening(opening) if kind == "collection" else None
        if opened is not None and (attack is None or attack < opened):
            attack = opened

        # Same at the other end: the net overrides the model's `end_word`.
        fade = cuts.word_moment(closing, str(raw.get("end_word", "")), end=True)
        guard = announcements.fade_before_marker(closing, collection=kind == "collection")
        if guard is not None and (fade is None or fade > guard):
            fade = guard

        ranges: list[tuple[float, float]] = []
        for run_rank, run in enumerate(runs):
            opens = segments[run[0] - 1]
            closes = segments[run[-1] - 1]
            # A Whisper line keeps its declared bound (`bound_before` aligns it
            # through the words); a subtitle bound is a display moment, often in
            # the blank before the sentence, which `_spoken_start` corrects.
            entry = (attack if (run_rank == 0 and attack is not None)
                     else opens.start if opens.words
                     else cuts._spoken_start(opens, silences))
            # A piece the reading time opens may have its first word laid on the
            # bell: the speech starts after it (see `after_the_bell`).
            if run_rank > 0 and kind == "collection":
                voice = announcements.after_the_bell(opens, silences)
                if voice is not None and voice > entry:
                    entry = voice
            # `_spoken_end` rather than `closes.end`, which can run onto the next
            # announcement: `cut_end` and `bound_after` never close before the
            # fade they are given, so a late fade passes both unseen.
            exit_at = (fade if (run_rank == len(runs) - 1 and fade is not None)
                       else cuts._spoken_end(closes, silences))
            start = cuts.cut_start(
                entry, silences,
                cuts.bound_before(entry, opens, segments, run[0], floor, silences),
                cuts._margin(opens))
            end = cuts.cut_end(
                exit_at, silences,
                cuts.bound_after(exit_at, closes, segments, run[-1], math.inf, silences),
                cuts._margin(closes))
            if end <= start:
                ranges = []
                break
            floor = end
            ranges.append((start, end))
        if not ranges:
            unreadable += 1
            continue

        block = Block(tuple(lines), tuple(ranges), item, _heard(opening, attack))
        if limit and round(block.duration) > round(limit):
            dropped.append(Dropped(block.start, block.end, "too long"))
            continue
        texts = [segments[i - 1].text for i in lines]
        if not quota.carries_a_question(texts):
            dropped.append(Dropped(ranges[0][0], ranges[-1][1], "too short"))
            continue
        blocks.append(block)

    # An unread kind takes the widest ceiling: the file was cut all the same.
    ceiling = {"stream": MAX_STREAM_BLOCKS,
               "fiction": MAX_FICTION_BLOCKS}.get(kind, MAX_BLOCKS)
    if len(blocks) > ceiling:
        for lost in blocks[ceiling:]:
            dropped.append(Dropped(lost.start, lost.end, "past the ceiling"))
        blocks = blocks[:ceiling]

    return Split(kind, blocks, dropped, unreadable)


def _whole_file(segments: list[Segment]) -> Split:
    """The file taken as it is, from the first sample to the last."""
    lines = tuple(range(1, len(segments) + 1))
    return Split(KIND_WHOLE,
                 [Block(lines, ((0.0, segments[-1].end if segments else 0.0),))], [])


def whole_block(segments: list[Segment], audio_path: Path | None = None,
                silences: list[tuple[float, float]] | None = None) -> Split:
    """The file in one piece - minus the number announcing it, if there is one.

    For a file too short for the model (`MIN_DURATION`), such as a いろどり track
    opening on its number said out loud: the deterministic net costs no call.
    `silences` when already measured; failing that `audio_path`, measured only if
    there is something to remove. Nothing to remove gives `KIND_WHOLE`: the
    sound goes to the media library as it is, without re-encoding.
    """
    if not segments:
        return _whole_file(segments)

    lines = list(range(1, len(segments) + 1))
    kept = without_the_announcements(segments, lines)
    opening, closing = segments[kept[0] - 1], segments[kept[-1] - 1]
    # The number glued to the first line (`1 ねえ、見て。`): the cut falls inside it.
    attack = announcements.attack_after_marker(opening)
    fade = announcements.fade_before_marker(closing)
    if kept == lines and attack is None and fade is None:
        return _whole_file(segments)

    if silences is None:
        silences = cuts.detect_silences(audio_path) if audio_path else []

    entry = (attack if attack is not None
             else opening.start if opening.words
             else cuts._spoken_start(opening, silences))
    exit_at = (fade if fade is not None
               else cuts._spoken_end(closing, silences))
    start = cuts.cut_start(
        entry, silences,
        cuts.bound_before(entry, opening, segments, kept[0], 0.0, silences),
        cuts._margin(opening))
    end = cuts.cut_end(
        exit_at, silences,
        cuts.bound_after(exit_at, closing, segments, kept[-1], math.inf, silences),
        cuts._margin(closing))
    if end <= start:
        # Crossed bounds mean a misread, not an empty file: the whole file keeps
        # the number in, which is better than losing the conversation.
        return _whole_file(segments)
    return Split(KIND_TRIMMED, [Block(tuple(kept), ((start, end),), None,
                                      _heard(opening, attack))], [])


def split_audio(client: AIClient, audio_path: Path, segments: list[Segment],
                *, active: bool = True, limit: float | None = None) -> Split:
    """Blocks to generate for this file, possibly the whole file.

    A failure does not fall back on one block: a collection handled whole costs
    a generation call for a card on ten exchanges at once, with no extract. An
    unreadable answer (a ValueError) is retried (see ATTEMPTS) and the file
    turned down once all attempts fail; the log does not say why, as `chat_json`'s
    error carries the raw answer, hence the transcript. Any other failure (a cut
    answer, the network, a bug) would fail the same way again: it is raised.
    """
    if not segments:
        return Split(KIND_WHOLE, [], [])
    # `--no-split` is taken at its word: the file as it is, whatever it holds.
    if not active:
        return _whole_file(segments)
    # Too short for a collection, so no call; the free net still applies, as a
    # textbook track opens on its number.
    if len(segments) < MIN_SEGMENTS or segments[-1].end < MIN_DURATION:
        return whole_block(segments, audio_path)

    silences = cuts.detect_silences(audio_path)
    message = _message(audio_path.name, segments, silences, limit)
    for attempt in range(ATTEMPTS):
        try:
            answer = client.chat_json(prompts.load("audio_split"), message)
            if not isinstance(answer, dict):
                raise ValueError(_("unexpected JSON structure: {kind}").format(
                    kind=type(answer).__name__))
            split = _read_answer(answer, segments, silences, limit)
            if split.unreadable and not split.blocks and not split.dropped:
                # Every block out of bounds: the answer lost the thread of the
                # file, which is no reason to take it whole.
                raise ValueError("no readable block")
        except ValueError:
            if attempt + 1 < ATTEMPTS:
                console.item(_("Splitting unreadable: {rank} attempt...").format(
                    rank=_(RANKS[attempt + 1])))
            continue
        if not split.blocks and not split.dropped:
            return whole_block(segments, silences=silences)
        return split

    console.failed(_("cannot split: file turned down."))
    return Split(KIND_FAILED, [], [])


# ── Display (structure only, never the content) ───────────────────────────────

# "01:12", or "1:03:20" past the hour: the console's shape, under the name the
# callers of this module use.
timestamp = console.duration

def label_for(reason: str, n: int) -> str:
    """The reason as it is displayed, agreed. An unknown reason goes through as it
    is: reading the answer has already brought them back to `REASONS`."""
    forms = LABELS.get(reason)
    if not forms:
        return reason
    return counted(n, *forms)


def summary(split: Split) -> str:
    """The splitting in one line: what is kept, what is not, why.

    One line, as a passage-by-passage detail becomes a wall on a shadowing book,
    and each kept passage's bounds show when it is generated. No Japanese and no
    translation: the card is there to make the audio discovered by listening.
    """
    if split.blocks:
        head = f"{len(split.blocks)} {console.plural(len(split.blocks), 'passage')}"
    else:
        head = _("no usable passage")

    parts = [head]
    if split.unreadable:
        # Counted, so a lost conversation does not pass for a choice; placed before
        # the refusals, whose detail after the colon would read it as one more reason.
        blocks = console.plural(split.unreadable, "unreadable block")
        parts.append(f"{split.unreadable} {blocks}")
    if split.dropped:
        tally: dict[str, int] = {}
        for one in split.dropped:
            tally[one.reason] = tally.get(one.reason, 0) + 1
        detail = listed(f"{n} {label_for(reason, n)}" for reason, n in
                        sorted(tally.items(), key=lambda c: -c[1]))
        parts.append(f"{len(split.dropped)} "
                     f"{console.plural(len(split.dropped), 'refusal')}"
                     f"{convention('colon', ': ')}{detail}")
    return listed(parts)


def show(split: Split) -> None:
    """Closes the "Splitting…" action on what it handed back.

    A failure was said on stderr, and "no usable passage" would make it a
    verdict on the content. A file taken whole says so too, or nothing would
    tell that the splitting was attempted.
    """
    # Opened here when called on its own: the splitting is an action like any other.
    if not console.is_open():
        console.action(_("Splitting"))
    if split.kind == KIND_FAILED:
        console.done(_("failed"))
    elif split.whole:
        console.done(_(KIND_WHOLE))
    elif split.kind == KIND_TRIMMED:
        # Neither "the whole file" (it was trimmed) nor "1 passage" (nothing was
        # cut): what happened is that an announcement was removed.
        console.done(_(KIND_TRIMMED))
    else:
        console.done(summary(split))
