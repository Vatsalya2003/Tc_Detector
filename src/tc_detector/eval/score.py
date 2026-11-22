"""The scoring script: load candidates and labels, match them, print precision and recall.

Run it from the repo root (both options take one or more files):
    uv run python -m tc_detector.eval.score \\
        --candidates results/petclinic/candidates.jsonl --labels ground_truth/petclinic.json

Candidates files are JSON Lines (one candidate per line), which is what the rules print.
Label files are a JSON list, read by load_labels() from contracts/.

Read matching.py and metrics.py first; this file only loads files, calls them, and prints.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tc_detector.contracts.candidate import Candidate
from tc_detector.contracts.label import Label, load_labels
from tc_detector.eval.matching import match
from tc_detector.eval.metrics import Score, score_by, score_overall


def load_candidates(path: str | Path) -> list[Candidate]:
    """Read a candidates file (JSON Lines: one candidate per line) and check every line.

    This is the format the rules print (`print(candidate.to_json())`). Blank lines are skipped.
    """
    candidates = []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    # Count from 1, like editors do, so the error points at the right line.
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{path}: line {line_number}"
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{where}: not valid JSON ({error.msg})") from error
        # A JSON list here usually means an old-style file (one list instead of one per line).
        if not isinstance(entry, dict):
            raise ValueError(f"{where}: must be one candidate object (JSON Lines format)")
        try:
            candidates.append(Candidate.from_dict(entry))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{where}: {error}") from error
    return candidates


@dataclass(frozen=True, slots=True)
class Report:
    """All the scores for one run: overall, then one per pattern and one per category."""

    overall: Score
    by_pattern: list[Score]
    by_category: list[Score]


def evaluate(candidates: Iterable[Candidate], labels: Iterable[Label]) -> Report:
    """Match candidates to labels and score the result."""
    result = match(candidates, labels)
    return Report(
        overall=score_overall(result),
        by_pattern=score_by(result, "pattern"),
        by_category=score_by(result, "category"),
    )


# The table columns after the group name. "found" is how many TC labels got a candidate.
HEADERS = ("candidates", "TP", "FP", "TC labels", "found", "precision", "recall")


def format_report(report: Report) -> str:
    """Turn a report into three plain-text tables."""
    sections = [
        ("Overall", [report.overall]),
        ("By pattern", report.by_pattern),
        ("By category", report.by_category),
    ]
    return "\n\n".join(_table(title, scores) for title, scores in sections)


def _table(title: str, scores: list[Score]) -> str:
    """One titled table: a header line, then one line per score."""
    name_width = max([len("group"), *(len(s.group) for s in scores)])
    col_widths = [max(len(h), 4) for h in HEADERS]  # 4 fits "0.67" and "n/a"

    def line(name: str, cells: Iterable[str]) -> str:
        padded = (cell.rjust(width) for cell, width in zip(cells, col_widths, strict=True))
        return "  ".join([name.ljust(name_width), *padded])

    rows = [line("group", HEADERS), *(line(s.group, _cells(s)) for s in scores)]
    return "\n".join([title, *rows])


def _cells(s: Score) -> list[str]:
    """The numbers for one row, in the same order as HEADERS."""
    counts = [s.candidates, s.true_positives, s.false_positives, s.tc_labels, s.found]
    return [*(str(n) for n in counts), _ratio(s.precision), _ratio(s.recall)]


def _ratio(value: float | None) -> str:
    """0.6666 -> "0.67"; None (nothing to divide by) -> "n/a"."""
    return "n/a" if value is None else f"{value:.2f}"


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point. argv is for tests; normally it comes from the shell."""
    parser = argparse.ArgumentParser(
        prog="python -m tc_detector.eval.score",
        description="Score candidates against human labels: precision and recall "
        "per pattern and per category.",
    )
    parser.add_argument(
        "--candidates",
        nargs="+",
        required=True,
        type=Path,
        help="candidate file(s) in JSON Lines (one candidate per line), as the rules print them",
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        required=True,
        type=Path,
        help="label file(s), one per repo, e.g. ground_truth/petclinic.json",
    )
    args = parser.parse_args(argv)

    try:
        candidates = [c for path in args.candidates for c in load_candidates(path)]
        labels = [lbl for path in args.labels for lbl in load_labels(path)]
    except (OSError, ValueError) as error:
        # A missing or broken file: one clear line on stderr, exit code 1, no traceback.
        sys.exit(f"error: {error}")

    print(format_report(evaluate(candidates, labels)))


# Lets you run it as `python -m tc_detector.eval.score`.
if __name__ == "__main__":
    main()
