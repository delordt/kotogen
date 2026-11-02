"""Press catalogue: Japanese sites whose articles read as they are.

The reading-side counterpart of the podcast catalogue. A site enters only if its
articles extract cleanly without a browser (NHK News Web, built in JavaScript,
gives back nothing), and all of them are press for adults, N2-N1. Any feed URL
works without being listed, and a `press.json` file adds sites for good.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from kotogen import system
from kotogen.generators import download, feed
from kotogen.i18n import _

TIMEOUT = 30

# Display order, from the general to the specialised. The genre takes the column
# the level has in the podcast catalogue, every site here being of one level.
GENRES = ("News", "Society", "Science", "Tech", "Practical")


@dataclass(frozen=True)
class Site:
    """A site of the catalogue: its name, its feed, and what one reads there."""

    name: str
    url: str
    genre: str = ""


SITES: dict[str, Site] = {
    "jiji": Site("時事通信 - jiji.com",
                 "https://www.jiji.com/rss/ranking.rdf", "News"),
    "nippon": Site("nippon.com - Japan seen from the inside",
                   "https://www.nippon.com/ja/feed/", "Society"),
    "gigazine": Site("GIGAZINE - science and curiosities",
                     "https://gigazine.net/news/rss_2.0/", "Science"),
    "itmedia": Site("ITmedia NEWS",
                    "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml", "Tech"),
    "impress": Site("Impress Watch - essays and columns",
                    "https://www.watch.impress.co.jp/data/rss/1.0/ipw/feed.rdf",
                    "Tech"),
    "lifehacker": Site("ライフハッカー・ジャパン - everyday life",
                       "https://www.lifehacker.jp/feed/index.xml", "Practical"),
}


# -- The catalogue ------------------------------------------------------------

def catalogue_file() -> Path:
    """The user's catalogue: {alias: {"name": ..., "url": ..., "genre": ...}}.

    In the data folder rather than the cache, being written by hand.
    """
    return system.data_dir() / "press.json"


def catalogue() -> dict[str, Site]:
    """The built-in table, completed and overridden by the user's file.

    Overriding lets a user fix a feed that moved without waiting for a release.
    """
    known = dict(SITES)
    try:
        raw = json.loads(catalogue_file().read_text(encoding="utf-8-sig"))
    except Exception:
        return known
    if not isinstance(raw, dict):
        return known
    for alias, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        url = str(entry.get("url") or "").strip()
        if not url:
            continue
        name = entry.get("name") or alias
        known[(alias or "").strip().lower()] = Site(
            str(name).strip(), url, str(entry.get("genre") or "").strip())
    return known


def by_genre(known: dict[str, Site] | None = None
             ) -> list[tuple[str, list[tuple[str, Site]]]]:
    """The sites filed by genre, from the general to the specialised.

    A genre the user's file invents goes to the end.
    """
    groups: dict[str, list[tuple[str, Site]]] = {}
    for alias, site in sorted((known if known is not None else catalogue()).items()):
        groups.setdefault(site.genre, []).append((alias, site))

    def rank(pair: tuple[str, list]) -> tuple[int, str]:
        genre = pair[0]
        return (GENRES.index(genre) if genre in GENRES else len(GENRES), genre)

    return sorted(groups.items(), key=rank)


# -- The articles of a site ---------------------------------------------------

def articles(url: str, limit: int = 0) -> list[feed.Item]:
    """The recent articles of a feed, from the newest to the oldest.

    Raises RuntimeError with a reason the menu shows as it is, rather than
    returning an empty list.
    """
    try:
        with download.open_url(url, TIMEOUT) as answer:
            data = download.capped(answer, url)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(_("the site answered {code} - the feed may have moved "
                             "to another address.").format(code=exc.code)) from exc
    except (OSError, http.client.HTTPException) as exc:
        raise download.failure(exc, url) from exc

    try:
        _title, items = feed.read(data, url)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    # Web links only: the feed is someone else's, and the reading route would
    # take a local path for a file of this machine to send to the model.
    usable = [item for item in items if download.is_web(item.link) and item.title]
    if not usable:
        raise RuntimeError(
            _("no article in this feed: {url}. Is that really an RSS address, "
              "and not the one of the home page of the site?").format(url=url))
    return usable[:limit] if limit else usable
