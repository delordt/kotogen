"""Safeguard: check that it really is the repository's code that runs.

Installed without `-e` (`pip install .`), the venv keeps a frozen copy of `src/`:
after a `git pull` the program silently runs the old version.
"""

import pathlib

import kotogen

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = ROOT / "src" / "kotogen"


def test_the_imported_package_really_comes_from_the_sources():
    """`import kotogen` must load `src/`, not a copy in site-packages."""
    loaded = pathlib.Path(kotogen.__file__).resolve().parent
    assert loaded == SOURCES, (
        f"Python runs {loaded}, not {SOURCES}.\n"
        "The installation is a frozen copy, not a link to the sources.\n"
        "Fix:  rm -rf build && pip install -e ."
    )


def test_no_stale_build_is_left_lying_around():
    """A leftover `build/lib` re-injects the files deleted since.

    setuptools reuses that folder between builds without pruning it.
    """
    build = ROOT / "build" / "lib" / "kotogen"
    if not build.is_dir():
        return
    ghosts = sorted(
        path.relative_to(build).as_posix()
        for path in build.rglob("*.py")
        if not (SOURCES / path.relative_to(build)).exists()
    )
    assert not ghosts, (
        f"{build} holds files absent from the sources: {', '.join(ghosts)}.\n"
        "They would come back into the package at the next installation.\n"
        "Fix:  rm -rf build"
    )
