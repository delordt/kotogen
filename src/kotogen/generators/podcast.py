"""Japanese podcasts: one episode of a feed, ready to become listening cards.

A podcast is an RSS feed served with no key or session, so `urllib` and
`xml.etree` are enough. A downloaded episode then takes the route of any local
audio file, whose cutting keeps self-contained passages for its "feed" nature.
`PODCASTS` is data: an unknown feed URL works without being listed.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from kotogen import console, memory, seen, system
from kotogen.generators import download, feed, levels as jlpt_levels
from kotogen.generators.text_source import is_url
from kotogen.i18n import _, quoted
from kotogen.known import NO_SOURCES

# -- Network ------------------------------------------------------------------

TIMEOUT = 30         # seconds, reading the feed
AUDIO_TIMEOUT = 300  # an episode weighs 10 to 30 MB: the same limit would cut it

# Past this an enclosure is not an episode: three hours at 320 kb/s weigh 430 MB.
MAX_EPISODE = 500 * 1024 * 1024

ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"

EXTENSIONS = {".mp3", ".m4a", ".mp4", ".aac", ".ogg", ".wav", ".flac"}

# Episodes kept in cache per podcast, with their transcription: minutes of
# Whisper and tens of megabytes, which a rerun with other settings reuses.
EPISODES_CACHE = 3


# -- The catalogue ------------------------------------------------------------

@dataclass(frozen=True)
class Podcast:
    """A known podcast: how to announce it, where to read its feed, who it is for.

    The level is only a filing marker (see `levels`).
    """
    name: str
    feed_url: str
    levels: tuple[str, ...] = ()


# The levels are an estimate, from what a show says of itself. `teppei` is the
# series in progress, each earlier one keeping its feed and alias; a show that
# stopped publishing stays, its episodes with it.
PODCASTS: dict[str, Podcast] = {
    # -- Beginner -------------------------------------------------------------
    # The only one that really slows down, hence N5 alone: elsewhere "for
    # beginners" means simple vocabulary at normal pace.
    "slow-japanese": Podcast(
        "Slow Japanese (Akari / Mochifika)",
        "https://anchor.fm/s/6ad2a4a0/podcast/rss",
        ("N5",)),
    "teppei-beginner": Podcast(
        "Japanese podcast for beginners (Nihongo con Teppei)",
        "https://nihongoconteppei.com/feed/podcast/",
        ("N5", "N4")),
    "sakura-tips": Podcast(
        "SAKURA TIPS｜Listen to Japanese",
        "https://anchor.fm/s/3c2daac8/podcast/rss",
        ("N5", "N4")),
    "shun": Podcast(
        "Japanese with Shun",
        "https://feeds.redcircle.com/e8ab057c-683d-4375-a197-2dcc42d4f851",
        ("N5", "N4")),
    "ako": Podcast(
        "日本語 with あこ - Nihongo Picnic Podcast",
        "https://anchor.fm/s/2e08a010/podcast/rss",
        ("N5", "N4")),
    # Every episode title announces its level, from N5 to N1: hence the range.
    "tomo": Podcast(
        "Let's Talk in Japanese!",
        "https://anchor.fm/s/c56bd1c/podcast/rss",
        ("N5", "N4", "N3", "N2", "N1")),
    # -- Intermediate ---------------------------------------------------------
    # The series Z follows, hence the same level: 700 closed episodes in an
    # archive feed.
    "teppei-original": Podcast(
        "Nihongo con Teppei Original (archives 1-700)",
        "https://original.nihongoconteppei.com/feed/podcast",
        ("N4", "N3")),
    "teppei-z": Podcast(
        "Nihongo con Teppei Z",
        "https://nihongoconteppeiz.com/feed/podcast/",
        ("N4", "N3")),
    "sayuri": Podcast(
        "Everyday Japanese Podcast (Sayuri)",
        "https://anchor.fm/s/25d02b0c/podcast/rss",
        ("N4", "N3")),
    "teppei": Podcast(
        "Nihongo con Teppei 波!",
        "https://nihongoconteppeiha.fukushuconteppei.com/feed/podcast/",
        ("N3", "N2")),
    "noriko": Podcast(
        "Learn Japanese with Noriko",
        "https://anchor.fm/s/1380f800/podcast/rss",
        ("N3", "N2")),
    "yuyu": Podcast(
        "YUYUの日本語Podcast",
        "https://anchor.fm/s/cda85d4/podcast/rss",
        ("N3", "N2")),
    "bitesize": Podcast(
        "The Bite Size Japanese Podcast (Layla)",
        "https://anchor.fm/s/463a19c0/podcast/rss",
        ("N3", "N2")),
    "thinking": Podcast(
        "Thinking in Japanese Podcast",
        "https://feeds.buzzsprout.com/673871.rss",
        ("N3", "N2")),
    # -- Advanced -------------------------------------------------------------
    "miku": Podcast(
        "The Miku Real Japanese Podcast",
        "https://rss.buzzsprout.com/1739827.rss",
        ("N2",)),
    "toranomaki": Podcast(
        "Nihongo Toranomaki",
        "https://anchor.fm/s/72db771c/podcast/rss",
        ("N2",)),
    "teppei-noriko": Podcast(
        "Japanese with Teppei and Noriko",
        "https://teppeinorikojapanese.com/feed/podcast/",
        ("N2", "N1")),
    "haru": Podcast(
        "N2~N1日本語！Haru no Nihongo",
        "https://anchor.fm/s/26aec4fc/podcast/rss",
        ("N2", "N1")),
    "4989": Podcast(
        "4989 American Life",
        "https://feed.podbean.com/americanlife4989/feed.xml",
        ("N1",)),
    # Public radio bulletins at broadcast pace, several a day. The feed keeps
    # only the latest, so `--episode` is of no use on it.
    "nhk-radio": Podcast(
        "NHKラジオニュース",
        "https://www.nhk.or.jp/s-media/news/podcast/list/v1/all.xml",
        ("N1",)),
    # By natives for natives: the vocabulary of a subject, not of a course.
    "coten": Podcast(
        "歴史を面白く学ぶコテンラジオ (COTEN RADIO)",
        "https://anchor.fm/s/8c2088c/podcast/rss",
        ("N1",)),
}


def by_level(known: dict[str, Podcast] | None = None
             ) -> list[tuple[str, list[tuple[str, Podcast]]]]:
    """The catalogue grouped: [(label, [(alias, podcast)...])...], easiest first."""
    return jlpt_levels.by_level(known if known is not None else catalogue())


def catalogue_file() -> Path:
    """The user's catalogue: {alias: {"name": ..., "feed": ...}}.

    In the data folder rather than the cache: it is written by hand, and a disk
    cleaner must not carry it off.
    """
    return system.data_dir() / "podcasts.json"


def _known(known: dict[str, Podcast], entry: str) -> str:
    """The catalogue key this entry names, or ""."""
    alias = jlpt_levels.alias_key(entry)
    return alias if alias in known else ""


def catalogue() -> dict[str, Podcast]:
    """The built-in table, completed and overridden by the user's file.

    Overriding lets a user fix a feed that moved without waiting for a release.
    """
    known = dict(PODCASTS)
    try:
        raw = json.loads(catalogue_file().read_text(encoding="utf-8-sig"))
    except Exception:
        return known
    if not isinstance(raw, dict):
        return known
    for alias, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        # An entry with no feed is skipped; the rest of the file still counts.
        feed_url = str(entry.get("feed") or "").strip()
        if not feed_url:
            continue
        name = str(entry.get("name") or alias).strip()
        known[jlpt_levels.alias_key(alias)] = Podcast(
            name, feed_url, jlpt_levels.written(entry.get("levels")))
    return known


def _looks_like_an_alias(entry: str) -> bool:
    """A lone word naming no file: an alias, simply mistyped.

    So that `kotogen audio teppie` lists the known aliases rather than "File not
    found". Deliberately narrow: no separator, no dot, nothing of that name on disk.
    """
    if "/" in entry or "\\" in entry or "." in entry:
        return False
    return not Path(entry).exists()


def is_podcast_input(entry: str) -> bool:
    """True if the input names a podcast: a known alias, or a feed URL.

    Any URL no other audio source claims (NHK, YouTube, 青空朗読) is held to be a
    feed, deliberately: feed addresses have no common shape, and one that is not
    a feed says so when it is read.
    """
    entry = (entry or "").strip()
    if not entry:
        return False
    if _known(catalogue(), entry):
        return True
    # Asked here, not left to the order of the routing: "nhk" would pass for a
    # mistyped alias below, and a video address for a feed.
    from kotogen.generators import aozora_roudoku, irodori, jlpt_papers, nhk, youtube
    if nhk.is_nhk_input(entry) or youtube.is_youtube_input(entry):
        return False
    if (jlpt_papers.is_jlpt_input(entry) or irodori.is_irodori_input(entry)
            or aozora_roudoku.is_roudoku_input(entry)):
        return False
    return True if is_url(entry) else _looks_like_an_alias(entry)


@dataclass(frozen=True)
class Feed:
    """A resolved feed: its history and cache key, its readable name, its URL."""
    key: str
    name: str
    url: str


def resolve(entry: str) -> Feed:
    """An alias or a URL to a resolved feed. An unknown alias lists the ones there are."""
    entry = (entry or "").strip()
    known = catalogue()
    if alias := _known(known, entry):
        return Feed(alias, known[alias].name, known[alias].feed_url)
    if is_url(entry):
        # A catalogued show pasted as its feed keeps its alias, hence its history,
        # its cache and the name its cards carry.
        for alias, show in known.items():
            if show.feed_url.rstrip("/") == entry.rstrip("/"):
                return Feed(alias, show.name, show.feed_url)
        host = urllib.parse.urlsplit(entry).hostname or entry
        return Feed(download.url_key(entry, "feed"), host, entry)
    # Filed by level: a mistyped alias means a show is being looked for.
    lines = jlpt_levels.listed(known)
    raise ValueError(
        _("unknown podcast: {entry}. Known aliases:").format(entry=quoted(entry))
        + "\n" + ("\n".join(lines) if lines else "   " + _("none", "alias")) + "\n"
        + _("   An RSS feed URL works too, with no alias, and {file} lets you "
            "add some.").format(file=catalogue_file())
    )


# -- Reading the feed ---------------------------------------------------------

@dataclass(frozen=True)
class Episode:
    guid: str
    title: str
    url: str
    published: str
    duration: float | None


def _duration(text: str | None) -> float | None:
    """`itunes:duration` in seconds: "823", "13:43" or "1:02:03"."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    total = 0.0
    for part in parts:  # seconds, or minutes:seconds, or hours:minutes:seconds
        total = total * 60 + part
    return total or None


def _enclosure(item: ET.Element) -> str:
    """The URL of the audio file of this item, or an empty string if it has none.

    The first `enclosure` typed as audio, or whose extension says so. Web
    addresses only: the feed is written by someone else, and `urllib` would open
    a `file://` as readily, copying a file of this machine into the cache.
    """
    for enclosure in item.findall("enclosure"):
        url = (enclosure.get("url") or "").strip()
        if not is_url(url):
            continue
        type_ = (enclosure.get("type") or "").strip().lower()
        if type_.startswith("audio/"):
            return url
        if Path(urllib.parse.urlsplit(url).path).suffix.lower() in EXTENSIONS:
            return url
    return ""


def read_feed(data: bytes, url: str = "") -> tuple[str, list[Episode]]:
    """(name of the podcast, episodes from the newest to the oldest).

    `feed` reads the XML; this keeps what makes an episode: the audio file, its
    duration, and the identifier the history keeps.
    """
    name, items = feed.read(data, url)

    episodes: list[Episode] = []
    for item in items:
        audio = _enclosure(item.element)
        if not audio:
            continue  # a show note, a video, an item with no file: not an episode
        episodes.append(Episode(
            guid=(item.element.findtext("guid") or audio).strip(),
            title=item.title,
            url=audio,
            published=item.published,
            duration=_duration(item.element.findtext(f"{{{ITUNES}}}duration")),
        ))

    if not episodes:
        raise ValueError(
            _("no audio episode in the feed: {url}. Is that really the RSS "
              "address of the podcast, and not the one of its web page?")
            .format(url=url or _("feed"))
        )
    return name, feed.order(episodes, lambda episode: episode.published)


def fetch_feed(channel: Feed) -> tuple[str, list[Episode]]:
    """Downloads and reads the feed. The catalogue name wins over the RSS one."""
    try:
        with download.open_url(channel.url, TIMEOUT) as answer:
            data = download.capped(answer, channel.url)
    except urllib.error.HTTPError as exc:
        raise ValueError(_("feed unreachable ({code}): {url}")
                         .format(code=exc.code, url=channel.url)) from exc
    except ValueError:
        raise
    except RuntimeError as exc:
        # Already a sentence for the screen, the address included.
        raise ValueError(str(exc)) from exc
    except Exception as exc:
        raise ValueError(_("feed unreachable: {url} ({error})")
                         .format(url=channel.url, error=exc)) from exc
    name, episodes = read_feed(data, channel.url)
    if channel.key in catalogue():
        return channel.name, episodes
    return name or channel.name, episodes


def latest(channel: Feed, count: int, *, mode: str = "audio",
           skip_seen: bool = True) -> tuple[str, list[Episode], int]:
    """(name of the podcast, `count` latest episodes not handled yet, how many skipped).

    The skipped count is not printed here: it goes on the podcast's announcement
    line, which the caller writes.
    """
    name, episodes = fetch_feed(channel)
    done = seen.load(mode, channel.key) if skip_seen else {}
    # The deck is a second memory, fed from other machines too. Matched on the
    # label, the card not carrying the `guid`: a retitled episode comes back as a
    # possible duplicate, never a lost card.
    deck = memory.known().sources() if skip_seen else NO_SOURCES
    kept: list[Episode] = []
    skipped = 0
    for episode in episodes:
        if episode.guid in done or deck.knows(mode, provenance(channel, episode)):
            skipped += 1
            continue
        kept.append(episode)
        if len(kept) >= count:
            break
    return name, kept, skipped


# -- One precise episode ------------------------------------------------------

# The number a show puts at the head of its titles: "#512", "318.", "Ep87",
# "No 141", "episode96", behind a level label if need be ("【N4-N3】Ep87...").
# Anchored at the head: "5％ Better" or "【12-3】第4回" carry another number.
TITLE_NUMBER_RE = re.compile(
    r"^\s*(?:【[^】]*】|\[[^\]]*\])?\s*"
    r"(?:(?:#|n[o°]\.?|ep(?:isode)?\.?)\s*(\d{1,4})|(\d{1,4})\s*(?:回|[.)．。]))",
    re.IGNORECASE)


def announced_number(title: str) -> int | None:
    """The number this title announces, or None if it announces none."""
    found = TITLE_NUMBER_RE.match(title or "")
    if not found:
        return None
    return int(found.group(1) or found.group(2))


def _rank(episodes: list[Episode], number: int, name: str) -> int:
    """The position in the feed (0 = the newest) of episode no. `number`.

    The number announced by a single title wins, as specials and skipped numbers
    shift it from the rank. Otherwise the rank from the oldest, which unlike one
    from the newest does not slide at every publication.
    """
    if number < 1:
        raise ValueError(_("episode number expected from 1 on, got {number}.")
                         .format(number=number))
    carrying = [rank for rank, episode in enumerate(episodes)
                if announced_number(episode.title) == number]
    if len(carrying) == 1:
        return carrying[0]
    if number > len(episodes):
        raise ValueError(
            _("{name}: the feed only carries {total} {episodes}, no. {number} is "
              "not in it.").format(
                  name=name, total=len(episodes), number=number,
                  episodes=console.plural(len(episodes), "episode"))
        )
    return len(episodes) - number


def from_number(channel: Feed, number: int,
                count: int = 1) -> tuple[str, list[Episode]]:
    """(name of the podcast, `count` episodes from no. `number` on, oldest first).

    Unlike `latest`, the history does not apply: a number typed by hand is meant.
    """
    name, episodes = fetch_feed(channel)
    start = _rank(episodes, number, name)
    # The feed runs newest first: the following numbers are higher up the list.
    kept = episodes[max(0, start - count + 1):start + 1]
    return name, list(reversed(kept))


def provenance(channel: Feed, episode: Episode) -> str:
    """Where these cards come from, as they will keep it in their Source field.

    Composed here, where an episode's name is known: the cached file carries only
    a key.
    """
    return f"{channel.name} - {episode.title or episode.guid}"


def link(channel: Feed, episode: Episode, start: float = 0.0) -> str:
    """Nothing to reopen: an episode points only at the file the card carries already.

    The `enclosure` is the mp3 itself. The function keeps the remote sources
    answering to the same names for `audio.run_audio`; "" means no link.
    """
    return ""


def mark_done(channel: Feed, episode: Episode, mode: str = "audio") -> None:
    """Memorises an episode handled, with cards or without: the next pass ignores it."""
    seen.mark(mode, channel.key, episode.guid, episode.title)


# -- Downloading and cache ----------------------------------------------------

def cache_folder(channel: Feed) -> Path:
    """Where the mp3 of an episode and its transcription live between two passes."""
    folder = system.cache_dir() / "podcasts" / channel.key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _file_name(channel: Feed, episode: Episode) -> str:
    """The name of an episode file: readable, unique by the fingerprint of its guid.

    Readable because the extracts in Anki's media library are named after it.
    """
    readable = re.sub(r"[^\w-]+", "_", episode.title, flags=re.UNICODE)
    readable = re.sub(r"_+", "_", readable).strip("_")[:30].strip("_")
    fingerprint = hashlib.sha256(episode.guid.encode("utf-8")).hexdigest()[:8]
    suffix = Path(urllib.parse.urlsplit(episode.url).path).suffix.lower()
    if suffix not in EXTENSIONS:
        suffix = ".mp3"
    return "_".join(p for p in (channel.key, readable, fingerprint) if p) + suffix


def fetch(channel: Feed, episode: Episode) -> Path:
    """The episode on disk, taken from the cache if it is already there.

    Raises RuntimeError with a sentence for the screen, past `MAX_EPISODE` too.
    """
    return download.file(episode.url, cache_folder(channel) / _file_name(channel, episode),
                         timeout=AUDIO_TIMEOUT, limit=MAX_EPISODE)


def cleanup(channel: Feed, keep: int = EPISODES_CACHE) -> None:
    """Keeps only the `keep` newest episodes, transcription included.

    What goes is downloaded and transcribed again if needed: time, never a card.
    """
    from kotogen.generators.whisper import _cache_key

    folder = system.cache_dir() / "podcasts" / channel.key
    if not folder.is_dir():
        return
    audios = sorted((f for f in folder.iterdir()
                     if f.is_file() and f.suffix.lower() in EXTENSIONS),
                    key=lambda f: f.stat().st_mtime, reverse=True)
    for old in audios[keep:]:
        (folder / _cache_key(old)).unlink(missing_ok=True)
        old.unlink(missing_ok=True)
