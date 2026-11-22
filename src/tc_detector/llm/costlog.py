"""Append-only JSON Lines log of every Claude call, read by B's cost report."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CostLog:
    def __init__(self, path: Path | str | None):
        self.path = Path(path) if path else None

    def write(self, row: dict[str, Any]) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **row}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def summarize(path: Path | str) -> dict[str, Any]:
    """Quick totals for a log file: calls, cache hits, tokens, dollars spent and saved."""
    totals = {
        "calls": 0,
        "api_calls": 0,
        "cache_hits": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cost_usd": 0.0,
        "saved_usd": 0.0,
    }
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            totals["calls"] += 1
            if row.get("cache_hit"):
                totals["cache_hits"] += 1
            else:
                totals["api_calls"] += 1
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ):
                totals[k] += row.get(k, 0)
            totals["cost_usd"] += row.get("cost_usd", 0.0)
            totals["saved_usd"] += row.get("saved_usd", 0.0)
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    totals["saved_usd"] = round(totals["saved_usd"], 6)
    return totals
