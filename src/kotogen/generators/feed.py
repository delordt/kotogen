"""A feed of articles or episodes, in any of its three dialects.

RSS 2.0 (`<rss><channel><item>`), RSS 1.0 alias RDF (`<rdf:RDF>`, items at the
root and dates in `dc:date`) and Atom (`<feed><entry>`, the link an attribute).
Only the common trunk is read: the feed's name, and each item's title, link and
date. What one use alone needs, such as a podcast's `enclosure`, the caller
reads off `element`. No network access: bytes in, objects out.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from kotogen.i18n import _

RSS1 = "http://purl.org/rss/1.0/"
ATOM = "http://www.w3.org/2005/Atom"
DC = "http://purl.org/dc/elements/1.1/"


@dataclass(frozen=True)
class Item:
    """One entry of the feed: what the three dialects have in common.

    `element` carries the raw entry, for what is specific to one dialect or use.
    """

    title: str
    link: str
    published: str
    element: ET.Element


def _text(element: ET.Element, *paths: str) -> str:
    """The first of these paths that carries something, cleaned up."""
    for path in paths:
        value = element.findtext(path)
        if value and value.strip():
            return value.strip()
    return ""


def _link(item: ET.Element) -> str:
    """The address of the article. In Atom it is an attribute, not content.

    Of several Atom `link`s (the article, its comments, its edit form),
    `alternate` is the one read, and the default when `rel` is missing.
    """
    direct = _text(item, "link", f"{{{RSS1}}}link")
    if direct:
        return direct
    for link in item.findall(f"{{{ATOM}}}link"):
        if (link.get("rel") or "alternate") == "alternate":
            address = (link.get("href") or "").strip()
            if address:
                return address
    return ""


def when(published: str):
    """A usable date, or None: RFC 822 (RSS) or ISO 8601 (RDF, Atom)."""
    published = (published or "").strip()
    if not published:
        return None
    try:
        return parsedate_to_datetime(published)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return None


def order(objects: list, date_of) -> list:
    """Newest to oldest, but only if EVERY date can be read.

    The feed's own order is almost always right, and sorting on half-missing
    dates would do worse. Dates of which only one has a time zone do not
    compare either: the order received is then kept.
    """
    dates = [when(date_of(item)) for item in objects]
    if not objects or any(date is None for date in dates):
        return objects
    try:
        return [item for _, item in sorted(
            zip(dates, objects), key=lambda pair: pair[0], reverse=True)]
    except TypeError:
        return objects


def read(data: bytes, url: str = "") -> tuple[str, list[Item]]:
    """(name of the feed, items newest to oldest).

    Valid XML that is not a feed gives an empty list rather than an error: the
    caller says what was missing ("no audio episode", "no article").
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        said = (_("unreadable RSS feed: {url} ({error})") if url
                else _("unreadable RSS feed ({error})"))
        raise ValueError(said.format(url=url, error=exc)) from exc

    tag = root.tag.split("}")[-1].lower()
    if tag == "feed":                                       # Atom
        header, items = root, root.findall(f"{{{ATOM}}}entry")
    elif tag == "rdf":                                      # RSS 1.0
        header = root.find(f"{{{RSS1}}}channel")
        items = root.findall(f"{{{RSS1}}}item")
    else:                                                   # RSS 2.0
        header = root.find("channel")
        items = (header if header is not None else root).findall("item")

    name = _text(header, "title", f"{{{ATOM}}}title",
                 f"{{{RSS1}}}title") if header is not None else ""
    parsed = [Item(title=_text(item, "title", f"{{{ATOM}}}title", f"{{{RSS1}}}title"),
                   link=_link(item),
                   published=_text(item, "pubDate", f"{{{DC}}}date",
                                   f"{{{ATOM}}}updated", f"{{{ATOM}}}published"),
                   element=item)
              for item in items]
    return name, order(parsed, lambda item: item.published)
