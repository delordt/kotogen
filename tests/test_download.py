"""Opening the web: http and https only, a capped answer, a whole file or none.

Every address read here is someone else's (a feed, a page, a link): urllib's
default opener reads a local file or a `data:` address as readily, which would
copy it into the cache or send it to the model. A server on the loopback stands
for the web.
"""

from __future__ import annotations

import http.client
import http.server
import io
import socket
import ssl
import threading
import urllib.error

import pytest

from kotogen.generators import download


@pytest.fixture
def web():
    """A server on the loopback: `routes` maps a path to (status, headers, body).

    Gives back (base address, routes, the User-Agent of each request).
    """
    routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
    agents: list[str] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            agents.append(self.headers.get("User-Agent", ""))
            status, headers, body = routes[self.path]
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", routes, agents
    server.shutdown()
    server.server_close()


class Endless:
    """An answer that never ends, as a hostile or broken server can send."""

    headers: dict[str, str] = {}

    def __init__(self, guard: int = 8 * 1024 * 1024) -> None:
        self.sent = 0
        self.guard = guard

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            raise AssertionError("read whole, it would never return")
        self.sent += size
        if self.sent > self.guard:
            raise AssertionError("the reading never stopped")
        return b"x" * size

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# -- What is opened -----------------------------------------------------------

def test_a_web_address_is_opened_under_the_name_of_kotogen(web):
    base, routes, agents = web
    routes["/feed"] = (200, {}, b"<rss/>")

    with download.open_url(f"{base}/feed", 5) as answer:
        assert answer.read() == b"<rss/>"
    assert agents == [download.AGENT]


@pytest.mark.parametrize("address", [
    "file:///etc/passwd",
    "ftp://example.test/notes.txt",
    "data:text/plain,secret",
    "C:\\Users\\me\\scan.pdf",
    "passport.pdf",
])
def test_what_is_not_a_web_address_is_refused(address):
    with pytest.raises(RuntimeError, match="not a web address"):
        download.open_url(address, 5)


def test_the_opener_cannot_read_a_file_of_this_machine(tmp_path):
    """Even handed one directly: it has no handler for `file://`."""
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    with pytest.raises(urllib.error.URLError, match="unknown url type"):
        download._opener().open(secret.as_uri(), timeout=5)


def test_a_redirection_off_the_web_is_refused(web):
    """urllib refuses a redirection to `file://` itself, but follows `ftp://`."""
    base, routes, _agents = web
    routes["/moved"] = (302, {"Location": "ftp://127.0.0.1:9/notes.txt"}, b"")

    with pytest.raises(RuntimeError, match="not a web address"):
        download.open_url(f"{base}/moved", 5)


def test_a_redirection_on_the_web_is_followed(web):
    base, routes, _agents = web
    routes["/old"] = (301, {"Location": f"{base}/new"}, b"")
    routes["/new"] = (200, {}, b"moved here")

    with download.open_url(f"{base}/old", 5) as answer:
        assert answer.read() == b"moved here"


# -- How much is read ---------------------------------------------------------

def test_an_answer_that_never_ends_stops_at_the_cap(monkeypatch):
    monkeypatch.setattr(download, "MAX_FEED", 1024)
    with pytest.raises(RuntimeError, match="outsized answer"):
        download.capped(Endless(), "https://example.test/feed")


def test_an_answer_under_the_cap_comes_whole(web):
    base, routes, _agents = web
    routes["/feed"] = (200, {}, b"<rss>" + b"x" * 3_000_000 + b"</rss>")

    with download.open_url(f"{base}/feed", 5) as answer:
        data = download.capped(answer, f"{base}/feed")
    assert data.startswith(b"<rss>") and data.endswith(b"</rss>")


def test_a_file_past_its_limit_leaves_nothing_in_the_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(download, "open_url", lambda url, timeout, headers=None: Endless())
    dest = tmp_path / "files" / "episode.mp3"

    with pytest.raises(RuntimeError, match="outsized file"):
        download.file("https://example.test/episode.mp3", dest, limit=1024 * 1024)
    assert list(dest.parent.iterdir()) == [], "neither the file nor its draft"


def test_a_cut_download_is_not_taken_for_the_whole_file(tmp_path):
    """A server that announces a megabyte and closes after 300 KB: `http.client`
    ends the read without a word, and the cache would keep a third of an episode."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def serve():
        conn, _address = server.accept()
        conn.recv(65536)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n"
                     b"Connection: close\r\n\r\n" + b"x" * 300_000)
        conn.shutdown(socket.SHUT_WR)
        conn.close()

    threading.Thread(target=serve, daemon=True).start()
    dest = tmp_path / "episode.mp3"
    try:
        with pytest.raises(RuntimeError, match="download interrupted"):
            download.file(f"http://127.0.0.1:{server.getsockname()[1]}/episode.mp3",
                          dest)
    finally:
        server.close()
    assert list(tmp_path.iterdir()) == [], "neither the file nor its draft"


class Cut(io.BytesIO):
    """An answer that announces more than it holds, as a dropped connection leaves it."""

    def __init__(self, body: bytes, announced: int) -> None:
        super().__init__(body)
        self.headers = {"Content-Length": str(announced)}


def test_a_page_cut_short_is_not_taken_for_the_whole_page(monkeypatch):
    """Half an Aozora work page, or a lesson listing fewer tracks, would pass."""
    monkeypatch.setattr(download, "open_url",
                        lambda url, timeout, headers=None: Cut(b"x" * 300, 1000))
    with pytest.raises(RuntimeError, match="download interrupted"):
        download.page("https://example.test/lesson")


def test_a_whole_page_comes_back(monkeypatch):
    monkeypatch.setattr(download, "open_url",
                        lambda url, timeout, headers=None: Cut(b"<html/>", 7))
    assert download.page("https://example.test/lesson") == b"<html/>"


def test_a_page_past_the_cap_raises_rather_than_comes_back_cut(monkeypatch):
    monkeypatch.setattr(download, "MAX_FEED", 1024)
    monkeypatch.setattr(download, "open_url", lambda url, timeout, headers=None: Endless())
    with pytest.raises(RuntimeError, match="outsized answer"):
        download.page("https://example.test/catalogue")


def test_the_draft_left_held_by_windows_does_not_hide_the_interruption(
        monkeypatch, tmp_path):
    """After a Ctrl+C, the unlink of a draft still open raises WinError 32."""
    class Interrupted(Endless):
        def read(self, size=-1):
            raise KeyboardInterrupt

    def held(self, missing_ok=False):
        raise PermissionError(32, "in use by another process")

    monkeypatch.setattr(download, "open_url", lambda url, timeout, headers=None: Interrupted())
    monkeypatch.setattr(download.Path, "unlink", held)
    with pytest.raises(KeyboardInterrupt):
        download.file("https://example.test/episode.mp3", tmp_path / "episode.mp3")


@pytest.mark.parametrize("error", [
    http.client.IncompleteRead(b"x" * 10, 90),
    http.client.BadStatusLine("garbage"),
    ConnectionResetError(10054, "reset"),
])
def test_a_broken_answer_is_said_in_plain_words(error):
    said = str(download.failure(error, "https://example.test/a.mp3"))

    assert said == "download interrupted - check your connection."


def test_an_unreachable_site_says_why():
    error = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
    said = str(download.failure(error, "https://example.test/feed"))

    assert said.startswith("site unreachable")
    assert "getaddrinfo failed" in said


CERTIFICATE = ssl.SSLCertVerificationError(
    1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
       "unable to get local issuer certificate")


def test_a_certificate_failure_on_macos_names_what_to_run(monkeypatch):
    """The Python of python.org on macOS installs no certificates of its own."""
    monkeypatch.setattr(download.system, "macos", lambda: True)
    said = str(download.failure(urllib.error.URLError(CERTIFICATE), "https://example.test/"))

    assert "CERTIFICATE_VERIFY_FAILED" in said
    assert "Install Certificates.command" in said


def test_a_certificate_failure_elsewhere_names_the_usual_causes(monkeypatch):
    monkeypatch.setattr(download.system, "macos", lambda: False)
    said = str(download.failure(urllib.error.URLError(CERTIFICATE), "https://example.test/"))

    assert "CERTIFICATE_VERIFY_FAILED" in said
    assert "Install Certificates" not in said and "proxy" in said


def test_the_agent_gives_the_address_of_the_project():
    """Wikipedia asks a robot for a way to reach whoever runs it."""
    assert "+https://github.com/delordt/kotogen" in download.AGENT


# -- The key of an address ----------------------------------------------------

def test_two_addresses_of_one_host_have_two_keys():
    one = download.url_key("https://files.example.test/a/sample.pdf")
    two = download.url_key("https://files.example.test/b/sample.pdf")
    assert one != two
    assert one.startswith("files-example-test-")


def test_an_address_with_no_host_takes_the_default():
    assert download.url_key("https:///sample.pdf", "feed").startswith("feed-")
