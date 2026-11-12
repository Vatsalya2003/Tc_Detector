"""Shared data formats. Start with enums.py, then ids.py, checks.py, candidate.py.

Re-exports the main names so `from tc_detector.contracts import Candidate` works.
"""

from tc_detector.contracts.candidate import (
    SNIPPET_MAX_CHARS,
    Candidate,
    Category,
    Unit,
    build_id,
)

__all__ = ["SNIPPET_MAX_CHARS", "Candidate", "Category", "Unit", "build_id"]
