# Taxonomy Canonicalize Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop Regroup from plateauing by repairing canonicalize-phase omissions in-run, filing whatever survives as its own canonical, and reporting the deferred backlog the escalation cap was already computing but never returning.

**Architecture:** All behavioural change lands inside `classify_incrementally`'s canonicalize section in `src/resume_tailor_harness/taxonomy/classification.py`. Omitted tokens are re-asked in geometrically shrinking rounds (`batch_size` → `batch_size // 4` → `1`); whatever still survives gets an identity alias and a failure recorded as `retryable=False`. That flag alone lets the existing `_apply_placement_floor` file the token, so `refresh_clusters` needs **no structural change** — only new telemetry keys. `refresh_clusters` is the sole caller of `classify_incrementally` (it calls it twice: pass one and escalation), so the blast radius is contained.

**Tech Stack:** Python 3.12, pydantic v2, pytest, agno `Agent` + `AgentRunner`, React + TypeScript + vitest for the toast.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-27-taxonomy-canonicalize-repair-design.md`. Read it before Task 1.
- Tests are offline: no API key, no network. All agent calls are faked. Never write a test that constructs a real model.
- Backend test command: `.venv/Scripts/python.exe -m pytest`
- Lint: `ruff check` — must be clean before every commit.
- Web test command: `cd web && npm test`
- `ClassificationMetrics` is a frozen dataclass and is constructed positionally in existing tests. **Every new field must have a default**, and new fields go at the end.
- Only `kind="output"` failures are repaired or backstopped. A `kind="call"` failure is an outage: excluded from repair, excluded from the backstop, retried next run. This is non-negotiable — it is what stops a timeout from permanently misfiling a skill.
- Canonicalize output-failures are recorded **only after the repair loop converges**, never per round. Recording per round would leave a `retryable=True` failure on a token a later round recovered.
- Do not add an off-switch for the backstop. `Settings.taxonomy_placement_floor` already governs coarse filing.
- Branch from `main`; `main` is protected and returns by PR.

---

### Task 1: Canonicalize repair rounds

**Files:**
- Modify: `src/resume_tailor_harness/config.py` (add one setting near `taxonomy_escalation_max_skills`, line ~131)
- Modify: `src/resume_tailor_harness/taxonomy/classification.py:47-54` (`ClassificationMetrics`), `:355-370` (signature), `:436-475` (canonicalize block), `:700-712` (metrics construction)
- Test: `tests/test_taxonomy_classification.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `Settings.taxonomy_canonical_repair_max_singletons: int` (default `500`, `ge=0`, `le=5000`)
  - `classify_incrementally(..., repair_max_singletons: int = 500)` — new keyword-only parameter
  - `ClassificationMetrics.canonical_repair_rounds: int = 0`
  - `ClassificationMetrics.canonical_repaired: int = 0`
  - `ClassificationMetrics.canonical_identity_filed: int = 0` (populated in Task 2; declared here so the dataclass is written once)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_taxonomy_classification.py`, after the `_Themer` class:

```python
class _OmittingCanonicalizer:
    """Covers a batch fully only when it holds ``full_at`` tokens or fewer.

    Reproduces the live failure: the model answers, and the answer partitions
    only part of the batch it was given.  With ``full_at=1`` only the singleton
    repair round can close the residue, which is exactly the property the
    geometric shrink is supposed to buy.
    """

    def __init__(self, full_at: int = 1):
        self.full_at = full_at
        self.batch_sizes: list[int] = []

    async def arun(self, prompt):
        payload = json.loads(prompt)
        new = payload["new"]
        self.batch_sizes.append(len(new))
        covered = new if len(new) <= self.full_at else new[: len(new) // 2]
        return SimpleNamespace(
            content=SkillClusters(clusters=[[token] for token in covered])
        )

    def run(self, prompt):
        raise AssertionError("async path expected")


def test_repair_rounds_recover_tokens_the_first_partition_omitted():
    canonicalizer = _OmittingCanonicalizer(full_at=1)
    demanded = {f"skill {index}" for index in range(8)}

    outcome = _classify(
        demanded=demanded, canonicalizer=canonicalizer, batch_size=8
    )

    # Every demanded token ends the pass with a canonical.
    assert set(outcome.additions.aliases) == demanded
    # Repair, not the backstop, is what recovered them.
    assert outcome.metrics.canonical_identity_filed == 0
    assert outcome.metrics.canonical_repaired == 8 - 4
    assert outcome.metrics.canonical_repair_rounds >= 1
    # The rounds shrink: 8, then 2, then 1.
    assert canonicalizer.batch_sizes[0] == 8
    assert min(canonicalizer.batch_sizes) == 1
    # No retryable canonicalize failure survives for a recovered token.
    recovered = {
        token
        for failure in outcome.failures
        if failure.phase == "canonicalize" and failure.retryable
        for token in failure.tokens
    }
    assert recovered == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_classification.py::test_repair_rounds_recover_tokens_the_first_partition_omitted -v`

Expected: FAIL with `AttributeError: 'ClassificationMetrics' object has no attribute 'canonical_identity_filed'`

- [ ] **Step 3: Add the setting**

In `src/resume_tailor_harness/config.py`, immediately after the `taxonomy_escalation_max_skills` field (line ~131):

```python
    # Bounds the terminal singleton repair round.  In the normal case it is
    # never reached -- that round only ever sees the residue of a residue.  It
    # exists for the systematic-failure case (a bad prompt edit, a schema
    # mismatch) where every token fails every round and would otherwise
    # dispatch one call per token.  Overflow goes to the identity backstop,
    # which is safe by construction.
    taxonomy_canonical_repair_max_singletons: int = Field(
        default=500, ge=0, le=5000
    )
```

- [ ] **Step 4: Extend the metrics dataclass**

In `src/resume_tailor_harness/taxonomy/classification.py`, replace the `ClassificationMetrics` body (lines 47-54) with:

```python
@dataclass(frozen=True)
class ClassificationMetrics:
    canonical_batches: int
    domain_batches: int
    prompt_bytes: int
    max_in_flight: int
    elapsed_ms: int
    embedding_mode: str = "none"
    # How the canonicalize pass actually closed its backlog.  `repaired` is
    # what the shrinking rounds recovered; `identity_filed` is what no round
    # could place and the backstop had to keep as its own canonical.  The
    # ratio between them is the measurement of the dedup quality this design
    # trades away for guaranteed termination.
    canonical_repair_rounds: int = 0
    canonical_repaired: int = 0
    canonical_identity_filed: int = 0
```

- [ ] **Step 5: Add the parameter to the signature**

In `classify_incrementally`'s signature, after `enforce_candidates: bool = True` (line ~370), add:

```python
    repair_max_singletons: int = 500,
```

- [ ] **Step 6: Replace the canonicalize block**

Replace `src/resume_tailor_harness/taxonomy/classification.py` lines 436-475 (from `aliases: dict[str, str] = {}` through the end of the `for batch, result in zip(alias_batches, ...)` loop, stopping before `new_heads = ...`) with:

```python
    aliases: dict[str, str] = {}
    canonical_repair_rounds = 0
    canonical_repaired = 0
    canonical_identity_filed = 0
    # Tokens whose provider CALL failed.  An outage carries no judgment, so it
    # is never repaired and never backstopped -- it keeps its retryable status
    # and is re-attempted on the next run.
    canonical_call_failed: set[str] = set()

    async def run_canonical_round(
        batches: list[list[str]], label: str
    ) -> set[str]:
        """Run one canonicalize fan-out; return the tokens it left uncovered."""
        nonlocal canonical_call_failed
        if reporter is not None:
            reporter.begin(len(batches), label)
        results = await gather_isolated(
            batches,
            lambda batch: canonicalize(
                batch, sorted(stable_canonicals), use_candidates=True
            ),
            on_complete=(
                (lambda completed: reporter.step(completed, label=label))
                if reporter is not None
                else None
            ),
            checkpoint=reporter.checkpoint if reporter is not None else None,
        )
        uncovered: set[str] = set()
        for batch, result in zip(batches, results, strict=True):
            if not result.ok or result.value is None:
                failures.append(
                    ClassificationFailure(
                        "canonicalize",
                        tuple(batch),
                        str(result.error or "model call failed"),
                        kind="call",
                    )
                )
                canonical_call_failed |= set(batch)
                continue
            aliases.update(result.value.aliases)
            uncovered |= set(result.value.failed_tokens)
        return uncovered

    if alias_batches:
        residue = await run_canonical_round(alias_batches, "Canonicalizing skills")
        first_residue = set(residue)
        # Geometric shrink.  Coverage of an exhaustive partition degrades with
        # batch size, so re-asking the SAME tokens at the SAME size reproduces
        # the same omission -- that identical-replay property is the bug.  The
        # terminal singleton round is the point: with one token per call, a
        # cross-cluster duplicate and a multi-existing-member violation are
        # both structurally impossible, so `_project_aliases` can only reject
        # an outright non-answer.
        for repair_size in (max(1, batch_size // 4), 1):
            if not residue:
                break
            targets = sorted(residue)
            if repair_size == 1:
                targets = targets[:repair_max_singletons]
            overflow = residue - set(targets)
            residue = (
                await run_canonical_round(
                    _shard(set(targets), repair_size), "Repairing skill canonicals"
                )
                | overflow
            )
            canonical_repair_rounds += 1
        residue -= canonical_call_failed
        canonical_repaired = len(first_residue - residue - canonical_call_failed)
```

- [ ] **Step 7: Feed the counters into the metrics**

In the `metrics = ClassificationMetrics(...)` construction near line 700, add the three keyword arguments after `embedding_mode=...`:

```python
        canonical_repair_rounds=canonical_repair_rounds,
        canonical_repaired=canonical_repaired,
        canonical_identity_filed=canonical_identity_filed,
```

- [ ] **Step 8: Run the test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_classification.py::test_repair_rounds_recover_tokens_the_first_partition_omitted -v`

Expected: PASS

- [ ] **Step 9: Run the full backend suite and lint**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_classification.py tests/test_services_match_gap.py -v && ruff check`

Expected: all PASS, ruff clean. Note: `residue` currently leaks tokens that no round covered — they get no alias, so a few existing assertions may still hold only because Task 2 has not landed. If a test fails here specifically because an uncovered token has no alias, that is expected and Task 2 fixes it; record which test, do not weaken it.

- [ ] **Step 10: Commit**

```bash
git add src/resume_tailor_harness/config.py src/resume_tailor_harness/taxonomy/classification.py tests/test_taxonomy_classification.py
git commit -m "fix(taxonomy): repair canonicalize omissions with shrinking rounds"
```

---

### Task 2: Identity-canonical backstop

**Files:**
- Modify: `src/resume_tailor_harness/taxonomy/classification.py` (end of the canonicalize block added in Task 1)
- Test: `tests/test_taxonomy_classification.py`, `tests/test_services_match_gap.py`

**Interfaces:**
- Consumes: `canonical_identity_filed`, `canonical_call_failed`, `residue` from Task 1's canonicalize block.
- Produces: a `ClassificationFailure(phase="canonicalize", kind="output", retryable=False, message="canonicalization incomplete; kept as its own canonical")` — `retryable=False` is the contract `_retryable_canonical_tokens` reads, and it is what lets `_apply_placement_floor` file the token.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_taxonomy_classification.py`:

```python
class _RefusingCanonicalizer:
    """Answers every batch, and covers nothing.  The permanent-omission case."""

    async def arun(self, prompt):
        return SimpleNamespace(content=SkillClusters(clusters=[]))

    def run(self, prompt):
        raise AssertionError("async path expected")


class _FailingCanonicalizer:
    """The provider call itself fails -- an outage, not a refusal."""

    async def arun(self, prompt):
        raise RuntimeError("provider down")

    def run(self, prompt):
        raise AssertionError("async path expected")


def test_a_token_no_round_can_place_becomes_its_own_canonical():
    outcome = _classify(
        demanded={"quantum widgetry"},
        canonicalizer=_RefusingCanonicalizer(),
        batch_size=8,
    )

    # It has a canonical, so the domain phase can see it at all.
    assert outcome.additions.aliases["quantum widgetry"] == "quantum widgetry"
    assert outcome.metrics.canonical_identity_filed == 1
    # retryable=False is the whole integration: it stops
    # `_retryable_canonical_tokens` from withholding the token from the floor.
    # Match on the message, not just on `retryable=False` -- an identity-aliased
    # token also lands in `new_heads`, so the reconcile pass emits its own
    # non-retryable "kept as-is" failure for the same token.  That second
    # record is correct and expected; it is reconcile getting one more free
    # chance to merge the token before the domain phase runs.
    backstopped = [
        failure
        for failure in outcome.failures
        if failure.phase == "canonicalize"
        and "kept as its own canonical" in failure.message
    ]
    assert len(backstopped) == 1
    assert backstopped[0].tokens == ("quantum widgetry",)
    assert backstopped[0].kind == "output"
    assert backstopped[0].retryable is False


def test_an_outage_is_never_backstopped():
    outcome = _classify(
        demanded={"rust"}, canonicalizer=_FailingCanonicalizer(), batch_size=8
    )

    # Filing a skill because a request failed would make an outage permanent.
    assert "rust" not in outcome.additions.aliases
    assert outcome.metrics.canonical_identity_filed == 0
    assert [failure.kind for failure in outcome.failures] == ["call"] * len(
        outcome.failures
    )
    assert all(failure.retryable for failure in outcome.failures)


def test_the_singleton_bound_sends_its_overflow_to_the_backstop():
    outcome = _classify(
        demanded={"alpha", "beta"},
        canonicalizer=_RefusingCanonicalizer(),
        batch_size=8,
        repair_max_singletons=1,
    )

    # Both still end up with a home; the bound caps dispatch, not coverage.
    assert set(outcome.additions.aliases) == {"alpha", "beta"}
    assert outcome.metrics.canonical_identity_filed == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_classification.py -k "own_canonical or never_backstopped or singleton_bound" -v`

Expected: FAIL — `KeyError: 'quantum widgetry'` on the first test.

- [ ] **Step 3: Add the backstop**

In `src/resume_tailor_harness/taxonomy/classification.py`, immediately after the `canonical_repaired = ...` line added in Task 1 Step 6, append (still inside `if alias_batches:`):

```python
        if residue:
            # Two rounds and a singleton attempt have now declined to cluster
            # these.  A token that is its own canonical is always structurally
            # valid -- the reconcile pass reaches exactly this conclusion for
            # its own unmerged heads -- so the only thing given up is a
            # possible synonym merge, which the Merge skill dialog can restore.
            # Leaving them aliasless instead is what made them invisible
            # forever: no alias means no domain phase, and `retryable=True`
            # means the placement floor is forbidden to file them either.
            backstopped = sorted(residue)
            for token in backstopped:
                aliases.setdefault(token, token)
            canonical_identity_filed = len(backstopped)
            failures.append(
                ClassificationFailure(
                    "canonicalize",
                    tuple(backstopped),
                    "canonicalization incomplete; kept as its own canonical",
                    retryable=False,
                )
            )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_classification.py -k "own_canonical or never_backstopped or singleton_bound" -v`

Expected: PASS

- [ ] **Step 5: Write the integration test**

Add to `tests/test_services_match_gap.py`:

```python
def test_a_backstopped_token_reaches_the_placement_floor(tmp_path):
    """The floor may file it because the backstop marked it retryable=False.

    Before the backstop this token had no alias at all, so the domain phase
    never saw it and `_retryable_canonical_tokens` withheld it from the floor
    -- the two conditions that made it permanently invisible.
    """

    class _RefusingCanonicalizer:
        async def arun(self, prompt):
            return SimpleNamespace(content=SkillClusters(clusters=[]))

        def run(self, prompt):
            raise AssertionError("async path expected")

    engine = _engine_with_target_skills("Quantum Widgetry")
    path = tmp_path / "cluster_map.json"

    with get_session(engine) as session:
        result = refresh_clusters(
            session,
            canonicalizer=_RefusingCanonicalizer(),
            themer=_AsyncThemer(lambda _new, _categories: []),
            escalation_themer=_AsyncThemer(lambda _new, _categories: []),
            path=path,
        )

    placed = load_cluster_map(path).domain_of
    assert "quantum widgetry" in placed
    assert placed["quantum widgetry"].startswith("general-")
    assert result["placedByFallback"] == 1
```

Note: `SimpleNamespace` and `SkillClusters` must be imported in this test module. Check the existing imports at the top and add whichever is missing.

- [ ] **Step 6: Run it**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_match_gap.py::test_a_backstopped_token_reaches_the_placement_floor -v`

Expected: PASS

- [ ] **Step 7: Run the full backend suite and lint**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`

Expected: all PASS, ruff clean. If `test_the_escalation_cap_defers_instead_of_flooring` (`tests/test_services_match_gap.py:634`) fails, read it carefully before touching it — it guards a real invariant (the cap's deferred tokens must NOT be floored) and the backstop must not have broken it.

- [ ] **Step 8: Commit**

```bash
git add src/resume_tailor_harness/taxonomy/classification.py tests/test_taxonomy_classification.py tests/test_services_match_gap.py
git commit -m "fix(taxonomy): file unclusterable tokens as their own canonical"
```

---

### Task 3: Canonicalizer model tier

**Files:**
- Modify: `src/resume_tailor_harness/tracking/canonicalize.py:279-296` (`build_incremental_canonicalizer_agent`)
- Test: `tests/test_tracking_canonicalize.py:168-197`

**Interfaces:**
- Consumes: nothing.
- Produces: no signature change. `build_incremental_canonicalizer_agent()` now builds on `settings.mid_model`.

- [ ] **Step 1: Update the existing assertion to the new expectation**

In `tests/test_tracking_canonicalize.py`, in `test_incremental_builders_use_expected_models_and_retry_policy`, change line ~196 from:

```python
    assert [entry["model"] for entry in captured] == ["premium", "mid"]
```

to:

```python
    # The canonicalizer used to run on the PREMIUM tier while the harder domain
    # judgment ran on mid -- inverted, and premium was not buying completeness
    # anyway (every live failure was an incomplete premium partition).  Repair
    # rounds and the identity backstop now absorb coverage loss that used to be
    # permanent, so the cheaper tier's downside is bounded.  Escalation keeps
    # premium; the ambiguous tail is where it earns its cost.
    assert [entry["model"] for entry in captured] == ["mid", "mid"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_canonicalize.py::test_incremental_builders_use_expected_models_and_retry_policy -v`

Expected: FAIL with `assert ['premium', 'mid'] == ['mid', 'mid']`

- [ ] **Step 3: Change the tier**

In `src/resume_tailor_harness/tracking/canonicalize.py`, in `build_incremental_canonicalizer_agent`, replace:

```python
    model = build_model(
        settings.premium_model,
        cache_system_prompt=prompt_cache_for(settings.premium_model),
    )
```

with:

```python
    model = build_model(
        settings.mid_model,
        cache_system_prompt=prompt_cache_for(settings.mid_model),
    )
```

- [ ] **Step 4: Run the test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_canonicalize.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/canonicalize.py tests/test_tracking_canonicalize.py
git commit -m "perf(taxonomy): run the canonicalizer on the mid tier"
```

---

### Task 4: Regroup telemetry legibility

**Files:**
- Modify: `src/resume_tailor_harness/services/match_gap.py:383-395` (pass one call), `:417-431` (escalation call), `:563-630` (result dict)
- Test: `tests/test_services_match_gap.py`

**Interfaces:**
- Consumes: `ClassificationMetrics.canonical_repair_rounds` / `.canonical_repaired` / `.canonical_identity_filed` from Task 1; `Settings.taxonomy_canonical_repair_max_singletons` from Task 1.
- Produces, in the `refresh_clusters` return dict:
  - `deferredSkills: int` — never tried this run; bounded out by the escalation cap
  - `uncertainDomainSkills: int` — a domain-phase refusal or the "no high-confidence existing or coherent new domain" verdict, **excluding** deferred
  - `uncertainCanonicalSkills: int` — a canonicalize-phase omission that survived repair
  - `canonicalRepairRounds`, `canonicalRepaired`, `canonicalIdentityFiled: int`
  - `uncertainSkills` is **unchanged** and remains the existing total, so no consumer breaks.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_services_match_gap.py`:

```python
def test_the_deferred_backlog_is_reported_separately_from_uncertainty(
    tmp_path, monkeypatch
):
    """"Deferred" and "uncertain" are different futures and must read that way.

    The cap already deferred work correctly; it just never said so, so a user
    could not tell monotonic progress from a permanent plateau.
    """

    from resume_tailor_harness.config import env_settings

    monkeypatch.setenv("TAXONOMY_ESCALATION_MAX_SKILLS", "1")
    env_settings.cache_clear()

    engine = _engine_with_target_skills("Alpha Skill", "Beta Skill")
    path = tmp_path / "cluster_map.json"

    try:
        with get_session(engine) as session:
            result = refresh_clusters(
                session,
                canonicalizer=_AsyncCanonicalizer(),
                themer=_AsyncThemer(lambda _new, _categories: []),
                escalation_themer=_AsyncThemer(_languages),
                path=path,
            )
    finally:
        env_settings.cache_clear()

    assert result["deferredSkills"] == 1
    # The deferred token is not double-counted as a domain-phase verdict.
    assert result["uncertainDomainSkills"] == 0
    assert result["uncertainCanonicalSkills"] == 0
    # The pre-existing total is untouched, so old consumers keep working.
    assert result["uncertainSkills"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_match_gap.py::test_the_deferred_backlog_is_reported_separately_from_uncertainty -v`

Expected: FAIL with `KeyError: 'deferredSkills'`

- [ ] **Step 3: Pass the singleton bound through both call sites**

In `src/resume_tailor_harness/services/match_gap.py`, add this keyword argument to **both** `classify_incrementally(...)` calls (the `first = await ...` at line ~383 and the `second = await ...` at line ~417), after `enforce_candidates` / `category_hints` respectively:

```python
                repair_max_singletons=settings.taxonomy_canonical_repair_max_singletons,
```

- [ ] **Step 4: Add the telemetry keys**

In `refresh_clusters`, immediately before the `return {` statement (line ~563), add:

```python
    deferred_canonicals = deferred & requested_canonicals
    uncertain_domain = len(
        [
            token
            for token, status in statuses.items()
            if status.state == "uncertain"
            and status.phase == "domain"
            and token not in deferred_canonicals
        ]
    )
    uncertain_canonical = len(
        [
            token
            for token, status in statuses.items()
            if status.state == "uncertain" and status.phase == "canonicalize"
        ]
    )
    escalated_metrics = escalated.metrics if escalated else None
```

Then add these entries to the returned dict, next to the existing `"uncertainSkills"` key:

```python
        # "Deferred" means the escalation cap postponed it, not that anything
        # judged it -- it escalates first on the next run.  Collapsing it into
        # "uncertain" is what made monotonic progress read as a plateau.
        "deferredSkills": len(deferred_canonicals),
        "uncertainDomainSkills": uncertain_domain,
        "uncertainCanonicalSkills": uncertain_canonical,
        "canonicalRepairRounds": outcome.metrics.canonical_repair_rounds
        + (escalated_metrics.canonical_repair_rounds if escalated_metrics else 0),
        "canonicalRepaired": outcome.metrics.canonical_repaired
        + (escalated_metrics.canonical_repaired if escalated_metrics else 0),
        "canonicalIdentityFiled": outcome.metrics.canonical_identity_filed
        + (escalated_metrics.canonical_identity_filed if escalated_metrics else 0),
```

- [ ] **Step 5: Run the test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_match_gap.py::test_the_deferred_backlog_is_reported_separately_from_uncertainty -v`

Expected: PASS

- [ ] **Step 6: Run the full backend suite and lint**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`

Expected: all PASS, ruff clean.

- [ ] **Step 7: Regenerate the OpenAPI contract if the repo tracks it**

Run: `git status --short` after the suite. If `web/src/lib/api/schema.ts` or any generated contract file is dirty, that regeneration is part of this task — stage it. If nothing is dirty, skip.

- [ ] **Step 8: Commit**

```bash
git add src/resume_tailor_harness/services/match_gap.py tests/test_services_match_gap.py
git commit -m "feat(taxonomy): report the deferred backlog separately from uncertainty"
```

---

### Task 5: Surface the deferred count in the completion toast

**Files:**
- Modify: `web/src/lib/runs/announce.ts:108-127`
- Test: `web/src/lib/runs/announce.test.ts`

**Interfaces:**
- Consumes: `deferredSkills` from Task 4.
- Produces: no exported API change.

- [ ] **Step 1: Write the failing test**

Add to `web/src/lib/runs/announce.test.ts`:

```ts
it("tells the user a deferred backlog will be picked up next run", () => {
  announceCompletions([
    run({
      kind: "refreshClusters",
      result: {
        assignedSkills: 300,
        aliasesMerged: 12,
        domainsCreated: 4,
        uncertainSkills: 900,
        deferredSkills: 880,
        failedSkills: 0,
        skippedStaleSkills: 0,
      },
    }),
  ]);

  expect(toast.success).toHaveBeenCalledWith(
    "Regroup complete: 300 assigned · 12 aliases merged · 4 domains created · 900 uncertain · 880 deferred to next run · 0 failed · 0 skipped.",
  );
});

it("omits the deferred clause when nothing was deferred", () => {
  announceCompletions([
    run({
      kind: "refreshClusters",
      result: {
        assignedSkills: 5,
        aliasesMerged: 0,
        domainsCreated: 1,
        uncertainSkills: 0,
        deferredSkills: 0,
        failedSkills: 0,
        skippedStaleSkills: 0,
      },
    }),
  ]);

  expect(toast.success).toHaveBeenCalledWith(
    "Regroup complete: 5 assigned · 0 aliases merged · 1 domains created · 0 uncertain · 0 failed · 0 skipped.",
  );
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npm test -- announce`

Expected: FAIL — the first test's received string lacks the deferred clause.

- [ ] **Step 3: Add the clause**

In `web/src/lib/runs/announce.ts`, inside the `run.kind === "refreshClusters"` branch, after the `const [assigned, aliases, domains, uncertain, failed, skipped] = fields;` line, add:

```ts
    // Read separately and default to 0: a run recorded before this key existed
    // must still produce the detailed toast rather than falling back to the
    // generic one.
    const deferred = numberField(result, "deferredSkills", "deferred_skills") ?? 0;
    const deferredNote = deferred > 0 ? ` · ${deferred} deferred to next run` : "";
```

Then replace the `toast.success(...)` template literal in that branch with:

```ts
    toast.success(
      `Regroup complete: ${assigned} assigned · ${aliases} aliases merged · ${domains} domains created · ${uncertain} uncertain${deferredNote} · ${failed} failed · ${skipped} skipped.`,
    );
```

- [ ] **Step 4: Run the tests**

Run: `cd web && npm test -- announce`

Expected: PASS, including the pre-existing `"uses honest generic summaries when specialized result detail is malformed"` test.

- [ ] **Step 5: Run the full web suite**

Run: `cd web && npm test`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/runs/announce.ts web/src/lib/runs/announce.test.ts
git commit -m "feat(web): distinguish deferred from uncertain in the regroup toast"
```

---

### Task 6: Record the decisions in the taxonomy reference

**Files:**
- Modify: `src/resume_tailor_harness/taxonomy/CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code-facing.

- [ ] **Step 1: Correct the now-stale claim**

`src/resume_tailor_harness/taxonomy/CLAUDE.md` currently contains the bullet beginning **"A regroup is two passes, and the second one differs."** That bullet states canonicalize failures are sent back through pass one, which is still true but is no longer the *end* of the story. Append to that bullet:

```markdown
  A canonicalize-phase failure is no longer permanent backlog. The pass now
  repairs its own residue in geometrically shrinking rounds (`batch_size` →
  `batch_size // 4` → `1`, the singleton round bounded by
  `Settings.taxonomy_canonical_repair_max_singletons`), because re-asking the
  same tokens at the same size reproduces the same omission — `_shard` sorts
  alphabetically, so the retry was byte-identical to the attempt that failed.
  Whatever survives every round is filed as **its own canonical** and recorded
  `retryable=False`, exactly as reconcile already does for unmerged heads.
  That flag is the whole integration: `_retryable_canonical_tokens` stops
  matching, so `_apply_placement_floor` may file it, and `refresh_clusters`
  needed no change. The cost is a possible unmerged synonym, which is visible
  and fixable through Merge skill; the previous behaviour was an invisible
  skill, which was not. Only `kind="output"` failures are repaired or
  backstopped — an outage carries no judgment to honour.
```

- [ ] **Step 2: Correct the model-tier claim**

The same file's regroup discussion refers to the classification tiers. Add a new bullet:

```markdown
- **The canonicalizer runs on the mid tier, not premium.** It used to run on
  `premium_model` while the harder domain judgment ran on `mid_model` —
  inverted, and premium was not buying completeness: every one of the 446
  failure records on the reference workspace was an incomplete premium
  partition. Repair rounds and the identity backstop now absorb coverage loss
  that used to be permanent, so the cheaper tier's downside is bounded.
  Escalation keeps `premium_model`; the ambiguous tail is where it earns its
  cost. Watch the ratio of `canonicalRepaired` to `canonicalIdentityFiled` on
  a run record — a large `canonicalIdentityFiled` means the repair rounds
  stopped pulling their weight, and the tier is the first thing to reconsider.
```

- [ ] **Step 3: Record the Batch API decision**

Add a further bullet:

```markdown
- **The Message Batches API was evaluated and rejected — on latency and seam
  cost, not on ignorance.** It cannot reach these call sites without bypassing
  agno (`acall` → `AgentRunner.arun` → `Agent(output_schema=...)`; batches need
  raw `client.messages.batches.create`), which would mean re-implementing
  structured-output binding, `SpendGate.open` gating, `SpendGate.settle` usage
  recording, and the `is_transient` predicate outside the `build_model` seam,
  and forking provider support since the seam covers four vendors and Batches
  is Anthropic-only. The pipeline is also only partly batchable — reconcile is
  strictly sequential by design — so it would take three dispatches of up to an
  hour each and turn an interactive Regroup into an overnight job. And the
  money is not there: a regroup is a sub-dollar operation, so halving it does
  not pay for a second dispatch architecture. **The trigger to revisit is rate
  limiting, not cost:** if regroups start failing with `kind="call"` 429s, the
  Batches API's separate and much higher throughput ceiling becomes the actual
  reason to adopt it. Full evaluation:
  `docs/superpowers/specs/2026-08-27-taxonomy-canonicalize-repair-design.md`.
```

- [ ] **Step 4: Verify nothing else in the file now contradicts the code**

Run: `grep -n "premium\|canonicalize" src/resume_tailor_harness/taxonomy/CLAUDE.md`

Read each hit. Fix any remaining statement that the code no longer supports.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/taxonomy/CLAUDE.md
git commit -m "docs(taxonomy): record canonicalize repair, tier change, batch rejection"
```

---

## Live verification (after the PR merges)

Offline tests prove termination; they cannot prove coverage improved, because every agent call in the suite is faked. Run **one** Regroup on the deployed corpus and read the run record:

| Read | Means |
| --- | --- |
| `deferredSkills > 0` | Converging, not plateaued — click again. |
| `canonicalRepaired` high, `canonicalIdentityFiled` low | The repair rounds are doing the work. Intended outcome. |
| `canonicalIdentityFiled` in the hundreds | Repair is not pulling its weight. Reconsider Task 3's tier change first, then the round sizes. |
| `uncertainCanonicalSkills > 0` | Should now be impossible except after an outage — a non-zero value here with no `kind="call"` failures means the backstop did not fire and is a bug. |

This is a one-shot measurement on one corpus, not a regression guard. Task 2's `canonical_identity_filed == 0` assertion pins the repair-before-backstop ordering so it cannot silently regress; nothing in CI measures real-world coverage.
