"""Fate of the audio files at the end of a generation, and the name they go out under.

The media follow the cards: nothing enters Anki's media library while the cards
wait in a TSV to import by hand. Each file gets a name of its own, as Anki keeps
every deck's media in one folder: a later `01.mp3` would overwrite an earlier one.
"""

import argparse
import re
from pathlib import Path

import pytest

from kotogen import exporter, seen
from kotogen.anki import send as anki_send
from kotogen.generators import audio, audio_files, nhk


def args_for(send: bool) -> argparse.Namespace:
    return argparse.Namespace(send=send, deck="Test", notetype="Audio")


CARDS = [{"ID": "a_001", "Question": "Pourquoi ?"}]


def _finish(monkeypatch, media, *, send, left_out=None):
    """Runs _finish_audio with the two observed side effects isolated."""
    installed: list[list[Path]] = []
    sent: list[bool] = []

    def fake_install(paths, renamed=None):
        installed.append(list(paths))
        return list(left_out or [])

    def fake_send(*a, **k):
        sent.append(True)
        return (len(CARDS), 0), ""

    monkeypatch.setattr(anki_send, "install_media_files", fake_install)
    monkeypatch.setattr(anki_send, "send_cards", fake_send)
    audio._finish_audio(CARDS, Path("out.tsv"), media, args_for(send))
    return installed, sent


def test_with_no_send_the_audio_stays_outside(monkeypatch, capsys, tmp_path):
    media = [tmp_path / "nhk_x.mp3"]
    installed, _ = _finish(monkeypatch, media, send=False)
    out = capsys.readouterr().out
    assert installed == []          # the media library is not touched
    assert "nhk_x.mp3" in out       # but the user knows what to drop there
    assert "collection.media" in out


def test_with_a_send_the_audio_joins_the_media_library(monkeypatch, tmp_path):
    """Without their audio, cards sent into Anki would be mute."""
    media = [tmp_path / "nhk_x.mp3"]
    installed, sent = _finish(monkeypatch, media, send=True)
    assert installed == [media]
    assert sent == [True]


def test_files_left_outside_are_named_again(monkeypatch, capsys, tmp_path):
    left = tmp_path / "nhk_y.mp3"
    _finish(monkeypatch, [left], send=True, left_out=[left])
    assert "nhk_y.mp3" in capsys.readouterr().out


def test_no_audio_no_reminder(monkeypatch, capsys):
    _finish(monkeypatch, [], send=False)
    assert "collection.media" not in capsys.readouterr().out


# ── Names of the files dropped ───────────────────────────────────────────────

def test_two_different_sounds_never_carry_the_same_name(tmp_path):
    """The case that really happens: `01.mp3` in two past-paper folders."""
    out = tmp_path / "out"
    out.mkdir()
    names = set()
    for folder, sound in (("papers2019", b"one"), ("papers2023", b"two")):
        src = tmp_path / folder
        src.mkdir()
        file = src / "01.mp3"
        file.write_bytes(sound)
        names.add(audio._copy_whole(file, out).name)

    assert len(names) == 2


def test_the_same_sound_seen_again_does_not_pile_up(tmp_path):
    """A fingerprint, not a random draw: a rerun drops no extra copy."""
    src = tmp_path / "01.mp3"
    src.write_bytes(b"one")
    out = tmp_path / "out"
    out.mkdir()

    first = audio._copy_whole(src, out)
    second = audio._copy_whole(src, out)

    assert first == second
    assert len(list(out.iterdir())) == 1


def test_a_file_we_have_already_named_is_not_copied_again(tmp_path):
    """Replaying a pass over its own output must not copy onto itself."""
    out = tmp_path / "out"
    out.mkdir()
    src = out / "01.mp3"
    src.write_bytes(b"one")

    dropped = audio._copy_whole(src, out)
    assert audio._copy_whole(dropped, out) == dropped
    assert dropped.read_bytes() == b"one"


@pytest.mark.parametrize("stem, expected", [
    ("Résumé 3 (final)", "Résumé_3_final"),   # the name ends up in an src= attribute
    ("第3回", "第3回"),                      # Japanese bothers neither Anki nor the HTML
    ("...", "audio"),                        # a name that leaves nothing stays nameable
])
def test_the_readable_name_does_not_break_the_card(stem, expected):
    assert audio_files._readable(stem) == expected


def test_the_readable_name_is_bounded():
    """Windows paths cap out, and the Anki profile is already deep."""
    assert len(audio_files._readable("a" * 200)) == audio_files.READABLE_MAX


def test_an_interrupted_extract_still_says_it_was_interrupted(tmp_path, monkeypatch):
    """After a Ctrl+C, Windows may refuse to delete the draft ffmpeg still holds
    (WinError 32): that refusal must not replace the interruption."""
    def interrupted(draft):
        draft.write_bytes(b"half")
        raise KeyboardInterrupt

    def held(self, missing_ok=False):
        raise PermissionError(32, "in use by another process")

    monkeypatch.setattr(Path, "unlink", held)
    with pytest.raises(KeyboardInterrupt):
        audio._write_extract(tmp_path / "lesson.mp3", tmp_path, 1, ".mp3", interrupted)


def test_a_name_cut_on_a_separator_reads_the_same_twice():
    """`maintain` finds a passage again by the readable part of its media name."""
    stem = "a" * (audio_files.READABLE_MAX - 1) + " lesson two"
    once = audio_files._readable(stem)

    assert not once.endswith("_")
    assert audio_files._readable(once) == once


def test_an_extract_carries_the_fingerprint_of_what_was_encoded(tmp_path, monkeypatch):
    """The fingerprint is taken on the file PRODUCED: two splits of the same
    collection that do not hand back the same sound cannot be confused."""
    sounds = iter([b"passage one", b"passage two"])
    monkeypatch.setattr(nhk, "transcode_spans_to_mp3",
                        lambda src, dest, spans, level: dest.write_bytes(next(sounds)))

    src = tmp_path / "collection.mp3"
    src.write_bytes(b"")
    block = type("B", (), {"spans": lambda self: [(0.0, 1.0)]})()

    one = audio._extract_span(src, block, 1, tmp_path, "48k")
    two = audio._extract_span(src, block, 2, tmp_path, "48k")

    assert one.name.startswith("collection_01_") and two.name.startswith("collection_02_")
    assert one.stem[-audio_files.FINGERPRINT_LEN:] != two.stem[-audio_files.FINGERPRINT_LEN:]
    # No draft left behind: the TSV folder is not a cache.
    assert not [f for f in tmp_path.iterdir() if f.name.startswith(".kotogen_")]


def test_an_extract_that_fails_leaves_no_draft(tmp_path, monkeypatch):
    def breaks(src, dest, spans, level):
        dest.write_bytes(b"incomplete")
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(nhk, "transcode_spans_to_mp3", breaks)
    src = tmp_path / "collection.mp3"
    src.write_bytes(b"")
    block = type("B", (), {"spans": lambda self: [(0.0, 1.0)]})()

    with pytest.raises(RuntimeError):
        audio._extract_span(src, block, 1, tmp_path, "48k")
    assert list(tmp_path.iterdir()) == [src]


def test_two_nhk_articles_with_no_identifier_are_not_confused():
    """One fallback name for all would give them the same audio and card IDs."""
    a = nhk._media_id("https://news.web.nhk/news/easy/article-a/")
    b = nhk._media_id("https://news.web.nhk/news/easy/article-b/")
    assert a != b
    # The article identifier itself stays empty: it is compared to the site's.
    assert nhk._article_id("https://news.web.nhk/news/easy/article-a/") == ""


# ── A video file comes in by its sound track ──────────────────────────────────

def test_a_video_is_picked_up_like_an_audio(tmp_path):
    """A drama folder is a listening source, just like a folder of mp3."""
    for name in ("ep1.mkv", "ep2.mp3", "notes.txt", "ep3.srt"):
        (tmp_path / name).write_bytes(b"")

    found = [p.name for p in audio_files._collect_audio_files([tmp_path])]

    assert found == ["ep1.mkv", "ep2.mp3"], "neither the text nor the subtitle"


# ── A shelf of series: walked down, and remembered ────────────────────────────

def _shelf(root: Path) -> None:
    """Two series, each keeping its episodes in a folder of its own."""
    for series, episodes in (("Ma Serie", ("ep01.mkv", "ep02.mkv")),
                             ("Autre Serie", ("ep01.mkv",))):
        (root / series).mkdir()
        for name in episodes:
            (root / series / name).write_bytes(b"x" * 10)


def test_a_folder_of_folders_is_walked_down(tmp_path):
    """A shelf holds one folder per series, the episodes a level below: the
    first level alone holds no audio file."""
    _shelf(tmp_path)

    found = audio_files._collect_audio_files([tmp_path])

    assert [f.name for f in found] == ["ep01.mkv", "ep01.mkv", "ep02.mkv"]
    # A series arrives whole, and its episodes in their order.
    assert [f.parent.name for f in found] == [
        "Autre Serie", "Ma Serie", "Ma Serie"]


def test_a_series_names_the_cards_of_its_episodes(tmp_path):
    """"ep02.mkv" says nothing six months later; the folder it sits in does."""
    _shelf(tmp_path)
    episode = tmp_path / "Ma Serie" / "ep02.mkv"

    assert audio_files._label(episode, [tmp_path]) == "Ma Serie - ep02.mkv"
    # Named itself, or found in the series folder named: the label is its name alone.
    assert audio_files._label(episode, [episode]) == "ep02.mkv"
    assert audio_files._label(episode, [tmp_path / "Ma Serie"]) == "ep02.mkv"


def test_a_folder_takes_up_where_it_left_off(tmp_path):
    """Run again every week, a shelf is worked through and not replayed."""
    _shelf(tmp_path)
    files = audio_files._collect_audio_files([tmp_path])
    seen.mark("audio", audio_files.FILES_SOURCE, audio_files._file_id(files[0]),
              files[0].name)

    left, skipped = audio_files._files_to_do(files, [tmp_path], None)

    assert [f.parent.name for f in left] == ["Ma Serie", "Ma Serie"]
    assert skipped == 1


def test_a_file_named_by_hand_ignores_the_history(tmp_path):
    """The one way to redo a file, as passing its URL redoes an NHK article."""
    _shelf(tmp_path)
    episode = tmp_path / "Ma Serie" / "ep01.mkv"
    seen.mark("audio", audio_files.FILES_SOURCE, audio_files._file_id(episode), episode.name)

    left, skipped = audio_files._files_to_do([episode], [episode], None)

    assert left == [episode]
    assert skipped == 0


def test_latest_takes_the_first_few_of_what_is_left(tmp_path):
    """Otherwise two hundred episodes go, and are paid for, in one pass."""
    _shelf(tmp_path)
    files = audio_files._collect_audio_files([tmp_path])

    left, skipped = audio_files._files_to_do(files, [tmp_path], 2)

    assert len(left) == 2
    assert skipped == 0
    # Without a count the folder goes whole, as textbook dialogues should.
    assert len(audio_files._files_to_do(files, [tmp_path], None)[0]) == 3


def test_a_file_replaced_comes_back_as_new(tmp_path):
    """The history keys on the weight as much as on the name: an episode
    re-encoded or downloaded again is not the one that was handled."""
    _shelf(tmp_path)
    episode = tmp_path / "Ma Serie" / "ep01.mkv"
    before = audio_files._file_id(episode)

    episode.write_bytes(b"x" * 20)

    assert audio_files._file_id(episode) != before


# ── A series of episodes ──────────────────────────────────────────────────────

def _videos(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"x")


@pytest.mark.parametrize("names", [
    ("[Group] Series - 03 (1080p) [A1B2C3D4].mkv",
     "[Group] Series - 04 (1080p) [E5F6A7B8].mkv"),
    ("Show - S01E01 - Pilot.mkv", "Show - S01E02 - The Return.mkv"),
    ("シリーズ 第01話「はじまり」.mkv", "シリーズ 第02話「旅立ち」.mkv"),
    ("ep01.mkv", "ep02.mkv"),
    ("01.mp4", "02.mp4"),
])
def test_numbered_episodes_make_a_series(tmp_path, names):
    """The group, the resolution and the checksum change from one file to the
    next, and so does a title; the series and the number are what is read."""
    _videos(tmp_path, *names)

    assert audio_files.is_series(tmp_path)


def test_a_shelf_is_a_series(tmp_path):
    _shelf(tmp_path)

    assert audio_files.is_series(tmp_path)


@pytest.mark.parametrize("names", [
    ("vacances.mp4", "IMG_2034.mp4", "IMG_2051.mp4", "anniversaire 2024.mkv",
     "3D demo.mp4"),
    ("ep01.mkv",),
    ("Show - S01E01.mkv", "Show - S02E01.mkv"),
])
def test_videos_put_together_are_not_a_series(tmp_path, names):
    """Five videos with nothing in common, a single episode, or the first
    episode of two seasons: nothing there to work through a few at a time."""
    _videos(tmp_path, *names)

    assert not audio_files.is_series(tmp_path)


def test_numbered_audio_files_are_not_a_series(tmp_path):
    """A textbook CD numbers its tracks, and they go whole."""
    _videos(tmp_path, "01.mp3", "02.mp3", "03.mp3")

    assert not audio_files.is_series(tmp_path)


def test_the_episodes_left_are_counted_as_the_run_counts_them(tmp_path):
    _shelf(tmp_path)
    files = audio_files._collect_audio_files([tmp_path])
    seen.mark("audio", audio_files.FILES_SOURCE, audio_files._file_id(files[0]), files[0].name)

    assert audio_files.episodes_left(tmp_path) == 2
    assert audio_files.episodes_left(files[1]) is None, "a file is not a series"


def test_the_track_is_extracted_without_the_picture(monkeypatch, tmp_path):
    """`-vn` goes AFTER the input, where ffmpeg reads it as an output option:
    without it a copy keeps the video track, and a re-encode the cover art."""
    seen: dict = {}

    def fake_write(input_args, probe_src, out_dir, stem, level, *, stream="a:0"):
        seen.update(args=list(input_args), stem=stem)
        return out_dir / f"{stem}.m4a"

    monkeypatch.setattr(nhk, "_write_audio", fake_write)
    monkeypatch.setattr(nhk, "probe_audio_tracks", lambda src: [("jpn", "")])
    video = tmp_path / "my episode.mkv"
    video.write_bytes(b"")

    track, _ = audio_files._extract_track(video, tmp_path, "none")

    assert seen["args"] == ["-i", str(video), "-vn"]
    # The name ends up in a `src` attribute: it goes through the media's filter.
    assert " " not in track.name


# ── Anki has to be able to find the file again from the field ─────────────────
#
# Anki finds media only through `[sound:…]` or an img/audio/video tag in a
# note's fields: a bare file name would be "unused" to the media check, and
# left out of an .apkg export.

# What Anki looks for, roughly: a media tag and a file in its `src`. Enough to
# fail when a field stops carrying one; not Anki's exact rule.
ANKI_REFERENCE = re.compile(
    r"""<(?:img|audio|video|object)\b[^>]*\b(?:src|data)\s*=\s*["']?([^"'\s>]+)""",
    re.IGNORECASE)


def _ai_answer():
    return {"Cards": [{"Question": "Où va-t-il ?", "Answer": "À Kyoto",
                       "Decoys": ["À Osaka", "À Nara", "À Kobe"], "KeyLine": 1}],
            "TranscriptLines": ["京都[きょうと]へ 行[い]きます。"],
            "TranslationLines": ["Je vais à Kyoto."]}


@pytest.mark.parametrize("is_video, field, name", [
    (False, "Audio", "ep_01_a1b2c3d4.mp3"),
    (True, "Video", "ep_01_a1b2c3d4.webm"),
])
def test_the_media_field_names_its_file_the_way_anki_expects(is_video, field, name):
    cards = audio._post_process(_ai_answer(), name, "ep_01", "N4",
                                is_video=is_video)

    found = ANKI_REFERENCE.search(cards[0][field])
    assert found, f"the {field} field carries no tag: {cards[0][field]!r}"
    assert found.group(1) == name


def test_the_past_paper_figure_is_named_the_same_way():
    answer = _ai_answer()
    answer["Cards"][0]["Figure"] = True
    cards = audio._post_process(answer, "ex.mp3", "ex", "N4",
                                figure="ex_2f3a4b5c.png")

    found = ANKI_REFERENCE.search(cards[0]["Image"])
    assert found and found.group(1) == "ex_2f3a4b5c.png"
    # No figure, no tag: an empty `<img>` would be a missing image.
    without = audio._post_process(_ai_answer(), "ex.mp3", "ex", "N4")
    assert without[0]["Image"] == ""


@pytest.mark.parametrize("field", ["Audio", "Video", "Image", "Images"])
def test_the_export_does_not_strip_the_media_fields(field):
    """The export clean-up strips the tags of every field but those.

    It runs last, for both the TSV and the send: a media tag stripped here
    leaves a mute card.
    """
    tag = exporter.audio_ref("x.mp3")
    assert exporter._field_value(field, tag) == tag
    # An ordinary field does lose its HTML.
    assert exporter._field_value("Question", tag) == ""
