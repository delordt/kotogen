"""The card preview (`kotogen/anki/preview.py`).

The page receives the RAW templates, markers included, and its JavaScript trims
them: the tests hold its pattern to Python's, and its fingerprint to the
customised rendering. The server, which writes the settings, serves only its own
media and accepts only what its own page sends.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

import pytest

from kotogen import choices
from kotogen.anki import notetypes, preview, templates as card_templates
from kotogen.cli import deck_config


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    """A file of choices of our own: the machine's would sway the tests, and be
    written by them."""
    target = tmp_path / choices.FILE
    monkeypatch.setattr(choices, "file", lambda: target)
    return target


@pytest.fixture(autouse=True)
def without_ffmpeg(tmp_path, monkeypatch):
    """The example media go to a throwaway cache, and ffmpeg is never run.

    The page builds without the sound and the video, whose absence is one of the
    cases covered; the mini-book pages are drawn in Python.
    """
    monkeypatch.setattr("kotogen.system.cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr("shutil.which", lambda _name: None)


@pytest.fixture
def root():
    """The real `templates/`: this preview shows the shipped templates."""
    found = notetypes.templates_root()
    if found is None:
        pytest.skip("templates/ folder not found")
    return found


# -- The samples ---------------------------------------------------------------

def test_every_field_of_the_generator_has_a_sample_value():
    """With no test value, a field shows empty, like a template ignoring it."""
    for sample in preview.SAMPLES:
        spec = next(s for s in notetypes.SPECS if s.command == sample.command)
        missing = [f for f in spec.fields if f not in sample.fields]
        assert not missing, f"{sample.key}: {', '.join(missing)}"


def test_every_badge_read_from_the_tags_has_a_sample_to_show_it(root):
    """A badge the templates draw from `{{Tags}}` is a field like any other.

    It is not in FIELDS, so the test above misses it: with no such tag, the
    preview shows an empty corner whatever `vocab.register` says.
    """
    tag_re = re.compile(r'"((?:Register|Speaker|Dialect)::[^"]+)"\s*:')
    for sample in preview.SAMPLES:
        spec = next(s for s in notetypes.SPECS if s.command == sample.command)
        read = {tag for page in (root / spec.directory).rglob("*.html")
                for tag in tag_re.findall(page.read_text(encoding="utf-8"))}
        if read:
            carried = set(sample.fields.get("Tags", "").split())
            assert read & carried, f"{sample.key}: no tag among {sorted(read)}"


def test_the_two_listening_samples_never_carry_both_media():
    """The card plays one medium only, and the FILLED field says which."""
    for sample in preview.SAMPLES:
        if sample.command != "audio":
            continue
        assert bool(sample.fields["Audio"]) != bool(sample.fields["Video"])


def test_two_samples_of_one_notetype_are_told_apart():
    """Samples of one note type are sub-tabs labelled by their detail alone: two
    empty or equal details would make two identical buttons."""
    by_command: dict[str, list] = {}
    for sample in preview.SAMPLES:
        by_command.setdefault(sample.command, []).append(sample)
    for command, group in by_command.items():
        if len(group) < 2:
            continue
        details = [s.detail for s in group]
        assert all(details), f"{command}: a sample with no detail"
        assert len(set(details)) == len(details), f"{command}: twice the same"


def test_an_unknown_sample_is_named_rather_than_ignored():
    with pytest.raises(preview.Unavailable, match="reading-book"):
        preview.samples(("reading-cassette",))


# -- The language a sample is told in ------------------------------------------
# A preview shows the cards about to be made: samples follow their language.

@pytest.mark.parametrize("key, field", [
    ("vocab", "Translation"), ("grammar", "Translation"),
    ("audio", "Question"), ("reading", "Answer"),
])
def test_a_sample_is_told_in_the_language_of_the_cards(key, field):
    from kotogen import prompts

    prompts.use("en")
    english = preview.samples((key,))[0].fields[field]
    prompts.use("fr")
    french = preview.samples((key,))[0].fields[field]
    assert english and french and english != french


def test_what_carries_no_language_does_not_move_with_it():
    """The Japanese, the tags and the media are one card, said twice."""
    from kotogen import prompts

    for key, unchanging in (("audio", ("Transcript", "Audio", "Timecodes")),
                            ("grammar", ("Sentence", "Hint", "Answer", "Tags")),
                            ("vocab", ("Expression", "Example", "Tags"))):
        prompts.use("en")
        english = preview.samples((key,))[0].fields
        prompts.use("fr")
        french = preview.samples((key,))[0].fields
        for name in unchanging:
            assert english[name] == french[name], f"{key}.{name} moved"


def test_a_sample_says_nothing_the_note_type_has_no_field_for():
    """The other language is an overlay, not a second set of fields."""
    for sample in preview.SAMPLES:
        for lang, overlay in sample.overlays.items():
            assert set(overlay) <= set(sample.fields), f"{sample.key} ({lang})"


def test_a_sample_spaces_its_readings_as_the_export_does():
    """In a line of prose, the space before a group with a reading is doubled
    by the export: Anki's filter takes one to start the group, and a single
    one would show `condition:降る →降れば` on the card."""
    from kotogen.furigana import protect_content_spaces

    for sample in preview.SAMPLES:
        for lang, fields in (("en", sample.fields), *sample.overlays.items()):
            for name, value in fields.items():
                for line in value.split("\n"):
                    assert protect_content_spaces(line) == line, f"{sample.key}.{name} ({lang})"
    grammar = next(s for s in preview.SAMPLES if s.key == "grammar")
    shown = preview.furigana_filter(grammar.fields["Explanation"])
    assert "condition: <ruby>降<rt>ふ</rt></ruby>る → <ruby>" in shown


def test_every_sample_is_told_in_every_language_of_the_cards():
    """A language with no overlay would silently preview its collection in
    English; an overlay for a language not shipped is the same slip reversed."""
    from kotogen import prompts

    told = set(prompts.languages()) - {prompts.SOURCE}
    for sample in preview.SAMPLES:
        assert set(sample.overlays) == told, sample.key


# -- What the page carries -----------------------------------------------------

def test_the_page_carries_the_templates_with_their_markers(root):
    """Without markers, there would be nothing left to remove in the browser."""
    data = preview.payload(preview.SAMPLES)
    for card in data["cards"]:
        assert "{{" not in card["html"], "a field was not substituted"
    assert any("kotogen:tts" in c["html"] for c in data["cards"])
    assert any("kotogen:" in s["text"] for s in data["styles"].values())


def test_the_source_keeps_the_fields_the_cards_substitute(root):
    """The source is what one pastes into Anki: `{{Expression}}` stays in it.

    That is its only difference with `cards`, which are filled in.
    """
    data = preview.payload(preview.samples(("vocab", "reading")))
    vocab = data["sources"]["vocab"]["Recognition"]
    assert "{{kanji::Expression}}" in vocab["front"]
    # The markers too, as in `cards`: the browser trims both by one rule.
    assert "kotogen:" in vocab["back"]
    # `{{FrontSide}}`: unfolded in the iframe, kept in the source for Anki.
    assert "{{FrontSide}}" in data["sources"]["reading"]["Reading"]["back"]


def test_the_source_says_what_a_paste_cannot_carry(root):
    """The name of the type, its fields in order, and whether it is a cloze."""
    data = preview.payload(preview.SAMPLES)
    assert data["types"]["grammar"]["cloze"] is True
    assert data["types"]["vocab"]["cloze"] is False
    assert data["types"]["vocab"]["fields"][0] == "Expression"
    assert data["types"]["audio"]["notetype"] == deck_config("audio")[1]


def test_the_fingerprint_is_that_of_the_customised_rendering(root):
    """It is the rendering of THIS profile the page checks, not the repository file.

    Otherwise the first setting changed would fail a true rendering's check.
    """
    before = {c["key"]: c["fingerprint"]
              for c in preview.payload(preview.SAMPLES)["cards"]}
    card_templates.set_one("vocab.tts", "yes")
    after = {c["key"]: c["fingerprint"]
             for c in preview.payload(preview.SAMPLES)["cards"]}
    changed = [key for key in before if before[key] != after[key]]
    assert changed and all(key.startswith("vocab") for key in changed)


def test_the_back_carries_the_front_like_anki_does(root):
    """`{{FrontSide}}`: the back shows the front, then what it adds."""
    data = preview.payload(preview.samples(("reading",)))
    faces = {c["face"]: c["html"] for c in data["cards"]}
    assert "{{FrontSide}}" not in faces["back"]
    assert faces["front"] in faces["back"]


def test_the_fields_are_substituted_like_anki_does():
    """The filters that decide what is read: furigana, kanji, cloze."""
    fields = {"Word": " 涼[すず]しい"}
    # The leading space goes with the reading, under all three filters: it is a
    # notation separator, and Anki eats it (` ?` at the head of its pattern).
    assert preview.render("{{furigana:Word}}", fields, front=True) == (
        "<ruby>涼<rt>すず</rt></ruby>しい")
    assert preview.render("{{kanji:Word}}", fields, front=True) == "涼しい"
    assert preview.render("{{kana:Word}}", fields, front=True) == "すずしい"

    gap = {"Sentence": "雨が{{c1::降れば}}中止"}
    assert "[...]" in preview.render("{{cloze:Sentence}}", gap, front=True)
    assert "降れば" in preview.render("{{cloze:Sentence}}", gap, front=False)


def test_the_hole_survives_the_furigana_filter():
    """`{{furigana:cloze:...}}`: the gap of the front is HTML, not a ruby base.

    The ruby base stops at a tag's `>`, as in Anki: otherwise the `[...]` of the
    gap reads as a reading, and `class="cloze">` shows in the sentence.
    """
    gap = {"Sentence": " 雨[あめ]が{{c1:: 降[ふ]れば}}"}
    out = preview.render("{{furigana:cloze:Sentence}}", gap, front=True)
    assert out == '<ruby>雨<rt>あめ</rt></ruby>が<span class="cloze">[...]</span>'


def test_the_speech_synthesis_becomes_ankis_replay_button():
    """`{{tts}}`: Anki's replay circle, with the reading the tag asked for.

    The field's text would look like a broken template, and nothing at all would
    hide the one visible effect of the "Speech synthesis" setting.
    """
    out = preview.render("<b>{{tts ja_JP:kana:Word}}</b>", {"Word": " 涼[すず]しい"},
                         front=False)
    assert 'class="replay-button soundLink"' in out
    assert 'data-say="すずしい"' in out     # the kana, as the tag asks for them
    assert "涼" not in out                  # and above all not the field in clear


def test_the_spoken_text_is_escaped_before_it_becomes_an_attribute():
    """A field has no business being able to close the attribute carrying it."""
    out = preview.render('{{tts ja_JP:kana:Word}}', {"Word": 'a"onclick="x'}, front=True)
    assert 'data-say="a&quot;onclick=&quot;x"' in out


def test_the_page_says_when_a_sample_medium_is_missing():
    """A mute listening card says why: otherwise it reads as a broken template."""
    from kotogen import system

    notes = preview.media(system.cache_dir() / "preview")
    assert notes and "FFmpeg" in notes[0]
    # The pages of the mini-book depend on nothing: they are drawn.
    assert all((system.cache_dir() / "preview" / name).exists()
               for name in preview.PAGES)


def test_every_medium_a_sample_cites_is_one_the_server_will_serve():
    """A medium cited but not served is a silent 404: a hole that looks like a
    template fault."""
    cited = set()
    for sample in preview.SAMPLES:
        for value in sample.fields.values():
            cited |= set(re.findall(r'src="([^"]+)"', str(value)))
            cited |= set(re.findall(r"\[sound:([^\]]+)\]", str(value)))

    assert cited, "no sample cites a medium: the pattern has drifted"
    assert cited <= set(preview.MEDIA), f"not served: {cited - set(preview.MEDIA)}"


# -- The switch that is not there ----------------------------------------------
# `all.lang` removes no block, so the panel draws no switch for it. It still
# travels in the payload: `set_all` resets whatever it is not given, so a value
# dropped by the page would turn a French collection English at the first "Apply".

def test_the_language_of_the_cards_gets_no_switch(root):
    """Drawn: every setting save that one, and no other is missing."""
    data = preview.payload(preview.SAMPLES)
    drawn = {r["key"] for r in data["settings"] if r["panel"]}
    assert card_templates.LANGUAGE.key not in drawn
    assert drawn == ({s.key for s in card_templates.SETTINGS}
                     - {card_templates.LANGUAGE.key})
    # And its value is in the payload, which is what the page sends back.
    assert data["values"][card_templates.LANGUAGE.key]


def test_the_page_puts_back_only_what_it_draws():
    """"Put everything back to default" bears on the switches, not on the file.

    The button walks the whole table: without one `if` in the page, a reset would
    silently turn a French collection's cards English.
    """
    page = preview.SHELL.read_text(encoding="utf-8")
    assert re.search(r'if \(r\.panel\)\s*state\[r\.key\] = r\["default"\]', page)


# -- The words of the page -----------------------------------------------------
# The page's sentences travel in the payload under short names (`preview._words`):
# a name misspelt on either side silently falls back on the page's English.

def _asked_words() -> set[str]:
    """Every name the page asks the payload for, markup and script alike.

    The name is the FIRST argument of `word()` and `counted()`, possibly a
    condition picking between two: every short quoted word before the first comma
    is taken. The definitions, whose first argument is `name`, are left out.
    """
    page = preview.SHELL.read_text(encoding="utf-8")
    asked = set(re.findall(r'data-word="(\w+)"', page))
    for call in re.finditer(r"\b(?:word|counted)\((?!name)", page):
        first = page[call.end():].split(",")[0]
        asked |= set(re.findall(r'"([a-z][a-z_]*)"', first))
    return asked


def test_every_word_the_page_asks_for_is_one_the_payload_carries():
    unknown = sorted(_asked_words() - set(preview._words()))
    assert unknown == []


def test_every_word_the_payload_carries_is_one_the_page_asks_for():
    """The other way round: a word not asked for is a sentence gone from the
    page."""
    unused = sorted(set(preview._words()) - _asked_words())
    assert unused == []


def test_the_page_keeps_its_english_beside_every_name():
    """`word()` takes the English as its second argument, and `data-word` sits on
    a node that holds it: a missing entry shows a sentence, never a name."""
    page = preview.SHELL.read_text(encoding="utf-8")
    nameless = re.findall(r'\bword\("[\w]+"\s*\)', page)
    assert nameless == []


def test_the_source_view_quotes_its_menu_as_the_language_does(monkeypatch):
    """The path of the menu is quoted by the language (`i18n.quoted`), and the
    braces of Anki's syntax around it stay as they are."""
    from kotogen import i18n

    quotes = {"quote_open": "« ", "quote_close": " »"}
    monkeypatch.setattr(i18n, "convention", lambda name, default: quotes.get(name, default))
    said = preview._words()["source_word"]
    assert said.startswith("What « Templates > Install » would lay down in Anki")
    assert "The {{Field}} and {{FrontSide}} are" in said


def test_the_count_reaches_the_page_agreed_for_every_number_it_can_show():
    """The page cannot tell which form a count takes, so it gets a sentence per
    count it can reach, from none switched to all of them."""
    sentences = preview._words()["to_apply"]
    assert len(sentences) == len(card_templates.SETTINGS) + 1
    assert all("{count}" in sentence for sentence in sentences)
    assert sentences[1] != sentences[2]


# -- The rule, on both sides ---------------------------------------------------

def _page_pattern(name: str) -> str:
    """The opening or closing pattern as the page writes it.

    The page writes it as concatenated strings: glued back together, with the
    JavaScript escapes turned into Python's.
    """
    page = preview.SHELL.read_text(encoding="utf-8")
    body = re.search(rf"var {name} = (.+?);\n", page, re.DOTALL)
    assert body, f"pattern {name} not found in the shell"
    pieces = re.findall(r'"((?:[^"\\]|\\.)*)"', body.group(1))
    return "".join(pieces).replace("\\\\", "\\").replace("\\/", "/")


def test_the_browser_rule_is_the_python_rule():
    """The pattern of the markers lives here and in the page: it must be the same.

    Named groups are ignored: the page writes them unnamed, to the same effect.
    """
    python = re.sub(r"\(\?P<\w+>", "(", card_templates._OPENING.pattern)
    assert _page_pattern("OPENING") == python


def test_the_browser_removes_the_same_blocks_as_python(root):
    """The rule copied out, run on the real templates, by the pattern of the page.

    The JavaScript does not run here, but its pattern does, on the same files.
    """
    opening = re.compile(_page_pattern("OPENING"))
    for spec in notetypes.SPECS:
        for _name, sub in spec.all_cards:
            folder = root / spec.directory / (sub or "")
            for filename in ("front.html", "back.html", "style.css"):
                text = (folder / filename).read_text(encoding="utf-8")
                expected = {m.group("name") for m in
                            card_templates._OPENING.finditer(text)}
                assert {m.group(1) for m in opening.finditer(text)} == expected


def test_the_fingerprint_matches_the_hash_the_page_computes():
    """djb2 on UTF-16 units: the same number on both sides, beyond ASCII too."""
    # Reference value computed by hand, as `charCodeAt` would give it.
    def djb2(text):
        h = 5381
        for unit in text.encode("utf-16-le").hex(" ", 2).split():
            h = ((h << 5) - h + int(unit[2:4] + unit[0:2], 16)) & 0xFFFFFFFF
        return h

    for text in ("", "kotogen", "駅[えき]", "« Listening »", "<div>涼しい</div>"):
        assert preview.fingerprint(text) == djb2(text)


# -- The server ----------------------------------------------------------------

@pytest.fixture
def served(root):
    """A preview served, without a browser, closed again at the end of the test."""
    open_ = preview.serve(open_browser=False)
    yield open_
    open_.stop()


def _read(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as answer:
        return answer.read().decode("utf-8")


def _data(page: str) -> dict:
    return json.loads(re.search(r"var DATA = (.+?);</script>", page).group(1))


def _token(page: str) -> str:
    return _data(page)["token"]


def test_the_served_page_carries_the_cards_and_the_settings(served):
    page = _read(served.url)
    assert "Card appearance" in page
    data = _data(page)
    # Eight samples, front and back - the vocabulary gives two cards.
    assert len(data["cards"]) == 18
    assert len(data["settings"]) == len(card_templates.SETTINGS)
    assert data["values"]["vocab.tts"] == "no"


def test_the_page_is_rebuilt_at_each_request(served, profile):
    """Refreshing shows what has just been changed - template as well as setting."""
    card_templates.set_one("all.palette", "light")
    assert _data(_read(served.url))["values"]["all.palette"] == "light"


def test_applying_writes_the_settings_of_the_profile(served, profile):
    request = urllib.request.Request(
        served.url + "settings", method="POST",
        data=json.dumps({"vocab.tts": "yes", "reading.markers": "digits"}).encode(),
        headers={"X-Kotogen": _token(_read(served.url))})
    with urllib.request.urlopen(request, timeout=5) as answer:
        assert answer.status == 200
    assert card_templates.value("vocab.tts") == "yes"
    assert card_templates.value("reading.markers") == "digits"
    # Only the drifts are written: what was not in the send follows the repository.
    assert "audio" not in profile.read_text(encoding="utf-8")


def test_applying_from_the_preview_keeps_the_language_of_the_cards(served, profile):
    """What the page does not draw, it hands back untouched.

    The whole round trip: the payload, `state` in the page, "Apply", and
    `set_all`, which writes exactly what it is given.
    """
    card_templates.set_one("all.lang", "fr")
    held = _data(_read(served.url))["values"]
    assert held["all.lang"] == "fr"
    request = urllib.request.Request(
        served.url + "settings", method="POST", data=json.dumps(held).encode(),
        headers={"X-Kotogen": _token(_read(served.url))})
    with urllib.request.urlopen(request, timeout=5) as answer:
        assert answer.status == 200
    assert card_templates.value("all.lang") == "fr"


def test_a_write_without_the_token_is_refused(served, profile):
    """Any page visited during the preview can write to 127.0.0.1.

    It cannot read the answer, so it never learns the token.
    """
    request = urllib.request.Request(
        served.url + "settings", method="POST", data=b'{"vocab.tts": "yes"}')
    with pytest.raises(urllib.error.HTTPError) as refusal:
        urllib.request.urlopen(request, timeout=5)
    assert refusal.value.code == 403
    assert not profile.exists()


def test_a_page_reached_under_another_name_is_refused(served, profile):
    """A page can point a name of its own at 127.0.0.1 and read this one as its
    own origin, token included: the Host its browser sends gives it away."""
    host = "rebound.example:" + served.url.rstrip("/").rsplit(":", 1)[1]
    token = _token(_read(served.url))
    for request in (
            urllib.request.Request(served.url, headers={"Host": host}),
            urllib.request.Request(
                served.url + "settings", method="POST", data=b'{"vocab.tts": "yes"}',
                headers={"Host": host, "X-Kotogen": token})):
        with pytest.raises(urllib.error.HTTPError) as refusal:
            urllib.request.urlopen(request, timeout=5)
        assert refusal.value.code == 403
    assert not profile.exists()


def test_an_impossible_position_is_refused_without_writing(served, profile):
    request = urllib.request.Request(
        served.url + "settings", method="POST",
        data=json.dumps({"vocab.tts": "whenever"}).encode(),
        headers={"X-Kotogen": _token(_read(served.url))})
    with pytest.raises(urllib.error.HTTPError) as refusal:
        urllib.request.urlopen(request, timeout=5)
    assert refusal.value.code == 400
    assert not profile.exists()


def test_a_medium_can_be_asked_by_pieces(served):
    """Without ranges, clicking a line of the transcript jumps nowhere.

    Chrome cannot seek in a file it cannot ask for by pieces: playback goes back
    to the start.
    """
    whole = _read(served.url + preview.PAGES[0])
    request = urllib.request.Request(served.url + preview.PAGES[0],
                                     headers={"Range": "bytes=10-19"})
    with urllib.request.urlopen(request, timeout=5) as answer:
        assert answer.status == 206
        assert answer.headers["Content-Range"] == f"bytes 10-19/{len(whole)}"
        assert answer.read().decode("utf-8") == whole[10:20]


def test_the_server_only_serves_what_it_made_itself(served):
    """A server open on the disk has no business in a preview."""
    for path in ("card_templates.env", "../../../etc/passwd",
                 "templates/audio/front.html"):
        with pytest.raises(urllib.error.HTTPError) as refusal:
            urllib.request.urlopen(served.url + path, timeout=5)
        assert refusal.value.code == 404


def test_the_payload_cannot_close_its_own_script_tag():
    """The templates hold `</script>`: written raw, the first would close the tag
    carrying the payload, which must run whole up to the first `</script>`."""
    page = preview.page(preview.samples(()))
    start = page.index("var DATA = ") + len("var DATA = ")
    raw = page[start:page.index("</script>", start)]
    assert raw.endswith(";")
    assert json.loads(raw[:-1])["cards"]
