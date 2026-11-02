"""What this profile keeps of the repository templates (`kotogen/anki/templates.py`).

With no difference set, a template without variants renders byte for byte as
the file. The other tests catch what would only show on a card: a marker renamed
on one side only, a mistyped value, a block forgotten in one of the two faces.
The setting keys and values (`vocab.tts`, `yes`, `on-click`...) are written
into `templates.env` and read back from it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from kotogen import choices
from kotogen.anki import notetypes, preview, templates as card_templates


@pytest.fixture(autouse=True)
def profile(tmp_path, monkeypatch):
    """A file of choices of our own: the tests ignore the machine's."""
    target = tmp_path / choices.FILE
    monkeypatch.setattr(choices, "file", lambda: target)
    return target


@pytest.fixture
def root():
    """The real `templates/`: these tests are about the shipped templates."""
    found = notetypes.templates_root()
    if found is None:
        pytest.skip("templates/ folder not found")
    return found


def shipped_templates(root):
    """(command, path) of every template of the repository, CSS included."""
    for spec in notetypes.SPECS:
        for _, sub in spec.all_cards:
            base = root / spec.directory
            folder = base / sub if sub else base
            for name in ("front.html", "back.html", "style.css"):
                if (folder / name).exists():
                    yield spec.command, folder / name
    # The sheet every type shares answers to the global settings alone.
    common = root / notetypes.COMMON_CSS
    if common.exists():
        yield card_templates.GLOBAL, common


# ── The two guarantees ────────────────────────────────────────────────────────

def test_a_file_without_variants_renders_byte_for_byte(root):
    """Nothing set, nothing changed: that is what makes the rest safe.

    A template with a group of variants also carries the ones not taken, so it
    is skipped here and its structure is checked further down.
    """
    seen = 0
    for command, path in shipped_templates(root):
        text = path.read_text(encoding="utf-8")
        if card_templates.variants(text):
            continue
        seen += 1
        assert card_templates.render(text, command) == text, path
    assert seen, "not one template without a variant left: the test proves nothing"


def test_rendering_twice_changes_nothing_more(root):
    """Rendering is idempotent: `deck` can compare a rendering with what Anki carries."""
    for command, path in shipped_templates(root):
        once = card_templates.render(path.read_text(encoding="utf-8"), command)
        assert card_templates.render(once, command) == once, path


def test_no_block_opens_inside_a_selector_list(root):
    """A block that removes the tail of a selector list leaves its comma behind.

    `.a,` followed by the next rule makes that rule `.a, .next { ... }`: the
    style of the next block lands on `.a`, and only with the setting turned off.
    """
    for _command, path in shipped_templates(root):
        if path.suffix != ".css":
            continue
        before = ""
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*/\*\s*kotogen:", line):
                assert not before.endswith(","), f"{path}:{number}"
            if line.strip():
                before = line.rstrip()


def _settings_of(command: str) -> tuple:
    """The settings that touch the templates of this command, global ones included."""
    return tuple(s for s in card_templates.SETTINGS
                 if s.command in (command, choices.GLOBAL))


def test_every_variant_names_a_declared_position(root):
    """A value invented in a marker: a block nothing ever keeps."""
    for command, path in shipped_templates(root):
        for name, values in card_templates.variants(path.read_text(encoding="utf-8")).items():
            setting = next(s for s in _settings_of(command) if s.marker == name)
            unknown = values - set(setting.positions)
            assert not unknown, f"{path}: {name} quotes {unknown}"


def test_every_position_changes_something(root, profile):
    """Every declared position renders a card different from the others.

    Catches a value mistyped in a marker, a block forgotten in one face, a
    position declared without markup. `all.lang` changes no template on purpose:
    it picks the folder of the instructions, which `test_prompts.py` checks.
    """
    for setting in card_templates.SETTINGS:
        if setting is card_templates.LANGUAGE:
            continue
        rendered = {}
        for position in setting.positions:
            card_templates.set_one(setting.key, position)
            rendered.setdefault(_rendered(root, setting.command), []).append(position)
        card_templates.set_one(setting.key, setting.default)
        twins = [p for p in rendered.values() if len(p) > 1]
        assert not twins, f"{setting.key}: {twins} render the same card"


def test_a_removed_block_takes_its_markers_with_it():
    card_templates.set_one("vocab.notes", "no")
    out = card_templates.render("before\n<!-- kotogen:notes -->\ninside\n"
                                "<!-- /kotogen:notes -->\nafter\n", "vocab")
    assert out == "before\nafter\n"


def test_a_kept_block_keeps_its_markers():
    """Kept, they cost nothing in Anki and say on the spot what they are for."""
    text = "<!-- kotogen:notes -->\ninside\n<!-- /kotogen:notes -->\n"
    assert card_templates.render(text, "vocab") == text


def test_the_real_back_ships_without_its_tts_tag(root):
    """A machine with no Japanese voice prints Anki's error on every back that
    carries `{{tts}}`: the back ships without it, and the recording still plays."""
    back = (root / "vocab" / "recognition" / "back.html").read_text(encoding="utf-8")
    out = card_templates.render(back, "vocab")
    assert "{{tts" not in out and "kotogen:tts" not in out
    assert "{{#Audio}}" in out
    assert "{{furigana::Expression}}" in out and 'id="vocab-class"' in out


def test_the_system_voice_stands_in_for_a_recording_never_beside_it(root):
    """Turned on, the voice speaks only on a note whose `Audio` is empty: a
    recording is the better voice, and two players would overlap."""
    back = (root / "vocab" / "recognition" / "back.html").read_text(encoding="utf-8")
    card_templates.set_one("vocab.tts", "yes")
    out = card_templates.render(back, "vocab")
    assert ('{{^Audio}}<div class="vocab-player">{{tts ja_JP:kana:Expression}}</div>'
            '{{/Audio}}') in out
    assert '{{#Audio}}<div class="vocab-player">{{Audio}}</div>{{/Audio}}' in out


@pytest.mark.parametrize("side", ["recognition", "production"])
def test_the_player_comes_before_the_card(root, side):
    """`.vocab-player ~ .vocab-card` keeps the foot of the card free for it, and
    a sibling selector only reads forward: a player laid after the card would
    leave the end of a long back under it."""
    back = (root / "vocab" / side / "back.html").read_text(encoding="utf-8")
    assert back.index('class="vocab-player"') < back.index('class="vocab-card"')


@pytest.mark.parametrize("side", ["recognition", "production"])
@pytest.mark.parametrize("tag", ["Verb::一段動詞", "Verb::五段動詞", "Verb::不規則動詞",
                                 "Adjective::い", "Adjective::な", "Noun", "Adverb",
                                 "Expression", "Onomatopoeia", "Counter", "Date"])
def test_the_colours_read_every_grammatical_tag(root, side, tag):
    """Each class the vocabulary instruction lays has its colour on both backs."""
    back = (root / "vocab" / side / "back.html").read_text(encoding="utf-8")
    assert f'"{tag}":' in back


def test_both_vocabulary_backs_run_the_same_script(root):
    """One script, copied into both backs: Anki has no file two templates can
    share, and a fix made in one copy only would leave the other behind."""
    scripts = [(root / "vocab" / side / "back.html").read_text(encoding="utf-8")
               .rsplit("<script>", 1)[1] for side in ("recognition", "production")]
    assert scripts[0] == scripts[1]


def test_the_word_fits_the_same_on_every_face(root):
    """The script that shrinks a word wider than the screen is the same on every
    face: otherwise the word would jump when the card turns."""
    faces = [root / "vocab" / "recognition" / "front.html",
             root / "vocab" / "recognition" / "back.html",
             root / "vocab" / "production" / "back.html"]
    scripts = [re.search(r"<!-- A word wider than the screen.*?</script>",
                         face.read_text(encoding="utf-8"), re.S)
               for face in faces]
    assert all(scripts)
    assert len({script.group(0) for script in scripts}) == 1


def test_both_vocabulary_sheets_are_the_same(root):
    """Anki keeps one sheet per note type, read from the first card: a rule
    written in the second one only would never reach a card."""
    sheets = [(root / "vocab" / side / "style.css").read_text(encoding="utf-8")
              for side in ("recognition", "production")]
    assert sheets[0] == sheets[1]


def test_the_style_sheet_keeps_the_player_without_the_voice(root):
    """The recording plays in the player the system voice uses: turning the
    voice off leaves it styled."""
    css = (root / "vocab" / "recognition" / "style.css").read_text(encoding="utf-8")
    for position in ("no", "yes"):
        card_templates.set_one("vocab.tts", position)
        out = card_templates.render(css, "vocab")
        assert ".vocab-player ~ .vocab-card {" in out and ".vocab-player {" in out


@pytest.mark.parametrize("command", ["reading", "audio"])
def test_the_answer_is_printed_as_its_decoys_are(root, command):
    """The export lays readings on the answer as on the decoys: printed raw on
    one face, it would show them in their brackets.

    What precedes the field name is its filter, "" for a field printed as it
    stands; a section tag (`{{#Decoy1}}`) prints nothing and is not caught.
    """
    for cmd, path in shipped_templates(root):
        if cmd != command or path.suffix != ".html":
            continue
        text = path.read_text(encoding="utf-8")
        for name in ("Answer", "Decoy1", "Decoy2", "Decoy3"):
            filters = set(re.findall(r"\{\{([^#/^{}]*?)\b" + name + r"\}\}", text))
            assert filters <= {"furigana::"}, f"{path.name}: {name} printed as {filters}"


# ── Each setting removes its own, and nothing else ────────────────────────────
# The risk of a marked-up block is that it takes a neighbour with it: the verb
# and adjective colours sit side by side, and the badge shares its script with
# the colouring. Each entry says what goes AND what stays.

REMOVES = {
    # The script colours the card before filling the badge in: with no badge,
    # the colour has to hold, and so does the register beside it.
    "vocab.badge": (('id="vocab-class"', ".vocab-class {"),
                    ("card.classList.add", ".vocab-card.verb-一段動詞", 'id="vocab-registers"')),
    # The three colour families sit side by side: each one goes alone.
    "vocab.verb-colours": ((".vocab-card.verb-一段動詞", ".vocab-card.verb-五段動詞"),
                           (".vocab-card.adj-い", ".vocab-card.noun", ".vocab-class {")),
    "vocab.adjective-colours": ((".vocab-card.adj-い", ".vocab-card.adj-な"),
                                (".vocab-card.verb-一段動詞", ".vocab-card.noun")),
    "vocab.other-colours": ((".vocab-card.noun", ".vocab-card.adverb",
                             ".vocab-card.expression"),
                            (".vocab-card.verb-一段動詞", ".vocab-card.adj-な")),
    "vocab.notes": (("{{furigana::Notes}}", ".vocab-notes {"),
                    ("{{furigana::Example}}", "{{furigana::Translation}}")),
    # The context goes from the back of `Recognition` and stays on `Production`,
    # where it is the question. The block is the same on both cards, so only its
    # marker can witness the removal.
    "vocab.context": (("kotogen:context",),
                      ("{{#Context}}", ".vocab-context {", "{{furigana::Translation}}")),
    # The badge goes from both backs (no front has one); the grammar badge stays.
    "vocab.register": (('id="vocab-registers"', ".vocab-register {"),
                       ('id="vocab-class"', "{{furigana::Translation}}")),
    # The hint goes from the gap and from the back, where the line setting it
    # against the answer finds no word and stays hidden. The answer stays.
    "grammar.hint": (("{{furigana::Hint}}", ".grammar-hint {"),
                     ("{{furigana:cloze:Sentence}}", 'id="grammar-answer"',
                      '<span class="grammar-nuance">')),
    # The explanation takes with it its ≠ contrast, cut out of it by a script of
    # its own, and leaves the name of the rule.
    "grammar.explanation": (("{{furigana::Explanation}}", ".grammar-explanation {",
                             'id="grammar-contrast"'),
                            ("{{furigana::Rule}}", "grammar-link")),
    "grammar.nuance": (('<span class="grammar-nuance">', ".grammar-nuance {"),
                       ('id="register"', ".grammar-badge {")),
    "reading.key-line": (("{{KeyLine}}", ".line.is-key"),
                         ("{{furigana::Translation}}", "{{#Source}}")),
    # The badge goes from over the sentence, the nuance under it stays.
    "grammar.register": (('id="register"', ".grammar-register.formal"),
                          ("{{furigana:cloze:Sentence}}", '<span class="grammar-nuance">')),
    # The level goes, the link beside it stays; its script finds nothing to fill.
    "grammar.badge": (('id="grammar-level"', ".grammar-level {"),
                      (".grammar-link {", 'getElementById("grammar-level")')),
    # The link goes, and the name of the rule it went with stays.
    "grammar.link": (("{{#URL}}", ".grammar-link {"),
                     ("{{furigana::Rule}}", "{{furigana::Explanation}}")),
    "audio.source": (("{{#Source}}", ".source-section"), ("{{#Transcript}}",)),
    # The level goes with the script that fills it and the tags it reads; the
    # question stays.
    "audio.badge": (('id="card-level"', ".card-badges {", 'id="note-tags"'),
                    ("{{furigana::Question}}",)),
    "reading.badge": (('id="card-level"', ".card-badges {", 'id="note-tags"'),
                      ("{{furigana::Question}}",)),
    "reading.source": (("{{#Source}}", ".source-section"),
                       ('class="answer-text">{{furigana::Answer}}',)),
    # The badges go, the script that would fill the level stays and finds
    # nothing to fill: it looks for the element before writing into it.
    "kanji.badge": (('id="kanji-level"', ".kanji-badges {", "画</span>"),
                    ("{{furigana::Meaning}}", 'getElementById("kanji-level")')),
    # A witness and not a block of the page: the script draws the reading at
    # the end of each word only when it finds this element.
    "kanji.word-readings": (('id="kanji-word-readings"',),
                            ('id="kanji-words"', "showWordReadings")),
    # The two asides share their style: one going takes nothing of the other.
    "kanji.composition": (("{{Composition}}",), ("{{LookAlikes}}", ".kanji-aside {")),
    "kanji.lookalikes": (("{{LookAlikes}}",), ("{{Composition}}", ".kanji-aside {")),
    "kanji.notes": (("{{furigana::Notes}}", "熟字訓"), ("{{LookAlikes}}", ".kanji-aside {")),
}


def _rendered(root, command: str) -> str:
    """The templates of one command, rendered and laid end to end.

    `card_templates.GLOBAL` takes them all: a global setting is judged on every card.
    """
    if command == card_templates.GLOBAL:
        return "\n".join(card_templates.render(path.read_text(encoding="utf-8"), cmd)
                         for cmd, path in shipped_templates(root))
    return "\n".join(card_templates.render(path.read_text(encoding="utf-8"), command)
                     for cmd, path in shipped_templates(root) if cmd == command)


@pytest.mark.parametrize("key", sorted(REMOVES))
def test_a_setting_removes_its_block_and_leaves_its_neighbours(root, key):
    gone, left = REMOVES[key]
    command = key.split(".")[0]
    before = _rendered(root, command)
    card_templates.set_one(key, "no")
    after = _rendered(root, command)
    for string in gone:
        assert string in before, f"{key}: \"{string}\" absent even before the setting"
        assert string not in after, f"{key}: \"{string}\" should have gone"
    for string in left:
        assert string in after, f"{key}: \"{string}\" went with the rest"


def test_every_yes_no_setting_is_covered_by_the_removal_table():
    """A setting added with no test could remove anything unseen.

    Settings with more than two positions swap variants: `VARIANTS` covers them."""
    binary = {s.key for s in card_templates.SETTINGS if s.positions == ("yes", "no")}
    assert binary == set(REMOVES)


# ── What each position gives ──────────────────────────────────────────────────
# That the positions differ is tested above; this says what each one gives.

# The four `howMany` written side by side in the card scripts: one survives the
# rendering, since of two in one script the second would silently win.
_HOW_MANY = {
    "four": "function howMany(total) { return total; }",
    "two": "function howMany(total) { return Math.min(2, total); }",
    "none": "function howMany() { return 0; }",
    "alternate": "parseInt(rank[1], 10) % 2 === 1",
}


def _choices(position: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What the position keeps, and what it must have taken away."""
    return ((_HOW_MANY[position],),
            tuple(v for key, v in _HOW_MANY.items() if key != position))


VARIANTS = {
    ("reading.choices", "four"): _choices("four"),
    ("reading.choices", "two"): _choices("two"),
    ("reading.choices", "none"): _choices("none"),
    ("reading.choices", "alternate"): _choices("alternate"),
    ("audio.choices", "four"): _choices("four"),
    ("audio.choices", "two"): _choices("two"),
    ("audio.choices", "none"): _choices("none"),
    ("audio.choices", "alternate"): _choices("alternate"),
    ("reading.markers", "digits"): (("'12345678'",), ("'ABCDEFGH'",)),
    ("reading.markers", "none"): ((), ("'ABCDEFGH'", "'12345678'", ".choice-letter {",
                                        ".choice-letter').textContent")),
    ("reading.order", "fixed"): (("seeded(hash(seed ? seed.textContent : ''))",),
                                ("ankiDay(",)),
    # Both versions of the text are in the template: the position picks the one
    # that survives, and whether the button to switch stays.
    ("reading.furigana", "button"): (("furigana-btn", "kotogenToggleFurigana",
                                      "{{kanji::Text}}", "{{furigana::Text}}"),
                                     ("read.style.display = 'block'",)),
    ("reading.furigana", "always"): (("{{furigana::Text}}",),
                                       ("{{kanji::Text}}", "furigana-btn",
                                        "kotogenToggleFurigana")),
    ("reading.furigana", "never"): (("{{kanji::Text}}",),
                                     ("{{furigana::Text}}", "furigana-btn")),
    ("reading.furigana", "back"): (("{{kanji::Text}}", "{{furigana::Text}}",
                                     "read.style.display = 'block'"), ("furigana-btn",)),
    ("reading.translation", "at-once"): (("showTranslation(true)",),
                                         ("showTranslation(false)",)),
    ("reading.translation", "never"): ((".japanese-text .trans,",),
                                       ("tr-toggle", "showTranslation(")),
    # The palette picks what the dark colours open on, and whether the light ones
    # stay; the shared dark colours stay in every palette, for full screen.
    ("all.palette", "dark"): ((":root,\n.card,\n/* /kotogen:palette */",
                               "--register-formal: 140, 158, 255;"),
                              ("--background: 250, 250, 250;", ".card.night_mode,\n",
                               ".nightMode, .night_mode {")),
    ("all.palette", "light"): (("--background: 250, 250, 250;", "--correct: 46, 125, 50;"),
                               (":root,\n.card,\n/* /kotogen:palette */", ".card.night_mode,\n",
                                "--register-formal: 140, 158, 255;",
                                ".nightMode, .night_mode {")),
    ("all.palette", "auto"): (("--background: 250, 250, 250;", ".card.night_mode,\n",
                               ".nightMode, .night_mode {", "--register-formal: 140, 158, 255;"),
                              (":root,\n.card,\n/* /kotogen:palette */",)),
    # Only the typing position has Anki's typing box; the `Answer` field is
    # written in both, so switching needs no new call to the AI.
    ("grammar.answer", "recall"): ((), ("{{type:Answer}}", ".grammar-typing input")),
    ("grammar.answer", "type"): (("{{type:Answer}}", ".grammar-typing input", ".typeGood"),
                                    ()),
    # Here the translation is the main hint: two positions, not three. Only the
    # script of the button hides it and the meaning under the gap, so a card with
    # no JavaScript stays solvable.
    ("grammar.translation", "at-once"): ((), ('"grammar-reveal"',
                                              ".grammar-under.is-veiled")),
    ("grammar.translation", "on-click"): (('"grammar-reveal"',
                                         ".grammar-under.is-veiled"), ()),
    # The setting touches the statement ONLY: the conjugation hint and the
    # explanation keep their readings in all three positions.
    ("grammar.furigana", "always"): (("{{furigana:cloze:Sentence}}",
                                        "{{furigana::Hint}}"),
                                       ("{{kanji:cloze:Sentence}}",)),
    ("grammar.furigana", "back"): (("{{kanji:cloze:Sentence}}",
                                     "{{furigana:cloze:Sentence}}",
                                     "{{furigana::Hint}}"), ()),
    ("grammar.furigana", "never"): (("{{kanji:cloze:Sentence}}",
                                      "{{furigana::Hint}}"),
                                     ("{{furigana:cloze:Sentence}}",)),
    # The word is judged by its box: the backs also carry it hidden, in kanji,
    # in every position.
    ("vocab.furigana", "no"): (('id="vocab-word">{{kanji::Expression}}',
                                "{{furigana::Example}}", "{{furigana::Notes}}"),
                               ("{{furigana::Expression}}", "{{kana::Expression}}")),
    ("vocab.furigana", "kana"): (("{{kana::Expression}}", "{{kana::Example}}",
                                  "{{kana::Notes}}", 'id="vocab-kanji" hidden>'),
                                 ('id="vocab-word">{{kanji::Expression}}',
                                  '"vocab-word-box">{{kanji::Expression}}',
                                  "{{furigana::Expression}}",
                                  "{{furigana::Example}}", "{{furigana::Notes}}")),
    # The example is written twice on the back, with and without translation:
    # the position picks one, "no" leaves neither.
    ("vocab.example", "untranslated"): (("{{furigana::Example}}", ".vocab-example {"),
                                        ("ExampleTranslation", ".vocab-example-translation")),
    ("vocab.example", "no"): ((), ("{{furigana::Example}}", "ExampleTranslation",
                                   ".vocab-example {")),
    ("audio.transcript", "unfolded"): (("panel.open = true",), ()),
    # Both halves are needed: the end bound laid on each sentence, and the stop
    # that watches for it, per frame: `timeupdate` fires four times a second and
    # would let a quarter of a second of the next sentence through.
    ("audio.click", "sentence"): (("dataset.end = clickables[i + 1].dataset.t",
                                "bound = parseFloat(line.dataset.end)",
                                "player.pause()",
                                "requestAnimationFrame(follow)",
                                "if (!frame) follow();"),
                               ()),
    ("audio.click", "continue"): ((),
                               ("dataset.end = clickables[i + 1].dataset.t",
                                "bound = parseFloat(line.dataset.end)",
                                "player.pause()",
                                "requestAnimationFrame(follow)",
                                "function follow()")),
    ("audio.translation", "at-once"): (("showTranslation(true)",),
                                       ("showTranslation(false)",)),
    # With no switch, the rule that hides the translation still has to stay.
    ("audio.translation", "never"): ((".interlinear .trans {",),
                                     ('class="aid tr-toggle"', "showTranslation(")),
    # The system's own player: the bar, the script removing the controls and the
    # ticks all go; the sentences of the transcript still seek into the sound.
    ("audio.player", "native"): (("{{Audio}}", "playLine(line)"),
                                 ('class="player-bar"', ".player-bar {",
                                  "media.removeAttribute('controls')", "player-tick")),
    # The script writes the on readings in hiragana only when it finds this element.
    ("kanji.onyomi", "katakana"): ((), ('id="kanji-on-in-hiragana"',)),
    ("kanji.onyomi", "hiragana"): (('id="kanji-on-in-hiragana"',), ()),
    # Folded, shown on their own row, or not at all; no fold, no fold style.
    ("kanji.other-readings", "folded"): (('<details class="other-readings">',
                                          ".other-readings summary"), ()),
    ("kanji.other-readings", "shown"): (("{{OtherReadings}}",),
                                        ('<details class="other-readings">',
                                         ".other-readings summary")),
    ("kanji.other-readings", "no"): ((), ("{{OtherReadings}}", ".other-readings summary")),
    # The words keep their place in the grid: the translation is hidden, not removed.
    ("kanji.words", "yes"): ((".word-meaning {",), ("visibility: hidden",)),
    ("kanji.words", "untranslated"): (("visibility: hidden", ".word-meaning {"), ()),
    # The voice speaks only where the note has no recording, which plays either
    # way. The tag line at the foot of the back goes with its style, not the
    # scripts reading the tags for a badge.
    ("vocab.tts", "no"): (("{{#Audio}}", ".vocab-player {"), ("{{tts",)),
    ("vocab.tts", "yes"): (("{{^Audio}}", "{{tts ja_JP:kana:Expression}}", "{{#Audio}}"),
                           ()),
    ("vocab.tags", "no"): (("{{furigana::Translation}}", '<span id="note-tags" hidden>{{Tags}}</span>'),
                           ('id="tags"',)),
    ("vocab.tags", "yes"): (('id="tags"', "{{furigana::Translation}}"), ()),
    ("grammar.tags", "no"): (("{{furigana:cloze:Sentence}}",), ('id="tags"', ".tags-footer")),
    ("grammar.tags", "yes"): (('id="tags"', ".tags-footer", "{{furigana:cloze:Sentence}}"),
                              ()),
    ("kanji.tags", "no"): (("{{furigana::Meaning}}", 'getElementById("kanji-level")'),
                           ('id="tags"', ".tags-footer")),
    ("kanji.tags", "yes"): (('id="tags"', ".tags-footer", "{{furigana::Meaning}}"), ()),
}


@pytest.mark.parametrize("key, position", sorted(VARIANTS))
def test_a_position_gives_what_it_says(root, key, position):
    present, absent = VARIANTS[(key, position)]
    card_templates.set_one(key, position)
    out = _rendered(root, key.split(".")[0])
    for string in present:
        assert string in out, f"{key}={position}: \"{string}\" is missing"
    for string in absent:
        assert string not in out, f"{key}={position}: \"{string}\" stayed"


def test_every_position_of_every_variant_is_described():
    """A position added with no test would give any card at all."""
    expected = {(s.key, p) for s in card_templates.SETTINGS if s.positions != ("yes", "no")
                for p in s.positions
                if p != s.default and s is not card_templates.LANGUAGE}
    assert expected <= set(VARIANTS)   # describing the default position is a bonus


# ── The contrast of the text ──────────────────────────────────────────────────
# Both palettes keep their levels of text at the AA ratio (4.5:1). The colours of
# the classes and of the readings are left out: chosen for their hue, a few of
# them fall short of it on their own tint.

def _palette(root, which: str, sheet: str = notetypes.COMMON_CSS) -> dict[str, tuple[int, ...]]:
    """The colours one palette of a sheet declares, by name: the shared one by default.

    The shared dark colours sit in no block, kept in every palette for full
    screen: they are the rule that opens on `.is-full-screen`.
    """
    css = (root / sheet).read_text(encoding="utf-8")
    block = re.search(rf"/\* kotogen:palette={which}\|auto \*/(.*?)/\* /kotogen:palette \*/",
                      css, re.S)
    body = block.group(1) if block else re.search(r"\.is-full-screen \{([^}]*)\}", css).group(1)
    return {name: tuple(int(c) for c in value.split(","))
            for name, value in re.findall(r"--([\w-]+): (\d+, \d+, \d+);", body)}


def _rules(css: str) -> list[tuple[list[str], dict[str, str]]]:
    """(selectors, declarations) of every rule of a sheet, its comments dropped."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [([s.strip() for s in selectors.split(",") if s.strip()],
             {d.split(":", 1)[0].strip(): d.split(":", 1)[1].strip()
              for d in body.split(";") if ":" in d})
            for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def _contrast(ink: tuple[float, ...], paper: tuple[float, ...]) -> float:
    """The contrast ratio of two colours, as WCAG computes it."""
    def luminance(rgb):
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
                  for c in (v / 255 for v in rgb)]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    light, dark = sorted((luminance(ink), luminance(paper)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("palette", ["dark", "light"])
def test_every_level_of_text_reads_at_the_aa_ratio(root, palette):
    """On the page, the sign of a lit button on the accent, and the faint level
    in the box of the vocabulary example, which a word with no colour of its own
    tints with the colour of the text."""
    colours = _palette(root, palette)
    page = colours["background"]
    sheet = (root / "vocab" / "recognition" / "style.css").read_text(encoding="utf-8")
    tint = float(re.search(r"\.vocab-example \{[^}]*background-color: rgba\(var\(--k\), ([\d.]+)\)",
                           sheet).group(1))
    box = tuple(tint * t + (1 - tint) * p for t, p in zip(colours["text"], page))
    read_on = [(name, page) for name in colours if name.startswith("text")]
    read_on += [("on-accent", colours["accent"]), ("text-faint", box)]
    short = [name for name, paper in read_on if _contrast(colours[name], paper) < 4.5]
    assert not short, f"{palette}: {short}"


@pytest.mark.parametrize("palette", ["dark", "light"])
def test_the_reading_of_the_highlighted_word_reads_at_the_aa_ratio(root, palette):
    """The highlight tints the box of the example a second time, with the colour
    of the word's class, or of the text for a word with none."""
    colours = _palette(root, palette)
    page = colours["background"]
    sheet = (root / "vocab" / "recognition" / "style.css").read_text(encoding="utf-8")

    def alpha(selector: str) -> float:
        return float(re.search(re.escape(selector) + r" \{[^}]*background-color: "
                               r"rgba\(var\(--k\), ([\d.]+)\)", sheet).group(1))

    reading = re.search(r"\.vocab-example mark rt \{[^}]*color: rgb\(var\(--([\w-]+)\)\)",
                        sheet).group(1)
    classes = {name: rgb for name, rgb
               in _palette(root, palette, "vocab/recognition/style.css").items()
               if not name.startswith("register")}
    short = []
    for name, tint in {**classes, "text": colours["text"]}.items():
        box = tuple(alpha(".vocab-example") * t + (1 - alpha(".vocab-example")) * p
                    for t, p in zip(tint, page))
        mark = tuple(alpha(".vocab-example mark") * t + (1 - alpha(".vocab-example mark")) * b
                     for t, b in zip(tint, box))
        if _contrast(colours[reading], mark) < 4.5:
            short.append(name)
    assert not short, f"{palette}: {short}"


# ── The consistency of the markers ────────────────────────────────────────────

def test_every_marker_in_the_repo_is_declared(root):
    """A marker with no setting: no rule says whether to keep the block."""
    for command, path in shipped_templates(root):
        placed = card_templates.markers(path.read_text(encoding="utf-8"))
        known = {setting.marker for setting in _settings_of(command)}
        assert placed <= known, f"{path}: {placed - known} with no setting"


def test_every_declared_setting_marks_something(root):
    """A setting with no marker: a switch that cuts nothing, silently.

    `all.lang` alone is exempt, by name, so that a second setting marking
    nothing up still fails.
    """
    placed: dict[str, set[str]] = {}
    for command, path in shipped_templates(root):
        placed.setdefault(command, set())
        placed[command] |= card_templates.markers(path.read_text(encoding="utf-8"))
    for setting in card_templates.SETTINGS:
        if setting is card_templates.LANGUAGE:
            continue
        # A global setting has no command: its marker may sit in any template.
        seen = (set().union(*placed.values()) if setting.command == card_templates.GLOBAL
                else placed.get(setting.command, set()))
        assert setting.marker in seen, setting.key


def test_every_language_of_the_cards_is_a_position_with_a_name():
    """The positions of `all.lang` are the folders of `prompts/`. Each needs a
    name in `LANGUAGE_NAMES` (else the list shows the bare code), and no name
    may outlive its folder."""
    from kotogen import prompts

    assert card_templates.LANGUAGE.positions == tuple(prompts.languages())
    assert card_templates.LANGUAGE.default == prompts.SOURCE
    assert set(card_templates.LANGUAGE_NAMES) == set(prompts.languages())


# ── What a card says in its own voice ─────────────────────────────────────────
# A card prints no prose: its words come from the note, and what it says on its
# own account it says in signs, so ONE set of templates serves every language
# (see `all.lang` in `kotogen/anki/templates.py`). The reading below catches the
# three ways to break it: a `title="First page"` in the markup, a
# `createTextNode("Detail")` in a script, a line of help in an `innerHTML`.

# Everything the cards say that comes neither from a field nor from a comment:
# signs, not one sentence.
SAID_BY_THE_CARDS = {
    "訳",          # the translation switch, on the three cards that have one
    "再生",        # the play button the listening card draws
    "再生速度",    # and its speed button, worn as one of the three below
    "再生位置",    # and the bar, read aloud as a slider
    "1×", "¾×", "½×",
    "本文",        # the transcript it faces on the listening card
    "ふ",          # the furigana switch
    "↗",           # a reference page whose domain the script could not read
    "参照",        # and its name, read aloud
    "«", "»", "‹", "›",   # the page jumps of the mini-book, and its page turns
    "最初のページ", "最後のページ", "前のページ", "次のページ",  # and their names, read aloud
    "全画面",      # the full screen button, drawn and worn as a label
    "頁",          # the page an image could not load on: the kanji of a page
    "▾", "▴",      # the arrows of a fold, written in the style sheet
    "※",           # the mark of a vocabulary note
    "な",          # what a な-adjective takes before a noun, after the word
    "|", "/", "0", "1",   # separators and counters
    "音", "訓", "他",  # the on, kun and other readings of the kanji card
    "構成",        # what a kanji is made of
    "≠",           # the kanji it is mistaken for, the rule set against the answer
    "→",           # the word to conjugate, set against the form on a grammar back
    "熟字訓",      # the words read as a whole, in its notes
    "画",          # after its number of strokes
}

_HUMAN = {"title", "alt", "placeholder", "aria-label"}


class _Reader(HTMLParser):
    """The text a reader sees and the attributes read aloud or on hover; what a
    script hands to the page is read in `_said_by`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.said: list[str] = []
        self._mute = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._mute += 1
        for name, value in attrs:
            if name in _HUMAN and value:
                self.said.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._mute = max(0, self._mute - 1)

    def handle_data(self, data):
        if not self._mute:
            self.said.append(data)


# Not said by the template: comments, fields (`{{Translation}}`: the note's
# words) and `${page}`, a number computed on the spot.
_ASIDE = re.compile(r"<!--.*?-->|/\*.*?\*/|//[^\n]*|\{\{[^}]*\}\}|\$\{[^}]*\}", re.S)

# The three ways a script puts words on the card, and the style sheet's one.
_INNER_HTML = re.compile(r'\.innerHTML\s*=\s*([`\'"])(.*?)\1', re.S)
_HANDED_OVER = re.compile(
    r'(?:\.title|\.textContent|\.innerText)\s*=\s*([\'"`])(.*?)\1'
    r'|createTextNode\(\s*([\'"`])(.*?)\3', re.S)
_CSS_CONTENT = re.compile(r"[^-]content:\s*([\"'])(.*?)\1", re.S)


def _said_by(text: str, suffix: str) -> set[str]:
    """Every word this rendered template puts in front of a reader.

    A style sheet speaks only through `content:`; parsed as markup, it would
    come back whole as one text node.
    """
    if suffix == ".css":
        return {body.strip() for _quote, body in _CSS_CONTENT.findall(text)
                if body.strip()}
    reader = _Reader()
    reader.feed(text)
    said = list(reader.said)
    # An `innerHTML` is markup handed over whole: it is read the same way.
    for _quote, body in _INNER_HTML.findall(text):
        inner = _Reader()
        inner.feed(body)
        said += inner.said
    for _q1, spoken, _q2, made in _HANDED_OVER.findall(text):
        said += [spoken, made]
    return {piece.strip() for piece in said if piece.strip()}


def test_a_card_says_nothing_but_signs(root, monkeypatch):
    """No template writes prose, in any position of any setting.

    Each position is swept, one at a time: a block left out by default is the
    one never looked at. `all.lang` is swept too and must change nothing.
    """
    for setting in card_templates.SETTINGS:
        for position in setting.positions:
            monkeypatch.setattr(choices, "values",
                                lambda key=setting.key, chosen=position: {key: chosen})
            for command, path in shipped_templates(root):
                shown = _ASIDE.sub(" ", card_templates.render(
                    path.read_text(encoding="utf-8"), command))
                prose = _said_by(shown, path.suffix) - SAID_BY_THE_CARDS
                assert not prose, (
                    f"{path.name} with {setting.key}={position} speaks for "
                    f"itself: {sorted(prose)}")


def test_nothing_is_allowed_that_nothing_says(root, monkeypatch):
    """`SAID_BY_THE_CARDS` is an inventory: an entry whose glyph is gone must go.

    Swept across every position, as above: a sign said only by a block left out
    by default (the 他 of the folded readings) is still said."""
    said = set()
    for setting in card_templates.SETTINGS:
        for position in setting.positions:
            monkeypatch.setattr(choices, "values",
                                lambda key=setting.key, chosen=position: {key: chosen})
            for command, path in shipped_templates(root):
                said |= _said_by(_ASIDE.sub(" ", card_templates.render(
                    path.read_text(encoding="utf-8"), command)), path.suffix)
    assert not SAID_BY_THE_CARDS - said, SAID_BY_THE_CARDS - said


def test_an_unknown_marker_stops_the_command():
    with pytest.raises(RuntimeError, match="unknown"):
        card_templates.render("<!-- kotogen:wizard -->x<!-- /kotogen:wizard -->", "vocab")


def test_an_unclosed_block_stops_the_command():
    with pytest.raises(RuntimeError, match="never closed"):
        card_templates.render("<!-- kotogen:tts -->x", "vocab")


# ── A script runs again on the same page ──────────────────────────────────────
# Anki desktop keeps one page from card to card and runs the scripts of every
# face in it, the front's a second time on the back through `{{FrontSide}}`. A
# `let` at the top of a script throws on that second run, which then runs
# nothing at all; a listener on the page is added once more by every face.

_SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S)

# A listener on the page itself, which outlives the card that added it.
_PAGE_LISTENER = re.compile(r"\b(?:window|document)(?:\.body|\.documentElement)?"
                            r"\.addEventListener\(\s*(['\"])(\w+)\1")

# The two ways to add one once per page: under a flag on window, raised as its
# block opens; and, for `DOMContentLoaded`, only while the page is loading.
_ONCE = re.compile(r"if \(!window\.(kotogen\w+)\) (\{)\s*window\.\1 = true;")
_LOADING = re.compile(r"if \(document\.readyState === (['\"])loading\1\) ")


def _scripts(root):
    """(where, body) of every script of the shipped faces, every block included."""
    for _command, path in shipped_templates(root):
        if path.suffix != ".html":
            continue
        text = path.read_text(encoding="utf-8")
        for match in _SCRIPT.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            yield f"{path.parent.name}/{path.name}:{line}", match.group(1)


def _statement(code: str, start: int) -> range:
    """Where the statement starting at `start` lies: a block up to its closing
    brace, anything else up to the end of its line."""
    if code.startswith("{", start):
        depth = 0
        for end in range(start, len(code)):
            depth += {"{": 1, "}": -1}.get(code[end], 0)
            if not depth:
                return range(start, end + 1)
        return range(start, len(code))
    end = code.find("\n", start)
    return range(start, len(code) if end < 0 else end)


def test_every_script_keeps_its_names_to_itself(root):
    """Wrapped whole in a function called on the spot, a script declares nothing
    on the page, and a `let`, a `const` or a `class` never meets itself again.

    Every line of code inside sits deeper than the opening one: a second
    function after the first, or a declaration between them, would not."""
    seen = 0
    for where, body in _scripts(root):
        code = [line for line in body.splitlines()
                if line.strip() and not line.strip().startswith("//")]
        seen += 1
        assert code[0].lstrip().startswith("(function"), f"{where}: {code[0].strip()}"
        assert code[-1].strip() == "})();", f"{where}: {code[-1].strip()}"
        margin = len(code[0]) - len(code[0].lstrip())
        outside = [line.strip() for line in code[1:-1]
                   if len(line) - len(line.lstrip()) <= margin]
        assert not outside, f"{where}: {outside[0]}"
    assert seen, "not one script found: the test proves nothing"


def test_a_listener_on_the_page_is_added_once(root):
    """Added by every face, listeners on the page would pile up, each acting on
    the card that added it. One goes under a flag on window, and finds the
    card on screen when it fires."""
    seen = 0
    for where, body in _scripts(root):
        flagged = [_statement(body, m.start(2)) for m in _ONCE.finditer(body)]
        loading = [_statement(body, m.end()) for m in _LOADING.finditer(body)]
        for listener in _PAGE_LISTENER.finditer(body):
            seen += 1
            at = listener.start()
            once = any(at in span for span in flagged) or (
                listener.group(2) == "DOMContentLoaded" and any(at in span for span in loading))
            assert once, f"{where}: {listener.group(0)} is added on every run"
    assert seen, "not one listener on the page found: the test proves nothing"


def test_a_handler_in_the_markup_calls_what_a_script_puts_on_window(root):
    """A wrapped script keeps its functions out of reach of an `onclick`, which
    can only call a name some face of the note type assigns to window: the ふ
    of a reading back calls the front's, carried there by `{{FrontSide}}`."""
    faces: dict[str, str] = {}
    for command, path in shipped_templates(root):
        if path.suffix == ".html":
            faces[command] = faces.get(command, "") + path.read_text(encoding="utf-8")
    for command, text in faces.items():
        published = set(re.findall(r"\bwindow\.(\w+) =", text))
        called = set(re.findall(r'\son\w+="\s*([\w$]+)\(', text))
        assert called <= published, f"{command}: {sorted(called - published)}"


# ── What the cards say in markup ──────────────────────────────────────────────

def test_no_field_is_written_into_a_script(root):
    """A field goes into a script as it stands: a tag holding a backtick, a `${`
    or a backslash would end the string or run. The scripts read what they need
    from an element of the page instead (`note-tags`)."""
    for where, body in _scripts(root):
        assert "{{" not in body, f"{where}: {re.findall(r'{{[^}]*}}', body)}"


def test_a_script_publishes_only_what_the_markup_calls(root):
    """The other half of the test above: a function a script puts on window is
    one an `onclick` calls. Anything else stays in its script, where a script of
    another card cannot replace it; a flag (`= true`) is no function."""
    for command, text in _faces_by_command(root).items():
        published = set(re.findall(r"\bwindow\.(\w+) = function", text))
        called = set(re.findall(r'\son\w+="\s*([\w$]+)\(', text))
        assert published <= called, f"{command}: {sorted(published - called)}"


def _faces_by_command(root) -> dict[str, str]:
    faces: dict[str, str] = {}
    for command, path in shipped_templates(root):
        if path.suffix == ".html":
            faces[command] = faces.get(command, "") + path.read_text(encoding="utf-8")
    return faces


def _script_of(text: str, witness: str) -> str:
    """The one script of a face that holds `witness`."""
    found = [body for body in _SCRIPT.findall(text) if witness in body]
    assert len(found) == 1, f"{witness}: {len(found)} scripts"
    return found[0]


@pytest.mark.parametrize("command, witnesses", [
    ("audio", ("getElementById('card-level')", "media.removeAttribute('controls')",
               "IntersectionObserver")),
    ("reading", ("getElementById('card-level')", "kotogenViewer = {")),
])
def test_a_back_runs_again_the_scripts_of_its_front(root, command, witnesses):
    """Whether the scripts of `{{FrontSide}}` run again on the back is up to the
    client: the back carries those it needs, the same, and each leaves alone
    what one before it has done."""
    folder = root / command
    front = (folder / "front.html").read_text(encoding="utf-8")
    back = (folder / "back.html").read_text(encoding="utf-8").replace("{{FrontSide}}", "")
    for witness in witnesses:
        assert _script_of(back, witness) == _script_of(front, witness), witness
    # The shuffle too, up to what each face does with it.
    shuffle = [_script_of(text, "function shuffle()").split("\n  shuffle();")[0]
               .split("\n  var box = shuffle();")[0] for text in (front, back)]
    assert shuffle[0] == shuffle[1]


def test_both_grammar_faces_fit_the_gap_alike(root):
    """The gap shrinks, wraps and keeps its punctuation by the same rule on both
    faces, or the sentence moves when the card turns."""
    fits = [re.search(r"\n    function fit\(gap\) \{.*?\n    \}\n\n    // Fitted again.*?\n    \}\n"
                      r"\n    // The marks after the gap.*?\n    \}\n",
                      (root / "grammar" / face).read_text(encoding="utf-8"), re.S)
            for face in ("front.html", "back.html")]
    assert all(fits) and fits[0].group(0) == fits[1].group(0)
    assert "hold(gap);\n      follow(gap);" in (root / "grammar" / "front.html").read_text(
        encoding="utf-8")


def test_a_gap_too_long_to_shrink_wraps_inside_its_slot(root):
    """Under 60% a gap would not read: past that floor its slot breaks rather
    than run off the screen, on lines tall enough for the readings of the
    back, or a line with a kanji would grow on the back alone."""
    front = (root / "grammar" / "front.html").read_text(encoding="utf-8")
    fit = re.search(r"\n    function fit\(gap\) \{(.*?)\n    \}\n", front, re.S).group(1)
    assert 'gap.style.fontSize = Math.max(0.6, ratio) + "em";' in fit
    assert re.search(r'if \(ratio < 0\.6\) \{\s*gap\.classList\.add\("is-wrapped"\);'
                     r'\s*gap\.style\.maxWidth = free \+ "px";', fit)
    assert 'gap.classList.remove("is-wrapped");' in fit
    hold = re.search(r"\n    function hold\(gap\) \{(.*?)\n    \}\n", front, re.S).group(1)
    assert 'held.parentNode.insertBefore(document.createElement("wbr"), next);' in hold
    sheet = dict((", ".join(s), d) for s, d in _rules(
        (root / "grammar" / "style.css").read_text(encoding="utf-8")))
    wrapped = sheet[".grammar-statement .cloze.is-wrapped .grammar-slot"]
    assert wrapped["white-space"] == "normal" and float(wrapped["line-height"]) >= 1.8
    assert sheet[".grammar-held"]["white-space"] == "nowrap"


def test_the_meaning_under_the_gap_is_in_the_language_of_the_cards(root):
    """Hung inside the Japanese statement, it would be read by a Japanese voice:
    it is marked "unknown", as the reading card marks a translation line."""
    for face in ("front.html", "back.html"):
        text = (root / "grammar" / face).read_text(encoding="utf-8")
        assert re.search(r'under\.className = "grammar-under";\n(?:\s*//[^\n]*\n)*'
                         r'\s*under\.lang = "";', text), face


def test_the_typed_answer_is_framed_by_its_rule_alone(root):
    """Anki focuses its typing box on every front: the ring every other control
    wears, `!important` to outrank Anki desktop's, would frame the rule the box
    is drawn as. The box says its own focus, by a selector that outranks it."""
    card_templates.set_one("grammar.answer", "type")
    css = card_templates.render((root / "grammar" / "style.css").read_text(encoding="utf-8"),
                                "grammar")
    ring = _specificity(".card :focus-visible")
    exempt = [s for selectors, said in _rules(css) if said.get("outline") == "none !important"
              for s in selectors if s.endswith("input:focus-visible")]
    assert exempt and all(_specificity(s) > ring for s in exempt), exempt
    assert any(".grammar-typing" in s for s in exempt)


def test_the_place_held_for_the_translation_is_sized_as_its_button(root):
    """The front holds the place of the back's 訳 with a span, which is no
    button: sized as the buttons are (`box-sizing` of `templates/common.css`),
    or the pill is wider on the front and the text flowing round it wraps anew
    when the card turns."""
    front = (root / "reading" / "front.html").read_text(encoding="utf-8")
    assert '<span class="aid is-placeholder"' in front
    common = dict((", ".join(s), d) for s, d in _rules(
        (root / notetypes.COMMON_CSS).read_text(encoding="utf-8")))
    sheet = dict((", ".join(s), d) for s, d in _rules(
        (root / "reading" / "style.css").read_text(encoding="utf-8")))
    assert sheet[".card .aid"]["box-sizing"] == common[":where(.card) button"]["box-sizing"]


def test_no_script_names_a_value_after_one_of_its_functions(root):
    """A `var marked` inside a callback hides the function `marked()` there: it
    works until someone calls the function from that callback."""
    for where, body in _scripts(root):
        functions = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", body))
        values = set(re.findall(r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)", body))
        for parameters in re.findall(r"\bfunction\s*[\w$]*\s*\(([^)]*)\)", body):
            values |= {p.strip() for p in parameters.split(",") if p.strip()}
        assert not functions & values, f"{where}: {sorted(functions & values)}"


def test_the_player_stands_on_the_tag_line(root):
    """Fixed at the foot of the screen both, a player and a tag line wrapped on
    a phone would overlap: on a vocabulary back the script that reserves the
    room of the tags lifts the player above them."""
    card_templates.set_one("vocab.tags", "yes")
    for side in ("recognition", "production"):
        back = card_templates.render(
            (root / "vocab" / side / "back.html").read_text(encoding="utf-8"), "vocab")
        footer = _script_of(back, 'getElementById("tags")')
        assert 'querySelector(".vocab-player")' in footer
        assert "player.style.bottom = room +" in footer, side


# The void elements of HTML, which close themselves.
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "source", "track", "wbr"}
_JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")


class _Languages(HTMLParser):
    """The Japanese a card says in its own voice, and the language it says it in."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, str | None]] = []
        self.unmarked: list[str] = []

    def _language(self) -> str | None:
        return next((lang for _tag, lang in reversed(self.stack) if lang is not None), None)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        lang = attrs.get("lang")
        if tag not in _VOID:
            self.stack.append((tag, lang))
        for name in ("aria-label", "title", "alt"):
            said = attrs.get(name) or ""
            if _JAPANESE.search(said) and (lang or self._language()) != "ja":
                self.unmarked.append(said)

    def handle_endtag(self, tag):
        while self.stack:
            if self.stack.pop()[0] == tag:
                break

    def handle_data(self, data):
        if any(tag in ("script", "style") for tag, _lang in self.stack):
            return
        if _JAPANESE.search(data) and self._language() != "ja":
            self.unmarked.append(data.strip())


def test_every_japanese_sign_is_marked_japanese(root, monkeypatch):
    """再生, 全画面, ふ, 音, 構成...: what a card says in Japanese is marked so,
    read aloud by a Japanese voice and drawn in Japanese forms, whatever the
    language of the page around the card. Swept across every position."""
    for setting in card_templates.SETTINGS:
        for position in setting.positions:
            monkeypatch.setattr(choices, "values",
                                lambda key=setting.key, chosen=position: {key: chosen})
            for command, path in shipped_templates(root):
                if path.suffix != ".html":
                    continue
                reader = _Languages()
                reader.feed(_ASIDE.sub(" ", card_templates.render(
                    path.read_text(encoding="utf-8"), command)))
                assert not reader.unmarked, (
                    f"{path.parent.name}/{path.name} with {setting.key}={position}: "
                    f"{reader.unmarked}")


def test_a_choice_is_a_button_to_the_keyboard(root):
    """A choice is a <div>: it takes the focus, says it is pressed, and Enter
    and Space pick it, as they would press a button."""
    for command in ("audio", "reading"):
        front = (root / command / "front.html").read_text(encoding="utf-8")
        choices_laid = re.findall(r'<div class="choice"[^>]*>', front)
        assert choices_laid and all('tabindex="0"' in c and 'role="button"' in c
                                    and 'aria-pressed="false"' in c for c in choices_laid)
        picking = _script_of(front, "box.dataset.picking")
        assert "addEventListener('keydown'" in picking
        assert "setAttribute('aria-pressed'" in picking


def test_the_speed_says_itself_with_its_name(root):
    """An `aria-label` would hide the speed the button wears: its name is a
    hidden word inside it, read with the speed."""
    front = (root / "audio" / "front.html").read_text(encoding="utf-8")
    speed = re.search(r'<button type="button" class="player-speed"[^>]*>(.*?)</button>',
                      front).group(0)
    assert "aria-label" not in speed
    assert '<span class="visually-hidden">再生速度</span><span data-rate="1">1×</span>' in speed


def test_the_written_answer_is_its_text_alone(root):
    """No empty sign before it, which only pushed the answer aside."""
    for command in ("audio", "reading"):
        back = (root / command / "back.html").read_text(encoding="utf-8")
        answer = re.search(r'<div class="answer">(.*?)</div>', back, re.S).group(1)
        assert answer.strip() == '<span class="answer-text">{{furigana::Answer}}</span>'


# Classes that Anki or the browser lays, not a template.
_LAID_BY_ANKI = {"card", "nightMode", "night_mode", "cloze", "replay-button", "soundLink",
                 "typeGood", "typeBad", "typeMissed"}


def test_every_class_a_sheet_styles_is_laid_by_its_cards(root):
    """A rule for a class no face of the type lays, by markup or by script, is
    left over from a card that changed."""
    for spec in notetypes.SPECS:
        folders = [root / spec.directory / (sub or "") for _name, sub in spec.all_cards]
        faces = "".join((folder / name).read_text(encoding="utf-8")
                        for folder in folders for name in ("front.html", "back.html"))
        sheets = [root / notetypes.COMMON_CSS] + [folder / "style.css" for folder in folders]
        for sheet in sheets:
            css = re.sub(r"/\*.*?\*/", "", sheet.read_text(encoding="utf-8"), flags=re.S)
            styled = {name for selectors in re.findall(r"([^{}]+)\{", css)
                      for name in re.findall(r"(?<![\w-])\.([A-Za-z_][\w-]*)", selectors)}
            if sheet.name == notetypes.COMMON_CSS:
                faces_all = "".join(_faces_by_command(root).values())
                unused = {n for n in styled - _LAID_BY_ANKI
                          if not re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", faces_all)}
            else:
                unused = {n for n in styled - _LAID_BY_ANKI
                          if not re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", faces)}
            assert not unused, f"{sheet.parent.name}/{sheet.name}: {sorted(unused)}"


def test_a_template_writes_its_colons_the_english_way(root):
    """The templates print no prose and follow no language of the screens:
    their comments write a colon the English way (`≠ 〜たら: …`)."""
    comment = re.compile(r"<!--.*?-->|/\*.*?\*/|//[^\n]*", re.S)
    for _command, path in shipped_templates(root):
        for said in comment.findall(path.read_text(encoding="utf-8")):
            assert not re.search(r"\S :\s", said), f"{path.parent.name}/{path.name}: {said}"


def test_bold_japanese_may_be_drawn_by_the_browser(root):
    """A Japanese font with a single weight is made bold by the browser: a
    `font-synthesis` that leaves out the weight would print the answer of a
    gap, or the kanji picked out in a word, at the weight of the rest."""
    css = re.sub(r"/\*.*?\*/", "", (root / notetypes.COMMON_CSS).read_text(encoding="utf-8"),
                 flags=re.S)
    for value in re.findall(r"font-synthesis:\s*([^;]+);", css):
        assert "weight" in value or value.strip() == "initial", value


# ── What Anki desktop lays around a card ──────────────────────────────────────
# Anki desktop shows a card in a page of its own, whose sheets style the body
# and every button, the card's too. The card says its own again.

def test_the_card_keeps_its_ground_in_ankis_night_mode(root):
    """`body.nightMode` paints Anki's canvas and outranks `.card`: the card says
    its ground again under both night classes, or its text, measured against its
    own ground above, reads against Anki's."""
    css = (root / notetypes.COMMON_CSS).read_text(encoding="utf-8")
    rule = re.search(r"\.card\.nightMode,\s*\.card\.night_mode\s*\{([^}]*)\}", css)
    assert rule, "no rule over Anki's night canvas"
    assert "background-color: rgb(var(--background))" in rule.group(1)
    assert "color: rgb(var(--text))" in rule.group(1)


def test_a_card_button_starts_from_the_browsers(root):
    """What Anki desktop gives every button - margins, a padding, a weight, a
    box sized without its border, corners, a shadow, a font size per platform -
    goes back to what a browser gives one; the focus ring outranks the
    `outline: none !important` it lays too."""
    css = re.sub(r"/\*.*?\*/", "", (root / notetypes.COMMON_CSS).read_text(encoding="utf-8"),
                 flags=re.S)
    base = re.search(r":where\(\.card\) button \{([^}]*)\}", css).group(1)
    assert "box-sizing: border-box" in base and "margin: 0;" in base
    own = re.search(r"\n\.card button \{([^}]*)\}", css).group(1)
    for declaration in ("font-size: revert", "border-radius: revert", "box-shadow: none"):
        assert declaration in own
    states = re.search(r"\.card button:hover,\s*\.card button:active,\s*\.card button:disabled"
                       r" \{([^}]*)\}", css).group(1)
    assert "background-image: none" in states and "box-shadow: none" in states
    assert "!important" in re.search(r"\.card :focus-visible \{([^}]*)\}", css).group(1)


# What Anki desktop sets on a button above the weight of one class (`.isWin
# button`, `.fancy button`, `button:hover`...): a rule of a card that says one
# of these for a button has to outrank it.
_ANKI_OUTRANKS = ("font", "border", "background", "color", "cursor", "box-shadow")


def _button_classes(root) -> set[str]:
    """The classes of every button the templates lay, in markup or by script."""
    found: set[str] = set()
    for text in _faces_by_command(root).values():
        for value in re.findall(r'<button[^>]*\bclass="([^"]+)"', text):
            found |= set(value.split())
        for made in re.finditer(r"createElement\((['\"])button\1\);(?:\n[^\n]*){0,3}?"
                                r"\.className = (['\"])([^'\"]+)\2", text):
            found |= set(made.group(3).split())
    return found


def _specificity(selector: str) -> tuple[int, int, int]:
    """(ids, classes, types) of a selector; `:where()` weighs nothing."""
    plain = re.sub(r":where\([^)]*\)", "", selector).replace(":not(", "(")
    plain = re.sub(r"\[[^\]]*\]", "[]", plain)
    classes = len(re.findall(r"\.[\w-]|\[\]|(?<!:):[\w-]", plain))
    types = len(re.findall(r"(?:^|[\s>+~(])[a-zA-Z][\w-]*|::[\w-]", plain))
    return plain.count("#"), classes, types


def test_a_rule_for_a_button_outranks_ankis(root):
    """`.isWin button` (0,1,1) sets 12px on Windows, above `.aid` (0,1,0); the
    rules of the card for its buttons are written under `.card`."""
    buttons = _button_classes(root)
    assert {"aid", "play-btn", "jump-btn", "vocab-forms", "grammar-reveal",
            "player-tick"} <= buttons
    weak = []
    for command, path in shipped_templates(root):
        if path.suffix != ".css" or command == card_templates.GLOBAL:
            continue
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            said = {d.split(":")[0].strip() for d in body.split(";") if ":" in d}
            if not any(p == name or p.startswith(name + "-")
                       for p in said for name in _ANKI_OUTRANKS):
                continue
            for selector in (s.strip() for s in selectors.split(",")):
                subject = re.split(r"[\s>+~]+", selector)[-1]
                if "::" in subject or not set(re.findall(r"\.([\w-]+)", subject)) & buttons:
                    continue
                if _specificity(selector) <= (0, 1, 1):
                    weak.append(f"{path.parent.name}/{path.name}: {selector}")
    assert not weak, weak


@pytest.mark.parametrize("palette", ["dark", "light", "auto"])
def test_the_full_screen_book_is_dark_in_every_palette(root, palette):
    """Black like an image reader: the book takes there the one rule that writes
    the dark colours, which every palette keeps, and its counter, its key page
    and the readings of its question read at the AA ratio on black. The sheets
    name a class the script lays, never `:fullscreen`: a WebView that refuses a
    selector drops its whole rule, the dark palette with it."""
    card_templates.set_one("all.palette", palette)
    common = card_templates.render((root / notetypes.COMMON_CSS).read_text(encoding="utf-8"),
                                   card_templates.GLOBAL)
    taken = next(said for selectors, said in _rules(common) if ".is-full-screen" in selectors)
    dark = _palette(root, "dark")
    assert taken["color-scheme"] == "dark"
    assert {name: tuple(int(c) for c in taken["--" + name].split(",")) for name in dark} == dark
    for _command, path in shipped_templates(root):
        if path.suffix == ".css":
            assert ":fullscreen" not in path.read_text(encoding="utf-8"), path
    reading = (root / "reading" / "style.css").read_text(encoding="utf-8")
    assert not set(re.findall(r"--([\w-]+):", reading)) & set(dark)
    for face in ("front.html", "back.html"):
        viewer = _script_of((root / "reading" / face).read_text(encoding="utf-8"),
                            "kotogenViewer = {")
        assert "book.classList.toggle('is-full-screen', on)" in viewer, face
    black = (0, 0, 0)
    key_page = tuple(0.14 * c for c in dark["correct"])
    for name, paper in (("text-soft", black), ("text-subtle", black), ("correct", key_page)):
        assert _contrast(dark[name], paper) >= 4.5, name


@pytest.mark.parametrize("palette, schemes", [
    ("dark", {".card": "dark"}),
    ("light", {".card": "light"}),
    ("auto", {".card": "light", ".card.nightMode": "dark", ".card.night_mode": "dark"}),
])
def test_each_palette_says_its_scheme_on_the_card(root, palette, schemes):
    """Anki desktop's night mode sets `color-scheme: dark` on `:root.night-mode`,
    above `:root`: said there alone, a light card would draw its native controls
    (the audio player, the input box, a button left to the browser) dark."""
    card_templates.set_one("all.palette", palette)
    common = card_templates.render((root / notetypes.COMMON_CSS).read_text(encoding="utf-8"),
                                   card_templates.GLOBAL)
    said = {}
    for selectors, declarations in _rules(common):
        if "color-scheme" in declarations:
            for selector in selectors:
                said[selector] = declarations["color-scheme"]
    assert {s: v for s, v in said.items() if s.startswith(".card")} == schemes


def test_a_one_kanji_suru_verb_is_told_on_its_written_form(root):
    """In kana, 愛する shows as あいする: the forms are chosen on the word as the
    note writes it, never on what the card shows of it."""
    back = (root / "vocab" / "recognition" / "back.html").read_text(encoding="utf-8")
    suru = re.search(r"var stem = (.*?);\n\s*if \(/\^\[㐀-鿿\]\$/\.test\(stem\)\)", back)
    assert suru and suru.group(1) == "kanji.slice(0, -2)"


def test_aru_draws_no_potential(root):
    """ある has no potential in use: the strip draws a dash, not あれる."""
    back = (root / "vocab" / "recognition" / "back.html").read_text(encoding="utf-8")
    branch = re.search(r'if \(ends\(kanji, \["ある", "有る", "在る"\]\)\) \{(.*?)\n      \}',
                       back, re.S)
    assert branch and 'forms[3].ending = "";' in branch.group(1)


def test_the_tag_line_keeps_its_room_on_every_back(root):
    """The line of tags is fixed at the foot of the screen: each back that lays
    it keeps the room it takes under the end of the card."""
    for command, card in (("vocab", "vocab-card"), ("grammar", "grammar-card"),
                          ("kanji", "kanji-card")):
        card_templates.set_one(f"{command}.tags", "yes")
        for _cmd, path in shipped_templates(root):
            if _cmd != command or path.name != "back.html":
                continue
            out = card_templates.render(path.read_text(encoding="utf-8"), command)
            footer = _script_of(out, 'getElementById("tags")')
            assert f'getElementById("{card}")' in footer and "paddingBottom" in footer


def test_the_kanji_card_marks_its_japanese_inside_a_sentence(root):
    """A look-alike or a composition is a sentence in the language of the cards
    with kanji in it: the script marks those Japanese, the card being about
    their shape."""
    back = (root / "kanji" / "recognition" / "back.html").read_text(encoding="utf-8")
    for field in ("Composition", "LookAlikes"):
        assert f'<span class="aside-text" data-mixed>{{{{{field}}}}}</span>' in back
    marking = _script_of(back, "data-mixed")
    assert 'run.lang = "ja"' in marking


# ── In a browser ──────────────────────────────────────────────────────────────
# What shows only when a card runs, in Chromium (the `[nhk]` extra's: skipped
# without it), in one page kept from card to card as Anki desktop keeps it. Its
# `_updateQA` lays the HTML, runs the scripts again, and sets the classes of the
# body only once they have run: on the first card of a session the body is not
# `.card` yet while they measure.

# What Anki desktop's own sheets (webview.css, reviewer.css) set on the page a
# card is shown in, as Anki 25 writes them: the body and every button.
ANKI_DESKTOP_CSS = """
:root { --fg: #020202; --fg-disabled: #858585; --canvas: #f5f5f5; --border: #c4c4c4;
  --border-subtle: #e4e4e4; --shadow: #c4c4c4; --button-bg: #fcfcfc;
  --button-gradient-start: white; --button-gradient-end: #fcfcfc;
  --border-radius: 5px; --border-radius-large: 15px; --transition: 180ms;
  color-scheme: light; }
:root.night-mode { --fg: #fcfcfc; --fg-disabled: #737373; --canvas: #2c2c2c;
  --border: #202020; --border-subtle: #252525; --shadow: #141414;
  --button-bg: rgb(64, 64, 64); --button-gradient-start: rgb(74, 74, 74);
  --button-gradient-end: rgb(64, 64, 64); color-scheme: dark; }
.isWin button { font-size: 12px; }
.isMac button { font-size: 13px; }
button { outline: none !important; background: var(--button-bg);
  border-radius: var(--border-radius); border: 1px solid var(--border-subtle); }
button:hover { background: var(--button-gradient-start); border: 1px solid var(--border); }
button { font-weight: 500; padding: 8px 10px; margin: 0 4px; -webkit-appearance: none;
  cursor: pointer; border: 1px solid var(--border-subtle);
  border-bottom-color: var(--shadow); background: var(--button-bg); }
button:hover { background: linear-gradient(180deg, var(--button-gradient-start) 0%,
  var(--button-gradient-end) 100%); border: 1px solid var(--shadow); }
button { color: var(--fg); }
button:active { box-shadow: inset 0 calc(var(--buttons-size, 10px) / 15)
  calc(var(--buttons-size, 10px) / 5) rgba(0, 0, 0, .35); border-color: var(--border-subtle); }
button[disabled], button[disabled]:hover { cursor: not-allowed; color: var(--fg-disabled);
  box-shadow: none !important; background: var(--button-gradient-end);
  border-bottom-color: var(--border-subtle); }
.fancy button { border-radius: var(--border-radius-large); box-shadow: 0px 2px 1px -1px
  rgba(20, 20, 20, .12), 0px 1px 1px 0px rgba(20, 20, 20, .06), 0px 1px 3px 0px rgba(20, 20, 20, .04); }
.fancy button:hover { box-shadow: 0px 3px 1px -2px rgba(20, 20, 20, .2), 0px 2px 2px 0px
  rgba(20, 20, 20, .14), 0px 1px 5px 0px rgba(20, 20, 20, .12);
  transition: box-shadow var(--transition) linear; }
* { box-sizing: content-box; }
body { color: var(--fg); background: var(--canvas); margin: 2em; }
body { margin: 20px; overflow-wrap: break-word; }
body.nightMode { background-color: var(--canvas); color: var(--fg); }
button { margin: 1em .5em; }
img { max-width: 100%; max-height: 95vh; }
"""

_SHELL = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{sheet}</head>
<body class="isWin fancy"><div id="qa"></div><script>
window.errors = [];
window.addEventListener("error", function (e) { window.errors.push(String(e.message)); });
function show(html, classes) {
  var qa = document.getElementById("qa");
  qa.innerHTML = html;
  Array.prototype.slice.call(qa.getElementsByTagName("script")).forEach(function (old) {
    var fresh = document.createElement("script");
    fresh.textContent = old.textContent;
    old.parentNode.replaceChild(fresh, old);
  });
  // Anki desktop sets the classes once its update hooks are awaited: after the
  // promises the scripts settled on the spot (`document.fonts.ready`).
  return new Promise(function (done) {
    setTimeout(function () { document.body.className = classes; done(); }, 0);
  });
}
</script></body></html>"""

_DAY = "card card1 isWin fancy"
_NIGHT = _DAY + " nightMode night_mode"


@pytest.fixture(scope="module")
def chromium():
    """Playwright's Chromium, or the test is skipped."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as exc:  # Playwright installed, its browser not downloaded
            pytest.skip(f"Chromium does not start: {exc}")
        yield browser
        browser.close()


def _faces(root, key: str, card: str, fields: dict[str, str] | None = None,
           bare_front: bool = False) -> tuple[str, str]:
    """The front and the back of a card of a preview sample, at the settings of
    the profile, its sheet laid at their head. `bare_front` lays the front on
    the back without its scripts, as a client that does not run them again."""
    sample = preview.samples((key,))[0]
    spec = next(s for s in notetypes.SPECS if s.command == sample.command)
    rendered, css = notetypes.read_templates(spec, root)
    values = {**sample.fields, **(fields or {})}
    front = preview.render(rendered[card]["Front"], values, front=True)
    laid = re.sub(r"<script>.*?</script>", "", front, flags=re.S) if bare_front else front
    back = preview.render(rendered[card]["Back"].replace("{{FrontSide}}", laid), values,
                          front=False)
    style = f"<style>{css}</style>"
    return style + front, style + back


def _anki(chromium, *, sheets: bool = True, width: int = 390, night: bool = False):
    """A page of Anki desktop's reviewer, no card in it yet."""
    page = chromium.new_page(viewport={"width": width, "height": 760})
    sheet = f"<style>{ANKI_DESKTOP_CSS}</style>" if sheets else ""
    page.set_content(_SHELL.replace("{sheet}", sheet))
    if night:
        page.evaluate("document.documentElement.className = 'night-mode'")
    return page


def _show(page, html: str, classes: str = _DAY, wait: int = 300) -> list[str]:
    """One face on the page, as Anki desktop shows it; the errors it raised."""
    page.evaluate("([html, classes]) => { window.errors = []; show(html, classes); }",
                  [html, classes])
    page.wait_for_timeout(wait)
    return page.evaluate("window.errors")


# What a button looks like, as far as Anki desktop's sheets could change it.
_BUTTON_LOOK = """(state) => Array.from(document.querySelectorAll('#qa button'))
    .filter(b => !state || !b.disabled).map(b => {
  const s = getComputedStyle(b), r = b.getBoundingClientRect();
  return [b.className, s.marginTop, s.marginRight, s.marginBottom, s.marginLeft,
          s.paddingTop, s.paddingRight, s.paddingBottom, s.paddingLeft, s.fontSize,
          s.fontWeight, s.borderTop, s.borderRight, s.borderBottom, s.borderLeft,
          s.borderTopLeftRadius, s.borderTopRightRadius, s.borderBottomLeftRadius,
          s.borderBottomRightRadius, s.backgroundColor, s.backgroundImage, s.boxShadow,
          s.boxSizing, s.color, s.cursor, Math.round(r.width), Math.round(r.height)].join(' | ');
})"""


def _looks(page, state: str | None) -> list[str]:
    """The look of every button of the card, `state` (hover, active) forced on each.

    A disabled button takes no pointer (`pointer-events: none`): it is looked
    at only at rest.
    """
    if state is None:
        return page.evaluate(_BUTTON_LOOK, None)
    cdp = page.context.new_cdp_session(page)
    cdp.send("DOM.enable")
    cdp.send("CSS.enable")
    document = cdp.send("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
    nodes = cdp.send("DOM.querySelectorAll", {"nodeId": document, "selector": "#qa button"})
    for node in nodes["nodeIds"]:
        cdp.send("CSS.forcePseudoState", {"nodeId": node, "forcedPseudoClasses": [state]})
    looks = page.evaluate(_BUTTON_LOOK, state)
    for node in nodes["nodeIds"]:
        cdp.send("CSS.forcePseudoState", {"nodeId": node, "forcedPseudoClasses": []})
    cdp.detach()
    return looks


@pytest.mark.parametrize("key, card, settings, fields", [
    ("vocab", "Recognition", {}, None),
    ("grammar", "Grammar", {"grammar.translation": "on-click"}, None),
    ("grammar", "Grammar", {"grammar.translation": "on-click"}, {"Target": ""}),
    ("audio", "Listening", {}, None),
    ("reading", "Reading", {}, None),
    ("reading-book", "Reading", {}, None),
    ("reading-document", "Reading", {}, None),
])
def test_ankis_own_sheets_change_nothing_on_a_card(root, chromium, key, card, settings, fields):
    """Laid in Anki desktop's page, every button of the card looks as it does on
    a bare page, at rest, hovered and pressed, and the card keeps its ground in
    night mode. Only the transition of a hovered button is Anki's: the looks are
    taken with none, at once."""
    for name, value in settings.items():
        card_templates.set_one(name, value)
    anki, bare = _anki(chromium, night=True), _anki(chromium, sheets=False, night=True)
    buttons = 0
    for face in _faces(root, key, card, fields):
        for page in (anki, bare):
            assert _show(page, face, _NIGHT) == []
            page.add_style_tag(content="* { transition: none !important; }")
        buttons += anki.evaluate("document.querySelectorAll('#qa button').length")
        for state in (None, "hover", "active"):
            assert _looks(anki, state) == _looks(bare, state), state
        ground = "[getComputedStyle(document.body).backgroundColor, getComputedStyle(document.body).color]"
        assert anki.evaluate(ground) == bare.evaluate(ground)
    assert buttons, "not one button on the card: the test proves nothing"
    anki.close()
    bare.close()


@pytest.mark.parametrize("palette", ["dark", "light", "auto"])
def test_the_ground_of_the_card_is_its_palettes_in_ankis_night_mode(root, chromium, palette):
    card_templates.set_one("all.palette", palette)
    page = _anki(chromium, night=True)
    _show(page, _faces(root, "kanji", "Recognition")[0], _NIGHT)
    ground = page.evaluate("getComputedStyle(document.body).backgroundColor")
    expected = _palette(root, "dark" if palette == "auto" else palette)["background"]
    assert ground == "rgb({}, {}, {})".format(*expected)
    page.close()


def _rgb(colour: tuple[int, ...]) -> str:
    return "rgb({}, {}, {})".format(*colour)


@pytest.mark.parametrize("player", ["drawn", "native"])
def test_a_light_card_stays_light_in_ankis_night_mode(root, chromium, player):
    """Anki desktop's night mode says `color-scheme: dark` above `:root`: a light
    card draws its native player, and the buttons it leaves to the browser, as
    it does by day."""
    card_templates.set_one("all.palette", "light")
    card_templates.set_one("audio.player", player)
    faces = _faces(root, "audio", "Listening",
                   {"Audio": f'<audio controls src="{_silence()}"></audio>'})
    day, night = _anki(chromium), _anki(chromium, night=True)
    schemes = ("[...new Set(Array.from(document.querySelectorAll('#qa, #qa *'))"
               ".map(e => getComputedStyle(e).colorScheme))]")
    for face in faces:
        assert _show(day, face) == [] and _show(night, face, _NIGHT) == []
        for page in (day, night):
            page.add_style_tag(content="* { transition: none !important; }")
        assert night.evaluate(schemes) == day.evaluate(schemes) == ["light"]
        assert _looks(night, None) == _looks(day, None)
    day.close()
    night.close()


@pytest.mark.parametrize("palette", ["light", "auto"])
def test_the_book_is_dark_in_full_screen_in_every_palette(root, chromium, palette):
    """Whichever way full screen is reached, the book wears the class the dark
    colours open on, and leaves it with full screen."""
    card_templates.set_one("all.palette", palette)
    front, _back = _faces(root, "reading-book", "Reading")
    page = _anki(chromium)
    _show(page, front)
    book = "document.getElementById('minibook-container')"
    ink = "getComputedStyle(document.querySelector('.page-counter')).color"
    page.click(".fullscreen-btn")
    page.wait_for_timeout(200)
    assert page.evaluate(f"{book}.classList.contains('is-full-screen')")
    assert page.evaluate(ink) == _rgb(_palette(root, "dark")["text-soft"])
    assert page.evaluate(f"getComputedStyle({book}).backgroundColor") == "rgb(0, 0, 0)"
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert not page.evaluate(f"{book}.classList.contains('is-full-screen')")
    assert page.evaluate(ink) == _rgb(_palette(root, "light")["text-soft"])
    page.close()


# The size of the pill of a reading card, and the first character of each line
# of the text flowing round it.
_PILL_AND_LINES = """() => {
  const pill = document.querySelector('.text-aids').getBoundingClientRect();
  const text = document.getElementById('japanese-text');
  const walker = document.createTreeWalker(text, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  const starts = [];
  let node, top = null;
  while ((node = walker.nextNode())) {
    for (let i = 0; i < node.length; i++) {
      range.setStart(node, i);
      range.setEnd(node, i + 1);
      const box = range.getBoundingClientRect();
      if (box.width && (top === null || Math.abs(box.top - top) > 4)) {
        top = box.top;
        starts.push(node.data[i]);
      }
    }
  }
  return [Math.round(pill.width), Math.round(pill.height), starts.join('')];
}"""


@pytest.mark.parametrize("width", [320, 390])
def test_the_text_of_a_reading_card_wraps_the_same_on_both_faces(root, chromium, width):
    """The front holds the place of the back's 訳: the pill is as large on both
    faces, and the text flowing round it breaks at the same places."""
    front, back = _faces(root, "reading", "Reading")
    page = _anki(chromium, width=width)
    assert _show(page, front) == []
    before = page.evaluate(_PILL_AND_LINES)
    assert _show(page, back) == []
    assert page.evaluate(_PILL_AND_LINES) == before
    page.close()


def test_the_typed_answer_wears_its_rule_and_a_button_its_ring(root, chromium):
    card_templates.set_one("grammar.answer", "type")
    card_templates.set_one("grammar.translation", "on-click")
    front, _back = _faces(root, "grammar", "Grammar")
    page = _anki(chromium)
    assert _show(page, front) == []
    look = ("(s) => { const c = getComputedStyle(document.querySelector(s));"
            " return [c.outlineStyle, c.outlineWidth, c.borderBottomColor]; }")
    page.focus("#typeans")
    style, _width, rule = page.evaluate(look, "#typeans")
    assert style == "none" and rule == _rgb(_palette(root, "dark")["accent"])
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("document.activeElement.classList.contains('grammar-reveal')")
    assert page.evaluate(look, ".grammar-reveal")[:2] == ["solid", "2px"]
    page.close()


def test_the_meaning_under_the_gap_is_in_no_language_the_card_knows(root, chromium):
    page = _anki(chromium)
    for face in _faces(root, "grammar", "Grammar"):
        _show(page, face)
        assert page.evaluate("document.querySelector('.grammar-under')"
                             ".closest('[lang]').getAttribute('lang')") == ""
    page.close()


# Whether the page runs off to the side, and where the gap and the comma after
# it lie.
_GAP = """() => {
  const gap = document.querySelector('.grammar-statement .cloze');
  const range = document.createRange();
  range.setStart(gap.nextSibling, 0);
  range.setEnd(gap.nextSibling, 1);
  const statement = document.querySelector('.grammar-statement').getBoundingClientRect();
  return {wide: document.documentElement.scrollWidth > document.documentElement.clientWidth,
          wrapped: gap.classList.contains('is-wrapped'), mark: gap.nextSibling.data[0],
          beside: range.getBoundingClientRect().left >= gap.getBoundingClientRect().right - 1,
          height: Math.round(statement.height * 10) / 10};
}"""


@pytest.mark.parametrize("width", [320, 390])
def test_a_gap_too_long_for_the_line_wraps_rather_than_run_off(root, chromium, width):
    """Past the smallest size it shrinks to, the gap breaks inside its slot, the
    comma after it stays on its line, and the sentence is as tall on both
    faces: a kanji on its second line takes no more room on the back."""
    long = {"Sentence": " 駅[えき]に{{c1:: 行[い]かなければならなかったのに 間[ま]に"
                        " 合[あ]わなかった}}、 先生[せんせい]に 怒[おこ]られた。",
            "Answer": "行かなければならなかったのに間に合わなかった", "Hint": " 行[い]く"}
    page = _anki(chromium, width=width)
    seen = []
    for face in _faces(root, "grammar", "Grammar", long):
        assert _show(page, face) == []
        seen.append(page.evaluate(_GAP))
    for gap in seen:
        assert gap["wrapped"] and not gap["wide"] and gap["mark"] == "、" and gap["beside"], gap
    assert seen[0]["height"] == seen[1]["height"]
    page.close()


def test_the_sentence_breaks_after_the_punctuation_of_the_gap(root, chromium):
    """The comma held to the gap is no reason to break before it: 雨が and the
    gap share their line, the rest of the sentence goes to the next."""
    page = _anki(chromium)
    for face in _faces(root, "grammar", "Grammar"):
        assert _show(page, face) == []
        lines = page.evaluate("""() => {
          const line = e => [Math.round(e.getBoundingClientRect().top),
                             Math.round(e.getBoundingClientRect().bottom)];
          const gap = document.querySelector('.grammar-statement .cloze');
          const words = Array.from(document.querySelectorAll('.grammar-statement ruby'))
            .filter(r => !gap.contains(r));
          return [line(words[0]), line(gap), line(words[1])];
        }""")
        first, gap, after = lines
        assert first[0] < gap[1] and gap[0] < first[1], lines
        assert after[0] >= first[1] - 1, lines
    page.close()


def test_the_player_and_the_tag_line_never_overlap(root, chromium):
    card_templates.set_one("vocab.tags", "yes")
    tags = " ".join(["Level::N4", "Register::敬語::謙譲語", "Verb::一段動詞",
                     "Source::NHK_Web_Easy", "Theme::travel_and_transport", "kotogen"])
    player = ('<a class="replay-button soundLink" href="#"><svg viewBox="0 0 64 64">'
              '<circle cx="32" cy="32" r="29"></circle></svg></a>')
    _front, back = _faces(root, "vocab", "Recognition", {"Tags": tags, "Audio": player})
    page = _anki(chromium, width=320)
    page.set_viewport_size({"width": 320, "height": 600})
    assert _show(page, back) == []
    boxes = page.evaluate("""() => {
      window.scrollTo(0, document.documentElement.scrollHeight);
      const box = s => document.querySelector(s).getBoundingClientRect();
      let last = document.getElementById('vocab-card').lastElementChild;
      while (last && !last.offsetHeight) last = last.previousElementSibling;
      return {player: box('.vocab-player'), tags: box('.tags-footer'),
              end: last.getBoundingClientRect().bottom};
    }""")
    assert boxes["player"]["bottom"] <= boxes["tags"]["top"]
    assert boxes["end"] <= boxes["player"]["top"]
    page.close()


def test_a_book_rated_at_once_leaves_the_next_card_at_its_first_page(root, chromium):
    """The back turns the book to its key page 150 ms after it shows: rated
    within them, the next card's front stays where its own card opens it."""
    front, back = _faces(root, "reading-book", "Reading")
    page = _anki(chromium)
    _show(page, back, wait=400)
    page_of = "document.getElementById('current-page').textContent"
    marked = "document.getElementById('minibook-container').classList.contains('at-key-page')"
    assert page.evaluate(page_of) == "2" and page.evaluate(marked)
    _show(page, back, wait=40)
    assert _show(page, front, wait=400) == []
    assert page.evaluate(page_of) == "1" and not page.evaluate(marked)
    page.close()


@pytest.mark.parametrize("key, check", [
    ("reading-book", "book"), ("reading-document", "furigana"), ("audio", "player"),
])
def test_a_back_whose_front_scripts_do_not_run_again_still_works(root, chromium, key, check):
    """A client may lay the front on the back without running its scripts: the
    back's own make the badge, the shuffle, the player, the book and the ふ."""
    card = "Listening" if key == "audio" else "Reading"
    _front, back = _faces(root, key, card, bare_front=True)
    page = _anki(chromium)
    assert _show(page, back, wait=400) == []
    assert page.evaluate("document.getElementById('card-level').textContent") == "N4"
    assert page.evaluate("document.querySelector('.choices-container').classList"
                         ".contains('is-revealed')")
    if check == "book":
        counter = "document.querySelector('.page-counter').textContent.replace(/\\s+/g, ' ').trim()"
        assert page.evaluate(counter) == "2 / 3"
        page.click("#next-btn")
        assert page.evaluate(counter) == "3 / 3"
    elif check == "furigana":
        page.click("#furigana-btn")
        assert page.evaluate("window.errors") == []
        assert page.get_attribute("#furigana-btn", "aria-pressed") == "true"
    else:
        assert page.evaluate("document.querySelector('.audio-player').classList.contains('is-drawn')")
    page.close()


def test_aru_takes_no_form_nobody_says(root, chromium):
    """No あらない and no あれる: the negative is ない, and the potential a dash."""
    _front, back = _faces(root, "vocab", "Recognition",
                          {"Expression": " 有[あ]る", "Tags": "Verb::五段動詞"})
    page = _anki(chromium)
    assert _show(page, back) == []
    forms = page.evaluate("Array.from(document.querySelectorAll('.vocab-form-word'))"
                          ".map(f => f.textContent)")
    assert forms[0] == "ない" and forms[3] == "-"
    page.close()


@pytest.mark.parametrize("expression, potential", [
    (" 愛[あい]する", "あいせる"), (" 関[かん]する", "-"), (" 属[ぞく]する", "ぞくしうる"),
])
def test_a_one_kanji_suru_verb_conjugates_on_its_kanji_in_kana(root, chromium, expression,
                                                                potential):
    card_templates.set_one("vocab.furigana", "kana")
    _front, back = _faces(root, "vocab", "Recognition",
                          {"Expression": expression, "Tags": "Verb::不規則動詞"})
    page = _anki(chromium)
    assert _show(page, back) == []
    forms = page.evaluate("Array.from(document.querySelectorAll('.vocab-form-word'))"
                          ".map(f => f.textContent)")
    assert forms[3] == potential
    page.close()


def _fit(page) -> str:
    return page.evaluate("document.querySelector('.vocab-word').style.getPropertyValue('--fit')")


def test_a_long_word_fits_the_same_on_the_first_card_of_a_session(root, chromium):
    """On the first card the scripts measure a page not styled yet: the word is
    fitted again once it is, and again when the screen turns."""
    word = {"Expression": "アイスクリームパーラーチェーン", "Tags": "Noun"}
    front, back = _faces(root, "vocab", "Recognition", word)
    page = _anki(chromium, width=700)
    _show(page, front, wait=400)
    first = _fit(page)
    _show(page, front, wait=400)
    assert first and _fit(page) == first
    _show(page, back, wait=400)
    assert _fit(page) == first
    page.set_viewport_size({"width": 390, "height": 760})
    page.wait_for_timeout(300)
    turned = _fit(page)
    _show(page, back, wait=400)
    assert turned != first and _fit(page) == turned
    page.close()


def test_the_forms_fit_again_when_the_screen_turns(root, chromium):
    """申し上げられる shrinks the strip on a phone held upright, and not across."""
    _front, back = _faces(root, "vocab", "Recognition")
    page = _anki(chromium, width=700)
    strip = "document.getElementById('vocab-forms').style.getPropertyValue('--fit')"
    _show(page, back)
    assert page.evaluate(strip) == ""
    page.set_viewport_size({"width": 320, "height": 760})
    page.wait_for_timeout(300)
    turned = page.evaluate(strip)
    _show(page, back)
    assert turned and page.evaluate(strip) == turned
    page.close()


def test_the_gap_fits_the_same_on_the_first_card_of_a_session(root, chromium):
    long = {"Sentence": " 先生[せんせい]が{{c1:: 召[め]し 上[あ]がっていらっしゃいました}}。",
            "Answer": "召し上がっていらっしゃいました", "Hint": " 食[た]べる"}
    front, _back = _faces(root, "grammar", "Grammar", long)
    page = _anki(chromium)
    size = "document.querySelector('.grammar-statement .cloze').style.fontSize"
    _show(page, front, wait=400)
    first = page.evaluate(size)
    _show(page, front, wait=400)
    assert first and page.evaluate(size) == first
    page.close()


def test_the_translation_on_click_moves_nothing_when_the_card_turns(root, chromium):
    """With no meaning to hang under the gap, the pill waits where the
    translation will show: the sentence is as tall on both faces."""
    card_templates.set_one("grammar.translation", "on-click")
    page = _anki(chromium)
    where = "JSON.stringify(document.querySelector('.grammar-statement').getBoundingClientRect())"
    for target in ("", None):
        front, back = _faces(root, "grammar", "Grammar",
                             {"Target": target} if target is not None else None)
        _show(page, front)
        before = page.evaluate(where)
        _show(page, back)
        assert page.evaluate(where) == before, repr(target)
    page.close()


def _silence(seconds: int = 3) -> str:
    """A sound the browser can play, made here: no medium to fetch."""
    import base64
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(8000)
        sound.writeframes(b"\0\0" * 8000 * seconds)
    return "data:audio/wav;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_the_player_and_the_choices_answer_the_keyboard(root, chromium):
    front, _back = _faces(root, "audio", "Listening",
                          {"Audio": f'<audio controls src="{_silence()}"></audio>'})
    page = _anki(chromium)
    assert _show(page, front, wait=600) == []
    assert page.get_attribute(".player-track", "aria-valuemax") == "3"
    page.focus(".player-track")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(100)
    assert page.get_attribute(".player-track", "aria-valuenow") == "3"
    page.keyboard.press("Home")
    page.wait_for_timeout(100)
    assert page.get_attribute(".player-track", "aria-valuenow") == "0"
    page.focus(".choice")
    page.keyboard.press("Space")
    assert page.get_attribute(".choice", "aria-pressed") == "true"
    assert page.evaluate("document.querySelector('.choice').classList.contains('is-picked')")
    page.close()


def test_the_book_says_when_it_is_in_full_screen(root, chromium):
    front, _back = _faces(root, "reading-book", "Reading")
    page = _anki(chromium)
    _show(page, front)
    page.click(".fullscreen-btn")
    page.wait_for_timeout(200)
    assert page.get_attribute(".fullscreen-btn", "aria-pressed") == "true"
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    assert page.get_attribute(".fullscreen-btn", "aria-pressed") == "false"
    page.close()


def test_the_counter_says_nothing_before_the_pages_are_counted(root, chromium):
    """Not `1 / 0` while the viewer waits for its pages, nor ever for a book
    with no picture in it."""
    front, _back = _faces(root, "reading-book", "Reading")
    page = _anki(chromium)
    seen = "getComputedStyle(document.querySelector('.page-jump')).visibility"
    _show(page, front, wait=0)
    assert page.evaluate(seen) == "hidden"
    page.wait_for_timeout(300)
    assert page.evaluate(seen) == "visible"
    empty, _back = _faces(root, "reading-book", "Reading", {"Images": "頁"})
    _show(page, empty)
    assert page.evaluate("getComputedStyle(document.querySelector('.minibook-controls'))"
                         ".display") == "none"
    page.close()


def test_the_keys_of_the_book_leave_a_field_and_the_scroll_alone(root, chromium):
    """An arrow typed into a field moves its caret, and Home and End scroll the
    card, except in full screen, where they open the book at either end."""
    front, _back = _faces(root, "reading-book", "Reading")
    page = _anki(chromium)
    _show(page, front)
    page.evaluate("""() => {
      var field = document.createElement('input');
      field.id = 'field';
      document.getElementById('qa').appendChild(field);
      window.kept = [];
      window.addEventListener('keydown', function (e) { window.kept.push(e.defaultPrevented); });
    }""")
    counter = "document.getElementById('current-page').textContent"
    page.focus("#field")
    page.keyboard.press("ArrowRight")
    assert page.evaluate(counter) == "1"
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("ArrowRight")
    assert page.evaluate(counter) == "2"
    page.keyboard.press("Home")
    assert page.evaluate(counter) == "2" and page.evaluate("window.kept") == [False, True, False]
    page.click(".fullscreen-btn")
    page.wait_for_timeout(200)
    page.keyboard.press("Home")
    assert page.evaluate(counter) == "1"
    page.close()


@pytest.mark.parametrize("key, card, box", [
    ("vocab", "Recognition", "vocab-card"), ("grammar", "Grammar", "grammar-card"),
    ("kanji", "Recognition", "kanji-card"),
])
def test_the_tag_line_never_covers_the_end_of_a_back(root, chromium, key, card, box):
    """Several tags wrap on a phone: the back keeps the room of every line."""
    card_templates.set_one(f"{key}.tags", "yes")
    tags = " ".join(["Level::N4", "Register::敬語::謙譲語", "Verb::一段動詞",
                     "Source::NHK_Web_Easy", "Theme::travel_and_transport", "kotogen"])
    _front, back = _faces(root, key, card, {"Tags": tags})
    page = _anki(chromium)
    assert _show(page, back) == []
    room = page.evaluate(f"parseFloat(getComputedStyle(document.getElementById('{box}'))"
                         ".paddingBottom)")
    line = page.evaluate("document.querySelector('.tags-footer').offsetHeight")
    assert line and room >= line
    page.close()


def test_the_kanji_of_a_look_alike_are_marked_japanese(root, chromium):
    _front, back = _faces(root, "kanji", "Recognition")
    page = _anki(chromium)
    _show(page, back)
    marked = page.evaluate("Array.from(document.querySelectorAll('.aside-text [lang=\"ja\"]'))"
                           ".map(s => s.textContent)")
    assert "牛" in marked
    page.close()


# ── The file of choices ───────────────────────────────────────────────────────

def test_only_the_gaps_are_written(profile):
    card_templates.set_one("vocab.notes", "no")
    assert "vocab.notes=no" in profile.read_text(encoding="utf-8")


def test_the_file_quotes_the_name_of_its_menu_as_the_language_does(profile, monkeypatch):
    """The language quotes a name (`i18n.quoted`): quotes typed into the
    sentence would quote it the English way in every language."""
    from kotogen import i18n

    quotes = {"quote_open": "« ", "quote_close": " »"}
    monkeypatch.setattr(i18n, "convention", lambda name, default: quotes.get(name, default))
    card_templates.set_one("vocab.notes", "no")
    assert "(the « Templates » menu)" in profile.read_text(encoding="utf-8")


def test_coming_back_to_the_repo_removes_the_file(profile):
    """"Nothing customised" and "no file" are the same state."""
    card_templates.set_one("vocab.notes", "no")
    card_templates.set_one("vocab.notes", "yes")
    assert not profile.exists()
    assert card_templates.is_default() and card_templates.differences() == []


def test_a_line_a_moved_default_left_behind_goes_at_the_next_write(profile):
    """A line equal to a moved default (`vocab.tags=no`) changes nothing when
    read, and is not carried over when the file is written."""
    profile.write_text("vocab.tags=no\n", encoding="utf-8")
    assert card_templates.is_default()
    card_templates.set_one("vocab.notes", "no")
    assert "vocab.tags" not in profile.read_text(encoding="utf-8")
    card_templates.set_one("vocab.notes", "yes")
    assert not profile.exists()


def test_an_unknown_value_falls_back_to_the_repo(profile):
    """The file may be edited by hand: a typo stops nothing."""
    profile.write_text("vocab.notes=maybe\n", encoding="utf-8")
    assert card_templates.value("vocab.notes") == "yes"


def test_an_impossible_position_is_refused():
    with pytest.raises(ValueError):
        card_templates.set_one("vocab.tts", "sometimes")


def test_the_summary_line_says_what_was_removed():
    card_templates.set_one("vocab.notes", "no")
    assert card_templates.differences() == ["vocabulary notes removed"]
    assert notetypes._customised("vocab") == ["1 customisation"]


def test_the_summary_line_counts_instead_of_unrolling():
    """The count, not the list: the details are on the customisation screen."""
    for key in ("vocab.register", "vocab.badge", "vocab.notes", "grammar.link"):
        card_templates.set_one(key, "no")
    assert notetypes._customised("vocab") == ["3 customisations"]


def test_a_customisation_is_counted_on_the_type_that_carries_it():
    """Each type counts only its own customisations; an untouched type shows none."""
    card_templates.set_one("grammar.link", "no")
    assert notetypes._customised("grammar") == ["1 customisation"]
    assert notetypes._customised("vocab") == []
