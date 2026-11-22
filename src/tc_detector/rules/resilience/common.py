"""Helpers shared by the resilience rules.

File walking and service naming belong to Vatsalya's scanner. These are stand-ins
so the rules can be built and tested now; swap them for the scanner's inventory
when it lands. Candidates themselves are built with the shared, frozen
`Candidate.create()`, so every rule output is validated the moment it is made.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.contracts.ids import SNIPPET_MAX_CHARS

EXCLUDED_DIRS = {
    ".git",
    "target",
    "build",
    "out",
    "node_modules",
    ".idea",
    ".gradle",
    ".mvn",
    "test",
    "tests",
}
BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")
_TRUNCATED = "\n[... truncated]"


@dataclass(frozen=True)
class Hit:
    """One detected range inside one file, before it becomes a candidate."""

    start: int  # 1-indexed, inclusive
    end: int  # 1-indexed, inclusive
    rule_id: str


def iter_files(repo: Path, suffixes: tuple[str, ...]) -> Iterator[Path]:
    """Source files under `repo`, skipping build output and test code.

    Test code is excluded on purpose: a test that configures a circuit breaker
    is not credit the production system holds.
    """
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo)
        if any(part in EXCLUDED_DIRS for part in rel.parts[:-1]):
            continue
        if path.is_file() and path.name.endswith(suffixes):
            yield path


def module_dirs(repo: Path) -> list[Path]:
    """Directories (below the root) that hold a build file: one per service."""
    found = {p.parent for name in BUILD_FILES for p in repo.rglob(name)}
    return sorted(
        d
        for d in found
        if d != repo and not any(part in EXCLUDED_DIRS for part in d.relative_to(repo).parts)
    )


def _common_dash_prefix(names: list[str]) -> str:
    if len(names) < 2:
        return ""
    split = [n.split("-") for n in names]
    prefix: list[str] = []
    for tokens in zip(*split, strict=False):
        if len(set(tokens)) != 1:
            break
        prefix.append(tokens[0])
    # Never strip a whole name away.
    if any(len(s) <= len(prefix) for s in split):
        prefix = prefix[:-1]
    return "-".join(prefix) + "-" if prefix else ""


class ServiceNamer:
    """Maps a file to its service: nearest module dir, minus the repo-wide prefix.

    PetClinic's `spring-petclinic-api-gateway/...` becomes `api-gateway`, matching
    the example in the candidate format. Files outside any module get `_repo`.
    """

    def __init__(self, repo: Path):
        self.repo = repo
        self.modules = module_dirs(repo)
        self.prefix = _common_dash_prefix([m.name for m in self.modules])

    def root(self, path: Path) -> Path:
        """The service root `path` lives in (the repo root if it is in no module)."""
        best = None
        for m in self.modules:
            if path.is_relative_to(m) and (best is None or len(m.parts) > len(best.parts)):
                best = m
        return best if best is not None else self.repo

    def __call__(self, path: Path) -> str:
        root = self.root(path)
        if root == self.repo:
            return "_repo"
        name = root.name
        return name[len(self.prefix) :] if self.prefix and name.startswith(self.prefix) else name


def head_commit(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def merge_hits(hits: list[Hit], gap: int = 0) -> list[Hit]:
    """Merge hits whose ranges overlap or sit within `gap` lines of each other.

    The first rule id (by start line) wins, so one region yields one candidate,
    which is what one-to-one matching expects.
    """
    merged: list[Hit] = []
    for h in sorted(hits, key=lambda h: (h.start, h.end)):
        if merged and h.start <= merged[-1].end + gap + 1:
            last = merged[-1]
            merged[-1] = Hit(last.start, max(last.end, h.end), last.rule_id)
        else:
            merged.append(h)
    return merged


def trim_snippet(lines: list[str]) -> str:
    """Join lines, cutting at a line boundary to stay within SNIPPET_MAX_CHARS."""
    text = "\n".join(lines)
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    cut = text[: SNIPPET_MAX_CHARS - len(_TRUNCATED)]
    if "\n" in cut:
        cut = cut[: cut.rindex("\n")]
    return cut + _TRUNCATED


def make_candidate(
    *,
    path: Path,
    service_root: Path,
    hit: Hit,
    lines: list[str],
    repo_name: str,
    commit: str,
    service: str,
    pattern: str,
    category: Category,
) -> Candidate:
    """Build a validated Candidate; `file` is relative to the service root."""
    return Candidate.create(
        repo=repo_name,
        commit=commit,
        service=service,
        file=path.relative_to(service_root).as_posix(),
        line_start=hit.start,
        line_end=hit.end,
        unit=Unit.LINE_RANGE,
        pattern=pattern,
        category=category,
        rule_id=hit.rule_id,
        snippet=trim_snippet(lines[hit.start - 1 : hit.end]),
    )
