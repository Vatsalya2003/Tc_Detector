"""The Claude verdict contract: JSON schemas sent to the API and output assembly.

See docs/contracts/claude-verdict.md for the field-by-field description.
"""

from __future__ import annotations

from typing import Any

from tc_detector.llm.prompts import TC_CATEGORIES

_NULLABLE_STRING = {"anyOf": [{"type": "string"}, {"type": "null"}]}

# Sent as output_config.format, so the API guarantees a parseable object.
STAGE3_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_tc": {"type": "boolean"},
        "tc_confidence": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "tc_category": {"type": "string", "enum": TC_CATEGORIES},
        "tc_benefit": {"type": "string"},
        "tc_conditions": {"type": "string"},
        "tc_signals": {"type": "array", "items": {"type": "string"}},
        "not_tc_reason": _NULLABLE_STRING,
    },
    "required": [
        "is_tc",
        "tc_confidence",
        "tc_category",
        "tc_benefit",
        "tc_conditions",
        "tc_signals",
        "not_tc_reason",
    ],
    "additionalProperties": False,
}

ADR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "adr_title": {"type": "string"},
        "context": {"type": "string"},
        "decision": {"type": "string"},
        "consequences_good": {"type": "array", "items": {"type": "string"}},
        "consequences_bad": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["adr_title", "context", "decision", "consequences_good", "consequences_bad"],
    "additionalProperties": False,
}

STAGE3_FIELDS = list(STAGE3_SCHEMA["required"])
ADR_FIELDS = list(ADR_SCHEMA["required"])
COST_FIELDS = [
    "model",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "cache_hit",
    "prompt_version",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "repeat",
    "error",
]


class InvalidVerdict(ValueError):
    pass


def validate_fields(data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Light check of a parsed model answer against our schema.

    Structured outputs should make this unnecessary; it guards the cache and the
    offline fakes, and fails loudly instead of letting a bad row reach scoring.
    """
    if not isinstance(data, dict):
        raise InvalidVerdict(f"expected an object, got {type(data).__name__}")
    missing = [k for k in schema["required"] if k not in data]
    extra = [k for k in data if k not in schema["properties"]]
    if missing or extra:
        raise InvalidVerdict(f"missing={missing} extra={extra}")
    if "tc_confidence" in data and data["tc_confidence"] not in (1, 2, 3, 4, 5):
        raise InvalidVerdict(f"tc_confidence out of range: {data['tc_confidence']!r}")
    if "tc_category" in data and data["tc_category"] not in TC_CATEGORIES:
        raise InvalidVerdict(f"unknown tc_category: {data['tc_category']!r}")
    return data


def empty_stage3() -> dict[str, Any]:
    """Verdict fields for a call that produced no usable answer."""
    return {k: ([] if k == "tc_signals" else None) for k in STAGE3_FIELDS}
