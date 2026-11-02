"""YouTube videos: a Japanese video, ready to become listening cards.

The counterpart of `podcast` for video: the same catalogue by level, history,
cache and output (a local file for the listening chain). Listing reads the Atom
feed for free; the medium needs yt-dlp, an extra (`pip install -e ".[youtube]"`).
A feed mixes in Shorts and gives no duration, so each video is probed first
(duration, title, language, a hand-written Japanese track). The feed holds only
the last fifteen videos, so there is no stable `--episode`, only `--latest`. The
Japanese subtitle is dropped beside the medium (`<medium>.ja.vtt`) for
`subtitles` to find, and keeping the picture is decided before the download.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from kotogen import console, memory, seen, system
from kotogen.generators import download, feed, levels as jlpt_levels
from kotogen.generators.text_source import is_url
from kotogen.i18n import _, quoted
from kotogen.known import NO_SOURCES

# -- Network ------------------------------------------------------------------

TIMEOUT = 30  # seconds, reading a feed or a channel page

# The feed of a channel and that of a playlist differ only by the name of the
# parameter. Both are Atom, both cap at fifteen entries.
CHANNEL_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
PLAYLIST_FEED = "https://www.youtube.com/feeds/videos.xml?playlist_id={}"

YT_XML = "http://www.youtube.com/xml/schemas/2015"

# Typed as it stands, its quotes the shell's (zsh refuses bare brackets), as
# `pdf_figures.PDF_EXTRA` is.
YOUTUBE_EXTRA = 'pip install -e ".[youtube]"'

# Videos kept in cache per source, like podcast episodes: a rerun with another
# setting then costs neither the download nor the transcription.
VIDEOS_CACHE = 3

# Below this, a Short, which a channel feed mixes in with the videos. On the
# catalogue's channels Shorts run 9 to 94 seconds and videos from 4 min 17, so
# two minutes falls in the gap. Too long is the business of `--max-video`.
MIN_DURATION = 120


# -- The catalogue ------------------------------------------------------------

@dataclass(frozen=True)
class Channel:
    """A known channel: how to announce it, where to read its feed, who it is for.

    The level is a filing marker only (see `levels`).
    """
    name: str
    feed_url: str
    levels: tuple[str, ...] = ()


# Each channel's last videos were probed for a hand-written Japanese track over
# Japanese sound. The levels are what the channel says of itself, or an estimate;
# one that stopped publishing says so, its feed being fifteen videos the history exhausts.
CHANNELS: dict[str, Channel] = {
    # -- Beginner -------------------------------------------------------------
    # Three "comprehensible input" channels: slow Japanese throughout, showing
    # what is talked about. Each video gives its step, hence a range of levels.
    "nihongo-no-jikan": Channel(
        "にほんごのじかん (Japanese Comprehensible Input)",
        CHANNEL_FEED.format("UCdZHET-9_Comx6UaVTSETiQ"),
        ("N5", "N4", "N3")),
    "nij": Channel(
        "Natural Japanese (NIJ)",
        CHANNEL_FEED.format("UCXo8kuCtqLjL1EH6m4FJJNA"),
        ("N5", "N4", "N3", "N2")),
    "nihongo-learning": Channel(
        "Nihongo-Learning",
        CHANNEL_FEED.format("UC6Xtu6v_op552SsOr5_jWrg"),
        ("N5", "N4", "N3")),
    # Simple Japanese over filmed scenes (shopping, a bus ride): what the video
    # mode serves best, the picture carrying the meaning.
    "kensan": Channel(
        "けんさんおかえり Japanese",
        CHANNEL_FEED.format("UCaXIrZ5Ere4lC4cdPE_ujXA"),
        ("N5", "N4")),
    # Self-contained numbered stories of six to nine minutes, the easiest to cut
    # into cards. Nothing since March 2024: fifteen stories in all.
    "japarrot": Channel(
        "Japarrot! - Let's Learn Japanese",
        CHANNEL_FEED.format("UCOk9XUAOmj1HCxgNXkouUEQ"),
        ("N5", "N4")),
    # -- Intermediate ---------------------------------------------------------
    # The level in every title, numbered episodes: the closest to a filmed podcast.
    "tekuteku": Channel(
        "てくてく日本語 (Japanese Podcast)",
        CHANNEL_FEED.format("UC4aPWZNw-GebNm0mSh1oxGw"),
        ("N4", "N3")),
    "akane": Channel(
        "あかね的日本語教室",
        CHANNEL_FEED.format("UCh-GhnQ7qDQmS6Bz3pGc1Mw"),
        ("N4", "N3")),
    "naoko": Channel(
        "Daily Japanese with Naoko",
        CHANNEL_FEED.format("UCMNVKIaw8hV8ln3dDE5z-hA"),
        ("N4", "N3")),
    # -- Advanced -------------------------------------------------------------
    # Closed since August 2025: fifteen videos, all subtitled by hand.
    "onomappu": Channel(
        "Onomappu",
        CHANNEL_FEED.format("UCLuymDHiOySsAQ9Nc-4NoEQ"),
        ("N3", "N2")),
    # Long videos (twenty to forty minutes), where `--max-duration` matters most.
    "speak-naturally": Channel(
        "Speak Japanese Naturally",
        CHANNEL_FEED.format("UCSbH_BPR_AoARW6RDYLlLog"),
        ("N3", "N2")),
    # Nine to twelve minutes, the step at the head of each title, nearly a video a
    # day: the steadiest pool at the top of the catalogue.
    "listening-lab": Channel(
        "Easy Japanese Listening Lab",
        CHANNEL_FEED.format("UCY1invdYR6KJTU_kfADvW6Q"),
        ("N3", "N2", "N1")),
    # News commentary and discussions, twenty to fifty minutes, at native pace:
    # the filmed counterpart of NHKラジオニュース in the podcasts.
    "jiro": Channel(
        "Jiro, just Japanese",
        CHANNEL_FEED.format("UC9zMlDf3SoAEgZta239F7nA"),
        ("N2", "N1")),
}


def by_level(known: dict[str, Channel] | None = None
             ) -> list[tuple[str, list[tuple[str, Channel]]]]:
    """The catalogue grouped: [(label, [(alias, channel)...])...], easiest first."""
    return jlpt_levels.by_level(known if known is not None else catalogue())


def catalogue_file() -> Path:
    """The user's catalogue: {alias: {"name": ..., "feed": ...}}.

    In the data folder, not the cache, like the podcasts': it is written by hand.
    """
    return system.data_dir() / "channels.json"


def catalogue() -> dict[str, Channel]:
    """The built-in table, completed and overridden by the user's file.

    Its `feed` field takes a feed URL or a bare identifier, as read off the page.
    """
    known = dict(CHANNELS)
    try:
        raw = json.loads(catalogue_file().read_text(encoding="utf-8-sig"))
    except Exception:
        return known
    if not isinstance(raw, dict):
        return known
    for alias, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        feed_url = _written_feed(str(entry.get("feed") or "").strip())
        if not feed_url:
            continue
        name = str(entry.get("name") or alias).strip()
        known[jlpt_levels.alias_key(alias)] = Channel(
            name, feed_url, jlpt_levels.written(entry.get("levels")))
    return known


def _written_feed(value: str) -> str:
    """The `feed` field of the user file: a feed URL, or a bare identifier.

    A handle URL (`.../@name`) is kept as written: `resolve` reads it off its
    page when the channel is used, the catalogue being read offline.
    """
    if not value:
        return ""
    if value.lower().startswith(("http://", "https://")):
        return _feed_from_url(value) or value
    if value.startswith("UC"):
        return CHANNEL_FEED.format(value)
    if value.startswith(("PL", "UU", "LL", "FL", "OL", "RD")):
        return PLAYLIST_FEED.format(value)
    return ""


# -- Recognising the inputs ---------------------------------------------------

# The hosts that serve YouTube, `music.youtube.com` included: its video URLs are
# the same.
HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com",
         "music.youtube.com", "youtu.be", "www.youtu.be")


def _host(entry: str) -> str:
    return (urllib.parse.urlsplit(entry.strip()).hostname or "").lower()


def is_youtube_input(entry: str) -> bool:
    """True if the input names YouTube: a catalogue alias, or a URL of the site.

    Strict, unlike `podcast.is_podcast_input`: YouTube is asked first, and
    claiming unknown words would answer a mistyped podcast alias with the list of
    channels.
    """
    entry = (entry or "").strip()
    if not entry:
        return False
    if jlpt_levels.alias_key(entry) in catalogue():
        return True
    return is_url(entry) and _host(entry) in HOSTS


# -- Resolving an input -------------------------------------------------------

@dataclass(frozen=True)
class Source:
    """A resolved input: its history and cache key, its name, what it aims at.

    Either `feed_url` (a channel or a playlist) or `video` (a single video pasted
    by hand).
    """
    key: str
    name: str
    feed_url: str = ""
    video: str = ""


# The five URL forms YouTube serves a video under. A pasted Short is recognised,
# then dropped like any video under `MIN_DURATION` (`audio._youtube_videos`).
_VIDEO_PATH_RE = re.compile(r"^/(?:shorts|embed|live|v)/([\w-]{6,})")

# A video identifier, as it appears in `?v=` or after `youtu.be/`.
_VIDEO_ID_RE = re.compile(r"^[\w-]{6,}$")


def _video_from_url(entry: str) -> str:
    """The identifier of the video this URL names, or "" if it aims at none.

    A `watch?v=...&list=...` URL names the video, not its playlist: it is what
    YouTube was showing.
    """
    parts = urllib.parse.urlsplit(entry.strip())
    if _host(entry) in ("youtu.be", "www.youtu.be"):
        candidate = parts.path.strip("/").split("/")[0]
        return candidate if _VIDEO_ID_RE.match(candidate) else ""
    found = _VIDEO_PATH_RE.match(parts.path)
    if found:
        return found.group(1)
    values = urllib.parse.parse_qs(parts.query).get("v") or []
    candidate = (values[0] if values else "").strip()
    return candidate if _VIDEO_ID_RE.match(candidate) else ""


def _feed_from_url(entry: str) -> str:
    """The Atom feed URL this URL implies, or "" if it implies none.

    Not for a handle (`/@onomappu`), which needs the network: see `resolve`.
    """
    parts = urllib.parse.urlsplit(entry.strip())
    query = urllib.parse.parse_qs(parts.query)
    # A feed URL passes as it is.
    if parts.path.rstrip("/").endswith("/feeds/videos.xml"):
        return entry.strip()
    channel = re.match(r"^/channel/(UC[\w-]+)", parts.path)
    if channel:
        return CHANNEL_FEED.format(channel.group(1))
    playlist = (query.get("list") or [""])[0].strip()
    if playlist and parts.path.rstrip("/").endswith("/playlist"):
        return PLAYLIST_FEED.format(playlist)
    return ""


_HANDLE_RE = re.compile(r"^/@([^/]+)")
_CHANNEL_ID_RE = re.compile(r'"(?:externalId|channelId)":"(UC[\w-]{22})"')


def _channel_id_from_handle(entry: str) -> str:
    """The channel identifier behind a handle (`/@onomappu`), read off its page.

    The only network call of the routing: the Atom feed does not take a handle.
    """
    parts = urllib.parse.urlsplit(entry.strip())
    handle = _HANDLE_RE.match(parts.path)
    if not handle:
        return ""
    url = f"https://www.youtube.com/@{handle.group(1)}/videos"
    try:
        with download.open_url(url, TIMEOUT) as answer:
            page = download.capped(answer, url).decode("utf-8", "replace")
    except Exception as exc:
        raise ValueError(_("unreadable channel: {url} ({error})")
                         .format(url=url, error=exc)) from exc
    found = _CHANNEL_ID_RE.search(page)
    if not found:
        raise ValueError(
            _("channel identifier not found on {url}. The page may have changed "
              "shape: the /channel/UC... URL still works, and is read off "
              "{button}.").format(url=url, button=quoted(_("Share channel")))
        )
    return found.group(1)


def _key_outside_catalogue(kind: str, identifier: str) -> str:
    """A stable key for what is not in the catalogue: its kind, plus a fingerprint.

    A fingerprint rather than the identifier, as for the podcasts: it is short,
    and YouTube's identifiers are case-sensitive where Windows folders are not.
    """
    return f"{kind}-{hashlib.sha256(identifier.encode('utf-8')).hexdigest()[:8]}"


def resolve(entry: str) -> Source:
    """An alias, a channel, playlist or video URL, to a resolved source.

    An unknown alias raises with the list of the known ones.
    """
    entry = (entry or "").strip()
    known = catalogue()
    alias = jlpt_levels.alias_key(entry)
    if alias in known:
        feed_url = known[alias].feed_url
        # A handle from the user file, resolved here rather than in `catalogue`,
        # which every routing reads: only a channel being used costs the network.
        if _host(feed_url) in HOSTS and (found := _channel_id_from_handle(feed_url)):
            feed_url = CHANNEL_FEED.format(found)
        return Source(alias, known[alias].name, feed_url=feed_url)

    if is_url(entry) and _host(entry) in HOSTS:
        video = _video_from_url(entry)
        if video:
            return Source(_key_outside_catalogue("video", video),
                          "YouTube", video=video)
        feed_url = _feed_from_url(entry) or ""
        if not feed_url:
            channel_id = _channel_id_from_handle(entry)
            if channel_id:
                feed_url = CHANNEL_FEED.format(channel_id)
        if feed_url:
            # A catalogue channel pasted as a URL keeps its alias, hence its
            # history and its cache.
            for alias, channel in known.items():
                if channel.feed_url == feed_url:
                    return Source(alias, channel.name, feed_url=feed_url)
            kind = "playlist" if "playlist_id=" in feed_url else "channel"
            return Source(_key_outside_catalogue(kind, feed_url), "YouTube",
                          feed_url=feed_url)
        raise ValueError(
            _("YouTube address not recognised: {entry}. What is accepted is the "
              "address of a video (.../watch?v=..., youtu.be/...), of a channel "
              "(.../@name, .../channel/UC...) or of a playlist "
              "(.../playlist?list=...).").format(entry=quoted(entry))
        )

    lines = jlpt_levels.listed(known)
    raise ValueError(
        _("unknown YouTube channel: {entry}. Known aliases:").format(
            entry=quoted(entry))
        + "\n" + ("\n".join(lines) if lines else "   " + _("none", "alias")) + "\n"
        + _("   A video, channel or playlist URL works too, with no alias, and "
            "{file} lets you add some.").format(file=catalogue_file())
    )


# -- Reading the feed ---------------------------------------------------------

@dataclass(frozen=True)
class Video:
    """A video as the feed announces it: nothing more, and above all not its duration.

    The duration and the subtitles come from `probe`, which costs a call.
    """
    id: str
    title: str
    published: str

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"


def read_feed(data: bytes, url: str = "") -> tuple[str, list[Video]]:
    """(name of the channel, videos from the newest to the oldest).

    `feed` reads the Atom; here each entry gives its video identifier, in
    YouTube's own namespace, and an entry without one is skipped.
    """
    name, items = feed.read(data, url)

    videos: list[Video] = []
    for item in items:
        identifier = (item.element.findtext(f"{{{YT_XML}}}videoId") or "").strip()
        if not identifier:
            continue
        videos.append(Video(id=identifier, title=item.title,
                            published=item.published))

    if not videos:
        raise ValueError(
            _("no video in the feed: {url}. The channel may be empty, or publish "
              "nothing but upcoming live streams.").format(url=url or _("feed"))
        )
    return name, feed.order(videos, lambda video: video.published)


def fetch_feed(source: Source) -> tuple[str, list[Video]]:
    """Downloads and reads the feed. The catalogue name wins over the feed's."""
    try:
        with download.open_url(source.feed_url, TIMEOUT) as answer:
            data = download.capped(answer, source.feed_url)
    except urllib.error.HTTPError as exc:
        raise ValueError(_("feed unreachable ({code}): {url}")
                         .format(code=exc.code, url=source.feed_url)) from exc
    except ValueError:
        raise
    except RuntimeError as exc:
        # Already a sentence for the screen, the address included.
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        raise ValueError(_("feed unreachable: {url} ({error})")
                         .format(url=source.feed_url, error=exc)) from exc
    name, videos = read_feed(data, source.feed_url)
    if source.key in catalogue():
        return source.name, videos
    return name or source.name, videos


def candidates(source: Source, *, mode: str = "audio",
               skip_seen: bool = True) -> tuple[str, list[Video], int]:
    """(name of the source, its videos not handled yet by this mode, how many skipped).

    Everything left, unlike `podcast.latest`: Shorts are only dropped once probed,
    so the caller goes down the list until it has its count. A single video comes
    back as it is, with no history: pasted by hand, it is asked for on purpose.
    """
    if source.video:
        return source.name, [Video(id=source.video, title="", published="")], 0

    name, videos = fetch_feed(source)
    done = seen.load(mode, source.key) if skip_seen else {}
    # The deck too, which holds cards from other machines, matched on the short
    # address in the Source field rather than on a title that may change.
    deck = memory.known().sources() if skip_seen else NO_SOURCES
    kept = [video for video in videos
            if video.id not in done
            and not deck.knows_id(mode, f"youtu.be/{video.id}")]
    # The skipped count is said by the caller, on its announcement line.
    return name, kept, len(videos) - len(kept)


# -- yt-dlp: the probe and the download ---------------------------------------

def _yt_dlp():
    """The yt-dlp module, or a clean stop saying what to install.

    A stop rather than a failed source, as every video would fail the same way.
    The module rather than the executable, which is not on the PATH of a venv
    that was not activated.
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        raise SystemExit(
            _("Package missing for YouTube videos. Run, in the kotogen folder: "
              "{command}\n"
              "   (or simply: pip install -U yt-dlp)\n"
              "   FFmpeg is required too: {hint}").format(
                command=YOUTUBE_EXTRA, hint=system.ffmpeg_hint())
        ) from None
    return yt_dlp


# The subtitle languages asked for, as a regular expression yt-dlp reads: `ja`,
# `ja-JP` and `ja-orig` (the original track), all named as `subtitles.companions`
# expects.
JA_SUBTITLES = ["ja.*"]

# The definition ceiling at download time: `video_clip` re-encodes in 480p
# anyway. The `?` of the format makes it optional: a 1080p-only video is taken.
MAX_HEIGHT = 720


@dataclass(frozen=True)
class ProbedVideo:
    """What the probe learned of a video, without downloading a second of it.

    `ja_subtitle` means a hand-written Japanese track: YouTube's ASR does not
    punctuate Japanese, which the cutting and the back of the cards need.
    `language` is that of the sound as YouTube declares it, since an English video
    may carry a `ja` track; empty when undeclared, which is not "not Japanese".
    """
    id: str
    title: str
    duration: float | None
    ja_subtitle: bool
    language: str = ""


def probe(video: Video) -> ProbedVideo:
    """Duration, title, language and subtitle tracks of a video, with no download."""
    yt_dlp = _yt_dlp()
    options = {"quiet": True, "no_warnings": True, "skip_download": True,
               "noprogress": True, "extract_flat": False}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(video.url, download=False)
    except Exception as exc:
        raise ValueError(_("unreadable video: {url} ({error})")
                         .format(url=video.url, error=exc)) from exc

    manual = info.get("subtitles") or {}
    duration = info.get("duration")
    return ProbedVideo(
        id=info.get("id") or video.id,
        title=(info.get("title") or video.title or "").strip(),
        duration=float(duration) if duration else None,
        ja_subtitle=any(language.lower().startswith("ja") for language in manual),
        language=(info.get("language") or "").strip(),
    )


def japanese_sound(probed: ProbedVideo) -> bool:
    """Is the video in Japanese, as far as YouTube lets us know?

    An undeclared language passes, many channels declaring none; only a declared
    language other than Japanese is refused.
    """
    return not probed.language or probed.language.lower().startswith("ja")


# -- Cache and download -------------------------------------------------------

def cache_folder(source: Source) -> Path:
    """Where the medium of a video, its subtitle and its transcription live."""
    folder = system.cache_dir() / "youtube" / source.key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _stem(source: Source, probed: ProbedVideo) -> str:
    """The working name of the medium: readable, unique by the video identifier.

    Readable because the extracts in Anki's media folder carry it; the identifier
    needs no hashing, being short, stable and safe in any path.
    """
    readable = re.sub(r"[^\w-]+", "_", probed.title, flags=re.UNICODE)
    readable = re.sub(r"_+", "_", readable).strip("_")[:30].strip("_")
    return "_".join(p for p in (source.key, readable, probed.id) if p)


# What may be found on disk under the stem, wide since yt-dlp picks the container
# YouTube serves that day. Sound and video share the stem, so the two families
# keep a `--video` run from taking an earlier mp3.
AUDIO_MEDIA = {".mp3", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".flac"}
VIDEO_MEDIA = {".mp4", ".mkv", ".webm", ".mov"}
MEDIA = AUDIO_MEDIA | VIDEO_MEDIA


def _media_on_disk(folder: Path, stem: str, image: bool) -> Path | None:
    """The medium already downloaded for this stem AND this form, if there is one."""
    wanted = VIDEO_MEDIA if image else AUDIO_MEDIA
    for path in sorted(folder.glob(f"{stem}.*")):
        if path.suffix.lower() in wanted and path.stat().st_size > 0:
            return path
    return None


def fetch(source: Source, probed: ProbedVideo, *, image: bool = False) -> Path:
    """The video on disk, taken from the cache if it is already there.

    `image` decides what is downloaded: without it, only the sound track (a few
    megabytes against a few hundred). A manual Japanese subtitle is dropped beside
    the medium, where `subtitles` finds it and Whisper is skipped.
    """
    yt_dlp = _yt_dlp()
    folder = cache_folder(source)
    stem = _stem(source, probed)

    already = _media_on_disk(folder, stem, image)
    if already is not None:
        return already

    # yt-dlp's own bar is off (`noprogress`); its progress callback feeds the
    # action line instead, in the units of the rest of the output.
    progress = download.Progress()

    def follow(state: dict) -> None:
        if state.get("status") != "downloading":
            # Finished, or converting: no more network to show.
            progress.received, progress.total = 0, 0
            return
        progress.received = int(state.get("downloaded_bytes") or 0)
        progress.total = int(state.get("total_bytes")
                             or state.get("total_bytes_estimate") or 0)

    options = {
        "quiet": True, "no_warnings": True, "noprogress": True,
        "progress_hooks": [follow],
        "outtmpl": str(folder / f"{stem}.%(ext)s"),
        # AUTOMATIC subtitles are explicitly refused: see `ProbedVideo`.
        "writesubtitles": True,
        "writeautomaticsub": False,
        "subtitleslangs": JA_SUBTITLES,
        "subtitlesformat": "vtt",
    }
    if image:
        options["format"] = (f"bv*[height<=?{MAX_HEIGHT}]+ba/"
                             f"b[height<=?{MAX_HEIGHT}]/b")
        options["merge_output_format"] = "mp4"
    else:
        options["format"] = "bestaudio/best"
        # Re-encoded as mp3: YouTube's best sound is Opus in WebM, which the file
        # collection would take for a video and extract the sound from again.
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "0",
        }]

    def pull() -> None:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={probed.id}"])

    try:
        console.while_working(pull, progress.status)
    except Exception as exc:
        raise ValueError(_("download impossible: {error}").format(error=exc)) from exc

    media = _media_on_disk(folder, stem, image)
    if media is None:
        raise ValueError(
            _("download finished with no readable file for {title}. FFmpeg may "
              "be absent: {hint}").format(title=quoted(probed.title),
                                          hint=system.ffmpeg_hint())
        )
    return media


def provenance(source: Source, probed: ProbedVideo) -> str:
    """Where these cards come from, as they will keep it in their Source field.

    The channel and the title of the video, which the channel alone does not name.
    """
    return f"{source.name} - {probed.title or probed.id}"


def link(source: Source, probed: ProbedVideo, start: float = 0.0) -> str:
    """The address that reopens this video, at the passage the card is drawn from.

    `?t=` opens it at the second the extract begins, and is left out at zero. The
    short `youtu.be` form, since the label is what is read in the field.
    """
    seconds = int(start)
    return f"https://youtu.be/{probed.id}" + (f"?t={seconds}" if seconds > 0 else "")


def mark_done(source: Source, probed: ProbedVideo, mode: str = "audio") -> None:
    """Memorises a video handled, with cards or without: the next pass ignores it."""
    seen.mark(mode, source.key, probed.id, probed.title)


def cleanup(source: Source, keep: int = VIDEOS_CACHE) -> None:
    """Keeps only the `keep` newest media, transcription included.

    What goes costs only the time to download and transcribe again. The subtitle
    goes with its medium, whose name is what makes it findable.
    """
    from kotogen.generators.whisper import _cache_key

    folder = system.cache_dir() / "youtube" / source.key
    if not folder.is_dir():
        return
    media = sorted((f for f in folder.iterdir()
                    if f.is_file() and f.suffix.lower() in MEDIA),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for old in media[keep:]:
        (folder / _cache_key(old)).unlink(missing_ok=True)
        for companion in folder.glob(f"{old.stem}.*"):
            if companion.suffix.lower() in (".vtt", ".srt"):
                companion.unlink(missing_ok=True)
        old.unlink(missing_ok=True)
