# Labelling guidelines (S6)

Use this file while labelling. Field rules live in [LABEL_FORMAT.md](LABEL_FORMAT.md).

## What a label is

- A label is one human judgment: "is this pattern present at this place?"
- `is_tc: true` means a **candidate** Technical Credit, with evidence.
- It never means proven credit. We can't prove the change got cheaper.
- `is_tc: false` means you looked and judged it absent (often a near-miss).

## PetClinic commit

All PetClinic paths and line numbers below refer to commit
`e8b747ab522721076cacb5cf688eb8a54ba8c5c9`.
Check out that commit before labelling.

## How to label

### Order

1. Read this file.
2. Label the repo using **only** these guidelines.
3. Do this **before** you see any rule output or Claude output.

### Who labels what

Owners never label or adjudicate their own patterns.

| Owner's patterns | Primary | Second | Tie-break |
|---|---|---|---|
| A (Vatsalya) | D | C | B |
| B (Abhi) | A | D | C |
| C (Neil) | B | A | D |
| D (Karan) | C | B | A |

A = Vatsalya, B = Abhi, C = Neil, D = Karan.

### Agreement sample

- Draw a random 20% of each pattern's labels, rounded up, so a pattern with one label still gets it checked.
- The seed is fixed in advance: **2026**. Always draw with it.
  Anyone can then redraw the same sample to check it, and nobody can redraw until they like the result.
- For each label in the sample, the second labeller judges that pattern at that place: present or absent.
- The second labeller must not see the primary's answers first.
- Disagreements: see "Second labeller and disagreements" in LABEL_FORMAT.md.

Run it with `eval/agreement.py`, from the repo root, once the primary labels are frozen:

1. Draw the sample. This writes a worksheet with no answers on it:

   ```sh
   uv run python -m tc_detector.eval.agreement sample --labels ground_truth/petclinic.json \
       --seed 2026 --out ground_truth/petclinic-agreement.json
   ```

2. Second labellers: find the rows with your letter in `second_labeller`.
   Set `second_is_tc` to `true` or `false` on each one.
   Don't open `petclinic.json` until you're done.
3. Copy the answers into the label file.
   If an answer disagrees with the primary's, this lists it and writes nothing.
   Settle it, fill in `adjudicated_by` and `final_is_tc` on that row, and run it again.

   ```sh
   uv run python -m tc_detector.eval.agreement merge --labels ground_truth/petclinic.json \
       --worksheet ground_truth/petclinic-agreement.json
   ```

4. Print agreement and Cohen's kappa:

   ```sh
   uv run python -m tc_detector.eval.agreement kappa --labels ground_truth/petclinic.json
   ```

   Most labels are `is_tc: true`, so kappa is often `n/a` or near 0 even when agreement is high.
   Report both numbers.

### Where labels go

- One file per repo, e.g. `ground_truth/petclinic.json`.
- `repo` is the `name` from `targets.yaml`: `spring-petclinic-microservices`.
- Validate before you push:

```sh
uv run python -c "from tc_detector.contracts.label import load_labels; load_labels('ground_truth/petclinic.json')"
```

### After a freeze

- Once labels are frozen, every change gets a line in the change log at the bottom of this file.
- Write: date, `label_id`, what changed, why, who.

### How to write `service` and `file`

- `file`: path relative to the service root, with `/`.
  Example: `src/main/resources/application.yml`.
  (Defined in `checks.py` and LABEL_FORMAT.md.)
- `service`: written as in the contract tests, e.g. `api-gateway`, `customers-service`, `config-server`.
- **Agreed by everyone:** use `spring.application.name` from the service's `application.yml`.
  So `spring-petclinic-api-gateway/` becomes `api-gateway`.
  If no name is set, fall back to the folder name minus the prefix all service folders share.
  So `spring-petclinic-config-server/` becomes `config-server`.
- **Known limitation:** files outside any service can't be labelled.
  Example: the root `docker-compose.yml` and root `pom.xml`.

### Patterns the repo doesn't have

**Decided by B.**

- If nothing in the repo qualifies for a pattern, that pattern gets no labels. That's fine.
- Don't label its near-misses (files that look close but don't qualify) as `is_tc: false`. Skip them.
  Example: PetClinic's controllers for `versioned-api`, or its `@EventListener` class for `event-schema-versioning`.
- Why: a `false` label doesn't change the score.
  A candidate that matches it is a false positive, the same as a candidate that matches no label.
  Easy "no" labels would also land in the agreement sample and make agreement look higher than it is.
- The negative examples below show what doesn't count. You don't have to find and label every file like them.

### `file` units: types nested inside another class

- A type declared inside another class or record (e.g. a nested `record`) gets no label of its own.
  It's covered by the label for the file it sits in.
- Why: a `file` label has no line numbers, so a second label for the same file and pattern gets the same `label_id`.
  `load_labels` rejects duplicate ids.
- Give the file one label per pattern: `is_tc: true` if any type in it qualifies.
  Name the type that qualifies in `notes`, e.g. `Outer.Inner`.

## Patterns at a glance

| Pattern | Category | Owner | Unit |
|---|---|---|---|
| `gateway` | abstraction | D | service |
| `externalised-config` | configurability | D | service |
| `feature-flags` | configurability | D | line_range |
| `distributed-tracing` | observability | A | service (confirmed by owner) |
| `structured-logging` | observability | A | file (confirmed by owner) |
| `custom-metrics` | observability | A | line_range (confirmed by owner) |
| `versioned-api` | api-stability | B | file (confirmed by owner) |
| `immutable-data-contracts` | api-stability | B | file (confirmed by owner) |
| `event-schema-versioning` | modularity | B | file (confirmed by owner) |
| `circuit-breaker-retry` | automation | C | line_range (confirmed by owner) |
| `health-checks` | automation | C | service (confirmed by owner) |
| `saga` | modularity | C | service (confirmed by owner) |

In the PetClinic paths below, `.../` stands for `src/main/java/org/springframework/samples/petclinic/`.
In the label itself, always write the full path.

---

## `gateway`

**What it is:** one service that is the single entry point and routes requests to the other services.

**Counts as TC:**
- Route definitions to backend services (`spring.cloud.gateway...routes`, `lb://...`).
- Clients call the gateway, not the services directly.
- Cross-cutting filters (circuit breaker, retry, auth) applied in one place.

**Matching unit:** `service`. One label for the gateway service.

**Positive example:** service `api-gateway`.
Evidence: `src/main/resources/application.yml` lines 20-45 (routes to vets, visits, customers, genai).

**Negative example:** service `discovery-server`, `is_tc: false`.
It is a service registry (Eureka). It helps services find each other but routes no traffic.

**Edge cases:**
- Aggregation endpoints inside the gateway (`ApiGatewayController`) belong to the same label. Don't add more.
- A plain REST controller in a business service is not a gateway.

---

## `externalised-config`

**What it is:** the service loads its config from outside its own code, so config changes need no rebuild.

**Counts as TC:**
- `spring.config.import` pointing at `configserver:`.
- The `optional:` prefix still counts.

**Matching unit:** `service`. One label per service that loads config from outside.

**Positive examples:** 7 services, all `is_tc: true`. Evidence in each `src/main/resources/application.yml`:

| Service | Lines |
|---|---|
| `admin-server` | 4-5 |
| `api-gateway` | 4-5 |
| `customers-service` | 4-5 |
| `discovery-server` | 4-5 |
| `genai-service` | 8-9 |
| `vets-service` | 4-5 |
| `visits-service` | 4-5 |

**Negative example:** service `config-server`, `is_tc: false`.
Note: "Serves config to others; its own config is local (application.yml), not loaded from outside."

**Edge cases:**
- `${ENV_VAR}` placeholders alone (e.g. `${OPENAI_API_KEY}`) don't make a service positive.
  The service must import config from outside.
- `optional:classpath:/creds.yaml` is a local file, not external. genai-service is positive because of its `configserver:` import.

---

## `feature-flags`

**What it is:** a named on/off switch that turns one app feature on or off without a code change.

**Counts as TC:**
- `@ConditionalOnProperty` on an app feature.
- An `if` on a flag value (`flags.isEnabled("x")`, a `@Value` boolean).
- A feature-flag library (Unleash, FF4J, LaunchDarkly, Togglz).

**Matching unit:** `line_range`.
The range covers the check: the annotation line, or the `if` line with its condition.
Don't label the property line in the YAML.

**Positive example (synthetic):** PetClinic has none.

```java
@Bean
@ConditionalOnProperty(name = "petclinic.features.vet-ratings", havingValue = "true")
VetRatingService vetRatingService() { ... }
```

Label the `@ConditionalOnProperty` line.

**Negative examples:**
- vets-service `.../vets/system/CacheConfig.java` line 28: `@Profile("production")`.
  A profile switches a whole environment, not one feature.
- genai-service `src/main/resources/application.yml` lines 10-13: `spring.ai.chat.client.enabled`.
  This is a framework auto-config switch, not an app feature flag.

**Edge cases:**
- `spring.profiles.active` is not a flag.
- A setting like a timeout or a URL is config, not a flag. A flag is on/off for a feature.

---

## `distributed-tracing`

**What it is:** requests carry a trace across services, so one call can be followed end to end.

**Counts as TC** (either one is enough):
- The service's build file has a tracing dependency (`spring-boot-starter-zipkin`, `micrometer-tracing-bridge-*`, OpenTelemetry).
  A dependency alone counts.
- The service has explicit tracing code: annotations (`@Observed`, `@NewSpan`) or manual spans (`tracer.nextSpan()`).

**Matching unit:** `service` (confirmed by owner). One label per service.
`file`, `line_start` and `line_end` are `null`. Put the evidence in `notes`.

**Positive example:** service `customers-service`.
Evidence: `pom.xml` lines 47-50 (`spring-boot-starter-zipkin`).
api-gateway, vets-service, visits-service and genai-service have the same dependency. Label each one.

**Negative example:** service `discovery-server`, `is_tc: false`.
No tracing dependency and no tracing code.

**Edge cases:**
- `micrometer-registry-prometheus` is metrics, not tracing.
- `reactor.context-propagation: auto` (api-gateway `application.yml` lines 46-47) passes context between threads.
  On its own it doesn't make a service positive.
- The Zipkin server (`tracing-server`) in the root `docker-compose.yml` is not a service label. It's outside any service.

---

## `structured-logging`

**What it is:** logs have a fixed machine-readable shape and carry a correlation/trace ID across services.
(This is the "correlation-ID logging" pattern from CLAUDE.md.)

**Counts as TC** (confirmed by owner). Only explicit correlation-ID setup counts:
- `MDC.put` of a correlation or trace ID (e.g. `MDC.put("correlationId", ...)`).
- A logging pattern that includes `traceId` or `correlationId` (e.g. `%X{traceId}` in logback, or in `logging.pattern.*`).

**Matching unit:** `file` (confirmed by owner).
One label for the file that does the setup: the Java file with the `MDC.put`, or the logging config file with the pattern.
`line_start` and `line_end` are `null`.

**Positive example (synthetic):** PetClinic has none.

```java
// src/main/java/x/CorrelationIdFilter.java
MDC.put("correlationId", request.getHeader("X-Correlation-Id"));
try { chain.doFilter(request, response); }
finally { MDC.remove("correlationId"); }
```

Label the whole file `src/main/java/x/CorrelationIdFilter.java`.

**Negative examples:**
- Plain log statements: customers-service `.../customers/web/OwnerResource.java`, `is_tc: false`.
  Line 89 `log.info("Saving owner {}", ownerModel);` logs data, but sets up no correlation ID.
- customers-service `src/main/resources/logback-spring.xml`, `is_tc: false`.
  It uses Spring's default `base.xml`: no `traceId` or `correlationId` in the pattern.

**Edge cases:**
- A JSON log encoder (`LogstashEncoder`) or `logging.structured.format.*` without a trace/correlation ID doesn't count.
- Setting log levels (`logging.level...`) doesn't count.
- `log.info("owner " + id)` doesn't count, even if it logs an ID.

---

## `custom-metrics`

**What it is:** the app defines its own named metrics for business operations.

**Counts as TC** (confirmed by owner):
- `@Timed` or `@Counted` on a class or method.
- `MeterRegistry` counter, timer or gauge calls: `meterRegistry.counter(...)`, `.timer(...)`, `.gauge(...)`,
  or `Counter.builder(...)`, `Timer.builder(...)`, `Gauge.builder(...)`.

**Matching unit:** `line_range` (confirmed by owner).
The range covers the annotation line, or the one statement that creates the meter.

**Positive example:** customers-service `.../customers/web/OwnerResource.java` line 41: `@Timed("petclinic.owner")`.
Also `.../customers/web/PetResource.java` line 37 and visits-service `.../visits/web/VisitResource.java` line 45.
Label each one.

**Negative example:** customers-service `pom.xml` lines 78-81 (`micrometer-registry-prometheus`), `is_tc: false`.
The Prometheus registry dependency alone only exports metrics. It defines no metric of its own.

**Edge cases:**
- `MetricConfig.java` lines 13-16 (`.../customers/config/`) add a common tag to all metrics but define no new metric.
- The `TimedAspect` bean (`MetricConfig.java` lines 18-21) only makes `@Timed` work. Don't label it on its own.

---

## `versioned-api`

**What it is:** the API contract is written down in a spec file that carries a version.

**Counts as TC:**
- An OpenAPI/Swagger file (`openapi.yaml`, `swagger.json`) with `info.version` and/or `/v1/` paths.
- A `.proto` file with a versioned package (`package petclinic.v1;`).

**Matching unit:** `file` (confirmed by owner). The spec file.

**Positive example (synthetic):** PetClinic has no spec files.

```yaml
# src/main/resources/openapi.yaml
openapi: 3.0.3
info: { title: Customers API, version: 1.2.0 }
paths:
  /v1/owners/{ownerId}: { get: { ... } }
```

**Negative example:** customers-service `.../customers/web/OwnerResource.java`, `is_tc: false`.
It has `@RequestMapping("/owners")` on line 39: no spec file, no version.

**Edge cases:**
- The Maven `<version>` in `pom.xml` is the build version, not the API version.
- A spec with no version and no versioned paths is `is_tc: false`.

---

## `immutable-data-contracts`

**What it is:** the objects sent between services can't be changed after creation and tolerate new fields.

**Counts as TC:**
- A DTO that is a Java `record`.
- A DTO with Lombok `@Value`.
- A DTO with `@JsonIgnoreProperties(ignoreUnknown = true)`.

**Matching unit:** `file` (confirmed by owner). One label per DTO file.
`line_start` and `line_end` are `null`.

**Positive example:** api-gateway `.../api/dto/OwnerDetails.java`.
Line 25: `public record OwnerDetails(`.

**Negative example:** customers-service `.../customers/model/Owner.java`, `is_tc: false`.
A JPA `@Entity` (line 37) with setters (from line 123). Mutable, and a database model, not a wire contract.

**Edge cases:**
- A record with a `List` field is only shallowly immutable.
  `OwnerDetails` still counts by the signals above. Say so in `notes`.
- A nested builder inside a record (`OwnerDetails` line 42) doesn't change the verdict.
- Records used only inside one service (not sent over the wire) are not contracts.

---

## `event-schema-versioning`

**What it is:** events between services have a schema file that can evolve without breaking readers.

**Counts as TC:**
- An Avro `.avsc` or `.proto` file for an event.
- New fields have defaults (Avro) or new field numbers (proto).
- A schema registry or a version in the name/namespace.

**Matching unit:** `file` (confirmed by owner). The schema file.

**Positive example (synthetic):** PetClinic has no events.

```json
{ "type": "record", "name": "VisitCreated", "namespace": "petclinic.events.v1",
  "fields": [ { "name": "petId", "type": "int" },
              { "name": "note", "type": ["null", "string"], "default": null } ] }
```

**Negative example (synthetic):** a Java event class sent as plain JSON, with no schema file.

```java
public class VisitCreated { public int petId; public String note; }
```

**Edge cases:**
- A `.proto` used only for request/response APIs belongs to `versioned-api`, not here.

---

## `circuit-breaker-retry`

**Slug** (confirmed by owner): write exactly `circuit-breaker-retry` in `pattern`, in labels and candidates.
Not `circuit-breaker` or `circuit-breaker-and-retry`, or nothing will match.

**What it is:** calls to another service stop or retry automatically when that service fails.

**Counts as TC:**
- `CircuitBreaker` or `Retry` filters in gateway config.
- `cbFactory.create(...).run(..., fallback)`, `@CircuitBreaker`, `@Retry`, `@Retryable`.
- A Resilience4j config bean.

**Matching unit:** `line_range` (confirmed by owner).
The range covers the whole filter/config block, or the lines from `create` to `run`.

**Positive examples (api-gateway):**
- `src/main/resources/application.yml` lines 10-19 (default `CircuitBreaker` + `Retry` filters).
- `src/main/resources/application.yml` line 45 (genai route breaker).
- `.../api/boundary/web/ApiGatewayController.java` lines 59-62 (`cbFactory.create` ... `cb.run`).
- `.../api/ApiGatewayApplication.java` lines 84-90 (default Resilience4j config).

**Negative example (synthetic):** a timeout alone.

```java
webClient.get().uri(url).retrieve().bodyToMono(Vet.class).timeout(Duration.ofSeconds(2));
```

It fails fast but doesn't retry or open a breaker.

**Edge cases:**
- `FallbackController` alone is just an endpoint. It's covered by the breaker labels above. Don't label it separately.
- `retries:` in the root `docker-compose.yml` healthchecks is outside any service. Don't label it.

---

## `health-checks`

**What it is:** the service exposes a health endpoint that tools can poll to restart or route around it.

**Counts as TC:**
- `spring-boot-starter-actuator` (gives `/actuator/health`).
- A custom `HealthIndicator`.
- Kubernetes liveness/readiness probes inside the service folder.

**Matching unit:** `service` (confirmed by owner). One label per service.
A working `/actuator/health` is a property of the whole service, not of one file or line.

**Positive example:** service `customers-service`.
Evidence: `pom.xml` lines 25-28 (`spring-boot-starter-actuator`).
api-gateway, vets-service, visits-service and genai-service also have it.

**Negative example:** service `config-server`, `is_tc: false`.
No actuator dependency. The root `docker-compose.yml` curls its root URL, but that file is outside the service.

**Edge cases:**
- Health of a whole stack in a root compose file can't be labelled (see known limitation).

---

## `saga`

**What it is:** a business action across several services, where each step has a compensating undo step.

**Counts as TC:**
- An orchestrator that calls steps and runs compensations on failure.
- Event handlers that undo earlier steps (choreography).
- Saga libraries (Axon, Eventuate, Temporal workflows).

**Matching unit:** `service` (confirmed by owner).
One saga is always exactly one label:
- **Orchestration:** label the service that coordinates the saga.
- **Choreography** (no coordinator; services react to each other's events): label the service that starts the saga.

**Positive example (synthetic):** PetClinic has none.

```java
try { visits.book(petId, slot); billing.charge(ownerId, fee); }
catch (ChargeFailed e) { visits.cancel(petId, slot); }  // compensation
```

**Negative example:** service `api-gateway`, `is_tc: false`.
`.../api/boundary/web/ApiGatewayController.java` lines 54-66 call customers and visits, but read-only, with no compensation.

**Edge cases:**
- A single local `@Transactional` is not a saga.
- Calls to several services without an undo step are not a saga.
- Choreography saga: the services that only react to events and compensate get no label of their own.
  Only the service that publishes the first event gets one label.

---

## Change log

Record every change after a freeze here.

| Date | label_id | Change | Reason | Who |
|---|---|---|---|---|
