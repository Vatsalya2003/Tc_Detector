"""structured-logging detection (correlation-ID logging). Owner: Vatsalya (A).

Pattern `structured-logging`, category `observability`, matching unit `file`
(`line_start`, `line_end` None). One candidate per file that sets up a correlation ID.
See ground_truth/GUIDELINES.md, `structured-logging`.

An "ID" below is traceId or correlationId in any case, with or without - or _
(trace_id, X-Correlation-Id, TRACE_ID).

Signals (only explicit correlation-ID setup counts):
  MDC.put      Java: MDC.put(KEY, ...) or MDC.putCloseable(KEY, ...) where KEY is a string
               or a constant whose name holds an ID ("correlationId", TRACE_ID).
  log pattern  logging files (logback*.xml, log4j2*): an ID inside a <pattern>, a
               pattern="..." attribute, a <property name="...PATTERN..." value="...">,
               or a `...pattern = ...` / `...pattern: ...` line.
               config files (application*/bootstrap*): an ID in a logging.pattern.* value.

Doesn't count (GUIDELINES negatives and edge cases):
  - plain log statements (log.info("owner " + id)): no MDC.put, no pattern;
  - a default logback-spring.xml that only includes Spring's base.xml;
  - logging.level.* settings, and JSON encoders with no ID in a pattern;
  - an ID that appears only in a comment.

Known gaps (not in GUIDELINES yet; add them there first):
  - log4j2's ThreadContext.put (the log4j2 counterpart of MDC.put).

Run by hand (prints one candidate JSON per line):
    uv run python -m tc_detector.rules.observability.structured_logging \\
        ../spring-petclinic-microservices
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.rules.observability.common import files, java_code, line_at, load, trim_snippet
from tc_detector.rules.observability.logging_config import (
    ID,
    config_signals,
    logging_file_signals,
)
from tc_detector.scanner import Inventory

PATTERN = "structured-logging"
CATEGORY = Category.OBSERVABILITY
RULE_ID = "observability-structured-logging-01"
CONTEXT = 2  # source lines shown above and below each signal

_MDC_PUT = re.compile(r"\bMDC\s*\.\s*put(?:Closeable)?\s*\(\s*(\"(?:\\.|[^\"\\])*\"|[\w.]+)")


def java_signals(rel: str, text: str) -> list[tuple[int, str]]:
    code = java_code(text, keep_strings=True)
    return [
        (line_at(code, m.start()), f"MDC.put of {m.group(1)}")
        for m in _MDC_PUT.finditer(code)
        if ID.search(m.group(1))
    ]


def _snippet(service: str, rel: str, text: str, signals: list[tuple[int, str]]) -> str:
    lines = [f"{PATTERN} candidate: service {service}, file {rel}"]
    lines += [f"signal: {what} (line {line})" for line, what in signals]
    lines.append("source:")
    source = text.split("\n")
    shown_to = 0  # last source line already printed, so overlapping windows print once
    for line, _ in signals:
        start, end = max(line - CONTEXT, shown_to + 1, 1), min(line + CONTEXT, len(source))
        if start > end:
            continue
        if shown_to and start > shown_to + 1:
            lines.append("...")
        lines += [f"{n} | {source[n - 1]}" for n in range(start, end + 1)]
        shown_to = end
    return trim_snippet(lines)


def detect(
    repo: Path | str,
    repo_name: str | None = None,
    commit: str | None = None,
    inventory: Inventory | None = None,
) -> list[Candidate]:
    """File-unit candidates for every file that sets up a correlation ID.

    Pass `inventory` to reuse a scan; otherwise the repo is scanned here.
    """
    repo, inv = load(repo, repo_name, commit, inventory)
    checks = {"java": java_signals, "logging": logging_file_signals, "config": config_signals}
    candidates = []
    for service in inv.services:
        for group, check in checks.items():
            for rel, text in files(repo, service, group):
                signals = sorted(check(rel, text))
                if not signals:
                    continue
                candidates.append(
                    Candidate.create(
                        repo=inv.repo,
                        commit=inv.commit,
                        service=service.name,
                        file=rel,
                        line_start=None,
                        line_end=None,
                        unit=Unit.FILE,
                        pattern=PATTERN,
                        category=CATEGORY,
                        rule_id=RULE_ID,
                        snippet=_snippet(service.name, rel, text, signals),
                    )
                )
    return candidates


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tc_detector.rules.observability.structured_logging")
    p.add_argument("repo_path", type=Path)
    p.add_argument("--repo-name", help="targets.yaml name; defaults to the folder name")
    p.add_argument("--commit", help="pinned SHA; defaults to the checkout's HEAD")
    args = p.parse_args(argv)
    for candidate in detect(args.repo_path, args.repo_name, args.commit):
        print(candidate.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
