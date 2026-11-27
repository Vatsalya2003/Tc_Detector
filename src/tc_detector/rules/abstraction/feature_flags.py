"""Feature-flag detection. Owner: Karan (D).

Pattern `feature-flags`, category `configurability`, matching unit `line_range`.
One candidate per flag *check*: the annotation, or the `if` line with its condition.
The property line in YAML is never a candidate. See ground_truth/GUIDELINES.md,
section `feature-flags`.

Signals (each one is a candidate on its own):

  A  conditional bean  `@ConditionalOnProperty` in the service's src/main/java, unless
                       every key it names is under a framework prefix (FRAMEWORK_PREFIXES).
                       Range: the annotation, from `@` to its closing `)`.
  B  @Value boolean    an `if` whose condition uses a `boolean`/`Boolean` field annotated
                       `@Value("${key}")` in the same file, key not under a framework
                       prefix. Range: `if` to the `)` closing its condition.
  C  flag library      an `if` whose condition calls a feature-flag library:
                         fires without a dependency (library-specific calls):
                           LaunchDarkly `x.boolVariation(`, FF4J `ff4j.check(`,
                           Togglz `Features.X.isActive()`, OpenFeature `x.getBooleanValue(`
                         needs a flag-library dependency in this service's build file
                         (generic names that other APIs use too):
                           `x.isEnabled(arg)` (Unleash), `x.isFeatureEnabled(` (Flagsmith),
                           `x.isActive(arg)` (Togglz FeatureManager), `x.check(` (FF4J only)
                       Range: `if` to the `)` closing its condition.

Supporting evidence, only added to a candidate's snippet, never a candidate itself:

  D  dependency        Togglz, FF4J, Unleash, LaunchDarkly, OpenFeature or Flagsmith in the
                       service's build file. The unit is the check, not the dependency.

Not signals (guideline negatives and edge cases): `@Profile`, `spring.profiles.active`,
framework switches such as `spring.ai.chat.client.enabled`, any property line in YAML or
.properties, and non-boolean settings like timeouts or URLs.

Comments are ignored; line numbers are kept. Services, their Java files and build files
come from the scanner.

Run by hand (prints one candidate JSON per line). Development set only:
    uv run python -m tc_detector.rules.abstraction.feature_flags \\
        targets/spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.contracts.ids import SNIPPET_MAX_CHARS
from tc_detector.scanner import scan
from tc_detector.scanner.inventory import Inventory, Service

PATTERN = "feature-flags"
CATEGORY = Category.CONFIGURABILITY
RULE_ID = "configurability-feature-flags-01"

# Property keys that belong to Spring Boot / Spring Cloud (and the libraries they wire in),
# not to the app. A switch under one of these turns framework behaviour on or off, like the
# guideline's `spring.ai.chat.client.enabled` negative, so it is not an app feature flag.
# A key matches when it equals a prefix or starts with "<prefix>.".
FRAMEWORK_PREFIXES = (
    "spring",  # spring.*: Boot, Cloud, Data, AI, profiles, ...
    "management",  # Actuator
    "server",  # embedded web server
    "eureka",  # Netflix Eureka (Spring Cloud)
    "logging",  # Boot logging
    "info",  # Actuator /info
    "endpoints",  # Boot 1.x Actuator endpoints
    "feign",  # OpenFeign (Spring Cloud)
    "ribbon",  # Netflix Ribbon (Spring Cloud)
    "hystrix",  # Netflix Hystrix (Spring Cloud)
    "zuul",  # Netflix Zuul (Spring Cloud)
    "resilience4j",  # Resilience4j (Spring Cloud Circuit Breaker)
    "springdoc",  # springdoc-openapi
    "debug",  # Boot's top-level debug switch
    "trace",  # Boot's top-level trace switch
)

# Flag libraries, as they appear in a build file (artifactId or groupId).
FLAG_LIBRARIES = {
    "Togglz": re.compile(r"\btogglz[\w.-]*", re.IGNORECASE),
    "FF4J": re.compile(r"\bff4j[\w.-]*", re.IGNORECASE),
    "Unleash": re.compile(r"\bunleash[\w.-]*|\bio\.getunleash\b", re.IGNORECASE),
    "LaunchDarkly": re.compile(r"\blaunchdarkly[\w.-]*", re.IGNORECASE),
    "OpenFeature": re.compile(r"\bdev\.openfeature\b|\bopenfeature[\w.-]*", re.IGNORECASE),
    "Flagsmith": re.compile(r"\bflagsmith[\w.-]*", re.IGNORECASE),
}

# Calls only a flag library makes: they count with or without a dependency.
SPECIFIC_CALLS = {
    "LaunchDarkly boolVariation": re.compile(r"\.\s*boolVariation\s*\("),
    # `ff4j.check(`, `this.ff4j.check(`, `getFf4j().check(`
    "FF4J check": re.compile(r"\b\w*ff4j\w*(?:\(\s*\))?\s*\.\s*check\s*\(", re.IGNORECASE),
    "Togglz Feature.isActive()": re.compile(r"\b[A-Z][A-Z0-9_]*\s*\.\s*isActive\s*\(\s*\)"),
    "OpenFeature getBooleanValue": re.compile(r"\.\s*getBooleanValue\s*\("),
}

# Calls with names other APIs use too: they count only with a flag-library dependency.
# The value is the library the call needs, or None for any flag library.
GENERIC_CALLS = {
    "isEnabled(...)": (re.compile(r"\.\s*isEnabled\s*\(\s*[^)\s]"), None),
    "isFeatureEnabled(...)": (re.compile(r"\.\s*isFeatureEnabled\s*\("), None),
    "isActive(...)": (re.compile(r"\.\s*isActive\s*\(\s*[^)\s]"), "Togglz"),
    "check(...)": (re.compile(r"\.\s*check\s*\("), "FF4J"),
}

_CONDITIONAL = re.compile(r"@(?:[\w.]+\.)?ConditionalOnProperty\b\s*(\()?")
_IF = re.compile(r"\bif\s*\(")
_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
_PREFIX_ARG = re.compile(r'\bprefix\s*=\s*"((?:[^"\\]|\\.)*)"')
_NAME_ARG = re.compile(r'\b(?:name|value)\s*=\s*(\{[^}]*\}|"(?:[^"\\]|\\.)*")')
_VALUE_BOOLEAN_FIELD = re.compile(
    r'@(?:[\w.]+\.)?Value\s*\(\s*"\$\{([^}:]+)(?::[^}]*)?\}"\s*\)'  # @Value("${key:default}")
    r"(?:\s*@[\w.]+(?:\([^)]*\))?)*"  # other annotations
    r"(?:\s*\b(?:private|protected|public|static|final|volatile|transient)\b)*"
    r"\s*\b(?:boolean|Boolean|java\.lang\.Boolean)\s+(\w+)\s*[;=]"
)
_TRUNCATED = "\n[... truncated]"
_MAX_SOURCE_LINES = 6


@dataclass
class Check:
    """One flag check in one file: its lines and the evidence for it."""

    file: str
    line_start: int
    line_end: int
    signals: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ java text


def strip_comments(text: str) -> str:
    """Blank out // and /* */ comments, keeping strings, line numbers and offsets."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            out[i:end] = " " * (end - i)
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out[i:end] = [c if c == "\n" else " " for c in text[i:end]]
            i = end
        elif text[i] in "\"'":
            quote = text[i]
            i += 1
            while i < n and text[i] != quote and text[i] != "\n":
                i += 2 if text[i] == "\\" else 1
            i += 1
        else:
            i += 1
    return "".join(out)


def blank_strings(code: str) -> str:
    """Blank the inside of string and char literals, so text in them can't look like code.

    Same length and line breaks as `code`, so an index found here points at the same
    place in `code`, where the literal (e.g. a property key) can still be read.
    """
    out = list(code)
    i, n = 0, len(code)
    while i < n:
        if code[i] in "\"'":
            quote, i = code[i], i + 1
            while i < n and code[i] != quote and code[i] != "\n":
                step = 2 if code[i] == "\\" else 1
                out[i : i + step] = " " * len(out[i : i + step])
                i += step
        i += 1
    return "".join(out)


def close_paren(text: str, open_index: int) -> int:
    """Index of the `)` matching the `(` at `open_index` (strings skipped); -1 if none."""
    depth, i = 0, open_index
    while i < len(text):
        c = text[i]
        if c in "\"'":
            i += 1
            while i < len(text) and text[i] != c:
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def is_framework_key(key: str) -> bool:
    key = key.strip()
    return any(key == p or key.startswith(p + ".") for p in FRAMEWORK_PREFIXES)


def conditional_keys(args: str) -> list[str]:
    """Property keys named by a @ConditionalOnProperty's arguments ([] if not literals)."""
    prefix_match = _PREFIX_ARG.search(args)
    prefix = prefix_match.group(1).strip(".") if prefix_match else ""
    names: list[str] = []
    for m in _NAME_ARG.finditer(args):
        names += _STRING.findall(m.group(1))
    positional = args.strip()
    if not names and positional.startswith('"'):  # @ConditionalOnProperty("x")
        names = _STRING.findall(positional)[:1]
    elif not names and positional.startswith("{"):  # @ConditionalOnProperty({"x", "y"})
        names = _STRING.findall(positional[: positional.find("}") + 1])
    if not names:
        return [prefix] if prefix else []
    return [f"{prefix}.{n}" if prefix else n for n in names]


# ------------------------------------------------------------------ signals


def conditional_signals(code: str, where: str) -> list[Check]:
    """Signal A: @ConditionalOnProperty not on framework keys."""
    found = []
    for m in _CONDITIONAL.finditer(blank_strings(code)):
        end = m.end()
        args = ""
        if m.group(1):
            close = close_paren(code, m.end() - 1)
            if close < 0:
                continue
            args, end = code[m.end() : close], close + 1
        keys = conditional_keys(args)
        if keys and all(is_framework_key(k) for k in keys):
            continue
        shown = ", ".join(keys) if keys else "key not a string literal"
        found.append(
            Check(
                where,
                _line(code, m.start()),
                _line(code, end - 1),
                [f"@ConditionalOnProperty on {shown}"],
            )
        )
    return found


def _if_conditions(code: str) -> list[tuple[int, int, str]]:
    """(start index, end index, condition text) of every `if (...)`."""
    out = []
    for m in _IF.finditer(blank_strings(code)):
        close = close_paren(code, m.end() - 1)
        if close > 0:
            out.append((m.start(), close + 1, code[m.end() : close]))
    return out


def value_boolean_fields(code: str) -> dict[str, str]:
    """field name -> property key, for @Value boolean fields not on framework keys."""
    blank = blank_strings(code)  # the key is read from `code`; the `@` must be real code
    return {
        m.group(2): m.group(1).strip()
        for m in _VALUE_BOOLEAN_FIELD.finditer(code)
        if blank[m.start()] == "@" and not is_framework_key(m.group(1))
    }


def library_calls(condition: str, libraries: set[str]) -> list[str]:
    """Names of the flag-library calls in one `if` condition."""
    found = [name for name, p in SPECIFIC_CALLS.items() if p.search(condition)]
    for name, (p, needs) in GENERIC_CALLS.items():
        has_dependency = bool(libraries) if needs is None else needs in libraries
        already_specific = name == "check(...)" and "FF4J check" in found
        if p.search(condition) and has_dependency and not already_specific:
            found.append(name)
    return found


def if_signals(code: str, where: str, libraries: set[str]) -> list[Check]:
    """Signals B and C: `if` conditions on a @Value boolean or a flag-library call."""
    fields_ = value_boolean_fields(code)
    found = []
    for start, end, condition in _if_conditions(code):
        signals = [
            f"if on @Value boolean {name} (${{{key}}})"
            for name, key in fields_.items()
            if re.search(rf"\b{re.escape(name)}\b", condition)
        ]
        calls = library_calls(condition, libraries)
        signals += [f"if on flag library call {call}" for call in calls]
        if signals:
            found.append(Check(where, _line(code, start), _line(code, end - 1), signals))
    return found


def dependencies(build_text: str, where: str) -> dict[str, str]:
    """Signal D: flag library -> where its first mention is in one build file."""
    found: dict[str, str] = {}
    for i, line in enumerate(build_text.splitlines(), start=1):
        for library, p in FLAG_LIBRARIES.items():
            if library not in found and p.search(line):
                found[library] = f"{where}:{i}"
    return found


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def collect(repo: Path, service: Service) -> tuple[list[Check], dict[str, str]]:
    """Every flag check in one service, plus its flag-library dependencies."""
    folder = repo / service.root
    deps: dict[str, str] = {}
    for rel in service.files["build"]:
        deps.update(dependencies(_read(folder / rel), rel))
    checks: dict[tuple[str, int, int], Check] = {}
    for rel in service.files["java"]:
        code = strip_comments(_read(folder / rel))
        for check in conditional_signals(code, rel) + if_signals(code, rel, set(deps)):
            key = (check.file, check.line_start, check.line_end)
            if key in checks:
                checks[key].signals += check.signals
            else:
                checks[key] = check
    return sorted(checks.values(), key=lambda c: (c.file, c.line_start)), deps


# ------------------------------------------------------------------- output


def _snippet(service: str, check: Check, source: list[str], deps: dict[str, str]) -> str:
    lines = [
        f"{PATTERN} candidate: service {service}, {check.file}:{check.line_start}-{check.line_end}"
    ]
    lines += [f"signal: {s}" for s in check.signals]
    code = source[check.line_start - 1 : check.line_end]
    if len(code) > _MAX_SOURCE_LINES:
        code = code[:_MAX_SOURCE_LINES] + ["..."]
    lines += [f"code: {c.strip()}" for c in code]
    lines += [f"supporting: {lib} dependency at {where}" for lib, where in sorted(deps.items())]
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
    """Line-range candidates for every feature-flag check.

    Pass `inventory` to reuse a scan; otherwise the repo is scanned here.
    """
    repo = Path(repo).resolve()
    inv = inventory or scan(repo, repo_name, commit)
    candidates = []
    for service in inv.services:
        checks, deps = collect(repo, service)
        for check in checks:
            source = _read(repo / service.root / check.file).splitlines()
            candidates.append(
                Candidate.create(
                    repo=inv.repo,
                    commit=inv.commit,
                    service=service.name,
                    file=check.file,
                    line_start=check.line_start,
                    line_end=check.line_end,
                    unit=Unit.LINE_RANGE,
                    pattern=PATTERN,
                    category=CATEGORY,
                    rule_id=RULE_ID,
                    snippet=_snippet(service.name, check, source, deps),
                )
            )
    return candidates


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tc_detector.rules.abstraction.feature_flags")
    p.add_argument("repo_path", type=Path)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    args = p.parse_args(argv)
    for candidate in detect(args.repo_path, args.repo_name, args.commit):
        print(candidate.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
