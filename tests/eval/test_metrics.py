"""Tests for metrics.py: what counts as a true/false positive, and precision/recall per group."""

import pytest

from tc_detector.eval.matching import match
from tc_detector.eval.metrics import Score, score_by, score_overall
from tests.eval.examples import WHOLE_FILE, cand, lbl


def overall(candidates, labels) -> Score:
    """Match, then score everything together."""
    return score_overall(match(candidates, labels))


# --------------------------------------------------------------- one rule per test


def test_a_perfect_match():
    """One candidate on one real credit: precision and recall are both 1."""
    score = overall([cand()], [lbl()])
    assert score == Score("all", candidates=1, true_positives=1, tc_labels=1, found=1)
    assert (score.precision, score.recall) == (1.0, 1.0)


def test_an_unmatched_candidate_is_a_false_positive():
    """A candidate where nobody labelled anything counts against precision."""
    score = overall([cand(), cand(line_start=100, line_end=110)], [lbl()])
    assert (score.true_positives, score.false_positives) == (1, 1)
    assert score.precision == 0.5


def test_an_extra_candidate_on_a_taken_label_is_a_false_positive():
    """One to one: a second candidate on the same label doesn't count twice."""
    score = overall([cand(), cand(line_start=15, line_end=25)], [lbl()])
    assert (score.true_positives, score.false_positives) == (1, 1)
    assert score.recall == 1.0


def test_a_candidate_on_a_label_judged_false_is_a_false_positive():
    """Humans said 'no credit here', so finding it is a mistake."""
    score = overall([cand()], [lbl(is_tc=False)])
    assert (score.true_positives, score.false_positives) == (0, 1)
    assert score.precision == 0.0


def test_a_missed_real_credit_lowers_recall():
    """A true label no candidate reached counts as missed."""
    labels = [lbl(), lbl(line_start=50, line_end=60)]
    score = overall([cand()], labels)
    assert (score.found, score.missed) == (1, 1)
    assert score.recall == 0.5


def test_labels_judged_false_are_never_missed():
    """Recall only counts is_tc=true labels."""
    score = overall([], [lbl(is_tc=False)])
    assert (score.tc_labels, score.missed) == (0, 0)


def test_nothing_to_divide_gives_none_not_a_crash():
    """No candidates: precision is None. No true labels: recall is None."""
    assert overall([], [lbl()]).precision is None
    assert overall([cand()], []).recall is None


def test_score_by_rejects_an_unknown_field():
    """Only pattern and category are supported groupings."""
    with pytest.raises(ValueError, match="field must be one of"):
        score_by(match([], []), "service")


def test_a_pattern_only_in_the_labels_still_gets_a_row():
    """A labelled pattern no rule reported yet shows up with zero candidates and recall 0."""
    labels = [lbl(pattern="saga", category="modularity")]
    assert score_by(match([], labels), "pattern") == [
        Score("saga", candidates=0, true_positives=0, tc_labels=1, found=0)
    ]


def test_each_side_is_counted_in_its_own_category():
    """If a rule files 'gateway' under modularity but the labels say abstraction,
    the candidate counts in modularity's precision and the label in abstraction's recall."""
    result = match([cand(category="modularity")], [lbl(category="abstraction")])
    assert score_by(result, "category") == [
        Score("abstraction", candidates=0, true_positives=0, tc_labels=1, found=1),
        Score("modularity", candidates=1, true_positives=1, tc_labels=0, found=0),
    ]


# -------------------------------------------------------------- one worked example
#
# Two categories, three patterns. Every row says what should happen and why.
#
#   label  pattern        place                        is_tc
#   L1     gateway        orders  PayGateway.java 10-20  true
#   L2     gateway        billing PayGateway.java 10-20  true   <- nobody finds it
#   L3     adapter        orders  Adapter.java (file)    true
#   L4     feature-flags  orders  app.yml (file)         true
#   L5     feature-flags  orders  other.yml (file)       false
#
#   cand   pattern        place                         result
#   C1     gateway        orders  PayGateway.java 12-18 TP (L1, shares 7 lines)
#   C2     gateway        orders  PayGateway.java 15-25 FP (L1 already taken by C1)
#   C3     adapter        orders  Adapter.java (file)   TP (L3)
#   C4     feature-flags  orders  app.yml (file)        TP (L4)
#   C5     feature-flags  orders  other.yml (file)      FP (L5 is judged false)
#   C6     feature-flags  orders  new.yml (file)        FP (nobody labelled it)

FLAGS = {"pattern": "feature-flags", "category": "configurability", **WHOLE_FILE}
ADAPTER = {"pattern": "adapter", "file": "src/Adapter.java", **WHOLE_FILE}


def worked_example():
    labels = [
        lbl(),  # L1
        lbl(service="billing"),  # L2
        lbl(**ADAPTER),  # L3
        lbl(**FLAGS, file="config/app.yml"),  # L4
        lbl(**FLAGS, file="config/other.yml", is_tc=False),  # L5
    ]
    candidates = [
        cand(line_start=12, line_end=18),  # C1
        cand(line_start=15, line_end=25),  # C2
        cand(**ADAPTER),  # C3
        cand(**FLAGS, file="config/app.yml"),  # C4
        cand(**FLAGS, file="config/other.yml"),  # C5
        cand(**FLAGS, file="config/new.yml"),  # C6
    ]
    return match(candidates, labels)


def test_worked_example_per_pattern():
    """Sorted by name; each pattern only sees its own candidates and labels."""
    scores = score_by(worked_example(), "pattern")
    assert scores == [
        Score("adapter", candidates=1, true_positives=1, tc_labels=1, found=1),  # C3; L3
        Score("feature-flags", candidates=3, true_positives=1, tc_labels=1, found=1),  # C4-6; L4
        Score("gateway", candidates=2, true_positives=1, tc_labels=2, found=1),  # C1-2; L1-2
    ]
    adapter, flags, gateway = scores
    assert (adapter.precision, adapter.recall) == (1.0, 1.0)
    assert (flags.precision, flags.recall) == (pytest.approx(1 / 3), 1.0)
    assert (gateway.precision, gateway.recall) == (0.5, 0.5)


def test_worked_example_per_category():
    """gateway and adapter add up into abstraction; feature-flags is configurability."""
    abstraction, configurability = score_by(worked_example(), "category")
    assert abstraction == Score("abstraction", candidates=3, true_positives=2, tc_labels=3, found=2)
    assert configurability == Score(
        "configurability", candidates=3, true_positives=1, tc_labels=1, found=1
    )
    assert abstraction.precision == pytest.approx(2 / 3)
    assert abstraction.recall == pytest.approx(2 / 3)


def test_worked_example_overall():
    """6 candidates, 3 true positives; 4 real credits, 3 found."""
    score = score_overall(worked_example())
    assert score == Score("all", candidates=6, true_positives=3, tc_labels=4, found=3)
    assert (score.false_positives, score.missed) == (3, 1)
    assert (score.precision, score.recall) == (0.5, 0.75)
