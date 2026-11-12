"""The validation rules: each function checks one part of a candidate and raises ValueError.

They catch a rule's mistake the moment it makes a bad candidate, not later in evaluation.
Read this file to learn every rule a candidate must follow. Read candidate.py next.
"""

# Lets us write the "Candidate" type hint without importing candidate.py when the
# program runs (candidate.py imports this file, so the reverse would be a loop).
from __future__ import annotations

from typing import TYPE_CHECKING

from tc_detector.contracts.enums import Unit
from tc_detector.contracts.ids import KEBAB_CASE, RULE_ID, SNIPPET_MAX_CHARS, build_id

if TYPE_CHECKING:  # only true for editors and type checkers, never at runtime
    from tc_detector.contracts.candidate import Candidate


def check_text_fields(c: Candidate) -> None:
    """Make sure the basic text fields are filled in and safe to put in an id."""
    # An empty repo, commit, etc. would make the candidate impossible to trace back.
    for name in ("repo", "commit", "service", "pattern", "rule_id"):
        value = getattr(c, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    # ":" separates the parts of the id, so a ":" inside a part would scramble it.
    for name in ("repo", "service", "pattern"):
        if ":" in getattr(c, name):
            raise ValueError(f"{name} must not contain ':' (used as id separator)")


def check_file(c: Candidate) -> None:
    """Make sure the file is present when needed and is a clean relative path."""
    if c.file is None:
        # A line range or file claim with no file has nothing to point at.
        if c.unit in (Unit.LINE_RANGE, Unit.FILE):
            raise ValueError(f"unit={c.unit} requires a file")
        return  # service units may leave file empty
    # An empty string is a sneaky "no file"; use None for that instead.
    if not isinstance(c.file, str) or not c.file:
        raise ValueError("file must be a non-empty string or None")
    # Each file must be written one way only, or the same file could get two ids.
    is_absolute = c.file.startswith("/")  # "/abs/x.java" isn't relative to the service
    has_backslash = "\\" in c.file  # "src\\x.java" uses Windows slashes
    has_colon = ":" in c.file  # "c:/x.java" would break the id
    goes_up = ".." in c.file.split("/")  # "../x.java" points outside the service
    if is_absolute or has_backslash or has_colon or goes_up:
        raise ValueError(
            f"file {c.file!r} must be a POSIX path relative to the service root "
            "(no leading '/', no '\\', no ':', no '..')"
        )


def check_lines(c: Candidate) -> None:
    """Make sure line numbers match the unit: real numbers for line_range, None otherwise."""
    # True/False count as ints in Python, and "12" or 1.5 would break comparisons.
    for name in ("line_start", "line_end"):
        value = getattr(c, name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"{name} must be an int or None")
    if c.unit == Unit.LINE_RANGE:
        # A line claim with no lines can't be matched against labelled lines.
        if c.line_start is None or c.line_end is None:
            raise ValueError("unit=line_range requires line_start and line_end")
        # Editors and labels count lines from 1, so 0 or negative is a bug in the rule.
        if c.line_start < 1:
            raise ValueError("line_start must be >= 1")
        # A range that ends before it starts is empty and can't match anything.
        if c.line_end < c.line_start:
            raise ValueError("line_end must be >= line_start")
    # A fake line range would cause fake matches against labels.
    elif c.line_start is not None or c.line_end is not None:
        raise ValueError(f"unit={c.unit} must have null line_start and line_end")


def check_pattern_and_rule_id(c: Candidate) -> None:
    """Make sure pattern and rule_id follow the naming rules in ids.py."""
    # One naming style means "tracing-span" and "TracingSpan" can't both exist.
    if not KEBAB_CASE.fullmatch(c.pattern):
        raise ValueError(f"pattern {c.pattern!r} must be kebab-case")
    # One rule id style lets us group and score results per rule.
    if not RULE_ID.fullmatch(c.rule_id):
        raise ValueError(f"rule_id {c.rule_id!r} must look like 'observability-tracing-01'")
    # A rule id from another category is a copy-paste mistake. Cutting off "-NN"
    # first means "observability-01" (no rule name) fails too.
    name_part = c.rule_id[:-3]  # "observability-tracing-01" -> "observability-tracing"
    if not name_part.startswith(f"{c.category}-"):
        raise ValueError(f"rule_id {c.rule_id!r} must start with its category '{c.category}-'")


def check_snippet(c: Candidate) -> None:
    """Make sure there is evidence, and not too much of it."""
    # Claude can't confirm or reject a candidate without evidence to read.
    if not isinstance(c.snippet, str) or not c.snippet.strip():
        raise ValueError("snippet must be a non-empty string")
    # Long snippets cost money on every Claude call; rules should trim them.
    if len(c.snippet) > SNIPPET_MAX_CHARS:
        raise ValueError(f"snippet is {len(c.snippet)} chars; max is {SNIPPET_MAX_CHARS}")


def check_id(c: Candidate) -> None:
    """Make sure the id was built from this candidate's own fields."""
    # A stale or hand-typed id would match the wrong human label.
    expected = build_id(c.repo, c.service, c.file, c.line_start, c.line_end, c.unit, c.pattern)
    if c.id != expected:
        raise ValueError(f"id {c.id!r} does not match fields; expected {expected!r}")
