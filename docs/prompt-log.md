# Prompt log

Every Stage 3 prompt version, why it changed, and what it scored on the
development set. Prompts live in `src/tc_detector/llm/prompts.py`; a released
version is never edited in place.

| Version | Date | Change | Dev precision | Dev recall | Notes |
|---|---|---|---|---|---|
| stage3-v1 | 2026-11-11 | Professor's spec template. Static field descriptions moved into the system prompt (cacheable); ADR fields split into `stage3-adr-v1`, requested only with `--adr`; categories limited to the team's six (`contracts/enums.py`) | — | — | Baseline for all categories |
