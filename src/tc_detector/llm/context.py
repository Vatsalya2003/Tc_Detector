"""Facts the Stage 3 prompt needs beyond the candidate itself.

Everything here must be deterministic for a pinned commit: the rendered prompt
is part of the cache key, so a value like "file age as of today" would silently
break caching and reproducibility. Ages are measured up to the pinned commit.

`service_role` and `n_consumers` should come from Vatsalya's scanner inventory
once it lands; until then callers may pass them in, and they default to "unknown".
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

_SECONDS_PER_MONTH = 30.44 * 24 * 3600
_ADR_DIRS = ("docs/decisions", "docs/adr", "docs/adrs", "doc/adr", "adr", "architecture/decisions")
_BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")


def _git(repo: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout


def _resolve_commit(commit: str | None) -> str:
    if commit and re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        return commit
    return "HEAD"


def repo_path(repo: Path, candidate: dict[str, Any]) -> str | None:
    """The candidate's file as a path from the repo root.

    Candidate `file` is relative to the service root, so look for a module
    directory named after the service (PetClinic: `spring-petclinic-<service>`).
    """
    file = candidate.get("file")
    if not file:
        return None
    service = candidate.get("service", "")
    if service == "_repo" and (repo / file).is_file():
        return file
    for build in _BUILD_FILES:
        for b in sorted(repo.rglob(build)):
            module = b.parent
            if module != repo and module.name.endswith(service) and (module / file).is_file():
                return (module / file).relative_to(repo).as_posix()
    return file if (repo / file).is_file() else None


def git_history(repo: Path, file: str, commit: str | None = None) -> dict[str, Any]:
    """File age in months, commit count and contributor count, up to `commit`."""
    rev = _resolve_commit(commit)
    head_time = _git(repo, "show", "-s", "--format=%ct", rev)
    log = _git(repo, "log", "--follow", "--format=%at%x09%ae", rev, "--", file)
    if not head_time or not log:
        return {"age_months": "unknown", "n_commits": "unknown", "n_contributors": "unknown"}
    rows = [line.split("\t", 1) for line in log.splitlines() if "\t" in line]
    first = min(int(t) for t, _ in rows)
    age = max(0.0, (int(head_time.strip()) - first) / _SECONDS_PER_MONTH)
    return {
        "age_months": round(age),
        "n_commits": len(rows),
        "n_contributors": len({email.lower() for _, email in rows}),
    }


def existing_adr_titles(repo: Path) -> list[str]:
    """First Markdown heading of each ADR file in the usual ADR folders."""
    titles: list[str] = []
    for rel in _ADR_DIRS:
        d = repo / rel
        if not d.is_dir():
            continue
        for md in sorted(d.glob("*.md")):
            for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("#"):
                    titles.append(line.lstrip("#").strip())
                    break
    return titles


def numbered_snippet(candidate: dict[str, Any]) -> str:
    """The candidate's snippet with real line numbers, when it has a line range."""
    snippet = candidate.get("snippet") or ""
    start = candidate.get("line_start")
    if not snippet or not start:
        return snippet
    lines = snippet.splitlines()
    width = len(str(start + len(lines)))
    return "\n".join(
        text if text.startswith("[... truncated") else f"{start + i:>{width}} | {text}"
        for i, text in enumerate(lines)
    )


def build_context(
    candidate: dict[str, Any],
    repo: Path | str | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "service_role": "unknown",
        "n_consumers": "unknown",
        "age_months": "unknown",
        "n_commits": "unknown",
        "n_contributors": "unknown",
        "adr_titles": [],
    }
    if repo is not None:
        repo = Path(repo)
        path = repo_path(repo, candidate)
        if path:
            ctx.update(git_history(repo, path, candidate.get("commit")))
        ctx["adr_titles"] = existing_adr_titles(repo)
    if overrides:
        ctx.update(overrides)
    return ctx
