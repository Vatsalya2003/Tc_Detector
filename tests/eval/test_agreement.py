"""Tests for agreement.py: drawing the sample, the blind worksheet, merging, and the commands."""

import json
import random
import re
from pathlib import Path

import pytest

from tc_detector.contracts.label import load_labels, save_labels
from tc_detector.eval.agreement import (
    OWNER,
    ROW_KEYS,
    SECOND_LABELLER,
    draw_sample,
    format_agreement,
    main,
    make_worksheet,
    merge,
)
from tc_detector.eval.kappa import original_answers
from tests.eval.examples import WHOLE_FILE, lbl

DTO = {"pattern": "immutable-data-contracts", "category": "api-stability", **WHOLE_FILE}
SAGA = {"pattern": "saga", "category": "modularity"}


def gateways(count: int):
    """`count` gateway labels by C (the primary for D's patterns), each on its own line."""
    return [lbl(labeller="C", line_start=n, line_end=n) for n in range(1, count + 1)]


def dtos(count: int):
    """`count` immutable-data-contracts labels by A (the primary for B's patterns)."""
    return [lbl(**DTO, labeller="A", file=f"Dto{n}.java") for n in range(1, count + 1)]


# ------------------------------------------------------------ draw_sample()


def test_sample_is_20_percent_of_each_pattern_rounded_up():
    labels = [*gateways(10), *dtos(6), lbl(**SAGA, labeller="B")]
    picked = draw_sample(labels, seed=1)
    per_pattern = {p: sum(1 for x in picked if x.pattern == p) for p in {x.pattern for x in labels}}
    # 10 -> 2, 6 -> 2 (1.2 rounded up), 1 -> 1 (a single label is still checked)
    assert per_pattern == {"gateway": 2, "immutable-data-contracts": 2, "saga": 1}


def test_same_seed_same_sample_whatever_the_order_in_the_file():
    labels = [*gateways(10), *dtos(6)]
    shuffled = labels[:]
    random.Random(99).shuffle(shuffled)
    assert draw_sample(shuffled, seed=7) == draw_sample(labels, seed=7)


def test_a_different_seed_picks_differently():
    labels = gateways(10)
    assert draw_sample(labels, seed=1) != draw_sample(labels, seed=2)


def test_the_sample_for_a_seed_never_changes():
    """Pinned: if a Python upgrade changed this, an already-drawn sample couldn't be redrawn."""
    picked = draw_sample(gateways(10), seed=6510)
    assert [x.line_start for x in picked] == [1, 7]


def test_more_labels_for_one_pattern_leave_another_patterns_sample_alone():
    before = draw_sample([*gateways(10), *dtos(6)], seed=3)
    after = draw_sample([*gateways(10), *dtos(11)], seed=3)
    assert [x for x in before if x.pattern == "gateway"] == [
        x for x in after if x.pattern == "gateway"
    ]


# ------------------------------------------------------------ make_worksheet()


def test_the_worksheet_is_blind():
    """Where to look and who looks, never the first labeller's answer or notes."""
    labels = [lbl(labeller="C", notes="routes everything")]
    row = make_worksheet(labels, seed=1)["rows"][0]
    assert tuple(row) == ROW_KEYS
    assert "is_tc" not in row and "notes" not in row
    assert (row["second_is_tc"], row["adjudicated_by"], row["final_is_tc"]) == (None, None, None)


def test_the_worksheet_names_the_second_labeller_from_the_guidelines():
    worksheet = make_worksheet([*gateways(1), *dtos(1), lbl(pattern="made-up")], seed=1)
    who = {row["pattern"]: row["second_labeller"] for row in worksheet["rows"]}
    # gateway is D's: second B. immutable-data-contracts is B's: second D. Unknown: nobody.
    assert who == {"gateway": "B", "immutable-data-contracts": "D", "made-up": None}


def test_each_persons_rows_are_together():
    # Second labellers: D for the DTOs, B for the gateways, A for the saga.
    worksheet = make_worksheet([*dtos(10), *gateways(10), lbl(**SAGA, labeller="B")], seed=1)
    people = [row["second_labeller"] for row in worksheet["rows"]]
    assert people == ["A", "B", "B", "D", "D"]


def test_the_worksheet_records_repo_commit_and_seed():
    worksheet = make_worksheet(gateways(1), seed=42)
    assert {k: worksheet[k] for k in ("repo", "commit", "seed", "percent")} == {
        "repo": "toy-shop",
        "commit": "abc123",
        "seed": 42,
        "percent": 20,
    }


def test_no_labels_means_nothing_to_sample():
    with pytest.raises(ValueError, match="no labels"):
        make_worksheet([], seed=1)


# ------------------------------------------------------------ merge()

# One gateway label (first labeller C said true) and one DTO label (first labeller A said
# true). Each pattern has one label, so both are in the sample.
GATEWAY, DTO_LABEL = gateways(1)[0], dtos(1)[0]
LABELS = [GATEWAY, DTO_LABEL]


def filled(answers: dict[str, dict]) -> dict:
    """The worksheet for LABELS, with some rows filled in, keyed by pattern."""
    worksheet = make_worksheet(LABELS, seed=1)
    for row in worksheet["rows"]:
        row.update(answers.get(row["pattern"], {}))
    return worksheet


def merged_label(result, original):
    """The label in a merge result with the same id as `original`."""
    return next(x for x in result.labels if x.label_id == original.label_id)


def test_an_agreeing_answer_is_copied_in():
    result = merge(LABELS, filled({"gateway": {"second_is_tc": True}}))
    new = merged_label(result, GATEWAY)
    assert (new.is_tc, new.second_labeller, new.second_is_tc, new.adjudicated_by) == (
        True,
        "B",
        True,
        None,
    )
    assert (result.merged, result.unanswered, result.unsettled, result.changed) == (1, 1, [], [])


def test_unanswered_rows_leave_their_labels_alone():
    result = merge(LABELS, filled({}))
    assert result.labels == LABELS
    assert (result.merged, result.unanswered) == (0, 2)


def test_an_unsettled_disagreement_is_listed_and_not_copied():
    result = merge(LABELS, filled({"gateway": {"second_is_tc": False}}))
    assert result.unsettled == [
        f"{GATEWAY.label_id}: first labeller C said true, second labeller B said false"
    ]
    assert merged_label(result, GATEWAY) == GATEWAY


def test_a_settled_disagreement_takes_the_final_answer_and_goes_in_the_change_log():
    settled = {"second_is_tc": False, "adjudicated_by": "A", "final_is_tc": False}
    result = merge(LABELS, filled({"gateway": settled}))
    new = merged_label(result, GATEWAY)
    assert (new.is_tc, new.second_is_tc, new.adjudicated_by) == (False, False, "A")
    assert result.changed == [f"{GATEWAY.label_id}: is_tc true -> false, settled by A"]


def test_a_disagreement_settled_for_the_first_labeller_changes_nothing_to_log():
    settled = {"second_is_tc": False, "adjudicated_by": "A", "final_is_tc": True}
    result = merge(LABELS, filled({"gateway": settled}))
    assert merged_label(result, GATEWAY).is_tc is True
    assert result.changed == []


def test_kappa_still_sees_both_original_answers_after_an_overturn():
    settled = {"second_is_tc": False, "adjudicated_by": "A", "final_is_tc": False}
    new = merged_label(merge(LABELS, filled({"gateway": settled})), GATEWAY)
    assert original_answers(new) == (True, False)


def test_merging_twice_gives_the_same_labels():
    worksheet = filled(
        {
            "gateway": {"second_is_tc": False, "adjudicated_by": "A", "final_is_tc": False},
            "immutable-data-contracts": {"second_is_tc": True},
        }
    )
    once = merge(LABELS, worksheet)
    twice = merge(once.labels, worksheet)
    assert twice.labels == once.labels
    assert twice.changed == []  # already logged the first time


@pytest.mark.parametrize(
    "answers",
    [
        {"second_labeller": "D", "second_is_tc": True},  # D owns gateway
        {"second_is_tc": False, "adjudicated_by": "D", "final_is_tc": True},
    ],
)
def test_the_owner_can_neither_label_nor_settle_their_pattern(answers):
    with pytest.raises(ValueError, match="D owns gateway"):
        merge(LABELS, filled({"gateway": answers}))


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({"second_is_tc": "yes"}, "second_is_tc must be true or false"),
        ({"second_is_tc": True, "second_labeller": "E"}, "second_labeller must be one of"),
        ({"second_is_tc": True, "second_labeller": None}, "second_labeller must be one of"),
        ({"adjudicated_by": "A"}, "fill in second_is_tc before"),
        ({"second_is_tc": True, "final_is_tc": True}, "both labellers agree"),
        ({"second_is_tc": False, "adjudicated_by": "A", "final_is_tc": 0}, "final_is_tc must"),
    ],
)
def test_badly_filled_rows_are_rejected_with_their_row_number(answers, message):
    with pytest.raises(ValueError, match=rf"worksheet row 1: .*{message}"):
        merge(LABELS, filled({"gateway": answers}))


def test_a_worksheet_from_another_commit_is_rejected():
    worksheet = filled({})
    worksheet["commit"] = "def456"
    with pytest.raises(ValueError, match="different repo or commit"):
        merge(LABELS, worksheet)


def test_a_row_for_a_label_that_is_gone_is_rejected():
    with pytest.raises(ValueError, match="not in the label file"):
        merge([GATEWAY], make_worksheet(LABELS, seed=1))


def test_a_label_listed_twice_is_rejected():
    worksheet = filled({})
    worksheet["rows"].append(dict(worksheet["rows"][0]))
    with pytest.raises(ValueError, match="lists these labels twice"):
        merge(LABELS, worksheet)


def test_a_row_with_extra_or_missing_keys_is_rejected():
    worksheet = filled({})
    worksheet["rows"][0]["is_tc"] = True
    with pytest.raises(ValueError, match="row 1: a row must have exactly these keys"):
        merge(LABELS, worksheet)


def test_a_worksheet_with_the_wrong_shape_is_rejected():
    with pytest.raises(ValueError, match="a worksheet must be an object"):
        merge(LABELS, {"rows": []})


# ------------------------------------------------------------ format_agreement()


def test_printed_tables_look_like_this():
    labels = [
        lbl(is_tc=True, second_labeller="B", second_is_tc=True),
        lbl(**DTO, file="A.java", is_tc=True, second_labeller="D", second_is_tc=True),
        lbl(
            **DTO,
            file="B.java",
            is_tc=True,
            second_labeller="D",
            second_is_tc=False,
            adjudicated_by="C",
        ),
        lbl(**DTO, file="C.java"),  # not in the sample
    ]
    assert format_agreement(labels) == (
        "Overall\n"
        "group  sampled  agreed  agreement  kappa\n"
        "all          3       2       0.67   0.00\n"
        "\n"
        "By pattern\n"
        "group                     sampled  agreed  agreement  kappa\n"
        "gateway                         1       1       1.00    n/a\n"
        "immutable-data-contracts        2       1       0.50   0.00\n"
        "\n"
        "By category\n"
        "group          sampled  agreed  agreement  kappa\n"
        "abstraction          1       1       1.00    n/a\n"
        "api-stability        2       1       0.50   0.00\n"
        "\n"
        "n/a: nothing was sampled, or both labellers gave the same answer to every label in "
        "that group, so kappa can't be computed (see kappa.py)."
    )


def test_no_footnote_when_every_kappa_exists():
    labels = [
        lbl(is_tc=True, second_labeller="B", second_is_tc=True),
        lbl(line_start=30, line_end=40, is_tc=False, second_labeller="B", second_is_tc=False),
    ]
    assert "n/a" not in format_agreement(labels)


# ------------------------------------------------------------ the command line


def test_sample_merge_kappa_end_to_end(tmp_path, capsys):
    labels_path = tmp_path / "labels.json"
    worksheet_path = tmp_path / "worksheet.json"
    save_labels(labels_path, LABELS)

    main(["sample", "--labels", str(labels_path), "--seed", "1", "--out", str(worksheet_path)])
    assert "Sampled 2 of 2 labels with seed 1" in capsys.readouterr().out

    worksheet = json.loads(worksheet_path.read_text())
    for row in worksheet["rows"]:
        row["second_is_tc"] = True
    worksheet_path.write_text(json.dumps(worksheet))
    main(["merge", "--labels", str(labels_path), "--worksheet", str(worksheet_path)])
    assert "Merged 2 answers" in capsys.readouterr().out
    assert all(x.second_is_tc is True for x in load_labels(labels_path))

    main(["kappa", "--labels", str(labels_path)])
    assert "all          2       2       1.00    n/a" in capsys.readouterr().out


def test_sample_never_overwrites_a_worksheet(tmp_path):
    labels_path = tmp_path / "labels.json"
    save_labels(labels_path, LABELS)
    existing = tmp_path / "worksheet.json"
    existing.write_text("answers already here")
    with pytest.raises(SystemExit, match="already exists"):
        main(["sample", "--labels", str(labels_path), "--seed", "1", "--out", str(existing)])
    assert existing.read_text() == "answers already here"


def test_merge_with_an_unsettled_disagreement_writes_nothing(tmp_path):
    labels_path = tmp_path / "labels.json"
    save_labels(labels_path, LABELS)
    before = labels_path.read_text()
    worksheet_path = tmp_path / "worksheet.json"
    worksheet_path.write_text(json.dumps(filled({"gateway": {"second_is_tc": False}})))
    with pytest.raises(SystemExit, match="settle these disagreements first"):
        main(["merge", "--labels", str(labels_path), "--worksheet", str(worksheet_path)])
    assert labels_path.read_text() == before


def test_a_missing_file_gives_a_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="error: "):
        main(["kappa", "--labels", str(tmp_path / "nope.json")])


# ------------------------------------------------------------ GUIDELINES.md


def test_owner_and_second_labeller_tables_match_the_guidelines():
    """OWNER and SECOND_LABELLER are copies of two GUIDELINES.md tables; keep them in step."""
    guidelines = Path(__file__).parents[2] / "ground_truth" / "GUIDELINES.md"
    text = guidelines.read_text(encoding="utf-8")
    # "| `gateway` | abstraction | D | service |"
    owners = dict(re.findall(r"^\| `([a-z-]+)` \| [a-z-]+ \| ([ABCD]) \|", text, re.MULTILINE))
    # "| A (Vatsalya) | D | C | B |": owner, primary, second, tie-break
    seconds = dict(
        re.findall(r"^\| ([ABCD]) \(\w+\) \| [ABCD] \| ([ABCD]) \| [ABCD] \|", text, re.MULTILINE)
    )
    assert owners == OWNER
    assert seconds == SECOND_LABELLER
