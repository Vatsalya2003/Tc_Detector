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


# stage3-abstraction-v1 (owner D, Karan): stage3-v1 plus guidance for the abstraction and
# configurability patterns (gateway, externalised-config, feature-flags), drawn from
# ground_truth/GUIDELINES.md. Same user template and same output schema as stage3-v1; only
# the system prompt grows, and it stays one stable, cacheable prefix.
_STAGE3_ABSTRACTION_V1_SYSTEM = (
    _STAGE3_V1_SYSTEM
    + """

The candidate comes from a rule for one of three patterns. "is_tc: true" means a \
candidate Technical Credit backed by the evidence shown, not proven credit. For \
service-level candidates the snippet is the rule's evidence, one finding per line: \
"strong:" and "signal:" lines are what made the rule fire; "weak:" lines support it; \
"supporting:" lines are context only and never enough on their own.

Pattern "gateway" (tc_category: abstraction)
- Genuine TC: one service is the single entry point and routes requests to the other \
services: route definitions to backend services (spring.cloud.gateway routes, lb:// \
URIs), clients call it instead of the services directly, and cross-cutting filters \
(circuit breaker, retry, auth) are applied in one place.
- Not TC: a service registry such as Eureka (discovery-server) helps services find \
each other but routes no traffic. A plain REST controller in a business service is not \
a gateway. Aggregation endpoints inside the gateway are part of the same gateway.
- Benefit to explain: backend services can be split, moved, renamed or replaced, and \
cross-cutting policy changed, by editing one place instead of every client.
- Conditions: when the backend topology changes, a service is added or replaced, or a \
policy such as retry, timeouts or auth has to change for every route.

Pattern "externalised-config" (tc_category: configurability)
- Genuine TC: the service loads its configuration from outside its own code, so a \
config change needs no rebuild: spring.config.import pointing at configserver: (the \
"optional:" prefix still counts), or a bootstrap file setting spring.cloud.config.uri.
- Not TC: the config server itself (it serves config to others; its own config is \
local). ${ENV_VAR} placeholders alone. Imports of local files such as \
optional:classpath:/creds.yaml.
- Benefit to explain: settings (URLs, credentials, tuning values) change per \
environment or at run time, from one place, without rebuilding or redeploying the \
service.
- Conditions: when the same build runs in several environments, or a setting must \
change quickly in production.

Pattern "feature-flags" (tc_category: configurability)
- Genuine TC: a named on/off switch that turns one app feature on or off without a \
code change: @ConditionalOnProperty on an app feature, an if on a flag value (a \
@Value boolean, flags.isEnabled("x")), or a feature-flag library (Unleash, FF4J, \
LaunchDarkly, Togglz, OpenFeature, Flagsmith).
- Not TC: @Profile and spring.profiles.active switch a whole environment, not one \
feature. Framework auto-configuration switches such as spring.ai.chat.client.enabled \
(spring.*, management.* and similar "*.enabled" keys) are not app feature flags. A \
timeout or a URL is config, not a flag.
- Benefit to explain: a feature can be released dark, rolled out gradually, or turned \
off quickly, without a code change or redeploy.
- Conditions: when a risky or unfinished feature ships, or must be disabled in \
production without a release.

Use the tc_category given for the pattern above. If the evidence shows one of the "Not \
TC" cases, or does not show what makes the pattern genuine, set is_tc to false and \
say which in not_tc_reason."""
)

STAGE3_ABSTRACTION_V1 = Prompt(
    "stage3-abstraction-v1", _STAGE3_ABSTRACTION_V1_SYSTEM, _STAGE3_V1_USER
)


# stage3-abstraction-v2 (owner D): v1 plus one rule, because v1 listed signals the snippet
# didn't show (e.g. "clients call gateway instead of services directly" for api-gateway).
_STAGE3_ABSTRACTION_V2_SYSTEM = (
    _STAGE3_ABSTRACTION_V1_SYSTEM
    + """

Only list tc_signals that appear in the code snippet. Anything you can't verify from \
the snippet (e.g. whether clients call the gateway, who sets a flag) goes in \
tc_conditions as an assumption, not in tc_signals."""
)

STAGE3_ABSTRACTION_V2 = Prompt(
    "stage3-abstraction-v2", _STAGE3_ABSTRACTION_V2_SYSTEM, _STAGE3_V1_USER
)


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

PROMPTS: dict[str, Prompt] = {
    p.version: p for p in (STAGE3_V1, STAGE3_ABSTRACTION_V1, STAGE3_ABSTRACTION_V2)
}
ADR_PROMPTS: dict[str, Prompt] = {p.version: p for p in (STAGE3_ADR_V1,)}
