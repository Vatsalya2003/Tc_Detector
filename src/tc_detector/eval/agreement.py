"""The 20% agreement sample: draw it, merge the second labeller's answers, print kappa.

Run from the repo root. The steps, in order:

1. Once a repo's first labels are frozen, draw the sample:
       uv run python -m tc_detector.eval.agreement sample --labels ground_truth/petclinic.json \\
           --seed 2026 --out ground_truth/petclinic-agreement.json
   This writes a BLIND worksheet: where each sampled label is and who checks it, but not
   the first labeller's answer or notes. Always use the fixed seed (SEED below).
2. Each second labeller sets "second_is_tc" to true or false on their own rows, judging
   from GUIDELINES.md and the code alone, without opening the label file first.
3. Copy the answers into the label file:
       uv run python -m tc_detector.eval.agreement merge --labels ground_truth/petclinic.json \\
           --worksheet ground_truth/petclinic-agreement.json
   Rows nobody has answered yet are skipped, so this can run as each person finishes.
   If an answer disagrees with the first labeller, merge lists it and writes nothing.
   Settle it as LABEL_FORMAT.md says, fill in "adjudicated_by" and "final_is_tc" on that
   row, and run merge again.
4. Print agreement and kappa:
       uv run python -m tc_detector.eval.agreement kappa --labels ground_truth/petclinic.json

Read kappa.py first for the math. This file draws the sample, moves answers between the
worksheet and the label file, and prints.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tc_detector.contracts.label import Label, Labeller, load_labels, save_labels
from tc_detector.eval.kappa import Agreement, agreement_by, agreement_overall, original_answers

# How much of each pattern's labels the second labeller checks (GUIDELINES.md).
SAMPLE_PERCENT = 20

# The seed the team fixed in advance (GUIDELINES.md, "Agreement sample"), so nobody can
# redraw until they like the sample.
SEED = 2026

# Who owns each pattern: GUIDELINES.md, "Patterns at a glance".
# A test compares both tables here with GUIDELINES.md, so they can't drift apart.
OWNER = {
    "gateway": "D",
    "externalised-config": "D",
    "feature-flags": "D",
    "distributed-tracing": "A",
    "structured-logging": "A",
    "custom-metrics": "A",
    "versioned-api": "B",
    "immutable-data-contracts": "B",
    "event-schema-versioning": "B",
    "circuit-breaker-retry": "C",
    "health-checks": "C",
    "saga": "C",
}

# The second labeller of each owner's patterns: GUIDELINES.md, "Who labels what".
SECOND_LABELLER = {"A": "C", "B": "D", "C": "A", "D": "B"}

# The top-level keys of a worksheet file.
WORKSHEET_KEYS = ("repo", "commit", "seed", "percent", "rows")

# The keys of one worksheet row, in the order they are written. The first seven say where
# to look. The last four are filled in by people.
ROW_KEYS = (
    "label_id",
    "service",
    "file",
    "line_start",
    "line_end",
    "unit",
    "pattern",
    "second_labeller",
    "second_is_tc",
    "adjudicated_by",
    "final_is_tc",
)


# ------------------------------------------------------------ step 1: sample


def draw_sample(labels: Iterable[Label], seed: int) -> list[Label]:
    """About 20% of each pattern's labels, rounded up. The same seed always picks the same ones.

    - Per pattern, so every pattern, and so every second labeller, gets part of the sample.
    - Rounded up, so a pattern with a single label still gets it checked.
    - Labels are sorted by label_id first, so their order in the file doesn't matter.
    - Each pattern gets its own random generator, seeded with "<seed>:<pattern>". Adding
      labels for one pattern then can't change which labels another pattern gets.
    """
    by_pattern: dict[str, list[Label]] = defaultdict(list)
    for label in labels:
        by_pattern[label.pattern].append(label)
    chosen = []
    for pattern, group in sorted(by_pattern.items()):
        group.sort(key=lambda label: label.label_id)
        size = math.ceil(len(group) * SAMPLE_PERCENT / 100)
        # A text seed is turned into numbers the same way on every machine and every run.
        generator = random.Random(f"{seed}:{pattern}")
        chosen.extend(generator.sample(group, size))
    return sorted(chosen, key=lambda label: label.label_id)


def make_worksheet(labels: list[Label], seed: int) -> dict[str, Any]:
    """The blind worksheet for one repo's labels: where to look and who looks, no answers."""
    if not labels:
        raise ValueError("there are no labels to sample")
    rows = [_blank_row(label) for label in draw_sample(labels, seed)]
    # Each person's rows next to each other, so they can find theirs.
    rows.sort(key=lambda row: (row["second_labeller"] or "", row["label_id"]))
    return {
        "repo": labels[0].repo,
        "commit": labels[0].commit,
        "seed": seed,
        "percent": SAMPLE_PERCENT,
        "rows": rows,
    }


def _blank_row(label: Label) -> dict[str, Any]:
    """One worksheet row: where the label is, who checks it, and empty answers.

    is_tc and notes are left out on purpose: the second labeller must not see the first
    labeller's answer before giving their own.
    """
    owner = OWNER.get(label.pattern)
    return {
        "label_id": label.label_id,
        "service": label.service,
        "file": label.file,
        "line_start": label.line_start,
        "line_end": label.line_end,
        "unit": label.unit.value,
        "pattern": label.pattern,
        # A pattern missing from GUIDELINES.md has no known second labeller: fill it in by hand.
        "second_labeller": SECOND_LABELLER[owner] if owner else None,
        "second_is_tc": None,
        "adjudicated_by": None,
        "final_is_tc": None,
    }


# ------------------------------------------------------------ step 3: merge


@dataclass(frozen=True, slots=True)
class MergeResult:
    """What merge() did. Only write `labels` to disk if `unsettled` is empty."""

    labels: list[Label]  # every label, in the original order, with the answers copied in
    merged: int  # rows whose answers were copied in
    unanswered: int  # rows nobody has answered yet; skipped
    unsettled: list[str]  # disagreements that still need adjudicated_by and final_is_tc
    changed: list[str]  # labels whose final is_tc changed; each goes in the change log


def merge(labels: list[Label], worksheet: dict[str, Any]) -> MergeResult:
    """Copy the answers in a filled-in worksheet into the labels it was drawn from.

    Raises ValueError if the worksheet is broken or wasn't drawn from these labels.
    """
    _check_worksheet(worksheet, labels)
    by_id = {label.label_id: label for label in labels}
    updated: dict[str, Label] = {}
    unanswered = 0
    unsettled: list[str] = []
    changed: list[str] = []

    for number, row in enumerate(worksheet["rows"], start=1):
        try:
            label = _label_for(row, by_id)
            if row["second_is_tc"] is None:
                if row["adjudicated_by"] is not None or row["final_is_tc"] is not None:
                    raise ValueError("fill in second_is_tc before adjudicated_by and final_is_tc")
                unanswered += 1
                continue
            second_labeller = _person(row, "second_labeller", label.pattern)
            second = _true_or_false(row, "second_is_tc")
            first = _first_answer(label)
            if first == second:
                if row["adjudicated_by"] is not None or row["final_is_tc"] is not None:
                    raise ValueError(
                        "both labellers agree, so adjudicated_by and final_is_tc stay null"
                    )
                adjudicated_by, final = None, first
            elif row["adjudicated_by"] is None or row["final_is_tc"] is None:
                unsettled.append(
                    f"{label.label_id}: first labeller {label.labeller.value} said "
                    f"{_text(first)}, second labeller {second_labeller.value} said {_text(second)}"
                )
                continue
            else:
                adjudicated_by = _person(row, "adjudicated_by", label.pattern)
                final = _true_or_false(row, "final_is_tc")
            # replace() builds a new Label, so every label check runs again on the result.
            new = replace(
                label,
                is_tc=final,
                second_labeller=second_labeller,
                second_is_tc=second,
                adjudicated_by=adjudicated_by,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"worksheet row {number}: {error}") from error
        if new.is_tc != label.is_tc:
            changed.append(
                f"{label.label_id}: is_tc {_text(label.is_tc)} -> {_text(new.is_tc)}, "
                f"settled by {new.adjudicated_by}"
            )
        updated[label.label_id] = new

    return MergeResult(
        labels=[updated.get(label.label_id, label) for label in labels],
        merged=len(updated),
        unanswered=unanswered,
        unsettled=unsettled,
        changed=changed,
    )


def _check_worksheet(worksheet: Any, labels: list[Label]) -> None:
    """Make sure the worksheet has the right shape and was drawn from these labels."""
    if not isinstance(worksheet, dict) or set(worksheet) != set(WORKSHEET_KEYS):
        raise ValueError(f"a worksheet must be an object with keys: {', '.join(WORKSHEET_KEYS)}")
    if labels and (worksheet["repo"], worksheet["commit"]) != (labels[0].repo, labels[0].commit):
        raise ValueError("this worksheet was drawn from a different repo or commit")
    rows = worksheet["rows"]
    if not isinstance(rows, list):
        raise ValueError("the worksheet's rows must be a list")
    # Two answers for one label: we couldn't tell which one counts.
    counts = Counter(row.get("label_id") for row in rows if isinstance(row, dict))
    duplicates = sorted(str(label_id) for label_id, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"the worksheet lists these labels twice: {duplicates}")


def _label_for(row: Any, by_id: dict[str, Label]) -> Label:
    """The label a worksheet row is about, after checking the row's keys."""
    if not isinstance(row, dict) or set(row) != set(ROW_KEYS):
        raise ValueError(f"a row must have exactly these keys: {', '.join(ROW_KEYS)}")
    label = by_id.get(row["label_id"])
    if label is None:
        raise ValueError(f"{row['label_id']!r} is not in the label file")
    return label


def _first_answer(label: Label) -> bool:
    """The first labeller's original answer, even if an earlier merge changed is_tc."""
    answers = original_answers(label)
    return label.is_tc if answers is None else answers[0]


def _person(row: dict[str, Any], key: str, pattern: str) -> Labeller:
    """The letter in row[key], which must not be the pattern's owner."""
    value = row[key]
    try:
        person = Labeller(value)
    except ValueError:
        raise ValueError(f"{key} must be one of A, B, C, D, not {value!r}") from None
    # GUIDELINES.md: owners never label or adjudicate their own patterns.
    if person.value == OWNER.get(pattern):
        raise ValueError(f"{key} {person.value} owns {pattern} and can't label or settle it")
    return person


def _true_or_false(row: dict[str, Any], key: str) -> bool:
    """row[key], which must be true or false (not "yes", 1 or null)."""
    value = row[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false, not {value!r}")
    return value


def _text(value: bool) -> str:
    """True -> "true", as it is written in the files."""
    return "true" if value else "false"


# ------------------------------------------------------------ step 4: kappa

# The table columns after the group name.
HEADERS = ("sampled", "agreed", "agreement", "kappa")

NOT_AVAILABLE = (
    "n/a: nothing was sampled, or both labellers gave the same answer to every label in that "
    "group, so kappa can't be computed (see kappa.py)."
)


def format_agreement(labels: Iterable[Label]) -> str:
    """Three plain-text tables (overall, by pattern, by category), as in score.py."""
    labels = list(labels)
    sections = [
        ("Overall", [agreement_overall(labels)]),
        ("By pattern", agreement_by(labels, "pattern")),
        ("By category", agreement_by(labels, "category")),
    ]
    text = "\n\n".join(_table(title, rows) for title, rows in sections)
    if any(row.kappa is None for _, rows in sections for row in rows):
        text += "\n\n" + NOT_AVAILABLE
    return text


def _table(title: str, rows: list[Agreement]) -> str:
    """One titled table: a header line, then one line per group."""
    name_width = max([len("group"), *(len(row.group) for row in rows)])
    col_widths = [max(len(h), 5) for h in HEADERS]  # 5 fits "-1.00"

    def line(name: str, cells: Iterable[str]) -> str:
        padded = (cell.rjust(width) for cell, width in zip(cells, col_widths, strict=True))
        return "  ".join([name.ljust(name_width), *padded])

    lines = [line("group", HEADERS), *(line(row.group, _cells(row)) for row in rows)]
    return "\n".join([title, *lines])


def _cells(row: Agreement) -> list[str]:
    """The numbers for one row, in the same order as HEADERS."""
    return [str(row.sampled), str(row.agreed), _number(row.observed), _number(row.kappa)]


def _number(value: float | None) -> str:
    """0.6666 -> "0.67"; None -> "n/a"."""
    return "n/a" if value is None else f"{value:.2f}"


# ------------------------------------------------------------ command line


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point. argv is for tests; normally it comes from the shell."""
    parser = argparse.ArgumentParser(
        prog="python -m tc_detector.eval.agreement",
        description="The 20% agreement sample: draw it, merge the second labeller's answers, "
        "print agreement and Cohen's kappa.",
    )
    steps = parser.add_subparsers(dest="step", required=True)

    sample = steps.add_parser("sample", help="draw the sample and write a blind worksheet")
    sample.add_argument(
        "--labels",
        required=True,
        type=Path,
        help="one repo's label file, e.g. ground_truth/petclinic.json",
    )
    sample.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help=f"default {SEED}, the seed fixed in GUIDELINES.md; another seed only warns",
    )
    sample.add_argument(
        "--out",
        required=True,
        type=Path,
        help="where to write the worksheet, e.g. ground_truth/petclinic-agreement.json",
    )

    merging = steps.add_parser("merge", help="copy a filled-in worksheet into the label file")
    merging.add_argument("--labels", required=True, type=Path, help="the label file to update")
    merging.add_argument("--worksheet", required=True, type=Path, help="the filled-in worksheet")

    kappa = steps.add_parser("kappa", help="print agreement and Cohen's kappa")
    kappa.add_argument(
        "--labels", nargs="+", required=True, type=Path, help="label file(s), one per repo"
    )

    args = parser.parse_args(argv)
    try:
        if args.step == "sample":
            _run_sample(args.labels, args.seed, args.out)
        elif args.step == "merge":
            _run_merge(args.labels, args.worksheet)
        else:
            labels = [label for path in args.labels for label in load_labels(path)]
            print(format_agreement(labels))
    except (OSError, ValueError) as error:
        # A missing or broken file: one clear message on stderr, exit code 1, no traceback.
        sys.exit(f"error: {error}")


def _run_sample(labels_path: Path, seed: int, out: Path) -> None:
    """Step 1: write the worksheet and say who has how many rows to check."""
    # A worksheet may already hold answers; never overwrite it by accident.
    if out.exists():
        raise ValueError(f"{out} already exists and may hold answers; delete it first")
    labels = load_labels(labels_path)
    worksheet = make_worksheet(labels, seed)
    out.write_text(json.dumps(worksheet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = worksheet["rows"]
    print(f"Sampled {len(rows)} of {len(labels)} labels with seed {seed} into {out}.")
    per_person = Counter(row["second_labeller"] or "no second labeller yet" for row in rows)
    for person, count in sorted(per_person.items()):
        print(f"  {person}: {count} to check")
    if seed != SEED:
        print(f"Warning: GUIDELINES.md fixes the seed at {SEED}. This sample doesn't count.")


def _run_merge(labels_path: Path, worksheet_path: Path) -> None:
    """Step 3: copy the answers into the label file, or say what must be settled first."""
    labels = load_labels(labels_path)
    worksheet = json.loads(worksheet_path.read_text(encoding="utf-8"))
    result = merge(labels, worksheet)
    if result.unsettled:
        raise ValueError(
            "settle these disagreements first (LABEL_FORMAT.md), then fill in adjudicated_by "
            "and final_is_tc on their rows and merge again. Nothing was written.\n  "
            + "\n  ".join(result.unsettled)
        )
    save_labels(labels_path, result.labels)
    print(
        f"Merged {result.merged} answers into {labels_path}; "
        f"{result.unanswered} rows not answered yet."
    )
    if result.changed:
        print("These final answers changed; add each one to the change log in GUIDELINES.md:")
        for line in result.changed:
            print(f"  {line}")


# Lets you run it as `python -m tc_detector.eval.agreement`.
if __name__ == "__main__":
    main()
