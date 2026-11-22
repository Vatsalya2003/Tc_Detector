"""Metrics: precision and recall per pattern, per category and overall.

Read matching.py first: this file only counts the pairs it made.

- A candidate is a TRUE POSITIVE if it was paired with a label whose is_tc is true.
- Every other candidate is a FALSE POSITIVE: unpaired (including extra candidates that lost
  a label to a bigger overlap), or paired with a label whose is_tc is false.
- Recall only counts labels whose is_tc is true. An is_tc=false label is never "missed".

Each candidate is counted in the group of its own pattern/category, and each label in the
group of its own. Matching requires the same pattern, so the two sides always agree per
pattern, and per category as long as each pattern belongs to one category.
"""

from __future__ import annotations

from dataclasses import dataclass

from tc_detector.contracts.candidate import Candidate
from tc_detector.contracts.label import Label
from tc_detector.eval.matching import MatchResult

# The two ways we split the results; both are fields on Candidate and Label.
GROUP_FIELDS = ("pattern", "category")


@dataclass(frozen=True, slots=True)
class Score:
    """The counts for one group, plus the precision and recall worked out from them."""

    group: str  # a pattern name, a category name, or "all"
    candidates: int  # candidates in this group
    true_positives: int  # of those, how many were paired with an is_tc=true label
    tc_labels: int  # labels in this group with is_tc true
    found: int  # of those, how many were paired with a candidate

    @property
    def false_positives(self) -> int:
        """Candidates that were not real credit (or not matched to any)."""
        return self.candidates - self.true_positives

    @property
    def missed(self) -> int:
        """Real credit (is_tc=true labels) that no candidate was paired with."""
        return self.tc_labels - self.found

    @property
    def precision(self) -> float | None:
        """Share of candidates that were real credit. None if there were no candidates."""
        return self.true_positives / self.candidates if self.candidates else None

    @property
    def recall(self) -> float | None:
        """Share of real credit that was found. None if no label here has is_tc true."""
        return self.found / self.tc_labels if self.tc_labels else None


def score_overall(result: MatchResult) -> Score:
    """One Score covering every candidate and label."""
    return _score(result, group="all", field=None)


def score_by(result: MatchResult, field: str) -> list[Score]:
    """One Score per pattern (field="pattern") or per category (field="category").

    A group appears if any candidate or label has it, sorted by name.
    """
    if field not in GROUP_FIELDS:
        raise ValueError(f"field must be one of {GROUP_FIELDS}, not {field!r}")
    everything = [*_all_candidates(result), *_all_labels(result)]
    groups = sorted({str(getattr(item, field)) for item in everything})
    return [_score(result, group=name, field=field) for name in groups]


def _score(result: MatchResult, group: str, field: str | None) -> Score:
    """Count one group. field=None means "every item belongs" (the overall score)."""

    def belongs(item: Candidate | Label) -> bool:
        # str() turns a Category enum into its plain name, e.g. "abstraction".
        return field is None or str(getattr(item, field)) == group

    # Only pairs with an is_tc=true label count as hits.
    hits = [m for m in result.matches if m.label.is_tc]
    return Score(
        group=group,
        candidates=sum(1 for c in _all_candidates(result) if belongs(c)),
        true_positives=sum(1 for m in hits if belongs(m.candidate)),
        tc_labels=sum(1 for lbl in _all_labels(result) if lbl.is_tc and belongs(lbl)),
        found=sum(1 for m in hits if belongs(m.label)),
    )


def _all_candidates(result: MatchResult) -> list[Candidate]:
    """Every candidate, paired or not."""
    return [m.candidate for m in result.matches] + result.unmatched_candidates


def _all_labels(result: MatchResult) -> list[Label]:
    """Every label, paired or not."""
    return [m.label for m in result.matches] + result.unmatched_labels
