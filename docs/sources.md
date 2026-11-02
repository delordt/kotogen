# Sources: web page, text file, PDF

The [`vocab`](vocabulary.md) and [`reading`](reading.md) commands read any web page (an NHK
Easy article included), a local text file or a PDF document. This page covers how they read
them; what each command makes of the text is on its own page.

## Any web page or text file

Only NHK Easy goes through a browser (Playwright), because its audio needs one. Every other
page is read over plain HTTP. Only an `http` or `https` address is fetched, and a redirection
to anything else is refused too (`not a web address (http or https only)`).

```bash
kotogen vocab https://ja.wikipedia.org/wiki/寿司 --count 10
kotogen reading https://example.jp/story --count 4     # at most 4 questions

kotogen vocab subtitles.srt          # .txt .md .html .srt .vtt .ass .csv .json...
kotogen reading chapter.txt          # as many questions as the text supports
kotogen reading episode01.ja.ass     # the dialogue of an anime episode
```

What happens to the text:

- **The body of the page is found first.** Every container is scored by the Japanese it
  carries *outside links* (a menu is made of links, an article is not), and the smallest
  one that still carries most of it is kept. This keeps a site's menu out of the prompt and
  off the back of a reading card.
- **The page's own `<ruby>` are kept** (`<ruby>吾輩<rt>わがはい</rt></ruby>` ->
  `吾輩[わがはい]`), so a site's furigana are not regenerated.
- **Only the lines containing Japanese are kept**, which drops footers and cookie banners
  without having to know the site.
- **A subtitle file is read cue by cue** (`.srt`, `.vtt`, and the `.ass` and `.ssa` that
  anime subtitles mostly come in). Numbering, timings and styling go, and a cue broken over
  two lines for the screen becomes one line of text, so a reading card translates the
  sentence whole. Of an `.ass`, only the dialogue is read, in screen order: signs, karaoke,
  credits and the other language of a bilingual release are left out (see
  [Listening](listening.md#an-ass-gives-its-dialogue-and-nothing-else)).
- **The encoding is detected**: UTF-8, and also Shift-JIS, EUC-JP and ISO-2022-JP, common on
  old sites and in files from Japanese publishers.
- **A Japanese URL can be pasted as it is** (`.../wiki/日本語`): it is encoded before
  sending, as a browser does.
- **In `vocab`, the text is capped** at 150 lines / 8,000 characters, and the cut is
  announced. `vocab` sends the page in one call, and a whole encyclopedia article would cost
  about $0.08. `reading` pays one call per passage kept, so it reads the whole text and only
  sends the passages of the current run (see
  [Reading](reading.md#resuming-a-long-work-where-you-left-off)).

In `reading`, the furigana of the `Text` field are filled in **locally by MeCab**, with no
extra AI call. A text too long for one card is cut into passages, one per card (see
[Reading](reading.md#a-long-text-is-cut-into-passages)).

**When a page cannot be read, the error says why**:

```
site unreachable ([Errno 11001] getaddrinfo failed) - check the URL and your connection.
page unreachable (HTTP 404 Not Found): https://example.jp/article
no Japanese text on this page. It may be built in JavaScript (the content only exists
    once a browser has been over it), reserved for subscribers, or simply not in
    Japanese.
```

The last one is the real limit: **JavaScript is not run**, so a page whose text is injected
on load yields little. NHK News Web is such a site (the main site, not NHK Easy, which has
its own route).

`audio` does not take an arbitrary web page: there is no sound to extract from one. Its
sources are NHK Easy, local files (**audio or video**, with their subtitle when one sits
next to them), **podcast RSS feeds**, which declare their audio file (see
[Listening](listening.md#podcasts)), and **YouTube videos**, whose media yt-dlp resolves and
whose hand-written Japanese subtitles replace Whisper when they exist (see
[Listening](listening.md#youtube-videos)).

> `kotogen vocab file.txt` **mines** the file (extraction of the useful vocabulary);
> `kotogen vocab --file file.txt` reads it as a **list of words**, one entry per line.
> The interactive assistant asks which one you mean.

`grammar` takes no text: it works on rules you name. The only address it accepts is that of
a page teaching **one** rule, given with `--url` (see
[Grammar](grammar.md#from-the-page-that-explains-it)). The rules of a text you have read come
from its reading card, through `maintain`.

## A PDF document (course, JLPT past papers, textbooks...)

`vocab` and `reading` accept a PDF document, by its path or by its URL. The
document goes **as it is to the AI model** (vision). The model reads the pages, which covers
scanned PDFs, text in images and PDFs whose copied text is unreadable (a broken encoding
table, frequent in JLPT past papers). No local extraction tool is needed, but the model has
to be **multimodal**, able to read a file (the OpenRouter catalogue of the menu lists only
those), and the document is limited to 25 MB. `audio` refuses PDFs: a document has no audio.

By default the extraction takes **as many items as possible**; `--count` (words) and
`--texts` (reading texts) set a limit. If the document cannot be used (no Japanese,
unreadable, no reading text...), the command gives up on it and shows the reason the model
gives.

`grammar` **refuses PDFs**, as it refuses any text: a document would only give rule *names*,
and the syllabus of the JLPT levels already lists them all, offline (see
[Grammar](grammar.md#filling-in-a-jlpt-level)).

The `reading` mini-book is the one exception to "as it is": the pages are first rendered as
images (the `[pdf]` extra), and the model receives only the requested range, read as a
single reading. The command decides from the pages themselves whether to show them or
transcribe them. See [the mini-book](reading.md#as-a-mini-book-the-pages-themselves).

## The sources with an alias

Three sources are named by a word rather than an address, because they always publish in
the same place. An alias is only a shortcut: it points to public PDF and MP3 files.

| Alias | What it is | Listening | Reading |
|---|---|---|---|
| `jlpt-nX`, `jlpt2012-nX`, `jlpt2009-nX` | Official JLPT past papers | 聴解 sections | 読解 booklet |
| `irodori-nyumon`... `irodori-shochukyu` | いろどり 生活の日本語 | dialogues of a lesson | PDF of a lesson |
| `roudoku` | 青空朗読 | public-domain readings | - |

An incomplete alias (`jlpt`, `irodori`) lists what can be typed, as a misspelt podcast alias
does. Each source is detailed in [Listening](listening.md) and [Reading](reading.md).

The **青空文庫** collection has no alias: a work is given by its address (its book card is
enough, and is turned into the page of the text), and the assistant opens its catalogue. It
is read as a web page, by the route above, with its original `<ruby>`.

---

[Documentation index](../README.md#documentation)
