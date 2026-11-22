"""Tiny made-up candidates and labels shared by the eval tests.

Everything starts from one place in a fake repo: a gateway on lines 10-20 of
src/PayGateway.java in the "orders" service. Tests pass only the fields they change,
so each test shows exactly what makes it different.
"""

from tc_detector.contracts.candidate import Candidate
from tc_detector.contracts.label import Label

# Fields candidates and labels share.
PLACE = {
    "repo": "toy-shop",
    "commit": "abc123",
    "service": "orders",
    "file": "src/PayGateway.java",
    "line_start": 10,
    "line_end": 20,
    "unit": "line_range",
    "pattern": "gateway",
    "category": "abstraction",
}

# Pass these to switch an example to a whole-file or whole-service claim.
WHOLE_FILE = {"unit": "file", "line_start": None, "line_end": None}
WHOLE_SERVICE = {"unit": "service", "file": None, "line_start": None, "line_end": None}


def cand(**changes) -> Candidate:
    """A valid candidate at PLACE, with some fields changed."""
    values = {**PLACE, "snippet": "class PayGateway { ... }", **changes}
    # rule_id must start with the category, so build it unless the test gave one.
    values.setdefault("rule_id", f"{values['category']}-{values['pattern']}-01")
    return Candidate.create(**values)


def lbl(**changes) -> Label:
    """A valid label at PLACE (judged true, one labeller), with some fields changed."""
    values = {
        **PLACE,
        "is_tc": True,
        "labeller": "A",
        "second_labeller": None,
        "second_is_tc": None,
        "adjudicated_by": None,
        "notes": "",
        **changes,
    }
    return Label.create(**values)
