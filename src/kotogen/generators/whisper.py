"""Whisper transcription: the model loaded or fetched, the wait watched, the result cached."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import warnings
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from kotogen import console, system
from kotogen.generators import audio_files
from kotogen.generators.audio_split import Segment
from kotogen.i18n import _, counted, quoted

# Fallback when the requested model cannot be loaded (memory, disk, download):
# it fits anywhere, and transcribes less faithfully, which is said.
WHISPER_FALLBACK = "small"


# ── Whisper transcription (with cache) ────────────────────────────────────────

def _load_whisper():
    try:
        import whisper  # type: ignore
    except ImportError:
        sys.exit(
            _("Missing package. Run: pip install -U openai-whisper\n"
              "   (FFmpeg is required too: {hint})").format(hint=system.ffmpeg_hint())
        )
    if shutil.which("ffmpeg") is None:
        sys.exit(
            _("FFmpeg not found in PATH (required by Whisper).\n"
              "   Install it: {hint}").format(hint=system.ffmpeg_hint())
        )
    return whisper


def _load_model(model_name: str):
    """Loads a Whisper model, and falls back on `small` if it does not fit.

    Returns (model, name of the model loaded), the second naming what the
    transcript is filed under. The loading is part of the "Transcribing..." wait
    and is not announced, save a first download (see `_Download`); the fallback
    always is, as it makes less faithful cards.
    """
    whisper = _load_whisper()
    try:
        return whisper.load_model(model_name), model_name
    except Exception as exc:
        if model_name == WHISPER_FALLBACK:
            raise
        console.failed(_("model {name} unavailable ({reason}): falling back on "
                         "{fallback}, transcription less faithful, so cards less "
                         "reliable.").format(name=quoted(model_name),
                                             reason=exc,
                                             fallback=quoted(WHISPER_FALLBACK)))
        return whisper.load_model(WHISPER_FALLBACK), WHISPER_FALLBACK


# ── Waiting on Whisper ────────────────────────────────────────────────────────
# One counter shows the progress (`medium` on a CPU runs at about real time) and
# catches a Whisper flaw: a window not ending on a closed utterance seeks back to
# the last timestamp ("seek to the last timestamp" in its `transcribe.py`), which
# may be 0.00, and the same thirty seconds are then decoded forever.

# The spectrogram frame is 10 ms (`whisper.audio.FRAMES_PER_SECOND`): it is the
# unit Whisper counts its progress in.
FRAMES_PER_SECOND = 100

# Windows decoded in place before calling it a stall. One proves nothing: the
# growing context may get the next decode out, but never after three in a row,
# and each costs a minute of computation.
STALL_MAX = 3


class _Trapped(RuntimeError):
    """Whisper keeps going over the same window: the wait has no end."""


class _Counter:
    """Fake tqdm: it draws nothing, it remembers where Whisper has got to.

    Whisper has no progress callback, but feeds its tqdm bar at every window,
    even with the bar switched off.
    """

    def __init__(self) -> None:
        self.frames = 0
        self.total = 0
        self.stalls = 0

    def __call__(self, total: int = 0, **_) -> _Counter:
        # Whisper builds its bar: `tqdm.tqdm(total=…, unit="frames")`.
        self.total = int(total or 0)
        return self

    def __enter__(self) -> _Counter:
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def update(self, frames: int = 1) -> None:
        """One more window is done. Zero frames: the cursor has not moved.

        Raising here stops the transcription in the thread that runs it, with
        nothing to kill.
        """
        if frames > 0:
            self.frames += frames
            self.stalls = 0
            return
        self.stalls += 1
        if self.stalls >= STALL_MAX:
            # Translated where raised: whoever catches it (a listening run, the
            # NHK cross-check) shows the message as it stands.
            raise _Trapped(_("Whisper is going back over the same window at {time}")
                           .format(time=console.duration(self.second)))

    @property
    def second(self) -> float:
        """The second of the audio the transcription has reached."""
        return self.frames / FRAMES_PER_SECOND

    def status(self) -> str:
        """What the animated line shows: where we are in the audio.

        Empty until Whisper knows the total, while it decodes the audio (where a
        damaged file holds ffmpeg silently): the spinner alone shows then.
        """
        if not self.total:
            return ""
        return _("{done} of {total}").format(
            done=console.duration(self.second),
            total=console.duration(self.total / FRAMES_PER_SECOND))


@contextmanager
def _counting(counter: _Counter):
    """Puts the counter in tqdm's place, for the length of the transcription.

    A no-op when `whisper.transcribe` holds no tqdm (a model faked by the tests,
    another Whisper version): the line stays mute. One transcription at a time,
    as the module has a single tqdm.
    """
    module = sys.modules.get("whisper.transcribe")
    before = getattr(module, "tqdm", None)
    if before is None:
        yield
        return
    module.tqdm = SimpleNamespace(tqdm=counter)
    try:
        yield
    finally:
        module.tqdm = before


# ── The model weights, which have to be fetched first ─────────────────────────
# The first run downloads the model's weights (1.4 GB for `medium`) before it
# decodes anything. The download shows at the end of the "Transcribing..." line,
# from when Whisper opens its bar to when it closes it.


class _Download:
    """Fake tqdm: it remembers how much of the model weights have arrived.

    Stands in for Whisper's own English bar ("100%|#####| 1.42G/1.42G"), so the
    size shows on our line, in the units of the rest of the output.
    """

    def __init__(self) -> None:
        self.received = 0
        self.total = 0

    def __call__(self, total: int = 0, **_) -> _Download:
        # Whisper builds its bar: `tqdm(total=…, unit="iB", …)`.
        self.received, self.total = 0, int(total or 0)
        return self

    def __enter__(self) -> _Download:
        return self

    def __exit__(self, *_exc) -> bool:
        # What remains (checksum, loading into torch) waits on the spinner alone.
        self.total = 0
        return False

    def update(self, received: int = 1) -> None:
        self.received += received

    def status(self) -> str:
        """What the animated line shows, or nothing while there is nothing to say.

        "once only": the gigabyte is not the price of every transcription.
        """
        if not self.total:
            return ""
        return _("model to download once only, {done} of {total}").format(
            done=console.size(self.received), total=console.size(self.total))


@contextmanager
def _watching(whisper, download: _Download):
    """Puts the watcher in tqdm's place, for the length of the model loading.

    A no-op without a tqdm to replace, as in `_counting`.
    """
    if getattr(whisper, "tqdm", None) is None:
        yield
        return
    before = whisper.tqdm
    whisper.tqdm = download
    try:
        yield
    finally:
        whisper.tqdm = before


def _load(model_name: str):
    """Loads the model while holding the action line: the wait is visible.

    Returns what `_load_model` does. `whisper` is imported inside the worker,
    under the spinner: importing torch takes seconds.
    """
    download = _Download()

    def load():
        whisper = _load_whisper()
        with _watching(whisper, download):
            return _load_model(model_name)

    return console.while_working(load, download.status)


def _whisper(model, audio_path: Path, *, context: bool) -> dict:
    """The call itself.

    `word_timestamps=True` lets the split cut the announced number off the first
    reply, often in the same segment (`4 あっそれ`). `context` carries text from
    one window to the next: more faithful, but what locks a stall in.
    """
    with warnings.catch_warnings():
        # Whisper warns that FP16 does not exist on CPU: of no interest here.
        warnings.simplefilter("ignore", UserWarning)
        # verbose=None, not False: False shows the tqdm bar, None silences
        # Whisper yet still feeds the bar the counter stands in for.
        return model.transcribe(
            str(audio_path), language="ja", verbose=None, word_timestamps=True,
            condition_on_previous_text=context,
        )


def _watched_transcribe(model, audio_path: Path) -> dict:
    """Transcribes while watching: the line lives, and a stall has a way out.

    After a stall, the file is transcribed again without the context that caused
    it; a second stall raises, and the caller drops the file.
    """
    counter = _Counter()
    try:
        with _counting(counter):
            return console.while_working(partial(_whisper, model, audio_path,
                                                 context=True), counter.status)
    except _Trapped:
        console.aside(_("Whisper is going round in circles: retrying without context"))

    counter = _Counter()
    with _counting(counter):
        return console.while_working(partial(_whisper, model, audio_path,
                                             context=False), counter.status)


def _cache_key(audio_path: Path) -> str:
    """Name of the file where the transcription of an audio is filed.

    Keyed on the full path, as two folders may each hold a `01.mp3`.
    """
    path = hashlib.sha256(str(audio_path.resolve()).encode("utf-8")).hexdigest()
    return f"{audio_files._readable(audio_path.stem)}_{path[:audio_files.FINGERPRINT_LEN]}.json"


def _filed(cache_file: Path) -> dict[str, list]:
    """The transcripts filed for one audio, by the name of the model that made them.

    Empty when there is none or the file does not read; any other shape, a bare
    list say, is ignored and made again.
    """
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {name: entries for name, entries in raw.items() if isinstance(entries, list)}


def _transcribe(audio_path: Path, model_name: str, model_cache: dict,
                work_dir: Path, source: Path | None = None) -> list[Segment]:
    """Transcribes an audio into timestamped segments.

    Cached in `work_dir`, which the caller picks: the run's temporary folder,
    or a downloaded source's cache folder, kept between runs. Filed under
    `source`, the medium the audio was extracted from (a video), else the audio
    itself, and under the model that made it, the fallback included, so that
    `small`'s is never served to a `large` run. An empty transcript is filed
    too: the same model hears the same nothing. `model_cache` holds what
    `_load` returned, by name asked.
    """
    cache_file = work_dir / _cache_key(source or audio_path)
    filed = _filed(cache_file)

    # Opened before the model loads: loading is part of the wait, and on a first
    # run the download is most of it.
    console.action(_("Transcribing"))
    # The model asked for first, even once this run has fallen back: what an
    # earlier run filed under it is worth more than the fallback's.
    entries = filed.get(model_name)
    if entries is None and model_name in model_cache:
        entries = filed.get(model_cache[model_name][1])
    if entries is None:
        if model_name not in model_cache:
            model_cache[model_name] = _load(model_name)
        model, made_by = model_cache[model_name]
        entries = filed.get(made_by)
    if entries is not None:
        segments = [Segment.from_whisper(s) for s in entries]
        console.done(counted(len(segments),
                             "{count} utterance, already done",
                             "{count} utterances, already done")
                     .format(count=len(segments))
                     if segments else _("empty, already done"))
        return segments

    result = _watched_transcribe(model, audio_path)
    segments = [Segment.from_whisper(seg) for seg in result["segments"]
                if str(seg.get("text", "")).strip()]

    console.done(f"{len(segments)} {console.plural(len(segments), 'utterance')}"
                 if segments else _("empty"))

    filed[made_by] = [s.as_dict() for s in segments]
    try:
        system.write_whole(cache_file, json.dumps(filed, ensure_ascii=False))
    except OSError as exc:
        # The transcript serves this run all the same.
        console.failed(_("transcript not kept for the next run ({reason})")
                       .format(reason=console.reason(exc)))
    return segments
