"""Matching: pair each candidate with at most one human label, and each label with at most one.

Read this file first in eval/: metrics.py only counts the pairs made here.

When do a candidate and a label match?
- Always: same repo, same pattern, same unit, and same service.
- line_range: also the same file, and the two line ranges share at least one line.
- file: also the same file.
- service: nothing more.

Why "same service" even for file units: file paths are relative to the service root,
so two services can both have a "src/main/resources/application.yml".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from tc_detector.contracts.candidate import Candidate
from tc_detector.contracts.enums import Unit
from tc_detector.contracts.label import Label


@dataclass(frozen=True, slots=True)
class Match:
    """One candidate paired with one label."""

    candidate: Candidate
    label: Label
    overlap: int  # lines shared for line_range; always 1 for file and service


@dataclass(frozen=True, slots=True)
class MatchResult:
    """What matching produced: the pairs, plus whatever was left without a partner."""

    matches: list[Match]
    unmatched_candidates: list[Candidate]  # every one of these is a false positive
    unmatched_labels: list[Label]  # the is_tc=true ones are credit the detector missed


def overlap(candidate: Candidate, label: Label) -> int:
    """How well a candidate fits a label: 0 means no match, bigger means a better match."""
    same_place = (candidate.repo, candidate.service, candidate.pattern, candidate.unit) == (
        label.repo,
        label.service,
        label.pattern,
        label.unit,
    )
    if not same_place:
        return 0
    # A whole-service claim has nothing finer to compare.
    if candidate.unit == Unit.SERVICE:
        return 1
    if candidate.file != label.file:
        return 0
    # A whole-file claim is all-or-nothing: same file is a full match.
    if candidate.unit == Unit.FILE:
        return 1
    # line_range: count the lines both ranges cover. Ranges include both end lines,
    # so 10-20 and 20-30 share one line (20). A negative count means they don't touch.
    shared = (
        min(candidate.line_end, label.line_end) - max(candidate.line_start, label.line_start) + 1
    )
    return max(shared, 0)


def match(candidates: Iterable[Candidate], labels: Iterable[Label]) -> MatchResult:
    """Pair candidates with labels one to one, biggest overlap first.

    This is "greedy": it keeps taking the biggest overlap still available. In a rare case
    (one long candidate covering two labels, while a second candidate fits only one of them)
    a cleverer pairing could find one more match. We accept that to keep the rule simple
    and easy to check by hand.
    """
    candidates = list(candidates)
    labels = list(labels)

    # Every pair that matches at all, as (overlap, label position, candidate position).
    # We track positions, not objects, because two rules can emit identical candidates.
    pairs = [
        (size, label_pos, cand_pos)
        for label_pos, label in enumerate(labels)
        for cand_pos, candidate in enumerate(candidates)
        if (size := overlap(candidate, label)) > 0
    ]

    # Biggest overlap first. Ties are broken by ids, so reordering the input files
    # never changes the result.
    def sort_key(pair: tuple[int, int, int]) -> tuple[int, str, str, str]:
        size, label_pos, cand_pos = pair
        candidate = candidates[cand_pos]
        return (-size, labels[label_pos].label_id, candidate.id, candidate.rule_id)

    pairs.sort(key=sort_key)

    # Walk down the list; keep a pair only if neither side already has a partner.
    used_labels: set[int] = set()
    used_candidates: set[int] = set()
    matches = []
    for size, label_pos, cand_pos in pairs:
        if label_pos in used_labels or cand_pos in used_candidates:
            continue
        used_labels.add(label_pos)
        used_candidates.add(cand_pos)
        matches.append(Match(candidates[cand_pos], labels[label_pos], size))

    return MatchResult(
        matches=matches,
        unmatched_candidates=[c for i, c in enumerate(candidates) if i not in used_candidates],
        unmatched_labels=[lbl for i, lbl in enumerate(labels) if i not in used_labels],
    )
