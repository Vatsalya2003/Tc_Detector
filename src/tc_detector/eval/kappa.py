"""Agreement between two labellers on the 20% sample: plain agreement and Cohen's kappa.

Read ground_truth/LABEL_FORMAT.md ("Second labeller and disagreements") first.
This file only does the math. agreement.py draws the sample, merges the second labeller's
answers into the label file, and prints the tables.

Only labels in the sample count: those with a second_labeller. For each one we need both
people's ORIGINAL answers, from before any disagreement was settled:
- Second labeller: second_is_tc, always.
- First labeller: is_tc if adjudicated_by is None (they agreed, so is_tc is still their
  answer). Otherwise the opposite of second_is_tc: they disagreed, and is_tc now holds
  whatever the person who settled it decided.

Cohen's kappa = (observed - expected) / (1 - expected), where
- observed = the share of labels the two people answered the same way;
- expected = the share they would agree on by luck alone, if each kept their own rate of
  "yes" answers but answered at random: P(both say yes) + P(both say no).
1 means perfect agreement, 0 means no better than luck, below 0 means worse than luck.

Kappa can't be computed when expected is 1, i.e. both people gave the same answer to every
label in the group (say, all "yes"). There is then no luck level to beat, and kappa is None.
Expect this here: near-misses are skipped (GUIDELINES.md), so most labels are is_tc=true.
Always read kappa next to the plain agreement share.

Pooling: each owner's patterns have their own labeller pair, and Cohen's kappa is defined
for one pair. So the per-pattern numbers are the clean ones; the overall and per-category
numbers pool several pairs and are a summary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tc_detector.contracts.label import Label

# The two ways we split the results, as in metrics.py; both are fields on Label.
GROUP_FIELDS = ("pattern", "category")

# (first labeller's original answer, second labeller's answer)
Answers = tuple[bool, bool]


def original_answers(label: Label) -> Answers | None:
    """Both labellers' original answers for one label, or None if it isn't in the sample."""
    if label.second_labeller is None or label.second_is_tc is None:
        return None
    second = label.second_is_tc
    # Agreed: is_tc is the first labeller's own answer. Disagreed: it was the other one.
    first = label.is_tc if label.adjudicated_by is None else not second
    return first, second


@dataclass(frozen=True, slots=True)
class Agreement:
    """The counts for one group of sampled labels, plus agreement and kappa worked out."""

    group: str  # a pattern name, a category name, or "all"
    sampled: int  # labels in the sample
    agreed: int  # of those, how many both people answered the same way
    first_yes: int  # how many the first labeller originally said is_tc=true
    second_yes: int  # how many the second labeller said is_tc=true

    @property
    def observed(self) -> float | None:
        """Share of sampled labels both people answered the same way. None if none sampled."""
        return self.agreed / self.sampled if self.sampled else None

    @property
    def expected(self) -> float | None:
        """Share they would agree on by luck alone. None if none sampled."""
        return self._luck_pairs / self.sampled**2 if self.sampled else None

    @property
    def kappa(self) -> float | None:
        """Cohen's kappa. None if nothing was sampled or both gave one answer to everything."""
        n = self.sampled
        # The formula from the top of the file, multiplied through by n*n so it uses only
        # whole numbers. That makes "expected is exactly 1" a safe == 0 check, with no
        # floating-point rounding.
        denominator = n * n - self._luck_pairs
        if denominator == 0:
            return None
        return (self.agreed * n - self._luck_pairs) / denominator

    @property
    def _luck_pairs(self) -> int:
        """expected * n * n: (first yes x second yes) + (first no x second no)."""
        n = self.sampled
        return self.first_yes * self.second_yes + (n - self.first_yes) * (n - self.second_yes)


def agreement_overall(labels: Iterable[Label]) -> Agreement:
    """One Agreement covering every sampled label."""
    return _count(_sampled(labels), group="all", field=None)


def agreement_by(labels: Iterable[Label], field: str) -> list[Agreement]:
    """One Agreement per pattern (field="pattern") or per category (field="category").

    A group appears if any sampled label has it, sorted by name.
    """
    if field not in GROUP_FIELDS:
        raise ValueError(f"field must be one of {GROUP_FIELDS}, not {field!r}")
    sampled = _sampled(labels)
    # str() turns a Category enum into its plain name, e.g. "api-stability".
    groups = sorted({str(getattr(label, field)) for label, _ in sampled})
    return [_count(sampled, group=name, field=field) for name in groups]


def _sampled(labels: Iterable[Label]) -> list[tuple[Label, Answers]]:
    """Every label in the sample, with both original answers."""
    pairs = []
    for label in labels:
        answers = original_answers(label)
        if answers is not None:
            pairs.append((label, answers))
    return pairs


def _count(sampled: list[tuple[Label, Answers]], group: str, field: str | None) -> Agreement:
    """Count one group. field=None means "every label belongs" (the overall number)."""
    rows = [
        answers
        for label, answers in sampled
        if field is None or str(getattr(label, field)) == group
    ]
    return Agreement(
        group=group,
        sampled=len(rows),
        agreed=sum(1 for first, second in rows if first == second),
        first_yes=sum(1 for first, _ in rows if first),
        second_yes=sum(1 for _, second in rows if second),
    )
