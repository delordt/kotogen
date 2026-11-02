"""A card that says for itself which video codecs the WebView can read.

What a WebView decodes is observed on the machine, not deduced from a version.
The card plays a clip in the generator's profile (`video_clip.encoder_args`)
beside an H.264 one, and a script says which of the two decoded a frame. Anki
desktop under Windows refuses MP4/H.264 (Qt WebEngine is built without the
proprietary codecs) and reads WebM/VP9, hence the generator's VP9.

    python tests/codec_bench.py            # builds the clips and installs the card
    python tests/codec_bench.py --remove   # takes the card, the deck and the clips away

The card is read in Anki (the `Kotogen::Codecs` deck), then on the phone after
a sync: the two verdicts differ. Not a test: pytest does not collect it.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# After adding the path.
from kotogen import video_clip
from kotogen.anki.connect import request as anki, status
from kotogen.anki.media import install_media_files
from kotogen.generators import nhk

# English, like every name kotogen puts in a collection. Never renamed: a rename
# in Anki aims at another type and orphans the old one.
DECK = "Kotogen::Codecs"
NOTETYPE = "Kotogen - codecs"

# Fixed names: they are what `remove` deletes from the media library.
MP4_NAME = "kotogen_codec_h264.mp4"
WEBM_NAME = "kotogen_codec_vp9.webm"

# Three seconds of a 320x180 test pattern: a frame shows, and both files weigh
# less than a photo. The pattern draws its own counter, as a text overlay would
# need fontconfig, missing on many machines.
DURATION = "3"
INPUTS = ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
          "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]

# The other candidate, the most common format and the one a WebView without
# proprietary codecs refuses: an ordinary H.264 profile, not one kotogen produces.
MP4_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
            "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart"]


FRONT = """
<div class="codecs">
  <div class="title">What can this WebView read?</div>

  <div class="trial" data-type="video/webm; codecs=&quot;vp9, opus&quot;">
    <div class="name">WebM / VP9 + Opus <span class="note">(what kotogen produces)</span></div>
    <video controls playsinline preload="auto" src={{WebM}}></video>
    <div class="verdict">loading…</div>
  </div>

  <div class="trial" data-type="video/mp4; codecs=&quot;avc1.4d401e, mp4a.40.2&quot;">
    <div class="name">MP4 / H.264 + AAC <span class="note">(the other candidate)</span></div>
    <video controls playsinline preload="auto" src={{MP4}}></video>
    <div class="verdict">loading…</div>
  </div>

  <div class="where"></div>
</div>

<script>
(function () {
  // Two measurements, and they do not say the same thing. `canPlayType` is a
  // DECLARATION by the engine: it answers "probably" having decoded nothing,
  // and that is exactly where Qt WebEngine can be wrong (or answer "maybe",
  // which means nothing at all). The verdict that counts is the second one: did
  // the file produce a frame? `videoWidth` only becomes non-zero if the video
  // track really was decoded - a file where only the sound gets through leaves
  // it at zero, and that is exactly the black frame we are trying to foresee.
  var TIMEOUT_MS = 8000;

  function show(trial, text, cls) {
    var v = trial.querySelector('.verdict');
    v.textContent = text;
    v.className = 'verdict ' + cls;
  }

  var trials = document.querySelectorAll('.trial');
  for (var i = 0; i < trials.length; i++) {
    (function (trial) {
      var video = trial.querySelector('video');
      var claimed = video.canPlayType(trial.dataset.type) || 'no';
      var done = false;

      function conclude(text, cls) {
        if (done) return;
        done = true;
        show(trial, text + '   (the engine announced: ' + claimed + ')', cls);
      }

      video.addEventListener('loadeddata', function () {
        if (video.videoWidth > 0) {
          conclude('READ - frame decoded in ' + video.videoWidth + 'x' + video.videoHeight, 'ok');
        } else {
          conclude('SOUND ONLY - no frame decoded', 'ko');
        }
      });
      video.addEventListener('error', function () {
        conclude('REFUSED - the file could not be opened', 'ko');
      });
      setTimeout(function () {
        conclude('NO ANSWER - neither frame nor error in ' + (TIMEOUT_MS / 1000) + ' s', 'ko');
      }, TIMEOUT_MS);
    })(trials[i]);
  }

  // Which device this verdict comes from: the card is made to be read twice, on
  // the desktop and on the phone, and the two answers differ.
  var ua = navigator.userAgent || '';
  var where = /Android/i.test(ua) ? 'AnkiDroid (Android)'
            : /Windows/i.test(ua) ? 'Anki desktop (Windows)'
            : /Linux/i.test(ua) ? 'Anki desktop (Linux)'
            : /Mac|iPhone|iPad/i.test(ua) ? 'Anki (Apple)' : 'unknown device';
  document.querySelector('.where').textContent = 'Verdict given on: ' + where;
})();
</script>
"""

CSS = """
.card { background-color: #1e1e1e; color: #eee; font-family: sans-serif; }
.codecs { max-width: 520px; margin: 0 auto; text-align: left; }
.title { font-size: 1.1em; font-weight: bold; margin-bottom: 14px; text-align: center; }
.trial { background-color: #2a2a2a; border-radius: 8px; padding: 10px; margin-bottom: 12px; }
.name { font-weight: bold; margin-bottom: 6px; }
.note { font-weight: normal; color: #9a9a9a; font-size: 0.85em; }
.trial video { width: 100%; max-height: 30vh; display: block; border-radius: 4px; }
.verdict { margin-top: 8px; font-family: monospace; font-size: 0.85em; }
.verdict.ok { color: #7ddc7d; }
.verdict.ko { color: #ff6b6b; }
.where { margin-top: 14px; text-align: center; color: #9a9a9a; font-size: 0.85em; }
"""


def _build_clips(out_dir: Path) -> tuple[Path, Path]:
    """Writes the two clips and gives back their paths.

    The WebM takes the generator's exact profile (`video_clip.encoder_args()`):
    a trial under other settings would say nothing about the cards.
    """
    mp4 = out_dir / MP4_NAME
    webm = out_dir / WEBM_NAME
    nhk._ffmpeg_run(INPUTS, webm,
                    output_args=["-t", DURATION, *video_clip.encoder_args()])
    nhk._ffmpeg_run(INPUTS, mp4, output_args=["-t", DURATION, *MP4_ARGS])
    return mp4, webm


def _install_notetype() -> None:
    """Creates the notetype if it is missing, updates its templates otherwise.

    The update lets a rerun show an edit of `FRONT` or `CSS`.
    """
    template = {"Name": "Codecs", "Front": FRONT, "Back": "{{FrontSide}}"}
    if NOTETYPE in (anki("modelNames") or []):
        anki("updateModelTemplates",
             model={"name": NOTETYPE, "templates": {"Codecs": template}})
        anki("updateModelStyling", model={"name": NOTETYPE, "css": CSS})
        return
    anki("createModel", modelName=NOTETYPE, inOrderFields=["MP4", "WebM"],
         css=CSS, isCloze=False, cardTemplates=[template])


def install() -> None:
    """Builds the clips, drops them in, and installs the card in Anki."""
    state = status()
    if not state.connected:
        sys.exit("Anki unreachable: open it (with AnkiConnect) and run again.\n"
                 "   The card can only be installed where it will be read.")

    with tempfile.TemporaryDirectory(prefix="kotogen_codecs_") as tmp:
        clips = _build_clips(Path(tmp))
        for clip in clips:
            print(f"   {clip.name} ({clip.stat().st_size // 1024} KB)")
        left_out = install_media_files(list(clips))
    if left_out:
        sys.exit("The clips could not reach the media library: "
                 + ", ".join(p.name for p in left_out))

    _install_notetype()
    anki("createDeck", deck=DECK)
    # The previous card goes first, so a rerun leaves exactly one, up to date.
    if previous := (anki("findNotes", query=f'note:"{NOTETYPE}"') or []):
        anki("deleteNotes", notes=previous)
    anki("addNote", note={
        "deckName": DECK, "modelName": NOTETYPE,
        "fields": {"MP4": MP4_NAME, "WebM": WEBM_NAME},
        "options": {"allowDuplicate": True},
        "tags": ["kotogen-verification"],
    })

    print(f"\nCard installed in \"{DECK}\" (profile {state.profile or 'open'}).")
    print("   Open it in Anki: each player says READ, SOUND ONLY or REFUSED.")
    print("   Synchronise, then read it again on the phone: the AnkiDroid verdict")
    print("   is not the desktop one, and it is the comparison that decides.")
    print("\n   video_clip.py writes VP9/WebM, as the desktop plays no H.264.")
    print("   If the WebM is READ on both sides, there is nothing to change.")
    print("   If one side refuses it, the profile in video_clip.py is the place")
    print("   to change, and this card the way to check the new one.")
    print("\n   To take it all away: python tests/codec_bench.py --remove")


def remove() -> None:
    """Takes the card, the deck and the clips away. The notetype stays."""
    if not status().connected:
        sys.exit("Anki unreachable: open it and run again.")

    notes = anki("findNotes", query=f'note:"{NOTETYPE}"') or []
    if notes:
        anki("deleteNotes", notes=notes)
    installed = anki("deckNames") or []
    stale = [name for name in (DECK,) if name in installed]
    if stale:
        anki("deleteDecks", decks=stale, cardsToo=True)
    for name in (MP4_NAME, WEBM_NAME):
        try:
            anki("deleteMediaFile", filename=name)
        except RuntimeError as exc:
            print(f"   {name}: {exc}", file=sys.stderr)

    print(f"Card, deck and clips taken away ({len(notes)} note(s)).")
    # AnkiConnect cannot delete a notetype: this one stays, empty.
    print(f"   The notetype \"{NOTETYPE}\" stays, empty: Anki > Tools >")
    print("   Manage Note Types, if you want to see it gone.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install in Anki a card that says which video codecs its "
                    "WebView can read.")
    parser.add_argument("--remove", action="store_true",
                        help="take the card, the deck and the clips away")
    args = parser.parse_args()
    remove() if args.remove else install()


if __name__ == "__main__":
    main()
