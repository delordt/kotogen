"""Bring a file back into the cache, once and once only, and open the web safely.

Shared by the sources that download (JLPT past papers, いろどり, 青空朗読,
podcasts). A file in the cache is a whole file: it is written under a `.part`
name and renamed at the end, so a cut download is never taken for the good one
next time. A failure is a `RuntimeError` with a sentence for the screen, never
an `urllib` traceback. The caller chooses the file name.

Every address read here is written by someone else (a feed, a page, a link), so
`open_url` opens http and https only, after a redirection too: urllib's default
opener would read a `file://`, `ftp://` or `data:` address as readily.
"""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from kotogen import __version__, console, system
from kotogen.i18n import _, quoted

# A name of our own rather than urllib's default ("Python-urllib/3.x"), which
# many Japanese sites and podcast hosts answer with a 403. It names kotogen
# rather than posing as a browser, with the address Wikipedia asks a robot for.
AGENT = f"Mozilla/5.0 (compatible; kotogen/{__version__}; +https://github.com/delordt/kotogen)"

TIMEOUT = 30        # seconds, for a page or a catalogue
FILE_TIMEOUT = 300  # a twenty-minute mp3 or a past-paper booklet: longer

# Past this it is not the file asked for. The vision API's limit on a PDF is
# checked by its caller.
MAX_FILE = 60 * 1024 * 1024

# Past this a feed or a page is not one: the longest-running podcast feeds weigh
# a few megabytes. The cap is what ends an answer that never does.
MAX_FEED = 40 * 1024 * 1024

WEB = ("http", "https")

HEADERS = {"User-Agent": AGENT, "Accept-Language": "ja,en;q=0.8"}

_BLOCK = 1 << 20


def is_web(url: str) -> bool:
    """True if `url` is an http or https address."""
    return urllib.parse.urlsplit((url or "").strip()).scheme.lower() in WEB


def _not_web(url: str) -> RuntimeError:
    return RuntimeError(_("not a web address (http or https only): {url}")
                        .format(url=url))


class _WebRedirects(urllib.request.HTTPRedirectHandler):
    """Follows a redirection to http or https only: urllib's own lets `ftp://` by."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_web(newurl):
            fp.close()
            raise _not_web(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    """urllib's default opener without its `file`, `ftp` and `data` handlers.

    Built at each call, as `urlopen` builds its own on first use: the proxy
    variables are read once the settings have been loaded.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.ProxyHandler(), urllib.request.UnknownHandler(),
                    urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(),
                    urllib.request.HTTPDefaultErrorHandler(), _WebRedirects(),
                    urllib.request.HTTPErrorProcessor()):
        opener.add_handler(handler)
    return opener


def open_url(url: str, timeout: float, headers: dict[str, str] | None = None):
    """The answer of a web address, as `urllib.request.urlopen` gives it.

    Anything but http or https raises a `RuntimeError` for the screen. `headers`
    replaces the default ones, which carry `AGENT`.
    """
    if not is_web(url):
        raise _not_web(url)
    request = urllib.request.Request(url, headers=headers or {"User-Agent": AGENT})
    return _opener().open(request, timeout=timeout)


def capped(answer, url: str) -> bytes:
    """All that `answer` holds, or a `RuntimeError` once past `MAX_FEED`."""
    data = bytearray()
    while block := answer.read(_BLOCK):
        data += block
        if len(data) > MAX_FEED:
            raise RuntimeError(
                _("outsized answer (over {limit} MB) - this is not a feed or a "
                  "page: {url}").format(limit=MAX_FEED // (1024 * 1024), url=url))
    return bytes(data)


def url_key(url: str, default: str = "web") -> str:
    """A key for what an address names: its host, plus a fingerprint of the address.

    One host serves thousands of shows or files; the host keeps the key readable.
    """
    host = urllib.parse.urlsplit(url).hostname or default
    host = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-")
    return f"{host}-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]}"


def failure(exc: BaseException, url: str) -> RuntimeError:
    """A failed download as it will be displayed, with no traceback or module name.

    Shared by every reader of the web, so that one breakdown reads the same
    whichever route met it.
    """
    if isinstance(exc, urllib.error.HTTPError):
        return RuntimeError(_("page unreachable (HTTP {code} {reason}): {url}")
                            .format(code=exc.code, reason=exc.reason, url=url))
    if isinstance(exc, urllib.error.URLError):
        cause = console.reason(exc.reason)
        if (isinstance(exc.reason, ssl.SSLCertVerificationError)
                or "CERTIFICATE_VERIFY_FAILED" in str(exc.reason)):
            # The Python of python.org on macOS ships without the certificates.
            if system.macos():
                return RuntimeError(
                    _("the certificate of the site could not be verified ({reason}) - "
                      "with the Python of python.org, run {command} from its folder in "
                      "Applications.").format(
                        reason=cause, command=quoted("Install Certificates.command")))
            return RuntimeError(
                _("the certificate of the site could not be verified ({reason}) - check "
                  "the date of this computer and the proxy of your network.")
                .format(reason=cause))
        return RuntimeError(_("site unreachable ({reason}) - check the URL and your "
                              "connection.").format(reason=cause))
    # A cut answer (`IncompleteRead`), a garbled one (`BadStatusLine`), a reset.
    if isinstance(exc, (http.client.HTTPException, ConnectionError, TimeoutError)):
        return RuntimeError(_("download interrupted - check your connection."))
    return RuntimeError(_("download interrupted: {error}").format(
        error=console.reason(exc)))


class Progress:
    """How much of the current file has arrived, for the waiting line.

    Against the total the server announces, if any; without one, the bytes
    received still show that it moves. Public, so that yt-dlp's progress
    callback is said the same way.
    """

    def __init__(self) -> None:
        self.received = 0
        self.total = 0

    def status(self) -> str:
        if not self.received and not self.total:
            # Nothing has arrived yet, or what is left is not network: the
            # spinner alone says it is working.
            return ""
        if not self.total:
            return console.size(self.received)
        return _("{received} of {total}").format(
            received=console.size(self.received), total=console.size(self.total))


def page(url: str, *, timeout: int = TIMEOUT) -> bytes:
    """The content of a page or a catalogue, in memory.

    For what is read and not kept: what weighs goes to disk through `file`.
    """
    def read() -> bytes:
        with open_url(url, timeout, HEADERS) as answer:
            data = capped(answer, url)
            check_whole(len(data), int(answer.headers.get("Content-Length") or 0))
            return data

    try:
        # Behind the waiting line, which shows how long a silent site has taken.
        return console.while_working(read)
    except RuntimeError:
        raise
    except Exception as exc:
        raise failure(exc, url) from exc


def file(url: str, dest: Path, *, timeout: int = FILE_TIMEOUT,
         limit: int = MAX_FILE) -> Path:
    """Download `url` to `dest`, or return `dest` as it is if it is there already.

    A file found in the cache is not reported: nothing happened, and the cache
    is disposable (wiped, everything downloads again). Past `limit` bytes the
    download stops and raises.
    """
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    draft = dest.with_suffix(dest.suffix + ".part")
    progress = Progress()

    def fetch() -> None:
        with open_url(url, timeout, HEADERS) as answer, open(draft, "wb") as out:
            progress.total = int(answer.headers.get("Content-Length") or 0)
            while block := answer.read(_BLOCK):
                progress.received += len(block)
                if progress.received > limit:
                    raise RuntimeError(
                        _("outsized file (over {limit} MB) - this is not what "
                          "was expected at this address: {url}")
                        .format(limit=limit // (1024 * 1024), url=url))
                out.write(block)

    try:
        # The progress says where one is in the file: a 40 MB mp3 takes minutes.
        console.while_working(fetch, progress.status)
        if not progress.received:
            raise RuntimeError(_("empty file at this address: {url}").format(url=url))
        check_whole(progress.received, progress.total)
        draft.replace(dest)
    except RuntimeError:
        raise
    except Exception as exc:
        raise failure(exc, url) from exc
    finally:
        # Windows may still hold the draft after a Ctrl+C (WinError 32): its
        # PermissionError would replace the KeyboardInterrupt.
        with contextlib.suppress(OSError):
            draft.unlink(missing_ok=True)
    return dest


def check_whole(received: int, announced: int) -> None:
    """Raises if fewer bytes arrived than the server announced.

    `http.client` ends a read on a closed connection without a word, so a cut
    download would otherwise pass for the whole file.
    """
    if announced and received < announced:
        raise RuntimeError(_("download interrupted - check your connection."))


def name_from(url: str, default: str = "file") -> str:
    """The file name a URL carries, or `default` if it carries none."""
    return Path(urllib.parse.urlsplit(url).path).name or default
