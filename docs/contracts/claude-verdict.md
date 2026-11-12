# Claude verdict format (draft for approval, Nov 11)

Owner: Neil (C). Produced by `tc_detector.llm`, one verdict per candidate.
Freezes with the candidate and label formats on **Wed Nov 11**; after that,
changing a field needs agreement from all four.

## Example

```json
{
  "candidate_id": "demo-shop:orders:src/main/java/shop/orders/PaymentClient.java:6-14:circuit-breaker",
  "is_tc": true,
  "tc_confidence": 4,
  "tc_category": "automation",
  "tc_benefit": "Checkout keeps working during a payment-provider outage, because failed charges are queued instead of failing the order.",
  "tc_conditions": "Pays off when the payment provider is slow or down, or is swapped for another provider.",
  "tc_signals": ["circuit-breaker-open-events", "fallback-invocation-rate"],
  "not_tc_reason": null,

  "model": "claude-sonnet-5-5",
  "input_tokens": 417,
  "output_tokens": 262,
  "cost_usd": 0.005519,
  "cache_hit": false,

  "prompt_version": "stage3-v1",
  "cache_read_input_tokens": 0,
  "cache_creation_input_tokens": 826,
  "repeat": 0,
  "error": null
}
```

## Fields

### Agreed in the v3 plan (spec Stage 3 fields + cost fields)

| Field | Type | Meaning |
|---|---|---|
| `candidate_id` | string | `id` of the candidate this verdict is for (join key with the candidate file) |
| `is_tc` | bool \| null | Claude's call: is this genuine Technical Credit? `null` only when `error` is set |
| `tc_confidence` | int 1–5 \| null | 1 = speculative, 5 = certain |
| `tc_category` | enum \| null | One of the team's 6 (`contracts/enums.py` `Category`): `observability`, `api-stability`, `modularity`, `automation`, `abstraction`, `configurability`. The spec's other two are a stretch goal |
| `tc_benefit` | string \| null | One sentence: the long-term value created |
| `tc_conditions` | string \| null | When that benefit materialises |
| `tc_signals` | string[] | Observable signal tags (empty when `is_tc` is false) |
| `not_tc_reason` | string \| null | Why it is not TC; `null` when `is_tc` is true |
| `model` | string | Model that **served** the call (can differ from the requested one if a refusal fallback ran) |
| `input_tokens` | int | Uncached input tokens billed **on this run** (0 on a cache hit) |
| `output_tokens` | int | Output tokens billed on this run, thinking included (0 on a cache hit) |
| `cost_usd` | float | Dollars spent **on this run** (0 on a cache hit) |
| `cache_hit` | bool | `true` = answer came from our local response cache, no API call was made |

### Proposed additions (please approve or strike)

| Field | Type | Why we need it |
|---|---|---|
| `prompt_version` | string | Experiments and the prompt log compare prompt versions; without this, results from different prompts mix silently |
| `cache_read_input_tokens` | int | Anthropic prompt-cache reads are billed separately from `input_tokens`; Experiment 4 needs them |
| `cache_creation_input_tokens` | int | Same, for prompt-cache writes |
| `repeat` | int | Run index 0–4 for the consistency experiment (Experiment 5). Repeats get separate cache entries, so five repeats are five real calls |
| `error` | string \| null | `refusal`, `max_tokens` or `invalid_json`; when set, the verdict fields are `null` and the evaluator should count the candidate as "no verdict" |

### Only with `--adr` (off in every experiment)

Requested in a **second** call, and only when `is_tc` is true, so they never
add output tokens to the experiments. Cost fields then cover both calls.

`adr_title`, `context`, `decision`, `consequences_good` (string[]),
`consequences_bad` (string[]) — exactly as in the spec's Stage 3 template, so
MADR export (stretch) is a template over these fields.

## Rules the other formats rely on

- One verdict per `(candidate_id, prompt_version, model, repeat)`.
- Verdicts are written as JSON Lines: one object per line, `results/<repo>/<run>/verdicts.jsonl`.
- Every API call (including cache hits) is also logged to `results/cost_log.jsonl`;
  Abhi's cost report reads that file. A cache-hit row carries `saved_usd`, the
  cost of the original call, so Experiment 4 can report savings directly.
- Scoring is always against the human labels; `is_tc` is never used as ground truth.
- The wrapper validates every candidate with `Candidate.from_dict()` before calling
  Claude, so a malformed candidate fails fast and costs nothing.

## Open questions for the team

1. Pattern slugs: I propose `circuit-breaker`, `health-check`, `saga` for mine.
   Can we fix all 12 slugs today alongside the candidate format?
2. `repo` value: `Candidate` comments say `petclinic`, the label format proposes the
   `targets.yaml` name (`spring-petclinic-microservices`). My rules default to the
   targets.yaml name; candidates and labels must use the same string or nothing matches.
3. Default model `claude-sonnet-5-5` (current Sonnet; the spec's `claude-sonnet-4-6`
   is the previous generation and costs more) and `claude-haiku-5-5` as the
   "smaller" model for Experiment 3?
