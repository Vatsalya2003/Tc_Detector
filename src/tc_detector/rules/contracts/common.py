"""Helpers shared by the contracts rules. Owner: Abhi (B).

Service discovery, file walking and naming belong to Vatsalya's scanner. These are
stand-ins so the rules can be built and tested now; swap them for the scanner's
inventory when it lands. They follow Karan's gateway rule, so both rules name the
same service the same way (and match the same labels):

  - a service is a folder below the repo root that holds a build file
    (or the repo root itself, if there are none);
  - its name is `spring.application.name` from application*/bootstrap* config,
    falling back to the folder name minus the prefix all service folders share
    (`spring-petclinic-config-server` -> `config-server`);
  - test code and build output are skipped.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import yaml

from tc_detector.contracts.ids import SNIPPET_MAX_CHARS

BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")
CONFIG_SUFFIXES = (".yml", ".yaml", ".properties")
# Test code is skipped on purpose: a DTO that only a test builds is not a contract
# the running system holds.
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
_TRUNCATED = "\n[... truncated]"
_PROP_APP_NAME = re.compile(r"^\s*spring\.application\.name\s*[=:]\s*(\S+)")


@dataclass(frozen=True)
class Service:
    """One service: its root folder and its name."""

    root: Path
    name: str


def _excluded(rel: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in rel.parts)


def _common_dash_prefix(names: list[str]) -> str:
    """`spring-petclinic-` for ["spring-petclinic-a", "spring-petclinic-b"]; never a whole name."""
    if len(names) < 2:
        return ""
    split = [n.split("-") for n in names]
    prefix: list[str] = []
    for tokens in zip(*split, strict=False):
        if len(set(tokens)) != 1:
            break
        prefix.append(tokens[0])
    if any(len(s) <= len(prefix) for s in split):
        prefix = prefix[:-1]
    return "-".join(prefix) + "-" if prefix else ""


def _config_files(root: Path) -> list[Path]:
    """application*/bootstrap* config files of one service, application.* first."""
    resources = root / "src" / "main" / "resources"
    if not resources.is_dir():
        return []
    files = [
        p
        for p in resources.iterdir()
        if p.is_file()
        and p.suffix in CONFIG_SUFFIXES
        and p.name.startswith(("application", "bootstrap"))
    ]
    return sorted(files, key=lambda p: (p.stem != "application", p.name))


def _yaml_app_name(text: str) -> str | None:
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return None
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        value = doc.get("spring.application.name")
        spring = doc.get("spring")
        if value is None and isinstance(spring, dict):
            app = spring.get("application")
            value = app.get("name") if isinstance(app, dict) else spring.get("application.name")
        if isinstance(value, str) and value.strip() and "${" not in value:
            return value.strip()
    return None


def _app_name(root: Path) -> str | None:
    """`spring.application.name` of one service, or None if it isn't set."""
    for path in _config_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix == ".properties":
            for line in text.splitlines():
                m = _PROP_APP_NAME.match(line)
                if m and "${" not in m.group(1):
                    return m.group(1)
        else:
            name = _yaml_app_name(text)
            if name:
                return name
    return None


def find_services(repo: Path) -> list[Service]:
    """Every service in the repo, with its name (see module docstring)."""
    roots = sorted({p.parent for name in BUILD_FILES for p in repo.rglob(name)} - {repo})
    roots = [r for r in roots if not _excluded(r.relative_to(repo))]
    if not roots:
        return [Service(repo, _app_name(repo) or repo.name)]
    prefix = _common_dash_prefix([r.name for r in roots])
    return [
        Service(root, _app_name(root) or (root.name.removeprefix(prefix) if prefix else root.name))
        for root in roots
    ]


def service_files(service: Service, all_roots: list[Path], suffix: str) -> Iterator[Path]:
    """Files of this service ending in `suffix`; not test code, build output or nested services."""
    nested = [r for r in all_roots if r != service.root and r.is_relative_to(service.root)]
    for path in sorted(service.root.rglob(f"*{suffix}")):
        if not path.is_file() or _excluded(path.relative_to(service.root).parent):
            continue
        if not any(path.is_relative_to(n) for n in nested):
            yield path


def head_commit(repo: Path) -> str:
    """The checkout's HEAD SHA, or "unknown" if it isn't a git repo."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def trim_snippet(lines: list[str]) -> str:
    """Join lines, cutting at a line boundary to stay within SNIPPET_MAX_CHARS."""
    text = "\n".join(lines)
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    cut = text[: SNIPPET_MAX_CHARS - len(_TRUNCATED)]
    if "\n" in cut:
        cut = cut[: cut.rindex("\n")]
    return cut + _TRUNCATED
