"""Tests for report.py: reading cost logs and verdicts, the numbers per repo, the table.

Every input is a tiny made-up file or list; nothing here calls Claude.
"""

import json

import pytest

from tc_detector.contracts.label import save_labels
from tc_detector.eval.report import (
    build_report,
    count_confirmed,
    format_report,
    load_cost_log,
    load_verdicts,
    main,
    repo_of,
)
from tc_detector.llm.costlog import summarize
from tests.eval.examples import WHOLE_SERVICE, cand, lbl

# Two repos. In toy-shop, Claude was asked about the gateway twice (the second answer came
# from the cache) and refused a second candidate. In toy-bank it saw one candidate once.
SHOP_HIT = cand()  # lines 10-20: matches the toy-shop label
SHOP_MISS = cand(line_start=40, line_end=45)  # nothing labelled there
BANK = cand(repo="toy-bank")


def call(candidate, **changes):
    """One cost log row, shaped like the rows the Claude wrapper writes for an API call."""
    row = {
        "ts": "2026-11-20T12:00:00+00:00",
        "candidate_id": candidate.id,
        "kind": "stage3",
        "requested_model": "claude-sonnet-5-5",
        "prompt_version": "stage3-v1",
        "effort": "medium",
        "repeat": 0,
        "cache_key": "made-up",
        "model": "claude-sonnet-5-5",
        "cache_hit": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cost_usd": 0.0,
        "error": None,
        "stop_reason": "end_turn",
        "request_id": "req_made_up",
    }
    return {**row, **changes}


def cache_hit(candidate, saved_usd):
    """A cost log row for an answer the response cache served: free, with saved_usd."""
    row = call(candidate, cache_hit=True, saved_usd=saved_usd)
    del row["stop_reason"], row["request_id"]
    return row


def verdict(candidate, is_tc, repeat=0):
    """The fields of a `tc-attribute --out` verdict that the report reads."""
    return {"candidate_id": candidate.id, "is_tc": is_tc, "repeat": repeat}


COST_LOG = [
    call(
        SHOP_HIT, input_tokens=1000, output_tokens=200, cache_read_input_tokens=800, cost_usd=0.005
    ),
    cache_hit(SHOP_HIT, saved_usd=0.005),
    call(SHOP_MISS, input_tokens=900, cost_usd=0.001, error="refusal", stop_reason="refusal"),
    call(
        BANK, input_tokens=1200, output_tokens=300, cache_creation_input_tokens=826, cost_usd=0.008
    ),
]
# The refused call has no answer (is_tc null); Claude rejected the toy-bank candidate.
VERDICTS = [verdict(SHOP_HIT, True), verdict(SHOP_MISS, None), verdict(BANK, False)]
CANDIDATES = [SHOP_HIT, SHOP_MISS, BANK]
SHOP_LABELS = [lbl()]  # real credit, found
BANK_LABELS = [lbl(repo="toy-bank", is_tc=False)]  # judged absent: never counts for recall

EXPECTED_TABLE = """\
|                           |   toy-bank |   toy-shop |
|---------------------------|-----------:|-----------:|
| Claude calls              |          1 |          3 |
| API calls                 |          1 |          2 |
| Cache hits                |          0 |          1 |
| Failed calls              |          0 |          1 |
| Input tokens              |      1,200 |      1,900 |
| Output tokens             |        300 |        200 |
| Cache read tokens         |          0 |        800 |
| Cache write tokens        |        826 |          0 |
| Spent (USD)               |  $0.008000 |  $0.006000 |
| Saved by cache (USD)      |  $0.000000 |  $0.005000 |
| Candidates sent to Claude |          1 |          2 |
| Cost per candidate (USD)  |  $0.008000 |  $0.003000 |
| Confirmed by Claude       |          0 |          1 |
| Cost per confirmed (USD)  |        n/a |  $0.006000 |
| Precision                 | 0.00 (0/1) | 0.50 (1/2) |
| Recall                    |        n/a | 1.00 (1/1) |"""


def full_report():
    """The report with every input given."""
    return build_report(COST_LOG, VERDICTS, CANDIDATES, SHOP_LABELS + BANK_LABELS)


def by_repo(reports):
    return {r.repo: r for r in reports}


def write_jsonl(path, rows):
    """Save rows the way the cost log and verdict files are written: one object per line."""
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


# ------------------------------------------------------------------- repo_of()


def test_the_repo_is_the_first_part_of_a_candidate_id():
    assert repo_of(BANK.id) == "toy-bank"
    # A service-unit id has "-" for the file; the repo still comes first.
    assert repo_of(cand(**WHOLE_SERVICE).id) == "toy-shop"


# ---------------------------------------------------------- reading the files


def test_cost_log_round_trip(tmp_path):
    """Writing rows then loading them gives back the same rows."""
    assert load_cost_log(write_jsonl(tmp_path / "cost.jsonl", COST_LOG)) == COST_LOG


def test_blank_lines_are_skipped(tmp_path):
    path = tmp_path / "cost.jsonl"
    path.write_text("\n" + json.dumps(COST_LOG[0]) + "\n\n   \n")
    assert load_cost_log(path) == COST_LOG[:1]


def test_a_line_that_is_not_json_names_the_line(tmp_path):
    """A half-written last line (e.g. a run killed mid-write) is easy to find."""
    path = tmp_path / "cost.jsonl"
    path.write_text(json.dumps(COST_LOG[0]) + "\n{oops\n")
    with pytest.raises(ValueError, match="line 2: not valid JSON"):
        load_cost_log(path)


@pytest.mark.parametrize(
    "line",
    [
        pytest.param(json.dumps(COST_LOG), id="a JSON list"),
        pytest.param(json.dumps({"cost_usd": 0.1}), id="no candidate_id"),
        pytest.param(json.dumps({"candidate_id": ""}), id="empty candidate_id"),
    ],
)
def test_a_row_must_be_an_object_with_a_candidate_id(tmp_path, line):
    """Without a candidate_id a row can't be put under a repo."""
    path = tmp_path / "cost.jsonl"
    path.write_text(line + "\n")
    with pytest.raises(ValueError, match="line 1"):
        load_cost_log(path)


def test_verdicts_load_including_failed_calls(tmp_path):
    """A failed call's verdict has is_tc null; that is a valid row."""
    assert load_verdicts(write_jsonl(tmp_path / "v.jsonl", VERDICTS)) == VERDICTS


@pytest.mark.parametrize("is_tc", ["yes", 1, "missing"])
def test_a_verdict_needs_a_true_false_or_null_is_tc(tmp_path, is_tc):
    """1 is not True here: a typo in a hand-edited file should fail, not count as a yes."""
    row = verdict(SHOP_HIT, is_tc)
    if is_tc == "missing":
        del row["is_tc"]
    path = write_jsonl(tmp_path / "v.jsonl", [verdict(BANK, False), row])
    with pytest.raises(ValueError, match="line 2: is_tc must be true, false or null"):
        load_verdicts(path)


# --------------------------------------------------------- the cost numbers


def test_cost_totals_for_one_repo():
    shop = by_repo(build_report(COST_LOG))["toy-shop"]
    assert (shop.calls, shop.api_calls, shop.cache_hits, shop.failed_calls) == (3, 2, 1, 1)
    assert (shop.input_tokens, shop.output_tokens) == (1900, 200)
    assert (shop.cache_read_input_tokens, shop.cache_creation_input_tokens) == (800, 0)
    assert shop.cost_usd == pytest.approx(0.006)
    assert shop.saved_usd == pytest.approx(0.005)


def test_repos_add_up_to_the_wrappers_own_summary(tmp_path):
    """Summed over repos, the report agrees with summarize() in llm/costlog.py."""
    path = write_jsonl(tmp_path / "cost.jsonl", COST_LOG)
    reports = build_report(load_cost_log(path))
    totals = summarize(path)
    for name, expected in totals.items():
        assert sum(getattr(r, name) for r in reports) == pytest.approx(expected), name


def test_each_candidate_is_counted_once_however_many_calls_it_took():
    """A cache hit, a repeat and an ADR call are still the same candidate, but all cost."""
    log = [
        *COST_LOG,
        call(SHOP_HIT, kind="adr", cost_usd=0.002),
        call(SHOP_HIT, repeat=1, cost_usd=0.004),
    ]
    shop = by_repo(build_report(log))["toy-shop"]
    assert shop.candidates == 2
    assert shop.cost_usd == pytest.approx(0.012)
    assert shop.cost_per_candidate == pytest.approx(0.006)


def test_cost_per_candidate_and_per_confirmed():
    reports = by_repo(full_report())
    assert reports["toy-shop"].cost_per_candidate == pytest.approx(0.003)
    assert reports["toy-shop"].cost_per_confirmed == pytest.approx(0.006)
    # Claude confirmed nothing in toy-bank, so there is nothing to divide by.
    assert reports["toy-bank"].confirmed == 0
    assert reports["toy-bank"].cost_per_confirmed is None


def test_without_verdicts_or_labels_those_numbers_are_none():
    """None means "not given", which the table shows by leaving the rows out."""
    for report in build_report(COST_LOG):
        assert report.confirmed is None
        assert report.cost_per_confirmed is None
        assert report.score is None


# ------------------------------------------------------------ count_confirmed()


@pytest.mark.parametrize(
    ("answers", "confirmed"),
    [
        pytest.param([True], 1, id="one yes"),
        pytest.param([False], 0, id="one no"),
        pytest.param([None], 0, id="one failed call"),
        pytest.param([True, True, False], 1, id="2 of 3 repeats say yes"),
        pytest.param([True, False], 0, id="a tie is not confirmed"),
        pytest.param([True, None, None], 0, id="failed calls are not yes votes"),
    ],
)
def test_a_candidate_is_confirmed_when_most_of_its_verdicts_say_yes(answers, confirmed):
    verdicts = [verdict(SHOP_HIT, is_tc, repeat=i) for i, is_tc in enumerate(answers)]
    assert count_confirmed(verdicts) == confirmed


def test_confirmed_counts_candidates_not_verdicts():
    verdicts = [verdict(SHOP_HIT, True, repeat=0), verdict(SHOP_HIT, True, repeat=1)]
    assert count_confirmed([*verdicts, verdict(SHOP_MISS, True)]) == 2


# ------------------------------------------------------- precision and recall


def test_each_repo_is_scored_only_against_its_own_labels():
    reports = by_repo(full_report())
    shop, bank = reports["toy-shop"].score, reports["toy-bank"].score
    assert (shop.precision, shop.recall) == (0.5, 1.0)
    # toy-bank's only label was judged absent, so its candidate is a false positive.
    assert (bank.precision, bank.recall) == (0.0, None)


def test_a_repo_with_only_labels_still_gets_a_column():
    """Labelled credit that nothing was sent to Claude for shows up as missed, at no cost."""
    cafe_label = lbl(repo="toy-cafe")
    cafe = by_repo(build_report(COST_LOG, None, CANDIDATES, [cafe_label]))["toy-cafe"]
    assert (cafe.calls, cafe.candidates, cafe.cost_per_candidate) == (0, 0, None)
    assert (cafe.score.tc_labels, cafe.score.found) == (1, 0)


def test_candidates_and_labels_go_together():
    with pytest.raises(ValueError, match="together"):
        build_report(COST_LOG, candidates=CANDIDATES)
    with pytest.raises(ValueError, match="together"):
        build_report(COST_LOG, labels=SHOP_LABELS)


# ------------------------------------------------------------------ the table


def test_printed_table_looks_like_this():
    """Pins the exact output, so any change to the table shows up in review."""
    assert format_report(full_report()) == EXPECTED_TABLE


def test_rows_that_need_verdicts_or_labels_are_left_out_without_them():
    text = format_report(build_report(COST_LOG))
    assert "Cost per candidate (USD)" in text
    for name in ("Confirmed by Claude", "Cost per confirmed", "Precision", "Recall"):
        assert name not in text


def test_every_line_of_the_table_has_the_same_columns():
    """A Markdown table breaks if a row has more or fewer cells than the header."""
    lines = format_report(full_report()).splitlines()
    assert {line.count("|") for line in lines} == {4}
    assert all(line.startswith("|") and line.endswith("|") for line in lines)


def test_nothing_to_report():
    assert format_report(build_report([])) == "Nothing to report: the inputs name no repo."


# ------------------------------------------------------------- the command line


def write_inputs(tmp_path):
    """Every input as a file, the way the pipeline leaves them in results/ and ground_truth/."""
    shop_labels, bank_labels = tmp_path / "shop.json", tmp_path / "bank.json"
    save_labels(shop_labels, SHOP_LABELS)
    save_labels(bank_labels, BANK_LABELS)
    return {
        "cost": write_jsonl(tmp_path / "cost.jsonl", COST_LOG),
        "verdicts": write_jsonl(tmp_path / "verdicts.jsonl", VERDICTS),
        "candidates": write_jsonl(tmp_path / "cands.jsonl", [c.to_dict() for c in CANDIDATES]),
        "labels": [shop_labels, bank_labels],
    }


def test_main_prints_the_table(tmp_path, capsys):
    files = write_inputs(tmp_path)
    main(
        [
            *("--cost-log", str(files["cost"])),
            *("--verdicts", str(files["verdicts"])),
            *("--candidates", str(files["candidates"])),
            *("--labels", *map(str, files["labels"])),
        ]
    )
    assert capsys.readouterr().out == EXPECTED_TABLE + "\n"


def test_main_adds_several_cost_logs_together(tmp_path, capsys):
    """Logs split across runs (e.g. one per rule area) give the same totals as one log."""
    first = write_jsonl(tmp_path / "a.jsonl", COST_LOG[:2])
    second = write_jsonl(tmp_path / "b.jsonl", COST_LOG[2:])
    main(["--cost-log", str(first), str(second)])
    assert capsys.readouterr().out == format_report(build_report(COST_LOG)) + "\n"


def test_main_needs_labels_with_candidates(tmp_path, capsys):
    files = write_inputs(tmp_path)
    with pytest.raises(SystemExit) as stopped:
        main(["--cost-log", str(files["cost"]), "--candidates", str(files["candidates"])])
    assert stopped.value.code == 2  # argparse's usage-error exit code
    assert "--candidates and --labels go together" in capsys.readouterr().err


def test_main_stops_with_a_clear_message_for_a_broken_file(tmp_path):
    """A bad file gives one readable line and a non-zero exit, not a traceback."""
    path = tmp_path / "cost.jsonl"
    path.write_text('{"cost_usd": 0.1}\n')
    with pytest.raises(SystemExit) as stopped:
        main(["--cost-log", str(path)])
    assert "line 1: needs a candidate_id" in str(stopped.value.code)


def test_main_stops_with_a_clear_message_for_a_missing_file(tmp_path):
    with pytest.raises(SystemExit) as stopped:
        main(["--cost-log", str(tmp_path / "nope.jsonl")])
    assert str(stopped.value.code).startswith("error:")
