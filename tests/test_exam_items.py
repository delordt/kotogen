"""Laying the right past-paper figure on the right card, or laying none at all.

A wrong figure is worse than none: the card can never be answered right and does
not say why. Hence the many tests expecting `None` rather than a guess. The file
names are those of the official 2018 samples, in both their spellings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kotogen.generators import exam_items
from kotogen.generators.exam_items import Position

# ── Reading the position in the file name ─────────────────────────────────────

@pytest.mark.parametrize("name, section, item", [
    ("N5_sample2018-2_3.mp3", 2, 3),
    ("N5_sample2018-2-1.mp3", 2, 1),      # the separator varies from file to file
    ("N5_sample2018-1_7.mp3", 1, 7),
    ("N5_sample2018-3_5.mp3", 3, 5),
    ("N4_sample2018-1_8.mp3", 1, 8),
    ("N5L_sample2018_m1b2.mp3", 1, 2),    # m for mondai, b for ban
    ("N5L_sample2018_m1b4.mp3", 1, 4),
])
def test_the_real_forms_are_read(name, section, item):
    assert exam_items.position_from_name(name) == Position(section, item)


@pytest.mark.parametrize("name", [
    "N4_sample2018-1_rey.mp3",     # the example, written "rey"
    "N5L_sample2018_m1r1.mp3",     # the example, written "r" for rei
    "N5_sample2018-2_0.mp3",       # the example, written with rank 0
    "N5_sample2018-3_0.mp3",
])
def test_the_example_is_not_an_item(name):
    """「れい」, the example opening a section, has no number and no figure."""
    assert exam_items.position_from_name(name) is None


@pytest.mark.parametrize("name", [
    "3_0.mp3",              # two numbers and an underscore, but nothing of an exam
    "Genki_K01-03.mp3",     # a textbook
    "K23_01.mp3",           # a textbook, named otherwise
    "teppei_ep42-3.mp3",    # a podcast episode
    "",
])
def test_what_is_not_a_past_paper_is_not_read(name):
    """Without the level up front, `3_0.mp3` would read as section 3 item 0 -
    and an exam figure would land on a textbook card."""
    assert exam_items.position_from_name(name) is None


@pytest.mark.parametrize("name, level", [
    ("N5L.pdf", "N5"), ("N4V.pdf", "N4"), ("N5_sample2018-2_3.mp3", "N5"),
    ("Genki_K01.mp3", ""), ("N6_thing.pdf", ""), ("EN5.pdf", ""),
])
def test_the_level_read_in_a_name(name, level):
    assert exam_items.level_from_name(name) == level


# ── Finding the booklet again ─────────────────────────────────────────────────

def lay(folder: Path, *names: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"")


def test_the_booklet_is_looked_for_beside_then_above(tmp_path):
    """The samples often sit in an `audio/` subfolder, the booklet above it."""
    lay(tmp_path, "N5L.pdf")
    lay(tmp_path / "audio", "N5_sample2018-2_3.mp3")

    found = exam_items.companion(tmp_path / "audio" / "N5_sample2018-2_3.mp3")

    assert found == tmp_path / "N5L.pdf"


def test_the_pairing_is_done_on_the_level(tmp_path):
    """The level is the only part of the name the audio and the booklet share."""
    lay(tmp_path, "N4L.pdf", "N5L.pdf", "N5_sample2018-2_3.mp3")

    found = exam_items.companion(tmp_path / "N5_sample2018-2_3.mp3")

    assert found == tmp_path / "N5L.pdf"


def test_two_booklets_of_one_level_are_told_apart_by_measurement(tmp_path, monkeypatch):
    """`N4L.pdf` (listening) and `N4V.pdf` (vocabulary) share a level; only the
    listening booklet has figure pages (measured: 8 against 0).
    """
    lay(tmp_path, "N4L.pdf", "N4V.pdf", "N4_sample2018-1_3.mp3")
    monkeypatch.setattr(exam_items, "_has_figures",
                        lambda pdf: pdf.name == "N4L.pdf")

    assert exam_items.companion(tmp_path / "N4_sample2018-1_3.mp3") == tmp_path / "N4L.pdf"


def test_two_listening_booklets_are_not_told_apart(tmp_path, monkeypatch):
    """Nothing is drawn by lot: with no image, the card stays right."""
    lay(tmp_path, "N4L.pdf", "N4L-bis.pdf", "N4_sample2018-1_3.mp3")
    monkeypatch.setattr(exam_items, "_has_figures", lambda pdf: True)

    assert exam_items.companion(tmp_path / "N4_sample2018-1_3.mp3") is None


def test_an_audio_with_no_level_looks_for_no_booklet(tmp_path):
    lay(tmp_path, "N5L.pdf", "K23_01.mp3")

    assert exam_items.companion(tmp_path / "K23_01.mp3") is None


def test_no_booklet_of_the_right_level(tmp_path):
    lay(tmp_path, "N4L.pdf", "N5_sample2018-2_3.mp3")

    assert exam_items.companion(tmp_path / "N5_sample2018-2_3.mp3") is None


# ── Filing a page under its section ───────────────────────────────────────────

def test_a_page_belongs_to_the_last_section_opened():
    """Measured on N5L: the sections open on pages 3, 8, 12 and 16."""
    starts = {1: 3, 2: 8, 3: 12, 4: 16}

    assert exam_items._section_of_page(4, starts) == 1
    assert exam_items._section_of_page(7, starts) == 1
    assert exam_items._section_of_page(9, starts) == 2
    assert exam_items._section_of_page(13, starts) == 3
    assert exam_items._section_of_page(16, starts) == 4


def test_a_page_before_any_section_has_none():
    """The cover and the foreword are in no exercise."""
    assert exam_items._section_of_page(1, {1: 3, 2: 8}) is None
    assert exam_items._section_of_page(5, {}) is None


# ── The booklet, end to end ───────────────────────────────────────────────────

class SilentClient:
    """An AI client handing back a ready-made map, without calling anything."""

    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    def chat_json_pdf(self, *a, **k):
        self.calls += 1
        return self.answer


def test_the_booklet_map_is_paid_for_only_once(tmp_path, monkeypatch):
    """Eight extracts of one exam pay for a single call: the map is cached."""
    booklet = exam_items.Booklet(tmp_path / "N5L.pdf")
    monkeypatch.setattr(exam_items.pdf_source, "load_pdf", lambda p: b"%PDF-fake")
    monkeypatch.setattr(exam_items, "_sections", lambda d: {1: 3})
    monkeypatch.setattr(exam_items.pdf_figures, "pages_with_figures", lambda d: [4])
    monkeypatch.setattr(exam_items, "_extract_pages", lambda d, p: b"%PDF-extract")
    monkeypatch.setattr(exam_items.pdf_figures, "drawings",
                        lambda d: {4: exam_items.pdf_figures.Objects(
                            ((0.1, 0.4, 0.2, 0.8),), ((0.09, 0.42, 0.18, 0.82),))})
    client = SilentClient({"Pages": [{"page": 1, "items": [{"number": 1, "figure": True}]}]})
    monkeypatch.setattr(exam_items.pdf_source, "extract_items",
                        lambda c, d, n, p: [[{"number": 1, "figure": True}]])

    booklet._load(client)
    booklet._load(client)

    assert len(booklet) == 1
    assert Position(1, 1) in booklet._figures


def _typeset(monkeypatch, data=b"%PDF-fake") -> list[int]:
    """A typeset booklet of one figure; hands back the pages each call was paid for."""
    paid: list[int] = []
    monkeypatch.setattr(exam_items.pdf_source, "load_pdf", lambda p: data)
    monkeypatch.setattr(exam_items, "_sections", lambda d: {1: 3})
    monkeypatch.setattr(exam_items.pdf_figures, "pages_with_figures", lambda d: [4])
    monkeypatch.setattr(exam_items, "_extract_pages", lambda d, p: b"%PDF-extract")
    monkeypatch.setattr(exam_items.pdf_figures, "drawings",
                        lambda d: {4: exam_items.pdf_figures.Objects(
                            ((0.1, 0.4, 0.2, 0.8),), ((0.09, 0.42, 0.18, 0.82),))})
    monkeypatch.setattr(exam_items.pdf_source, "extract_items",
                        lambda c, d, n, p: paid.append(p) or [[{"number": 1, "figure": True}]])
    return paid


def test_the_booklet_map_is_kept_from_one_run_to_the_next(tmp_path, monkeypatch):
    """An exam is worked over several runs: its map is paid for by the first."""
    paid = _typeset(monkeypatch)
    first = exam_items.Booklet(tmp_path / "N5L.pdf")
    first._load(SilentClient({}))
    # The next run, under another name: the bytes are what the map is kept by.
    second = exam_items.Booklet(tmp_path / "copy" / "N5L-2018.pdf")
    second._load(SilentClient({}))

    assert len(paid) == 1
    assert second._figures == first._figures and Position(1, 1) in second._figures


def test_a_kept_map_that_does_not_read_is_drawn_again(tmp_path, monkeypatch):
    """A cache is disposable: an entry broken or of another shape costs a call."""
    paid = _typeset(monkeypatch)
    exam_items.Booklet(tmp_path / "N5L.pdf")._load(SilentClient({}))
    exam_items._map_file(b"%PDF-fake").write_text("{not json", encoding="utf-8")

    booklet = exam_items.Booklet(tmp_path / "N5L.pdf")
    booklet._load(SilentClient({}))

    assert len(paid) == 2
    assert not booklet.error and Position(1, 1) in booklet._figures


def test_the_map_is_kept_whole_or_not_at_all(monkeypatch):
    """Cut by a Ctrl+C half written, the map would cost the next run its call."""
    figures = {Position(1, 1): (2, (0.1, 0.5, 0.1, 0.5))}
    written: list[Path] = []
    monkeypatch.setattr(exam_items.system, "write_whole",
                        lambda path, text: written.append(path))

    exam_items._write_map(b"%PDF-fake", figures)

    assert written == [exam_items._map_file(b"%PDF-fake")]


def _two_runs(tmp_path, monkeypatch, drawings: dict, page_items: list) -> list[int]:
    """Loads one typeset booklet in two runs; hands back the pages each call paid for."""
    paid = _typeset(monkeypatch)
    monkeypatch.setattr(exam_items.pdf_figures, "pages_with_figures", lambda d: sorted(drawings))
    monkeypatch.setattr(exam_items.pdf_figures, "drawings", lambda d: drawings)
    monkeypatch.setattr(exam_items.pdf_source, "extract_items",
                        lambda c, d, n, p: paid.append(p) or page_items)
    exam_items.Booklet(tmp_path / "N5L.pdf")._load(SilentClient({}))
    exam_items.Booklet(tmp_path / "N5L.pdf")._load(SilentClient({}))
    return paid


def _one_image():
    return exam_items.pdf_figures.Objects(((0.1, 0.4, 0.2, 0.8),), ())


def test_a_map_with_no_figure_is_not_kept(tmp_path, monkeypatch):
    """Kept under the digest of the booklet, it would answer every run with nothing."""
    paid = _two_runs(tmp_path, monkeypatch, {4: _one_image()},
                     [[{"number": 1, "figure": False}]])

    assert len(paid) == 2
    assert not exam_items._map_file(b"%PDF-fake").exists()


def test_a_map_short_of_a_flagged_figure_is_not_kept(tmp_path, monkeypatch):
    """Two figures flagged on page 5 and one drawing: that page laid nothing."""
    paid = _two_runs(tmp_path, monkeypatch, {4: _one_image(), 5: _one_image()},
                     [[{"number": 1, "figure": True}],
                      [{"number": 2, "figure": True}, {"number": 3, "figure": True}]])

    assert len(paid) == 2
    assert not exam_items._map_file(b"%PDF-fake").exists()


def test_another_booklet_does_not_take_the_map_of_the_first(tmp_path, monkeypatch):
    paid = _typeset(monkeypatch)
    exam_items.Booklet(tmp_path / "N5L.pdf")._load(SilentClient({}))
    _typeset(monkeypatch, data=b"%PDF-other")
    monkeypatch.setattr(exam_items.pdf_source, "extract_items",
                        lambda c, d, n, p: paid.append(p) or [[{"number": 2, "figure": True}]])

    booklet = exam_items.Booklet(tmp_path / "N4L.pdf")
    booklet._load(SilentClient({}))

    assert len(paid) == 2
    assert set(booklet._figures) == {Position(1, 2)}


def test_an_unreadable_booklet_does_not_bring_the_generation_down(tmp_path, monkeypatch):
    """The cards are made without an image, and the reason is said once."""
    booklet = exam_items.Booklet(tmp_path / "missing.pdf")

    assert booklet.figure(SilentClient({}), Position(1, 1)) is None
    assert booklet.error


# ── The scanned booklet ───────────────────────────────────────────────────────
#
# The 2012 booklets are scans with no drawing objects: figures come from the
# printed frames, sections and items from one vision call.

def _scan(monkeypatch, blocks, page_map, pages=5):
    """Sets up a booklet whose every page is an image, and hands back (booklet, client).

    `blocks`: each page's frames grouped by item, as `pdf_figures.scanned_items`
    returns them.
    """
    monkeypatch.setattr(exam_items.pdf_source, "load_pdf", lambda p: b"%PDF-fake")
    monkeypatch.setattr(exam_items.pdf_figures, "pages_with_figures", lambda d: [])
    monkeypatch.setattr(exam_items.pdf_figures, "scanned_items", lambda d: blocks)
    from kotogen.generators import pdf_pages

    monkeypatch.setattr(pdf_pages, "page_count", lambda d: pages)
    client = SilentClient({"Pages": page_map})
    monkeypatch.setattr(exam_items.pdf_source, "extract_map",
                        lambda c, d, n, p, **k: c.chat_json_pdf() and page_map)
    return exam_items.Booklet(Path("N4L.pdf")), client


def _items(*groups):
    """The frames of a page, one group per item."""
    return tuple(tuple(group) for group in groups)


def test_a_booklet_with_no_object_goes_through_the_printed_frames(monkeypatch):
    """The measurement picks the route, never the year nor the file name."""
    booklet, client = _scan(
        monkeypatch,
        {4: _items([(0.10, 0.30, 0.15, 0.48)], [(0.34, 0.54, 0.15, 0.48)])},
        [{"section": None, "items": []},
         {"section": None, "items": []},
         {"section": 1, "items": []},
         {"section": None, "items": [{"number": 1, "figure": True},
                                     {"number": 2, "figure": True}]},
         {"section": None, "items": []}])

    booklet._load(client)

    assert not booklet.error, booklet.error
    assert set(booklet._figures) == {Position(1, 1), Position(1, 2)}


def test_the_section_of_a_scan_comes_from_the_title_page(monkeypatch):
    """The section titles sit on unframed pages, so the whole booklet is sent.

    Sending only the framed pages would miss the title of section 3 and file its
    items under section 1.
    """
    booklet, client = _scan(
        monkeypatch,
        {5: _items([(0.10, 0.45, 0.15, 0.85)])},
        [{"section": None, "items": []},
         {"section": 1, "items": []},
         {"section": None, "items": []},
         {"section": 3, "items": []},
         {"section": None, "items": [{"number": 1, "figure": True}]}])

    booklet._load(client)

    assert set(booklet._figures) == {Position(3, 1)}


def test_a_page_that_does_not_tally_with_its_labels_lays_no_figure(monkeypatch):
    """The safeguard left when sections and items come from the same call.

    The ink counts two items, the read three: one is wrong and nothing says
    which, so no figure is laid.
    """
    booklet, client = _scan(
        monkeypatch,
        {4: _items([(0.10, 0.30, 0.15, 0.48)], [(0.34, 0.54, 0.15, 0.48)])},
        [{"section": 1, "items": []}, {"section": None, "items": []},
         {"section": None, "items": []},
         {"section": None, "items": [{"number": 1, "figure": True},
                                     {"number": 2, "figure": True},
                                     {"number": 3, "figure": True}]},
         {"section": None, "items": []}])

    booklet._load(client)

    assert booklet._figures == {}, "a figure was laid by guesswork"


def test_the_ink_wins_over_the_figure_flag(monkeypatch):
    """Two items of four drawings, the read flagging a figure on the second only.

    Ink and read both count two items, so they pair one by one and the flag is
    what is wrong: item 2 must not take the drawings of item 1 too.
    """
    grid_1 = [(0.11, 0.29, 0.16, 0.49), (0.11, 0.29, 0.51, 0.84),
              (0.31, 0.48, 0.16, 0.49), (0.31, 0.48, 0.51, 0.84)]
    grid_2 = [(0.53, 0.71, 0.16, 0.49), (0.53, 0.71, 0.51, 0.84),
              (0.73, 0.90, 0.16, 0.49), (0.73, 0.90, 0.51, 0.84)]
    booklet, client = _scan(
        monkeypatch,
        {4: _items(grid_1, grid_2)},
        [{"section": 1, "items": []}, {"section": None, "items": []},
         {"section": None, "items": []},
         {"section": None, "items": [{"number": 1, "figure": False},
                                     {"number": 2, "figure": True}]},
         {"section": None, "items": []}])

    booklet._load(client)

    assert set(booklet._figures) == {Position(1, 1), Position(1, 2)}
    (_page, first), (_p, second) = (booklet._figures[Position(1, 1)],
                                    booklet._figures[Position(1, 2)])
    assert first[1] < second[0], "the two items share the same area"
    assert first[1] < 0.5, f"item 1 took the drawings of item 2: {first}"


def test_the_example_beside_an_item_lays_nothing(monkeypatch):
    """A drawn 「れい」 is framed like an item and is not one.

    The read leaves it out, so the page has one block more than items and nothing
    says which is the example: pairing in order would give it to the item.
    """
    booklet, client = _scan(
        monkeypatch,
        {4: _items([(0.11, 0.45, 0.16, 0.84)], [(0.53, 0.88, 0.16, 0.84)])},
        [{"section": 3, "items": []}, {"section": None, "items": []},
         {"section": None, "items": []},
         {"section": None, "items": [{"number": 1, "figure": True}]},
         {"section": None, "items": []}])

    booklet._load(client)

    assert booklet._figures == {}


def test_a_drawn_example_listed_as_such_keeps_its_drawing_from_item_1(monkeypatch):
    """The shape of a 発話表現 section: the title page holds the drawn example
    alone, the next pages two items each."""
    booklet, client = _scan(
        monkeypatch,
        {2: _items([(0.20, 0.50, 0.16, 0.84)]),
         3: _items([(0.11, 0.48, 0.18, 0.85)], [(0.54, 0.91, 0.18, 0.85)])},
        [{"section": None, "items": []},
         {"section": 4, "items": [{"number": None, "figure": True, "example": True}]},
         {"section": None, "items": [{"number": 1, "figure": True},
                                     {"number": 2, "figure": True}]}],
        pages=3)

    booklet._load(client)

    assert set(booklet._figures) == {Position(4, 1), Position(4, 2)}
    assert booklet._figures[Position(4, 1)][0] == 3, "item 1 took the example's drawing"


def test_an_example_in_words_shifts_nothing(monkeypatch):
    """The shape of a 課題理解 section: an example in words, then a page whose
    first item alone is drawn."""
    booklet, client = _scan(
        monkeypatch,
        {3: _items([(0.11, 0.48, 0.18, 0.85)])},
        [{"section": None, "items": []},
         {"section": 1, "items": [{"number": None, "figure": False, "example": True}]},
         {"section": None, "items": [{"number": 1, "figure": True},
                                     {"number": 2, "figure": False}]}],
        pages=3)

    booklet._load(client)

    assert set(booklet._figures) == {Position(1, 1)}


def test_two_figures_for_one_item_leave_their_section_without_any(monkeypatch):
    """The read numbered the section wrongly, and nothing says which is right;
    another section keeps its figures."""
    booklet, client = _scan(
        monkeypatch,
        {1: _items([(0.20, 0.50, 0.16, 0.84)]),
         3: _items([(0.11, 0.48, 0.18, 0.85)], [(0.54, 0.91, 0.18, 0.85)]),
         4: _items([(0.11, 0.48, 0.18, 0.85)])},
        [{"section": 4, "items": [{"number": 1, "figure": True}]},
         {"section": None, "items": []},
         {"section": None, "items": [{"number": 1, "figure": True},
                                     {"number": 2, "figure": True}]},
         {"section": 5, "items": [{"number": 1, "figure": True}]}],
        pages=4)

    booklet._load(client)

    assert set(booklet._figures) == {Position(5, 1)}


def test_a_scan_without_a_single_frame_says_so(monkeypatch):
    """Neither objects nor frames: there is nothing to cut, and the reason is said."""
    booklet, client = _scan(monkeypatch, {}, [])

    booklet._load(client)

    assert exam_items.NO_FIGURE_PAGE in booklet.error


def test_an_item_without_a_figure_does_not_take_its_neighbours_frame(monkeypatch):
    """Options written out in words want no image.

    Item 3 is spelled out and item 4 carries the page's only frame: counting
    both would cut that frame in two.
    """
    booklet, client = _scan(
        monkeypatch,
        {4: _items([(0.38, 0.75, 0.16, 0.84)])},
        [{"section": 1, "items": []}, {"section": None, "items": []},
         {"section": None, "items": []},
         {"section": None, "items": [{"number": 3, "figure": False},
                                     {"number": 4, "figure": True}]},
         {"section": None, "items": []}])

    booklet._load(client)

    assert set(booklet._figures) == {Position(1, 4)}
    page, area = booklet._figures[Position(1, 4)]
    assert area[1] - area[0] > 0.3, f"the frame was cut: {area}"


# ── Which exercise a downloaded section is drawn from ─────────────────────────
# The official file names only the section (`N5Q1.mp3`, the whole 問題1); the
# rank of the item comes from the sound, as the split read it.

def target_and_track():
    from kotogen.generators import jlpt_papers

    target = jlpt_papers.resolve("jlpt-n5")
    return jlpt_papers, target, jlpt_papers.Track(1, "http://example.test/N5Q1.mp3")


def block(item):
    from kotogen.generators import audio_split

    return audio_split.Block((1,), ((0.0, 10.0),), item)


def test_a_passage_with_no_announced_number_has_no_figure(monkeypatch, tmp_path):
    """Without a rank no figure can be picked, so the booklet is not downloaded."""
    from kotogen.generators import audio_files, jlpt_papers

    def never(*a, **k):
        raise AssertionError("the booklet must not be fetched")

    monkeypatch.setattr(jlpt_papers, "figures_booklet", never)
    assert audio_files._passage_figure(None, target_and_track(), block(None), {}, tmp_path) is None


def test_another_distant_source_looks_for_no_figure(monkeypatch, tmp_path):
    """A podcast numbers its passages like a collection, but has no booklet."""
    from kotogen.generators import audio_files, podcast

    distant = (podcast, object(), object())
    assert audio_files._passage_figure(None, distant, block(3), {}, tmp_path) is None
    assert audio_files._passage_figure(None, None, block(3), {}, tmp_path) is None


def test_the_section_comes_from_the_track_and_the_item_from_the_sound(monkeypatch, tmp_path):
    from kotogen.generators import audio_files, jlpt_papers

    booklet = tmp_path / "N5L.pdf"
    booklet.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(jlpt_papers, "figures_booklet", lambda target: booklet)
    seen = []
    monkeypatch.setattr(audio_files, "_figure",
                        lambda client, path, position, booklets, out, readable:
                        seen.append((path, position, readable)) or None)

    audio_files._passage_figure(None, target_and_track(), block(3), {}, tmp_path)

    assert seen == [(booklet, Position(1, 3), "N5_問題1_3")]


def test_an_unreachable_listening_booklet_does_not_bring_the_pass_down(
        monkeypatch, tmp_path, capsys):
    """The card is made without an image, the reason is said, the batch goes on."""
    from kotogen.generators import audio_files, jlpt_papers

    def falls(target):
        raise RuntimeError("site unreachable")

    monkeypatch.setattr(jlpt_papers, "figures_booklet", falls)
    assert audio_files._passage_figure(None, target_and_track(), block(3), {}, tmp_path) is None
    assert "unreachable" in capsys.readouterr().err


def test_an_unusable_booklet_is_said_by_the_first_line_of_its_reason(
        monkeypatch, tmp_path, capsys):
    """Its reason is an exception's, the model's answer below it: not an English
    sentence to look up, and not a dump for the screen."""
    from kotogen.generators import audio_files

    class Unreadable:
        def __init__(self, path):
            self.error = ""

        def figure(self, client, position):
            self.error = 'the map did not read\n{"Pages": "the raw answer"}'
            return None

    monkeypatch.setattr(exam_items, "Booklet", Unreadable)
    assert audio_files._figure(None, tmp_path / "N5L.pdf", Position(1, 3), {},
                               tmp_path, "N5_1_3") is None
    said = capsys.readouterr().err
    assert "the map did not read" in said and "raw answer" not in said


def test_a_past_paper_gives_its_level_to_its_cards():
    """A past paper states its level: its cards take it rather than an estimate."""
    from kotogen.generators import audio_files

    assert audio_files._set_level(Path("N5Q1.mp3"), target_and_track()) == "N5"
    assert audio_files._set_level(Path("N4_sample2018-4_3.mp3"), None) == "N4"
    assert audio_files._set_level(Path("episode_12.mp3"), None) == ""


# ── The type of the exercise, and what is done with it ────────────────────────
# 発話表現 and 即時応答 are not conversations but a prompt and three lines to
# choose from: rendered as a dialogue, they make a wrong card.


@pytest.mark.parametrize("level, section, expected_type", [
    ("N5", 3, "発話表現"),
    ("N5", 4, "即時応答"),
    ("N4", 3, "発話表現"),
    ("N4", 4, "即時応答"),
    ("N3", 4, "発話表現"),
    ("N3", 5, "即時応答"),
    ("N2", 4, "即時応答"),
    ("N1", 4, "即時応答"),
    ("n4", 1, "課題理解"),          # the case of the level does not count
])
def test_the_section_gives_the_type_of_the_exercise(level, section, expected_type):
    assert exam_items.section_type(level, section) == expected_type


@pytest.mark.parametrize("level, section", [
    ("N5", 5),      # the N5 has only four sections
    ("N3", 6),
    ("N3", 0),
    ("", 1),
    ("N9", 1),
])
def test_a_section_that_is_not_known_gives_no_type(level, section):
    """The type picks the card's shape: an unknown section gets none, not a guess."""
    assert exam_items.section_type(level, section) == ""


def test_the_number_of_sections_agrees_with_the_table_of_collections():
    """`COLLECTIONS` and `TYPES` must count the same sections per level: one more
    on either side gives an empty type, and a card on the wrong template."""
    from kotogen.generators import jlpt_papers

    for collection in jlpt_papers.COLLECTIONS.values():
        if not collection.per_section:
            continue
        for level, sections in collection.sections.items():
            assert len(sections) == len(exam_items.TYPES[level]), (collection.key, level)


# An 即時応答 item, as Whisper renders it: the shape measured on the N4 of the
# 2009 collection, in words of our own.
ERRAND = [
    "1番 これから図書館に行くんですが何か返しておきましょうか",
    "1 いいですよ",
    "2 そうですか残念ですね",
    "3 あっじゃあこの本お願いします",
]

# A 発話表現 item where Whisper cuts each option in two (the shape of the 2012
# N3 問題4, in words of our own): the numbered lines are not the last three.
DARK_ROOM = [
    "1番 少し寒いのでドアを閉めたいです",
    "先生に何と言いますか",
    "1 あのー", "ドアを閉めてもいいですか",
    "2 あのー", "ドアを閉めてください",
    "3 あのー", "ドアを閉めましょう",
]


@pytest.mark.parametrize("lines", [ERRAND, DARK_ROOM])
def test_the_shape_of_an_item_with_answers_to_choose_from_is_recognised(lines):
    assert exam_items.looks_like_choice(lines) is True


def test_four_options_are_not_an_item_with_answers_to_choose_from():
    """The 概要理解 reads out four choices after its question: a badly split
    passage, not a choice item."""
    assert exam_items.looks_like_choice([
        "女の人が駅の窓口で話しています",
        "女の人は何をしに来ましたか",
        "1 切符を買いに来た", "2 道を聞きに来た",
        "3 忘れ物を取りに来た", "4 時間を調べに来た",
    ]) is False


@pytest.mark.parametrize("lines", [
    # Numbers glued to their word (a price, a time, a duration) are not options.
    ["A：1000円です", "B：2時に行きます",
     "A：3時間かかります", "B：一緒に行きましょう"],
    # Numbers out of order.
    ["あのー", "2 いいですよ", "1 そうですか", "3 お願いします"],
    # Three options with no prompt.
    ["1 いいですよ", "2 そうですか", "3 お願いします"],
    # An ordinary conversation.
    ["A：おはよう", "B：おはよう", "A：今日は暑いね", "B：そうですね"],
    [],
])
def test_what_is_not_an_item_with_answers_to_choose_from_is_refused(lines):
    assert exam_items.looks_like_choice(lines) is False


# ── Which line the answer was copied from ─────────────────────────────────────

# The item as the model hands it back: the announcing line gone, the prompt cut
# one sentence per line. Reply 2 sits on the fourth line, which is why the rank
# is read off the answer rather than taken on trust.
MOVIE = [
    "週末[しゅうまつ]、 友達[ともだち]と 海[うみ]に 行[い]きたいです。",
    "何[なん]と 言[い]いますか。",
    "1 週末[しゅうまつ] 海[うみ]に 行[い]ってもいいですか",
    "2 週末[しゅうまつ] 海[うみ]に 行[い]きませんか",
    "3 週末[しゅうまつ] 海[うみ]に 行[い]くそうですよ",
]


def test_the_answer_says_which_line_it_was_copied_from():
    assert exam_items.answered_line(MOVIE[3], MOVIE) == 4


@pytest.mark.parametrize("answer", [
    "2週末[しゅうまつ]海[うみ]に行[い]きませんか",   # spacing lost
    "2 週末海に行きませんか",                          # readings dropped
])
def test_the_line_is_found_again_under_another_spelling(answer):
    """A copy may lose a space or a reading: only the written form is compared."""
    assert exam_items.answered_line(answer, MOVIE) == 4


def test_the_option_number_answers_when_the_text_no_longer_matches():
    """A shortened copy is still placed by its number, which opens one line only."""
    assert exam_items.answered_line("2 海[うみ]に 行[い]きませんか",
                                    MOVIE) == 4


@pytest.mark.parametrize("answer", [
    "海[うみ]に 誘[さそ]う",   # neither the text of a line nor a number
    "4 そうしましょう",            # a number no line opens on
    "",
])
def test_what_places_no_line_places_none(answer):
    """A key line on another reply teaches the wrong answer; none only costs a hint."""
    assert exam_items.answered_line(answer, MOVIE) == 0


def test_a_number_carried_by_two_lines_places_nothing():
    """A doubled option: the number no longer names one line, so it places none."""
    lines = ["1 あのー", "1 持[も]ちましょうか", "2 いいですよ"]
    assert exam_items.answered_line("1 持[も]ちますか", lines) == 0


# ── What the listening chain makes of it ──────────────────────────────────────

def test_the_downloaded_section_gives_the_type_without_reading_the_transcript():
    """The N5 問題4 is an 即時応答, whatever its transcription shows."""
    from kotogen.generators import audio_files, jlpt_papers

    source = (jlpt_papers, jlpt_papers.resolve("jlpt-n5"),
              jlpt_papers.Track(4, "http://example.test/N5Q4.mp3"))
    assert audio_files._is_choice(Path("N5_問題4.mp3"), source, ["こんにちは"]) is True


def test_a_section_of_conversations_is_not_an_item_with_answers_to_choose_from():
    """The table wins over the shape: the 問題1 is a 課題理解, whatever its lines."""
    from kotogen.generators import audio_files, jlpt_papers

    source = (jlpt_papers, jlpt_papers.resolve("jlpt-n5"),
              jlpt_papers.Track(1, "http://example.test/N5Q1.mp3"))
    assert audio_files._is_choice(Path("N5_問題1.mp3"), source, ERRAND) is False


def test_a_single_file_collection_falls_back_on_the_shape_of_the_passage():
    """The 2009 collection is one file per exam: its track 1 names no section."""
    from kotogen.generators import audio_files, jlpt_papers

    source = (jlpt_papers, jlpt_papers.resolve("jlpt2009-n4"),
              jlpt_papers.Track(1, "http://example.test/N4Sample.mp3"))
    assert audio_files._is_choice(Path("N4_問題1.mp3"), source, ERRAND) is True


def test_an_item_split_one_by_one_takes_its_type_from_its_name():
    """`N5_sample2018-4_3.mp3` is item 3 of the 問題4, hence an 即時応答."""
    from kotogen.generators import audio_files

    assert audio_files._is_choice(Path("N5_sample2018-4_3.mp3"), None,
                                  ["こんにちは"]) is True
    assert audio_files._is_choice(Path("N5_sample2018-1_3.mp3"), None, ERRAND) is False


def test_any_other_file_falls_back_on_the_shape_of_the_passage():
    from kotogen.generators import audio_files

    assert audio_files._is_choice(Path("Genki_K01-03.mp3"), None, ERRAND) is True
    assert audio_files._is_choice(Path("teppei_ep42.mp3"), None,
                                  ["A：おはよう", "B：おはよう"]) is False


# ── The card that comes out of it: no written option ──────────────────────────
#
# The three lines are the exercise: written on the front in the language of the
# card, they could be answered without a word of Japanese. The back writes the
# right one out.

TRANSLATED_ERRAND = [
    "Je vais à la bibliothèque, je rends quelque chose pour toi ?",
    "1 D'accord.",
    "2 Ah bon, c'est dommage.",
    "3 Ah, alors ce livre, s'il te plaît.",
]


def _choice_card(choice: bool, **raw):
    from kotogen.generators import audio

    card = {"Question": "Que répondre à cette proposition ?",
            "Answer": "3 あっ、じゃあこの 本[ほん]お 願[ねが]いします",
            "KeyLine": 4, **raw}
    result = {"Level": "N4", "TranscriptLines": list(ERRAND),
              "TranslationLines": list(TRANSLATED_ERRAND), "Cards": [card]}
    return audio._post_process(result, "x.mp3", "x", "N4", choice=choice)[0]


def test_an_item_with_answers_to_choose_from_carries_no_written_option():
    """Even when the model hands some back: the front's options sit under
    `{{#Decoy1}}`."""
    card = _choice_card(True, Decoys=["Lui dire que c'est bon",
                                       "Dire que ça a l'air bon",
                                       "Refuser poliment"])
    assert card["Decoy1"] == card["Decoy2"] == card["Decoy3"] == ""


def test_the_solution_of_a_choice_item_stays_the_japanese_line():
    """Number included: that is what the back writes out in full."""
    card = _choice_card(True)
    assert card["Answer"] == "3 あっ、じゃあこの 本[ほん]お 願[ねが]いします"
    assert card["KeyLine"] == "4"


def test_a_choice_item_asks_the_same_question_everywhere():
    """The exam writes no question: the card asks which reply fits, in the
    language of the cards, whatever the model wrote or left out."""
    from kotogen import prompts
    from kotogen.generators import audio

    expected = prompts.say(audio.CHOICE_QUESTION)
    assert _choice_card(True)["Question"] == expected
    assert _choice_card(True, Question="")["Question"] == expected


def test_elsewhere_the_decoys_are_kept():
    card = _choice_card(False, Decoys=["Un", "Deux", "Trois"])
    assert [card["Decoy1"], card["Decoy2"], card["Decoy3"]] == ["Un", "Deux", "Trois"]


# ── Which card carries the figure ─────────────────────────────────────────────
#
# The figure illustrates the exam's own question; beside the other cards of the
# passage it would answer nothing.

UMBRELLAS = ["A：どの 傘[かさ]にしますか", "B：青[あお]いのにします"]
TRANSLATED_UMBRELLAS = ["A : Quel parapluie prenez-vous ?", "B : Je prends le bleu."]
FIGURE = "N5_Q1_3_2f3a4b5c.png"


def _figured_cards(*marks, choice: bool = False, figure: str = FIGURE, fits=None):
    from kotogen.generators import audio

    cards = [{"Question": f"Question {rank}", "Answer": "Le bleu",
              "Decoys": ["Le rouge", "Le vert", "Le noir"], "KeyLine": 2,
              **({"Figure": mark} if mark is not None else {})}
             for rank, mark in enumerate(marks, 1)]
    result = {"Level": "N5", "TranscriptLines": list(UMBRELLAS),
              "TranslationLines": list(TRANSLATED_UMBRELLAS), "Cards": cards,
              **({"FigureFits": fits} if fits is not None else {})}
    return audio._post_process(result, "x.mp3", "x", "N5", figure=figure,
                               choice=choice)


def test_the_figure_goes_on_the_card_that_asks_the_question_of_the_exam():
    cards = _figured_cards(None, True, None, None)
    assert [bool(card["Image"]) for card in cards] == [False, True, False, False]
    assert FIGURE in cards[1]["Image"]


def test_the_card_of_the_figure_is_answered_on_the_figure():
    """Its drawings are its options: its written decoys go, not the others'."""
    cards = _figured_cards(None, True)
    assert [cards[1]["Decoy1"], cards[1]["Decoy2"], cards[1]["Decoy3"]] == ["", "", ""]
    assert cards[1]["Answer"] == "Le bleu"
    assert cards[0]["Decoy1"] == "Le rouge"


def test_two_cards_marked_give_the_figure_to_the_first_only():
    cards = _figured_cards(True, True)
    assert [bool(card["Image"]) for card in cards] == [True, False]


def test_only_a_true_mark_counts():
    """`"false"` is a string, and a truthy one: the mark is the JSON `true`."""
    cards = _figured_cards("false", False)
    assert not any(card["Image"] for card in cards)


def test_no_card_marked_gives_the_figure_to_none_and_says_so(capsys):
    cards = _figured_cards(None, None)
    assert not any(card["Image"] for card in cards)
    assert "figure" in capsys.readouterr().out


def test_a_choice_item_takes_the_figure_without_being_marked():
    """Its one card is the exercise: there is nothing to mark."""
    (card,) = _figured_cards(None, choice=True)
    assert FIGURE in card["Image"]


def test_no_figure_says_nothing_about_one(capsys):
    cards = _figured_cards(None, figure="")
    assert not cards[0]["Image"]
    assert "figure" not in capsys.readouterr().out


def test_a_figure_cut_out_for_another_item_goes_on_no_card(capsys):
    """The model sees the figure, and says when it shows another conversation."""
    cards = _figured_cards(None, True, fits=False)
    assert not any(card["Image"] for card in cards)
    assert "does not illustrate this passage" in capsys.readouterr().out


def test_a_choice_item_loses_a_picture_that_is_not_its_own():
    (card,) = _figured_cards(None, choice=True, fits=False)
    assert not card["Image"]


def test_a_figure_said_to_fit_or_said_nothing_of_is_laid():
    assert _figured_cards(None, True, fits=True)[1]["Image"]
    assert _figured_cards(None, True)[1]["Image"]


class _Client:
    def __init__(self):
        self.sent = ""
        self.attached = None

    def chat_json(self, system, user):
        self.sent = user
        return {"Cards": []}

    def chat_json_pdf(self, system, user, pdf_bytes, filename):
        self.attached = (pdf_bytes, filename)
        return self.chat_json(system, user)


@pytest.mark.parametrize("figured, choice, instruction", [
    (True, False, "FIGURE_INSTRUCTION"),
    (False, False, None),
    # The choice item's one card takes the picture: only its fit is asked.
    (True, True, "CHOICE_FIGURE_INSTRUCTION"),
])
def test_the_figure_goes_with_the_call_and_the_model_is_told_what_to_do_with_it(
        monkeypatch, figured, choice, instruction):
    from kotogen import prompts
    from kotogen.generators import audio, pdf_pages

    monkeypatch.setattr(pdf_pages, "to_pdf", lambda paths: b"%PDF-" + paths[0].name.encode())
    client = _Client()
    audio._generate_for_audio(client, "x.mp3", UMBRELLAS, 3, "N5", choice,
                              figure=Path(FIGURE) if figured else None)
    for name in ("FIGURE_INSTRUCTION", "CHOICE_FIGURE_INSTRUCTION"):
        assert (prompts.say(getattr(audio, name)) in client.sent) is (name == instruction)
    assert client.attached == ((b"%PDF-" + FIGURE.encode(), "N5_Q1_3_2f3a4b5c.pdf")
                               if figured else None)
