"""Versioned Stage 3 prompts.

`stage3-v1` is the professor's spec template (TC Mining plan, "Stage 3 AI prompt
template") with two mechanical changes:

1. The static "Return JSON" field descriptions moved from the user turn into the
   system prompt, so the stable part sits in the cacheable prefix and only the
   per-candidate facts vary.
2. The ADR fields (adr_title, context, decision, consequences_*) are left out of
   the default call and asked in a separate follow-up (`stage3-adr-v1`), only for
   confirmed candidates and only with --adr.

Never edit a released version in place: add `stage3-v2` etc. and log the change
in docs/prompt-log.md, so cached answers and results stay tied to the prompt
that produced them.
"""

from __future__ import annotations

from dataclasses import dataclass

from tc_detector.contracts.enums import Category

# The team's six categories (contracts/enums.py). The spec lists eight; the other
# two (compliance-readiness, reusability) are a stretch goal, so Claude may not use them.
TC_CATEGORIES = [c.value for c in Category]


@dataclass(frozen=True)
class Prompt:
    version: str
    system: str
    user_template: str


_STAGE3_V1_SYSTEM = """\
You are a software architecture expert analysing microservices systems for \
Technical Credit (TC) -- strategic design decisions that create long-term value. \
TC is the positive counterpart to Technical Debt.

You receive one candidate found by a rule-based detector. Decide whether it is \
genuine TC, and return JSON only, with these fields:

- is_tc: true if the code is genuine Technical Credit, false otherwise
- tc_confidence: 1-5 (1 = speculative, 5 = certain)
- tc_category: one of observability, api-stability, modularity, automation, \
abstraction, configurability
- tc_benefit: one sentence, the long-term value created
- tc_conditions: when this benefit will materialise
- tc_signals: list of short signal tags that would show the benefit being realised
- not_tc_reason: null, or the reason if is_tc is false"""

_STAGE3_V1_USER = """\
Service: {service_name}
Role in system: {service_role}
Downstream consumers: {n_consumers}
Detected pattern: {pattern_type} at {file}:{line_range}
Git history: file age {file_age}, {n_commits} commits, {n_contributors} contributors
Existing ADRs in project: {adr_titles_list}
Code snippet:
{code_snippet}"""

STAGE3_V1 = Prompt("stage3-v1", _STAGE3_V1_SYSTEM, _STAGE3_V1_USER)


_STAGE3_ADR_V1_SYSTEM = """\
You are a software architecture expert writing Architecture Decision Records \
(MADR 4.0) for Technical Credit (TC) found in a microservices system.

You receive a candidate already confirmed as TC, with its benefit and conditions. \
Return JSON only, with these fields:

- adr_title: short imperative title for the ADR
- context: 2-3 sentence ADR context section
- decision: 1-2 sentence decision statement
- consequences_good: list of strings, each starting "Good, because ..."
- consequences_bad: list of strings, each starting "Bad, because ..." """

_STAGE3_ADR_V1_USER = """\
{stage3_user}

Confirmed TC:
Category: {tc_category}
Benefit: {tc_benefit}
Conditions: {tc_conditions}"""

STAGE3_ADR_V1 = Prompt("stage3-adr-v1", _STAGE3_ADR_V1_SYSTEM, _STAGE3_ADR_V1_USER)

PROMPTS: dict[str, Prompt] = {p.version: p for p in (STAGE3_V1,)}
ADR_PROMPTS: dict[str, Prompt] = {p.version: p for p in (STAGE3_ADR_V1,)}
