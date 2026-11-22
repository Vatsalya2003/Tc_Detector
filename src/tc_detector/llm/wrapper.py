"""Claude wrapper for Stage 3 attribution (stories S1 and S5). Owner: Neil (C).

    from tc_detector.llm import Attributor, Settings
    verdict = Attributor(Settings()).attribute(candidate, context)

Every call goes through the response cache (repeat runs spend no tokens) and is
appended to the cost log (tokens and dollars per call).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tc_detector.contracts.candidate import Candidate
from tc_detector.llm.cache import ResponseCache, request_key
from tc_detector.llm.context import numbered_snippet
from tc_detector.llm.costlog import CostLog
from tc_detector.llm.pricing import cost_usd
from tc_detector.llm.prompts import ADR_PROMPTS, PROMPTS, Prompt
from tc_detector.llm.verdict import (
    ADR_FIELDS,
    ADR_SCHEMA,
    STAGE3_SCHEMA,
    InvalidVerdict,
    empty_stage3,
    validate_fields,
)

DEFAULT_MODEL = "claude-sonnet-5-5"
SMALL_MODEL = "claude-haiku-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Settings:
    model: str = DEFAULT_MODEL
    # Thinking depth. Thinking tokens bill as output, so this is a cost knob too.
    effort: str = "medium"
    max_tokens: int = 16000
    prompt_version: str = "stage3-v1"
    adr_prompt_version: str = "stage3-adr-v1"
    # Server-side refusal fallback. The verdict's `model` records who actually
    # answered, so a fallback can never hide inside a model comparison.
    fallbacks: bool = True
    use_cache: bool = True
    cache_dir: Path = field(default_factory=lambda: Path(".tc_cache"))
    cost_log: Path | None = field(default_factory=lambda: Path("results/cost_log.jsonl"))


@dataclass
class CallResult:
    fields: dict[str, Any] | None
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0
    cache_hit: bool = False
    error: str | None = None


class Attributor:
    def __init__(self, settings: Settings | None = None, client: Any = None):
        self.settings = settings or Settings()
        self._client = client
        self.cache = ResponseCache(self.settings.cache_dir)
        self.log = CostLog(self.settings.cost_log)

    @property
    def client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    # ------------------------------------------------------------------ prompt

    @staticmethod
    def render_user(prompt: Prompt, candidate: dict[str, Any], ctx: dict[str, Any]) -> str:
        unit = candidate.get("unit", "line_range")
        if candidate.get("line_start"):
            line_range = f"{candidate['line_start']}-{candidate['line_end']}"
        else:
            line_range = "whole file" if unit == "file" else "whole service"
        snippet = numbered_snippet(candidate) or "(no snippet)"
        return prompt.user_template.format(
            service_name=candidate.get("service", "unknown"),
            service_role=ctx.get("service_role", "unknown"),
            n_consumers=ctx.get("n_consumers", "unknown"),
            pattern_type=candidate["pattern"],
            file=candidate.get("file") or "(service-level)",
            line_range=line_range,
            # "119mo" when known (as in the spec template), plain "unknown" otherwise.
            file_age=(
                f"{ctx['age_months']}mo" if isinstance(ctx.get("age_months"), int) else "unknown"
            ),
            n_commits=ctx.get("n_commits", "unknown"),
            n_contributors=ctx.get("n_contributors", "unknown"),
            adr_titles_list=", ".join(ctx.get("adr_titles") or []) or "none",
            code_snippet=snippet,
        )

    # -------------------------------------------------------------------- call

    def _call(
        self,
        prompt: Prompt,
        user_text: str,
        schema: dict[str, Any],
        *,
        candidate_id: str,
        repeat: int,
        kind: str,
    ) -> CallResult:
        s = self.settings
        material = {
            "model": s.model,
            "effort": s.effort,
            "max_tokens": s.max_tokens,
            "fallbacks": s.fallbacks,
            "prompt_version": prompt.version,
            "system": prompt.system,
            "user": user_text,
            "schema": schema,
            "repeat": repeat,
        }
        key = request_key(material)
        base_row = {
            "candidate_id": candidate_id,
            "kind": kind,
            "requested_model": s.model,
            "prompt_version": prompt.version,
            "effort": s.effort,
            "repeat": repeat,
            "cache_key": key,
        }

        if s.use_cache and (entry := self.cache.get(key)) is not None:
            fields = validate_fields(entry["fields"], schema)
            self.log.write(
                {
                    **base_row,
                    "model": entry["model"],
                    "cache_hit": True,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cost_usd": 0.0,
                    "saved_usd": entry["cost_usd"],
                    "error": None,
                }
            )
            return CallResult(fields=fields, model=entry["model"], cache_hit=True)

        kwargs: dict[str, Any] = {
            "model": s.model,
            "max_tokens": s.max_tokens,
            # Cache breakpoint on the stable system prompt. Below the model's
            # minimum cacheable size (512 tokens on Sonnet/Haiku 5.5) it is a silent
            # no-op, but the structured-output schema counts toward the prefix, so stage3-v1
            # already caches ~826 tokens (measured Nov 11).
            "system": [
                {"type": "text", "text": prompt.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": user_text}],
            "output_config": {
                "effort": s.effort,
                "format": {"type": "json_schema", "schema": schema},
            },
        }
        if s.fallbacks:
            resp = self.client.beta.messages.create(
                **kwargs, betas=[FALLBACK_BETA], fallbacks="default"
            )
        else:
            resp = self.client.messages.create(**kwargs)

        usage = resp.usage
        tokens = {
            "input_tokens": usage.input_tokens or 0,
            "output_tokens": usage.output_tokens or 0,
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None) or 0,
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None) or 0,
        }
        served = resp.model
        cost = cost_usd(served, **tokens)

        fields: dict[str, Any] | None = None
        error: str | None = None
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            error = f"refusal:{category}" if category else "refusal"
        elif resp.stop_reason == "max_tokens":
            error = "max_tokens"
        else:
            text = "".join(b.text for b in resp.content if b.type == "text")
            try:
                fields = validate_fields(json.loads(text), schema)
            except (json.JSONDecodeError, InvalidVerdict):
                error = "invalid_json"

        request_id = getattr(resp, "_request_id", None)
        self.log.write(
            {
                **base_row,
                "model": served,
                "cache_hit": False,
                **tokens,
                "cost_usd": cost,
                "error": error,
                "stop_reason": resp.stop_reason,
                "request_id": request_id,
            }
        )
        # Only good answers are cached, so a failed call is retried next run.
        if fields is not None and s.use_cache:
            self.cache.put(
                key,
                {
                    "material": material,
                    "fields": fields,
                    "model": served,
                    **tokens,
                    "cost_usd": cost,
                    "stop_reason": resp.stop_reason,
                    "request_id": request_id,
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                },
            )
        return CallResult(fields=fields, model=served, cost_usd=cost, error=error, **tokens)

    # --------------------------------------------------------------- attribute

    def attribute(
        self,
        candidate: Candidate | dict[str, Any],
        context: dict[str, Any] | None = None,
        *,
        repeat: int = 0,
        adr: bool = False,
    ) -> dict[str, Any]:
        """Return one verdict (see docs/contracts/claude-verdict.md).

        A dict is validated against the frozen Candidate format first, so a
        malformed candidate fails here instead of costing an API call.
        """
        if isinstance(candidate, dict):
            candidate = Candidate.from_dict(candidate)
        candidate = candidate.to_dict()
        s = self.settings
        ctx = context or {}
        prompt = PROMPTS[s.prompt_version]
        user_text = self.render_user(prompt, candidate, ctx)
        calls = [
            self._call(
                prompt,
                user_text,
                STAGE3_SCHEMA,
                candidate_id=candidate["id"],
                repeat=repeat,
                kind="stage3",
            )
        ]
        main = calls[0]
        verdict: dict[str, Any] = {"candidate_id": candidate["id"]}
        verdict.update(main.fields or empty_stage3())

        if adr:
            verdict.update(dict.fromkeys(ADR_FIELDS))
            if main.fields and main.fields["is_tc"]:
                adr_prompt = ADR_PROMPTS[s.adr_prompt_version]
                adr_user = adr_prompt.user_template.format(
                    stage3_user=user_text,
                    tc_category=main.fields["tc_category"],
                    tc_benefit=main.fields["tc_benefit"],
                    tc_conditions=main.fields["tc_conditions"],
                )
                adr_call = self._call(
                    adr_prompt,
                    adr_user,
                    ADR_SCHEMA,
                    candidate_id=candidate["id"],
                    repeat=repeat,
                    kind="adr",
                )
                calls.append(adr_call)
                if adr_call.fields:
                    verdict.update(adr_call.fields)

        verdict.update(
            {
                "model": main.model,
                "input_tokens": sum(c.input_tokens for c in calls),
                "output_tokens": sum(c.output_tokens for c in calls),
                "cost_usd": round(sum(c.cost_usd for c in calls), 6),
                "cache_hit": all(c.cache_hit for c in calls),
                "prompt_version": prompt.version,
                "cache_read_input_tokens": sum(c.cache_read_input_tokens for c in calls),
                "cache_creation_input_tokens": sum(c.cache_creation_input_tokens for c in calls),
                "repeat": repeat,
                "error": next((c.error for c in calls if c.error), None),
            }
        )
        return verdict
