# Abstraction / configurability: dev-set experiments (2026-11-27)

Owner: D (Karan). Patterns `gateway`, `externalised-config`, `feature-flags`.
Prompt `stage3-abstraction-v2`, `--no-fallbacks`, no ADR fields, default effort `medium`.
PetClinic @ `e8b747ab522721076cacb5cf688eb8a54ba8c5c9`, plus the synthetic feature-flags
fixture (owner-written labels). Nothing was run on the course repo.

Total spend: **$0.069902** (96 API calls).

## Inputs (`candidates/`)

| File | What | Made by |
|---|---|---|
| `petclinic.jsonl` | 8 candidates: 1 gateway + 7 externalised-config (+0 feature-flags) | rule branches `karan/gateway-rule-fix` @ d477269, `karan/externalised-config-rule` @ 90c8569, `karan/feature-flags-rule` @ ff2f146 |
| `fixture.jsonl` | 8 feature-flags candidates | `karan/feature-flags-rule` on `tests/fixtures/feature_flags_repo` |
| `fixture-labels.json` | copy of that fixture's `labels.json` (written by the rule owner; not ground truth) | |

## Results

| # | Experiment | Result | Cost |
|---|---|---|---|
| 1 | Rules only vs. rules + Claude (Haiku) | PetClinic: both arms P 1.00 / R 1.00 for `gateway` (1/1) and `externalised-config` (7/7). Fixture: both 1.00 / 1.00 (8/8). Claude confirmed 16/16, so the two arms are identical | $0.003088 |
| 2 | Everything to Claude vs. rules prefilter | **Not run**: the wrapper can't take un-prefiltered input. Estimate for PetClinic: 77 calls, ~$0.017 (Haiku) / ~$0.32 (Sonnet). See `docs/results-abstraction.md` | $0 |
| 3 | Haiku vs. Sonnet, same 16 | Both confirmed 16/16; **verdict agreement 16/16**, same category 16/16. Sonnet's confidence is higher on 5 PetClinic candidates. Sonnet costs ~18× more per candidate ($0.0035 vs $0.00019) | Sonnet $0.055431 |
| 4 | Caching | Re-run of all 32 (Haiku + Sonnet): 32/32 cache hits, **0 new tokens, $0 spent, $0.058519 saved**. Anthropic's prompt cache also saved $0.002643 (Haiku) and $0.055803 (Sonnet) on the first runs | $0 |
| 5 | Consistency, Haiku × 5 repeats | 80 runs, **no verdict flips**: same verdict 100% for every pattern (gateway 5/5, externalised-config 35/35, feature-flags 40/40). Confidence varied on 2 candidates: `api-gateway` [4,4,5,5,5] and `RatingsConfig.java:20-23` [3,4,3,4,4] | $0.011383 |

`eval.report`'s PetClinic recall row (0.24, 8/33) divides by all 33 PetClinic labels, for
every owner's patterns. For these two patterns it is 8/8 (see `exp1-rules-vs-claude/scores.txt`).

## Files

- `exp1-rules-vs-claude/`: Haiku verdicts, the confirmed-only candidate files, `scores.txt` (eval.score), `report.md` (eval.report), `cost_log.jsonl`
- `exp3-models/`: Sonnet and Haiku verdicts, `report.md` (one table per model), `cost_log-sonnet.jsonl`. The Haiku arm's cost log is `exp1-rules-vs-claude/cost_log.jsonl`
- `exp4-cache/`: re-run verdicts, `cost_log.jsonl` (all cache hits), `report.md`
- `exp5-consistency/`: 5 repeats per candidate, `cost_log.jsonl`, `report.md`
