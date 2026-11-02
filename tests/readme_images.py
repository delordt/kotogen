"""The pictures of the README, taken again from the program itself.

The README shows the five cards and the assistant's main menu, and both drift
from the program without anything failing. This script takes them all again:

- the cards are the faces of the preview (`kotogen.anki.preview`) at the default
  settings, in English whatever `all.lang` says;
- the menu is the one `kotogen` prints, run in a process of its own against a
  stand-in AnkiConnect with every note type installed.

    python tests/readme_images.py

The pictures land in `docs/images/`, a light and a dark one per card, which the
README hands to GitHub in a `<picture>`. It needs Playwright and its Chromium
(the `[nhk]` extra), Pillow (`[pdf]`) and FFmpeg, without which the listening
card shows an empty player. Not a test: pytest does not collect it.
"""

from __future__ import annotations

import base64
import html
import io
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from kotogen import console, menu, prompts, settings
from kotogen.ai_client import KEY_VARS
from kotogen.anki import preview

try:
    from PIL import Image
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit('Pillow and Playwright are needed: pip install -e ".[pdf,nhk]", '
             "then playwright install chromium.")

OUT = ROOT / "docs" / "images"

# A phone, in CSS pixels. Cards are cut at that height, so that side by side
# they read as screens of one size.
PHONE = (390, 700)

# The faces shown, by their key in the preview: sample, card, face. A key gone
# from the preview stops the run rather than leave a hole in a row.
PAIRS = {
    "kanji": ("kanji-recognition-front", "kanji-recognition-back"),
    "vocabulary": ("vocab-recognition-front", "vocab-recognition-back"),
    "grammar": ("grammar-grammar-front", "grammar-grammar-back"),
    "listening": ("audio-listening-front", "audio-listening-back"),
    "reading": ("reading-reading-front", "reading-reading-back"),
}
# The head of the README: four backs. The reading card stays out: beside the
# listening one, it would ask the same question twice.
BANNER = ("kanji-recognition-back", "vocab-recognition-back",
          "grammar-grammar-back", "audio-listening-back")

PALETTES = ("dark", "light")

# The model the status line of the menu names: none is built in, and the picture
# puts none forward, only the shape of an OpenRouter id.
PICTURED_MODEL = "publisher/model"

# The templates shuffle the choices from the note and the day of review: one
# day, frozen in one time zone, keeps the pictures the same from run to run, so
# the diff shows only the cards that moved. This one puts no answer first.
_TIME_ZONE = "UTC"
_DAY = datetime(2026, 8, 19, 12, tzinfo=timezone.utc)


# -- The cards ----------------------------------------------------------------

def _documents(browser, url: str) -> dict[str, dict[str, str]]:
    """Palette -> face key -> the document the preview lays in that face's frame.

    The controls are found by their attributes, not their translated words.
    "Apply" is never pressed, so nothing reaches the user's `templates.env`.
    """
    shell = browser.new_page(viewport={"width": 1600, "height": 1000})
    shell.goto(url)
    defaults = shell.locator("#defaults")
    if defaults.is_enabled():
        defaults.click()
    found: dict[str, dict[str, str]] = {}
    for palette in PALETTES:
        shell.click(f'button[data-key="all.palette"][data-position="{palette}"]')
        documents = found[palette] = {}
        tabs = shell.locator("#tabs button")
        for i in range(tabs.count()):
            tabs.nth(i).click()
            subtabs = shell.locator("#subtabs button")
            views = subtabs.count() if shell.locator("#subtabs").is_visible() else 0
            for j in range(max(views, 1)):
                if views:
                    subtabs.nth(j).click()
                frames = shell.locator("#cards iframe")
                for k in range(frames.count()):
                    key = frames.nth(k).get_attribute("id").removeprefix("if-")
                    documents[key] = frames.nth(k).get_attribute("srcdoc")
    shell.close()
    return found


def _face(browser, document: str) -> bytes:
    """One face at phone size, its folded parts opened.

    A listening card's transcript and a reading card's text sit in a
    `<details>` the reviewer opens.
    """
    page = browser.new_page(viewport={"width": PHONE[0], "height": PHONE[1]},
                            device_scale_factor=2, timezone_id=_TIME_ZONE)
    # The clock of Playwright, not an init script: `set_content` lays the page
    # in the blank document, where an init script has never run.
    page.clock.set_fixed_time(_DAY)
    page.set_content(document)
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    # The player reads the length of its sound once the media has answered.
    page.wait_for_timeout(900)
    shot = page.screenshot()
    page.close()
    return shot


_ROW = """<!doctype html><meta charset="utf-8"><style>
html, body {{ margin: 0; background: transparent; }}
.row {{ display: inline-flex; align-items: flex-start; gap: {gap}px; padding: 28px; }}
.phone {{ width: {width}px; border-radius: {radius}px; overflow: hidden;
  box-shadow: 0 10px 30px rgba(0, 0, 0, .28), 0 0 0 1px rgba(127, 127, 127, .28); }}
.phone img {{ display: block; width: 100%; }}
.arrow {{ align-self: center; font: 600 34px system-ui, sans-serif; color: #8a8f99; }}
</style><div class="row">{cells}</div>"""


def _phones(browser, shots: list[bytes], *, gap: int, arrow: bool, scale: float) -> bytes:
    """Faces laid side by side as phones, on a transparent ground.

    Transparent to sit on GitHub's white and black alike; the border and the
    shadow draw the edge of a card whose ground matches the page.
    """
    cells = ['<div class="phone"><img src="data:image/png;base64,'
             + base64.b64encode(shot).decode() + '"></div>' for shot in shots]
    if arrow:
        cells.insert(1, '<div class="arrow">&rarr;</div>')
    width = 300
    page = browser.new_page(viewport={"width": 2400, "height": 1000},
                            device_scale_factor=scale)
    page.set_content(_ROW.format(gap=gap, width=width, radius=round(width / 13),
                                 cells="".join(cells)))
    shot = page.locator(".row").screenshot(omit_background=True)
    page.close()
    return shot


# -- The menu -----------------------------------------------------------------

# AnkiConnect's answers for an open profile with every note type installed:
# the menu shows no warning under its status line.
_ANSWERS = {
    "version": 6,
    "getActiveProfile": "User 1",
    "deckNames": sorted(deck for deck, _type in settings.DECK_DEFAULTS.values()),
    "modelNames": sorted(kind for _deck, kind in settings.DECK_DEFAULTS.values()),
}


class _Anki(BaseHTTPRequestHandler):
    """A stand-in for AnkiConnect, for the time the menu takes to print."""

    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        action = body.get("action")
        answer = ({"result": _ANSWERS[action], "error": None} if action in _ANSWERS
                  else {"result": None, "error": f"unsupported action: {action}"})
        data = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _menu_lines() -> list[str]:
    """The main menu as `kotogen` prints it, from the banner to the last entry.

    The environment overrides the settings files, which keeps the profile's
    choices (model, hidden commands, language) out of the picture. On a pipe the
    menu is the numbered one read with Enter: the same lines without the
    terminal codes, and "q" closes it.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Anki)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               KOTOGEN_LANG="en", KOTOGEN_INSTALL="never", KOTOGEN_SKIP="",
               KOTOGEN_PROVIDER="openrouter", KOTOGEN_MODEL=PICTURED_MODEL,
               KOTOGEN_ANKICONNECT_URL=f"127.0.0.1:{server.server_address[1]}",
               KOTOGEN_ANKICONNECT_KEY="")
    # A key is only read for whether it is there: the menu calls nobody.
    env[KEY_VARS["openrouter"]] = "sk-or-readme"
    for command, (deck, kind) in settings.DECK_DEFAULTS.items():
        env[f"KOTOGEN_{command.upper()}_DECK"] = deck
        env[f"KOTOGEN_{command.upper()}_NOTETYPE"] = kind
    try:
        # A pipe is no terminal, and the assistant refuses to open there: this
        # one run is let through, as the tests of the menu let it.
        run = subprocess.run([sys.executable, "-c", OPEN_ON_A_PIPE], input=b"q\n",
                             capture_output=True, env=env, cwd=ROOT, timeout=60)
    finally:
        server.shutdown()
        server.server_close()
    lines = [line.rstrip() for line in run.stdout.decode("utf-8").splitlines()]
    # What the pipe adds around the screen: the clearing that has nothing to
    # clear, and the prompt of the numbered entry.
    lines = [line for line in lines if line.strip() != ">"]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not any(re.match(r"\s+1\. ", line) for line in lines):
        sys.exit("kotogen printed no menu:\n" + run.stdout.decode("utf-8", "replace")
                 + run.stderr.decode("utf-8", "replace"))
    return lines


OPEN_ON_A_PIPE = ("from kotogen import cli; "
                  "cli._assistant_can_open = lambda: True; cli.main()")


_TERMINAL = """<!doctype html><meta charset="utf-8"><style>
html, body {{ margin: 0; background: transparent; }}
.wrap {{ display: inline-block; padding: 28px; }}
.window {{ background: #15171c; border-radius: 12px; overflow: hidden;
  box-shadow: 0 10px 30px rgba(0, 0, 0, .30), 0 0 0 1px rgba(127, 127, 127, .30); }}
.bar {{ height: 36px; display: flex; align-items: center; gap: 8px; padding: 0 14px;
  background: #1f2229; }}
.dot {{ width: 12px; height: 12px; border-radius: 50%; background: #3a3f4b; }}
.name {{ flex: 1; text-align: center; margin-right: 52px;
  font: 13px system-ui, "Segoe UI", sans-serif; color: #8b93a3; }}
pre {{ margin: 0; padding: 18px 26px 22px; color: #d7dae1;
  font: 15px/1.45 "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; }}
.banner {{ display: block; line-height: 1; margin: .2em 0 -1.3em; }}
.reverse {{ background: #d7dae1; color: #15171c; }}
</style><div class="wrap"><div class="window"><div class="bar"><span class="dot"></span>
<span class="dot"></span><span class="dot"></span><span class="name">kotogen</span></div>
<pre>{text}</pre></div></div>"""

# The reverse video of `menu.emphasise` and its reset. No code for dimmed
# entries: the stand-in Anki and the key leave none.
_CODES = {"\033[7m": '<span class="reverse">', "\033[0m": "</span>"}


def _terminal(browser, lines: list[str]) -> bytes:
    """The menu in a terminal window, as it opens: aimed at its first entry.

    The bar is painted by `menu.emphasise`, as in the key-driven menu. The
    banner's half blocks join only with no space between lines: it gets a line
    height of its own.
    """
    block = [line for line in lines if line.startswith("  ")]
    width = max(console.width(line) for line in block)
    aimed = next(i for i, line in enumerate(lines) if re.match(r"\s+1\. ", line))
    shown = [menu.emphasise(line, width) if i == aimed else line
             for i, line in enumerate(lines)]
    text = [html.escape(line) for line in shown]
    for i, line in enumerate(text):
        for code, tag in _CODES.items():
            line = line.replace(code, tag)
        text[i] = line
    banner = [i for i, line in enumerate(lines) if "█" in line]
    if banner:
        first, last = banner[0], banner[-1] + 1
        text[first:last] = ['<span class="banner">' + "\n".join(text[first:last])
                            + "</span>"]
    page = browser.new_page(viewport={"width": 1400, "height": 1000},
                            device_scale_factor=2)
    page.set_content(_TERMINAL.format(text="\n".join(text)))
    shot = page.locator(".wrap").screenshot(omit_background=True)
    page.close()
    return shot


# -- The files ----------------------------------------------------------------

def _save(shot: bytes, name: str) -> None:
    """A screenshot cut down to a palette of 256 colours, and written.

    A quarter of the weight. The nearly transparent edge of the shadow is
    cleared first, or the palette turns the margin into a faint grey box.
    """
    picture = Image.open(io.BytesIO(shot)).convert("RGBA")
    alpha = picture.getchannel("A").point(lambda a: 0 if a < 12 else a)
    picture = Image.composite(picture, Image.new("RGBA", picture.size), alpha)
    flat = picture.quantize(colors=256, method=Image.Quantize.FASTOCTREE,
                            dither=Image.Dither.NONE)
    flat.save(OUT / name, optimize=True)
    print(f"   docs/images/{name}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # The samples follow `all.lang`, and the README is English.
    prompts.use("en")
    try:
        served = preview.serve(preview.samples(), open_browser=False)
    except preview.Unavailable as exc:
        sys.exit(str(exc))
    for note in served.notes:
        print(note, file=sys.stderr)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            documents = _documents(browser, served.url)
            wanted = {key for pair in PAIRS.values() for key in pair} | set(BANNER)
            for palette in PALETTES:
                missing = sorted(wanted - set(documents[palette]))
                if missing:
                    sys.exit(f"Not in the preview any more: {', '.join(missing)}. "
                             f"The faces shown are named at the head of this file.")
                faces = {key: _face(browser, documents[palette][key]) for key in wanted}
                _save(_phones(browser, [faces[key] for key in BANNER],
                              gap=26, arrow=False, scale=2), f"cards-{palette}.png")
                for name, pair in PAIRS.items():
                    _save(_phones(browser, [faces[key] for key in pair],
                                  gap=20, arrow=True, scale=1.5), f"{name}-{palette}.png")
            _save(_terminal(browser, _menu_lines()), "assistant.png")
            browser.close()
    finally:
        served.stop()


if __name__ == "__main__":
    main()
