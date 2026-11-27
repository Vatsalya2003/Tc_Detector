"""Externalised configuration detection. Owner: Karan (D).

Pattern `externalised-config`, category `configurability`, matching unit `service`.
One candidate per service that loads its config from outside its own code;
see ground_truth/GUIDELINES.md, section `externalised-config`.

Signals (either one is enough):

  import     `spring.config.import` with an entry `configserver:...`, with or without the
             `optional:` prefix, in an application*/bootstrap* .yml/.yaml/.properties file
             (profile variants such as application-docker.yml included). This is the
             signal the guideline lists.
  bootstrap  `spring.cloud.config.uri` set in a bootstrap*.yml/.yaml/.properties file: the
             pre-Spring-Boot-2.4 way to load config from a config server. It follows from
             the guideline's definition; PetClinic doesn't use it.

Supporting evidence, only added to the snippet of a service that already qualifies:

  dependency  spring-cloud-starter-config / spring-cloud-config-client in the build file.
              On its own it imports nothing, so it never makes a service a candidate.

Not signals (guideline negatives and edge cases):
  - the config server itself: it serves config, its own config is local;
  - `${ENV_VAR}` placeholders, including a bare `spring.config.import: ${X}`;
  - non-config-server imports such as `optional:classpath:/creds.yaml` or `file:`;
  - `@ConfigurationProperties` classes and Kubernetes ConfigMaps.

Services, their names and their config files come from the scanner, like the
observability and resilience rules.

Run by hand (prints one candidate JSON per line). Development set only:
    uv run python -m tc_detector.rules.abstraction.externalised_config \\
        targets/spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.contracts.ids import SNIPPET_MAX_CHARS
from tc_detector.scanner import scan
from tc_detector.scanner.inventory import Inventory, Service

PATTERN = "externalised-config"
CATEGORY = Category.CONFIGURABILITY
RULE_ID = "configurability-externalised-config-01"

IMPORT_KEY = ("spring", "config", "import")
BOOTSTRAP_URI_KEY = ("spring", "cloud", "config", "uri")
_TRUNCATED = "\n[... truncated]"

# `spring.config.import`, optionally indexed (`spring.config.import[0]`), in a .properties file.
_PROP_LINE = re.compile(r"^\s*([\w.\-\[\]]+)\s*[=:]\s*(.*?)\s*$")
_INDEX = re.compile(r"\[\d+\]$")
_DEPENDENCY = re.compile(r"\b(spring-cloud-starter-config|spring-cloud-config-client)\b")


@dataclass
class Evidence:
    """The signals found in one service; each entry is one line of the snippet."""

    signals: list[str] = field(default_factory=list)
    dependency: list[str] = field(default_factory=list)

    def is_candidate(self) -> bool:
        return bool(self.signals)


# ------------------------------------------------------------------ parsing


def split_imports(value: str) -> list[str]:
    """Split a `spring.config.import` value on commas outside `${...}` placeholders."""
    parts, depth, current = [], 0, []
    i = 0
    while i < len(value):
        if value.startswith("${", i):
            depth += 1
            current.append("${")
            i += 2
            continue
        c = value[i]
        if c == "}" and depth:
            depth -= 1
        if c == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(c)
        i += 1
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def is_config_server_import(entry: str) -> bool:
    """True for `configserver:...` and `optional:configserver:...`."""
    entry = entry.strip()
    entry = entry.removeprefix("optional:")
    return entry.startswith("configserver:")


def _key(node: Any) -> str:
    return str(node.value) if isinstance(node, yaml.ScalarNode) else ""


def yaml_values(text: str, wanted: tuple[str, ...]) -> list[tuple[int, str]]:
    """(1-based line, value) of every scalar under the key path `wanted`.

    Dotted keys at any level count (`spring: {config.import: x}`), as do lists of values.
    Every document of a multi-document file (profile sections) is searched.
    """
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    found: list[tuple[int, str]] = []

    def visit(node: Any, path: tuple[str, ...]) -> None:
        if not isinstance(node, yaml.MappingNode):
            return
        for k, v in node.value:
            full = (*path, *_key(k).split("."))
            if full == wanted:
                if isinstance(v, yaml.ScalarNode):
                    found.append((k.start_mark.line + 1, str(v.value)))
                elif isinstance(v, yaml.SequenceNode):
                    found.extend(
                        (item.start_mark.line + 1, str(item.value))
                        for item in v.value
                        if isinstance(item, yaml.ScalarNode)
                    )
            elif wanted[: len(full)] == full:
                visit(v, full)

    for doc in docs:
        visit(doc, ())
    return found


def properties_values(text: str, wanted: tuple[str, ...]) -> list[tuple[int, str]]:
    """(1-based line, value) of every `wanted` key in a .properties file (`[n]` allowed)."""
    key = ".".join(wanted)
    found = []
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(("#", "!")):
            continue
        m = _PROP_LINE.match(line)
        if m and _INDEX.sub("", m.group(1)) == key:
            found.append((i, m.group(2)))
    return found


def config_values(rel: str, text: str, wanted: tuple[str, ...]) -> list[tuple[int, str]]:
    if rel.endswith(".properties"):
        return properties_values(text, wanted)
    return yaml_values(text, wanted)


# ------------------------------------------------------------------ signals


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def collect(repo: Path, service: Service) -> Evidence:
    """Gather every signal for one service."""
    ev = Evidence()
    folder = repo / service.root
    for rel in service.files["config"]:
        text = _read(folder / rel)
        for line, value in config_values(rel, text, IMPORT_KEY):
            for entry in split_imports(value):
                if is_config_server_import(entry):
                    ev.signals.append(f"spring.config.import {entry} at {rel}:{line}")
        if PurePosixPath(rel).name.startswith("bootstrap"):
            for line, value in config_values(rel, text, BOOTSTRAP_URI_KEY):
                if value.strip():
                    ev.signals.append(
                        f"bootstrap spring.cloud.config.uri {value.strip()} at {rel}:{line}"
                    )
    for rel in service.files["build"]:
        for i, line in enumerate(_read(folder / rel).splitlines(), start=1):
            if m := _DEPENDENCY.search(line):
                ev.dependency.append(f"config client dependency {m.group(1)} at {rel}:{i}")
    return ev


# ------------------------------------------------------------------- output


def _snippet(service: str, ev: Evidence) -> str:
    lines = [f"{PATTERN} candidate: service {service}"]
    lines += [f"signal: {s}" for s in ev.signals]
    lines += [f"supporting: {d}" for d in ev.dependency]
    text = "\n".join(lines)
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    cut = text[: SNIPPET_MAX_CHARS - len(_TRUNCATED)]
    return cut[: cut.rindex("\n")] + _TRUNCATED


def detect(
    repo: Path | str,
    repo_name: str | None = None,
    commit: str | None = None,
    inventory: Inventory | None = None,
) -> list[Candidate]:
    """Service-unit candidates for every service that loads config from a config server.

    Pass `inventory` to reuse a scan; otherwise the repo is scanned here.
    """
    repo = Path(repo).resolve()
    inv = inventory or scan(repo, repo_name, commit)
    candidates = []
    for service in inv.services:
        ev = collect(repo, service)
        if not ev.is_candidate():
            continue
        candidates.append(
            Candidate.create(
                repo=inv.repo,
                commit=inv.commit,
                service=service.name,
                file=None,
                line_start=None,
                line_end=None,
                unit=Unit.SERVICE,
                pattern=PATTERN,
                category=CATEGORY,
                rule_id=RULE_ID,
                snippet=_snippet(service.name, ev),
            )
        )
    return candidates


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tc_detector.rules.abstraction.externalised_config")
    p.add_argument("repo_path", type=Path)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    args = p.parse_args(argv)
    for candidate in detect(args.repo_path, args.repo_name, args.commit):
        print(candidate.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
