"""Per-model prices in USD per million tokens.

Check against https://platform.claude.com/docs/en/about-claude/pricing before the
cost report is written, and note the check date in the report. Values below were
taken on 2026-11-11.

`cache_write` is the 5-minute prompt-cache write price; `cache_read` the cache read price.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write: float
    cache_read: float


PRICES: dict[str, Price] = {
    # The "mid-size" model and our default.
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_write=2.50, cache_read=0.10),
    # The "smaller" model for Experiment 3. Cache prices assume the standard
    # 1.25x / 0.1x multipliers: verify before the cost report.
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_write=0.125, cache_read=0.01),
    # Listed so a fallback or an explicit choice is still costed correctly.
    "claude-sonnet-5": Price(input=2.00, output=10.00, cache_write=2.50, cache_read=0.20),
    "claude-sonnet-4-6": Price(input=3.00, output=15.00, cache_write=3.75, cache_read=0.30),
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_write=5.00, cache_read=0.20),
}


class UnknownModelPrice(KeyError):
    pass


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    """Dollar cost of one call. Raises UnknownModelPrice rather than guessing."""
    try:
        p = PRICES[model]
    except KeyError as exc:
        raise UnknownModelPrice(
            f"No price for model {model!r}; add it to tc_detector/llm/pricing.py"
        ) from exc
    total = (
        input_tokens * p.input
        + output_tokens * p.output
        + cache_creation_input_tokens * p.cache_write
        + cache_read_input_tokens * p.cache_read
    ) / 1_000_000
    return round(total, 6)
