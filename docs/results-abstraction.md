# Results: abstraction and configurability (dev set)

Owner: D (Karan). Patterns: `gateway` (abstraction), `externalised-config` and
`feature-flags` (configurability). Run on 2026-11-27 on the **development set only**:
PetClinic at `e8b747a` and a small synthetic feature-flags fixture. The held-out course
repo is scored once, after the Dec 1 freeze (see `docs/experiments-abstraction.md`).

Claude prompt: `stage3-abstraction-v2`. Raw outputs: `results/abstraction/dev/`.
Total cost of everything below: **$0.07**.

## In one paragraph

The rules found every labelled instance in PetClinic (1 gateway, 7 services with
externalised config) and made no false finds. Claude agreed with all of them, so adding
Claude changed nothing on this data. The small and mid-size models gave the same answers,
and the small one was about 18 times cheaper. Running the same input again cost nothing,
because of the response cache. Asking the same question five times always gave the same
yes/no answer. These numbers look perfect, but they are **optimistic**; the gaps below
explain why.

## What we found

**1. Rules only vs. rules + Claude.** On PetClinic both score precision 1.00 and recall
1.00 for `gateway` (1/1) and `externalised-config` (7/7). On the feature-flags fixture
both score 1.00 / 1.00 (8/8). Claude confirmed all 16 candidates, so it removed nothing
and the two arms are the same. This run can't show whether Claude would catch a wrong
rule finding: there were none to catch. In a separate sanity check, the prompt rejected
6 out of 6 hand-made wrong candidates, such as the config server itself or an `@Profile`
line (`docs/prompt-log.md`).

**2. Everything to Claude vs. rules first.** Not run. The wrapper only accepts rule
candidates, so there is no way yet to send it "every service" or "every file".
What's missing:
- something that turns every service or file into a candidate (no such tool exists);
- the 2000-character snippet limit in the frozen candidate format: all 8 PetClinic
  services and 15 of 61 files are bigger than that, so they would be cut short;
- a way for Claude to say *where* in a file a flag is: the verdict has no line fields,
  so `feature-flags` (matched by line range) couldn't be scored;
- a prompt for raw files: v2 explains rule-evidence snippets, not whole files.
Estimate for PetClinic: 77 calls (8 services × 2 service-level patterns + 61 files),
about **$0.017 on Haiku or $0.32 on Sonnet**, compared with 8 calls after the rules.

**3. Small vs. mid-size model** (`claude-haiku-5-5` vs `claude-sonnet-5-5`). Both
confirmed 16/16 and agreed on every verdict and category. Sonnet usually gave a higher
confidence (5 instead of 4 on several PetClinic candidates). Cost per candidate: Haiku
about $0.0002, Sonnet about $0.0035 (around 18×). On this data, the cheaper model is enough.

**4. Caching.** Running all 32 calls again used 0 new tokens and cost $0, saving $0.059.
Separately, Anthropic's prompt cache cut the first run's cost, because every call shares
the same long system prompt: that saved about $0.003 on Haiku and $0.056 on Sonnet.

**5. Consistency.** Haiku answered each candidate 5 times (80 answers). The yes/no answer
never changed, for any pattern. Confidence moved by one point on two candidates: the
gateway (4 or 5) and one feature flag (3 or 4).

## Known gaps

- **The guideline doesn't cover the anti-corruption-layer half of this category.**
  GUIDELINES.md defines `gateway` only as "the single entry point that routes requests".
  So a service that wraps a vendor or legacy API is neither labelled nor detected. That
  was a deliberate choice, but it means that kind of credit is not measured at all.
- **Feature-flags was measured only on a synthetic fixture with owner-written labels.**
  PetClinic has no feature flags. The fixture and its labels were written by the rule's
  owner, from the same guideline the rule follows, so its 1.00 shows the code works as
  intended, not real accuracy.
- **Role, consumers and git history are "unknown" in every prompt.** The wrapper doesn't
  get them from the scanner yet. Git history is looked up per file, and the gateway and
  externalised-config candidates are whole services, so there is no file to look up.
  Claude decides from the rule's evidence alone. (Wrapper owner: Neil.)
- **Dev numbers are optimistic.** The rules, the prompt and the labels all follow the same
  guideline; PetClinic has very few instances (1 gateway, 7 config imports); and every
  candidate was a true positive, so Claude never had to reject anything.
- **Feature-flags prompts show wrong line numbers.** The wrapper numbers the rule's whole
  snippet from `line_start`, including its header line. The verdicts weren't affected,
  but this needs a fix in the rule or the wrapper.
- **The rules aren't on `main` yet.** These results come from the unmerged branches
  `karan/gateway-rule-fix`, `karan/externalised-config-rule` and `karan/feature-flags-rule`.
