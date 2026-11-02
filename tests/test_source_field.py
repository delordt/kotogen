"""The Source field: where the matter of a card was drawn from.

Every generation route fills it in, and names the passage, not just the file:
the extracts of one collection would otherwise all point at the same name.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from kotogen import seen as history
from kotogen.generators import audio, audio_files, audio_split, nhk, reading, whisper

# Fake transcript segments: what matters here is the split.
SEGMENTS = [
    audio_split.Segment("セクション10", 0.0, 2.0),
    audio_split.Segment("ねえ、聞いて。", 4.0, 9.0),
    audio_split.Segment("どうしたの?何かいいことあった?", 9.0, 14.0),
    audio_split.Segment("来週から、駅前のパン屋で働くんだ。", 20.0, 25.0),
]


def _ai_answer(*_a, **_k) -> dict:
    return {
        "Level": "N4",
        "TranscriptLines": ["ねえ、聞いて。", "どうしたの?何かいいことあった?"],
        "TranslationLines": ["Écoute.", "Qu'y a-t-il ? Il t'est arrivé quelque chose ?"],
        "Cards": [{"Question": "Que demande l'amie ?", "Answer": "Ce qui est arrivé",
                   "Decoys": ["L'heure", "Le chemin", "Un prix"], "KeyLine": 2}],
    }


def _audio_args(tmp_path: Path, source: Path) -> argparse.Namespace:
    return argparse.Namespace(
        inputs=[str(source)], latest=4, provider="openrouter", model="m",
        output=str(tmp_path / "out.tsv"), send=False, deck="Test", notetype="Audio",
        count=None, level="auto", max_duration=None, whisper_model="small",
        audio_quality=None, split=True,
        # Sound alone, or a YouTube entry would ask about the picture
        # (see `video_clip`).
        video=False,
    )


def _run_audio(tmp_path, monkeypatch, source: Path, split,
               args: argparse.Namespace | None = None,
               answer=_ai_answer) -> list[dict]:
    """Runs `run_audio` on stand-ins and hands back the cards produced.

    `answer` stands for the generation call, given the same arguments.
    """
    def extract(src, block, rank, out_dir, bitrate):
        path = out_dir / f"{src.stem}_{rank:02d}.mp3"
        path.write_bytes(b"")
        return path

    monkeypatch.setattr(audio, "AIClient", lambda **k: object())
    monkeypatch.setattr(whisper, "_transcribe", lambda *a, **k: SEGMENTS)
    monkeypatch.setattr(audio_split, "split_audio", lambda *a, **k: split)
    monkeypatch.setattr(audio, "_extract_span", extract)
    monkeypatch.setattr(audio, "_generate_for_audio", answer)
    monkeypatch.setattr(audio, "append_cards", lambda *a, **k: None)
    monkeypatch.setattr(audio, "resolve_output_path", lambda *a, **k: tmp_path / "out.tsv")

    seen: dict = {}
    monkeypatch.setattr(
        audio, "_finish_audio",
        lambda cards, tsv, media, args, refused=0, failures=0: seen.update(cards=cards))

    audio.run_audio(args or _audio_args(tmp_path, source))
    return seen["cards"]


def _shelf(tmp_path: Path) -> tuple[Path, Path]:
    """A folder of series holding one series, holding one episode."""
    shelf = tmp_path / "shelf"
    (shelf / "Ma Serie").mkdir(parents=True)
    episode = shelf / "Ma Serie" / "ep01.mp3"
    episode.write_bytes(b"")
    return shelf, episode


def _one_passage() -> audio_split.Split:
    return audio_split.Split(
        "stream", [audio_split.Block((1,), ((4.0, 9.0),))], [])


# ── Listening ────────────────────────────────────────────────────────────────

def test_each_extract_of_a_collection_says_where_it_sits(tmp_path, monkeypatch):
    """The file name is not enough: three extracts share it."""
    source = tmp_path / "collection.mp3"
    source.write_bytes(b"")
    split = audio_split.Split(
        "collection",
        [audio_split.Block((1,), ((4.0, 9.0),)),
         audio_split.Block((2,), ((9.0, 14.0),)),
         audio_split.Block((3,), ((20.0, 25.0),))],
        [],
    )

    cards = _run_audio(tmp_path, monkeypatch, source, split)

    assert [c["Source"] for c in cards] == [
        "collection.mp3 (00:04 → 00:09)",
        "collection.mp3 (00:09 → 00:14)",
        "collection.mp3 (00:20 → 00:25)",
    ]


def test_an_episode_says_which_series_it_comes_from(tmp_path, monkeypatch):
    """Every series has its "ep01.mp3": the series folder tells them apart."""
    shelf, _episode = _shelf(tmp_path)

    cards = _run_audio(tmp_path, monkeypatch, shelf, _one_passage())

    assert [c["Source"] for c in cards] == ["Ma Serie - ep01.mp3 (00:04 → 00:09)"]


def test_an_episode_handled_is_remembered_for_the_next_pass(tmp_path, monkeypatch):
    """A shelf is worked through, not replayed, like a podcast's episodes."""
    shelf, episode = _shelf(tmp_path)

    assert _run_audio(tmp_path, monkeypatch, shelf, _one_passage())

    assert history.load("audio", audio_files.FILES_SOURCE) == {
        audio_files._file_id(episode): episode.name}
    assert audio_files._files_to_do([episode], [shelf], None) == ([], 1)


def _nothing_kept() -> audio_split.Split:
    return audio_split.Split(
        "stream", [], [audio_split.Dropped(0.0, 2.0, "off topic")])


def _no_card(*_a, **_k) -> dict:
    return {**_ai_answer(), "Cards": []}


def _broken_call(*_a, **_k) -> dict:
    raise RuntimeError("connection reset")


def _podcast_episode(tmp_path, monkeypatch) -> tuple[Path, argparse.Namespace]:
    """An episode served as if downloaded: (its file, the arguments naming it)."""
    from kotogen.generators import podcast, sources

    file = tmp_path / "teppei_0123.mp3"
    file.write_bytes(b"")
    feed = podcast.Feed("teppei", "Nihongo con Teppei", "https://example.jp/rss")
    episode = podcast.Episode("g1", "#123", "https://example.jp/123.mp3",
                              "2026-08-20", 300.0)

    monkeypatch.setattr(sources, "is_podcast", lambda entry: entry == "teppei")
    monkeypatch.setattr(audio, "_podcast_episodes",
                        lambda *a, **k: [(file, feed, episode)])
    monkeypatch.setattr(podcast, "cache_folder", lambda feed: tmp_path)
    monkeypatch.setattr(podcast, "cleanup", lambda *a, **k: None)

    args = _audio_args(tmp_path, file)
    args.inputs = ["teppei"]
    args.episode = None
    return file, args


@pytest.mark.parametrize("split, answer", [
    (_nothing_kept(), _ai_answer),   # the split keeps no passage
    (_one_passage(), _no_card),      # the model makes no card of the passage
])
def test_an_episode_that_gives_no_card_is_handled_all_the_same(
        tmp_path, monkeypatch, split, answer):
    """Offered again, it would cost its splitting at every run, and `--latest 1`
    would never get past it."""
    file, args = _podcast_episode(tmp_path, monkeypatch)

    assert _run_audio(tmp_path, monkeypatch, file, split, args, answer) == []

    assert history.load("audio", "teppei") == {"g1": "#123"}


def test_an_episode_whose_run_broke_stays_to_be_handled(tmp_path, monkeypatch):
    """A failed call says nothing of the episode: the next run tries it again."""
    file, args = _podcast_episode(tmp_path, monkeypatch)

    assert _run_audio(tmp_path, monkeypatch, file, _one_passage(), args,
                      _broken_call) == []

    assert history.load("audio", "teppei") == {}


def test_an_episode_of_a_shelf_that_gives_no_card_is_handled_all_the_same(
        tmp_path, monkeypatch):
    """The same rule as for a podcast's episodes."""
    shelf, episode = _shelf(tmp_path)

    assert _run_audio(tmp_path, monkeypatch, shelf, _nothing_kept()) == []

    assert audio_files._files_to_do([episode], [shelf], None) == ([], 1)


def test_a_file_taken_whole_has_no_bounds_to_give(tmp_path, monkeypatch):
    """No bounds to give: the name says it all."""
    source = tmp_path / "simple.mp3"
    source.write_bytes(b"some sound")

    cards = _run_audio(tmp_path, monkeypatch, source,
                       audio_split.whole_block(SEGMENTS))

    assert [c["Source"] for c in cards] == ["simple.mp3"]


def test_a_podcast_episode_names_itself_and_not_its_cache_file(
        tmp_path, monkeypatch):
    """The download `teppei_0123.mp3` goes with the cache clean-up: the card
    keeps the feed and the episode."""
    from kotogen.generators import podcast, sources

    file = tmp_path / "teppei_0123.mp3"
    file.write_bytes(b"")
    feed = podcast.Feed("teppei", "Nihongo con Teppei", "https://example.jp/rss")
    episode = podcast.Episode("g1", "#123 ゲスト回 / 後半", "https://example.jp/123.mp3",
                              "2026-08-20", 300.0)

    monkeypatch.setattr(sources, "is_podcast", lambda entry: entry == "teppei")
    monkeypatch.setattr(audio, "_podcast_episodes",
                        lambda *a, **k: [(file, feed, episode)])
    monkeypatch.setattr(podcast, "cache_folder", lambda feed: tmp_path)
    monkeypatch.setattr(podcast, "mark_done", lambda *a, **k: None)
    monkeypatch.setattr(podcast, "cleanup", lambda *a, **k: None)

    args = _audio_args(tmp_path, file)
    args.inputs = ["teppei"]
    args.episode = None
    cards = _run_audio(tmp_path, monkeypatch, file,
                       audio_split.whole_block(SEGMENTS), args)

    assert [c["Source"] for c in cards] == ["Nihongo con Teppei - #123 ゲスト回 / 後半"]


def test_a_youtube_video_reads_and_reopens_at_the_right_passage(tmp_path, monkeypatch):
    """The label reads, the address reopens the video at the extract's second.
    The back turns it into a clickable label, hence the address BEHIND."""
    from kotogen.generators import sources, youtube

    file = tmp_path / "onomappu_20260801_abc12345678.m4a"
    file.write_bytes(b"")
    source = youtube.Source("onomappu", "Onomappu", feed_url="https://example.jp/feed")
    info = youtube.ProbedVideo(id="abc12345678", title="オノマトペ入門",
                               duration=600.0, ja_subtitle=True)
    split = audio_split.Split(
        "onomappu",
        [audio_split.Block((1,), ((4.0, 9.0),)),
         audio_split.Block((3,), ((20.0, 25.0),))],
        [],
    )

    monkeypatch.setattr(sources, "is_youtube", lambda entry: entry == "onomappu")
    monkeypatch.setattr(audio, "_youtube_videos",
                        lambda *a, **k: [(file, source, info)])
    monkeypatch.setattr(youtube, "cache_folder", lambda source: tmp_path)
    monkeypatch.setattr(youtube, "mark_done", lambda *a, **k: None)
    monkeypatch.setattr(youtube, "cleanup", lambda *a, **k: None)

    args = _audio_args(tmp_path, file)
    args.inputs = ["onomappu"]
    cards = _run_audio(tmp_path, monkeypatch, file, split, args)

    assert [c["Source"] for c in cards] == [
        "Onomappu - オノマトペ入門 (00:04 → 00:09) https://youtu.be/abc12345678?t=4",
        "Onomappu - オノマトペ入門 (00:20 → 00:25) https://youtu.be/abc12345678?t=20",
    ]


def test_an_nhk_article_keeps_its_address(tmp_path, monkeypatch):
    """Everything comes from it - the sound, the text, the furigana - and it
    reopens."""
    url = "https://news.web.nhk/news/easy/ne2026082512345/ne2026082512345.html"
    audio_path = tmp_path / "nhk_ne2026082512345.mp3"

    monkeypatch.setattr(nhk, "fetch_article",
                        lambda *a, **k: ("Title", ["日本[にほん]。"], b"some sound", ".mp3", ""))
    monkeypatch.setattr(nhk, "transcode_bytes",
                        lambda *a, **k: (audio_path.write_bytes(b""), audio_path)[1])
    monkeypatch.setattr(nhk, "check_duration", lambda *a, **k: None)
    monkeypatch.setattr(nhk, "mark_seen", lambda *a, **k: None)
    monkeypatch.setattr(nhk, "_listen", lambda *a, **k: [])

    class _AI:
        def chat_json(self, *a, **k):
            return _ai_answer()

    args = argparse.Namespace(max_duration=None, audio_quality=None,
                              count=1, level="auto")
    cards, _ = nhk.generate_for_url(url, args, _AI(), tmp_path)

    assert [c["Source"] for c in cards] == [url]


# ── Reading ──────────────────────────────────────────────────────────────────

def _reading_answer() -> dict:
    return {"Level": "N4",
            "Cards": [{"Question": "Où a-t-il plu ?", "Decoys": [], "Answer": "À Tokyo"}]}


def test_a_reading_card_carries_the_source_of_its_text():
    cards = reading._post_process(_reading_answer(), ["東京[とうきょう]。"], "N4",
                                  source="https://example.jp/reading")
    assert cards[0]["Source"] == "https://example.jp/reading"


def test_a_document_read_by_page_range_says_which(tmp_path, monkeypatch):
    """Without the range, the card would point at 600 pages to search."""
    from kotogen.generators import pdf_pages, pdf_source

    document = tmp_path / "papers_n4.pdf"
    document.write_bytes(b"%PDF-1.7")

    monkeypatch.setattr(pdf_source, "load_pdf", lambda path: b"%PDF-1.7")
    monkeypatch.setattr(pdf_pages, "page_count", lambda data: 600)
    monkeypatch.setattr(pdf_pages, "parse_pages", lambda spec, total: [11, 12, 13])
    monkeypatch.setattr(pdf_pages, "subset", lambda data, indices: data)
    monkeypatch.setattr(pdf_source, "extract_texts",
                        lambda *a, **k: [pdf_source.Text("手紙[てがみ]", ["一行目。"])])
    monkeypatch.setattr(reading, "_generate_for_text",
                        lambda *a, **k: _reading_answer())
    monkeypatch.setattr(reading, "append_cards", lambda *a, **k: None)

    args = argparse.Namespace(read_as="text", pages="12-14", texts=None, passages=None,
                              count=None, level="auto", deck="Test", notetype="Reading")
    cards: list[dict] = []
    reading._emit_pdf(None, document, args, None, cards, [])

    assert [c["Source"] for c in cards] == ["papers_n4.pdf (p. 12-14)"]


def test_a_book_brought_back_from_the_web_keeps_its_address_not_its_download(
        tmp_path, monkeypatch):
    """The card keeps the record to reopen, not the cache file `6346.pdf`."""
    from kotogen.generators import pdf_web

    record = "https://tadoku.org/japanese/book/6346/"
    monkeypatch.setattr(pdf_web, "fetch",
                        lambda source: (tmp_path / "6346.pdf", "ありますか"))

    inputs, books, origins, titles, _alias = reading._fetch_web_pdfs([record])
    # The record's title survives the download: the book announces itself by it.
    assert titles[inputs[0]] == "ありますか"

    assert books == {str(tmp_path / "6346.pdf")}
    assert origins[inputs[0]] == record
