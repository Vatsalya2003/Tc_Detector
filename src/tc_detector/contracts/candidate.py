"""The Candidate: one Technical Credit claim from one rule, plus saving and loading it.

This is the one shape every rule outputs, so Claude and evaluation only need to read one format.
Read this file last (after enums.py, ids.py, checks.py) to see how the pieces fit together.
"""

# Lets methods say they return "Candidate" before the class is fully defined.
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Any

from tc_detector.contracts import checks
from tc_detector.contracts.enums import Category, Unit
from tc_detector.contracts.ids import KEBAB_CASE, RULE_ID, SNIPPET_MAX_CHARS, build_id

# Re-exported so old imports like `from ...candidate import Unit, build_id` keep working.
__all__ = [
    "KEBAB_CASE",
    "RULE_ID",
    "SNIPPET_MAX_CHARS",
    "Candidate",
    "Category",
    "Unit",
    "build_id",
]


# The format is "frozen" (locked) since Nov 11: the whole team builds on these 12 fields,
# so don't rename, add or remove one without all four of us agreeing.
# frozen=True: each Candidate is locked too; nothing downstream can edit it by accident.
# slots=True: uses less memory and stops typos like `c.snipet = ...` adding new fields.
@dataclass(frozen=True, slots=True)
class Candidate:
    """One Technical Credit claim from one rule, with the evidence for it."""

    id: str  # built by build_id(); how we match this candidate to a human label
    repo: str  # which target repo, e.g. "petclinic"
    commit: str  # exact git commit scanned, since code changes over time
    service: str  # which microservice, e.g. "api-gateway"
    file: str | None  # path relative to the service root, using "/"; None only for service units
    line_start: int | None  # first line of evidence (1-based); None for file/service units
    line_end: int | None  # last line of evidence; None for file/service units
    unit: Unit  # how precise the claim is (see enums.py)
    pattern: str  # what kind of credit, in kebab-case, e.g. "tracing-span"
    category: Category  # one of the six categories (see enums.py)
    rule_id: str  # which rule found it, e.g. "observability-tracing-01"
    snippet: str  # the evidence text Claude will read (max 2000 chars)

    @classmethod
    def create(cls, **values: Any) -> Candidate:
        """Make a Candidate from every field except id, which is computed for you."""
        # A hand-typed id could disagree with the fields, so create() always builds it.
        if "id" in values:
            raise TypeError("Candidate.create() computes the id for you; don't pass one")
        # Without this, a missing field would fail with a confusing error deep inside.
        required = [f.name for f in fields(cls) if f.name != "id"]
        missing = [name for name in required if name not in values]
        if missing:
            raise TypeError(
                f"Candidate.create() is missing required field(s): {', '.join(missing)}. "
                "Pass None for file/line_start/line_end when they don't apply."
            )
        # The id is made from these seven fields, in this order (see build_id in ids.py).
        id_parts = ("repo", "service", "file", "line_start", "line_end", "unit", "pattern")
        candidate_id = build_id(*(values[name] for name in id_parts))
        return cls(id=candidate_id, **values)

    def __post_init__(self) -> None:
        """Check every rule in checks.py the moment a Candidate is made."""
        # Turn plain strings like "file" into enum values, so a typo fails here.
        # The class can't be edited, so object.__setattr__ is the one allowed way in.
        object.__setattr__(self, "unit", Unit(self.unit))
        object.__setattr__(self, "category", Category(self.category))
        # Order matters: later checks assume earlier ones passed.
        checks.check_text_fields(self)
        checks.check_file(self)
        checks.check_lines(self)
        checks.check_pattern_and_rule_id(self)
        checks.check_snippet(self)
        checks.check_id(self)

    def to_dict(self) -> dict[str, Any]:
        """Turn this candidate into a plain dict (enums become plain strings)."""
        data = asdict(self)
        data["unit"] = self.unit.value
        data["category"] = self.category.value
        return data

    def to_json(self) -> str:
        """Turn this candidate into a JSON string, e.g. for saving to results/."""
        # ensure_ascii=False keeps non-English characters in snippets readable.
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Candidate:
        """Rebuild a candidate from a dict, e.g. one loaded from a results file."""
        # Missing or extra keys usually mean the file uses an old or renamed format.
        expected = {f.name for f in fields(cls)}
        missing = sorted(expected - data.keys())
        extra = sorted(data.keys() - expected)
        if missing or extra:
            raise ValueError(f"bad candidate keys: missing={missing} extra={extra}")
        return cls(**data)

    @classmethod
    def from_json(cls, text: str) -> Candidate:
        """Rebuild a candidate from a JSON string made by to_json()."""
        return cls.from_dict(json.loads(text))
