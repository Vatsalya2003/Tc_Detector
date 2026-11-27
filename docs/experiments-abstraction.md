# Re-running the abstraction experiments on the course repo (after Dec 1)

Owner: D (Karan). This is the exact recipe for the held-out run of `gateway`,
`externalised-config` and `feature-flags` on `cs6510-checkout-microservices`.

**Run it once, after the Dec 1 freeze, and don't change anything because of what it shows.**
The course repo is the test set (`targets.yaml`, role `test`). The dev-set version of each
step, with its results, is in `docs/results-abstraction.md` and `results/abstraction/dev/`.

## Before you start

- The three rule PRs are merged into `main`: `karan/gateway-rule-fix`,
  `karan/externalised-config-rule` and `karan/feature-flags-rule`. If one isn't merged,
  run that rule from its branch, e.g. `git worktree add ../ff origin/karan/feature-flags-rule`
  and `PYTHONPATH=../ff/src`.
- `stage3-abstraction-v2` is in `src/tc_detector/llm/prompts.py` (branch `karan/abstraction-prompt`).
- The course-repo label file `ground_truth/cs6510-checkout-microservices.json` exists and
  is frozen, with this category's labels in it. (Primary labeller for D's patterns: C.)
- `.env` holds `ANTHROPIC_API_KEY` and `uv run python scripts/check_api_key.py` passes.
- The budget is shared: check the cost estimate below before each step.

## Setup (run from the repo root, in bash)

```bash
uv run python scripts/clone_targets.py        # checks out 241caa78568f1fb19056b85d318adfd07f8326b0
REPO=targets/cs6510-checkout-microservices/week6-events   # targets.yaml `path:`
NAME=cs6510-checkout-microservices
SHA=241caa78568f1fb19056b85d318adfd07f8326b0
LABELS=ground_truth/cs6510-checkout-microservices.json
OUT=results/abstraction/test
CACHE=.tc_cache                                # git-ignored response cache
mkdir -p $OUT/candidates $OUT/exp1 $OUT/exp3 $OUT/exp4 $OUT/exp5
git -C targets/cs6510-checkout-microservices rev-parse HEAD   # must print $SHA
```

`attr` sends candidates to Claude with this category's fixed settings
(v2 prompt, no fallbacks, no ADR fields):

```bash
attr() {  # attr <candidates> <model> <cost-log> <verdicts-out> [extra flags]
  uv run tc-attribute "$1" --repo $REPO --model "$2" --no-fallbacks \
    --prompt-version stage3-abstraction-v2 --cache-dir $CACHE \
    --cost-log "$3" --out "$4" "${@:5}"
}
confirmed() {  # confirmed <candidates> <verdicts> <out>: keep the candidates Claude said yes to
  python3 -c "import json,sys; ok={json.loads(l)['candidate_id'] for l in open(sys.argv[2]) if json.loads(l)['is_tc'] is True}; open(sys.argv[3],'w').writelines(l for l in open(sys.argv[1]) if json.loads(l)['id'] in ok)" "$1" "$2" "$3"
}
```

## Step 0: rule candidates (free)

```bash
for rule in gateway externalised_config feature_flags; do
  uv run python -m tc_detector.rules.abstraction.$rule $REPO --repo-name $NAME --commit $SHA
done > $OUT/candidates/candidates.jsonl
wc -l $OUT/candidates/candidates.jsonl        # N, used in the estimates below
```

## Cost estimates

The cost per candidate was measured on the dev set (prompt v2, effort `medium`):
Haiku **$0.00019**, Sonnet **$0.0035**. `N` is the number of rule candidates from Step 0,
which isn't known until the rules run. The two service-level patterns give at most one
candidate per service: the scanner finds 8 "services" there, so at most 16. `feature-flags`
can add any number.

| Step | Calls | Estimate | N = 20 | N = 50 | N = 100 |
|---|---|---|---|---|---|
| 1. Rules + Claude (Haiku) | N | N × $0.00019 | $0.004 | $0.010 | $0.019 |
| 3. Sonnet arm | N | N × $0.0035 | $0.07 | $0.18 | $0.35 |
| 4. Caching re-run | 2N | $0 (all cache hits) | $0 | $0 | $0 |
| 5. Consistency, 4 more repeats (Haiku) | 4N | N × $0.00077 | $0.015 | $0.04 | $0.08 |
| **Total** | | **N × ~$0.0045** | **~$0.09** | **~$0.23** | **~$0.45** |

Pay attention to Step 3: if N > 70, the Sonnet arm alone is over $0.25.

## Step 1: rules only vs. rules + Claude

```bash
attr $OUT/candidates/candidates.jsonl claude-haiku-5-5 $OUT/exp1/cost_log.jsonl $OUT/exp1/verdicts-haiku.jsonl
confirmed $OUT/candidates/candidates.jsonl $OUT/exp1/verdicts-haiku.jsonl $OUT/exp1/confirmed-haiku.jsonl
echo "## rules only";           uv run python -m tc_detector.eval.score --candidates $OUT/candidates/candidates.jsonl --labels $LABELS
echo "## rules + Claude (haiku)"; uv run python -m tc_detector.eval.score --candidates $OUT/exp1/confirmed-haiku.jsonl --labels $LABELS
uv run python -m tc_detector.eval.report --cost-log $OUT/exp1/cost_log.jsonl \
  --verdicts $OUT/exp1/verdicts-haiku.jsonl --candidates $OUT/exp1/confirmed-haiku.jsonl --labels $LABELS > $OUT/exp1/report.md
```

Read the `gateway`, `externalised-config` and `feature-flags` rows. The report's overall
recall also counts other owners' labels.

## Step 2: everything to Claude vs. rules prefilter

**Not available.** The wrapper only accepts rule candidates (see
`docs/results-abstraction.md`, item 2). If it gets built, estimate it before running: one
call per service for each of the two service-level patterns, plus one call per Java and
config file for `feature-flags`. From the labelling inventory, the course repo has 8
services, 110 main Java files and 5 config files, so about 131 calls: **~$0.03 on Haiku,
~$0.55 on Sonnet**, using PetClinic's measured cost per call.

## Step 3: Haiku vs. Sonnet

```bash
attr $OUT/candidates/candidates.jsonl claude-sonnet-5-5 $OUT/exp3/cost_log-sonnet.jsonl $OUT/exp3/verdicts-sonnet.jsonl
confirmed $OUT/candidates/candidates.jsonl $OUT/exp3/verdicts-sonnet.jsonl $OUT/exp3/confirmed-sonnet.jsonl
uv run python -m tc_detector.eval.score --candidates $OUT/exp3/confirmed-sonnet.jsonl --labels $LABELS
uv run python -m tc_detector.eval.report --cost-log $OUT/exp3/cost_log-sonnet.jsonl \
  --verdicts $OUT/exp3/verdicts-sonnet.jsonl --candidates $OUT/exp3/confirmed-sonnet.jsonl --labels $LABELS > $OUT/exp3/report-sonnet.md
# Agreement: count candidates where both models give the same is_tc
python3 -c "import json; h={json.loads(l)['candidate_id']:json.loads(l)['is_tc'] for l in open('$OUT/exp1/verdicts-haiku.jsonl')}; s={json.loads(l)['candidate_id']:json.loads(l)['is_tc'] for l in open('$OUT/exp3/verdicts-sonnet.jsonl')}; print(sum(h[k]==s[k] for k in h),'/',len(h),'agree')"
```

## Step 4: caching

```bash
attr $OUT/candidates/candidates.jsonl claude-haiku-5-5  $OUT/exp4/cost_log.jsonl $OUT/exp4/verdicts-rerun-haiku.jsonl
attr $OUT/candidates/candidates.jsonl claude-sonnet-5-5 $OUT/exp4/cost_log.jsonl $OUT/exp4/verdicts-rerun-sonnet.jsonl
uv run python -m tc_detector.eval.report --cost-log $OUT/exp4/cost_log.jsonl > $OUT/exp4/report.md
```

Expect 0 API calls, $0 spent, and "Saved by cache" equal to Steps 1 + 3. Use the same
`--cache-dir` as Steps 1 and 3, or nothing will be cached.

## Step 5: consistency (Haiku, 5 repeats)

```bash
attr $OUT/candidates/candidates.jsonl claude-haiku-5-5 $OUT/exp5/cost_log.jsonl $OUT/exp5/verdicts-haiku-x5.jsonl --repeats 5
uv run python -m tc_detector.eval.report --cost-log $OUT/exp5/cost_log.jsonl --verdicts $OUT/exp5/verdicts-haiku-x5.jsonl > $OUT/exp5/report.md
# Share of runs with the same verdict, per pattern, and any flips
python3 -c "
import json, collections
by = collections.defaultdict(list)
for l in open('$OUT/exp5/verdicts-haiku-x5.jsonl'):
    v = json.loads(l); by[v['candidate_id']].append(v['is_tc'])
pat = collections.defaultdict(lambda: [0, 0])
for cid, vs in by.items():
    maj = collections.Counter(vs).most_common(1)[0][0]; p = pat[cid.split(':')[-1]]
    p[0] += len(vs); p[1] += vs.count(maj)
    if len(set(vs)) > 1: print('FLIP', cid, vs)
for k, (n, same) in pat.items(): print(f'{k}: {same}/{n} same verdict')"
```

Repeat 0 is served from Step 1's cache, so only repeats 1-4 are new calls. Each repeat
index has its own cache entry, which is why the other four are real calls.

## Afterwards

- Write the numbers into `docs/results-abstraction.md` under a "Test set" heading, next to
  the dev numbers, along with the total from all the cost logs in `$OUT`.
- Don't change rules or prompts because of these results: the test set is scored once.
