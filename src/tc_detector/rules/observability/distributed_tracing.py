"""distributed-tracing detection. Owner: Vatsalya (A).

Pattern `distributed-tracing`, category `observability`, matching unit `service`
(`file`, `line_start`, `line_end` None). One candidate per service with any signal.
See ground_truth/GUIDELINES.md, `distributed-tracing`.

Signals (either one is enough; a dependency alone counts):
  dependency  the service's build file depends on spring-boot-starter-zipkin,
              micrometer-tracing-bridge-*, or an OpenTelemetry artifact (any artifactId
              containing "opentelemetry"). Maven: an <artifactId>, not inside
              <dependencyManagement> or <exclusions>. Gradle: a "group:artifact" string.
              A BOM (artifactId ending in -bom) only pins versions, so it never counts.
  code        @Observed or @NewSpan, or a manual span `nextSpan(` (tracer.nextSpan()),
              in the service's src/main/java. Comments and strings are ignored.

Doesn't count (GUIDELINES edge cases):
  - micrometer-registry-prometheus: metrics, not tracing;
  - reactor context-propagation (the dependency or `reactor.context-propagation: auto`);
  - the Zipkin server in the root docker-compose.yml: outside any service, and the
    scanner puts it in repo_files, which this rule never reads.

Known gaps (not in GUIDELINES yet; add them there first):
  - Spring Cloud Sleuth (spring-cloud-starter-sleuth), the pre-Boot-3 tracer;
  - OpenTelemetry manual spans written as tracer.spanBuilder(...);
  - Gradle version catalogs (libs.xxx): only literal "group:artifact" strings are read.

Run by hand (prints one candidate JSON per line):
    uv run python -m tc_detector.rules.observability.distributed_tracing \\
        ../spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.rules.observability.common import (
    blank,
    files,
    java_code,
    line_at,
    load,
    trim_snippet,
    xml_code,
)
from tc_detector.scanner import Inventory, Service

PATTERN = "distributed-tracing"
CATEGORY = Category.OBSERVABILITY
RULE_ID = "observability-distributed-tracing-01"

_TRACING_ARTIFACT = re.compile(
    r"spring-boot-starter-zipkin|micrometer-tracing-bridge-[\w.-]+|[\w.-]*opentelemetry[\w.-]*"
)
_NOT_USED = re.compile(r"<(dependencyManagement|exclusions)>.*?</\1>", re.DOTALL)
_POM_ARTIFACT = re.compile(r"<artifactId>\s*([\w.-]+)\s*</artifactId>")
_GRADLE_COORDINATE = re.compile(r"[\"'][\w.-]+:([\w.-]+)(?::[^\"'\n]*)?[\"']")
_ANNOTATION = re.compile(r"@(?:[\w.]+\.)?(Observed|NewSpan)\b")
_NEXT_SPAN = re.compile(r"\bnextSpan\s*\(")


def build_signals(rel: str, text: str) -> list[str]:
    """Tracing dependencies in one build file (pom.xml or build.gradle[.kts])."""
    if rel.endswith(".xml"):
        code = blank(_NOT_USED, xml_code(text))
        found = [(m.start(1), m.group(1)) for m in _POM_ARTIFACT.finditer(code)]
    else:  # Gradle: comments removed, strings kept (the coordinates are strings)
        code = java_code(text, keep_strings=True)
        found = [(m.start(1), m.group(1)) for m in _GRADLE_COORDINATE.finditer(code)]
    return [
        f"dependency {artifact} ({rel}:{line_at(code, i)})"
        for i, artifact in found
        if _TRACING_ARTIFACT.fullmatch(artifact) and not artifact.endswith("-bom")
    ]


def code_signals(rel: str, text: str) -> list[str]:
    """Tracing annotations and manual spans in one Java file."""
    code = java_code(text, keep_strings=False)
    found = [(m.start(), f"@{m.group(1)}") for m in _ANNOTATION.finditer(code)]
    found += [(m.start(), "manual span nextSpan()") for m in _NEXT_SPAN.finditer(code)]
    return [f"{what} ({rel}:{line_at(code, i)})" for i, what in sorted(found)]


def service_signals(repo: Path, service: Service) -> list[str]:
    signals = []
    for rel, text in files(repo, service, "build"):
        signals += build_signals(rel, text)
    for rel, text in files(repo, service, "java"):
        signals += code_signals(rel, text)
    return signals


def detect(
    repo: Path | str,
    repo_name: str | None = None,
    commit: str | None = None,
    inventory: Inventory | None = None,
) -> list[Candidate]:
    """Service-unit candidates for every service with a tracing signal.

    Pass `inventory` to reuse a scan; otherwise the repo is scanned here.
    """
    repo, inv = load(repo, repo_name, commit, inventory)
    candidates = []
    for service in inv.services:
        signals = service_signals(repo, service)
        if not signals:
            continue
        lines = [f"{PATTERN} candidate: service {service.name}"]
        lines += [f"signal: {s}" for s in signals]
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
                snippet=trim_snippet(lines),
            )
        )
    return candidates


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m tc_detector.rules.observability.distributed_tracing"
    )
    p.add_argument("repo_path", type=Path)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    args = p.parse_args(argv)
    for candidate in detect(args.repo_path, args.repo_name, args.commit):
        print(candidate.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
