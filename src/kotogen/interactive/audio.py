"""The dialogue of `kotogen audio`: a local file, an NHK Easy article, a
podcast, a video or one of the catalogues, then the questions each one asks -
the episode, the length of the passages, whether the picture is kept."""

from __future__ import annotations

from pathlib import Path

from kotogen import audio_quality, video_clip
from kotogen.i18n import _, means
from kotogen.interactive.catalogues import _chosen_exam_papers, _chosen_irodori, _chosen_roudoku
from kotogen.interactive.screen import (
    _ask,
    _ask_auto_max,
    _ask_int,
    _ask_optional_seconds,
    _ask_yes_no,
    _Back,
    _columns,
    _header,
    _menu,
    _submenu,
)


def _audio_source() -> str:
    # One entry per source, not per way of aiming at it: which NHK article is
    # asked afterwards, as which episode is after the podcast. NHK Easy has a
    # line of its own, being the only article that carries sound.
    while True:
        choice = _menu(_("Listening cards - where does the audio come from?"),
                       _columns([
            ("nhk", _("NHK Easy articles"), _("text, furigana and sound from the site")),
            ("programme", _("A programme"),
             _("podcasts and YouTube channels, from N5 to N1")),
            ("book", _("A book"), _("いろどり textbook, literature read aloud")),
            ("jlpt", _("Official JLPT past papers"), _("the 聴解 sections, by level")),
            ("local", _("A local file"), _("audio or video, or a whole folder")),
        ]), default=1, allow_back=True, memory="audio")
        try:
            if choice == "programme":
                # Two catalogues, as thirty-three programmes do not fit one
                # screen. Keeping a video's picture is asked later
                # (`_ask_picture`), so the title only asks "which one".
                return _submenu(_("A programme - which one?"), [
                    ("podcast", _("A Japanese podcast"),
                     _("a score of predefined programmes, or the URL of a feed")),
                    # "A video", not "a channel": a channel is one way of aiming
                    # at a video, a pasted address another.
                    ("youtube", _("A YouTube video"),
                     _("twelve predefined channels, or the URL of a video")),
                ])
            if choice == "book":
                # Each entry names its shelf, as in `_reading_source`.
                return _submenu(_("A book - which one?"), [
                    ("irodori", "いろどり",
                     _("a Japan Foundation textbook, N5-N3 dialogues")),
                    ("roudoku", "青空朗読",
                     _("the public domain read aloud, N2-N1")),
                ])
        except _Back:
            # A clean page, or the menu redraws under the submenu left behind
            # (see `_deck_mode`).
            _header()
            continue
        return choice


# What stands for "the latest out" in the "which article" question, and for "the
# most recent" in the "which episode" one.
_LATEST_ANSWERS = ("the latest", "latest", "last", "l")
_NEXT_ANSWERS = ("the next one", "next", "n", "")


def _ask_article_nhk() -> str | None:
    """Question "which article": Enter (or "the latest") = the site's feed.

    None for the `nhk` keyword (the latest out, history included), the pasted URL
    otherwise: the counterpart of `_ask_episode_number`, with the same default.
    """
    while True:
        answer = _ask(_("Which article"), _("the latest"), back=True).strip()
        if (means(answer.lower(), _LATEST_ANSWERS, "latest")
                or answer.lower() == _("the latest")):
            return None
        if answer.startswith(("http://", "https://")):
            return answer
        print("   " + _("Answer expected: the URL of an NHK Easy article"
                        " (https://...), or Enter for the latest out."))


def _chosen_podcast() -> str:
    """Alias of the catalogue filed by level, or feed URL pasted by hand.

    The level is a column on the left rather than a heading per group, which
    would fill two screens; a programme with no level leaves its box empty.
    """
    from kotogen.generators import podcast

    options: list[tuple[str | None, str]] = [
        # The level flush left, to line the names up.
        (alias, f"{level:<7}{entry.name}")
        for level, entries in podcast.by_level()
        for alias, entry in entries
    ]
    options.append((None, ""))
    options.append(("url", _("Another podcast (paste the URL of its RSS feed)")))
    choice = _menu(_("Which podcast?"), options, default=1, allow_back=True)
    return (_ask(_("URL of the RSS feed"), back=True).strip()
            if choice == "url" else choice)


def _chosen_video() -> str:
    """Channel alias of the catalogue filed by level, or URL pasted by hand.

    A channel means "its latest video"; a URL may aim at a video, a channel or a
    playlist, and is the only way to a single video.
    """
    from kotogen.generators import youtube

    options: list[tuple[str | None, str]] = [
        # The level flush left to line the names up, as with the podcasts.
        (alias, f"{level:<7}{entry.name}")
        for level, entries in youtube.by_level()
        for alias, entry in entries
    ]
    options.append((None, ""))
    options.append(("url", _("Paste a URL (a video, a channel or a playlist)")))
    choice = _menu(_("Which video?"), options, default=1, allow_back=True)
    if choice != "url":
        return choice
    while True:
        url = _ask(_("YouTube URL"), back=True).strip()
        if url.startswith(("http://", "https://")):
            return url
        print("   " + _("Answer expected: a YouTube address (https://...) - a"
                        " video, a channel (/@name) or a playlist."))


def _ask_episode_number() -> int | None:
    """Question "which episode": Enter (or "latest") = the most recent.

    Right for a programme one follows, wrong for an archive taken up from the
    start, hence the question. No. 1 is the first episode published, in both ways
    of counting them (see `podcast._rank`).
    """
    while True:
        answer = _ask(_("Episode number"), _("latest"), back=True).lower()
        if means(answer, _LATEST_ANSWERS, "latest") or answer == _("latest"):
            return None
        if answer.isdigit() and int(answer) > 0:
            return int(answer)
        print("   " + _("Answer expected: an episode number (1 = the oldest),"
                        " or Enter for the most recent."))


def _ask_lesson_number() -> int | None:
    """Question "which lesson": Enter = the one where one left off.

    A textbook is followed in order: "the next one" is the first of the eighteen
    lessons that has given no cards yet.
    """
    while True:
        answer = _ask(_("Lesson number"), _("the next one"), back=True).lower()
        if means(answer, _NEXT_ANSWERS, "next") or answer == _("the next one"):
            return None
        if answer.isdigit() and 1 <= int(answer) <= 18:
            return int(answer)
        print("   " + _("Answer expected: a lesson number (1 to 18), or Enter"
                        " to take up where one left off."))


def _keeps_picture(answer: bool | None) -> bool | None:
    """Is the picture kept? The answer given, otherwise what the setting imposes.

    None only when nothing was asked and the setting says to ask, that is when no
    picture is at stake: the command then goes without a flag.
    """
    if answer is not None:
        return answer
    current = video_clip.mode()
    return None if current == "ask" else current == "always"


def _ask_picture() -> bool | None:
    """The question of the picture, asked here when the setting says to ask it.

    None when the setting has settled it ("always", "never"): the caller writes
    the flag. Asked here with the other questions rather than mid-run by the
    pipeline (`video_clip`), it leaves as `--video` / `--no-video`. The default
    is the sound alone, which costs nothing in the media library.
    """
    if video_clip.mode() != "ask":
        return None
    return _ask_yes_no(_("Keep the picture (otherwise the sound track alone)"))


def _holds_a_video(path: Path) -> bool:
    """Does this path put a picture at stake? A file by its suffix, a folder by
    what it holds - down to its sub-folders, like `audio_files._collect_audio_files`.

    Sub-folders count, since a shelf of series keeps its episodes there.
    """
    from kotogen.generators.audio_files import VIDEO_EXTENSIONS

    if path.is_dir():
        return any(f.suffix.lower() in VIDEO_EXTENSIONS for f in path.rglob("*"))
    return path.suffix.lower() in VIDEO_EXTENSIONS


def _audio_options(source: str) -> list[str]:
    argv = ["audio"]
    # None: not asked for this source (no video at stake, or settled by the
    # setting); the flag is decided at the end.
    picture: bool | None = None
    if source in ("nhk", "podcast"):
        if source == "nhk":
            # Asked only on the feed: a pasted URL is a single article.
            article = _ask_article_nhk()
            if article is not None:
                argv.append(article)
            else:
                argv.append("nhk")
                latest = _ask_int(_("Number of recent articles to handle"), 4)
                if latest != 4:
                    argv += ["--latest", str(latest)]
        elif source == "podcast":
            argv.append(_chosen_podcast())
            number = _ask_episode_number()
            if number is not None:
                argv += ["--episode", str(number)]
            # One episode by default: it weighs megabytes and takes minutes of
            # transcription, where an NHK article comes with its text.
            latest = _ask_int(
                _("Number of recent episodes to handle") if number is None
                else _("Number of episodes from no. {number} on").format(number=number),
                1)
            if latest != 1:
                argv += ["--latest", str(latest)]
        # NHK articles run from a minute to a quarter of an hour, as podcast
        # passages do: asked now rather than found out in the deck. No limit by
        # default, as it is a sorting, not a rule.
        limit = _ask_optional_seconds(_("Max duration of the audio, in seconds"))
        if limit is not None:
            argv += ["--max-duration", str(limit)]
    elif source in ("jlpt", "irodori", "roudoku"):
        if source == "jlpt":
            # A closed set of sections, an exam sat whole: nothing to ask.
            argv.append(_chosen_exam_papers("audio"))
        elif source == "irodori":
            argv.append(_chosen_irodori("audio"))
            number = _ask_lesson_number()
            if number is not None:
                argv += ["--episode", str(number)]
            lessons = _ask_int(_("Number of lessons to handle"), 1)
            if lessons != 1:
                argv += ["--latest", str(lessons)]
        else:
            argv += _chosen_roudoku()
            readings = _ask_int(_("Number of readings to handle"), 1)
            if readings != 1:
                argv += ["--latest", str(readings)]
        # It bounds the passage, as everywhere, and drops a reading too long
        # before it is downloaded: the 青空朗読 catalogue carries the durations.
        limit = _ask_optional_seconds(_("Max duration of the audio, in seconds"))
        if limit is not None:
            argv += ["--max-duration", str(limit)]
    elif source == "youtube":
        argv.append(_chosen_video())
        # Asked first: it decides what the duration question below is about.
        picture = _ask_picture()
        # One by default, like a podcast episode; Shorts are dropped, not counted.
        latest = _ask_int(_("Number of recent videos to handle"), 1)
        if latest != 1:
            argv += ["--latest", str(latest)]
        # The duration of a passage, the medium of the card, not of the source:
        # a source too long is dropped by --max-video, on the command line only.
        # The word, video or audio, follows the answer above.
        limit = _ask_optional_seconds(
            _("Max duration of the video, in seconds") if _keeps_picture(picture)
            else _("Max duration of the audio, in seconds"))
        if limit is not None:
            argv += ["--max-duration", str(limit)]
    else:
        # A folder is a legitimate source: all its audio files go through.
        while True:
            path = Path(_ask(_("Path of the file or folder"), back=True)
                        .strip('"').strip("'"))
            if path.exists():
                break
            print("   " + _("Not found: {path}").format(path=path))
        argv.append(str(path))
        # Asked only when the path holds a picture: on mp3 files both answers
        # would do the same.
        if _holds_a_video(path):
            picture = _ask_picture()
        # A series is asked what a podcast is, how many at a time and how long
        # a passage; unrelated videos go whole (see `audio_files.is_series`).
        from kotogen.generators import audio_files

        left = audio_files.episodes_left(path)
        if left:
            if left > 1:
                # Asked from two on only, so "left" always takes the plural.
                episodes = _ask_int(_("Number of episodes to handle ({left} left)")
                                    .format(left=left), 1)
                if episodes < left:
                    argv += ["--latest", str(episodes)]
            limit = _ask_optional_seconds(
                _("Max duration of the video, in seconds") if _keeps_picture(picture)
                else _("Max duration of the audio, in seconds"))
            if limit is not None:
                argv += ["--max-duration", str(limit)]

    # A ceiling, not a quota: by default the length of the audio sets it.
    count = _ask_auto_max(_("Max number of questions per audio"))
    if count is not None:
        argv += ["--count", str(count)]
    # The compression is a setting, not a question, carried in the command when
    # it is not the default so that it replays where the .env says otherwise.
    if audio_quality.code() != audio_quality.DEFAULT_CODE:
        argv += ["--audio-quality", audio_quality.code()]
    # Either answer is written: with no flag the command would ask again, the
    # default being to ask. A setting that settled it travels the same way.
    if (keep := _keeps_picture(picture)) is not None:
        argv.append("--video" if keep else "--no-video")
    return argv
