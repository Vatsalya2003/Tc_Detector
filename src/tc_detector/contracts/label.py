"""The Label: one human judgment about one place in a repo, plus saving and loading it.

DRAFT: the label format needs team sign-off (see ground_truth/LABEL_FORMAT.md).
Labels are what candidates are scored against. Every field a candidate also has
(repo ... category) uses the same name, type, enum and checks as in candidate.py.
Read candidate.py and label_checks.py first.
"""

# Lets methods say they return "Label" before the class is fully defined.
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import Any

from tc_detector.contracts import checks, label_checks
from tc_detector.contracts.enums import Category, Unit
from tc_detector.contracts.ids import build_id

__all__ = ["Label", "Labeller", "load_labels", "save_labels"]


class Labeller(StrEnum):
    """The four team members, by their letter in the plan."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


# frozen=True: labels are ground truth; nothing downstream can edit one by accident.
# slots=True: uses less memory and stops typos like `lbl.is_ct = ...` adding new fields.
@dataclass(frozen=True, slots=True)
class Label:
    """One human judgment about whether a Technical Credit is present at one place."""

    label_id: str  # PROPOSAL: built by build_id(), exactly like a candidate id
    repo: str  # the repo's `name` in targets.yaml, e.g. "spring-petclinic-microservices"
    commit: str  # the pinned commit that was labelled
    service: str  # which microservice, e.g. "api-gateway"
    file: str | None  # path relative to the service root, using "/"; None only for service units
    line_start: int | None  # first line (1-based); None for file/service units
    line_end: int | None  # last line; None for file/service units
    unit: Unit  # how precise the label is (see enums.py)
    pattern: str  # what kind of credit, in kebab-case, e.g. "gateway"
    category: Category  # one of the six categories (see enums.py)
    is_tc: bool  # final verdict that evaluation scores; False = judged absent
    labeller: Labeller  # who made the first judgment
    second_labeller: Labeller | None  # who labelled it again (20% sample), else None
    second_is_tc: bool | None  # PROPOSAL: the second labeller's own verdict, else None
    adjudicated_by: Labeller | None  # PROPOSAL: who settled a disagreement, else None
    notes: str  # free-text reason; may be ""

    @classmethod
    def create(cls, **values: Any) -> Label:
        """Make a Label from every field except label_id, which is computed for you."""
        # A hand-typed id could disagree with the fields, so create() always builds it.
        if "label_id" in values:
            raise TypeError("Label.create() computes the label_id for you; don't pass one")
        # Without this, a missing field would fail with a confusing error deep inside.
        required = [f.name for f in fields(cls) if f.name != "label_id"]
        missing = [name for name in required if name not in values]
        if missing:
            raise TypeError(
                f"Label.create() is missing required field(s): {', '.join(missing)}. "
                "Pass None for fields that don't apply."
            )
        # The id is made from these seven fields, in this order (see build_id in ids.py).
        id_parts = ("repo", "service", "file", "line_start", "line_end", "unit", "pattern")
        label_id = build_id(*(values[name] for name in id_parts))
        return cls(label_id=label_id, **values)

    def __post_init__(self) -> None:
        """Check every rule the moment a Label is made."""
        # Turn plain strings like "file" or "A" into enum values, so a typo fails here.
        # The class can't be edited, so object.__setattr__ is the one allowed way in.
        object.__setattr__(self, "unit", Unit(self.unit))
        object.__setattr__(self, "category", Category(self.category))
        object.__setattr__(self, "labeller", Labeller(self.labeller))
        for name in ("second_labeller", "adjudicated_by"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, Labeller(value))
        # Order matters: later checks assume earlier ones passed.
        label_checks.check_text_fields(self)
        # Shared with candidates: these only read file, unit, line_start and line_end.
        checks.check_file(self)  # type: ignore[arg-type]
        checks.check_lines(self)  # type: ignore[arg-type]
        label_checks.check_pattern(self)
        label_checks.check_verdicts(self)
        label_checks.check_labellers(self)
        label_checks.check_label_id(self)

    def to_dict(self) -> dict[str, Any]:
        """Turn this label into a plain dict (enums become plain strings)."""
        data = asdict(self)
        for name in ("unit", "category", "labeller", "second_labeller", "adjudicated_by"):
            value = getattr(self, name)
            data[name] = value.value if value is not None else None
        return data

    def to_json(self) -> str:
        """Turn this label into a JSON string."""
        # ensure_ascii=False keeps non-English characters in notes readable.
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Label:
        """Rebuild a label from a dict, e.g. one entry of a ground_truth/ file."""
        # Missing or extra keys usually mean the file uses an old or renamed format.
        expected = {f.name for f in fields(cls)}
        missing = sorted(expected - data.keys())
        extra = sorted(data.keys() - expected)
        if missing or extra:
            raise ValueError(f"bad label keys: missing={missing} extra={extra}")
        return cls(**data)

    @classmethod
    def from_json(cls, text: str) -> Label:
        """Rebuild a label from a JSON string made by to_json()."""
        return cls.from_dict(json.loads(text))


def load_labels(path: str | Path) -> list[Label]:
    """Read one repo's label file (a JSON list of labels) and check all of it."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: a label file must be a JSON list of labels")
    labels = []
    for index, entry in enumerate(data):
        # Say which entry is broken; label files are hand-edited and can be long.
        try:
            labels.append(Label.from_dict(entry))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{path}: label #{index}: {error}") from error
    label_checks.check_label_file(labels)
    return labels


def save_labels(path: str | Path, labels: list[Label]) -> None:
    """Write one repo's labels as a JSON list, one field per line for readable diffs."""
    # Check before writing, so a bad file never lands in ground_truth/.
    label_checks.check_label_file(labels)
    text = json.dumps([lbl.to_dict() for lbl in labels], ensure_ascii=False, indent=2)
    Path(path).write_text(text + "\n", encoding="utf-8")
