"""The French of the program stays in the places the program keeps it.

Comments, docstrings, names, the documentation and the configuration files are
English, in any file, including one added later. French has places of its own:
the catalogue, the French instructions, the French gloss of a table. String
literals are not searched for French: what reaches the screen goes through
`kotogen.i18n`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Accented letters and French quotation marks: no English technical prose
# carries them, and the Japanese these files hold is out of this range.
_ACCENTED = re.compile(r"[àâäçéèêëî"
                       r"ïôöùûüœÀÂ"
                       r"ÄÇÉÈÊËÎÏÔ"
                       r"ÖÙÛÜŒ«»]")

# French function words rare in English prose: two in one line are telling.
# Words both languages share (son, par, tout, encore, chez, note, page) are left
# out to avoid false alarms.
_WORDS = re.compile(
    r"\b(le|la|les|une|des|de|du|au|aux|ou|sur|dans|pour|qui|que|pas|est|sont"
    r"|avec|sans|mais|donc|cette|ces|ses|elle|nous|vous|leur|quand|comme|fait"
    r"|faire|peut|doit|alors|jamais|toujours|rien|chaque|autre|entre|avant"
    r"|apres|depuis"
    r"|pendant|ainsi|cela|celui|plutot|deja|ceux|dont|lorsque|puisque|parce"
    r"|toute|toutes|tous|meme|memes|etre|avoir|cela|voila|ici|ailleurs)\b",
    re.IGNORECASE)

# Names of things, in unambiguous French only (`index`, `mode` or `page` are
# English too). `lecture` stays: English never gives it the sense of reading.
_IDENTIFIERS = re.compile(
    r"(?:^|_)(adjectif|apercu|apparence|apparier|attendu|avancement|bloc|borne|bornes"
    r"|cadre|cadres|carte|cartes|chaine|champ|champs|chercher|choisi|choisir"
    r"|choix|cible|cle|coche|coches|colonne|colonnes|compteur|consigne|corps"
    r"|couper|curseur|debut|decoupe|deja|demande|demander|depuis|dossier|duree"
    r"|ecart|ecarts|ecoute|ecran|entree|entrees|envoi|envoyer|etat|etape"
    r"|fiche|flux|fonds|gabarit|gabarits|garder|indice|lecon|lecture|leurre|libre"
    r"|ligne|lignes|lire|livre|livres|manquant|manquants|montre|mot|mots"
    r"|niveau|niveaux|nombre|numero|oeuvre|paquet|phrase"
    r"|phrases|piste|pistes|plafond|poser|prerequis|qcm|recto|reglage|reglages"
    r"|regle|regles|relecture|repere|reponse|reprise|retenues|situer|taper"
    r"|telechargement|texte|textes|titre|touche|trad|traduction|verbe|verso"
    r"|vide|vue)"
    r"(?:_|$)")


def _sources() -> list[Path]:
    files = sorted(ROOT.joinpath("src").rglob("*.py"))
    files += sorted(ROOT.joinpath("tests").rglob("*.py"))
    return [path for path in files if "__pycache__" not in path.parts]


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# What sits between backticks is a name, not prose: the way out for French a
# comment has to name, such as a catalogue word (`légère`) or a user's deck.
_QUOTED = re.compile(r"`[^`]*`")


def _french(text: str) -> bool:
    text = _QUOTED.sub("", text)
    return bool(_ACCENTED.search(text)) or len(_WORDS.findall(text)) >= 2


@pytest.mark.parametrize("path", _sources(), ids=_relative)
def test_comments_and_docstrings_are_english(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    guilty = [line.strip() for line in source.splitlines()
              if line.lstrip().startswith("#") and _french(line)]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc and _french(doc):
                guilty.append(doc.splitlines()[0].strip())
    assert not guilty, f"French in {_relative(path)}: {guilty[:3]}"


@pytest.mark.parametrize("path", _sources(), ids=_relative)
def test_names_are_english(path: Path) -> None:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    guilty = sorted(name for name in names if _IDENTIFIERS.search(name.lower()))
    assert not guilty, f"French names in {_relative(path)}: {guilty[:5]}"


def test_module_filenames_are_english() -> None:
    guilty = [_relative(path) for path in _sources()
              if _IDENTIFIERS.search(path.stem.lower())]
    assert not guilty, f"French module names: {guilty}"


# ── Beyond the Python ─────────────────────────────────────────────────────────
# The documentation, the configuration files and the template comments get the
# same test and the same backtick way out. Skipped too: fenced markdown blocks,
# which quote screens and cards, and the setting lines of `.env.example`.

_FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_SETTING_LINE = re.compile(r"^#?\s*[A-Z][A-Z0-9_]*=.*$", re.MULTILINE)

# The comments of a card template, which mixes HTML, CSS and JavaScript. In a
# script, `/*` and `//` count only with a blank on both sides, so that neither
# the `https://` of a URL nor a regular expression (`/\s*/`) is taken for one.
_CSS_COMMENT = re.compile(r"/\*(.*?)\*/", re.DOTALL)
_HTML_COMMENT = re.compile(
    r"<!--(.*?)-->|(?:^|\s)/\*\s(.*?)\*/|(?:^|\s)//\s([^\n]*)",
    re.MULTILINE | re.DOTALL)


def _prose_files() -> list[Path]:
    # By glob rather than by name, like the Python files: a page added later is
    # checked without being listed here.
    files = sorted(ROOT.glob("*.md"))
    files += [ROOT / name for name in (".env.example", "pyproject.toml",
                                       ".gitignore", ".gitattributes")]
    files += sorted(ROOT.joinpath("docs").glob("*.md"))
    files += sorted(ROOT.joinpath(".github").rglob("*.yml"))
    files += sorted(ROOT.joinpath(".github").rglob("*.md"))
    files += sorted(ROOT.joinpath("templates").rglob("context.md"))
    # Of the instructions, `en/` asks for English cards and `structure/` for JSON:
    # both are English prose, a French word they name sitting between backticks.
    prompts = ROOT.joinpath("src", "kotogen", "prompts")
    files += sorted(prompts.joinpath("en").glob("*.md"))
    files += sorted(prompts.joinpath("structure").glob("*.md"))
    # Nothing on the preview page is card content, so unlike a template it is
    # checked whole rather than comment by comment.
    files.append(ROOT / "src" / "kotogen" / "data" / "preview.html")
    return [path for path in files if path.exists()]


def _template_files() -> list[Path]:
    root = ROOT.joinpath("templates")
    return sorted(p for p in root.rglob("*") if p.suffix in (".html", ".css"))


def _prose(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        text = _FENCE.sub("", text)
    if path.name == ".env.example":
        text = _SETTING_LINE.sub("", text)
    return _QUOTED.sub("", text)


@pytest.mark.parametrize("path", _prose_files(), ids=_relative)
def test_documentation_and_configuration_are_english(path: Path) -> None:
    guilty = [line.strip() for line in _prose(path).splitlines() if _french(line)]
    assert not guilty, f"French in {_relative(path)}: {guilty[:3]}"


# Only the `#` lines heading a data table are checked: they describe the
# columns. The rows are data, and their glosses card content (the French column
# of `jlpt_grammar.tsv`).
_DATA_TABLES = ("jlpt_grammar.tsv", "jlpt_kanji.tsv", "jlpt_vocab.tsv",
                "joyo_kanji.tsv", "joyo_special_readings.tsv", "kanji_strokes.tsv")


@pytest.mark.parametrize("name", _DATA_TABLES)
def test_data_table_headers_are_english(name: str) -> None:
    path = ROOT / "src" / "kotogen" / "data" / name
    head = [line for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("#")]
    guilty = [line.strip() for line in head if _french(_QUOTED.sub("", line))]
    assert not guilty, f"French in {_relative(path)}: {guilty[:3]}"


@pytest.mark.parametrize("path", _template_files(), ids=_relative)
def test_template_comments_are_english(path: Path) -> None:
    """What a card says follows `all.lang`; its template is code either way."""
    text = path.read_text(encoding="utf-8")
    pattern = _CSS_COMMENT if path.suffix == ".css" else _HTML_COMMENT
    guilty = []
    for match in pattern.finditer(text):
        comment = next(group for group in match.groups() if group is not None)
        guilty += [line.strip() for line in _QUOTED.sub("", comment).splitlines()
                   if _french(line)]
    assert not guilty, f"French in {_relative(path)}: {guilty[:3]}"


# ── The colon, which is punctuation and not a word ────────────────────────────
# English writes `Expression: 猫`, French `Expression : 猫`. `i18n.convention`
# spaces the colon for the screens, `prompts.say` for the model; a French-spaced
# colon is allowed only in a French string, such as a French sample of the preview.
#
# An f-string is read whole, its placeholders standing as `{}`; otherwise
# `f"   !! {deck}: {exc}"` would read as `!! ` followed by `: `.
_FRENCH_COLON = re.compile(r"\S :(?!:)")

# JavaScript handed to a browser is not prose in any language, and a ternary
# (`h1 ? h1.innerHTML : ''`) is spaced the way JavaScript is written.
_NOT_PROSE = {"evaluate"}


def _texts(tree: ast.AST) -> list[tuple[int, str]]:
    """Every string the file writes, f-strings whole and docstrings left out."""
    docs, code = set(), set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant):
            docs.add(id(body[0].value))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in _NOT_PROSE:
            code |= {id(inner) for arg in node.args for inner in ast.walk(arg)}
    found, inside = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            inside |= {id(part) for part in node.values}
            if id(node) not in code:
                found.append((node.lineno, "{}".join(
                    part.value for part in node.values
                    if isinstance(part, ast.Constant) and isinstance(part.value, str))))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docs | code | inside:
            found.append((node.lineno, node.value))
    return found


# `src/` only: the program is what writes to a screen or a model. A test file
# quotes (a French card, a ternary, a model's answer) and chooses no convention.
@pytest.mark.parametrize("path", [p for p in _sources() if ROOT / "src" in p.parents],
                         ids=_relative)
def test_a_colon_is_spaced_the_way_its_language_spaces_it(path: Path) -> None:
    guilty = [f"line {lineno}: {text[:60]!r}"
              for lineno, text in _texts(ast.parse(path.read_text(encoding="utf-8")))
              if _FRENCH_COLON.search(text) and not _french(text)]
    assert not guilty, (f"French-spaced colon in English, in {_relative(path)}: "
                        f"{guilty[:3]} - see `i18n.convention` / `prompts.say`")
