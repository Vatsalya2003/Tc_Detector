# Synthetic fixture: `feature-flags`

The team project plan says:

> If a pattern has no real instances in our target repos, its owner adds a small
> synthetic test fixture and reports that pattern separately.

PetClinic (the development set) has no feature flags, so this small fake repo stands in
for one. It is **not ground truth**, and that's why it sits under `tests/fixtures/` instead of `ground_truth/`.

- `labels.json` was **written by the rule owner (D)**, from the same guideline the rule
  follows. So the fixture score shows that the code behaves as intended. It is **not**
  a measure of real accuracy.
- Report its numbers separately from PetClinic and from the held-out test set.

## Contents

| Service | Positives (in `labels.json`) | Negatives (no label; must not fire) |
|---|---|---|
| `ratings-service` | A: `@ConditionalOnProperty` on `petclinic.features.vet-ratings` (the guideline's example) and on `ratings.beta.enabled` (prefix + name, multi-line). B: `if (showStars)` on a `@Value` boolean | `@ConditionalOnProperty` on `spring.cache.enabled` and `management.metrics.enabled` (framework keys); `@Profile("production")`; a commented-out annotation; `if` on a `@Value` timeout (`int`), on a framework `@Value` boolean (`spring.cloud.discovery.enabled`), and on `spring.profiles.active`; property lines in `application.yml`, including the framework switch `spring.ai.chat.client.enabled` |
| `billing-service` (Unleash and LaunchDarkly dependencies) | C: `unleash.isEnabled("…")` (generic, so it needs the dependency); `ldClient.boolVariation(…)` | the property lines in `application.properties` |
| `catalog-service` (no flag-library dependency) | C: Togglz `CatalogFeatures.NEW_SEARCH.isActive()`, OpenFeature `client.getBooleanValue(…)`, FF4J `ff4j.check(…)` (library-specific calls, so no dependency needed) | unrelated `account.isEnabled()` and `validator.isEnabled("strict")` |

## Score it

```sh
uv run python -m tc_detector.rules.abstraction.feature_flags tests/fixtures/feature_flags_repo \
    --repo-name feature-flags-fixture --commit 0000000000000000000000000000000000000000 \
    > /tmp/ff-fixture.jsonl
uv run python -m tc_detector.eval.score --candidates /tmp/ff-fixture.jsonl \
    --labels tests/fixtures/feature_flags_repo/labels.json
```

The Java files don't compile, and they don't need to. The rule only reads their text.
