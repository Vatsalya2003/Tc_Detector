# TC Detector

Python 3.11 CLI (`tc-detect`) that finds **Technical Credit (TC)** candidates in Java microservice repos.
TC is the opposite of technical debt: design decisions that make future change cheap (e.g. one gateway
wrapping a vendor API, so switching vendors touches one place). We find **candidates with evidence**, never proven credit.

## Pipeline
1 **Scan** services/files → 2 **Rules** (12 detectors, one shared candidate format) → 3 **Claude** confirms/rejects →
4 **Evaluate** against human labels (precision/recall) → 5 **Report** accuracy + cost per repo

The candidate format is **frozen as of Nov 11**: changing it breaks every rule, the LLM wrapper and
evaluation, so **get team agreement first**.

## Team / ownership (CS6510, 4 people)
| Person   | Owns |
|----------|------|
| Vatsalya | Observability rules (tracing, correlation-ID logging, custom metrics), scanner, candidate format |
| Abhi     | Contracts rules, evaluation |
| Neil     | Resilience rules, Claude wrapper (`llm/`) |
| Karan    | Abstraction/config rules, ground-truth labels, pinned repos, CI |

Dev repo: **PetClinic Microservices**. Held-out: Abhi's CS6510 checkout system, **scored once after Dec 1**; never tune on it.

## Rules folders (by owner) → categories (from each pattern)
| Folder (owner) | Categories its rules emit |
|---|---|
| `observability/` (Vatsalya) | `observability` |
| `contracts/` (Abhi) | `api-stability`, `modularity` |
| `resilience/` (Neil) | `automation`, `modularity` |
| `abstraction/` (Karan) | `abstraction`, `configurability` |

## Layout
```
src/tc_detector/
  contracts/            shared candidate format; read in this order:
    enums.py            Unit and Category (allowed values)
    ids.py              build_id(), naming regexes, snippet size limit
    checks.py           validation rules, one function per topic
    candidate.py        Candidate dataclass, create(), save/load (JSON)
  scanner/              repo inventory
  rules/<owner-area>/   observability, contracts, resilience, abstraction
  llm/                  Claude wrapper
  eval/                 scoring against labels
  cli.py                entry point
schemas/                JSON Schemas
tests/                  mirrors src/
ground_truth/           human labels (planned)
results/                run outputs
docs/decisions/         decision records (planned)
targets.yaml            pinned target repos
```

## Commands
`uv sync` (install) · `uv run pytest` (test) · `uv run ruff check .` (lint) · `uv run ruff format .` (format)

## Conventions
- Every rule returns `list[Candidate]`; `rule_id` starts with the category (`observability-tracing-01`).
- Keep `snippet` short (max 2000 chars). It is sent to Claude and drives cost.
- Never commit API keys; use `.env` (see `.env.example`).
