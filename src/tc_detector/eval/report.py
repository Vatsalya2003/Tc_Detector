"""The cost report (pipeline step 5): accuracy and cost per repo, as one Markdown table.

Run it from the repo root (every option takes one or more files):
    uv run python -m tc_detector.eval.report --cost-log results/cost_log.jsonl \\
        --verdicts results/petclinic/verdicts.jsonl \\
        --candidates results/petclinic/candidates.jsonl --labels ground_truth/petclinic.json

Only --cost-log is needed. The other inputs each add rows to the table:
- --verdicts (what `tc-attribute --out` writes): how many candidates Claude confirmed,
  and the cost per confirmed candidate.
- --candidates and --labels (the same files score.py takes): precision and recall.

The table has one column per repo. A cost log row or a verdict has no repo field, but its
candidate_id starts with the repo (ids are repo:service:file:location:pattern, see
contracts/ids.py). Candidates and labels have their own repo field.

Dollars are what the cost log recorded at call time (priced by llm/pricing.py); nothing
here re-prices a call. The table adds up every row it is given, so pass the log of one
run (or one experiment) to compare like with like. Read score.py first for how precision
and recall are counted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from tc_detector.contracts.candidate import Candidate
from tc_detector.contracts.label import Label, load_labels
from tc_detector.eval.metrics import Score
from tc_detector.eval.score import evaluate, load_candidates

# Token counts the cost log records for every call (the same names as llm/costlog.py).
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def repo_of(candidate_id: str) -> str:
    """The repo a candidate id belongs to: everything before the first ":"."""
    # contracts/checks.py forbids ":" in a repo name, so this split can't cut a name in two.
    return candidate_id.split(":", 1)[0]


# ------------------------------------------------------------------ loading files


def load_cost_log(path: str | Path) -> list[dict[str, Any]]:
    """Read a cost log written by llm/costlog.py: one Claude call per line."""
    return _read_rows(path)


def load_verdicts(path: str | Path) -> list[dict[str, Any]]:
    """Read a verdicts file written by `tc-attribute --out`: one verdict per line."""
    return _read_rows(path, check=_check_verdict)


def _check_verdict(row: dict[str, Any]) -> None:
    """A verdict's is_tc must be true, false, or null (null: the call gave no answer)."""
    is_tc = row.get("is_tc", "missing")
    if is_tc is not None and not isinstance(is_tc, bool):
        raise ValueError(f"is_tc must be true, false or null, not {is_tc!r}")


def _read_rows(
    path: str | Path, check: Callable[[dict[str, Any]], None] | None = None
) -> list[dict[str, Any]]:
    """Read JSON Lines where every line is an object with a candidate_id.

    Blank lines are skipped. An error names the file and the line (counting from 1).
    """
    rows = []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        where = f"{path}: line {line_number}"
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{where}: not valid JSON ({error.msg})") from error
        if not isinstance(row, dict):
            raise ValueError(f"{where}: must be one JSON object per line")
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError(f"{where}: needs a candidate_id")
        if check:
            try:
                check(row)
            except ValueError as error:
                raise ValueError(f"{where}: {error}") from error
        rows.append(row)
    return rows


# --------------------------------------------------------------- the numbers


@dataclass(frozen=True, slots=True)
class RepoReport:
    """Every number in one column of the table: one repo's cost, plus accuracy if given."""

    repo: str
    calls: int  # every logged call, cache hits included
    api_calls: int  # calls that reached the API, so cost money
    cache_hits: int  # calls answered from the response cache, so free
    failed_calls: int  # API calls with no usable answer (refusal, max_tokens, bad JSON)
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    cost_usd: float  # dollars spent
    saved_usd: float  # dollars the cache saved: what each cached answer first cost
    candidates: int  # different candidates Claude was asked about
    confirmed: int | None  # of those, how many Claude confirmed; None if no verdicts given
    score: Score | None  # this repo's overall precision and recall; None if not scored

    @property
    def cost_per_candidate(self) -> float | None:
        """Dollars per candidate Claude was asked about. None if there were none."""
        return self.cost_usd / self.candidates if self.candidates else None

    @property
    def cost_per_confirmed(self) -> float | None:
        """Dollars per candidate Claude confirmed. None if none (or no verdicts given)."""
        return self.cost_usd / self.confirmed if self.confirmed else None


def count_confirmed(verdicts: Iterable[dict[str, Any]]) -> int:
    """How many candidates Claude confirmed.

    A candidate is confirmed when more than half of its verdicts say is_tc: true. In a
    normal run each candidate has one verdict, so that verdict decides; with --repeats it is
    a majority vote, and a tie is not confirmed. A failed call (is_tc null) is not a yes.
    """
    verdict_count: Counter[str] = Counter()
    yes_count: Counter[str] = Counter()
    for verdict in verdicts:
        verdict_count[verdict["candidate_id"]] += 1
        if verdict.get("is_tc") is True:
            yes_count[verdict["candidate_id"]] += 1
    return sum(1 for cid, n in verdict_count.items() if yes_count[cid] * 2 > n)


def build_report(
    cost_rows: Iterable[dict[str, Any]],
    verdicts: Iterable[dict[str, Any]] | None = None,
    candidates: Iterable[Candidate] | None = None,
    labels: Iterable[Label] | None = None,
) -> list[RepoReport]:
    """One RepoReport per repo found in any input, sorted by repo name.

    Leave verdicts as None to skip the confirmed counts. Leave candidates and labels as
    None to skip precision and recall; scoring needs both, so give both or neither.
    """
    if (candidates is None) != (labels is None):
        raise ValueError("give candidates and labels together, or neither")
    cost_by_repo = _group(cost_rows, lambda row: repo_of(row["candidate_id"]))
    verdicts_by_repo = _group(verdicts or [], lambda v: repo_of(v["candidate_id"]))
    candidates_by_repo = _group(candidates or [], lambda c: c.repo)
    labels_by_repo = _group(labels or [], lambda lbl: lbl.repo)
    repos = sorted({*cost_by_repo, *verdicts_by_repo, *candidates_by_repo, *labels_by_repo})

    reports = []
    for repo in repos:
        rows = cost_by_repo.get(repo, [])
        hits = sum(1 for row in rows if row.get("cache_hit"))
        confirmed = None
        if verdicts is not None:
            confirmed = count_confirmed(verdicts_by_repo.get(repo, []))
        score = None
        if candidates is not None:
            repo_candidates = candidates_by_repo.get(repo, [])
            score = evaluate(repo_candidates, labels_by_repo.get(repo, [])).overall
        reports.append(
            RepoReport(
                repo=repo,
                calls=len(rows),
                api_calls=len(rows) - hits,
                cache_hits=hits,
                failed_calls=sum(1 for row in rows if row.get("error")),
                **{name: sum(row.get(name) or 0 for row in rows) for name in TOKEN_FIELDS},
                # Rounded like summarize() in llm/costlog.py, so the two totals agree.
                cost_usd=round(sum(row.get("cost_usd") or 0.0 for row in rows), 6),
                saved_usd=round(sum(row.get("saved_usd") or 0.0 for row in rows), 6),
                candidates=len({row["candidate_id"] for row in rows}),
                confirmed=confirmed,
                score=score,
            )
        )
    return reports


T = TypeVar("T")


def _group(items: Iterable[T], key: Callable[[T], str]) -> dict[str, list[T]]:
    """Sort items into lists by key, e.g. by repo."""
    groups: dict[str, list[T]] = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    return groups


# ------------------------------------------------------------------- printing


def format_report(reports: list[RepoReport]) -> str:
    """Turn the reports into one Markdown table: a row per number, a column per repo.

    Rows that need verdicts or labels appear only when those inputs were given.
    """
    if not reports:
        return "Nothing to report: the inputs name no repo."
    rows = _rows(reports)
    header = ["", *(r.repo for r in reports)]
    body = [[name, *(cell(r) for r in reports)] for name, cell in rows]
    return _markdown_table(header, body)


def _rows(reports: list[RepoReport]) -> list[tuple[str, Callable[[RepoReport], str]]]:
    """Each row's name, and how to fill in its cell for one repo."""
    rows: list[tuple[str, Callable[[RepoReport], str]]] = [
        ("Claude calls", lambda r: _count(r.calls)),
        ("API calls", lambda r: _count(r.api_calls)),
        ("Cache hits", lambda r: _count(r.cache_hits)),
        ("Failed calls", lambda r: _count(r.failed_calls)),
        ("Input tokens", lambda r: _count(r.input_tokens)),
        ("Output tokens", lambda r: _count(r.output_tokens)),
        ("Cache read tokens", lambda r: _count(r.cache_read_input_tokens)),
        ("Cache write tokens", lambda r: _count(r.cache_creation_input_tokens)),
        ("Spent (USD)", lambda r: _usd(r.cost_usd)),
        ("Saved by cache (USD)", lambda r: _usd(r.saved_usd)),
        ("Candidates sent to Claude", lambda r: _count(r.candidates)),
        ("Cost per candidate (USD)", lambda r: _usd(r.cost_per_candidate)),
    ]
    if any(r.confirmed is not None for r in reports):
        rows += [
            ("Confirmed by Claude", lambda r: _count(r.confirmed)),
            ("Cost per confirmed (USD)", lambda r: _usd(r.cost_per_confirmed)),
        ]
    if any(r.score is not None for r in reports):
        rows += [
            ("Precision", lambda r: _ratio(r.score, "precision")),
            ("Recall", lambda r: _ratio(r.score, "recall")),
        ]
    return rows


def _count(n: int | None) -> str:
    """51200 -> "51,200"."""
    return "n/a" if n is None else f"{n:,}"


def _usd(value: float | None) -> str:
    """0.28914 -> "$0.289140"; None (nothing to divide by) -> "n/a".

    Six decimals, as the cost log stores them: a small model can cost under $0.001 a call.
    """
    return "n/a" if value is None else f"${value:.6f}"


def _ratio(score: Score | None, which: str) -> str:
    """Precision or recall with the counts behind it, e.g. "0.72 (13/18)"."""
    if score is None:
        return "n/a"
    if which == "precision":
        value, part, whole = score.precision, score.true_positives, score.candidates
    else:
        value, part, whole = score.recall, score.found, score.tc_labels
    return "n/a" if value is None else f"{value:.2f} ({part}/{whole})"


def _markdown_table(header: list[str], body: list[list[str]]) -> str:
    """A Markdown table, padded so it also lines up in a terminal.

    The first column (row names) is left-aligned; the repo columns are right-aligned.
    """
    # Markdown needs at least 3 dashes under each header cell.
    widths = [max(3, *(len(row[i]) for row in [header, *body])) for i in range(len(header))]

    def line(cells: list[str]) -> str:
        first = cells[0].ljust(widths[0])
        rest = (cell.rjust(width) for cell, width in zip(cells[1:], widths[1:], strict=True))
        return "| " + " | ".join([first, *rest]) + " |"

    separator = "|" + "|".join(["-" * (widths[0] + 2), *("-" * (w + 1) + ":" for w in widths[1:])])
    return "\n".join([line(header), separator + "|", *(line(row) for row in body)])


# --------------------------------------------------------------- command line


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point. argv is for tests; normally it comes from the shell."""
    parser = argparse.ArgumentParser(
        prog="python -m tc_detector.eval.report",
        description="Accuracy and cost per repo, as a Markdown table.",
    )
    parser.add_argument(
        "--cost-log",
        nargs="+",
        required=True,
        type=Path,
        help="cost log(s) the Claude wrapper wrote, e.g. results/cost_log.jsonl",
    )
    parser.add_argument(
        "--verdicts",
        nargs="+",
        type=Path,
        help="verdict file(s) from `tc-attribute --out`; adds the confirmed counts",
    )
    parser.add_argument(
        "--candidates",
        nargs="+",
        type=Path,
        help="candidate file(s), as for score.py; needs --labels",
    )
    parser.add_argument(
        "--labels",
        nargs="+",
        type=Path,
        help="label file(s), as for score.py; needs --candidates",
    )
    args = parser.parse_args(argv)
    if (args.candidates is None) != (args.labels is None):
        parser.error("--candidates and --labels go together: give both or neither")

    try:
        cost_rows = [row for path in args.cost_log for row in load_cost_log(path)]
        verdicts = None
        if args.verdicts is not None:
            verdicts = [v for path in args.verdicts for v in load_verdicts(path)]
        candidates = labels = None
        if args.candidates is not None:
            candidates = [c for path in args.candidates for c in load_candidates(path)]
            labels = [lbl for path in args.labels for lbl in load_labels(path)]
    except (OSError, ValueError) as error:
        # A missing or broken file: one clear line on stderr, exit code 1, no traceback.
        sys.exit(f"error: {error}")

    print(format_report(build_report(cost_rows, verdicts, candidates, labels)))


# Lets you run it as `python -m tc_detector.eval.report`.
if __name__ == "__main__":
    main()
