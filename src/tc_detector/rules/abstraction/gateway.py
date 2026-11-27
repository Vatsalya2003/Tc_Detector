"""S12: gateway detection. Owner: Karan (D).

Pattern `gateway`, category `abstraction`, matching unit `service`.
One candidate per gateway service; see ground_truth/GUIDELINES.md, section `gateway`
("one service that is the single entry point and routes requests to the other services").

Signals:

  strong  gateway routes: a `routes` list under `spring.cloud.gateway` (any variant,
          e.g. `spring.cloud.gateway.server.webflux.routes`) whose entries have a `uri`,
          in application*/bootstrap* .yml/.yaml/.properties
  strong  Java-defined gateway routes: a @Bean method returning RouteLocator that uses
          RouteLocatorBuilder and defines a route (`.routes()`, `.route(`, `.uri(`)
  strong  Zuul proxy: `@EnableZuulProxy` in Java, or a `zuul.routes` config
  weak    gateway dependency: spring-cloud-starter-gateway* or
          spring-cloud-starter-netflix-zuul in the service's pom.xml / build.gradle(.kts)
  weak    a whole word of the service name (split on "-" and "_") is one of
          gateway, bff, proxy, edge, facade, adapter

A service is a candidate if it has any strong signal, or a name signal plus the gateway
dependency. Class names are never used: an `...Adapter` class inside an ordinary service
is not a gateway.

Supporting evidence, added to a candidate's snippet but never deciding whether it is one:

  - cross-cutting filters: `default-filters` and per-route `filters` under
    `spring.cloud.gateway` (the guideline's "filters applied in one place");
  - calls to other services of the same repo from Java, via @FeignClient("svc"),
    "http://svc/...", "lb://svc" or getInstances("svc").

Calls used to count with a name signal (name + calls to 2+ services). That path was
removed: the guideline defines a gateway by routing, and says nothing about flagging an
anti-corruption layer, adapter or BFF by its name and the calls it makes.

Services, their names and their files come from the scanner (`scanner.scan()`), so the
service names match the ones the labels use.

Run by hand (prints one candidate JSON per line). Development set only:
    uv run python -m tc_detector.rules.abstraction.gateway targets/spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.contracts.ids import SNIPPET_MAX_CHARS
from tc_detector.scanner import scan
from tc_detector.scanner.inventory import Inventory, Service

PATTERN = "gateway"
CATEGORY = Category.ABSTRACTION
RULE_ID = "abstraction-gateway-01"

NAME_WORDS = {"gateway", "bff", "proxy", "edge", "facade", "adapter"}
_TRUNCATED = "\n[... truncated]"

_DEPENDENCY = re.compile(
    r"\b(spring-cloud-starter-gateway[\w-]*|spring-cloud-starter-netflix-zuul)\b"
)
# @EnableZuulProxy counts on its own, even with no `zuul.routes`: with service discovery,
# Zuul routes to every registered service automatically, so the annotation alone makes
# the service the routing entry point.
_ZUUL_ANNOTATION = re.compile(r"@EnableZuulProxy\b")
# `@Bean` (plus other annotations/modifiers, but no `{` `}` `;` in between) on a method
# whose return type is RouteLocator.
_ROUTE_LOCATOR_BEAN = re.compile(r"@Bean\b[^;{}]*?\bRouteLocator\s+\w+\s*\(")
_ROUTE_DSL_CALLS = (
    re.compile(r"\.routes\(\s*\)"),
    re.compile(r"\.route\("),
    re.compile(r"\.uri\("),
)
_ROUTE_DSL_URI = re.compile(r'\.uri\(\s*"([^"]+)"')
_CALL_TARGETS = (
    re.compile(r'@FeignClient\(\s*(?:(?:name|value)\s*=\s*)?"([\w.-]+)"'),
    re.compile(r'"(?:https?|lb)://([\w.-]+)'),
    re.compile(r'getInstances\(\s*"([\w.-]+)"\s*\)'),
)
_PROP_ROUTE_URI = re.compile(
    r"^\s*spring\.cloud\.gateway\.[\w.-]*routes\[\d+\]\.uri\s*[=:]\s*(\S+)"
)
_PROP_DEFAULT_FILTER = re.compile(
    r"^\s*spring\.cloud\.gateway\.[\w.-]*default-filters\[\d+\](?:\.name)?\s*[=:]\s*(\S+)"
)
_PROP_ROUTE_FILTER = re.compile(
    r"^\s*spring\.cloud\.gateway\.[\w.-]*routes\[\d+\]\.filters\[\d+\](?:\.name)?\s*[=:]\s*(\S+)"
)
_PROP_ZUUL_ROUTE = re.compile(r"^\s*zuul\.routes\.")


@dataclass
class Evidence:
    """The signals found in one service; each entry is one line of the snippet."""

    strong: list[str] = field(default_factory=list)
    dependency: list[str] = field(default_factory=list)
    name_words: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)  # supporting only
    calls: dict[str, str] = field(default_factory=dict)  # supporting only: target -> where

    def is_candidate(self) -> bool:
        return bool(self.strong) or (bool(self.name_words) and bool(self.dependency))


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


def filter_name(item: Any) -> str:
    """`StripPrefix` for `- StripPrefix=2`; `CircuitBreaker` for `- name: CircuitBreaker`."""
    if isinstance(item, yaml.ScalarNode):
        return str(item.value).split("=", 1)[0].strip()
    if isinstance(item, yaml.MappingNode):
        return next((_key(v) for k, v in item.value if _key(k) == "name"), "")
    return ""


def _filter_names(filters: Any) -> list[str]:
    if not isinstance(filters, yaml.SequenceNode):
        return []
    return [n for n in (filter_name(item) for item in filters.value) if n]


def _route_filters(routes: Any, where: str) -> list[str]:
    """One line per route that has filters: where they are and their names."""
    found = []
    for item in routes.value:
        if not isinstance(item, yaml.MappingNode):
            continue
        for k, v in item.value:
            names = _filter_names(v) if _key(k) == "filters" else []
            if names:
                lines = f"{where}:{k.start_mark.line + 1}-{_last_line(v)}"
                found.append(f"route filters at {lines} -> {', '.join(names)}")
    return found


def yaml_signals(text: str, where: str) -> tuple[list[str], list[str]]:
    """(strong signals, supporting filters) in one YAML file."""
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return [], []
    strong: list[str] = []
    filters: list[str] = []

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
                    strong.append(f"gateway routes at {lines} -> {', '.join(uris)}")
                filters.extend(_route_filters(v, where))
                continue
            if is_gateway and full[-1] == "default-filters":
                names = _filter_names(v)
                if names:
                    filters.append(f"default filters at {lines} -> {', '.join(names)}")
                continue
            if full[:2] == ("zuul", "routes") and isinstance(v, yaml.MappingNode) and v.value:
                strong.append(f"zuul routes at {lines}")
                continue
            visit(v, full)

    for doc in docs:
        visit(doc, ())
    return strong, filters


def _prop_lines(matches: list[tuple[int, str]], what: str, where: str) -> list[str]:
    if not matches:
        return []
    first, last = matches[0][0], matches[-1][0]
    names = ", ".join(dict.fromkeys(v.split("=", 1)[0] for _, v in matches))
    return [f"{what} at {where}:{first}-{last} -> {names}"]


def properties_signals(text: str, where: str) -> tuple[list[str], list[str]]:
    """(strong signals, supporting filters) in one .properties file."""
    uris: list[tuple[int, str]] = []
    zuul: list[int] = []
    default_filters: list[tuple[int, str]] = []
    route_filters: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if m := _PROP_ROUTE_URI.match(line):
            uris.append((i, m.group(1)))
        elif m := _PROP_DEFAULT_FILTER.match(line):
            default_filters.append((i, m.group(1)))
        elif m := _PROP_ROUTE_FILTER.match(line):
            route_filters.append((i, m.group(1)))
        elif _PROP_ZUUL_ROUTE.match(line):
            zuul.append(i)
    strong = []
    if uris:
        targets = ", ".join(u for _, u in uris)
        strong.append(f"gateway routes at {where}:{uris[0][0]}-{uris[-1][0]} -> {targets}")
    if zuul:
        strong.append(f"zuul routes at {where}:{zuul[0]}-{zuul[-1]}")
    filters = _prop_lines(default_filters, "default filters", where)
    filters += _prop_lines(route_filters, "route filters", where)
    return strong, filters


def _block_end(text: str, open_brace: int) -> int:
    """Index just past the `}` matching the `{` at `open_brace`, skipping strings and comments."""
    depth, i = 0, open_brace
    while i < len(text):
        c = text[i]
        if text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                return len(text)
        elif text.startswith("/*", i):
            i = text.find("*/", i)
            if i < 0:
                return len(text)
            i += 1
        elif c in "\"'":
            i += 1
            while i < len(text) and text[i] != c:
                i += 2 if text[i] == "\\" else 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def java_route_signals(text: str, where: str) -> list[str]:
    """Strong signals in one Java file: @Bean RouteLocator methods that define routes.

    The method must use RouteLocatorBuilder and call `.routes()`, `.route(` and `.uri(`.
    """
    found = []
    for m in _ROUTE_LOCATOR_BEAN.finditer(text):
        brace = text.find("{", m.end())
        if brace < 0:
            continue
        method = text[m.start() : _block_end(text, brace)]
        if "RouteLocatorBuilder" not in method or not all(
            p.search(method) for p in _ROUTE_DSL_CALLS
        ):
            continue
        first = text.count("\n", 0, m.start()) + 1
        last = first + method.count("\n")
        uris = _ROUTE_DSL_URI.findall(method)
        target = f" -> {', '.join(uris)}" if uris else ""
        found.append(f"gateway routes (Java RouteLocator bean) at {where}:{first}-{last}{target}")
    return found


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def collect(repo: Path, service: Service, known: set[str]) -> Evidence:
    """Gather every signal for one service. `known` is every service name from the scanner."""
    ev = Evidence(name_words=name_words(service.name))
    folder = repo / service.root
    for rel in service.files["config"]:
        text = _read(folder / rel)
        if rel.endswith(".properties"):
            strong, filters = properties_signals(text, rel)
        else:
            strong, filters = yaml_signals(text, rel)
        ev.strong += strong
        ev.filters += filters
    for rel in service.files["build"]:
        for i, line in enumerate(_read(folder / rel).splitlines(), start=1):
            if m := _DEPENDENCY.search(line):
                ev.dependency.append(f"gateway dependency {m.group(1)} at {rel}:{i}")
    for rel in service.files["java"]:
        text = _read(folder / rel)
        ev.strong += java_route_signals(text, rel)
        for i, line in enumerate(text.splitlines(), start=1):
            if _ZUUL_ANNOTATION.search(line):
                ev.strong.append(f"@EnableZuulProxy at {rel}:{i}")
            for pattern in _CALL_TARGETS:
                for target in pattern.findall(line):
                    if target in known and target != service.name:
                        ev.calls.setdefault(target, f"{rel}:{i}")
    return ev


# ------------------------------------------------------------------- output


def _snippet(service: str, ev: Evidence) -> str:
    lines = [f"gateway candidate: service {service}"]
    lines += [f"strong: {s}" for s in ev.strong]
    lines += [f"weak: {d}" for d in ev.dependency]
    if ev.name_words:
        lines.append(f"weak: service name word(s): {', '.join(ev.name_words)}")
    lines += [f"supporting: {f}" for f in ev.filters]
    if ev.calls:
        targets = ", ".join(f"{t} ({w})" for t, w in sorted(ev.calls.items()))
        lines.append(f"supporting: calls {len(ev.calls)} other services: {targets}")
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
    """Run the rule over a checkout and return validated service-unit candidates.

    `repo_name` defaults to the checkout's folder name and `commit` to its HEAD (both via
    the scanner). Pass `inventory` to reuse a scan; otherwise the repo is scanned here.
    """
    repo = Path(repo).resolve()
    inv = inventory or scan(repo, repo_name, commit)
    known = {s.name for s in inv.services}
    candidates = []
    for service in inv.services:
        ev = collect(repo, service, known)
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
