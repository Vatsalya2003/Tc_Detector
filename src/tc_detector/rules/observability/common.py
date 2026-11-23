"""Helpers shared by the observability rules. Owner: Vatsalya (A).

Services and their files come from the scanner's inventory (tc_detector.scanner), so
these rules have no service finder of their own and name services the way labels do.
"""

from __future__ import annotations

import re
from pathlib import Path

from tc_detector.contracts.ids import SNIPPET_MAX_CHARS
from tc_detector.scanner import Inventory, Service, scan

_TRUNCATED = "\n[... truncated]"
# Java/Groovy/Kotlin: a string literal, or a comment. Strings are matched first so a
# "http://..." inside a string is never read as the start of a // comment.
_STRING = r"\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'"
_COMMENT = r"/\*.*?\*/|//[^\n]*"
_CODE_TOKENS = re.compile(f"{_STRING}|{_COMMENT}", re.DOTALL)
_XML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def load(
    repo: Path | str, repo_name: str | None, commit: str | None, inventory: Inventory | None
) -> tuple[Path, Inventory]:
    """The repo folder and its inventory: the one passed in, or a fresh scan."""
    repo = Path(repo).resolve()
    return repo, inventory or scan(repo, repo_name, commit)


def files(repo: Path, service: Service, group: str) -> list[tuple[str, str]]:
    """(path relative to the service root, text) of every file in one inventory group."""
    folder = repo / service.root
    return [
        (rel, (folder / rel).read_text(encoding="utf-8", errors="replace"))
        for rel in service.files[group]
    ]


def blank(pattern: re.Pattern[str], text: str) -> str:
    """Replace every match with blank lines, so line numbers of the rest don't move."""
    return pattern.sub(lambda m: "\n" * m.group().count("\n") or " ", text)


def java_code(text: str, keep_strings: bool) -> str:
    """Source with comments blanked (and string literals too, unless `keep_strings`)."""

    def replace(m: re.Match[str]) -> str:
        if keep_strings and m.group()[0] in "\"'":
            return m.group()
        return "\n" * m.group().count("\n") or " "

    return _CODE_TOKENS.sub(replace, text)


def xml_code(text: str) -> str:
    """XML with <!-- comments --> blanked."""
    return blank(_XML_COMMENT, text)


def line_at(text: str, index: int) -> int:
    """1-indexed line number of a character position."""
    return text.count("\n", 0, index) + 1


def trim_snippet(lines: list[str]) -> str:
    """Join lines, cutting at a line boundary to stay within SNIPPET_MAX_CHARS."""
    text = "\n".join(lines)
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    cut = text[: SNIPPET_MAX_CHARS - len(_TRUNCATED)]
    if "\n" in cut:
        cut = cut[: cut.rindex("\n")]
    return cut + _TRUNCATED
