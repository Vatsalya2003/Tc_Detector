# TC Detector

Finds candidate Technical Credit (TC) in Java microservice repos: rules emit
candidates, Claude confirms or rejects each one, and everything is scored
against hand-made labels. CS6510, Fall 2026.

> Work in progress. See `CLAUDE.md` for the pipeline, owners and conventions.
> The sections below cover the Claude wrapper (`llm/`) and the resilience rules.

## Setup

```bash
uv sync                          # installs dependencies into .venv
cp .env.example .env             # then paste the API key you got by direct message
uv run python scripts/check_api_key.py
uv run pytest                    # offline: no key, no cost
```

## Claude wrapper (S1, S5)

```bash
# Show exactly what would be sent, without calling the API
uv run tc-attribute examples/demo-candidate.json --dry-run

# One candidate -> verdict JSON (docs/contracts/claude-verdict.md)
uv run tc-attribute examples/demo-candidate.json

# Run it again: served from .tc_cache/, 0 tokens, $0
```

| Flag | Default | Purpose |
|---|---|---|
| `--model` | `claude-sonnet-5-5` | `claude-haiku-5-5` for the smaller-model arm of Experiment 3 |
| `--effort` | `medium` | Thinking depth; thinking bills as output tokens |
| `--repeats N` | 1 | Consistency experiment: N real calls per candidate |
| `--adr` | off | Second call for the ADR fields, confirmed TC only. Off in every experiment |
| `--no-cache` | off | Always call the API |
| `--out FILE` | stdout | Append verdicts as JSON Lines |

Every call, including cache hits, is appended to `results/cost_log.jsonl`
(tokens, dollars, and `saved_usd` on hits).

## Resilience rules (S11)

```bash
uv run tc-rules-resilience --repo targets/spring-petclinic-microservices --out results/spring-petclinic-microservices/candidates-resilience.jsonl
```

What the rule detects and why: `src/tc_detector/rules/resilience/circuit_breaker.py`
(module docstring) and `docs/patterns/resilience.md`.
