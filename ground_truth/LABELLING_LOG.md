# Labelling log

Records labelling outcomes per repo, including outcomes that produce no labels,
which the label files can't show. Changes to individual labels after a freeze
go in the change log at the bottom of [GUIDELINES.md](GUIDELINES.md).

Newest entries first.

---

## 2026-11-27: cs6510-checkout-microservices @ 241caa7

- **Repo:** `cs6510-checkout-microservices` at `241caa78568f1fb19056b85d318adfd07f8326b0`
  (path `week6-events`), the held-out test set.
- **Who:** labeller D (Karan), Job A: primary labeller for Person A's patterns. Completed 2026-11-27.
- **Scope:** all 8 services found by the scanner: `analytics-service`, `architecture-tests`,
  `catalog-service`, `contracts`, `gateway`, `inventory-service`, `service-support`,
  `transaction-service`.

| Pattern | Labels | Outcome |
|---|---|---|
| `distributed-tracing` | 0 | Verdict for all 8 services: no tracing dependency, config or instrumentation in `pom.xml`, `application.properties` or code. No labels, per "Patterns the repo doesn't have" (matches PetClinic, which recorded no `false` tracing labels). |
| `structured-logging` | 0 | No labels. Near-miss skipped: `service-support` `QueryClient.java` / `QueryResponder.java` use a correlation-id Kafka header for request/reply routing, but it is not propagated to logs (no MDC, no structured/JSON log output). |
| `custom-metrics` | 0 | No labels. |

- **No rule run:** no rule had been run on this repo when these labels were made.
  There were no course-repo files in `results/` or on any branch. Only the scanner was run, with output kept out of the repo.
- **Consequence:** the `observability` category has zero positive instances in the test set,
  so test-set recall for it can't be measured.
- **Pending:**
  - Job B (D as second labeller for B's patterns): waiting on primary labels from A.
  - Job C (D as tie-breaker for C's patterns): waiting on primary (B) and second (A) labels.
  - No label file for this repo exists yet, and none was created, so the eval and the sampler
    don't treat the test set as finished.
