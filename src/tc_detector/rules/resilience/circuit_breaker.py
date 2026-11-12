"""S11: circuit breaker and retry detection. Owner: Neil (C).

Pattern `circuit-breaker`, spec category `automation`, matching unit `line_range`.

What counts as one candidate (one unit):

- Java: the method (or constructor / field / class) that declares or uses a
  resilience construct. Several uses inside one method are one candidate.
- YAML: one Spring Cloud Gateway filter list containing CircuitBreaker/Retry
  filters; one child block of `resilience4j:` (circuitbreaker, retry, ...); one
  top-level `hystrix:` block; one Istio `retries` / `outlierDetection` block.
- .properties: one contiguous run of `resilience4j.*` / `hystrix.*` lines.

Deliberately not detected:

- Dependencies in pom.xml / build.gradle. A library on the classpath is not a
  decision anyone made about a call path; the use sites are.
- Test code (excluded by the file walker).
- Java files that don't import a resilience library. The annotation names
  (`@Retry`, `@CircuitBreaker`) are too generic to trust without an import.

Rule ids:
  automation-cb-annotation-01   resilience annotation on a method or class
  automation-cb-programmatic-01 calls on circuit breaker / retry objects, gateway DSL
  automation-cb-config-java-01  resilience config built in Java (CircuitBreakerConfig, ...)
  automation-cb-config-yaml-01  gateway filters and resilience4j / hystrix / feign blocks
  automation-cb-mesh-yaml-01    service mesh retries / outlier detection
  automation-cb-properties-01   resilience4j.* / hystrix.* properties
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tree_sitter_java as tsjava
import yaml
from tree_sitter import Language, Node, Parser

from tc_detector.contracts.candidate import Candidate, Category
from tc_detector.rules.resilience.common import (
    Hit,
    ServiceNamer,
    head_commit,
    iter_files,
    make_candidate,
    merge_hits,
)

PATTERN = "circuit-breaker"
CATEGORY = Category.AUTOMATION

RESILIENCE_IMPORTS = (
    "io.github.resilience4j",
    "com.netflix.hystrix",
    "org.springframework.retry",
    "org.springframework.cloud.client.circuitbreaker",
    "org.springframework.cloud.circuitbreaker",
    "org.eclipse.microprofile.faulttolerance",
    "io.smallrye.faulttolerance",
    "dev.failsafe",
    "net.jodah.failsafe",
)
GATEWAY_IMPORT = "org.springframework.cloud.gateway"

ANNOTATIONS = {
    "CircuitBreaker",
    "Retry",
    "Bulkhead",
    "TimeLimiter",
    "RateLimiter",  # resilience4j
    "HystrixCommand",  # Hystrix
    "Retryable",  # Spring Retry
    "Fallback",  # MicroProfile Fault Tolerance (with CircuitBreaker / Retry from the same import)
}
RUNTIME_TYPES = {
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitBreakerFactory",
    "ReactiveCircuitBreakerFactory",
    "ReactiveCircuitBreaker",
    "Retry",
    "RetryRegistry",
    "RetryTemplate",
    "Bulkhead",
    "BulkheadRegistry",
    "TimeLimiter",
    "TimeLimiterRegistry",
    "Decorators",
    "Failsafe",
    "RetryPolicy",
}
CONFIG_TYPES = {
    "CircuitBreakerConfig",
    "RetryConfig",
    "BulkheadConfig",
    "TimeLimiterConfig",
    "Resilience4JConfigBuilder",
    "RetryTemplateBuilder",
}
GATEWAY_DSL_METHODS = {"circuitBreaker", "retry"}
GATEWAY_FILTER_NAMES = {"CircuitBreaker", "Retry", "Hystrix"}
RESILIENCE4J_MODULES = {
    "circuitbreaker",
    "retry",
    "bulkhead",
    "thread-pool-bulkhead",
    "timelimiter",
    "ratelimiter",
}

_PRIORITY = {
    "automation-cb-annotation-01": 0,
    "automation-cb-programmatic-01": 1,
    "automation-cb-config-java-01": 2,
}
_ENCLOSING = ("method_declaration", "constructor_declaration", "field_declaration")
_TYPE_DECLS = (
    "class_declaration",
    "interface_declaration",
    "record_declaration",
    "enum_declaration",
)

_parser = Parser(Language(tsjava.language()))


# --------------------------------------------------------------------------- Java


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _simple_type(type_text: str) -> str:
    """`Map<String, Retry>` -> `Map`; `io.x.CircuitBreaker` -> `CircuitBreaker`."""
    return type_text.split("<", 1)[0].strip().split(".")[-1]


def _walk(node: Node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _imports(root: Node) -> list[str]:
    out = []
    for n in root.children:
        if n.type == "import_declaration":
            out.append(_text(n).removeprefix("import").removeprefix(" static").strip(" ;"))
    return out


def _enclosing(node: Node) -> Node:
    n = node.parent
    while n is not None:
        if n.type in _ENCLOSING:
            return n
        n = n.parent
    return node


def _annotation_name(node: Node) -> str:
    return _simple_type(_text(node.child_by_field_name("name")))


def detect_java(source: bytes) -> list[Hit]:
    tree = _parser.parse(source)
    root = tree.root_node
    imports = _imports(root)
    has_resilience = any(i.startswith(RESILIENCE_IMPORTS) for i in imports)
    has_gateway = any(i.startswith(GATEWAY_IMPORT) for i in imports)
    if not (has_resilience or has_gateway):
        return []

    # Identifiers declared with a resilience type (fields, locals, parameters).
    typed_vars: set[str] = set()
    if has_resilience:
        for n in _walk(root):
            if n.type in ("field_declaration", "local_variable_declaration", "formal_parameter"):
                if _simple_type(_text(n.child_by_field_name("type"))) not in RUNTIME_TYPES:
                    continue
                if n.type == "formal_parameter":
                    typed_vars.add(_text(n.child_by_field_name("name")))
                else:
                    for d in n.children_by_field_name("declarator"):
                        typed_vars.add(_text(d.child_by_field_name("name")))

    hits: dict[tuple[int, int], str] = {}

    def add(region: Node, rule_id: str) -> None:
        key = (region.start_point[0] + 1, region.end_point[0] + 1)
        if key not in hits or _PRIORITY[rule_id] < _PRIORITY[hits[key]]:
            hits[key] = rule_id

    for n in _walk(root):
        if has_resilience and n.type in ("marker_annotation", "annotation"):
            if _annotation_name(n) in ANNOTATIONS:
                modifiers = n.parent
                target = modifiers.parent if modifiers is not None else None
                if target is not None and (target.type in _ENCLOSING or target.type in _TYPE_DECLS):
                    add(target, "automation-cb-annotation-01")

        elif n.type == "method_invocation":
            obj = n.child_by_field_name("object")
            name = _text(n.child_by_field_name("name"))
            obj_name = _text(obj) if obj is not None and obj.type == "identifier" else ""
            if has_resilience and (obj_name in typed_vars or obj_name in RUNTIME_TYPES):
                add(_enclosing(n), "automation-cb-programmatic-01")
            elif has_resilience and obj_name in CONFIG_TYPES:
                add(_enclosing(n), "automation-cb-config-java-01")
            elif has_gateway and name in GATEWAY_DSL_METHODS and obj is not None:
                add(_enclosing(n), "automation-cb-programmatic-01")

        elif has_resilience and n.type == "object_creation_expression":
            ctype = _simple_type(_text(n.child_by_field_name("type")))
            if ctype in CONFIG_TYPES:
                add(_enclosing(n), "automation-cb-config-java-01")
            elif ctype in RUNTIME_TYPES:
                add(_enclosing(n), "automation-cb-programmatic-01")

    # Overlapping regions (e.g. an annotated class and the methods inside it)
    # become one candidate, so one-to-one matching doesn't see duplicates.
    return merge_hits([Hit(s, e, r) for (s, e), r in hits.items()])


# --------------------------------------------------------------------------- YAML


def _key(node: Any) -> str:
    return node.value if isinstance(node, yaml.ScalarNode) else ""


def _last_line(node: Any) -> int:
    """Last 1-indexed line holding content of `node` (not the blank after it)."""
    if isinstance(node, yaml.MappingNode):
        return max([_last_line(v) for _, v in node.value] + [node.start_mark.line + 1])
    if isinstance(node, yaml.SequenceNode):
        return max([_last_line(v) for v in node.value] + [node.start_mark.line + 1])
    end = node.end_mark
    if end.column == 0 and end.line > node.start_mark.line:
        return end.line
    return end.line + 1


def _filter_name(item: Any) -> str:
    if isinstance(item, yaml.ScalarNode):
        return str(item.value).split("=", 1)[0].strip()
    if isinstance(item, yaml.MappingNode):
        for k, v in item.value:
            if _key(k) == "name":
                return str(v.value) if isinstance(v, yaml.ScalarNode) else ""
    return ""


def _is_true(node: Any) -> bool:
    return isinstance(node, yaml.ScalarNode) and str(node.value).lower() == "true"


def detect_yaml(text: str) -> list[Hit]:
    try:
        docs = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    hits: list[Hit] = []

    def visit(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, yaml.SequenceNode):
            if path and path[-1] in ("filters", "default-filters"):
                items = [i for i in node.value if _filter_name(i) in GATEWAY_FILTER_NAMES]
                if items:
                    hits.append(
                        Hit(
                            items[0].start_mark.line + 1,
                            max(_last_line(i) for i in items),
                            "automation-cb-config-yaml-01",
                        )
                    )
            for item in node.value:
                visit(item, path)
            return
        if not isinstance(node, yaml.MappingNode):
            return
        for k, v in node.value:
            key = _key(k)
            start = k.start_mark.line + 1
            first = key.split(".", 1)[0]
            if first == "resilience4j":
                rest = key.split(".")[1:]
                if rest:  # dotted key such as `resilience4j.circuitbreaker:`
                    hits.append(Hit(start, _last_line(v), "automation-cb-config-yaml-01"))
                elif isinstance(v, yaml.MappingNode):
                    for mk, mv in v.value:
                        if _key(mk) in RESILIENCE4J_MODULES:
                            hits.append(
                                Hit(
                                    mk.start_mark.line + 1,
                                    _last_line(mv),
                                    "automation-cb-config-yaml-01",
                                )
                            )
                continue
            if first == "hystrix" and not path:
                hits.append(Hit(start, _last_line(v), "automation-cb-config-yaml-01"))
                continue
            if key == "outlierDetection" or (
                key == "retries"
                and isinstance(v, yaml.MappingNode)
                and any(_key(rk) == "attempts" for rk, _ in v.value)
            ):
                hits.append(Hit(start, _last_line(v), "automation-cb-mesh-yaml-01"))
                continue
            full = (*path, *key.split("."))
            if (
                full[-2:] == ("circuitbreaker", "enabled")
                and _is_true(v)
                and ({"feign", "openfeign"} & set(full))
            ):
                hits.append(Hit(start, start, "automation-cb-config-yaml-01"))
                continue
            visit(v, full)

    for doc in docs:
        if doc is not None:
            visit(doc, ())
    return merge_hits(hits)


# --------------------------------------------------------------------- properties

_PROP_LINE = re.compile(
    r"^\s*(?:resilience4j\.(?:" + "|".join(sorted(RESILIENCE4J_MODULES)) + r")\.|hystrix\.)"
    r"|^\s*spring\.cloud\.gateway\.\S*filters\[\d+\]\s*[=:]\s*(?:CircuitBreaker|Retry)\b"
)


def detect_properties(text: str) -> list[Hit]:
    hits: list[Hit] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if _PROP_LINE.match(line):
            hits.append(Hit(i, i, "automation-cb-properties-01"))
    return merge_hits(hits)


# -------------------------------------------------------------------------- entry


def detect(
    repo: Path | str,
    repo_name: str | None = None,
    commit: str | None = None,
) -> list[Candidate]:
    """Run the rule over a checkout and return validated candidates.

    `repo_name` defaults to the checkout's folder name, which is the `name` in
    targets.yaml (e.g. `spring-petclinic-microservices`), as the label format proposes.
    """
    repo = Path(repo).resolve()
    repo_name = repo_name or repo.name
    commit = commit or head_commit(repo)
    service_of = ServiceNamer(repo)
    candidates: list[Candidate] = []

    for path in iter_files(repo, (".java", ".yml", ".yaml", ".properties")):
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        if path.suffix == ".java":
            hits = detect_java(raw)
        elif path.suffix in (".yml", ".yaml"):
            hits = detect_yaml(text)
        else:
            hits = detect_properties(text)
        if not hits:
            continue
        lines = text.splitlines()
        for hit in hits:
            candidates.append(
                make_candidate(
                    path=path,
                    service_root=service_of.root(path),
                    hit=hit,
                    lines=lines,
                    repo_name=repo_name,
                    commit=commit,
                    service=service_of(path),
                    pattern=PATTERN,
                    category=CATEGORY,
                )
            )
    return candidates
