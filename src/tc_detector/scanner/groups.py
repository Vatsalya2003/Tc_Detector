"""Step 3 of a scan: sort a service's files into the groups rules look at.

A file is in at most one group. Files in no group (SQL, images, static JS, ...) are
left out of the inventory, because no rule reads them.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from tc_detector.scanner.walk import BUILD_FILES

GROUPS = ("build", "config", "logging", "java", "specs", "schemas")

CONFIG_PREFIXES = ("application", "bootstrap")
CONFIG_SUFFIXES = (".yml", ".yaml", ".properties")
DOC_SUFFIXES = (".yml", ".yaml", ".json")  # what an OpenAPI/AsyncAPI document is written in
HEAD_CHARS = 4096  # only the start of a file is read to spot a spec's top-level key

# The version key a spec starts with. YAML: a key at column 0 (top level, not nested).
# JSON: the first key of the top-level object, as spec tools write it.
_YAML_KEY = r"^[\"']?({keys})[\"']?\s*:"
_JSON_KEY = r"\A\s*\{{\s*\"({keys})\"\s*:"


def _has_top_key(path: Path, keys: str) -> bool:
    with path.open(encoding="utf-8", errors="replace") as f:
        head = f.read(HEAD_CHARS)
    pattern = _JSON_KEY if path.suffix == ".json" else _YAML_KEY
    return re.search(pattern.format(keys=keys), head, re.MULTILINE) is not None


def _is_doc(rel: PurePosixPath, path: Path, words: tuple[str, ...]) -> bool:
    """A .yml/.yaml/.json whose name has one of `words`, or that starts with that key."""
    if rel.suffix not in DOC_SUFFIXES:
        return False
    return any(w in rel.stem.lower() for w in words) or _has_top_key(path, "|".join(words))


def group_of(rel: str, path: Path) -> str | None:
    """The group of one file. `rel` is relative to its service root; `path` is on disk."""
    p = PurePosixPath(rel)
    name = p.name
    if rel in BUILD_FILES:  # only the build file at the service root, not a nested one
        return "build"
    if name.startswith(CONFIG_PREFIXES) and p.suffix in CONFIG_SUFFIXES:
        return "config"
    if (name.startswith("logback") and p.suffix == ".xml") or name.startswith("log4j2"):
        return "logging"
    if rel.startswith("src/main/java/") and p.suffix == ".java":
        return "java"
    if p.suffix in (".proto", ".avsc") or _is_doc(p, path, ("asyncapi",)):
        return "schemas"
    if _is_doc(p, path, ("openapi", "swagger")):
        return "specs"
    return None


def empty_groups() -> dict[str, list[str]]:
    return {g: [] for g in GROUPS}
