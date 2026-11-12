"""An offline stand-in for the Anthropic client, so wrapper tests need no key and cost nothing."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

GOOD_ANSWER = {
    "is_tc": True,
    "tc_confidence": 4,
    "tc_category": "automation",
    "tc_benefit": "Checkout keeps working during a payments outage.",
    "tc_conditions": "When the payment provider fails or is slow.",
    "tc_signals": ["fallback-invocation-rate"],
    "not_tc_reason": None,
}
ADR_ANSWER = {
    "adr_title": "Wrap payment calls in a circuit breaker",
    "context": "Orders call an external payment provider.",
    "decision": "Use a Resilience4j circuit breaker with a queueing fallback.",
    "consequences_good": ["Good, because checkout stays up."],
    "consequences_bad": ["Bad, because payments may be queued, not settled."],
}


def make_response(
    answer: Any,
    *,
    model: str = "claude-sonnet-5-5",
    stop_reason: str = "end_turn",
    input_tokens: int = 1000,
    output_tokens: int = 200,
    cache_read: int = 0,
    cache_write: int = 0,
) -> SimpleNamespace:
    """A response shaped like anthropic's Message, with just the fields the wrapper reads."""
    text = answer if isinstance(answer, str) else json.dumps(answer)
    return SimpleNamespace(
        model=model,
        stop_reason=stop_reason,
        stop_details=None,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
        _request_id="req_test",
    )


class FakeMessages:
    def __init__(self, responses: list[SimpleNamespace]):
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeClient:
    """Mimics `client.messages` and `client.beta.messages`; both share one queue."""

    def __init__(self, *responses: SimpleNamespace):
        self.messages = FakeMessages(list(responses))
        self.beta = SimpleNamespace(messages=self.messages)

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls
