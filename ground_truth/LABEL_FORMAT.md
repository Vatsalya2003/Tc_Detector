# Label format (DRAFT, needs team sign-off)

A **label** is one human judgment: "is this Technical Credit present at this place?"
Evaluation scores the detector's candidates against these labels.

- Schema: [`schemas/label.schema.json`](../schemas/label.schema.json)
- Code: `src/tc_detector/contracts/label.py` (`Label`, `load_labels`, `save_labels`)

Every field a label shares with a candidate (`repo` to `category`) has exactly the same
name, type and allowed values as in [`schemas/candidate.schema.json`](../schemas/candidate.schema.json).
The label schema points at the candidate schema instead of copying it.

## One file per repo

All labels for one repo go in a single file, as a JSON list, e.g. `ground_truth/petclinic.json`:

```json
[
  { "label_id": "...", "repo": "spring-petclinic-microservices", ... },
  { "label_id": "...", "repo": "spring-petclinic-microservices", ... }
]
```

Every label in the file must have the same `repo` and `commit`, and no two labels may
share a `label_id`. `load_labels()` checks this and names the broken entry if one is wrong.

## Fields

| Field | Meaning |
|---|---|
| `label_id` | **Proposal.** Unique name for the label, built from the fields as `repo:service:file:location:pattern` (same as a candidate's `id`). Don't type it by hand: `Label.create()` builds it. |
| `repo` | Which target repo. **Rule (needs team sign-off): use the repo's `name` from `targets.yaml`**, e.g. `spring-petclinic-microservices`. Candidates must use the same string, or nothing will match. |
| `commit` | The pinned commit you labelled, from `targets.yaml`. |
| `service` | Which microservice, e.g. `api-gateway`. |
| `file` | Path relative to the service root, with `/`. No leading `/`, `\`, `:` or `..`. `null` only for `service` units. |
| `line_start`, `line_end` | First and last line, counting from 1. See the unit rules below. |
| `unit` | How precise the label is: `line_range`, `file` or `service`. |
| `pattern` | Which pattern, as a kebab-case slug. Use the list below. |
| `category` | One of `observability`, `api-stability`, `modularity`, `automation`, `abstraction`, `configurability`. |
| `is_tc` | The **final** verdict that evaluation scores. `true` = present; `false` = judged absent. |
| `labeller` | Who labelled it first: `A`, `B`, `C` or `D`. |
| `second_labeller` | Who labelled it again for the 20% agreement sample, or `null`. Never the same person as `labeller`. |
| `second_is_tc` | **Proposal.** The second labeller's own verdict, or `null`. Set exactly when `second_labeller` is set. |
| `adjudicated_by` | **Proposal.** Who settled a disagreement, or `null`. See below. |
| `notes` | Why you decided this. May be `""`, but not `null`. |

## The three unit rules

1. **`line_range`**: `file` is required, and `line_start` and `line_end` are required whole numbers with `line_start <= line_end`.
2. **`file`**: `file` is required, and `line_start` and `line_end` must be `null`.
3. **`service`**: `line_start` and `line_end` must be `null`, and `file` may be `null`.

## Second labeller and disagreements

- **Not in the sample:** `second_labeller`, `second_is_tc` and `adjudicated_by` are all `null`.
- **In the sample and they agreed:** `second_is_tc` equals `is_tc`, and `adjudicated_by` is `null`.
- **In the sample and they disagreed:** the two labellers first try to settle it themselves. If they're still split, the tie-breaker decides. `adjudicated_by` is whoever made the final call (the labeller, the second labeller, or another team member), and `is_tc` is that final answer.

For Cohen's kappa you need both people's original answers. The second labeller's is
`second_is_tc`. The first labeller's is `second_is_tc` again if `adjudicated_by` is
`null` (they agreed), and `not second_is_tc` if it is set (they disagreed).

**The owner of a pattern must never label or adjudicate that pattern** (e.g. Neil doesn't
label `circuit-breaker-retry`). The code doesn't enforce this, so please follow it yourselves.

## Pattern names (proposed, needs team sign-off)

Use exactly these strings in `pattern`, in both labels and candidates:

`gateway`, `externalised-config`, `feature-flags`, `distributed-tracing`, `structured-logging`,
`custom-metrics`, `versioned-api`, `immutable-data-contracts`, `event-schema-versioning`,
`circuit-breaker-retry`, `health-checks`, `saga`

The code only checks that a pattern is kebab-case, not that it is on this list.

## Examples

### `line_range`: one labeller

```json
{
  "label_id": "spring-petclinic-microservices:customers-service:src/main/java/org/springframework/samples/petclinic/customers/OwnerResource.java:48-55:distributed-tracing",
  "repo": "spring-petclinic-microservices",
  "commit": "TODO-pin-sha",
  "service": "customers-service",
  "file": "src/main/java/org/springframework/samples/petclinic/customers/OwnerResource.java",
  "line_start": 48,
  "line_end": 55,
  "unit": "line_range",
  "pattern": "distributed-tracing",
  "category": "observability",
  "is_tc": true,
  "labeller": "A",
  "second_labeller": null,
  "second_is_tc": null,
  "adjudicated_by": null,
  "notes": "Span around the owner lookup; tracing backend is swappable via config"
}
```

### `file`: judged absent, both labellers agreed

```json
{
  "label_id": "spring-petclinic-microservices:config-server:src/main/resources/application.yml:file:feature-flags",
  "repo": "spring-petclinic-microservices",
  "commit": "TODO-pin-sha",
  "service": "config-server",
  "file": "src/main/resources/application.yml",
  "line_start": null,
  "line_end": null,
  "unit": "file",
  "pattern": "feature-flags",
  "category": "configurability",
  "is_tc": false,
  "labeller": "B",
  "second_labeller": "C",
  "second_is_tc": false,
  "adjudicated_by": null,
  "notes": ""
}
```

### `service`: labellers disagreed, D settled it

```json
{
  "label_id": "spring-petclinic-microservices:api-gateway:-:service:gateway",
  "repo": "spring-petclinic-microservices",
  "commit": "TODO-pin-sha",
  "service": "api-gateway",
  "file": null,
  "line_start": null,
  "line_end": null,
  "unit": "service",
  "pattern": "gateway",
  "category": "abstraction",
  "is_tc": true,
  "labeller": "A",
  "second_labeller": "C",
  "second_is_tc": false,
  "adjudicated_by": "D",
  "notes": "Routes all external traffic; hides service topology"
}
```
