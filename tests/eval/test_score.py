"""Tests for score.py: loading candidate files, the printed report, and the command line."""

import json

import pytest

from tc_detector.contracts.label import save_labels
from tc_detector.eval.score import evaluate, format_report, load_candidates, main
from tests.eval.examples import WHOLE_FILE, cand, lbl

FLAGS = {"pattern": "feature-flags", "category": "configurability", **WHOLE_FILE}

# A small run: one hit, one candidate where nothing was labelled, one candidate on a
# label judged false, and one real credit (in the billing service) nobody found.
CANDIDATES = [
    cand(line_start=12, line_end=18),  # TP: shares lines 12-18 with the orders label
    cand(line_start=40, line_end=45),  # FP: nothing labelled there
    cand(**FLAGS, file="config/app.yml"),  # FP: humans said is_tc=false
]
LABELS = [
    lbl(),  # found
    lbl(service="billing"),  # missed
    lbl(**FLAGS, file="config/app.yml", is_tc=False),  # never counts toward recall
]

EXPECTED_REPORT = """\
Overall
group  candidates    TP    FP  TC labels  found  precision  recall
all             3     1     2          2      1       0.33    0.50

By pattern
group          candidates    TP    FP  TC labels  found  precision  recall
feature-flags           1     0     1          0      0       0.00     n/a
gateway                 2     1     1          2      1       0.50    0.50

By category
group            candidates    TP    FP  TC labels  found  precision  recall
abstraction               2     1     1          2      1       0.50    0.50
configurability           1     0     1          0      0       0.00     n/a"""


def write_candidates(path, candidates):
    """Save candidates the way the rules print them: one JSON object per line."""
    path.write_text("".join(c.to_json() + "\n" for c in candidates))
    return path


# ------------------------------------------------------------ load_candidates()


def test_candidates_file_round_trip(tmp_path):
    """Saving then loading gives back the same candidates."""
    path = write_candidates(tmp_path / "run.jsonl", CANDIDATES)
    assert load_candidates(path) == CANDIDATES


def test_blank_lines_are_skipped(tmp_path):
    """A trailing newline or an empty line between candidates is fine."""
    path = tmp_path / "run.jsonl"
    path.write_text(f"\n{cand().to_json()}\n\n   \n")
    assert load_candidates(path) == [cand()]


def test_an_empty_file_means_no_candidates(tmp_path):
    """A rule that found nothing prints nothing; that's a valid, empty run."""
    path = tmp_path / "run.jsonl"
    path.write_text("")
    assert load_candidates(path) == []


def test_error_names_the_broken_line(tmp_path):
    """A bad candidate in a long results file is easy to find (lines count from 1)."""
    path = tmp_path / "run.jsonl"
    bad = {**cand().to_dict(), "unit": "lines"}
    path.write_text(cand().to_json() + "\n" + json.dumps(bad) + "\n")
    with pytest.raises(ValueError, match="line 2"):
        load_candidates(path)


def test_a_line_that_is_not_json_names_the_line(tmp_path):
    """A half-written or hand-edited line gets a clear message, not a traceback."""
    path = tmp_path / "run.jsonl"
    path.write_text(cand().to_json() + "\n{oops\n")
    with pytest.raises(ValueError, match="line 2: not valid JSON"):
        load_candidates(path)


def test_an_old_style_json_list_gets_a_clear_message(tmp_path):
    """One big JSON list is the label format, not the candidates format."""
    path = tmp_path / "run.json"
    path.write_text(json.dumps([cand().to_dict()]))
    with pytest.raises(ValueError, match="line 1: must be one candidate object"):
        load_candidates(path)


# ------------------------------------------------------ evaluate() and the report


def test_report_has_overall_pattern_and_category_scores():
    """evaluate() returns all three views of the same run."""
    report = evaluate(CANDIDATES, LABELS)
    assert report.overall.group == "all"
    assert [s.group for s in report.by_pattern] == ["feature-flags", "gateway"]
    assert [s.group for s in report.by_category] == ["abstraction", "configurability"]


def test_printed_report_looks_like_this():
    """Pins the exact output, so any change to the tables shows up in review."""
    assert format_report(evaluate(CANDIDATES, LABELS)) == EXPECTED_REPORT


def test_report_with_nothing_to_score():
    """No candidates and no labels: empty tables, not a crash."""
    text = format_report(evaluate([], []))
    assert "By pattern\ngroup" in text
    assert "all             0     0     0          0      0        n/a     n/a" in text


# ------------------------------------------------------------- the command line


def test_main_prints_the_report(tmp_path, capsys):
    """The script reads real files and prints the same report."""
    cands = write_candidates(tmp_path / "run.jsonl", CANDIDATES)
    labels = tmp_path / "labels.json"
    save_labels(labels, LABELS)
    main(["--candidates", str(cands), "--labels", str(labels)])
    assert capsys.readouterr().out == EXPECTED_REPORT + "\n"


def test_main_reads_several_candidate_files(tmp_path, capsys):
    """Candidates split across files (e.g. one per rule area) are scored together."""
    first = write_candidates(tmp_path / "a.jsonl", CANDIDATES[:1])
    second = write_candidates(tmp_path / "b.jsonl", CANDIDATES[1:])
    labels = tmp_path / "labels.json"
    save_labels(labels, LABELS)
    main(["--candidates", str(first), str(second), "--labels", str(labels)])
    assert capsys.readouterr().out == EXPECTED_REPORT + "\n"


def test_main_stops_with_a_clear_message_for_a_broken_file(tmp_path):
    """A bad file gives one readable line and a non-zero exit, not a traceback."""
    cands = tmp_path / "run.jsonl"
    cands.write_text(json.dumps({"repo": "toy-shop"}) + "\n")
    labels = tmp_path / "labels.json"
    save_labels(labels, LABELS)
    with pytest.raises(SystemExit) as stopped:
        main(["--candidates", str(cands), "--labels", str(labels)])
    assert "line 1: bad candidate keys" in str(stopped.value.code)
