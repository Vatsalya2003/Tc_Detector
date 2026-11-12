"""Tests for the Label format: every validation rule, the id, saving/loading, and the schema.

Each test checks one promise the label format makes to the team, so if someone loosens
a rule later, a test here fails. The format is a DRAFT (see ground_truth/LABEL_FORMAT.md).
"""

import dataclasses
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from tc_detector.contracts.candidate import Candidate, Category, Unit
from tc_detector.contracts.label import Label, Labeller, load_labels, save_labels

SCHEMAS = Path(__file__).parents[2] / "schemas"
LABEL_SCHEMA = json.loads((SCHEMAS / "label.schema.json").read_text())
CANDIDATE_SCHEMA = json.loads((SCHEMAS / "candidate.schema.json").read_text())

# The fields a label shares with a candidate (everything except id/rule_id/snippet).
SHARED_FIELDS = [
    "repo", "commit", "service", "file", "line_start", "line_end", "unit", "pattern", "category",
]  # fmt: skip

# ---------------------------------------------------------------------------
# Valid example labels, one per unit plus one adjudicated disagreement. Tests copy
# one and change a single field to see whether that change is accepted or rejected.
# ---------------------------------------------------------------------------

REPO = "spring-petclinic-microservices"
COMMIT = "TODO-pin-sha"
TRACING_FILE = "src/main/java/org/springframework/samples/petclinic/customers/OwnerResource.java"

# line_range: one labeller, a tracing span on specific lines.
LINE_RANGE_EXAMPLE = {
    "repo": REPO,
    "commit": COMMIT,
    "service": "customers-service",
    "file": TRACING_FILE,
    "line_start": 48,
    "line_end": 55,
    "unit": Unit.LINE_RANGE,
    "pattern": "distributed-tracing",
    "category": Category.OBSERVABILITY,
    "is_tc": True,
    "labeller": Labeller.A,
    "second_labeller": None,
    "second_is_tc": None,
    "adjudicated_by": None,
    "notes": "Span around the owner lookup; tracing backend is swappable via config",
}

# file: judged absent, and in the agreement sample (both labellers said no).
FILE_EXAMPLE = {
    "repo": REPO,
    "commit": COMMIT,
    "service": "config-server",
    "file": "src/main/resources/application.yml",
    "line_start": None,
    "line_end": None,
    "unit": Unit.FILE,
    "pattern": "feature-flags",
    "category": Category.CONFIGURABILITY,
    "is_tc": False,
    "labeller": Labeller.B,
    "second_labeller": Labeller.C,
    "second_is_tc": False,
    "adjudicated_by": None,
    "notes": "",
}

# service: the whole gateway is the credit; no file.
SERVICE_EXAMPLE = {
    "repo": REPO,
    "commit": COMMIT,
    "service": "api-gateway",
    "file": None,
    "line_start": None,
    "line_end": None,
    "unit": Unit.SERVICE,
    "pattern": "gateway",
    "category": Category.ABSTRACTION,
    "is_tc": True,
    "labeller": Labeller.A,
    "second_labeller": None,
    "second_is_tc": None,
    "adjudicated_by": None,
    "notes": "Routes all external traffic; hides service topology",
}

# The labellers disagreed (C said no); D settled it as yes.
ADJUDICATED_EXAMPLE = {
    **SERVICE_EXAMPLE,
    "second_labeller": Labeller.C,
    "second_is_tc": False,
    "adjudicated_by": Labeller.D,
}

ALL_EXAMPLES = [LINE_RANGE_EXAMPLE, FILE_EXAMPLE, SERVICE_EXAMPLE, ADJUDICATED_EXAMPLE]


def make(example=LINE_RANGE_EXAMPLE, **changes):
    """Build a Label from an example, with some fields changed."""
    return Label.create(**{**example, **changes})


# ------------------------------------------------------------------- the id


def test_label_id_for_each_unit():
    """label_id uses the same format as a candidate id."""
    assert make(LINE_RANGE_EXAMPLE).label_id == (
        f"{REPO}:customers-service:{TRACING_FILE}:48-55:distributed-tracing"
    )
    assert make(FILE_EXAMPLE).label_id == (
        f"{REPO}:config-server:src/main/resources/application.yml:file:feature-flags"
    )
    assert make(SERVICE_EXAMPLE).label_id == f"{REPO}:api-gateway:-:service:gateway"


def test_label_and_candidate_for_the_same_place_share_an_id():
    """A label and a candidate pointing at the same place get the same id."""
    label = make(SERVICE_EXAMPLE)
    candidate = Candidate.create(
        **{name: getattr(label, name) for name in SHARED_FIELDS},
        rule_id="abstraction-gateway-01",
        snippet="api-gateway routes all external traffic",
    )
    assert label.label_id == candidate.id


def test_create_rejects_a_hand_written_id():
    """create() always computes the label_id itself."""
    with pytest.raises(TypeError, match="computes the label_id"):
        Label.create(label_id="x", **LINE_RANGE_EXAMPLE)


def test_create_names_missing_fields():
    """Forgetting a field gives a clear message saying which one."""
    without_notes = {k: v for k, v in LINE_RANGE_EXAMPLE.items() if k != "notes"}
    with pytest.raises(TypeError, match=r"missing required field\(s\): notes"):
        Label.create(**without_notes)


def test_label_id_must_match_the_other_fields():
    """A wrong id (e.g. stale after editing the line range) is rejected."""
    with pytest.raises(ValueError, match="does not match"):
        Label(label_id=f"{REPO}:wrong:id:1-2:x", **LINE_RANGE_EXAMPLE)


# ----------------------------------------------------------- valid labels


@pytest.mark.parametrize("example", ALL_EXAMPLES)
def test_valid_examples_are_accepted(example):
    """All example labels pass validation."""
    label = make(example)
    assert isinstance(label.unit, Unit)
    assert isinstance(label.labeller, Labeller)


def test_plain_strings_become_enums():
    """Label files hold plain strings like "line_range" and "A"."""
    label = make(ADJUDICATED_EXAMPLE, unit="service", labeller="A", adjudicated_by="D")
    assert label.unit is Unit.SERVICE
    assert label.labeller is Labeller.A
    assert label.adjudicated_by is Labeller.D


def test_single_line_range_is_allowed():
    """line_start == line_end is a valid one-line range."""
    make(line_start=7, line_end=7)


def test_label_cannot_be_changed_after_creation():
    """Labels are frozen, so nothing downstream can edit ground truth by accident."""
    label = make()
    with pytest.raises(dataclasses.FrozenInstanceError):
        label.is_tc = False  # type: ignore[misc]


# ------------------------------------------- unit and line rules (shared)


def test_unknown_unit_is_rejected():
    """Only line_range, file and service are units."""
    with pytest.raises(ValueError):
        make(unit="lines")


@pytest.mark.parametrize("example", [FILE_EXAMPLE, SERVICE_EXAMPLE])
@pytest.mark.parametrize(("start", "end"), [(1, None), (None, 5), (1, 5)])
def test_file_and_service_labels_have_no_lines(example, start, end):
    """Whole-file and whole-service labels must not carry line numbers."""
    with pytest.raises(ValueError, match="must have null line_start and line_end"):
        make(example, line_start=start, line_end=end)


@pytest.mark.parametrize("field", ["line_start", "line_end"])
def test_line_range_needs_both_lines(field):
    """A line label with a missing line number can't be matched."""
    with pytest.raises(ValueError, match="requires line_start and line_end"):
        make(**{field: None})


def test_range_cannot_end_before_it_starts():
    """line_start must be <= line_end."""
    with pytest.raises(ValueError, match="line_end must be >= line_start"):
        make(line_start=10, line_end=9)


def test_line_range_needs_a_file():
    """Lines without a file point at nothing."""
    with pytest.raises(ValueError, match="requires a file"):
        make(file=None)


def test_file_must_be_a_clean_relative_path():
    """Paths follow the candidate rules, so labels and candidates write files the same way."""
    with pytest.raises(ValueError, match="relative to the service root"):
        make(file="/abs/Path.java")


# ------------------------------------------------- text, pattern, category


@pytest.mark.parametrize("bad", ["Gateway", "circuit_breaker", "gateway\n"])
def test_pattern_must_be_kebab_case(bad):
    """Patterns use the same naming style as candidates."""
    with pytest.raises(ValueError, match="kebab-case"):
        make(pattern=bad)


def test_unknown_category_is_rejected():
    """Only the six categories exist."""
    with pytest.raises(ValueError):
        make(category="resilience")


@pytest.mark.parametrize("field", ["repo", "commit", "service", "pattern"])
def test_text_fields_cannot_be_blank(field):
    """Blank text fields would make a label impossible to trace."""
    with pytest.raises(ValueError, match=f"{field} must be a non-empty string"):
        Label(label_id="x", **{**LINE_RANGE_EXAMPLE, field: "  "})


def test_notes_must_be_text():
    """Use "" for no notes, not None."""
    with pytest.raises(ValueError, match="notes must be a string"):
        make(notes=None)


# ------------------------------------------------------------- verdicts


@pytest.mark.parametrize("bad", ["yes", 1, None])
def test_is_tc_must_be_true_or_false(bad):
    """Only real booleans count as a verdict."""
    with pytest.raises(ValueError, match="is_tc must be true or false"):
        make(is_tc=bad)


def test_second_is_tc_must_be_true_false_or_none():
    """The second verdict is a boolean too."""
    with pytest.raises(ValueError, match="second_is_tc must be"):
        make(FILE_EXAMPLE, second_is_tc="no")


# ----------------------------------------------------- labeller rules


@pytest.mark.parametrize("field", ["labeller", "second_labeller", "adjudicated_by"])
@pytest.mark.parametrize("bad", ["E", "a", "Karan"])
def test_labellers_must_be_a_to_d(field, bad):
    """Only the four team letters are allowed."""
    with pytest.raises(ValueError):
        make(ADJUDICATED_EXAMPLE, **{field: bad})


def test_second_is_tc_without_second_labeller_is_rejected():
    """A second verdict with no name attached is useless for kappa."""
    with pytest.raises(ValueError, match="both be set or both be None"):
        make(second_is_tc=True)


def test_second_labeller_without_second_is_tc_is_rejected():
    """A second labeller with no verdict is useless for kappa."""
    with pytest.raises(ValueError, match="both be set or both be None"):
        make(second_labeller=Labeller.B)


def test_second_labeller_must_be_someone_else():
    """Agreeing with yourself says nothing."""
    with pytest.raises(ValueError, match="different person"):
        make(FILE_EXAMPLE, second_labeller=Labeller.B)


def test_disagreement_needs_an_adjudicator():
    """If the verdicts differ, someone must have settled it."""
    with pytest.raises(ValueError, match="adjudicated_by must say who settled it"):
        make(FILE_EXAMPLE, second_is_tc=True)


def test_adjudicator_needs_a_second_labeller():
    """With one labeller there is no disagreement to settle."""
    with pytest.raises(ValueError, match="requires a second_labeller"):
        make(adjudicated_by=Labeller.D)


@pytest.mark.parametrize("who", [Labeller.A, Labeller.C, Labeller.D])
def test_adjudicator_can_be_either_labeller_or_anyone_else(who):
    """The two labellers settle it themselves first, else a tie-breaker does."""
    make(ADJUDICATED_EXAMPLE, adjudicated_by=who)


@pytest.mark.parametrize("final", [True, False])
def test_adjudicated_verdict_can_side_with_either_labeller(final):
    """After a disagreement, is_tc is the settled answer, whichever way it went."""
    make(ADJUDICATED_EXAMPLE, is_tc=final, second_is_tc=not final)
    make(ADJUDICATED_EXAMPLE, is_tc=final, second_is_tc=final)


# ---------------------------------------------------- saving and loading


@pytest.mark.parametrize("example", ALL_EXAMPLES)
def test_json_round_trip(example):
    """to_json then from_json gives back the same label, with plain strings in the JSON."""
    label = make(example)
    saved = json.loads(label.to_json())
    assert type(saved["unit"]) is str
    assert type(saved["labeller"]) is str
    assert Label.from_json(label.to_json()) == label


def test_from_dict_rejects_missing_and_unknown_keys():
    """Loading data with a missing or renamed field fails and names it."""
    data = make().to_dict()
    del data["notes"]
    data["comment"] = "renamed field"
    with pytest.raises(ValueError, match=r"missing=\['notes'\] extra=\['comment'\]"):
        Label.from_dict(data)


def test_label_file_round_trip(tmp_path):
    """save_labels then load_labels gives back the same list."""
    labels = [make(e) for e in (LINE_RANGE_EXAMPLE, FILE_EXAMPLE, SERVICE_EXAMPLE)]
    path = tmp_path / "petclinic.json"
    save_labels(path, labels)
    assert load_labels(path) == labels


def test_label_file_must_be_a_list(tmp_path):
    """A label file is a JSON list, even with one label."""
    path = tmp_path / "petclinic.json"
    path.write_text(make().to_json())
    with pytest.raises(ValueError, match="JSON list"):
        load_labels(path)


def test_label_file_error_names_the_broken_entry(tmp_path):
    """A bad entry in a long hand-edited file is easy to find."""
    path = tmp_path / "petclinic.json"
    bad = {**make().to_dict(), "unit": "lines"}
    path.write_text(json.dumps([make(SERVICE_EXAMPLE).to_dict(), bad]))
    with pytest.raises(ValueError, match="label #1"):
        load_labels(path)


@pytest.mark.parametrize(("field", "value"), [("repo", "other-repo"), ("commit", "abc123")])
def test_label_file_holds_one_repo_at_one_commit(tmp_path, field, value):
    """Mixing repos or commits in one file is rejected."""
    with pytest.raises(ValueError, match=f"share one {field}"):
        save_labels(tmp_path / "x.json", [make(), make(SERVICE_EXAMPLE, **{field: value})])


def test_label_file_rejects_duplicate_ids(tmp_path):
    """Two labels for the same place would make one candidate match twice."""
    with pytest.raises(ValueError, match="duplicate label_id"):
        save_labels(tmp_path / "x.json", [make(), make(is_tc=False)])


# ------------------------------------------------- schema matches the code


def test_schema_matches_the_python_model():
    """The JSON Schema and the Python class list the same fields and labeller letters."""
    field_names = [f.name for f in dataclasses.fields(Label)]
    props = LABEL_SCHEMA["properties"]

    assert LABEL_SCHEMA["$schema"] == CANDIDATE_SCHEMA["$schema"]
    assert LABEL_SCHEMA["additionalProperties"] is False
    assert LABEL_SCHEMA["required"] == field_names
    assert list(props) == field_names
    assert LABEL_SCHEMA["$defs"]["labeller"]["enum"] == [x.value for x in Labeller]
    # Shared fields must point at the candidate schema, not copy it.
    for name in SHARED_FIELDS:
        assert props[name]["$ref"] == f"candidate.schema.json#/properties/{name}"
    assert props["label_id"]["$ref"] == "candidate.schema.json#/properties/id"


# The candidate schema is registered under its own $id; the label schema's relative
# "$ref": "candidate.schema.json#..." must resolve against the label schema's $id to it.
REGISTRY = Registry().with_resource(
    CANDIDATE_SCHEMA["$id"], Resource.from_contents(CANDIDATE_SCHEMA)
)


def schema_validator():
    """A validator for label.schema.json that can follow $refs into candidate.schema.json."""
    return jsonschema.Draft202012Validator(LABEL_SCHEMA, registry=REGISTRY)


def test_relative_ref_resolves_to_the_candidate_schema():
    """The relative ref, read against the label schema's $id, lands on the candidate schema."""
    resolver = REGISTRY.resolver(base_uri=LABEL_SCHEMA["$id"])
    resolved = resolver.lookup("candidate.schema.json#/properties/unit").contents
    assert resolved == CANDIDATE_SCHEMA["properties"]["unit"]


def test_label_schema_is_a_valid_schema():
    """The schema file itself follows the 2020-12 rules."""
    jsonschema.Draft202012Validator.check_schema(LABEL_SCHEMA)


@pytest.mark.parametrize("example", ALL_EXAMPLES)
def test_valid_examples_pass_the_schema(example):
    """What the Python code accepts, the schema accepts too (and the $refs resolve)."""
    schema_validator().validate(make(example).to_dict())


@pytest.mark.parametrize(
    ("example", "changes"),
    [
        (LINE_RANGE_EXAMPLE, {"unit": "lines"}),  # bad unit
        (SERVICE_EXAMPLE, {"line_start": 1, "line_end": 5}),  # lines on a service unit
        (LINE_RANGE_EXAMPLE, {"pattern": "Gateway"}),  # not kebab-case
        (LINE_RANGE_EXAMPLE, {"labeller": "E"}),  # labeller not in A-D
        (LINE_RANGE_EXAMPLE, {"second_is_tc": True}),  # second verdict, no second labeller
        (FILE_EXAMPLE, {"second_labeller": "B"}),  # same person twice
        (FILE_EXAMPLE, {"second_is_tc": True}),  # disagreement, no adjudicator
        (LINE_RANGE_EXAMPLE, {"adjudicated_by": "D"}),  # adjudicator, no second labeller
    ],
)
def test_schema_rejects_what_the_python_code_rejects(example, changes):
    """The schema's if/then rules catch the same mistakes as the Python checks."""
    data = {**make(example).to_dict(), **changes}
    with pytest.raises(jsonschema.ValidationError):
        schema_validator().validate(data)
