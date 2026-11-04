"""The card preview: every template in the browser, adjustable on the spot.

Python fills the fields of the raw template, markers kept, and the page removes
the blocks itself by the same rule, so a switch redraws a card on the spot; the
fingerprint of the Python rendering tells when the two rules part. The page is
served rather than written to a file, so that Apply can write and a refresh
reads `templates/` again.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import threading
import unicodedata
import webbrowser
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import token_urlsafe

from kotogen import console, exporter, prompts, system
from kotogen.anki import notetypes, templates as card_templates
from kotogen.i18n import _, counted, listed, quoted as _quoted


class Unavailable(RuntimeError):
    """The preview cannot open, and the reason is said to whoever asked for it."""


# -- The samples ---------------------------------------------------------------
#
# Every card that looks different: the kanji, the vocabulary both ways round,
# the grammar, the listening as a sound or a video, the reading as a text, a
# mini-book or a composed document. The fields exercise the template: two
# sentences in a row from one speaker (turn grouping), a key line, one timestamp
# per line, a label in kanji (it arrives as <ruby>, which no string pattern
# would match).


@dataclass(frozen=True)
class Sample:
    """A set of plausible fields, and what it comes to show.

    `command` names the note type, which decides the templates, the CSS and the
    switches. Two samples may share one, as the text and the mini-book do.
    """

    key: str            # reading-book
    command: str        # reading
    label: str          # "Reading"
    detail: str         # "a mini-book": what THIS sample shows
    fields: dict[str, str] = field(default_factory=dict)
    # Per other language of the cards (`all.lang`), the fields that carry
    # language: the Japanese, the tags and the media are the same in all of them.
    overlays: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def title(self) -> str:
        # `label` is the note type's name in the collection, kept as it is;
        # `detail` is translated, here rather than at import time.
        return f"{self.label} - {_(self.detail)}" if self.detail else self.label

    def told(self) -> Sample:
        """The same sample, in the language the cards are written in."""
        overlay = self.overlays.get(prompts.language())
        if not overlay:
            return self
        return replace(self, fields={**self.fields, **overlay})


# The example media, made further down and served beside the page. Named here
# because the fields cite them.
SOUND = "sound.mp3"
CLIP = "clip.webm"
PAGES = ("page1.svg", "page2.svg", "page3.svg")
# The composed document of a reading card: a poster, a table.
POSTER = "poster.svg"

# Everything the server agrees to serve: a medium a sample cites but missing here
# is a 404, and the card shows with a hole.
MEDIA = (SOUND, CLIP, POSTER, *PAGES)

_LISTENING = {
    "ID": "demo_001",
    # The whole tag, as a real note's field carries it (see `exporter.audio_ref`).
    "Audio": exporter.audio_ref(SOUND),
    # Filled by the video sample alone, never with Audio: the card plays one
    # medium only (see templates/audio/front.html).
    "Video": "",
    "Question": "Where is the station?",
    "Decoy1": "Left after the lights",
    "Decoy2": "Behind the post office",
    "Decoy3": "You have to take the bus",
    "Image": "",
    "Answer": "Straight on, then right",
    "Transcript": ("A： すみません、 駅[えき]はどこですか。\n"
                   "駅員[えきいん]： まっすぐ 行[い]ってください。\n"
                   "駅員[えきいん]： そのあと 右[みぎ]に 曲[ま]がります。\n"
                   "A： ありがとうございます。"),
    "Translation": ("A: Excuse me, where is the station?\n"
                    "The clerk: Go straight on.\n"
                    "The clerk: Then turn right.\n"
                    "A: Thank you very much."),
    "Timecodes": "0.50 3.00 4.20 7.10",
    # The third sentence, which the back marks: a rank, as on the reading card,
    # not an arrow inside the text.
    "KeyLine": "3",
    "Source": "demo.mkv (00:12 → 00:48)",
    # An Anki variable, not a field: the level badge over the question reads it.
    "Tags": "Level::N4",
}

_READING = {
    "ID": "RC_demo_001",
    "Text": ("今日[きょう]は 朝[あさ]から 雨[あめ]が 降[ふ]っています。\n"
             "でも 午後[ごご]には 晴[は]れるそうです。"),
    "Images": "",
    # In the language of the cards, under `{{furigana::Question}}` all the same:
    # a Japanese deck asks in Japanese, with readings laid by the export.
    "Question": "When is the weather going to clear up?",
    "Decoy1": "Tomorrow morning",
    "Decoy2": "Right away",
    "Decoy3": "During the night",
    "Answer": "In the afternoon",
    # Line for line with `Text`: the back lays each line under its sentence and
    # brings the key line (the second) forward.
    "Translation": ("It has been raining since this morning.\n"
                    "But it is supposed to clear up in the afternoon."),
    "KeyLine": "2",
    # A text points at a line, never a page: `KeyPage` is the mini-book's (see
    # the `reading-book` sample).
    "KeyPage": "",
    "Source": "https://news.web.nhk/news/easy/demo/demo.html",
    "Tags": "Level::N4",
}

# The same fields in each other language of the cards, kept apart so that the
# Japanese, the timecodes and the media are written once.
_LISTENING_FR = {
    "Question": "Où se trouve la gare ?",
    "Decoy1": "À gauche après le feu",
    "Decoy2": "Derrière la poste",
    "Decoy3": "Il faut prendre le bus",
    "Answer": "Tout droit, puis à droite",
    "Translation": ("A : Excusez-moi, où est la gare ?\n"
                    "L'employé : Allez tout droit.\n"
                    "L'employé : Ensuite, tournez à droite.\n"
                    "A : Merci beaucoup."),
}

_READING_FR = {
    "Question": "Quand le temps va-t-il se dégager ?",
    "Decoy1": "Demain matin",
    "Decoy2": "Tout de suite",
    "Decoy3": "Dans la nuit",
    "Answer": "Dans l'après-midi",
    "Translation": ("Depuis ce matin, il pleut.\n"
                    "Mais il paraît que ça va se dégager dans l'après-midi."),
}

# A Japanese deck explains in easier Japanese, with readings on what goes
# through the furigana filter. Fields shown as they stand carry none: a word's
# `Context`, a grammar gap's hints, the words listed by a kanji.
_LISTENING_JA = {
    "Question": "駅[えき]はどこにありますか。",
    "Decoy1": "信号[しんごう]を 左[ひだり]に 曲[ま]がったところ",
    "Decoy2": "郵便局[ゆうびんきょく]のうしろ",
    "Decoy3": "バスに 乗[の]って 行[い]くところ",
    "Answer": "まっすぐ 行[い]って、 右[みぎ]に 曲[ま]がったところ",
    "Translation": ("A：すみません、 駅[えき]はどこにありますか。\n"
                    "駅員[えきいん]：まっすぐ 進[すす]んでください。\n"
                    "駅員[えきいん]：それから 右[みぎ]へ 曲[ま]がります。\n"
                    "A：どうもありがとう。"),
}

_READING_JA = {
    "Question": "天気[てんき]はいつよくなりますか。",
    "Decoy1": "明日[あした]の 朝[あさ]",
    "Decoy2": "すぐに",
    "Decoy3": "夜[よる]のあいだ",
    "Answer": "午後[ごご]",
    "Translation": ("今日[きょう]は 朝[あさ]からずっと 雨[あめ]です。\n"
                    "でも、 午後[ごご]は 晴[は]れると 言[い]われています。"),
}

_VOCAB_JA = {
    "Translation": " 言[い]う",
    "Context": "目上の人に",
    "Notes": "お／ご＋ 名詞[めいし]のあとにも 使[つか]う：ご 案内[あんない] 申[もう]し 上[あ]げます",
    "ExampleTranslation": " 先生[せんせい]にお 礼[れい]を 言[い]いました。",
}

_GRAMMAR_JA = {
    "Translation": "雨の場合は、試合をしません。",
    "Target": "雨の場合",
    "Nuance": "条件と、当然の結果",
    "Explanation": "〜ばは、もしそうなったらという 条件[じょうけん]を 表[あらわ]す："
                   " 降[ふ]る →  降[ふ]れば。 話[はな]し 手[て]は、その 条件[じょうけん]から"
                   " 当然[とうぜん] 起[お]きる 結果[けっか]を 言[い]っている。≠ 〜たら："
                   "ここでも 使[つか]えるが、〜ばは 二[ふた]つのことのつながりを 強[つよ]く 言[い]う。",
}

_VOCAB_FR = {
    "Translation": "Dire",
    "Context": "à un supérieur",
    "Notes": "Aussi après お/ご + nom : ご 案内[あんない] 申[もう]し 上[あ]げます",
    "ExampleTranslation": "J'ai remercié mon professeur.",
}

_GRAMMAR_FR = {
    "Translation": "S'il pleut, le match est annulé.",
    "Target": "S'il pleut",
    "Nuance": "condition, résultat attendu",
    "Explanation": "〜ば exprime une condition hypothétique :  降[ふ]る →  "
                   "降[ふ]れば. Le locuteur énonce un résultat attendu et "
                   "naturel de cette condition. ≠ 〜たら : possible aussi, "
                   "mais 〜ば insiste sur le lien logique.",
    "URL": "https://www.cours-de-japonais.com/grammaire/conditionnel-ba/",
}

# 生 for its twelve common readings: on a simpler kanji the fold of the other
# readings would stay empty, and never show.
_KANJI = {
    "Kanji": "生",
    "Meaning": "life, birth, raw",
    "Onyomi": "セイ、ショウ",
    "Kunyomi": "い.きる、う.まれる",
    "Words": ("学生[がくせい]|student|セイ<br>"
              "一生[いっしょう]|a whole life|ショウ<br>"
              "生[い]きる|to live|い.きる<br>"
              "生[う]まれる|to be born|う.まれる"),
    "Strokes": "5",
    "OtherReadings": "い.かす、い.ける、う.む、お.う、は.える、は.やす、き、なま",
    "Composition": "pictograph: a shoot rising from the ground",
    "LookAlikes": "牛 cow - its upright runs through, with no base line",
    "Notes": " 芝生[しばふ]、 弥生[やよい]",
    "Decoy1": "牛",
    "Decoy2": "主",
    "Decoy3": "失",
    # The level badge is read from the tags.
    "Tags": "Level::N5",
}

_KANJI_FR = {
    "Meaning": "vie, naissance, cru",
    "Words": ("学生[がくせい]|étudiant|セイ<br>"
              "一生[いっしょう]|toute une vie|ショウ<br>"
              "生[い]きる|vivre|い.きる<br>"
              "生[う]まれる|naître|う.まれる"),
    "Composition": "pictogramme : une pousse qui sort de terre",
    "LookAlikes": "牛 vache - son trait vertical traverse, sans base",
}

_KANJI_JA = {
    "Meaning": "いきること、うまれること、なま",
    "Words": ("学生[がくせい]|学校でまなぶ人|セイ<br>"
              "一生[いっしょう]|うまれてから死ぬまで|ショウ<br>"
              "生[い]きる|いのちがある|い.きる<br>"
              "生[う]まれる|この世に出てくる|う.まれる"),
    "Composition": "象形：地面から出てくる芽",
    "LookAlikes": "牛 うし - たての線がつきぬけ、下の横線がない",
}

SAMPLES: tuple[Sample, ...] = (
    Sample("kanji", "kanji", "Kanji", "", dict(_KANJI), {"fr": _KANJI_FR, "ja": _KANJI_JA}),
    Sample(
        "vocab", "vocab", "Vocabulary", "",
        {
            # An Anki variable: the backs read two badges from it, the word's
            # class (which colours the card and gives its forms) and its register.
            # Most words have no register, hence a humble verb.
            "Tags": "Verb::一段動詞 Register::敬語::謙譲語 Level::N4",
            # The register is on the back only: on the `Production` front, the
            # Context is what tells it from 言う (see `vocab_fields.md`).
            "Expression": " 申[もう]し 上[あ]げる",
            "Translation": "To say",
            "Context": "to a superior",
            "Notes": "Also after お/ご + noun: ご 案内[あんない] 申[もう]し 上[あ]げます",
            "Example": " 先生[せんせい]にお 礼[れい]を 申[もう]し 上[あ]げました。",
            "ExampleTranslation": "I thanked my teacher.",
            # Empty, as the generation leaves it: a recording would replace the
            # system voice, on which `vocab.tts` is judged.
            "Audio": "",
        },
        {"fr": _VOCAB_FR, "ja": _VOCAB_JA}),
    Sample(
        "grammar", "grammar", "Grammar", "",
        {
            "Sentence": " 雨[あめ]が{{c1:: 降[ふ]れば}}、 試合[しあい]は 中止[ちゅうし]です。",
            "Translation": "If it rains, the match is cancelled.",
            # An EXACT excerpt of the translation, which the card finds to colour.
            "Target": "If it rains",
            "Hint": " 降[ふ]る",
            "Nuance": "condition, expected result",
            "Rule": "ば",
            # Two spaces before a group read in a line of prose, as the export
            # writes them (`furigana.protect_content_spaces`): Anki's filter
            # takes one as the start of the group, and the card shows the other.
            "Explanation": "〜ば expresses a hypothetical condition:  降[ふ]る →  "
                           "降[ふ]れば. The speaker states an expected, natural "
                           "result of that condition. ≠ 〜たら: possible too, "
                           "but 〜ば stresses the logical link.",
            # What the "typed answer" mode asks to type: the gap without its
            # readings, written by the generator, never seen by the model.
            "Answer": "降れば",
            # As given with `--url`, empty otherwise. The `www.` exercises the
            # back's script, which displays the domain only.
            "URL": "https://www.tofugu.com/japanese-grammar/ba-conditional/",
            # Without a register tag, that half of the front's script never runs.
            "Tags": "Grammar::N4::ば Register::丁寧体",
        },
        {"fr": _GRAMMAR_FR, "ja": _GRAMMAR_JA}),
    Sample("audio", "audio", "Listening", "a sound extract", dict(_LISTENING),
           {"fr": _LISTENING_FR, "ja": _LISTENING_JA}),
    # The FILLED field decides between sound and video, not an option.
    Sample("audio-video", "audio", "Listening", "a video extract",
           dict(_LISTENING, Audio="", Video=exporter.video_ref(CLIP)),
           {"fr": _LISTENING_FR, "ja": _LISTENING_JA}),
    Sample("reading", "reading", "Reading", "a text", dict(_READING), {"fr": _READING_FR, "ja": _READING_JA}),
    # The mini-book has ONLY its pages: the generator empties `Text`,
    # `Translation` and `KeyLine` (`reading._post_process`), and so does the
    # sample, or the back would lay the text out under the book. `KeyPage` makes
    # the back open the book on page 2.
    Sample("reading-book", "reading", "Reading", "a mini-book",
           dict(_READING,
                Images="".join(exporter.image_ref(p) for p in PAGES),
                Text="", Translation="", KeyLine="", KeyPage="2",
                Source="Sample collection, pages 12-14"),
           {"fr": dict(_READING_FR, Translation="",
                       Source="Recueil d'exemple, pages 12 à 14"),
            "ja": dict(_READING_JA, Translation="", Source="見本の問題集、12〜14ページ")}),
    # The only case carrying BOTH: the image on the front, the transcript and its
    # translation on the back.
    Sample("reading-document", "reading", "Reading", "a composed document",
           dict(_READING,
                Images=exporter.image_ref(POSTER),
                Source="Sample collection, page 15"),
           {"fr": dict(_READING_FR, Source="Recueil d'exemple, page 15"),
            "ja": dict(_READING_JA, Source="見本の問題集、15ページ")}),
)


def samples(keys: tuple[str, ...] = ()) -> tuple[Sample, ...]:
    """The ones asked for, or all of them, in the language of the cards.

    An unknown key, typed on a command line, raises `Unavailable`. The language
    is settled here, not in `SAMPLES`: at import time the settings are not read.
    """
    if not keys:
        return tuple(sample.told() for sample in SAMPLES)
    known = {s.key: s for s in SAMPLES}
    for key in keys:
        if key not in known:
            raise Unavailable(_("Unknown sample: {name}. The ones that exist: {known}")
                              .format(name=_quoted(key), known=listed(known)))
    return tuple(known[key].told() for key in keys)


def _spec(command: str) -> notetypes.NoteTypeSpec:
    return next(s for s in notetypes.SPECS if s.command == command)


# -- The little of Anki that has to be imitated --------------------------------

_SECTION_RE = re.compile(r"\{\{([#^])([^{}/]+?)\}\}(.*?)\{\{/\2\}\}", re.DOTALL)
_FIELD_RE = re.compile(r"\{\{([^{}]+)\}\}")
# Anki's pattern, to the letter: the ruby base stops at the `>` of a tag, and the
# anchoring space goes with the reading. A `\S+?` would turn the front's gap,
# `<span class="cloze">[...]</span>`, into ruby on `class="cloze">`.
_FURIGANA_RE = re.compile(r" ?([^ >]+?)\[([^\]]+)\]")
_CLOZE_RE = re.compile(r"\{\{c\d+::(.*?)\}\}", re.DOTALL)


def furigana_filter(text: str) -> str:
    """What `{{furigana:...}}` does: 駅[えき] -> <ruby>駅<rt>えき</rt></ruby>."""
    return _FURIGANA_RE.sub(r"<ruby>\1<rt>\2</rt></ruby>", text)


def kanji_filter(text: str) -> str:
    """`{{kanji:...}}`: the reading falls, the writing stays (涼[すず]しい -> 涼しい).

    Only the notation space goes, as in Anki: removing every space between two
    characters would close a rendered gap into `<spanclass=...>`
    (`{{kanji:cloze:Sentence}}`).
    """
    return _FURIGANA_RE.sub(r"\1", text)


def kana_filter(text: str) -> str:
    """`{{kana:...}}`: the other way round, only the readings are kept (-> すずしい)."""
    return _FURIGANA_RE.sub(r"\2", text)


def cloze_filter(text: str, *, front: bool) -> str:
    """The gap of a cloze notetype: hidden on the front, revealed on the back.

    The front keeps its class, which the template's script finds to lay the hint.
    """
    replacement = (r'<span class="cloze">[...]</span>' if front
                   else r'<span class="cloze">\1</span>')
    return _CLOZE_RE.sub(replacement, text)


# What Anki puts in place of a `{{tts}}`: its replay button, which takes room on
# the card and is what the "Speech synthesis" setting is judged on. Anki's markup
# down to the class (`replay-button soundLink`), which the stylesheets aim at.
# `data-say` is what the browser's voice reads on click (see data/preview.html).
_TTS_BUTTON = (
    '<a class="replay-button soundLink" href="#" data-say="{say}"'
    ' title="{title}">'
    '<svg class="playImage" viewBox="0 0 64 64" version="1.1">'
    '<circle cx="32" cy="32" r="29" fill="lightgrey"></circle>'
    '<path d="M56.502,32.301l-37.502,20.101l0.329,-40.804l37.173,20.703Z"'
    ' fill="black"></path></svg></a>')


# Anki's input box, identical: the stylesheets aim at its `typeans` id.
_TYPE_BOX = ('<input type="text" id="typeans" autocapitalize="off"'
             ' autocomplete="off" spellcheck="false" placeholder="{placeholder}">')


def render(template: str, fields: dict[str, str], *, front: bool) -> str:
    """An Anki template and some fields, as HTML.

    The `kotogen:` markers are comments, left as they are for the browser.
    """
    # Conditional sections, inside out: passes until nothing moves, not a parser.
    for _pass in range(6):
        def section(m):
            sign, name, body = m.group(1), m.group(2).strip(), m.group(3)
            filled = bool(str(fields.get(name, "")).strip())
            return body if (filled if sign == "#" else not filled) else ""

        again = _SECTION_RE.sub(section, template)
        if again == template:
            break
        template = again

    def one_field(m):
        parts = m.group(1).split(":")
        name = parts[-1].strip()
        # An unclosed section is left to show: the template's fault, not ours.
        if name.startswith(("#", "^", "/")):
            return m.group(0)
        filters = [p.strip() for p in parts[:-1] if p.strip()]
        # `{{tts ja_JP:kana:Field}}`: Anki's button, with the reading asked for,
        # in place of the field's text.
        if any(f.startswith("tts") for f in filters):
            raw = str(fields.get(name, ""))
            said = kana_filter(raw) if "kana" in filters else kanji_filter(raw)
            return _TTS_BUTTON.format(
                say=html.escape(said, quote=True),
                title=html.escape(_("Speech synthesis: Anki does it with the "
                                    "system voice"), quote=True))
        # `{{type:Field}}`: Anki's input box on the front, where the field would
        # show the ANSWER. Nothing is typed, so the back shows the expected
        # answer in Anki's markup for a right one.
        if "type" in filters:
            if front:
                return _TYPE_BOX.format(placeholder=html.escape(
                    _("Answer (the preview does not mark it)"), quote=True))
            expected = html.escape(str(fields.get(name, "")))
            return (f'<code id="typeans">'
                    f'<span class="typeGood">{expected}</span></code>')
        # As the export does: a newline is a <br> (Shift+Enter in Anki).
        value = str(fields.get(name, "")).replace("\n", "<br>")
        if "cloze" in filters:
            value = cloze_filter(value, front=front)
        if "kanji" in filters:
            value = kanji_filter(value)
        if "kana" in filters:
            value = kana_filter(value)
        if "furigana" in filters:
            value = furigana_filter(value)
        return value

    return _FIELD_RE.sub(one_field, template)


def fingerprint(text: str) -> int:
    """djb2 in 32-bit integers, the same hash as the scripts of the templates.

    The page hashes its own rendering to compare, in UTF-16 units since that is
    what `charCodeAt` counts.
    """
    h = 5381
    units = text.encode("utf-16-le")
    for i in range(0, len(units), 2):
        h = (((h << 5) - h) + (units[i] | (units[i + 1] << 8))) & 0xFFFFFFFF
    return h


# -- The example media ---------------------------------------------------------
#
# Made so that the listening card can be judged: a click on a transcript line
# jumps in the audio, and the jump has to be heard. Kept in the cache, so ffmpeg
# runs once.

_TYPES = {".mp3": "audio/mpeg", ".webm": "video/webm", ".svg": "image/svg+xml"}


def _run(cmd: list[str]) -> bool:
    def go():
        return subprocess.run(cmd, capture_output=True, check=False)

    try:
        # Ten seconds of VP9 take seconds to encode: the spinner turns meanwhile.
        done = console.while_working(go)
    except OSError:
        return False
    return done.returncode == 0


def _page_svg(number: int, total: int) -> str:
    """A page of the mini-book: panels, a speech bubble, columns of text.

    Drawn rather than written: real Japanese would show as squares on a system
    without a CJK font.
    """
    # The text columns on the right of the first panel, the bubble on its left:
    # overlapping, they read as a display fault.
    columns = "".join(
        f'<rect x="{574 - 34 * i}" y="{78 + 18 * (i % 3)}" width="13" '
        f'height="{120 + 30 * ((i * 7) % 4)}" rx="6" fill="#c9ccd4"/>'
        for i in range(0, 4))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 660 940" '
        f'width="660" height="940">'
        f'<rect width="660" height="940" fill="#fdfdfb"/>'
        f'<rect x="18" y="18" width="624" height="904" fill="none" '
        f'stroke="#22242a" stroke-width="3"/>'
        f'<rect x="46" y="46" width="568" height="330" fill="#eef0f4" '
        f'stroke="#22242a" stroke-width="3"/>'
        f'<rect x="46" y="400" width="270" height="300" fill="#e6e9ef" '
        f'stroke="#22242a" stroke-width="3"/>'
        f'<rect x="344" y="400" width="270" height="300" fill="#f2f3f7" '
        f'stroke="#22242a" stroke-width="3"/>'
        f'<rect x="46" y="724" width="568" height="170" fill="#eef0f4" '
        f'stroke="#22242a" stroke-width="3"/>'
        f'<ellipse cx="230" cy="170" rx="115" ry="76" fill="#ffffff" '
        f'stroke="#22242a" stroke-width="3"/>'
        f'{columns}'
        f'<text x="330" y="915" text-anchor="middle" font-size="26" '
        f'font-family="sans-serif" fill="#6b7280">{number} / {total}</text>'
        f'</svg>\n')


def _poster_svg() -> str:
    """The composed document of a reading card: a framed notice, a table.

    Drawn, like `_page_svg`, and wider than tall, as the posters and timetables
    of a 読解 booklet are.
    """
    rows = "".join(
        f'<rect x="{56 + 150 * c}" y="{188 + 62 * r}" width="{120 if c else 250}" '
        f'height="22" rx="6" fill="#c9ccd4"/>'
        for r in range(4) for c in range(4))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 560" '
        'width="820" height="560">'
        '<rect width="820" height="560" fill="#fdfdfb"/>'
        '<rect x="16" y="16" width="788" height="528" fill="none" '
        'stroke="#22242a" stroke-width="3"/>'
        '<rect x="56" y="56" width="330" height="34" rx="8" fill="#22242a"/>'
        '<rect x="56" y="112" width="560" height="18" rx="8" fill="#c9ccd4"/>'
        '<rect x="640" y="52" width="128" height="86" fill="#eef0f4" '
        'stroke="#22242a" stroke-width="3"/>'
        '<rect x="40" y="164" width="740" height="300" fill="none" '
        'stroke="#22242a" stroke-width="3"/>'
        + "".join(f'<line x1="40" y1="{164 + 60 * r}" x2="780" y2="{164 + 60 * r}" '
                  f'stroke="#22242a" stroke-width="2"/>' for r in range(1, 5))
        + "".join(f'<line x1="{40 + 150 * c}" y1="164" x2="{40 + 150 * c}" y2="464" '
                  f'stroke="#22242a" stroke-width="2"/>' for c in range(2, 5))
        + f'{rows}'
        '<rect x="56" y="496" width="420" height="18" rx="8" fill="#c9ccd4"/>'
        '</svg>\n')


def media(folder: Path) -> list[str]:
    """Makes what is missing in the media folder, says what was missing.

    The notes go on the page, so a mute card does not pass for a broken template.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for rank, name in enumerate(PAGES, 1):
        (folder / name).write_text(_page_svg(rank, len(PAGES)), encoding="utf-8")
    (folder / POSTER).write_text(_poster_svg(), encoding="utf-8")

    notes: list[str] = []
    if (folder / SOUND).exists() and (folder / CLIP).exists():
        return notes
    if shutil.which("ffmpeg") is None:
        return [_("FFmpeg is absent from the PATH: the listening card shows with "
                  "neither sound nor image. Its layout, though, stays true.")]

    # One note per second, rising: a click on a transcript line is heard to land
    # where its timestamp says.
    if not (folder / SOUND).exists() and not _run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i",
             "aevalsrc=0.12*sin(2*PI*t*(220+55*floor(t))):d=10:s=22050",
             "-c:a", "libmp3lame", "-q:a", "6", str(folder / SOUND)]):
        notes.append(_("FFmpeg could not make the example sound: the player of "
                       "the listening card stays empty."))
    # VP9 in a WebM, like the generator's clips. The picture is dull on purpose,
    # not to draw the eye from the colours of the card.
    if not (folder / CLIP).exists() and not _run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i",
             "color=c=0x16202e:s=480x270:d=8:r=12,"
             r"drawbox=x='mod(t*70\,440)':y='110+40*sin(t*2)':w=44:h=44:"
             "color=0x9fb4d8@0.85:t=fill",
             "-c:v", "libvpx-vp9", "-b:v", "200k",
             "-deadline", "realtime", "-cpu-used", "8", str(folder / CLIP)]):
        notes.append(_("FFmpeg could not make the example video: the video card "
                       "shows with an empty player."))
    return notes


# -- The payload ---------------------------------------------------------------

def _labels() -> dict[str, str]:
    """Readable name of each group of switches.

    Copied from `interactive.status.CARD_COMMANDS`: importing it would be circular.
    """
    return {"kanji": "Kanji", "vocab": "Vocabulary", "grammar": "Grammar",
            "audio": "Listening", "reading": "Reading",
            card_templates.GLOBAL: _("All the cards")}


def _words() -> dict[str, str | list[str]]:
    """The page's own sentences, translated here rather than over there.

    The page is a static file with no catalogue: its words travel in the payload,
    each under a short name, and its English stays as the fallback (the text of a
    `data-word` node, or of `word()`). A sentence that agrees with a count is a
    list indexed by the count (see `to_apply`). Left out: the errors of `trim()`,
    seen only by someone editing a template.
    """
    return {
        # The top bar.
        "page_title": _("Card preview - kotogen"),
        "title": _("Card appearance"),
        "cards": _("Cards"),
        "source": _("Source"),
        # Real collisions: "Desktop" is also a folder (`Bureau`, where a screen
        # is `Ordinateur`), "Back" also leaves a menu (`Retour`, where a card
        # has a `Verso`). "Mobile" and "Front" take their pair's context.
        "desktop": _("Desktop", "screen"),
        "mobile": _("Mobile", "screen"),
        "reset": _("Put everything back to default"),
        "revert": _("Back to my settings"),
        "apply": _("Apply"),
        # The panel of switches.
        "apply_word": _("Apply writes your settings, those of the other cards "
                        "included. It is deck install that carries them into "
                        "Anki afterwards."),
        # One sentence per count the page can reach, agreed here by
        # `i18n.counted`: the page has no plural rule to read.
        "to_apply": [counted(n, "{count} setting to apply", "{count} settings to apply")
                     for n in range(len(card_templates.SETTINGS) + 1)],
        "as_written": _("Your settings, as they are written"),
        "applied": _("Settings applied"),
        "refused": _("the server refused ({status})"),
        "not_written": _("Settings not written: {reason}. The preview may have "
                         "been closed in the terminal."),
        # The source view, for the day AnkiConnect does not answer. Filled by
        # `replace`: `format` would read the braces of Anki's syntax.
        "source_word": _("What {path} would lay down in Anki, your settings "
                         "included - to be pasted by hand when AnkiConnect "
                         "does not answer. The {{Field}} and {{FrontSide}} are "
                         "Anki's syntax: they stay as they are.")
                       .replace("{path}", _quoted(_("Templates") + " > " + _("Install"))),
        "copy": _("Copy"),
        "copied": _("Copied"),
        "copy_refused": _("Copy refused"),
        "fields": _("Fields"),
        "front": _("Front", "card"),
        "back": _("Back", "card"),
        "styling": _("Styling"),
        "fields_where": _("Manage Note Types > Fields... - in this order"),
        "fields_cloze": _(", Cloze type"),
        # The page puts the name in later: what is quoted here is the PLACEHOLDER.
        "front_where": _("Cards... > {name} > Front Template")
                       .format(name=_quoted("{card}")),
        "back_where": _("Cards... > {name} > Back Template")
                      .format(name=_quoted("{card}")),
        "styling_where": _("Cards... > Styling - a single sheet for {name}")
                         .format(name=_quoted("{notetype}")),
        # The guard rail, when the page no longer trims like Python.
        "drifted": _("This preview does not render what kotogen would install: "
                     "{guilty}."),
        "drifted_why": _("The rendering rule of the page has diverged from that "
                         "of kotogen/anki/templates.py."),
    }


def _markers() -> dict[str, dict[str, str]]:
    """Command -> marker -> setting key, with the same precedence as in Python.

    Its own command over the global one, the rule of `card_templates._by_marker`.
    """
    table: dict[str, dict[str, str]] = {}
    for spec in notetypes.SPECS:
        own = {r.marker: r.key for r in card_templates.SETTINGS
               if r.command == card_templates.GLOBAL}
        own |= {r.marker: r.key for r in card_templates.SETTINGS
                if r.command == spec.command}
        table[spec.command] = own
    return table


def _ident(name: str) -> str:
    """A card name (`Recognition`, `Listening`) cut down to what fits an identifier.

    Accents fall rather than become dashes: `Résumé` gives `resume`, not `r-sum`.
    """
    flat = unicodedata.normalize("NFKD", name.lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", flat).strip("-") or "card"


def _face(template: dict[str, str], side: str, fields: dict[str, str]) -> str:
    """The front, or the back with its FrontSide already laid inside it."""
    front = render(template["Front"], fields, front=True)
    if side == "Front":
        return front
    return render(template["Back"].replace("{{FrontSide}}", front), fields,
                  front=False)


def payload(chosen: tuple[Sample, ...]) -> dict:
    """Everything the page needs to know, in one structure.

    Each template goes in raw (markers kept) for the browser to trim, with the
    fingerprint of the Python rendering to check it, and unfilled in `sources`,
    for pasting into Anki. `types` holds what a paste lacks: the type's name, its
    fields in order, whether it is a cloze.
    """
    root = notetypes.templates_root()
    if root is None:
        raise Unavailable(_("`templates/` folder not found: the preview reads the "
                            "same templates as `deck install`."))
    cards: list[dict] = []
    styles: dict[str, dict] = {}
    types: dict[str, dict] = {}
    sources: dict[str, dict[str, dict[str, str]]] = {}
    for sample in chosen:
        spec = _spec(sample.command)
        try:
            raw, raw_css = notetypes.read_templates(spec, root, raw=True)
            rendered, rendered_css = notetypes.read_templates(spec, root)
        except FileNotFoundError as exc:
            raise Unavailable(_("Template missing: {error}").format(error=exc)) from exc
        styles[sample.command] = {"text": raw_css,
                                  "fingerprint": fingerprint(rendered_css.strip())}
        # One source per note type, however many samples it has.
        if sample.command not in types:
            types[sample.command] = {"notetype": spec.notetype,
                                     "cloze": spec.is_cloze,
                                     "fields": spec.fields}
            sources[sample.command] = {
                name: {"front": faces["Front"], "back": faces["Back"]}
                for name, faces in raw.items()
            }
        for name in raw:
            for face, side in (("front", "Front"), ("back", "Back")):
                cards.append({
                    "key": f"{sample.key}-{_ident(name)}-{face}",
                    "sample": sample.key,
                    "command": sample.command,
                    "card": name,
                    "face": face,
                    "html": _face(raw[name], side, sample.fields),
                    "fingerprint": fingerprint(
                        _face(rendered[name], side, sample.fields).strip()),
                })
    return {
        "global": card_templates.GLOBAL,
        "groups": [{"key": c, "label": label} for c, label in _labels().items()],
        # `panel` is false for `all.lang` alone, which removes no block. It stays
        # in `values`, which Apply sends back: `set_all` puts back to default
        # whatever it is not given.
        "settings": [{"key": r.key, "command": r.command, "marker": r.marker,
                      "label": _(r.label), "positions": list(r.positions),
                      "shown": [r.show(p) for p in r.positions], "default": r.default,
                      "panel": r is not card_templates.LANGUAGE}
                     for r in card_templates.SETTINGS],
        "values": {r.key: card_templates.value(r.key) for r in card_templates.SETTINGS},
        "markers": _markers(),
        "words": _words(),
        # `detail` labels the sub-tab telling apart two samples of one note type.
        "samples": [{"key": s.key, "title": s.title, "command": s.command,
                     "detail": _(s.detail)} for s in chosen],
        "cards": cards,
        "styles": styles,
        "types": types,
        "sources": sources,
    }


# -- The page ------------------------------------------------------------------

SHELL = Path(__file__).resolve().parent.parent / "data" / "preview.html"


def page(chosen: tuple[Sample, ...], *, token: str = "", anchor: str = "",
         notes: tuple[str, ...] | list[str] = ()) -> str:
    """The shell, with the data of the preview inside it.

    Read again at every call, so that a refresh shows `templates/` as on disk.
    `notes` are those of `media`, made once at start-up.
    """
    data = payload(chosen)
    data["token"] = token
    data["anchor"] = anchor
    data["notes"] = list(notes)
    # json.dumps leaves `<` as it is, and a `</script>` in a template would close
    # the tag carrying the data.
    data_json = (json.dumps(data, ensure_ascii=False)
                 .replace("<", "\\u003c")
                 .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return SHELL.read_text(encoding="utf-8").replace("/*DATA*/", data_json)


# -- The local server ----------------------------------------------------------
#
# 127.0.0.1 and a port the system picks: nothing is exposed to the network, and
# two previews do not collide.
#
# The token guards against the browser: any page visited meanwhile can write to
# 127.0.0.1 blind. A custom header forces a preflight request, which is not
# served; a page that could READ the token is stopped by the Host (see `_ours`).

# What a write may weigh: the settings of every card, a few kilobytes, many
# times over. A body is read before its token is checked (see `_body`), so this
# bounds what any page can make the preview hold.
_BODY_LIMIT = 1 << 20


@dataclass
class Preview:
    """An open preview: its address, what it has to say, and what closes it."""

    url: str
    notes: list[str]
    _server: ThreadingHTTPServer

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def serve(chosen: tuple[Sample, ...] = (), *, anchor: str = "",
          open_browser: bool = True) -> Preview:
    """Serves the preview, opens the browser, and hands control back at once.

    The calling screen waits for a key to close it while the page is in use.
    """
    chosen = chosen or samples()
    folder = system.cache_dir() / "preview"
    notes = media(folder)
    token = token_urlsafe(16)
    # Built once first, so that a broken template says so in the terminal.
    page(chosen, token=token, anchor=anchor, notes=notes)

    class _Handler(BaseHTTPRequestHandler):
        # Silent: kotogen's output in the terminal is read line by line.
        def log_message(self, *_args):
            pass

        def _respond(self, code: int, body: bytes, type_: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", type_)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _ours(self) -> bool:
            """True if the request names this server as the browser opened it.

            A page can point a name of its own at 127.0.0.1 and read this one,
            token included, as its own origin; but its browser sends that name
            as the Host.
            """
            port = self.server.server_address[1]
            return self.headers.get("Host") in (f"127.0.0.1:{port}",
                                                f"localhost:{port}")

        def do_GET(self):
            if not self._ours():
                self._respond(403, b"", "text/plain")
                return
            path = self.path.split("?", 1)[0].lstrip("/")
            if not path or path == "index.html":
                try:
                    body = page(chosen, token=token, anchor=anchor, notes=notes)
                except (Unavailable, RuntimeError) as exc:
                    self._respond(500, str(exc).encode("utf-8"),
                                  "text/plain; charset=utf-8")
                    return
                self._respond(200, body.encode("utf-8"),
                              "text/html; charset=utf-8")
                return
            # The media only: this server gives access to no file it did not make.
            if path in MEDIA and (folder / path).exists():
                self._media((folder / path).read_bytes(),
                            _TYPES[Path(path).suffix])
                return
            self._respond(404, b"", "text/plain")

        def _media(self, body: bytes, type_: str) -> None:
            """A medium, in pieces if they are asked for.

            Without ranges a player cannot seek, and Chrome sends playback back
            to the start on a click on a transcript line.
            """
            asked = (self.headers.get("Range") or "").strip()
            start, end = 0, len(body) - 1
            partial = asked.startswith("bytes=") and "," not in asked
            if partial:
                bounds = asked[6:].split("-", 1)
                try:
                    start = int(bounds[0]) if bounds[0] else start
                    end = int(bounds[1]) if len(bounds) > 1 and bounds[1] else end
                except ValueError:
                    partial = False
            if not partial or start > end or end >= len(body):
                self.send_response(200)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Type", type_)
                self.send_header("Content-Length", str(len(body)))
                # Like the page, so that a refresh shows media just remade.
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            piece = body[start:end + 1]
            self.send_response(206)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", type_)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
            self.send_header("Content-Length", str(len(piece)))
            self.end_headers()
            self.wfile.write(piece)

        def _body(self) -> bytes:
            """The body of the request, read before any answer is given.

            A refusal included: on Windows a socket closed on unread bytes is
            reset, and the client loses the answer (`ConnectionAbortedError`).
            Read up to `_BODY_LIMIT`, the sender being unchecked yet.
            """
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return b""
            return self.rfile.read(max(0, min(size, _BODY_LIMIT)))

        def do_POST(self):
            body = self._body()
            if (not self._ours() or self.path != "/settings"
                    or self.headers.get("X-Kotogen") != token):
                self._respond(403, b"", "text/plain")
                return
            try:
                choices = json.loads(body or b"{}")
                written = card_templates.set_all(choices)
            except (ValueError, OSError) as exc:
                self._respond(400, json.dumps({"error": str(exc)}).encode("utf-8"),
                              "application/json")
                return
            self._respond(200, json.dumps({"file": str(written)}).encode("utf-8"),
                          "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    if open_browser:
        webbrowser.open(url)
    return Preview(url, notes, server)
