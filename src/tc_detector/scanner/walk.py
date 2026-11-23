"""Step 1 of a scan: list the files of a target repo and find its service folders.

Read this file first, then naming.py, groups.py, inventory.py and scan.py.
Everything here only reads the target repo; nothing is ever written to it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Folders never looked into, wherever they are: version control, tool caches, IDE files.
SKIP_DIRS = {".git", "node_modules", ".idea", ".vscode", ".mvn", ".gradle"}
# Build output: skipped only right next to a build file (a service root) or in the scanned
# root. Deeper down these are ordinary source folders, e.g. the Java package com/acme/build/.
BUILD_OUTPUT_DIRS = {"target", "build", "out"}
# A folder holding one of these is a service (unless it only groups other modules).
BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")
GRADLE_SETTINGS = ("settings.gradle", "settings.gradle.kts")

_XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_POM_MODULE = re.compile(r"<module>")
_LINE_COMMENT = re.compile(r"//[^\n]*")
_GRADLE_INCLUDE = re.compile(r"^\s*include\b", re.MULTILINE)


def _skipped(folder: str, parent: Path, next_to_build: bool) -> bool:
    """Should the walk stay out of `folder` (a subfolder of `parent`)?

    SKIP_DIRS: always. BUILD_OUTPUT_DIRS: only when `next_to_build`.
    `test`: only when it sits in `src` (src/test).
    """
    if folder in SKIP_DIRS:
        return True
    if folder in BUILD_OUTPUT_DIRS:
        return next_to_build
    return folder == "test" and parent.name == "src"


def walk_files(root: Path) -> list[str]:
    """Every file under `root` as a "/"-separated path relative to `root`, sorted.

    Skipped folders are never entered, so a large node_modules costs nothing.
    Symlinked folders are not followed, so a link can't lead outside the repo.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        # Is this folder a service root or the scanned root? Then its target/, build/ and
        # out/ hold build output. (A Gradle settings file marks a build root too.)
        next_to_build = here == root or any(
            f in BUILD_FILES or f in GRADLE_SETTINGS for f in filenames
        )
        # Editing `dirnames` in place is how os.walk is told not to go into a folder.
        dirnames[:] = [d for d in dirnames if not _skipped(d, here, next_to_build)]
        rel = here.relative_to(root)
        found += [(rel / f).as_posix() for f in filenames if (here / f).is_file()]
    return sorted(found)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def is_aggregator(folder: Path) -> bool:
    """True if the folder's build only groups other modules, so it is not a service.

    Maven: a pom.xml listing <module>s (a parent pom).
    Gradle: a settings.gradle(.kts) that `include`s subprojects.
    """
    pom = _XML_COMMENT.sub("", _read(folder / "pom.xml"))
    if _POM_MODULE.search(pom):
        return True
    return any(
        _GRADLE_INCLUDE.search(_LINE_COMMENT.sub("", _read(folder / name)))
        for name in GRADLE_SETTINGS
    )


def service_roots(root: Path, files: list[str]) -> list[str]:
    """Folders (relative to `root`, "." for root itself) that are services, sorted."""
    folders = {os.path.dirname(f) or "." for f in files if os.path.basename(f) in BUILD_FILES}
    return sorted(f for f in folders if not is_aggregator(root / f))
