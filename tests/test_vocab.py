"""Vocabulary generation pipeline: reading the entries, batches, filters.

The AI client is faked, to check what is sent to it, and above all what is not.
"""

import argparse

import pytest

from conftest import Held
from kotogen import dictionary, exporter, i18n, jlpt, known, memory, prompts
from kotogen.ai_client import AIAuthError, AITruncatedError
from kotogen.generators import vocab
from kotogen.generators.vocab import (
    FIELDS,
    _apply_level,
    _filter_and_dedup,
    _generate_cards,
    _parse_word_file,
    _process_entries,
    _skip_known,
    _split_hung_tags,
    _tag_levels,
)
from kotogen.known import NO_WORDS, Words


class FakeClient:
    """Faked AI client: hands back the given answers, keeps the messages received."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def chat_json(self, system, user):
        self.prompts.append(user)
        answer = self.responses.pop(0) if self.responses else []
        if isinstance(answer, Exception):
            raise answer
        return answer


def card(expression, translation="Sens", **extra):
    base = {"Expression": expression, "Translation": translation, "Context": "",
            "Notes": "", "Example": "", "ExampleTranslation": "", "Tags": ""}
    base.update(extra)
    return base


def make_args(**extra):
    # jobs=1: `FakeClient` answers in call order, which parallel generation does
    # not keep; test_ai_failures covers the parallel case.
    defaults = dict(deck="Japanese::Vocabulary", notetype="Vocabulary",
                    batch_size=10, jobs=1, level="auto", send=False,
                    output=None, force=False)
    defaults.update(extra)
    return argparse.Namespace(**defaults)


@pytest.fixture(autouse=True)
def no_kanji_review(monkeypatch):
    """The lone-kanji check calls the AI: off topic here, neutralised."""
    monkeypatch.setattr(vocab.kanji_word, "not_words", lambda client, exprs: {})


# ── Reading a word file ───────────────────────────────────────────────────────

def test_bullets_and_blank_lines_are_ignored(tmp_path):
    path = tmp_path / "words.md"
    path.write_text("# Title\n\n涼しい - cool\n- 飲む to drink\n* 走る hashiru\n",
                    encoding="utf-8")
    assert _parse_word_file(path) == ["涼しい - cool", "飲む to drink", "走る hashiru"]


def test_the_bom_of_a_windows_editor_stays_off_the_first_word(tmp_path):
    """Notepad writes it: kept, the first entry would be another word for the
    model and for the deck."""
    path = tmp_path / "words.md"
    path.write_text("涼しい\n飲む\n", encoding="utf-8-sig")
    assert _parse_word_file(path) == ["涼しい", "飲む"]


def test_a_file_with_no_entry(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("# Title\n\n\n", encoding="utf-8")
    assert _parse_word_file(path) == []


# ── Calling the model ─────────────────────────────────────────────────────────

def test_one_entry_asks_for_one_card():
    client = FakeClient(card("水[みず]"))
    _generate_cards(client, ["水"])
    assert "水" in client.prompts[0]
    assert "tableau JSON" not in client.prompts[0]


def test_several_entries_ask_for_an_array():
    client = FakeClient([card("水[みず]"), card("火[ひ]")])
    _generate_cards(client, ["水", "火"])
    assert "tableau JSON" in client.prompts[0]
    assert "les 2 mots" in client.prompts[0]


def test_a_lone_card_is_normalised_into_a_list():
    assert _generate_cards(FakeClient(card("水[みず]")), ["水"]) == [card("水[みず]")]


def test_an_unexpected_structure_is_refused():
    with pytest.raises(ValueError):
        _generate_cards(FakeClient("not structured JSON"), ["水"])


# ── Filtering the cards handed back ───────────────────────────────────────────

def test_a_card_the_ai_turned_down_is_set_aside():
    valid, skipped = _filter_and_dedup(
        [{"_skip": True, "_input": "は", "_reason": "particule"}], set())
    assert valid == []
    assert skipped[0]["_reason"] == "particule"


@pytest.mark.parametrize("incomplete", [
    {"Expression": "", "Translation": "Eau"},
    {"Expression": "水[みず]", "Translation": ""},
])
def test_the_essential_fields_are_required(incomplete):
    valid, skipped = _filter_and_dedup([incomplete], set())
    assert valid == []
    assert "empty" in skipped[0]["_reason"]


def test_a_duplicate_within_one_run():
    seen = set()
    valid, _ = _filter_and_dedup([card("水[みず]"), card("水[みず]")], seen)
    assert len(valid) == 1
    assert seen == {"水[みず]"}


# ── Words already known ───────────────────────────────────────────────────────

def index_with(*expressions):
    return known.words_of(expressions)


def deck_holding(monkeypatch, index: Words) -> None:
    """The run remembers with a deck whose vocabulary is `index`."""
    class Deck(Held):
        def words(self, notetype, field_name="Expression"):
            return index

    monkeypatch.setattr(memory, "_known", Deck())


def test_a_known_entry_is_turned_down_before_generation():
    entries, skipped = _skip_known(["水", "火"], index_with("水[みず]"))
    assert entries == ["火"]
    assert skipped[0]["_input"] == "水"
    assert skipped[0][vocab.KNOWN_FLAG] is True
    assert "already in the deck" in skipped[0]["_reason"]


def test_an_empty_index_filters_nothing():
    entries, skipped = _skip_known(["水", "火"], NO_WORDS)
    assert entries == ["水", "火"]
    assert skipped == []


def test_no_call_at_all_for_an_already_known_word(tmp_path):
    """The known word must not reach the AI."""
    client = FakeClient()
    cards, skipped = _process_entries(
        client, ["水"], make_args(), tmp_path / "out.tsv", set(), index_with("水[みず]"))
    assert client.prompts == []
    assert cards == []
    assert len(skipped) == 1


# ── JLPT level ────────────────────────────────────────────────────────────────

def test_the_level_tag_is_added():
    cards = [card("水[みず]", Tags="Noun::Nature")]
    _tag_levels(cards)
    assert cards[0]["Tags"].split() == ["Noun::Nature", "Level::N5"]


def test_a_register_tag_hung_under_a_category_is_split_off():
    """Seen from the model: `Verb::五段動詞::Register::敬語::尊敬語`, one tag
    that neither the badge nor a search would find."""
    cards = [card("召[め]し 上[あ]がる", Tags="Verb::五段動詞::Register::敬語::尊敬語"),
             card("俺[おれ]", Tags="Noun::People::Register::口語::Speaker::男性語")]
    _split_hung_tags(cards)
    assert cards[0]["Tags"].split() == ["Verb::五段動詞", "Register::敬語::尊敬語"]
    assert cards[1]["Tags"].split() == ["Noun::People", "Register::口語", "Speaker::男性語"]


def test_a_word_outside_the_table_stays_without_a_level():
    cards = [card("躊躇[ちゅうちょ]", Tags="Noun")]
    _tag_levels(cards)
    assert cards[0]["Tags"] == "Noun"


def test_the_level_asked_for_turns_down_the_words_that_are_too_easy(capsys):
    kept = _apply_level(["水", "躊躇"], "N3")
    assert kept == ["躊躇"]
    assert "too easy for N3" in capsys.readouterr().out


def test_auto_sorts_without_turning_anything_down():
    assert _apply_level(["躊躇", "水"], "auto") == ["水", "躊躇"]


# ── Rereading the readings ────────────────────────────────────────────────────

def test_a_doubtful_reading_is_tagged(monkeypatch):
    monkeypatch.setattr(dictionary, "check",
                        lambda expr: (dictionary.READING_TAG, "unexpected reading"))
    cards = [card("図書館[としょしつ]")]
    assert vocab._check_readings(cards) == 1
    assert dictionary.READING_TAG in cards[0]["Tags"]


def test_a_valid_reading_is_not_tagged(monkeypatch):
    monkeypatch.setattr(dictionary, "check", lambda expr: None)
    cards = [card("水[みず]", Tags="Noun::Nature")]
    assert vocab._check_readings(cards) == 0
    assert cards[0]["Tags"] == "Noun::Nature"


# ── Splitting into batches, and saving ────────────────────────────────────────

def test_batches_of_the_size_asked_for(tmp_path):
    client = FakeClient([card("一[いち]")], [card("二[に]")], [card("三[さん]")])
    _process_entries(client, ["一", "二", "三"], make_args(batch_size=1),
                     tmp_path / "out.tsv", set(), NO_WORDS)
    assert len(client.prompts) == 3


def test_a_single_entry_does_not_announce_itself_as_a_word(tmp_path, capsys):
    """An entry may be a free sentence, so "1 word" would be wrong; and a single
    entry has just been typed, so its count says nothing."""
    client = FakeClient([card("水[みず]")])
    _process_entries(client, ["kono inu ha kawaii desu"], make_args(),
                     tmp_path / "out.tsv", set(), NO_WORDS)
    out = capsys.readouterr().out
    assert "Generating the cards…" in out and "entries" not in out


def test_several_entries_are_counted(tmp_path, capsys):
    client = FakeClient([card("一[いち]"), card("二[に]")])
    _process_entries(client, ["一", "二"], make_args(),
                     tmp_path / "out.tsv", set(), NO_WORDS)
    assert "Generating the cards (2 entries)…" in capsys.readouterr().out


def test_the_tsv_is_written_as_the_batches_go(tmp_path):
    """A crash halfway must not take the cards already produced with it."""
    path = tmp_path / "out.tsv"
    client = FakeClient([card("一[いち]")], AIAuthError("key refused"))
    with pytest.raises(AIAuthError):
        _process_entries(client, ["一", "二"], make_args(batch_size=1),
                         path, set(), NO_WORDS)
    assert "一[いち]" in path.read_text(encoding="utf-8")


def test_one_batch_failing_does_not_affect_the_next_ones(tmp_path, capsys):
    client = FakeClient(RuntimeError("unreadable answer"), [card("二[に]")])
    cards, _ = _process_entries(client, ["一", "二"], make_args(batch_size=1),
                                tmp_path / "out.tsv", set(), NO_WORDS)
    assert [c["Expression"] for c in cards] == ["二[に]"]
    assert "batch 1: unreadable answer" in capsys.readouterr().err


def test_a_batch_of_one_entry_among_several_is_counted_too(tmp_path, capsys):
    """Several batches name their rank and their count, a last one of one entry
    included: never a rank left hanging on a comma."""
    client = FakeClient([card("一[いち]"), card("二[に]")], [card("三[さん]")])
    _process_entries(client, ["一", "二", "三"], make_args(batch_size=2),
                     tmp_path / "out.tsv", set(), NO_WORDS)
    out = capsys.readouterr().out
    assert "(batch 1/2, 2 entries)" in out and "(batch 2/2, 1 entry)" in out


def test_a_half_lost_after_a_truncation_counts_as_failed(tmp_path):
    """The derive action of `maintain` keeps its flag only when a call failed:
    a half dropped is one, though the batch gave cards."""
    client = FakeClient(AITruncatedError("cut off"), ValueError("invalid JSON"),
                        [card("二[に]")])
    failed: list[str] = []
    cards, _ = _process_entries(client, ["一", "二"], make_args(), tmp_path / "out.tsv",
                                set(), NO_WORDS, failed=failed)
    assert [c["Expression"] for c in cards] == ["二[に]"]
    assert failed == ["一"]


def test_what_a_split_batch_says_is_said_by_the_loop(monkeypatch, tmp_path):
    """Said from a pool thread, its lines would land under whatever batch the
    screen animates at that moment."""
    import threading

    said: list[tuple[bool, str]] = []

    def record(text):
        said.append((threading.current_thread() is threading.main_thread(), text))

    monkeypatch.setattr(vocab.console, "item", record)
    monkeypatch.setattr(vocab.console, "failed", record)
    client = FakeClient(AITruncatedError("cut off"), ValueError("invalid JSON"),
                        [card("二[に]")])
    _process_entries(client, ["一", "二"], make_args(), tmp_path / "out.tsv",
                     set(), NO_WORDS)

    split = [(main, text) for main, text in said
             if "replayed in two" in text or "half dropped" in text]
    assert len(split) == 2 and all(main for main, _text in split)


@pytest.mark.parametrize("answer", [
    ["水", card("火[ひ]")],
    [{"Expression": None, "Translation": "Eau"}, card("火[ひ]")],
])
def test_a_malformed_item_does_not_stop_the_run(tmp_path, capsys, answer):
    """A bare string or a null Expression is one entry lost, not the run: the
    cards before it and after it still reach the file."""
    client = FakeClient(answer)
    cards, _ = _process_entries(client, ["水", "火"], make_args(), tmp_path / "out.tsv",
                                set(), NO_WORDS)
    assert [c["Expression"] for c in cards] == ["火[ひ]"]
    assert "None" not in capsys.readouterr().out


def test_a_refused_key_stops_everything(tmp_path):
    """Replaying an invalid key on every batch would only waste time.

    The batches in flight finish, but none still waiting is sent: with four
    jobs, about four calls out of ten.
    """
    entries = [str(i) for i in range(10)]
    client = FakeClient(*([AIAuthError("key refused")] * 10))
    with pytest.raises(AIAuthError):
        _process_entries(client, entries, make_args(batch_size=1, jobs=4),
                         tmp_path / "out.tsv", set(), NO_WORDS)
    assert len(client.prompts) <= 4


def test_a_refused_key_in_sequence_stops_at_the_first_batch(tmp_path):
    client = FakeClient(AIAuthError("key refused"), [card("二[に]")])
    with pytest.raises(AIAuthError):
        _process_entries(client, ["一", "二"], make_args(batch_size=1, jobs=1),
                         tmp_path / "out.tsv", set(), NO_WORDS)
    assert len(client.prompts) == 1


def test_the_tsv_columns_match_the_fields(tmp_path):
    path = tmp_path / "out.tsv"
    _process_entries(FakeClient([card("水[みず]", "Eau")]), ["水"], make_args(),
                     path, set(), NO_WORDS)
    body = [l for l in path.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
    assert body[0].split("\t")[:len(FIELDS)][:2] == ["水[みず]", "Eau"]


def test_the_context_has_its_column_right_after_the_translation(tmp_path):
    """The Anki import matches columns to fields by rank, and `Expression` stays
    first: Anki sorts and checks duplicates on it."""
    assert FIELDS[:3] == ["Expression", "Translation", "Context"]

    path = tmp_path / "out.tsv"
    _process_entries(FakeClient([card("被[かぶ]る", "Porter", Context="sur la tête")]),
                     ["被る"], make_args(), path, set(), NO_WORDS)
    body = [l for l in path.read_text(encoding="utf-8").splitlines() if not l.startswith("#")]
    assert body[0].split("\t")[:3] == ["被[かぶ]る", "Porter", "sur la tête"]


# ── Entry point ───────────────────────────────────────────────────────────────

def run_vocab_with(monkeypatch, args, responses=()):
    client = FakeClient(*responses)
    monkeypatch.setattr(vocab, "AIClient", lambda provider, model: client)
    deck_holding(monkeypatch, NO_WORDS)
    vocab.run_vocab(args)
    return client


def test_a_missing_file_stops_the_command(monkeypatch, tmp_path):
    args = make_args(provider="openrouter", model="m", word=None,
                     file=tmp_path / "missing.md", output=str(tmp_path / "o.tsv"))
    with pytest.raises(SystemExit) as err:
        run_vocab_with(monkeypatch, args)
    assert "not found" in str(err.value)


def test_a_file_of_one_entry_counts_it_in_the_singular(monkeypatch, tmp_path, capsys):
    path = tmp_path / "words.md"
    path.write_text("水\n", encoding="utf-8")
    args = make_args(provider="openrouter", model="m", word=None, file=path,
                     output=str(tmp_path / "o.tsv"))
    run_vocab_with(monkeypatch, args, responses=([card("水[みず]", "Eau")],))
    assert "1 entry read" in capsys.readouterr().out


def test_everything_already_known_is_not_a_failure(monkeypatch, tmp_path):
    """A dedicated message: the filtering worked, this is not a failed generation."""
    args = make_args(provider="openrouter", model="m", word="水",
                     file=None, output=str(tmp_path / "o.tsv"))
    monkeypatch.setattr(vocab, "AIClient", lambda provider, model: FakeClient())
    deck_holding(monkeypatch, index_with("水[みず]"))
    with pytest.raises(SystemExit) as err:
        vocab.run_vocab(args)
    assert "already in the deck" in str(err.value)
    assert "--force" in str(err.value)


def test_force_regenerates_a_known_word(monkeypatch, tmp_path):
    """--force remakes a word the deck holds, and the model is still told what
    the deck knows: the example of the remade card is built on it too."""
    args = make_args(provider="openrouter", model="m", word="水", file=None,
                     force=True, output=str(tmp_path / "o.tsv"))
    deck_holding(monkeypatch, Words(frozenset(jlpt.words_of("N5")[:500]) | {"水"},
                                    frozenset()))
    sent: list[tuple[str, str]] = []

    def spy(system, user):
        sent.append((system, user))
        return [card("水[みず]", "Eau")]

    client = FakeClient()
    client.chat_json = spy
    monkeypatch.setattr(vocab, "AIClient", lambda provider, model: client)
    vocab.run_vocab(args)
    assert len(sent) == 1 and "水" in sent[0][1]
    assert "Vocabulaire déjà connu" in sent[0][0]


# ── The "jlpt" source: filling a level in ─────────────────────────────────────
# What is left to do is the level's table minus the deck.

def _connected(monkeypatch, ok=True):
    monkeypatch.setattr("kotogen.anki.connect.status",
                        lambda **k: type("S", (), {"connected": ok})())


def test_jlpt_keeps_only_what_is_missing(capsys):
    index = Words(frozenset({"水", "犬"}), frozenset())
    entries = vocab._jlpt_entries("N5", 5, index)
    assert "水" not in entries and "犬" not in entries
    assert len(entries) == 5
    out = capsys.readouterr().out
    assert "2 already in the deck" in out


def test_jlpt_respects_the_number_asked_for():
    assert len(vocab._jlpt_entries("N5", 3, NO_WORDS)) == 3


def test_jlpt_without_anki_refuses_to_generate_the_whole_level(monkeypatch, tmp_path):
    """Without the deck, "what is missing" has no meaning: it would be everything."""
    _connected(monkeypatch, False)
    monkeypatch.setattr(vocab, "AIClient", lambda **k: FakeClient())
    args = make_args(word="jlpt", file=None, level="N4", count=None,
                     provider="openrouter", model="m")
    with pytest.raises(SystemExit) as excinfo:
        vocab.run_vocab(args)
    assert "Anki has to be open" in str(excinfo.value)


def test_jlpt_generates_the_missing_words(monkeypatch, tmp_path):
    _connected(monkeypatch)
    deck_holding(monkeypatch, Words(frozenset({"水"}), frozenset()))
    client = FakeClient(*[[card(w)] for w in ("一", "二", "三")])
    monkeypatch.setattr(vocab, "AIClient", lambda **k: client)

    args = make_args(word="jlpt", file=None, level="N5", count=3,
                     provider="openrouter", model="m", output=str(tmp_path / "out.tsv"))
    vocab.run_vocab(args)

    # A single batch of 3 words, and 水 (already learned) is not part of it.
    assert len(client.prompts) == 1
    assert "水" not in client.prompts[0]


def test_a_level_already_complete_costs_nothing(monkeypatch, tmp_path, capsys):
    """Level finished: it is said, without calling the AI."""
    _connected(monkeypatch)
    everything = frozenset(jlpt.words_of("N5"))
    deck_holding(monkeypatch, Words(everything, frozenset()))
    client = FakeClient()
    monkeypatch.setattr(vocab, "AIClient", lambda **k: client)

    args = make_args(word="jlpt", file=None, level="N5", count=20,
                     provider="openrouter", model="m", output=str(tmp_path / "out.tsv"))
    vocab.run_vocab(args)

    assert client.prompts == []
    assert "already in the deck" in capsys.readouterr().out


# ── The theme source: the words of a field ────────────────────────────────────
# No table holds a theme's words, so the model lists them; those the deck holds
# are dropped before anything is billed.

def _theme_args(tmp_path, **extra):
    return make_args(word=None, file=None, theme="fruits", count=2,
                     provider="openrouter", model="m",
                     output=str(tmp_path / "out.tsv"), **extra)


def test_a_theme_keeps_only_what_the_deck_lacks(capsys):
    client = FakeClient(["果物", "桃", "梨", "葡萄"])
    entries = vocab._theme_entries(client, "fruits", 5, "auto", index_with("桃[もも]"))
    assert "桃" not in entries
    assert set(entries) == {"果物", "梨", "葡萄"}
    assert "1 already in the deck" in capsys.readouterr().out


def test_a_theme_asks_for_more_words_than_it_keeps():
    """Asking for more leaves enough once the deck's words are dropped."""
    client = FakeClient(["果物", "桃", "梨"])
    vocab._theme_entries(client, "fruits", 20, "auto", NO_WORDS)
    assert "at most 60 words" in client.prompts[0]


def test_a_theme_with_no_word_is_said(monkeypatch, tmp_path):
    monkeypatch.setattr(vocab, "AIClient", lambda **k: FakeClient([]))
    deck_holding(monkeypatch, NO_WORDS)
    with pytest.raises(SystemExit) as err:
        vocab.run_vocab(_theme_args(tmp_path))
    assert "no word for this theme" in str(err.value)


def test_a_theme_that_fails_exits_on_the_first_line_of_its_reason(monkeypatch, tmp_path):
    """A model's error carries its raw answer below the first line, and may hold
    an escape sequence: neither reaches the terminal."""
    def failing(*args, **kwargs):
        raise ValueError("The AI did not return valid JSON.\x1b[2J\n{raw answer}")

    monkeypatch.setattr(vocab, "AIClient", lambda **k: FakeClient())
    monkeypatch.setattr(vocab, "_theme_entries", failing)
    deck_holding(monkeypatch, NO_WORDS)
    with pytest.raises(SystemExit) as err:
        vocab.run_vocab(_theme_args(tmp_path))
    assert str(err.value) == "The AI did not return valid JSON.[2J"


def test_the_preview_shows_no_control_character_of_the_model(monkeypatch, tmp_path):
    previews = []
    monkeypatch.setattr(vocab, "finish",
                        lambda *a, preview=(), **k: previews.extend(preview))
    args = make_args(provider="openrouter", model="m", word="水", file=None,
                     output=str(tmp_path / "o.tsv"))
    run_vocab_with(monkeypatch, args,
                   responses=([card("水[みず]", "Eau\x1b[31m rouge")],))
    assert previews and not any("\x1b" in line for line in previews)


def test_a_theme_generates_the_missing_words(monkeypatch, tmp_path):
    deck_holding(monkeypatch, index_with("果物[くだもの]"))
    client = FakeClient(["果物", "桃", "梨", "葡萄"], [card("桃[もも]"), card("梨[なし]")])
    monkeypatch.setattr(vocab, "AIClient", lambda **k: client)
    vocab.run_vocab(_theme_args(tmp_path))

    # The list, then a single batch of the 2 words asked for, 果物 left out.
    assert len(client.prompts) == 2
    assert "果物" not in client.prompts[1]


def test_a_theme_the_deck_already_holds_costs_one_call(monkeypatch, tmp_path, capsys):
    deck_holding(monkeypatch, index_with("桃[もも]", "梨[なし]"))
    client = FakeClient(["桃", "梨"])
    monkeypatch.setattr(vocab, "AIClient", lambda **k: client)
    vocab.run_vocab(_theme_args(tmp_path))

    assert len(client.prompts) == 1
    assert "every word of the theme" in capsys.readouterr().out


# ── Examples built on the vocabulary already learned (i+1) ────────────────────
# An empty or small deck, or a closed Anki, must give EXACTLY the plain prompt.

def _big_index(n=500):
    words = jlpt.words_of("N5")[:n]
    return Words(frozenset(words), frozenset())


def _words_kept(section: str) -> list[str]:
    """The words that actually went off in the prompt, read back in the section."""
    line = next(l for l in section.splitlines() if "、" in l)
    return line.split("、")


def test_the_section_is_absent_without_a_deck():
    assert vocab.known_words_section(NO_WORDS) == ""


def test_the_section_is_absent_for_a_beginner_deck():
    """Below the threshold, there is not enough to write a natural sentence."""
    small = Words(frozenset({"水", "火", "本"}), frozenset())
    assert vocab.known_words_section(small) == ""


def test_the_section_is_there_for_a_well_stocked_deck():
    section = vocab.known_words_section(_big_index())
    assert "Vocabulaire déjà connu" in section
    # The first word in order, safe from the KNOWN_WORDS_MAX cut: a word near the
    # cut would pass or fail by chance.
    assert sorted(jlpt.words_of("N5")[:500])[0] in section


def test_the_words_kept_are_not_drawn_by_lot():
    """`surfaces` is a set, iterated in a per-process salted order, and
    `sort_by_level` is stable: unsorted, the words kept would change at every
    launch, and so would the cached prompt.

    A repeat within one process would prove nothing: the rule itself is checked.
    """
    words = jlpt.words_of("N5")[:500]
    kept = _words_kept(vocab.known_words_section(_big_index()))

    assert kept == sorted(words)[:vocab.KNOWN_WORDS_MAX]


def test_the_section_is_capped():
    """Beyond the ceiling, one would pay for context with a decreasing return."""
    huge = Words(frozenset(jlpt.words_of("auto")), frozenset())
    section = vocab.known_words_section(huge)
    assert section.count("、") + 1 == vocab.KNOWN_WORDS_MAX


def test_the_section_keeps_the_most_fundamental_words():
    """The words served have to be the raw material of a simple sentence."""
    mixed = Words(
        frozenset(jlpt.words_of("N1")[:300] + jlpt.words_of("N5")[:300]), frozenset())
    section = vocab.known_words_section(mixed)
    served = next(l for l in section.splitlines() if "、" in l).split("、")
    assert sum(1 for w in served if jlpt.level_of(w) == "N5") > len(served) // 2


def test_the_prompt_is_unchanged_when_the_deck_says_nothing(tmp_path):
    """Anki closed: the system prompt is the plain one, to the character."""
    seen = []
    client = FakeClient([card("水[みず]")])

    def spy(system, user):
        seen.append(system)
        return [card("水[みず]")]

    client.chat_json = spy
    _process_entries(client, ["水"], make_args(), tmp_path / "out.tsv",
                     set(), NO_WORDS)
    assert seen == [prompts.load("vocab_card")]


def test_the_known_vocabulary_is_passed_to_the_model(tmp_path):
    seen = []
    client = FakeClient()

    def spy(system, user):
        seen.append(system)
        return [card("躊躇[ちゅうちょ]")]

    client.chat_json = spy
    # A word absent from the index, or it would be turned down before generation.
    _process_entries(client, ["躊躇"], make_args(), tmp_path / "out.tsv",
                     set(), _big_index())

    assert "Vocabulaire déjà connu" in seen[0]
    assert seen[0].startswith(prompts.load("vocab_card"))   # an addition, not a rewrite


def test_the_switch_that_turns_it_off(tmp_path):
    seen = []
    client = FakeClient()

    def spy(system, user):
        seen.append(system)
        return [card("躊躇[ちゅうちょ]")]

    client.chat_json = spy
    _process_entries(client, ["躊躇"], make_args(known_words=False),
                     tmp_path / "out.tsv", set(), _big_index())
    assert seen == [prompts.load("vocab_card")]


# ── Breaking an expression down into its words ────────────────────────────────
# The model lists the components in the same answer as the card: no call is
# added to spot them, and a word already produced or learned is not regenerated.

EXPRESSION = "お 腹[なか]が 空[す]く"


@pytest.fixture
def accepted(monkeypatch):
    """Answers "yes" to the question asked before generating the components."""
    monkeypatch.setattr(vocab, "ask_choice", lambda *a, **k: "y")


def _decomposed(client, tmp_path, entry="お腹が空いた", index=NO_WORDS,
                decompose=True, **extra):
    return _process_entries(client, [entry], make_args(**extra),
                            tmp_path / "out.tsv", set(), index, decompose)


def test_an_expression_broken_down_into_words(tmp_path, accepted):
    client = FakeClient(
        [card(EXPRESSION, "Avoir faim", Components=["お腹", "空く"])],
        [card("お 腹[なか]", "Ventre"), card("空[す]く", "Se vider")],
    )
    cards, _ = _decomposed(client, tmp_path)

    # Two calls: the card of the expression, then the batch of its words.
    assert len(client.prompts) == 2
    assert "お腹" in client.prompts[1] and "空く" in client.prompts[1]
    assert [c["Expression"] for c in cards] == [EXPRESSION, "お 腹[なか]", "空[す]く"]


def test_the_components_key_is_dropped_from_the_cards(tmp_path, accepted):
    """`Components` is not a note field: it must reach neither the TSV nor the
    send, breakdown asked for or not."""
    for decompose in (True, False):
        client = FakeClient([card("水[みず]", Components=["水"])], [])
        cards, _ = _decomposed(client, tmp_path, entry="水", decompose=decompose)
        assert vocab.COMPONENTS_KEY not in cards[0]


def test_without_a_request_there_is_no_second_batch(tmp_path):
    client = FakeClient([card(EXPRESSION, "Avoir faim", Components=["お腹", "空く"])])
    cards, _ = _decomposed(client, tmp_path, decompose=False)
    assert len(client.prompts) == 1
    assert len(cards) == 1


def test_a_component_already_in_the_deck_is_not_regenerated(tmp_path, accepted, capsys):
    client = FakeClient(
        [card(EXPRESSION, "Avoir faim", Components=["お腹", "空く"])],
        [card("空[す]く", "Se vider")],
    )
    _decomposed(client, tmp_path, index=index_with("お腹"))
    assert "お腹" not in client.prompts[1]
    assert "空く" in client.prompts[1]


def test_the_question_counts_only_the_words_it_would_make(tmp_path, accepted, capsys):
    """A component the deck holds is dropped before the question, whose count is
    what will be paid for."""
    client = FakeClient(
        [card(EXPRESSION, "Avoir faim", Components=["お腹", "空く"])],
        [card("空[す]く", "Se vider")],
    )
    _decomposed(client, tmp_path, index=index_with("お腹"))
    out = capsys.readouterr().out
    assert "1 vocabulary word picked up:" in out
    assert "お腹、空く" not in out


def test_no_question_when_the_deck_holds_every_component(tmp_path, monkeypatch):
    monkeypatch.setattr(vocab, "ask_choice",
                        lambda *a, **k: pytest.fail("asked about words the deck holds"))
    client = FakeClient([card(EXPRESSION, "Avoir faim", Components=["お腹", "空く"])])
    _cards, skipped = _decomposed(client, tmp_path, index=index_with("お腹", "空[す]く"))
    assert len(client.prompts) == 1
    assert [s["_input"] for s in skipped] == ["お腹", "空く"]


def test_a_component_repeating_the_expression_is_ignored(tmp_path, accepted):
    """The model may list the whole expression among its components: its card
    already exists."""
    client = FakeClient([card(EXPRESSION, "Avoir faim", Components=["お腹が空く"])])
    cards, _ = _decomposed(client, tmp_path)
    assert len(client.prompts) == 1
    assert len(cards) == 1


def test_a_component_repeated_between_two_expressions(tmp_path, accepted):
    client = FakeClient(
        [card(EXPRESSION, "Avoir faim", Components=["お腹", "空く"]),
         card("お 腹[なか]が 痛[いた]い", "Avoir mal au ventre", Components=["お腹", "痛い"])],
        [card("お 腹[なか]"), card("空[す]く"), card("痛[いた]い")],
    )
    _process_entries(client, ["お腹が空いた", "お腹が痛い"], make_args(),
                     tmp_path / "out.tsv", set(), NO_WORDS, True)
    assert client.prompts[1].count("お腹") == 1


def test_a_component_is_not_broken_down_again(tmp_path, accepted):
    """One depth only: otherwise a compound word would start the machine again."""
    client = FakeClient(
        [card(EXPRESSION, "Avoir faim", Components=["お腹", "空く"])],
        [card("お 腹[なか]", Components=["腹"]), card("空[す]く")],
    )
    cards, _ = _decomposed(client, tmp_path)
    assert len(client.prompts) == 2
    assert all(vocab.COMPONENTS_KEY not in c for c in cards)


def test_a_refusal_generates_no_component(tmp_path, monkeypatch):
    monkeypatch.setattr(vocab, "ask_choice", lambda *a, **k: "n")
    client = FakeClient([card(EXPRESSION, "Avoir faim", Components=["お腹", "空く"])])
    cards, skipped = _decomposed(client, tmp_path)
    assert len(client.prompts) == 1
    assert len(cards) == 1
    assert [s["_input"] for s in skipped] == ["お腹", "空く"]


SENTENCE = "onna no ko to otoko no hito ha hanashite imasu"


def _sentence_skip(**extra):
    return {"_skip": True, "_input": SENTENCE, "_reason": "phrase, pas un mot",
            vocab.COMPONENTS_KEY: ["女の子", "男の人", "話す"], **extra}


def test_a_sentence_gives_its_words(tmp_path, accepted, capsys):
    """A sentence has no card, but its words have one each."""
    client = FakeClient(
        [_sentence_skip()],
        [card("女[おんな]の 子[こ]", "Fille"), card("男[おとこ]の 人[ひと]", "Homme"),
         card("話[はな]す", "Parler")],
    )
    cards, skipped = _decomposed(client, tmp_path, entry=SENTENCE)

    assert [c["Expression"] for c in cards] == [
        "女[おんな]の 子[こ]", "男[おとこ]の 人[ひと]", "話[はな]す"]
    assert [s["_input"] for s in skipped] == [SENTENCE]
    # The turned-down sentence is not announced as a loss: its words follow.
    out = capsys.readouterr().out
    assert "skipped" not in out and "3 words to draw from it" in out


def test_a_sentence_with_no_request_stays_skipped(tmp_path, capsys):
    """Bulk sources (`--no-decompose`): a sentence stays a plain skip."""
    client = FakeClient([_sentence_skip()])
    cards, skipped = _decomposed(client, tmp_path, entry=SENTENCE, decompose=False)
    assert len(client.prompts) == 1
    assert cards == [] and len(skipped) == 1
    assert "skipped (phrase" in capsys.readouterr().out


def test_outside_a_dialogue_the_components_go_off(monkeypatch, capsys):
    """Script or redirected input: the breakdown was asked for, so it generates."""
    def eof(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert vocab._confirm_components([("お腹", EXPRESSION)]) is True
    assert "お腹" in capsys.readouterr().out


def _no_hand(monkeypatch):
    def waited(prompt=""):
        raise AssertionError("an answer was waited for")

    monkeypatch.setattr("builtins.input", waited)


def test_under_yes_the_components_go_off(monkeypatch, capsys):
    """`--yes` answers as a script does: their list still shows, then they come."""
    _no_hand(monkeypatch)
    with exporter.unattended(True):
        assert vocab._confirm_components([("お腹", EXPRESSION)]) is True
    assert "お腹" in capsys.readouterr().out


def test_under_yes_a_lone_kanji_is_turned_down(monkeypatch, capsys):
    """The answer of a script again, written behind the question."""
    _no_hand(monkeypatch)
    monkeypatch.setattr(vocab.kanji_word, "not_words",
                        lambda client, exprs: {"語[ご]": ("suffix", "")})
    lone, word = card("語[ご]"), card("言語[げんご]")
    with exporter.unattended(True):
        kept, dropped = vocab._review_single_kanji(None, [lone, word])
    assert kept == [word]
    assert [c["Expression"] for c in dropped] == ["語[ご]"]
    assert "[c] create anyway r\n" in capsys.readouterr().out


def test_the_words_picked_up_are_grouped_under_their_source(accepted, capsys):
    """Words drawn from one sentence show the sentence once, as it was typed.

    The spaces of a romaji sentence count there, though matching ignores them.
    """
    pairs = [(word, SENTENCE) for word in ("女の子", "男の人", "話す")]
    assert vocab._confirm_components(pairs) is True
    out = capsys.readouterr().out
    assert out.count(SENTENCE) == 1
    assert "女の子、男の人、話す" in out


def test_two_sources_stay_distinct(accepted, capsys):
    pairs = [("お腹", EXPRESSION), ("空く", EXPRESSION), ("女の子", SENTENCE)]
    assert vocab._confirm_components(pairs) is True
    out = capsys.readouterr().out
    assert "お腹、空く" in out and SENTENCE in out


def test_the_flag_takes_precedence_over_the_source():
    assert vocab._decompose_wanted(make_args(), default=True) is True
    assert vocab._decompose_wanted(make_args(), default=False) is False
    assert vocab._decompose_wanted(make_args(decompose=False), default=True) is False
    assert vocab._decompose_wanted(make_args(decompose=True), default=False) is True


@pytest.mark.parametrize("argv, expected", [
    ([], None),
    (["--decompose"], True),
    (["--no-decompose"], False),
])
def test_the_flag_on_the_command_line(argv, expected):
    from kotogen.cli import build_parser
    args = build_parser().parse_args(["vocab", "お腹が空いた", *argv])
    assert args.decompose is expected


# ── Text sources (web page, NHK article) ─────────────────────────────────────
# Through `generators.sources`: the text goes to extraction, the words extracted
# to generation, and only then is the article remembered.

def _source_args(word, tmp_path, **extra):
    return make_args(provider="openrouter", model="m", word=word, file=None,
                     count=5, output=str(tmp_path / "o.tsv"), **extra)


def test_a_web_page_is_extracted_then_generated(monkeypatch, tmp_path):
    from kotogen.generators import text_source

    monkeypatch.setattr(text_source, "fetch",
                        lambda src, **kwargs: ("題名", ["水を飲む"]))
    client = run_vocab_with(
        monkeypatch, _source_args("https://example.jp/article", tmp_path),
        responses=(["水", "飲む"], [card("水[みず]", "Eau"), card("飲[の]む", "Boire")]))

    assert len(client.prompts) == 2
    assert "題名" in client.prompts[0]   # extraction: the text did go off
    assert "水" in client.prompts[1]     # generation: the extracted words


def test_an_nhk_article_is_remembered_after_generation(monkeypatch, tmp_path):
    from kotogen.generators import nhk

    url = "https://news.web.nhk/news/easy/ne1/ne1.html"
    monkeypatch.setattr(nhk, "collect_urls", lambda inputs, latest, mode: [url])
    monkeypatch.setattr(nhk, "fetch_article_text", lambda u: ("記事", ["水を飲む"]))
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(nhk, "mark_seen",
                        lambda u, title="", mode="audio": seen.append((u, mode)))

    run_vocab_with(monkeypatch, _source_args(url, tmp_path),
                   responses=(["水"], [card("水[みず]", "Eau")]))

    assert seen == [(url, "vocab")]


def test_an_article_whose_every_batch_failed_stays_to_be_handled(monkeypatch, tmp_path):
    """Its words were never asked: remembered, the article would be lost to the
    next run, which would skip it as done."""
    from kotogen.generators import nhk

    url = "https://news.web.nhk/news/easy/ne1/ne1.html"
    monkeypatch.setattr(nhk, "collect_urls", lambda inputs, latest, mode: [url])
    monkeypatch.setattr(nhk, "fetch_article_text", lambda u: ("記事", ["水を飲む"]))
    monkeypatch.setattr(nhk, "mark_seen",
                        lambda *a, **k: pytest.fail("article remembered with no card"))

    with pytest.raises(SystemExit):
        run_vocab_with(monkeypatch, _source_args(url, tmp_path),
                       responses=(["水"], RuntimeError("HTTP 503")))


def test_an_article_with_one_batch_failed_stays_to_be_handled(monkeypatch, tmp_path):
    """The words of the failed batch were never asked: the next run takes them,
    the others being in the deck by then."""
    from kotogen.generators import nhk

    url = "https://news.web.nhk/news/easy/ne1/ne1.html"
    monkeypatch.setattr(nhk, "collect_urls", lambda inputs, latest, mode: [url])
    monkeypatch.setattr(nhk, "fetch_article_text", lambda u: ("記事", ["水を飲む"]))
    monkeypatch.setattr(nhk, "mark_seen",
                        lambda *a, **k: pytest.fail("article remembered with words unasked"))

    run_vocab_with(monkeypatch, _source_args(url, tmp_path, batch_size=1),
                   responses=(["水", "飲む"], [card("水[みず]", "Eau")],
                              RuntimeError("HTTP 503")))


def test_an_aozora_work_mined_for_words_is_remembered_by_vocab(monkeypatch, tmp_path):
    """The history is kept by mode: a work whose words were taken is still to
    read, and must not show as handled in the reading catalogue."""
    from kotogen.generators import aozora, text_source

    work = aozora.Work("000628", "ごん狐", "新美 南吉", "913",
                       "https://www.aozora.gr.jp/cards/000121/files/628_14895.html")
    monkeypatch.setattr(aozora, "resolve", lambda src: (work.url, work))
    monkeypatch.setattr(text_source, "fetch", lambda src, **kwargs: ("題名", ["水を飲む"]))
    marked: list[tuple[str, str]] = []
    monkeypatch.setattr(aozora, "mark_seen",
                        lambda work, mode="reading": marked.append((work.work_id, mode)))

    run_vocab_with(monkeypatch,
                   _source_args("https://www.aozora.gr.jp/cards/000121/card628.html",
                                tmp_path),
                   responses=(["水"], [card("水[みず]", "Eau")]))

    assert marked == [("000628", "vocab")]


def test_an_article_with_no_word_kept_stays_to_be_handled(monkeypatch, tmp_path, capsys):
    """Nothing extracted: the article is not remembered, another run will take it up."""
    from kotogen.generators import nhk

    url = "https://news.web.nhk/news/easy/ne1/ne1.html"
    monkeypatch.setattr(nhk, "collect_urls", lambda inputs, latest, mode: [url])
    monkeypatch.setattr(nhk, "fetch_article_text", lambda u: ("記事", ["水を飲む"]))
    monkeypatch.setattr(nhk, "mark_seen",
                        lambda *a, **k: pytest.fail("article remembered with no card"))

    with pytest.raises(SystemExit):
        run_vocab_with(monkeypatch, _source_args(url, tmp_path), responses=([],))
    assert "No word kept" in capsys.readouterr().err


def test_a_pdf_url_is_downloaded_then_read(monkeypatch, tmp_path):
    """Fetched as `reading` fetches it, then read like the file on disk."""
    from kotogen.generators import pdf_source, pdf_web

    url = "https://example.jp/docs/lesson.pdf"
    local = tmp_path / "lesson.pdf"
    local.write_bytes(b"%PDF-1.4\n")
    fetched: list[str] = []
    monkeypatch.setattr(pdf_web, "fetch",
                        lambda source: fetched.append(source) or (local, ""))
    monkeypatch.setattr(pdf_source, "extract_vocab",
                        lambda client, data, name, count, level: ["水"])
    client = run_vocab_with(monkeypatch, _source_args(url, tmp_path),
                            responses=([card("水[みず]", "Eau")],))
    assert fetched == [url]
    assert "水" in client.prompts[0]


def test_the_word_nhk_names_no_feed(monkeypatch, tmp_path):
    """Words come from a text one has in hand: "nhk" is a word like another."""
    from kotogen.generators import nhk

    monkeypatch.setattr(nhk, "collect_urls",
                        lambda *a, **k: pytest.fail("the NHK feed was read"))
    client = run_vocab_with(monkeypatch, _source_args("nhk", tmp_path),
                            responses=([card("NHK", "NHK")],))

    assert len(client.prompts) == 1
    assert "nhk" in client.prompts[0]


@pytest.mark.parametrize("lang", [name for name in i18n.available()
                                  if name != i18n.SOURCE])
def test_every_table_says_why_the_queued_batches_gave_up(lang):
    """`FATAL_REPORTED` is held in English and translated where it is raised."""
    assert vocab.FATAL_REPORTED in i18n._load(lang)


def test_an_answer_of_another_shape_names_its_kind_plainly():
    """The name of the type, not "<class 'str'>"."""
    with pytest.raises(ValueError, match="^unexpected JSON structure: str$"):
        vocab._generate_cards(FakeClient("a sentence"), ["水"])
