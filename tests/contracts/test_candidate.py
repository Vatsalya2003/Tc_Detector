"""Tests for the Candidate format: every validation rule, the id, and saving/loading.

Each test checks one promise the format makes to the team, so if someone loosens
a rule later, a test here fails.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from tc_detector.contracts.candidate import (
    SNIPPET_MAX_CHARS,
    Candidate,
    Category,
    Unit,
    build_id,
)

SCHEMA_PATH = Path(__file__).parents[2] / "schemas" / "candidate.schema.json"

# ---------------------------------------------------------------------------
# Three valid example candidates, one per unit. Tests copy one and change a
# single field to see whether that change is accepted or rejected.
# ---------------------------------------------------------------------------

TRACING_FILE = "src/main/java/org/springframework/samples/petclinic/customers/OwnerResource.java"

# line_range: a tracing annotation on specific lines.
LINE_RANGE_EXAMPLE = {
    "repo": "petclinic",
    "commit": "a1b2c3d",
    "service": "customers-service",
    "file": TRACING_FILE,
    "line_start": 48,
    "line_end": 55,
    "unit": Unit.LINE_RANGE,
    "pattern": "tracing-span",
    "category": Category.OBSERVABILITY,
    "rule_id": "observability-tracing-01",
    "snippet": '@NewSpan("find-owner")\npublic Optional<Owner> findOwner(...) { ... }',
}

# file: a logging config where the whole file is the evidence.
FILE_EXAMPLE = {
    "repo": "petclinic",
    "commit": "a1b2c3d",
    "service": "api-gateway",
    "file": "src/main/resources/logback-spring.xml",
    "line_start": None,
    "line_end": None,
    "unit": Unit.FILE,
    "pattern": "correlation-id",
    "category": Category.OBSERVABILITY,
    "rule_id": "observability-correlation-id-01",
    "snippet": "<pattern>%X{traceId} %msg</pattern>",
}

# service: the whole gateway service is the evidence, so there is no file.
SERVICE_EXAMPLE = {
    "repo": "petclinic",
    "commit": "a1b2c3d",
    "service": "api-gateway",
    "file": None,
    "line_start": None,
    "line_end": None,
    "unit": Unit.SERVICE,
    "pattern": "gateway",
    "category": Category.ABSTRACTION,
    "rule_id": "abstraction-gateway-01",
    "snippet": "api-gateway routes all external traffic",
}

ALL_EXAMPLES = [LINE_RANGE_EXAMPLE, FILE_EXAMPLE, SERVICE_EXAMPLE]


def make(example=LINE_RANGE_EXAMPLE, **changes):
    """Build a Candidate from an example, with some fields changed."""
    return Candidate.create(**{**example, **changes})


# ------------------------------------------------------------------- the id


def test_build_id_matches_documented_example():
    """The example id from the docs is exactly what build_id produces."""
    candidate_id = build_id(
        "petclinic", "api-gateway", "GatewayConfig.java", 12, 40, "line_range", "gateway"
    )
    assert candidate_id == "petclinic:api-gateway:GatewayConfig.java:12-40:gateway"


def test_id_for_each_unit():
    """line_range ids hold line numbers; file/service ids hold the unit name instead."""
    assert make(LINE_RANGE_EXAMPLE).id == (
        f"petclinic:customers-service:{TRACING_FILE}:48-55:tracing-span"
    )
    assert make(FILE_EXAMPLE).id == (
        "petclinic:api-gateway:src/main/resources/logback-spring.xml:file:correlation-id"
    )
    assert make(SERVICE_EXAMPLE).id == "petclinic:api-gateway:-:service:gateway"


def test_same_file_name_in_different_folders_gives_different_ids():
    """The id uses the full path, so two Config.java files don't collide."""
    a = make(file="src/main/java/a/Config.java")
    b = make(file="src/main/java/b/Config.java")
    assert a.id != b.id


def test_create_rejects_a_hand_written_id():
    """create() always computes the id itself."""
    with pytest.raises(TypeError, match="computes the id"):
        Candidate.create(id="x", **LINE_RANGE_EXAMPLE)


def test_create_names_missing_fields():
    """Forgetting a field gives a clear message saying which one."""
    fields_without_snippet = {k: v for k, v in LINE_RANGE_EXAMPLE.items() if k != "snippet"}
    with pytest.raises(TypeError, match=r"missing required field\(s\): snippet"):
        Candidate.create(**fields_without_snippet)


def test_id_must_match_the_other_fields():
    """A wrong id (e.g. stale after a copy-paste) is rejected."""
    with pytest.raises(ValueError, match="does not match"):
        Candidate(id="petclinic:wrong:id:1-2:x", **LINE_RANGE_EXAMPLE)


# ------------------------------------------------------- valid candidates


@pytest.mark.parametrize("example", ALL_EXAMPLES)
def test_valid_examples_are_accepted(example):
    """All three example candidates pass validation."""
    candidate = make(example)
    assert isinstance(candidate.unit, Unit)
    assert isinstance(candidate.category, Category)


def test_plain_strings_become_enums():
    """Rules may pass "line_range" instead of Unit.LINE_RANGE."""
    candidate = make(unit="line_range", category="observability")
    assert candidate.unit is Unit.LINE_RANGE
    assert candidate.category is Category.OBSERVABILITY


def test_service_unit_may_name_a_file():
    """A service claim can optionally point at a file (e.g. its config)."""
    candidate = make(SERVICE_EXAMPLE, file="src/main/resources/application.yml")
    assert candidate.file == "src/main/resources/application.yml"


def test_single_line_range_is_allowed():
    """line_start == line_end is a valid one-line range."""
    make(line_start=7, line_end=7)


def test_candidate_cannot_be_changed_after_creation():
    """Candidates are frozen, so nothing downstream can edit them by accident."""
    candidate = make()
    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.snippet = "changed"  # type: ignore[misc]


# --------------------------------------------------------- line_range rules


def test_line_range_needs_a_file():
    """Lines without a file point at nothing."""
    with pytest.raises(ValueError, match="requires a file"):
        make(file=None)


@pytest.mark.parametrize("field", ["line_start", "line_end"])
def test_line_range_needs_both_lines(field):
    """A line claim with a missing line number can't be matched."""
    with pytest.raises(ValueError, match="requires line_start and line_end"):
        make(**{field: None})


@pytest.mark.parametrize("start", [0, -1])
def test_lines_start_at_one(start):
    """Line numbers count from 1, like in an editor."""
    with pytest.raises(ValueError, match="line_start must be >= 1"):
        make(line_start=start, line_end=5)


def test_range_cannot_end_before_it_starts():
    """An end line before the start line is an empty range."""
    with pytest.raises(ValueError, match="line_end must be >= line_start"):
        make(line_start=10, line_end=9)


@pytest.mark.parametrize("bad", [True, 1.5, "12"])
def test_line_numbers_must_be_whole_numbers(bad):
    """True, 1.5 and "12" are not valid line numbers."""
    with pytest.raises(ValueError, match="must be an int"):
        make(line_start=bad)


# ------------------------------------------------------ file/service rules


@pytest.mark.parametrize("example", [FILE_EXAMPLE, SERVICE_EXAMPLE])
@pytest.mark.parametrize(("start", "end"), [(1, None), (None, 5), (1, 5)])
def test_file_and_service_claims_have_no_lines(example, start, end):
    """Whole-file and whole-service claims must not carry (fake) line numbers."""
    with pytest.raises(ValueError, match="must have null line_start and line_end"):
        make(example, line_start=start, line_end=end)


def test_file_claim_needs_a_file():
    """A file claim must say which file."""
    with pytest.raises(ValueError, match="requires a file"):
        make(FILE_EXAMPLE, file=None)


@pytest.mark.parametrize(
    ("bad_path", "message"),
    [
        ("/abs/Path.java", "relative to the service root"),  # absolute path
        ("src\\Win.java", "relative to the service root"),  # Windows slashes
        ("src/../escape.java", "relative to the service root"),  # leaves the service
        ("c:/x.java", "relative to the service root"),  # ':' breaks the id
        ("", "non-empty string or None"),  # empty string instead of None
    ],
)
def test_file_must_be_a_clean_relative_path(bad_path, message):
    """Each file can only be written one way, so it always gets the same id."""
    with pytest.raises(ValueError, match=message):
        make(file=bad_path)


# -------------------------------------------------- text, pattern, rule_id


@pytest.mark.parametrize("field", ["repo", "commit", "service", "pattern", "rule_id"])
def test_text_fields_cannot_be_blank(field):
    """Blank text fields would make a candidate impossible to trace."""
    with pytest.raises(ValueError, match=f"{field} must be a non-empty string"):
        Candidate(id="x", **{**LINE_RANGE_EXAMPLE, field: "  "})


@pytest.mark.parametrize("field", ["repo", "service"])
def test_id_parts_cannot_contain_colons(field):
    """':' separates id parts, so it can't appear inside one."""
    with pytest.raises(ValueError, match="must not contain ':'"):
        make(**{field: "a:b"})


@pytest.mark.parametrize(
    "bad",
    [
        "TracingSpan",  # uppercase
        "tracing-span\n",  # trailing newline (the JSON Schema rejects this too)
    ],
)
def test_pattern_must_be_kebab_case(bad):
    """Patterns use one naming style: lowercase words joined by dashes."""
    with pytest.raises(ValueError, match="kebab-case"):
        make(pattern=bad)


@pytest.mark.parametrize(
    "bad",
    [
        "OBS-01",  # old style: uppercase and no rule name
        "observability-tracing",  # no number
        "observability-tracing-1",  # number must be two digits
        "observability-01",  # no rule name between category and number
        "observability-tracing-01\n",  # trailing newline (the JSON Schema rejects this too)
    ],
)
def test_rule_id_format(bad):
    """rule_id must look like category-name-NN."""
    with pytest.raises(ValueError, match="rule_id"):
        make(rule_id=bad)


def test_rule_id_must_start_with_its_category():
    """An observability candidate can't carry another category's rule id."""
    with pytest.raises(ValueError, match="must start with its category"):
        make(rule_id="resilience-retry-01")


def test_rule_id_works_for_dashed_category():
    """Categories with a dash (api-stability) still work."""
    make(category=Category.API_STABILITY, rule_id="api-stability-versioning-01")


@pytest.mark.parametrize(("field", "value"), [("unit", "lines"), ("category", "resilience")])
def test_unknown_unit_or_category_is_rejected(field, value):
    """Typos or made-up values for unit/category fail immediately."""
    with pytest.raises(ValueError):
        make(**{field: value})


# --------------------------------------------------------------- snippet


def test_snippet_at_the_limit_is_allowed():
    """Exactly 2000 characters is fine."""
    make(snippet="x" * SNIPPET_MAX_CHARS)


def test_snippet_over_the_limit_is_rejected():
    """2001 characters is too much to send to Claude."""
    with pytest.raises(ValueError, match="max is 2000"):
        make(snippet="x" * (SNIPPET_MAX_CHARS + 1))


@pytest.mark.parametrize("blank", ["", "   "])
def test_snippet_cannot_be_blank(blank):
    """Claude needs some evidence to read."""
    with pytest.raises(ValueError, match="snippet must be a non-empty string"):
        make(snippet=blank)


# ---------------------------------------------------- saving and loading


@pytest.mark.parametrize("example", ALL_EXAMPLES)
def test_dict_round_trip(example):
    """to_dict then from_dict gives back the same candidate."""
    candidate = make(example)
    assert Candidate.from_dict(candidate.to_dict()) == candidate


@pytest.mark.parametrize("example", ALL_EXAMPLES)
def test_json_round_trip(example):
    """to_json then from_json gives back the same candidate."""
    candidate = make(example)
    saved = json.loads(candidate.to_json())
    assert saved["unit"] == candidate.unit.value
    assert saved["category"] == candidate.category.value
    assert Candidate.from_json(candidate.to_json()) == candidate


def test_to_dict_uses_plain_strings_and_none():
    """Saved data has plain strings for enums and None (JSON null) for empty fields."""
    data = make(SERVICE_EXAMPLE).to_dict()
    assert type(data["unit"]) is str
    assert type(data["category"]) is str
    assert data["file"] is None
    assert data["line_start"] is None
    assert data["line_end"] is None


def test_from_dict_rejects_missing_keys():
    """Loading data with a field missing fails and names the field."""
    data = make().to_dict()
    del data["snippet"]
    with pytest.raises(ValueError, match=r"missing=\['snippet'\]"):
        Candidate.from_dict(data)


def test_from_dict_rejects_unknown_keys():
    """Loading data with an extra or renamed field fails and names the field."""
    data = make().to_dict()
    data["evidence"] = "renamed field"
    with pytest.raises(ValueError, match=r"extra=\['evidence'\]"):
        Candidate.from_dict(data)


# ------------------------------------------------- schema matches the code


def test_schema_matches_the_python_model():
    """The JSON Schema and the Python class list the same fields, values and limits."""
    schema = json.loads(SCHEMA_PATH.read_text())
    field_names = [f.name for f in dataclasses.fields(Candidate)]

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert schema["required"] == field_names
    assert list(schema["properties"]) == field_names
    assert schema["properties"]["unit"]["enum"] == [u.value for u in Unit]
    assert schema["properties"]["category"]["enum"] == [c.value for c in Category]
    assert schema["properties"]["snippet"]["maxLength"] == SNIPPET_MAX_CHARS
