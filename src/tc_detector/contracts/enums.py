"""The fixed lists of allowed values for a candidate's `unit` and `category`.

They live in their own file because the id, the checks and the Candidate all use them.
Read this file to learn what a unit and a category are. Read ids.py next.
"""

from enum import StrEnum

# A StrEnum is a fixed list of allowed strings. A typo like "observabilty" fails
# right away, instead of quietly creating a new category nobody counts.


class Unit(StrEnum):
    """How precise a claim is; evaluation uses this to decide how to match it."""

    LINE_RANGE = "line_range"  # "these exact lines are the credit"
    FILE = "file"  # "this whole file is the credit" (e.g. a logging config)
    SERVICE = "service"  # "this whole service is the credit" (e.g. an API gateway)


class Category(StrEnum):
    """The six kinds of Technical Credit from the course spec."""

    OBSERVABILITY = "observability"
    API_STABILITY = "api-stability"
    MODULARITY = "modularity"
    AUTOMATION = "automation"
    ABSTRACTION = "abstraction"
    CONFIGURABILITY = "configurability"
