"""The `audio` action on a listening card: is it badly HEARD?

One pass for an extract cut mid-sentence, a transcript that differs from the
sound and `Timecodes` that drifted. Whisper hears the extract again with a margin
taken from its recording, found by the readable name the extract carries
(`<name>_<rank>_<fingerprint>`); the bounds are laid again in the silences as
`audio_split` lays them, the model rewrites the transcript, and the instants come
from Whisper's timestamps. Without the recording, the bounds cannot move; nor can
they on an extract made of pieces, but a past paper's then loses the reading time
left inside it.

In automatic mode, a change that leaves a question of the passage without its
answer is not made, and the flag stays. What the card says, and what the model
writes of what is heard, is the library's (`maintenance.listening`).
"""

from __future__ import annotations

import tempfile
import unicodedata
from pathlib import Path

from kotogen import audio_quality, console, system
from kotogen.ai_client import AIAuthError, AIClient
from kotogen.anki.connect import EditorOpen
from kotogen.anki.maintain.flag_pass import unmark
from kotogen.anki.maintain.marks import ai_failed, apply_changes, passage_of, tally
from kotogen.anki.media import install_media_files, media_dir
from kotogen.exporter import ask_choice, audio_ref, short, video_ref
from kotogen.generators import (
    audio as audio_gen,
    audio_files,
    audio_split,
    cuts,
    jlpt_papers,
    timecodes,
    whisper,
)
from kotogen.i18n import _, convention, counted, quoted
from kotogen.maintenance.kinds import CardKind
from kotogen.maintenance.listening import (
    Heard,
    Media,
    Rewrite,
    ask_transcript,
    bounds_of,
    media_of,
    recut,
    same_instants,
    with_bounds,
    without_reading_time,
)
from kotogen.maintenance.review import _field, _passage_stem, auto_line, card_name, field_lines

# Seconds heard on each side of the extract: a spoken sentence rarely runs past
# ten, so the one the cut went through is heard whole, with its silences.
MARGIN = 15.0

# The Whisper model: the one `kotogen audio` uses by default, since its mistakes
# end up in the cards.
WHISPER_MODEL = "medium"

# How far a bound may drift before it is said to have moved: the bounds of the
# `Source` field are to the second.
_MOVED = 1.0

# How much shorter than its bounds an extract is when the split left something
# out inside it (an exam question): past the second each rounded bound may lose.
_PIECES = 1.5


# The folders named during this run, searched for every later passage.
_folders: list[Path] = []


def locate(media: Media, folders: list[Path] | None = None) -> Path | None:
    """The recording an extract was cut from, looked for by its readable name.

    In the cache first, where downloads are kept, then in the folders named
    during the run. A video extract needs a video; a sound extract takes either.
    """
    wanted = (audio_files.VIDEO_EXTENSIONS if media.video
              else audio_files.MEDIA_EXTENSIONS)
    readable = _comparable(media.readable)
    for root in [system.cache_dir(), *(_folders if folders is None else folders)]:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if (path.suffix.lower() in wanted and path.is_file()
                    and _comparable(audio_files._readable(path.stem)) == readable):
                return path
    return None


def _comparable(name: str) -> str:
    """A media name as Anki may have stored it: lowercased and in NFC (see `anki.media`)."""
    return unicodedata.normalize("NFC", name).casefold()


def _ask_where(media: Media) -> Path | None:
    """Asks for the recording once; the folder given is searched for the others."""
    print("   " + _("Where is the recording {name} was cut from? A file or a folder, "
                    "empty to go on without it.").format(name=quoted(media.readable)))
    try:
        answer = console.read_line().strip().strip('"')
    except EOFError:
        return None
    if not answer:
        return None
    path = Path(answer).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        _folders.append(path)
        return locate(media, [path])
    return None


def _media_path(media: Media) -> Path | None:
    folder = media_dir()
    path = folder / media.name if folder else None
    return path if path and path.is_file() else None


def in_pieces(media: Media, bounds: tuple[float, float] | None) -> bool:
    """Whether the extract is shorter than its bounds: pieces glued back together.

    Cut again in one span from the recording, it would get back what the split
    left out between them, a past paper's exam question.
    """
    extract = _media_path(media)
    if bounds is None or extract is None:
        return False
    from kotogen.generators import nhk  # late import (nhk drags the browser)
    length = nhk.probe_duration(extract)
    return length is not None and (bounds[1] - bounds[0]) - length > _PIECES


def hear(media: Media, bounds: tuple[float, float] | None, recording: Path | None,
         work: Path, models: dict, paper: bool = False) -> Heard | None:
    """Hears the extract again, with its margins when the recording is there.

    `paper`: the extract comes from a past paper, and one heard as it stands
    loses the reading time left in it.
    """
    level = audio_quality.resolve(None)
    if recording is not None and bounds is not None and media.rank:
        sound = recording
        if recording.suffix.lower() in audio_files.VIDEO_EXTENSIONS:
            sound, _note = audio_files._extract_track(recording, work, level)
        offset = max(0.0, bounds[0] - MARGIN)
        window = work / "window.mp3"
        from kotogen.generators import nhk  # late import (nhk drags the browser)
        nhk.transcode_spans_to_mp3(sound, window,
                                   [(offset, bounds[1] + MARGIN - offset)], level)
        segments = whisper._transcribe(window, WHISPER_MODEL, models, work)
        block = recut(segments, bounds[0] - offset, bounds[1] - offset,
                      cuts.detect_silences(window))
        if block is not None:
            moved = (abs(block.start + offset - bounds[0]) > _MOVED
                     or abs(block.end + offset - bounds[1]) > _MOVED)
            return Heard(window, offset, sound, segments, block, moved)
    extract = _media_path(media)
    if extract is None:
        return None
    segments = whisper._transcribe(extract, WHISPER_MODEL, models, work)
    block = None
    if paper and media.rank and not media.video:
        from kotogen.generators import nhk  # late import (nhk drags the browser)
        length = nhk.probe_duration(extract)
        if length:
            block = without_reading_time(segments, cuts.detect_silences(extract), length)
    return Heard(extract, 0.0, None, segments, block, trimmed=block is not None)


# ── The new extract ───────────────────────────────────────────────────────────

def _encode(media: Media, recording: Path, heard: Heard, work: Path) -> Path:
    """The new extract, named as the generation names it, in `work`."""
    from kotogen.generators import nhk  # late import (nhk drags the browser)

    start = heard.offset + heard.block.start
    spans = [(start, heard.block.end - heard.block.start)]
    rank = int(media.rank)
    if media.video:
        track = nhk.japanese_track(nhk.probe_audio_tracks(recording))
        return audio_gen._write_extract(
            recording, work, rank, Path(media.name).suffix,
            lambda dest: nhk.transcode_spans_to_clip(recording, dest, spans, track))
    # Cut from the track heard rather than the recording, whose picture, for a
    # video, has no place in an mp3.
    sound = heard.sound or recording
    level = audio_quality.resolve(None)
    return audio_gen._write_extract(
        recording, work, rank, ".mp3",
        lambda dest: nhk.transcode_spans_to_mp3(sound, dest, spans, level))


def _trim(media: Media, heard: Heard, work: Path) -> Path:
    """The extract without its reading time, cut from the extract itself."""
    from kotogen.generators import nhk  # late import (nhk drags the browser)

    level = audio_quality.resolve(None)
    # Named after its recording as the generation names it, so that a later pass
    # finds the recording again.
    return audio_gen._write_extract(
        Path(media.readable + ".mp3"), work, int(media.rank), ".mp3",
        lambda dest: nhk.transcode_spans_to_mp3(heard.audio, dest, heard.block.spans(), level))


def _install(path: Path) -> str | None:
    """Puts the new extract into Anki; the name Anki kept, or None."""
    renamed: dict[str, str] = {}
    if install_media_files([path], renamed):
        return None
    return renamed.get(path.name, path.name)


# ── The pass ──────────────────────────────────────────────────────────────────

def process(client: AIClient, cards: list[dict], notes_by_id: dict[int, dict],
            kind: CardKind, auto: bool) -> tuple[int, int]:
    """Handles every card of the flag. Hands back (cards changed, flags removed).

    The flagged cards of one passage are heard once: it is the extract that is
    badly heard, not one question of it.
    """
    start = tally.start()
    models: dict = {}
    by_passage: dict[str, list[dict]] = {}
    for card in cards:
        note = notes_by_id.get(card["note"])
        if note is not None:
            by_passage.setdefault(_passage_stem(note) or str(note["id"]), []).append(card)
    for flagged in by_passage.values():
        note = notes_by_id[flagged[0]["note"]]
        if not auto:
            console.space()
            print("── " + _("note {id}").format(id=note['id']) + " ──────────────────────────────────")
            print(f"   {kind.label}{convention('colon', ': ')}{card_name(note)}")
        try:
            settled = _passage(client, note, kind, auto, notes_by_id, models)
        except (AIAuthError, ConnectionError, EditorOpen):
            raise
        except Exception as exc:
            # FFmpeg, Whisper or a write Anki refused: the model's failures are
            # said as such inside `_passage`.
            where = card_name(note) + convention("colon", ": ") if auto else ""
            console.failed(_("Hearing the passage again failed: {where}{error}").format(
                where=where, error=console.reason(exc)))
            continue
        if settled:
            for card in flagged:
                unmark(card["cardId"])
                tally.cleared += 1
    return tally.since(start)


def _passage(client: AIClient, note: dict, kind: CardKind, auto: bool,
             known: dict[int, dict], models: dict) -> bool:
    """Hears one passage again; True when its flags are to come off."""
    media = media_of(note)
    if media is None:
        if auto:
            auto_line("!", note, _("no sound on this card, flag kept"))
        else:
            print("   ! " + _("no sound on this card: nothing to hear again"))
        return False
    bounds = bounds_of(_field(note, "Source"))
    pieced = bool(media.rank) and in_pieces(media, bounds)
    recording = None
    if media.rank and not pieced:
        recording = locate(media) if media.readable else None
        if recording is None and not auto:
            recording = _ask_where(media)

    with tempfile.TemporaryDirectory(prefix="kotogen_") as tmp:
        work = Path(tmp)
        heard = hear(media, bounds, recording, work, models,
                     jlpt_papers.names_a_paper(_field(note, "Source")))
        if heard is None:
            line = _("the sound of this card is not in Anki's media folder, flag kept")
            if auto:
                auto_line("!", note, line)
            else:
                print("   ! " + line)
            return False
        if (heard.block is None or heard.trimmed) and media.rank:
            if pieced:
                why = _("the extract is made of pieces: it is heard as it stands, "
                        "its bounds cannot move")
            elif recording is None:
                why = _("recording not found: the extract is heard as it stands, "
                        "its bounds cannot move")
            elif bounds is None:
                why = _("the Source field gives no bounds: the extract is heard as it "
                        "stands, its bounds cannot move")
            else:
                why = _("the extract was not found again in its recording: it is heard "
                        "as it stands, its bounds cannot move")
            print("   ! " + why)

        questions = [note, *passage_of(note, kind, known)]
        try:
            rewrite = ask_transcript(client, heard, questions)
        except AIAuthError:
            raise
        except Exception as exc:
            ai_failed(exc, note if auto else None)
            return False
        if rewrite is not None and rewrite.refused:
            for line in rewrite.refused:
                print("   ! " + line)
            if auto:
                auto_line("!", note, _("transcript turned down, flag kept"))
            return False
        if rewrite is None:
            rewrite = Rewrite(field_lines(_field(note, "Transcript")),
                              field_lines(_field(note, "Translation")),
                              {n: _field(q, "KeyLine")
                               for n, q in enumerate(questions, 1)}, [])
        # The instants are worked out again whatever the model says: a right
        # transcript can still point its lines at the wrong second.
        stamps = timecodes.for_lines(rewrite.transcript, heard.segments, heard.block,
                                     whole=heard.block is None)
        if (not heard.moved and not heard.trimmed
                and rewrite.transcript == field_lines(_field(note, "Transcript"))
                and same_instants(stamps, _field(note, "Timecodes"))):
            if auto:
                auto_line("=", note, _("heard right, flag removed"))
            else:
                print("   → " + _("The transcript says what the extract says."))
            return True
        _show(note, questions, heard, bounds, rewrite)
        if rewrite.lost and auto:
            auto_line("!", note, _("a question of the passage loses its answer, "
                                   "flag kept"))
            return False
        if not auto and ask_choice(_("Apply? [y] yes  [n] cancel"), "yn") != "y":
            return False

        shared = {"Transcript": "<br>".join(rewrite.transcript),
                  "Translation": "<br>".join(rewrite.translation),
                  "Timecodes": stamps}
        # The old extract stays in the media folder: the snapshot taken before the
        # run plays it, and Anki's Tools > Check Media takes it once unused.
        if heard.moved and recording is not None:
            new_name = _install(_encode(media, recording, heard, work))
            if new_name is None:
                print("   ! " + _("the new extract did not reach Anki: nothing changed"))
                return False
            shared[media.field] = (video_ref if media.video else audio_ref)(new_name)
            start = heard.offset + heard.block.start
            shared["Source"] = with_bounds(_field(note, "Source"), start,
                                           heard.offset + heard.block.end)
        elif heard.trimmed:
            # Cut inside the extract: its bounds in the recording stay as they are.
            new_name = _install(_trim(media, heard, work))
            if new_name is None:
                print("   ! " + _("the new extract did not reach Anki: nothing changed"))
                return False
            shared[media.field] = audio_ref(new_name)

    # The bounds go to the cards whose `Source` says the same extract: one
    # edited by hand keeps what it says. Read before any write, since the first
    # card written is the flagged one.
    source = _field(note, "Source")
    changed = 0
    for n, question in enumerate(questions, 1):
        fields = {name: value for name, value in shared.items()
                  if name != "Source" or _field(question, "Source") == source}
        key = rewrite.key_lines.get(n, "")
        if key != _field(question, "KeyLine"):
            fields["KeyLine"] = key
        fields = {k: v for k, v in fields.items() if v != _field(question, k)}
        if fields:
            apply_changes(question["id"], fields, [], [])
            tally.changed += 1
            for name, value in fields.items():
                question["fields"][name] = value
            changed += 1
    if auto:
        auto_line("✓", note, counted(changed,
                                     "heard again, {count} card of the passage updated",
                                     "heard again, {count} cards of the passage updated")
                  .format(count=changed))
    else:
        print("   " + _("applied, flag removed"))
    return True


def _show(note: dict, questions: list[dict], heard: Heard,
          bounds: tuple[float, float] | None, rewrite: Rewrite) -> None:
    """The change, before it is made: the bounds, the lines, the questions."""
    if rewrite.reason:
        print("   " + _("Reason: {reason}").format(reason=console.clean(rewrite.reason)))
    if heard.moved and bounds is not None:
        start = heard.offset + heard.block.start
        end = heard.offset + heard.block.end
        print("   " + _("Extract: {old} -> {new}").format(
            old=f"{audio_split.timestamp(bounds[0])} → {audio_split.timestamp(bounds[1])}",
            new=f"{audio_split.timestamp(start)} → {audio_split.timestamp(end)}"))
    if heard.trimmed:
        for (_start, stop), (resume, _end) in zip(heard.block.ranges, heard.block.ranges[1:]):
            print("   " + _("Reading time cut out: {span}").format(
                span=f"{audio_split.timestamp(stop)} → {audio_split.timestamp(resume)}"))
    before = field_lines(_field(note, "Transcript"))
    if before != rewrite.transcript:
        print("   Transcript" + convention("colon", ": ").rstrip())
        for line in before:
            if line not in rewrite.transcript:
                print(f"      - {short(line)}")
        for line in rewrite.transcript:
            if line not in before:
                print(f"      + {short(line)}")
    for n in rewrite.lost:
        print("   ! " + _("question {n} loses its answer: {question}").format(
            n=n, question=quoted(card_name(questions[n - 1]))))
    others = len(questions) - 1
    if others:
        print("   = " + counted(others,
                                "{count} other card of the passage changes with it",
                                "{count} other cards of the passage change with it")
              .format(count=others))
