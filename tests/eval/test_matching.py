"""Tests for matching.py: when a candidate fits a label, and how pairs are chosen one to one."""

import pytest

from tc_detector.eval.matching import match, overlap
from tests.eval.examples import WHOLE_FILE, WHOLE_SERVICE, cand, lbl

# ----------------------------------------------------------- overlap(): line ranges


@pytest.mark.parametrize(
    ("start", "end", "shared"),
    [
        (10, 20, 11),  # exactly the label's lines (10-20 is 11 lines)
        (15, 30, 6),  # partly inside: lines 15-20
        (12, 14, 3),  # fully inside the label
        (1, 40, 11),  # covers the whole label and more
        (20, 30, 1),  # touches at one line (20): still a match
        (5, 10, 1),  # touches at the label's first line
    ],
)
def test_overlap_counts_shared_lines(start, end, shared):
    """The overlap is how many lines both ranges cover, end lines included."""
    assert overlap(cand(line_start=start, line_end=end), lbl()) == shared


@pytest.mark.parametrize(("start", "end"), [(21, 30), (1, 9)])
def test_ranges_that_do_not_share_a_line_do_not_match(start, end):
    """Side by side is not overlapping: 21-30 doesn't touch 10-20."""
    assert overlap(cand(line_start=start, line_end=end), lbl()) == 0


# --------------------------------------------- overlap(): things that must be equal


@pytest.mark.parametrize(
    "change",
    [
        {"repo": "other-shop"},
        {"service": "billing"},  # same file path, different service
        {"file": "src/Other.java"},
        {"pattern": "feature-flags", "category": "configurability"},
        WHOLE_FILE,  # different unit: a file claim never matches a line label
    ],
)
def test_any_difference_in_place_means_no_match(change):
    """Repo, service, file, pattern and unit must all be equal."""
    assert overlap(cand(**change), lbl()) == 0


def test_overlap_ignores_the_verdict():
    """Matching doesn't look at is_tc; scoring decides what a match to a 'no' label means."""
    assert overlap(cand(), lbl(is_tc=False)) == 11


# ------------------------------------------------ overlap(): file and service units


def test_file_units_match_on_the_same_file():
    """Whole-file claims are all-or-nothing: same file is a match of size 1."""
    assert overlap(cand(**WHOLE_FILE), lbl(**WHOLE_FILE)) == 1
    assert overlap(cand(**WHOLE_FILE, file="src/Other.java"), lbl(**WHOLE_FILE)) == 0


def test_service_units_match_on_the_same_service():
    """Whole-service claims only need the same service."""
    assert overlap(cand(**WHOLE_SERVICE), lbl(**WHOLE_SERVICE)) == 1
    assert overlap(cand(**WHOLE_SERVICE, service="billing"), lbl(**WHOLE_SERVICE)) == 0


def test_service_units_ignore_the_file():
    """A service claim may name a file as a hint; it doesn't change the match."""
    assert overlap(cand(**{**WHOLE_SERVICE, "file": "pom.xml"}), lbl(**WHOLE_SERVICE)) == 1


# ----------------------------------------------------------------------- match()


def test_one_candidate_one_label():
    """The simplest case: they pair up and nothing is left over."""
    result = match([cand()], [lbl()])
    assert [(m.candidate, m.label, m.overlap) for m in result.matches] == [(cand(), lbl(), 11)]
    assert result.unmatched_candidates == []
    assert result.unmatched_labels == []


def test_nothing_to_match():
    """Empty inputs give an empty result, not an error."""
    result = match([], [])
    assert (result.matches, result.unmatched_candidates, result.unmatched_labels) == ([], [], [])


def test_unrelated_candidates_and_labels_stay_unmatched():
    """No overlap: everything ends up in the leftovers."""
    far_away = cand(line_start=100, line_end=110)
    result = match([far_away], [lbl()])
    assert result.matches == []
    assert result.unmatched_candidates == [far_away]
    assert result.unmatched_labels == [lbl()]


def test_a_label_takes_the_candidate_with_the_biggest_overlap():
    """Two candidates fit one label: the one sharing more lines wins, the other is left over."""
    small = cand(line_start=19, line_end=25)  # shares 2 lines
    big = cand(line_start=12, line_end=25)  # shares 9 lines
    result = match([small, big], [lbl()])
    assert [m.candidate for m in result.matches] == [big]
    assert result.unmatched_candidates == [small]


def test_a_candidate_takes_at_most_one_label():
    """One long candidate covering two labels is paired with only one of them."""
    first = lbl(line_start=10, line_end=20)
    second = lbl(line_start=30, line_end=32)
    long = cand(line_start=10, line_end=32)  # shares 11 lines with first, 3 with second
    result = match([long], [first, second])
    assert [m.label for m in result.matches] == [first]
    assert result.unmatched_labels == [second]


def test_identical_candidates_from_two_rules_give_one_match():
    """Two rules can report the same place; only one of them can claim the label."""
    a = cand(rule_id="abstraction-gateway-01")
    b = cand(rule_id="abstraction-gateway-02")
    result = match([a, b], [lbl()])
    assert len(result.matches) == 1
    assert len(result.unmatched_candidates) == 1


def test_labels_judged_false_still_get_matched():
    """A candidate on an is_tc=false label is paired with it (scoring calls it a false positive)."""
    result = match([cand()], [lbl(is_tc=False)])
    assert [m.label.is_tc for m in result.matches] == [False]


def test_input_order_does_not_change_the_result():
    """Ties (equal overlap) are broken by ids, not by which file came first."""
    left = cand(line_start=5, line_end=12)  # shares 3 lines
    right = cand(line_start=18, line_end=25)  # also shares 3 lines
    forwards = match([left, right], [lbl()])
    backwards = match([right, left], [lbl()])
    assert forwards.matches == backwards.matches


def test_greedy_takes_the_biggest_overlap_even_if_a_cleverer_pairing_exists():
    """Pins down the trade-off described in match(): simple beats optimal.

    long fits label 10-20 best (11 lines) and also fits 21-30 (7 lines).
    short fits only 10-20. Greedy gives 10-20 to long, so short and 21-30 stay unmatched,
    even though long->21-30 plus short->10-20 would make two matches.
    """
    first = lbl(line_start=10, line_end=20)
    second = lbl(line_start=21, line_end=30)
    long = cand(line_start=10, line_end=27)
    short = cand(line_start=10, line_end=12)
    result = match([long, short], [first, second])
    assert [(m.candidate, m.label) for m in result.matches] == [(long, first)]
    assert result.unmatched_candidates == [short]
    assert result.unmatched_labels == [second]
