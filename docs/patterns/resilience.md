# Resilience patterns (owner: Neil, C)

## In one sentence each

- **Circuit breaker and retry** (`circuit-breaker`, automation): a service wraps
  its calls to another service so that failed calls are retried a few times and,
  if that service keeps failing, calls stop and a fallback answer is served
  instead, which means one slow or broken service can't take its callers down
  with it, and the credit pays off whenever that dependency goes down.
- **Health checks** (`health-check`, automation): each service reports whether
  it is alive and ready for traffic, so the platform can restart it or route
  around it automatically, and the credit pays off at every crash and every
  rolling deploy that needs no human.
- **Saga** (`saga`, modularity): a transaction that spans several services runs
  as a chain of local steps, each with an "undo" step, so every service keeps its
  own database yet the system still ends up consistent when a step fails halfway,
  and the credit pays off when you add a step or split a service without a
  distributed lock.

Where these patterns occur in PetClinic is deliberately not written here: Abhi
labels them, and must do so from the guidelines alone. Owner notes on the
development set are added after labels freeze on Nov 20.

## Questions for the labelling guidelines (Karan, S6)

1. Circuit breaker unit: I emit one candidate per **method** (Java) or per
   **filter list / config block** (YAML). The guideline should say the same, or
   one-to-one matching will count the extra granularity as false positives.
2. Do adjacent `circuitbreaker:` and `retry:` blocks under `resilience4j:` form
   one unit or two? The rule currently merges adjacent blocks into one.
3. Does a dependency in `pom.xml` with no use site count? The rule says no.
4. Health checks: is a default Actuator `/health` with no custom indicator TC,
   or only non-trivial checks (the spec says "non-trivial logic")?
