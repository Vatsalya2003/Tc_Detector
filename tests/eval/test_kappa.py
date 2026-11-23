"""Tests for kappa.py: recovering original answers, and agreement and kappa per group."""

import pytest

from tc_detector.eval.kappa import agreement_by, agreement_overall, original_answers
from tests.eval.examples import WHOLE_FILE, lbl

DTO = {"pattern": "immutable-data-contracts", "category": "api-stability", **WHOLE_FILE}


def sampled(first: bool, second: bool, **changes):
    """A label in the sample where the first labeller said `first` and the second `second`.

    On a disagreement, C settles it. The final is_tc is the first labeller's answer unless
    the test passes another one.
    """
    if first == second:
        return lbl(is_tc=first, second_labeller="B", second_is_tc=second, **changes)
    changes.setdefault("is_tc", first)
    return lbl(second_labeller="B", second_is_tc=second, adjudicated_by="C", **changes)


def many(first: bool, second: bool, count: int):
    """`count` sampled labels with the same pair of answers, each on its own lines."""
    return [sampled(first, second, line_start=n, line_end=n) for n in range(1, count + 1)]


# ------------------------------------------------------------ original_answers()


def test_a_label_outside_the_sample_has_no_answers():
    assert original_answers(lbl()) is None


def test_when_they_agreed_both_answers_are_is_tc():
    assert original_answers(sampled(True, True)) == (True, True)
    assert original_answers(sampled(False, False)) == (False, False)


def test_after_a_disagreement_the_first_answer_is_recovered_whatever_was_decided():
    """is_tc holds the settled answer, so the first labeller's is the opposite of the second's."""
    kept = sampled(True, False, is_tc=True)  # settled in the first labeller's favour
    overturned = sampled(True, False, is_tc=False)  # settled in the second labeller's favour
    assert original_answers(kept) == (True, False)
    assert original_answers(overturned) == (True, False)


# ------------------------------------------------------------ agreement and kappa


def test_worked_example():
    """The textbook example: 50 items, 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no.

    observed = 35/50 = 0.7. First says yes 25/50, second 30/50, so
    expected = 0.5 * 0.6 + 0.5 * 0.4 = 0.5, and kappa = (0.7 - 0.5) / (1 - 0.5) = 0.4.
    """
    labels = [
        *many(True, True, 20),
        *[sampled(True, False, line_start=100 + n, line_end=100 + n) for n in range(5)],
        *[sampled(False, True, line_start=200 + n, line_end=200 + n) for n in range(10)],
        *[sampled(False, False, line_start=300 + n, line_end=300 + n) for n in range(15)],
    ]
    result = agreement_overall(labels)
    assert (result.sampled, result.agreed, result.first_yes, result.second_yes) == (50, 35, 25, 30)
    assert result.observed == pytest.approx(0.7)
    assert result.expected == pytest.approx(0.5)
    assert result.kappa == pytest.approx(0.4)


def test_perfect_agreement_using_both_answers_is_kappa_1():
    no_no = sampled(False, False, line_start=50, line_end=50)
    result = agreement_overall([*many(True, True, 3), no_no])
    assert result.observed == 1.0
    assert result.kappa == 1.0


def test_everyone_saying_yes_to_everything_gives_no_kappa():
    """Expected agreement is 1, so kappa would divide by zero. Agreement is still shown."""
    result = agreement_overall(many(True, True, 4))
    assert result.observed == 1.0
    assert result.expected == 1.0
    assert result.kappa is None


def test_one_no_among_all_yes_gives_kappa_0_despite_75_percent_agreement():
    """Why kappa must be read next to agreement when nearly every label is a yes."""
    labels = [*many(True, True, 3), sampled(True, False, line_start=50, line_end=50)]
    result = agreement_overall(labels)
    assert result.observed == 0.75
    assert result.expected == 0.75
    assert result.kappa == 0.0


def test_always_disagreeing_is_worse_than_luck():
    labels = [sampled(True, False, line_start=1), sampled(False, True, line_start=2)]
    assert agreement_overall(labels).kappa == -1.0


def test_labels_outside_the_sample_are_ignored():
    result = agreement_overall([lbl(), lbl(line_start=30, line_end=40), sampled(True, True)])
    assert result.sampled == 1


def test_nothing_sampled_gives_none_not_a_crash():
    result = agreement_overall([lbl()])
    assert (result.sampled, result.observed, result.expected, result.kappa) == (0, None, None, None)


# ------------------------------------------------------------ agreement_by()


def test_one_row_per_sampled_pattern_and_category_sorted_by_name():
    labels = [
        *many(True, True, 2),  # gateway / abstraction
        sampled(True, False, **DTO, file="Dto.java"),
        lbl(pattern="saga", category="modularity"),  # not in the sample: no row
    ]
    by_pattern = agreement_by(labels, "pattern")
    assert [(a.group, a.sampled, a.agreed) for a in by_pattern] == [
        ("gateway", 2, 2),
        ("immutable-data-contracts", 1, 0),
    ]
    by_category = agreement_by(labels, "category")
    assert [a.group for a in by_category] == ["abstraction", "api-stability"]


def test_agreement_by_rejects_an_unknown_field():
    with pytest.raises(ValueError, match="field must be one of"):
        agreement_by([], "service")
