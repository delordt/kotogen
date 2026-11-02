"""Tests of the PDF source: recognising the inputs, loading the file and the
extraction contracts (the AI client is simulated - no network call)."""

import pytest

from kotogen.generators import pdf_source


class FakeClient:
    """Stands in for AIClient: returns a canned JSON result and records the calls."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def chat_json_pdf(self, system, user, pdf_bytes, filename="document.pdf"):
        self.calls.append({"system": system, "user": user, "filename": filename})
        return self.result


# -- Recognising --------------------------------------------------------------

@pytest.mark.parametrize("entry", [
    "N4V.pdf",
    r"C:\Users\me\Desktop\N4V.pdf",
    '"C:\\folder with spaces\\course.PDF"',
    "  papers.Pdf  ",
])
def test_is_pdf_input_accepts_pdf_paths(entry):
    assert pdf_source.is_pdf_input(entry)


@pytest.mark.parametrize("entry", [
    "食べる",
    "nhk",
    "https://news.web.nhk/news/easy/ne1/ne1.html",
    "words.md",
    "",
])
def test_is_pdf_input_rejects_other_inputs(entry):
    assert not pdf_source.is_pdf_input(entry)


def test_clean_path_strips_quotes():
    assert str(pdf_source.clean_path('"course.pdf"')) == "course.pdf"


# -- Loading ------------------------------------------------------------------

def test_load_pdf_missing_file(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        pdf_source.load_pdf(tmp_path / "absent.pdf")


def test_load_pdf_rejects_non_pdf(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"not a pdf")
    with pytest.raises(RuntimeError, match="not a valid PDF"):
        pdf_source.load_pdf(fake)


def test_load_pdf_rejects_oversized(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_source, "MAX_PDF_BYTES", 10)
    big = tmp_path / "big.pdf"
    big.write_bytes(b"%PDF-1.7 and a good deal more than ten bytes")
    with pytest.raises(RuntimeError, match="too large"):
        pdf_source.load_pdf(big)


def test_load_pdf_returns_bytes(tmp_path):
    doc = tmp_path / "ok.pdf"
    doc.write_bytes(b"%PDF-1.7 content")
    assert pdf_source.load_pdf(doc) == b"%PDF-1.7 content"


# -- The shared error contract ------------------------------------------------

@pytest.mark.parametrize("extract", [
    lambda c: pdf_source.extract_vocab(c, b"%PDF", "doc.pdf", 0, "auto"),
    lambda c: pdf_source.extract_texts(c, b"%PDF", "doc.pdf", None),
    lambda c: pdf_source.extract_reading(c, b"%PDF", "doc.pdf", 12),
    lambda c: pdf_source.extract_mode_and_texts(c, b"%PDF", "doc.pdf", 12),
])
def test_error_contract_raises_with_reason(extract):
    client = FakeClient({"error": "document in Korean, no Japanese"})
    with pytest.raises(RuntimeError, match="document in Korean"):
        extract(client)


# -- Vocabulary ---------------------------------------------------------------

def test_extract_vocab_returns_clean_words():
    client = FakeClient(["言葉", "  続く ", "", "涼しい"])
    words = pdf_source.extract_vocab(client, b"%PDF", "doc.pdf", 0, "auto")
    assert words == ["言葉", "続く", "涼しい"]


def test_extract_vocab_count_limits_and_shows_in_prompt():
    client = FakeClient(["一", "二", "三", "四"])
    words = pdf_source.extract_vocab(client, b"%PDF", "doc.pdf", 2, "N4")
    assert words == ["一", "二"]
    assert "at most 2" in client.calls[0]["user"]
    assert "N4" in client.calls[0]["user"]


def test_extract_vocab_no_count_asks_for_maximum():
    client = FakeClient(["一"])
    pdf_source.extract_vocab(client, b"%PDF", "doc.pdf", 0, "auto")
    assert "MAXIMUM" in client.calls[0]["user"]


def test_extract_vocab_rejects_unexpected_json():
    client = FakeClient({"words": ["一"]})
    # The kind by its name, in the sentence every generator says it with.
    with pytest.raises(ValueError, match="^unexpected JSON structure: dict$"):
        pdf_source.extract_vocab(client, b"%PDF", "doc.pdf", 0, "auto")


# -- Reading ------------------------------------------------------------------

def test_extract_texts_normalises_and_limits():
    client = FakeClient([
        {"title": "手紙[てがみ]", "lines": ["一行目。", " 二行目。 ", ""]},
        {"title": "", "lines": []},              # no lines: ignored
        {"title": "メール", "lines": ["こんにちは。"]},
    ])
    texts = pdf_source.extract_texts(client, b"%PDF", "doc.pdf", None)
    assert texts == [
        pdf_source.Text("手紙[てがみ]", ["一行目。", "二行目。"]),
        pdf_source.Text("メール", ["こんにちは。"]),
    ]
    assert pdf_source.extract_texts(client, b"%PDF", "doc.pdf", 1) == texts[:1]


def test_extract_texts_wraps_single_object():
    client = FakeClient({"title": "お知らせ", "lines": ["明日[あした]は 休[やす]みです。"]})
    texts = pdf_source.extract_texts(client, b"%PDF", "doc.pdf", None)
    assert texts == [pdf_source.Text("お知らせ", ["明日[あした]は 休[やす]みです。"])]


def test_the_document_nature_is_kept():
    """The 情報検索 asks its question about a poster or a table: the layout makes
    the exercise, and the card will show it as an image rather than flat."""
    client = FakeClient([
        {"kind": "document", "title": "「夏[なつ]の 町[まち]まつり」",
         "lines": ["おどりの 会[かい]　7/20"]},
    ])
    assert pdf_source.extract_texts(client, b"%PDF", "N4R.pdf", None)[0].document


def test_an_answer_with_no_nature_describes_prose():
    """Saying nothing means "text": a default leaning to the image would show as
    photos articles that read perfectly well in lines."""
    client = FakeClient([{"title": "手紙[てがみ]", "lines": ["一行目。"]}])
    assert not pdf_source.extract_texts(client, b"%PDF", "doc.pdf", None)[0].document


# -- Reading as a mini-book ---------------------------------------------------

def test_extract_reading_gives_back_one_single_reading():
    """A book's pages form one text, and the model is told the number of pages so
    that it knows where it stops."""
    client = FakeClient({"title": "かえるの 話[はなし]",
                         "lines": ["一行目。", "  二行目。 ", ""]})
    reading = pdf_source.extract_reading(client, b"%PDF", "book.pdf", 12)
    assert reading.title == "かえるの 話[はなし]"
    assert reading.lines == ["一行目。", "二行目。"]
    assert "12 page(s)" in client.calls[0]["user"]


def test_extract_reading_places_each_line_on_its_page():
    """The back of the card opens the book at the answer's page, known only if
    the transcription says it."""
    client = FakeClient({"title": "かえるの 話[はなし]",
                         "pages": [["一行目。", "二行目。"], [], ["三行目。"]]})
    reading = pdf_source.extract_reading(client, b"%PDF", "book.pdf", 3)
    assert reading.lines == ["一行目。", "二行目。", "三行目。"]
    assert reading.page_of_line == (1, 1, 3)
    assert "3 group(s)" in client.calls[0]["user"]


def test_a_page_count_that_does_not_tally_drops_the_map():
    """One group short and every later line names the page before: the book would
    open where the answer is not. The lines are kept, only the jump is lost."""
    client = FakeClient({"title": "かえるの 話[はなし]",
                         "pages": [["一行目。"], ["二行目。"]]})
    reading = pdf_source.extract_reading(client, b"%PDF", "book.pdf", 5)
    assert reading.lines == ["一行目。", "二行目。"]
    assert reading.page_of_line == ()


def test_extract_reading_accepts_an_array_of_one_reading():
    """The model sometimes answers with an array, out of habit from the other
    instructions."""
    client = FakeClient([{"title": "お知らせ", "lines": ["明日[あした]は 休[やす]みです。"]}])
    reading = pdf_source.extract_reading(client, b"%PDF", "doc.pdf", 1)
    assert (reading.title, reading.lines) == (
        "お知らせ", ["明日[あした]は 休[やす]みです。"])


def test_extract_reading_with_no_text_is_an_error():
    """Pages with no readable Japanese would give invented questions."""
    client = FakeClient({"title": "empty", "lines": []})
    with pytest.raises(RuntimeError, match="no Japanese text"):
        pdf_source.extract_reading(client, b"%PDF", "doc.pdf", 3)


# -- Arbitration: nature AND content, in one single call ----------------------
# Scanned pages with no text layer: the answer says how to read the document and
# brings its content with it, so the arbitration costs no extra call.

def test_the_arbitration_recognises_a_book_and_transcribes_it():
    client = FakeClient({"type": "book", "texts": [
        {"title": "かえるの 話[はなし]", "lines": ["一行目。", " 二行目。 "]},
    ]})
    mode, texts = pdf_source.extract_mode_and_texts(client, b"%PDF", "manga.pdf", 24)
    assert mode == "book"
    assert texts == [pdf_source.Text("かえるの 話[はなし]", ["一行目。", "二行目。"])]
    assert "24 page(s)" in client.calls[0]["user"]


def test_the_arbitration_recognises_independent_texts():
    client = FakeClient({"type": "text", "texts": [
        {"title": "手紙[てがみ]", "lines": ["一行目。"]},
        {"title": "メール", "lines": ["こんにちは。"]},
    ]})
    mode, texts = pdf_source.extract_mode_and_texts(client, b"%PDF", "papers.pdf", 30)
    assert mode == "text"
    assert [t.title for t in texts] == ["手紙[てがみ]", "メール"]


def test_the_arbitration_keeps_one_reading_only_for_a_book():
    """The pages of a book follow one another: two texts would mean two mini-books
    over the same images."""
    client = FakeClient({"type": "book", "texts": [
        {"title": "第[だい]一[いち]章[しょう]", "lines": ["一行目。"]},
        {"title": "第[だい]二[に]章[しょう]", "lines": ["二行目。"]},
    ]})
    mode, texts = pdf_source.extract_mode_and_texts(client, b"%PDF", "book.pdf", 40)
    assert mode == "book" and len(texts) == 1


def test_the_arbitration_bounds_the_texts_like_extract_texts():
    client = FakeClient({"type": "text", "texts": [
        {"title": "un", "lines": ["一行目。"]},
        {"title": "two", "lines": ["二行目。"]},
    ]})
    mode, texts = pdf_source.extract_mode_and_texts(client, b"%PDF", "doc.pdf", 30,
                                                    max_texts=1)
    assert mode == "text" and len(texts) == 1
    assert "1 text(s)" in client.calls[0]["user"]


def test_the_arbitration_without_a_type_is_text():
    """A bare list of texts means the model saw nothing calling for the images:
    it is text, and a book would cost media space and truncate the reading."""
    client = FakeClient([{"title": "手紙[てがみ]", "lines": ["一行目。"]}])
    assert pdf_source.extract_mode_and_texts(client, b"%PDF", "doc.pdf", 8)[0] == "text"


@pytest.mark.parametrize("kind, mode", [(" Book ", "book"), ("BOOK", "book"),
                                        ("manga", "text"), ("", "text")])
def test_only_book_makes_a_mini_book(kind, mode):
    """`book` is read whatever its case; any other answer reads the pages as text."""
    client = FakeClient({"type": kind, "texts": [
        {"title": "手紙[てがみ]", "lines": ["一行目。"]}]})
    assert pdf_source.extract_mode_and_texts(client, b"%PDF", "doc.pdf", 8)[0] == mode


def test_the_arbitration_without_a_text_is_an_error():
    client = FakeClient({"type": "book", "texts": [{"title": "empty", "lines": []}]})
    with pytest.raises(RuntimeError, match="no Japanese text"):
        pdf_source.extract_mode_and_texts(client, b"%PDF", "doc.pdf", 3)


# -- The map of a 聴解 booklet -------------------------------------------------
# One entry per page, in the order sent, never trusting the page number the
# model returns (wrong twice on a real booklet): a scanned booklet can then be
# sent whole, with no need to know which pages carry items.

class MapClient:
    """An AI client giving back the answer it was handed, and keeping the message."""

    def __init__(self, answer):
        self.answer = answer
        self.message = ""

    def chat_json_pdf(self, prompt, user_msg, pdf_bytes, filename):
        self.message = user_msg
        return self.answer


def test_one_entry_per_page_even_an_empty_one():
    """A cover, a section title, a page of written options: they keep their rank,
    failing which everything shifts."""
    client = MapClient({"Pages": [
        {"section": None, "items": []},
        {"section": 1, "items": []},
        {"section": None, "items": [{"number": 1, "figure": True}]},
    ]})

    chart = pdf_source.extract_map(client, b"%PDF", "N4L.pdf", 3)

    assert [page["section"] for page in chart] == [None, 1, None]
    assert [len(page["items"]) for page in chart] == [0, 0, 1]


def test_a_count_that_does_not_match_is_refused():
    """Better to give up on the figures than to stick them on the wrong items."""
    client = MapClient({"Pages": [{"section": None, "items": []}]})

    with pytest.raises(RuntimeError, match="incomplete"):
        pdf_source.extract_map(client, b"%PDF", "N4L.pdf", 3)


@pytest.mark.parametrize("raw", [None, "", "  ", "two", 0, -1, True, 1.5, {}])
def test_a_section_that_cannot_be_read_is_worth_nothing(raw):
    """An invented section would attach figures to the wrong one; None leaves the
    page in the section opened before it, which is the right fallback."""
    client = MapClient({"Pages": [{"section": raw, "items": []}]})

    assert pdf_source.extract_map(client, b"%PDF", "L.pdf", 1)[0]["section"] is None


@pytest.mark.parametrize("raw, expected", [(3, 3), ("3", 3), (" 4 ", 4)])
def test_a_section_written_plainly_is_read(raw, expected):
    client = MapClient({"Pages": [{"section": raw, "items": []}]})

    assert pdf_source.extract_map(client, b"%PDF", "L.pdf", 1)[0]["section"] == expected


def test_the_message_says_whether_the_booklet_leaves_whole():
    client = MapClient({"Pages": [{"section": None, "items": []}]})

    pdf_source.extract_map(client, b"%PDF", "L.pdf", 1, whole=True)
    assert "the whole booklet" in client.message

    pdf_source.extract_map(client, b"%PDF", "L.pdf", 1)
    assert "drawings of items" in client.message


def test_a_map_with_no_pages_names_the_field_in_the_quotes_of_the_screen(monkeypatch):
    """The name of the field is a value inside the sentence: quoted the way the
    language of the screen quotes."""
    monkeypatch.setattr(pdf_source, "quoted", lambda name: f"<{name}>")
    with pytest.raises(RuntimeError, match="<Pages>"):
        pdf_source.extract_map(MapClient({"pages": []}), b"%PDF", "L.pdf", 1)


def test_extract_items_gives_back_the_items_only():
    """The shape the typeset-booklet route expects, since it reads its sections in
    the text layer."""
    client = MapClient({"Pages": [
        {"section": 1, "items": [{"number": 1, "figure": True}]},
        {"section": None, "items": [{"number": 2, "figure": False}]},
    ]})

    assert pdf_source.extract_items(client, b"%PDF", "L.pdf", 2) == [
        [{"number": 1, "figure": True}],
        [{"number": 2, "figure": False}],
    ]
