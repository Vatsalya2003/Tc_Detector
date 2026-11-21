"""S12: gateway / anti-corruption layer detection. Owner: Karan (D).

Pattern `gateway`, category `abstraction`, matching unit `service`.
One candidate per gateway service; see ground_truth/GUIDELINES.md, section `gateway`.

Signals:

  strong  gateway routes: a `routes` list under `spring.cloud.gateway` (any variant,
          e.g. `spring.cloud.gateway.server.webflux.routes`) whose entries have a `uri`,
          in application*/bootstrap* .yml/.yaml/.properties
  strong  Zuul proxy: `@EnableZuulProxy` in Java, or a `zuul.routes` config
  weak    gateway dependency: spring-cloud-starter-gateway* or
          spring-cloud-starter-netflix-zuul in the service's pom.xml / build.gradle(.kts)
  weak    calls 2+ other services of the same repo from Java, via @FeignClient("svc"),
          "http://svc/...", "lb://svc" or getInstances("svc")
  weak    a whole word of the service name (split on "-" and "_") is one of
          gateway, bff, proxy, edge, facade, adapter

A service is a candidate if it has any strong signal, or a name signal plus a
dependency or call signal. Class names are never used: an `...Adapter` class inside
an ordinary service is not a gateway. A dependency plus calls without a name is not
enough either (PetClinic's genai-service has both and is not a gateway).

Deliberately not detected: routes built in Java with RouteLocatorBuilder.

Service discovery and naming are stand-ins until the scanner lands:
  - a service is a folder below the repo root that holds a build file
    (or the repo root itself, if there are none); test code and build output are skipped;
  - its name is `spring.application.name`, falling back to the folder name minus the
    prefix all service folders share (`spring-petclinic-config-server` -> `config-server`).

Run by hand (prints one candidate JSON per line):
    uv run python -m tc_detector.rules.abstraction.gateway targets/spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.contracts.ids import SNIPPET_MAX_CHARS

PATTERN = "gateway"
CATEGORY = Category.ABSTRACTION
RULE_ID = "abstraction-gateway-01"

NAME_WORDS = {"gateway", "bff", "proxy", "edge", "facade", "adapter"}
BUILD_FILES = ("pom.xml", "build.gradle", "build.gradle.kts")
CONFIG_SUFFIXES = (".yml", ".yaml", ".properties")
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

_DEPENDENCY = re.compile(
    r"\b(spring-cloud-starter-gateway[\w-]*|spring-cloud-starter-netflix-zuul)\b"
)
_ZUUL_ANNOTATION = re.compile(r"@EnableZuulProxy\b")
_CALL_TARGETS = (
    re.compile(r'@FeignClient\(\s*(?:(?:name|value)\s*=\s*)?"([\w.-]+)"'),
    re.compile(r'"(?:https?|lb)://([\w.-]+)'),
    re.compile(r'getInstances\(\s*"([\w.-]+)"\s*\)'),
)
_PROP_APP_NAME = re.compile(r"^\s*spring\.application\.name\s*[=:]\s*(\S+)")
_PROP_ROUTE_URI = re.compile(
    r"^\s*spring\.cloud\.gateway\.[\w.-]*routes\[\d+\]\.uri\s*[=:]\s*(\S+)"
)
_PROP_ZUUL_ROUTE = re.compile(r"^\s*zuul\.routes\.")


@dataclass(frozen=True)
class Service:
    """One service: its root folder and its name."""

    root: Path
    name: str


@dataclass
class Evidence:
    """The signals found in one service; each entry is one line of the snippet."""

    strong: list[str] = field(default_factory=list)
    dependency: list[str] = field(default_factory=list)
    calls: dict[str, str] = field(default_factory=dict)  # target service -> where
    name_words: list[str] = field(default_factory=list)

    def is_candidate(self) -> bool:
        weak_support = bool(self.dependency) or len(self.calls) >= 2
        return bool(self.strong) or (bool(self.name_words) and weak_support)


# ------------------------------------------------------------------ services


def _excluded(rel: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in rel.parts)


def _iter_files(root: Path) -> Iterator[Path]:
    """Files under `root`, skipping test code and build output."""
    for path in sorted(root.rglob("*")):
        if path.is_file() and not _excluded(path.relative_to(root).parent):
            yield path


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


def _config_files(root: Path) -> list[Path]:
    """application*/bootstrap* config files of one service, application.yml first."""
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


def _app_name(root: Path) -> str | None:
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
    roots = sorted(
        {p.parent for name in BUILD_FILES for p in repo.rglob(name)} - {repo},
    )
    roots = [r for r in roots if not _excluded(r.relative_to(repo))]
    if not roots:
        return [Service(repo, _app_name(repo) or repo.name)]
    prefix = _common_dash_prefix([r.name for r in roots])
    services = []
    for root in roots:
        fallback = root.name.removeprefix(prefix) if prefix else root.name
        services.append(Service(root, _app_name(root) or fallback))
    return services


def _own_files(service: Service, all_roots: list[Path]) -> Iterator[Path]:
    """Files of this service, not of a service nested inside it."""
    nested = [r for r in all_roots if r != service.root and r.is_relative_to(service.root)]
    for path in _iter_files(service.root):
        if not any(path.is_relative_to(n) for n in nested):
            yield path


# ------------------------------------------------------------------- signals


def name_words(service_name: str) -> list[str]:
    """Whole words of the name that signal a gateway (`knowledge-service` has none)."""
    return [w for w in re.split(r"[-_]", service_name.lower()) if w in NAME_WORDS]


def _key(node: Any) -> str:
    return str(node.value) if isinstance(node, yaml.ScalarNode) else ""


def _last_line(node: Any) -> int:
    """Last 1-indexed line holding content of `node`."""
    if isinstance(node, yaml.MappingNode | yaml.SequenceNode):
        children = [v for _, v in node.value] if isinstance(node, yaml.MappingNode) else node.value
        return max([_last_line(c) for c in children] + [node.start_mark.line + 1])
    end = node.end_mark
    if end.column == 0 and end.line > node.start_mark.line:
        return end.line
    return end.line + 1


def _route_uris(routes: Any) -> list[str]:
    uris = []
    for item in routes.value:
        if isinstance(item, yaml.MappingNode):
            uris += [_key(v) for k, v in item.value if _key(k) == "uri" and _key(v)]
    return uris


def yaml_signals(text: str, where: str) -> list[str]:
    """Strong signals in one YAML file: gateway routes with a uri, Zuul routes."""
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    found: list[str] = []

    def visit(node: Any, path: tuple[str, ...]) -> None:
        if not isinstance(node, yaml.MappingNode):
            return
        for k, v in node.value:
            full = (*path, *_key(k).split("."))
            lines = f"{where}:{k.start_mark.line + 1}-{_last_line(v)}"
            is_gateway = full[:3] == ("spring", "cloud", "gateway")
            if is_gateway and full[-1] == "routes" and isinstance(v, yaml.SequenceNode):
                uris = _route_uris(v)
                if uris:
                    found.append(f"gateway routes at {lines} -> {', '.join(uris)}")
                continue
            if full[:2] == ("zuul", "routes") and isinstance(v, yaml.MappingNode) and v.value:
                found.append(f"zuul routes at {lines}")
                continue
            visit(v, full)

    for doc in docs:
        visit(doc, ())
    return found


def properties_signals(text: str, where: str) -> list[str]:
    """Strong signals in one .properties file."""
    uris, uri_lines, zuul_lines = [], [], []
    for i, line in enumerate(text.splitlines(), start=1):
        if m := _PROP_ROUTE_URI.match(line):
            uris.append(m.group(1))
            uri_lines.append(i)
        elif _PROP_ZUUL_ROUTE.match(line):
            zuul_lines.append(i)
    found = []
    if uris:
        found.append(
            f"gateway routes at {where}:{uri_lines[0]}-{uri_lines[-1]} -> {', '.join(uris)}"
        )
    if zuul_lines:
        found.append(f"zuul routes at {where}:{zuul_lines[0]}-{zuul_lines[-1]}")
    return found


def collect(service: Service, all_roots: list[Path], known: set[str]) -> Evidence:
    """Gather every signal for one service."""
    ev = Evidence(name_words=name_words(service.name))
    config_files = set(_config_files(service.root))
    for path in _own_files(service, all_roots):
        where = path.relative_to(service.root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if path in config_files:
            if path.suffix == ".properties":
                ev.strong += properties_signals(text, where)
            else:
                ev.strong += yaml_signals(text, where)
        elif path.parent == service.root and path.name in BUILD_FILES:
            for i, line in enumerate(text.splitlines(), start=1):
                if m := _DEPENDENCY.search(line):
                    ev.dependency.append(f"gateway dependency {m.group(1)} at {where}:{i}")
        elif path.suffix == ".java":
            for i, line in enumerate(text.splitlines(), start=1):
                if _ZUUL_ANNOTATION.search(line):
                    ev.strong.append(f"@EnableZuulProxy at {where}:{i}")
                for pattern in _CALL_TARGETS:
                    for target in pattern.findall(line):
                        if target in known and target != service.name:
                            ev.calls.setdefault(target, f"{where}:{i}")
    return ev


# ------------------------------------------------------------------- output


def _snippet(service: str, ev: Evidence) -> str:
    lines = [f"gateway candidate: service {service}"]
    lines += [f"strong: {s}" for s in ev.strong]
    lines += [f"weak: {d}" for d in ev.dependency]
    if ev.calls:
        targets = ", ".join(f"{t} ({w})" for t, w in sorted(ev.calls.items()))
        lines.append(f"weak: calls {len(ev.calls)} other services: {targets}")
    if ev.name_words:
        lines.append(f"weak: service name word(s): {', '.join(ev.name_words)}")
    text = "\n".join(lines)
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    cut = text[: SNIPPET_MAX_CHARS - len(_TRUNCATED)]
    return cut[: cut.rindex("\n")] + _TRUNCATED


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


def detect(
    repo: Path | str,
    repo_name: str | None = None,
    commit: str | None = None,
) -> list[Candidate]:
    """Run the rule over a checkout and return validated service-unit candidates.

    `repo_name` defaults to the checkout's folder name. scripts/clone_targets.py clones
    each target into targets/<name>, so that folder name is the target's `name` in
    targets.yaml (e.g. `spring-petclinic-microservices`). Pass it explicitly otherwise.
    `commit` defaults to the checkout's HEAD.
    """
    repo = Path(repo).resolve()
    repo_name = repo_name or repo.name
    commit = commit or head_commit(repo)
    services = find_services(repo)
    roots = [s.root for s in services]
    known = {s.name for s in services}
    candidates = []
    for service in services:
        ev = collect(service, roots, known)
        if not ev.is_candidate():
            continue
        candidates.append(
            Candidate.create(
                repo=repo_name,
                commit=commit,
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
    p = argparse.ArgumentParser(prog="python -m tc_detector.rules.abstraction.gateway")
    p.add_argument("repo_path", type=Path)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    args = p.parse_args(argv)
    for candidate in detect(args.repo_path, args.repo_name, args.commit):
        print(candidate.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
