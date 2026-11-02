"""青空文庫 and 青空朗読: the filters of the collection, and the collection read aloud.

No network: the index and the catalogue of readings are built here. The filters
matter most, as they keep out the orthography abandoned in 1946.
"""

from __future__ import annotations

import csv
import io
import zipfile

import pytest

from kotogen.generators import aozora, aozora_roudoku as roudoku, sources

COLUMNS = ["作品ID", "作品名", "分類番号", "文字遣い種別", "作品著作権フラグ",
           "図書カードURL", "姓", "名", "役割フラグ", "XHTML/HTMLファイルURL"]


def _work(**fields) -> dict:
    """A valid index row, of which we change only what we are proving."""
    row = {
        "作品ID": "000628", "作品名": "ごん狐", "分類番号": "NDC K913",
        "文字遣い種別": "新字新仮名", "作品著作権フラグ": "なし",
        "図書カードURL": "https://www.aozora.gr.jp/cards/000121/card628.html",
        "姓": "新美", "名": "南吉", "役割フラグ": "著者",
        "XHTML/HTMLファイルURL":
            "https://www.aozora.gr.jp/cards/000121/files/628_14895.html",
    }
    row.update(fields)
    return row


def index(rows: list[dict]) -> bytes:
    """The archive the site publishes, as `_read_csv` receives it."""
    text = io.StringIO(newline="")
    pen = csv.DictWriter(text, fieldnames=COLUMNS)
    pen.writeheader()
    pen.writerows(rows)
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w") as archive:
        archive.writestr("list_person_all_extended_utf8.csv",
                         text.getvalue().encode("utf-8"))
    return memory.getvalue()


# -- The filters of the index -------------------------------------------------

def test_an_ordinary_work_gets_through():
    works = aozora._read_csv(index([_work()]))
    assert len(works) == 1
    assert works[0].title == "ごん狐" and works[0].author == "新美 南吉"


def test_an_archive_with_no_list_says_so_in_plain_words():
    """A learner reads it: the site's list of works, not "the CSV of the index"."""
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w") as archive:
        archive.writestr("readme.txt", b"")
    with pytest.raises(RuntimeError) as raised:
        aozora._read_csv(memory.getvalue())
    assert "list of works" in str(raised.value) and "CSV" not in str(raised.value)


def test_an_archive_that_unpacks_past_the_cap_is_not_read(monkeypatch):
    """A few megabytes of zip can unpack to gigabytes: that is not the index."""
    monkeypatch.setattr(aozora, "MAX_INDEX", 1024)
    with pytest.raises(RuntimeError, match="list of works"):
        aozora._read_csv(index([_work() for _ in range(20)]))


@pytest.mark.parametrize("orthography", ["新字旧仮名", "旧字旧仮名", "旧字新仮名"])
def test_the_orthography_from_before_1946_is_discarded(orthography):
    """けふ for きょう, 舊 for 旧: an obsolete spelling nothing would flag to a learner."""
    assert aozora._read_csv(index([_work(文字遣い種別=orthography)])) == []


def test_a_translator_does_not_republish_the_work():
    # Otherwise the same work would appear twice in the menu.
    assert aozora._read_csv(index([_work(役割フラグ="翻訳者")])) == []


def test_a_work_still_in_copyright_is_discarded():
    assert aozora._read_csv(index([_work(作品著作権フラグ="あり")])) == []


def test_a_work_with_no_xhtml_page_is_discarded():
    """The text file writes readings as 漢字《かんじ》, which the generic route
    does not know and would put on the card as it is."""
    assert aozora._read_csv(index([_work(**{"XHTML/HTMLファイルURL": ""})])) == []


# -- The shelves --------------------------------------------------------------

def test_the_children_classmark_files_on_the_children_shelf():
    works = aozora._read_csv(index([
        _work(),                                       # NDC K913
        _work(作品ID="000001", 作品名="檸檬", 分類番号="NDC 913"),
    ]))
    children = aozora.shelf(works, "children")
    literature = aozora.shelf(works, "literature")
    assert [w.title for w in children] == ["ごん狐"]
    assert [w.title for w in literature] == ["檸檬"]


def test_the_best_stocked_authors_open_the_list():
    """多読 stays with one author: the menu opens on those with the most works."""
    works = aozora._read_csv(index([
        _work(作品ID="1", 作品名="A", 姓="小川", 名="未明"),
        _work(作品ID="2", 作品名="B", 姓="小川", 名="未明"),
        _work(作品ID="3", 作品名="C"),
    ]))
    authors = aozora.by_author(works)
    assert [name for name, _works in authors] == ["小川 未明", "新美 南吉"]
    assert [w.title for w in authors[0][1]] == ["A", "B"]


def test_the_whole_library_opens_on_the_easier_shelf_and_says_its_level():
    """A list mixing both shelves puts the children first, each work carrying
    the estimate of its shelf and nothing finer."""
    works = aozora._read_csv(index([
        _work(作品ID="1", 作品名="檸檬", 分類番号="NDC 913"),
        _work(作品ID="2", 作品名="ごん狐"),
        _work(作品ID="3", 作品名="あの時", 分類番号="NDC 914"),
    ]))
    ordered = aozora.by_shelf(works)
    assert [w.title for w in ordered] == ["ごん狐", "あの時", "檸檬"]
    assert [aozora.level_of(w) for w in ordered] == ["N3-N2", "N1", "N1"]


def test_the_search_bears_on_the_title_and_on_the_author():
    works = aozora._read_csv(index([_work()]))
    assert aozora.search(works, "ごん")
    assert aozora.search(works, "南吉")
    assert not aozora.search(works, "賢治")
    assert not aozora.search(works, "")


# -- Resolving an address -----------------------------------------------------

@pytest.fixture
def works(monkeypatch):
    monkeypatch.setattr(aozora.download, "page",
                        lambda url, **kwargs: index([_work()]))
    return aozora.catalogue(refresh=True)


def test_a_card_is_turned_into_the_page_of_the_text(works):
    """The address one has is usually the card's, but the text is on the other
    page."""
    url, work = aozora.resolve(
        "https://www.aozora.gr.jp/cards/000121/card628.html")
    assert url.endswith("628_14895.html")
    assert work.title == "ごん狐"


def test_the_padded_number_of_the_index_finds_the_one_of_the_address(works):
    """The index writes "000628", the addresses "card628": without normalising,
    a pasted card would miss its history."""
    _url, work = aozora.resolve(
        "https://www.aozora.gr.jp/cards/000121/files/628_14895.html")
    assert work is not None and work.work_id == "000628"


def test_a_page_outside_the_catalogue_is_read_all_the_same(works):
    url = "https://www.aozora.gr.jp/cards/000999/files/99999_1.html"
    address, work = aozora.resolve(url)
    assert address == url and work is None


def test_a_handled_work_enters_the_history(works):
    work = works[0]
    assert work.work_id not in aozora.load_seen()
    aozora.mark_seen(work)
    assert aozora.load_seen()[work.work_id] == "ごん狐"


def test_an_address_outside_the_catalogue_marks_nothing():
    aozora.mark_seen(None)
    assert aozora.load_seen() == {}


def test_a_cache_of_an_older_layout_is_read_again_from_the_site(monkeypatch):
    """Its entries carry one field more (the address of the book card): taken as
    they are, they would not build a work."""
    import json
    import time

    aozora.index_file().parent.mkdir(parents=True, exist_ok=True)
    aozora.index_file().write_text(json.dumps({
        "date": time.time(),
        "works": [["000628", "ごん狐", "新美 南吉", "NDC K913",
                   "https://www.aozora.gr.jp/cards/000121/files/628_14895.html",
                   "https://www.aozora.gr.jp/cards/000121/card628.html"]],
    }), encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(aozora.download, "page",
                        lambda url, **kwargs: calls.append(url) or index([_work()]))

    works = aozora.catalogue()

    assert calls == [aozora.INDEX_URL]
    assert [work.title for work in works] == ["ごん狐"]


def test_a_card_linking_off_the_web_gives_no_text_page(monkeypatch):
    """The card is read from the site, but its link is followed by a route that
    would open a file of this machine as readily."""
    card = b'<a href="file:///C:/files/1_1.html">XHTML</a>'
    monkeypatch.setattr(aozora.download, "page",
                        lambda url, **kwargs: (index([_work()]) if url == aozora.INDEX_URL
                                               else card))
    with pytest.raises(RuntimeError, match="no text page"):
        aozora.resolve("https://www.aozora.gr.jp/cards/000999/card999.html")


def test_an_unreachable_index_gives_an_empty_menu_and_not_a_breakdown(monkeypatch):
    def falls(url, **kwargs):
        raise RuntimeError("site unreachable")
    monkeypatch.setattr(aozora.download, "page", falls)
    assert aozora.catalogue(refresh=True) == []


# -- 青空朗読 ------------------------------------------------------------------

LIST = """
<li><p><a href="../voice/rdp/rd558.html" target="_blank">
<span class="listTitle">私の好きなロマンス中の女性</span>
<span class="listData">著者：芥川 龍之介　読み手：森 さくら　時間：37秒</span>
</a></p></li>
<li><p><a href="../voice/rdp/rd001.html" target="_blank">
<span class="listTitle">よだかの星</span>
<span class="listData">著者：宮沢 賢治　読み手：原田 ゆう　時間：19分47秒</span>
</a></p></li>
<li><p><a href="../voice/rdp/rd991.html" target="_blank">
<span class="listTitle">あのときの王子くん</span>
<span class="listData">著者：サン＝テグジュペリ　読み手：木村 あや　時間：2時間34分56秒</span>
</a></p></li>
"""


@pytest.fixture
def readings(monkeypatch):
    monkeypatch.setattr(roudoku.download, "page",
                        lambda url, **kwargs: LIST.encode("utf-8"))
    return roudoku.catalogue(refresh=True)


def test_the_collection_reads_with_its_durations(readings):
    assert [x.reading_id for x in readings] == ["rd558", "rd001", "rd991"]
    assert [x.duration for x in readings] == [37.0, 1187.0, 9296.0]
    assert readings[1].title == "よだかの星" and readings[1].author == "宮沢 賢治"


def test_the_file_follows_from_the_identifier(readings):
    assert readings[0].mp3 == "https://aozoraroudoku.jp/voice/mp3/rd558.mp3"
    assert readings[0].page == "https://aozoraroudoku.jp/voice/rdp/rd558.html"


def test_the_longest_reading_fits_under_the_cap_of_its_download(monkeypatch, readings):
    """Two and a half hours weigh 93 MB on the site, past the default cap."""
    limits: list[int] = []
    monkeypatch.setattr(roudoku.download, "file",
                        lambda url, dest, **kwargs: limits.append(kwargs["limit"]) or dest)

    roudoku.fetch(roudoku.Library(), readings[-1])

    assert limits[0] > 93 * 1024 * 1024


def test_the_shortest_ones_first(readings):
    kept, done, discarded = roudoku.to_do(2)
    assert [x.reading_id for x in kept] == ["rd558", "rd001"]
    assert done == 0 and discarded == 0


def test_the_duration_discards_before_the_download(readings):
    """The catalogue carries the durations: no long mp3 is pulled for nothing."""
    kept, _done, discarded = roudoku.to_do(5, limit=1200)
    assert [x.reading_id for x in kept] == ["rd558", "rd001"]
    assert discarded == 1


def test_a_handled_reading_does_not_come_back(readings):
    roudoku.mark_done(roudoku.Library(), readings[0])
    kept, done, _discarded = roudoku.to_do(1)
    assert kept[0].reading_id == "rd001" and done == 1


def test_a_pasted_address_names_one_reading(readings):
    _works, reading = roudoku.resolve("https://aozoraroudoku.jp/voice/rdp/rd001.html")
    assert reading.title == "よだかの星"


def test_a_reading_newer_than_the_catalogue_stays_reachable(readings):
    """We lose its title and its duration, not the card: the file follows from
    the address."""
    _works, reading = roudoku.resolve("https://aozoraroudoku.jp/voice/rdp/rd9999.html")
    assert reading.reading_id == "rd9999"
    assert reading.mp3.endswith("rd9999.mp3")


@pytest.mark.parametrize("entry", [
    "roudoku", "aozora-roudoku", "https://aozoraroudoku.jp/voice/rdp/rd020.html",
])
def test_it_recognises_the_collection(entry):
    assert roudoku.is_roudoku_input(entry)


@pytest.mark.parametrize("entry", ["", "teppei", "https://www.aozora.gr.jp/"])
def test_it_ignores_what_is_not_one(entry):
    assert not roudoku.is_roudoku_input(entry)


def test_the_pointer_points_at_the_page_carrying_the_text(readings):
    assert roudoku.link(roudoku.Library(), readings[0]) == readings[0].page


# -- Wiring into the reading route --------------------------------------------

def test_an_address_of_the_collection_becomes_a_followed_source(works):
    """The card is turned at RESOLUTION time, once, before any network."""
    resolved = sources.text_sources(
        ["https://www.aozora.gr.jp/cards/000121/card628.html"],
        mode="reading", latest=1, furigana=True, whole=True)
    assert len(resolved) == 1
    source = resolved[0]
    assert isinstance(source, sources.AozoraWork)
    assert source.origin.endswith("628_14895.html")
    assert source.label == "ごん狐 - 新美 南吉"
    assert source.tracking_key  # a long work is picked up where it was left


def test_a_work_that_gave_cards_enters_the_history(works):
    source = sources.text_sources(
        ["https://www.aozora.gr.jp/cards/000121/card628.html"],
        mode="reading", latest=1, whole=True)[0]
    source.mark_done("ごん狐")
    assert aozora.load_seen() == {"000628": "ごん狐"}


def test_an_unreachable_collection_does_not_carry_off_the_source(monkeypatch):
    """The page is still read, like any address, only outside the history."""
    def falls(url, **kwargs):
        raise RuntimeError("site unreachable")
    monkeypatch.setattr(aozora.download, "page", falls)
    url = "https://www.aozora.gr.jp/cards/000121/card628.html"
    source = sources.text_sources([url], mode="reading", latest=1, whole=True)[0]
    assert source.origin == url and source.work is None


def test_any_page_at_all_stays_any_page_at_all():
    source = sources.text_sources(["https://example.jp/article"], mode="reading",
                                  latest=1, whole=True)[0]
    assert type(source) is sources.GenericText


def test_the_progress_is_followed_under_the_number_of_the_work(works):
    """A key drawn from the URL works but does not read: the screen where one
    forgets a reading would show a fingerprint."""
    from kotogen.interactive.history import _source_labels

    source = sources.text_sources(
        ["https://www.aozora.gr.jp/cards/000121/card628.html"],
        mode="reading", latest=1, whole=True)[0]
    assert source.tracking_key == "aozora-000628"
    assert _source_labels(["aozora-000628"]) == {"aozora-000628": "ごん狐 (青空文庫)"}


def test_a_work_outside_the_catalogue_keeps_the_key_of_its_address(monkeypatch):
    def falls(url, **kwargs):
        raise RuntimeError("site unreachable")
    monkeypatch.setattr(aozora.download, "page", falls)
    source = sources.text_sources(
        ["https://www.aozora.gr.jp/cards/000121/files/628_14895.html"],
        mode="reading", latest=1, whole=True)[0]
    assert source.tracking_key.startswith("www-aozora-gr-jp-")


# -- The deck as a second memory ----------------------------------------------
# With the local history alone, a second machine or a cleared history would
# redo, and pay again for, cards the deck already carries.

def _deck(*traces: str, mode: str = "audio"):
    from kotogen.known import Sources as DeckSources
    return DeckSources({mode: frozenset(traces)})


def test_a_reading_the_deck_already_carries_does_not_come_back(monkeypatch, readings):
    from kotogen import memory

    monkeypatch.setattr(memory.known(), "_sources", _deck(
        "青空朗読 - 私の好きなロマンス中の女性 - 芥川 龍之介 (00:12 → 00:45)"))
    kept, done, _discarded = roudoku.to_do(2)
    assert [x.reading_id for x in kept] == ["rd001", "rd991"]
    assert done == 1


@pytest.mark.parametrize("trace, expected", [
    ("青空朗読 - よだかの星 - 宮沢 賢治 (00:12 → 00:45) "
     "https://aozoraroudoku.jp/voice/rdp/rd001.html", ("roudoku", "rd001")),
    ("青空朗読 - あのときの王子くん - サン＝テグジュペリ", ("roudoku", "rd991")),
    # A reading not in the collection, and another source: nothing.
    ("青空朗読 - 銀河鉄道の夜 - 宮沢 賢治", None),
    ("Nihongo con Teppei - Ep 700", None),
    ("", None),
])
def test_a_provenance_says_which_reading_it_comes_from(trace, expected, readings):
    """Through the catalogue: the card carries the title and the author, not the
    identifier (`rd001`)."""
    assert roudoku.recognise(trace) == expected


def test_an_unreachable_collection_recognises_nothing_rather_than_inventing(
        monkeypatch):
    def falls(url, **kwargs):
        raise RuntimeError("site unreachable")
    monkeypatch.setattr(roudoku.download, "page", falls)
    monkeypatch.setattr(roudoku, "_read_cache", lambda: None)
    assert roudoku.recognise("青空朗読 - よだかの星 - 宮沢 賢治") is None


@pytest.mark.parametrize("trace, expected", [
    ("https://www.aozora.gr.jp/cards/000121/files/628_14895.html (p. 3-)",
     ("aozora", "000628")),
    # The card too: it is the one pasted by hand, and the card keeps it.
    ("https://www.aozora.gr.jp/cards/000121/card628.html", ("aozora", "000628")),
    # From the site, but not a work; a work outside the catalogue; something else.
    ("https://www.aozora.gr.jp/index_pages/person121.html", None),
    ("https://www.aozora.gr.jp/cards/000035/files/1567_14913.html", None),
    ("https://tadoku.org/japanese/book/6346/", None),
    ("", None),
])
def test_a_provenance_says_which_work_it_comes_from(trace, expected, works):
    """The number padded to six digits, as `mark_seen` writes it, or the same
    work would enter the history twice."""
    assert aozora.recognise(trace) == expected
