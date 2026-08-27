# Taxonomy canonicalize repair and regroup legibility — design

**Date:** 2026-08-27
**Status:** Approved, awaiting implementation plan

## Problem

Clicking **Regroup unassigned** categorizes only a portion of the backlog.
Repeated clicks clear the easy tokens, then plateau: the unassigned count drops
once and then stops moving, while the completion toast reports a large
`uncertain` figure that gives no indication whether the remainder will ever be
handled.

Observed on the deployed instance. Reproduced in the code path below against the
live workspace state at `data/users/144c652c6338/`.

### Evidence

The live taxonomy state carries 446 `grouping_status` records. Every one of them
reads:

| field | value |
| --- | --- |
| `state` | `uncertain` (446/446) |
| `reason` | `invalid or incomplete model output` (446/446) |
| `phase` | `null` (446/446) |

There are no `kind="call"` outage records and no retired skills. Every recorded
failure is the same thing: the provider answered, and the answer did not cover
the batch it was given.

## Root cause

Two independent mechanisms produce "a portion each time". The first produces the
plateau; the second produces the slow tail.

### 1. The canonicalize replay loop (dominant)

`_project_aliases` (`taxonomy/classification.py`) ends with:

```python
failed = batch - assignments.keys()
```

Anything the model omits from its 60-item partition — or duplicates across two
clusters, or places in a cluster holding more than one existing canonical — is
dropped and marked failed. There is no repair round. `retry_kwargs()` sets
`retries: 0`, and `AgentRunner`'s retry predicate only fires on transient
errors, so a valid-but-incomplete response is a *successful* call.

A token that fails this way is then locked out on four separate axes:

```
no alias recorded
  -> absent from `merged_aliases`
  -> excluded from `demanded_canonicals`
  -> the domain phase never sees it

failure is retryable=True, phase="canonicalize"
  -> `_retryable_canonical_tokens` withholds it from `_apply_placement_floor`
  -> the floor cannot file it either

`attempted` is gated on `phase == "domain"`
  -> it is not "attempted", so it routes back through pass one

`_shard` sorts alphabetically
  -> the same tokens, in the same neighbours, with the same prompt, to the
     same model
```

Identical input reproduces the identical omission. This is precisely the
"clicking Regroup twice used to change nothing" failure that `GroupingStatus.phase`
was introduced to fix — it was fixed for **domain**-phase failures and left live
for **canonicalize**-phase ones.

The domain phase has no equivalent hole: a domain-phase failure escalates in the
same run (premium themer, quarter batches, whole taxonomy, `min_new_domain_members=1`)
and then hits the placement floor, so it terminates in at most two runs.

### 2. The deferred tail (secondary)

`refresh_clusters` bounds escalation at `Settings.taxonomy_escalation_max_skills`
(300) and correctly withholds the remainder from the placement floor — an
untried token must not be filed coarsely, because a filed token is never
re-attempted. Progress is monotonic and bounded, which is right.

But `deferred` is computed and **never returned**. The result dict has no
`deferredSkills` key, so `announce.ts` can only report `uncertainSkills`, which
collapses four unrelated dispositions into one number:

- a domain-phase refusal,
- a canonicalize-phase omission,
- a genuine "no high-confidence existing or coherent new domain" verdict,
- a token that was simply never tried.

The user cannot distinguish *"will be handled on the next click"* from
*"permanently stuck"*. The system was already making monotonic progress on the
deferred tail and refusing to say so.

## Design

Only `refresh_clusters` calls `classify_incrementally` (twice: pass one and
escalation). Both fixes therefore live inside `classify_incrementally`'s
canonicalize section, and `refresh_clusters` needs no structural change.

### Change 1 — Canonicalize repair rounds

After the initial `gather_isolated` over `alias_batches`, loop on the residue
with geometric shrink: **`batch_size` → `max(1, batch_size // 4)` → `1`**
(60 → 15 → 1 at the default `Settings.cluster_batch_size`; the quarter-size step
matches the ratio escalation already uses). Each round re-shards only what the
previous round left uncovered, and each reuses the same `candidate_context`, so a
repaired token is still scored against its own semantic neighbours rather than
the whole canonical set.

The terminal singleton round is the point of the design. At batch size 1,
`_project_aliases`'s rejection rules are near-trivially satisfiable: a lone
token either matches a candidate canonical or is its own head. Cross-cluster
duplication and the multi-existing-member violation are both structurally
impossible.

Two mechanics that are load-bearing:

- **Only `kind="output"` failures are repaired.** A `kind="call"` failure is an
  outage, not a refusal; it keeps today's behaviour (excluded from repair, from
  the backstop, and from the floor; retried next run). Repairing an outage
  harder inside the same run just hammers a rate limit.
- **Failures are recorded only after the loop converges**, not per round.
  Recording per round would leave a `retryable=True` failure on a token a later
  round successfully aliased, and `_retryable_canonical_tokens` would then
  withhold it from the placement floor for no reason.

**Spend guardrail.** The singleton round is bounded by a new setting,
`taxonomy_canonical_repair_max_singletons` (default 500). In the normal case the
bound is never reached — the round only ever sees the residue of a residue (900
tokens → ~180 → ~36 singleton calls). It exists for the systematic-failure case,
where a bad prompt edit or a schema mismatch fails every token in every round
and would otherwise dispatch 900 singleton calls in one run. Tokens beyond the
bound skip to the backstop, which is safe by construction.

### Change 2 — Identity-canonical backstop

Whatever survives all three rounds gets `aliases.setdefault(token, token)` plus a
failure recorded as **`retryable=False`**, message
`"canonicalization incomplete; kept as its own canonical"`.

This deliberately mirrors the reconcile pass, which already reaches the same
conclusion for the same reason: *"Every head here is already a valid canonical
from its own batch... A head the merge pass leaves untouched simply stays its own
canonical (identity alias)."* Pass one has been treating an identical situation
as retryable backlog.

`retryable=False` is the entire integration. `_retryable_canonical_tokens` stops
matching, so `_apply_placement_floor` is free to file the token, and
`refresh_clusters` is untouched. The token now flows: identity alias → domain
phase (same run) → escalation if refused → placement floor. **Termination is
guaranteed in one run.**

Side effect, deliberate and welcome: an identity-aliased token lands in
`new_heads`, so the reconcile pass gets one further chance to merge it correctly
before the domain phase runs.

**No off-switch.** `Settings.taxonomy_placement_floor` already governs whether
coarse filing happens at all, and the backstop sits upstream of it. A second
toggle would be two ways to express one intent.

**Cost accepted.** This spends dedup quality to buy termination: a token the
model never clustered stays its own canonical, so `k8s` may sit beside
`kubernetes`. That is recoverable — `TaxonomyCorrections.aliases` is applied last
in `apply_taxonomy_corrections` and therefore beats LLM output, `add_skill_alias`
enforces the cycle guard, and `MergeSkillDialog.tsx` exposes it. An unassigned
skill is invisible; an imperfectly-merged one is visible and one dialog from
correct.

### Change 3 — Canonicalizer model tier

`build_incremental_canonicalizer_agent` moves from `settings.premium_model` to
`settings.mid_model` (Opus 5 → Sonnet 5, $5/$25 → $2/$10 per MTok).

The canonicalizer currently runs on the *premium* tier while the domain
classifier — the harder judgment — runs on mid. That is inverted, and Opus is
demonstrably not buying completeness on this task: all 446 live failures are
incomplete Opus partitions. The repair rounds and the backstop now absorb
coverage loss that was previously permanent, so the downside is bounded.

`build_escalation_themer_agent` stays on `premium_model`; the ambiguous tail is
where that tier earns its cost.

**Stated risk.** Repair rounds catch *omissions*; nothing catches *bad merges*.
A weaker model that confidently merges two distinct skills produces output
indistinguishable from a correct merge. This trade is accepted knowingly, and the
live verification below is the check on it.

### Change 4 — Regroup legibility

- Return `deferredSkills` from `refresh_clusters`.
- Split `uncertainSkills` into its real dispositions rather than collapsing four
  states into one count. `uncertainSkills` is retained as the existing total so
  no consumer breaks, alongside `deferredSkills` (never tried this run, bounded
  out by the escalation cap), `uncertainDomainSkills` (a domain-phase refusal or
  the "no high-confidence existing or coherent new domain" verdict), and
  `uncertainCanonicalSkills` (a canonicalize-phase omission that survived repair).
- Add repair telemetry to `ClassificationMetrics`: `repair_rounds`,
  `repaired_tokens`, `identity_filed`.
- `announce.ts` reports the split, e.g.
  `"… 120 uncertain · 900 deferred to next run"`.

The escalation cap's *mechanism* is unchanged. The fix here is honesty, not
behaviour.

### Change 5 — Documentation

Update `src/resume_agent/taxonomy/CLAUDE.md`:

- The canonicalize pass now repairs, then files an identity canonical, and a
  canonicalize-phase failure is no longer permanent backlog.
- The Message Batches API was evaluated and rejected — see below — with the
  trigger that would flip the decision recorded explicitly.

## Rejected: Message Batches API

Evaluated at the user's request against current Anthropic documentation
(50% cost reduction, up to 100k requests / 256MB per batch, most batches within
1 hour with a hard 24-hour maximum, structured output and caching supported,
results unordered and keyed by `custom_id`). Rejected for this workload on three
grounds:

1. **It cannot reach the call sites without bypassing agno.** Classification
   goes `acall(runner, prompt)` → `AgentRunner.arun()` → `Agent(output_schema=...)`.
   Batches requires raw `client.messages.batches.create` with
   `output_config.format`; an `Agent` object cannot be batched. Adopting it means
   re-implementing structured-output binding, `SpendGate.open` gating,
   `SpendGate.settle` usage recording, and the `is_transient` retry predicate
   outside the `build_model` seam — and forking provider support, since the seam
   covers Anthropic/OpenAI/Gemini/DeepSeek and Batches is Anthropic-only.
2. **The pipeline is only partly batchable.** Reconcile is strictly sequential by
   design (each shard's heads feed the next shard's `running_stable`). Batching
   would mean three separate dispatches, each potentially an hour, turning an
   interactive Regroup into an overnight job. Batch IDs would also need to
   survive Railway redeploys or in-flight batches orphan.
3. **The economics do not justify it.** Order-of-magnitude on a ~900-token
   backlog, canonicalizer on Opus 5: pass one is ~15 calls at roughly 1–2K input
   and 1–2K output each — well under a dollar per regroup. Halving that does not
   pay for a second dispatch architecture. Change 3 delivers a larger cost
   reduction for one config line.

**Trigger to revisit: rate limiting, not cost.** If regroups begin failing with
`kind="call"` 429s, the Batches API's separate and substantially higher
throughput ceiling becomes the actual reason to adopt it, and this decision
should be reopened as its own spec.

## Verification

**Offline (TDD, matches existing discipline — all agent calls are faked):** a
fake canonicalizer that omits a fixed slice of every batch must demonstrate:

1. repair rounds converge (60 → 15 → 1) and the aliased set grows each round;
2. the backstop fires only *after* the rounds — on a fixture where repair
   recovers everything, `identity_filed == 0`;
3. a backstopped token carries `retryable=False` and therefore reaches
   `_apply_placement_floor`;
4. a `kind="call"` failure is never repaired and never backstopped;
5. failures are not recorded for tokens a later round recovered;
6. the singleton bound caps dispatch and sends the overflow to the backstop.

**Live (one-shot):** one real Regroup on the deployed corpus, reading the Change 4
telemetry. `deferredSkills` plus the split `uncertainSkills` distinguish
converged from plateaued; `repaired_tokens` versus `identity_filed` shows what
the repair rounds bought and what the backstop had to absorb — which is the only
measurement of the dedup-quality cost accepted in Changes 2 and 3.

This is a one-shot measurement on one corpus, not a regression guard. Offline
assertion (2) pins the ordering invariant so repair-before-backstop cannot
silently regress; nothing in CI measures real-world coverage.

## Explicitly out of scope

- **416 stale `grouping_status` records.** `set_grouping_statuses` prunes only the
  tokens the current run requested, so a token assigned via profile build,
  corrections, or maintenance keeps its old status indefinitely. File cruft, not
  a defect; `attempted` only consults statuses for tokens that are still
  unassigned.
- **The 446 `phase: null` records.** The first run after this ships gives them one
  free standard-path re-attempt, after which each carries a real phase and routes
  correctly forever. That is the intended migration path, not a bug.
- **The escalation cap mechanism.** Unchanged; only its reporting changes.
