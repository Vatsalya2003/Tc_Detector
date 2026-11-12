"""The validation rules for labels: each function checks one part and raises ValueError.

DRAFT: the label format needs team sign-off (see ground_truth/LABEL_FORMAT.md).
The unit, file and line rules are NOT repeated here: Label calls check_file() and
check_lines() from checks.py, so labels and candidates follow the exact same rules.
Read checks.py first, then this file, then label.py.
"""

# Lets us write the "Label" type hint without importing label.py when the program
# runs (label.py imports this file, so the reverse would be a loop).
from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from tc_detector.contracts.ids import KEBAB_CASE, build_id

if TYPE_CHECKING:  # only true for editors and type checkers, never at runtime
    from tc_detector.contracts.label import Label


def check_text_fields(lbl: Label) -> None:
    """Make sure the basic text fields are filled in and safe to put in an id."""
    # Same rule as candidates, minus rule_id (labels come from people, not rules).
    for name in ("repo", "commit", "service", "pattern"):
        value = getattr(lbl, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    # ":" separates the parts of the id, so a ":" inside a part would scramble it.
    for name in ("repo", "service", "pattern"):
        if ":" in getattr(lbl, name):
            raise ValueError(f"{name} must not contain ':' (used as id separator)")
    # Notes may be empty, but must be text so the file always loads the same way.
    if not isinstance(lbl.notes, str):
        raise ValueError("notes must be a string (use '' for no notes)")


def check_pattern(lbl: Label) -> None:
    """Make sure the pattern follows the same naming rule as candidate patterns."""
    # A label only matches a candidate if both use the exact same pattern string.
    if not KEBAB_CASE.fullmatch(lbl.pattern):
        raise ValueError(f"pattern {lbl.pattern!r} must be kebab-case")


def check_verdicts(lbl: Label) -> None:
    """Make sure the verdicts are real true/false values."""
    # "yes", 1 or None would silently count as true or false in scoring.
    if not isinstance(lbl.is_tc, bool):
        raise ValueError("is_tc must be true or false")
    if lbl.second_is_tc is not None and not isinstance(lbl.second_is_tc, bool):
        raise ValueError("second_is_tc must be true, false or None")


def check_labellers(lbl: Label) -> None:
    """Make sure the second-labeller and adjudication fields tell a consistent story."""
    has_second = lbl.second_labeller is not None
    # Kappa needs both the name and the verdict; one without the other is half a record.
    if has_second != (lbl.second_is_tc is not None):
        raise ValueError("second_labeller and second_is_tc must both be set or both be None")
    # Agreement with yourself says nothing about how reliable the labels are.
    if has_second and lbl.second_labeller == lbl.labeller:
        raise ValueError("second_labeller must be a different person from labeller")
    if lbl.adjudicated_by is not None:
        # With one labeller there is no disagreement to settle.
        if not has_second:
            raise ValueError("adjudicated_by requires a second_labeller")
    # Two labellers, no adjudicator: they agreed, so their verdicts must be equal.
    # (When adjudicated, is_tc is the settled answer and may equal either verdict.)
    elif has_second and lbl.second_is_tc != lbl.is_tc:
        raise ValueError(
            "labellers disagree (is_tc != second_is_tc), so adjudicated_by must say who settled it"
        )


def check_label_id(lbl: Label) -> None:
    """Make sure the label_id was built from this label's own fields."""
    # A stale or hand-typed id would make evaluation report the wrong label.
    expected = build_id(
        lbl.repo, lbl.service, lbl.file, lbl.line_start, lbl.line_end, lbl.unit, lbl.pattern
    )
    if lbl.label_id != expected:
        raise ValueError(f"label_id {lbl.label_id!r} does not match fields; expected {expected!r}")


def check_label_file(labels: list[Label]) -> None:
    """Make sure one repo's label file is about one repo at one commit, with no duplicates."""
    # Labels from another repo or commit point at code that isn't what was scanned.
    for name in ("repo", "commit"):
        values = sorted({getattr(lbl, name) for lbl in labels})
        if len(values) > 1:
            raise ValueError(f"all labels in one file must share one {name}; found {values}")
    # Two labels for the same place would make one candidate match twice.
    counts = Counter(lbl.label_id for lbl in labels)
    duplicates = sorted(label_id for label_id, n in counts.items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate label_id(s): {duplicates}")
