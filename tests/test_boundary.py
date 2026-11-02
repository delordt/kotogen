"""The line between the library and the Anki adapter.

The library makes cards and does not know Anki exists; the adapter,
`kotogen.anki`, sends them there and looks after the deck. Only the modules that
assemble the two may name the adapter, so a program importing the library gets
no Anki with it. The rule is read twice: in the sources, to name the line at
fault, and by importing the library in a process of its own, to catch an
indirect import.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "kotogen"
ADAPTER = PACKAGE / "anki"

# The modules that may name both layers: the command line, the menu (a
# package) and the getting-started guide the menu opens on.
ASSEMBLY = ("cli.py", "interactive", "getting_started.py")

# What the library may not import: the adapter.
FORBIDDEN = ("kotogen.anki",)

def _module(path: Path) -> str:
    """The dotted name of a source file of the package."""
    parts = list(path.relative_to(PACKAGE.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _forbidden(name: str) -> bool:
    return any(name == root or name.startswith(root + ".") for root in FORBIDDEN)


def imports(source: str, module: str, is_package: bool = False) -> list[tuple[int, str]]:
    """Every module a source imports, as absolute names, with the line of each.

    A name imported from a package counts as a module too, as in
    `from kotogen import anki`; a relative import is resolved from the file, and
    `import_module("...")` with a literal name counts.
    """
    package = module if is_package else module.rpartition(".")[0]
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[:len(anchor) - (node.level - 1)]
                base = ".".join(anchor + ([node.module] if node.module else []))
            found.append((node.lineno, base))
            found += [(node.lineno, f"{base}.{alias.name}") for alias in node.names]
        elif (isinstance(node, ast.Call) and node.args
              and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)
              and (getattr(node.func, "id", "") == "import_module"
                   or getattr(node.func, "attr", "") == "import_module")):
            found.append((node.lineno, node.args[0].value))
    return found


def library() -> list[Path]:
    """The source files of the library: everything but the adapter and the two
    modules that assemble it."""
    return [path for path in sorted(PACKAGE.rglob("*.py"))
            if ADAPTER not in path.parents
            and not any(PACKAGE / name in (path, *path.parents) for name in ASSEMBLY)]


def test_the_scan_reads_every_form_of_import():
    source = "\n".join([
        "import kotogen.anki.connect",
        "from kotogen import anki",
        "from kotogen.anki.connect import request",
        "from . import anki",
        "from .anki.deck import Deck",
        "def late():",
        "    from kotogen.anki import send",
        "    return importlib.import_module('kotogen.anki.deck')",
        "from kotogen import exporter",
    ])
    found = [(line, name) for line, name in imports(source, "kotogen.memory")
             if _forbidden(name)]
    assert sorted({line for line, _name in found}) == [1, 2, 3, 4, 5, 7, 8]


def test_the_library_is_what_the_rule_reads():
    names = {_module(path) for path in library()}
    assert {"kotogen.exporter", "kotogen.generators.vocab", "kotogen.memory"} <= names
    assert not any(name.startswith("kotogen.anki.") for name in names)
    assert "kotogen.cli" not in names
    assert not any(name.split(".")[:2] == ["kotogen", "interactive"] for name in names)


def test_the_library_does_not_import_the_adapter():
    offending = []
    for path in library():
        seen_lines: set[int] = set()
        for line, name in imports(path.read_text(encoding="utf-8"), _module(path),
                                  path.name == "__init__.py"):
            if _forbidden(name) and line not in seen_lines:
                seen_lines.add(line)
                offending.append(f"{path.relative_to(ROOT).as_posix()}:{line} imports {name}")
    assert not offending, ("the library imports the Anki adapter:\n  "
                           + "\n  ".join(offending))


# Run in a process of its own: what this one has imported already says nothing.
# The network is refused there, so an import that tried to reach Anki fails.
_IMPORT_ALONE = """
import importlib, socket, sys

def refuse(self, address):
    raise SystemExit(f"reached {address} on import")

socket.socket.connect = refuse
for name in sys.argv[1:]:
    importlib.import_module(name)
loaded = sorted(name for name in sys.modules
                if any(name == root or name.startswith(root + ".")
                       for root in ("kotogen.anki",)))
if loaded:
    raise SystemExit("the library loaded " + ", ".join(loaded))
"""


def test_the_library_imports_without_anki():
    """`import kotogen.generators.vocab` on a machine with no Anki tries nothing."""
    names = [_module(path) for path in library() if path.name != "__main__.py"]
    result = subprocess.run([sys.executable, "-c", _IMPORT_ALONE, *names],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, (result.stderr or result.stdout).strip()
