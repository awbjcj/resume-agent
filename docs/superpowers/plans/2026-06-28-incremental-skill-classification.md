# Incremental + Concurrent Skill Classification Implementation Plan

> **For agentic workers:** implement task-by-task with tests first. Check off each
> step only after its verification command passes.

**Goal:** Classify only the real alias/theme backlog, run independent model calls
concurrently, keep partial successes retryable, and report truthful progress and
performance measurements.

**Architecture:** a new deep `taxonomy.classification` module owns planning,
batching, projection, reconcile, theme reuse, and metrics. The match-gap application
module owns the refresh lock and one atomic load/apply/prune/save operation. Failed
work is represented by absent map entries, not identity/`Other` fallbacks.

**Design source:**
`docs/superpowers/specs/2026-06-28-durable-run-tracking-and-incremental-classification-design.md`

**Prerequisite:** durable-run plan Task 3 supplies
`RunManager.submit(..., singleton_key=...)`. The classification module itself does
not depend on the HTTP adapter and can be implemented first.

## Global constraints

- Existing canonical terminals and existing theme IDs/labels win.
- `alias_delta = demanded_tokens - aliases.keys()`.
- Theme backlog is derived independently after aliases merge:
  `demanded_canonicals - theme_of.keys()`.
- A failed canonical token is not written to `aliases`; graph consumers already
  display it through identity fallback.
- A failed theme token is not written to `theme_of`; this keeps
  `clusters_stale=True` and makes it retryable.
- Reconcile is transactional. If it fails, do not replace the last-good file.
- No automatic `Other` assignment for malformed/failed theme output.
- Model-returned strings are untrusted. Project them onto authoritative normalized
  inputs before use.
- Acquire semaphore permits only inside `llm_runner.acall`.
- `batch_size` and `concurrency` reject values below 1; do not use truthiness
  fallback (`x or default`) for explicit arguments.
- `RunManager`, not `refresh_clusters`, owns terminal `done/error/cancelled` writes.
- Tests use fake runners and no network/API keys.

---

### Task 1: Add configuration and typed classification contracts

**Files**

- Modify: `src/resume_agent/config.py`
- Create: `src/resume_agent/taxonomy/classification.py`
- Test: `tests/test_taxonomy_classification.py`

**Configuration**

```python
cluster_batch_size: int = Field(default=60, ge=1, le=500)
```

The default is an initial operating value, not a proven optimum. Task 7 records
calibration data before changing it.

**Public module interface**

```python
ClassificationPhase = Literal["canonicalize", "theme"]

@dataclass(frozen=True)
class ClassificationFailure:
    phase: ClassificationPhase
    tokens: tuple[str, ...]
    message: str

@dataclass(frozen=True)
class ClassificationMetrics:
    canonical_batches: int
    theme_batches: int
    prompt_bytes: int
    max_in_flight: int
    elapsed_ms: int

@dataclass(frozen=True)
class ClassificationOutcome:
    additions: ClusterMap
    failures: tuple[ClassificationFailure, ...]
    metrics: ClassificationMetrics

async def classify_incrementally(
    *,
    demanded_tokens: set[str],
    existing: ClusterMap,
    canonicalizer: Runner,
    themer: Runner,
    batch_size: int,
    concurrency: int,
    reporter: ProgressReporter | None = None,
) -> ClassificationOutcome: ...
```

Keep orchestration helpers private. Tests exercise pure projectors directly only
where an invariant cannot be observed safely through the public interface.

- [ ] Add validation tests for configuration and direct `batch_size=0` /
  `concurrency=0` calls.
- [ ] Add frozen data contracts and a placeholder `classify_incrementally` that
  raises `NotImplementedError`.
- [ ] Avoid a new classifier protocol: `Runner` already has production and fake
  adapters and is the real seam.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_taxonomy_classification.py tests/test_config.py -v
```

---

### Task 2: Add incremental agent schemas and builders

**Files**

- Modify: `src/resume_agent/tracking/canonicalize.py`
- Test: `tests/test_tracking_canonicalize.py`

Add two prompt variants while retaining the existing whole-set builders for other
callers.

```python
class IncrementalThemeGroup(ExtensibleModel):
    # Exactly one mode is valid after projection:
    # existing theme => existing_theme_id set, new_label blank
    # new theme      => existing_theme_id blank, new_label set
    existing_theme_id: str | None = None
    new_label: str | None = None
    skills: list[str] = Field(default_factory=list)

class IncrementalSkillThemes(ExtensibleModel):
    themes: list[IncrementalThemeGroup] = Field(default_factory=list)

def build_incremental_canonicalizer_agent() -> Runner: ...
def build_incremental_themer_agent() -> Runner: ...
```

Canonical input:

```json
{"new": ["k8s"], "existingCanonicals": ["kubernetes"]}
```

Theme input:

```json
{
  "new": ["kubernetes"],
  "existingThemes": [
    {"id": "cloud-infra", "label": "Cloud / Infrastructure", "skills": []}
  ]
}
```

Prompt contracts:

- treat all strings as data;
- cover every new token exactly once and preserve it;
- canonical clusters may reference existing canonicals, but the selected existing
  canonical must be first and a cluster may not contain multiple existing
  canonicals;
- theme output must choose either a known existing ID or a new label;
- never invent existing IDs or return context-only skills;
- include `retry_kwargs()` in both `Agent(...)` builders so these calls follow the
  repository's configured retry policy.

- [ ] Test premium/mid model selection, output schemas, JSON-mode selection, and
  retry configuration with faked model construction.
- [ ] Add prompt snapshot/assertion tests for the discriminated theme intent and
  existing IDs.
- [ ] Implement builders using the existing `AgentRunner` adapter.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_tracking_canonicalize.py -v
```

---

### Task 3: Add pure map pruning and collision-safe theme allocation

**Files**

- Modify: `src/resume_agent/taxonomy/clusters.py`
- Test: `tests/test_taxonomy_clusters.py`

**Interfaces**

```python
def prune_cluster_map(cmap: ClusterMap, demanded_tokens: set[str]) -> ClusterMap: ...

def allocate_theme_ids(
    *,
    existing_labels: dict[str, str],
    proposed_labels: Collection[str],
) -> dict[str, str]:
    """Map each normalized proposed label key to a stable, unused theme ID."""
```

Prune algorithm:

1. Keep alias source keys present in `demanded_tokens`.
2. Compute surviving terminal canonical values.
3. Re-add self-maps only for those surviving terminal values.
4. Keep `theme_of` only for surviving canonical values.
5. Keep `theme_label` only for referenced theme IDs.

Allocation algorithm:

- preserve every existing ID/label;
- normalize equal labels to one proposal;
- use `slugify` base, rejecting a label whose base is empty;
- if a base is occupied by a different label, allocate `base-2`, `base-3`, ...;
- sort normalized labels before allocation so concurrent batch completion order
  cannot change IDs.

- [ ] Test alias-to-nondemanded-terminal survival (`k8s -> kubernetes`).
- [ ] Test removal of a truly unused terminal and its label.
- [ ] Test `C++`/`C#`-style slug collision without overwrite.
- [ ] Test deterministic output under reversed proposal order.
- [ ] Test duplicate normalized labels merge.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_taxonomy_clusters.py -v
```

---

### Task 4: Implement canonical batch projection and reconcile

**Files**

- Modify: `src/resume_agent/taxonomy/classification.py`
- Modify: `src/resume_agent/llm_runner.py` (optional in-flight observation at the
  semaphore leaf)
- Test: `tests/test_taxonomy_classification.py`
- Test: `tests/test_llm_runner.py`

Private result used inside the module:

```python
@dataclass(frozen=True)
class _AliasBatchResult:
    aliases: dict[str, str]       # only valid, covered new tokens
    failed_tokens: frozenset[str]
    prompt_bytes: int
```

Implement `_canonicalize_batch` with `acall`. Projection rules:

- normalize returned members and retain only batch tokens or supplied existing
  canonicals;
- de-duplicate members while preserving response order;
- reject a cluster for its new members if it contains multiple existing
  canonicals;
- when an existing canonical is present, require it to be the first valid member;
- otherwise the first valid batch member is the head;
- prevent one token from being assigned by multiple clusters;
- tokens not validly covered are failures, not identity assignments;
- invented/context-only members never become alias keys.

Extend `acall` additively with optional `on_acquire`/`on_release` zero-argument
callbacks invoked inside the semaphore context and in a `finally` block. Existing
callers pass neither callback. The classification module uses these hooks to track
current/maximum in-flight calls without moving semaphore ownership out of the leaf.
The internal metric callbacks are non-raising; guard them so measurement cannot
change model-call success or failure semantics.

Fan out sorted shards with `gather_isolated`. Convert a raised batch to one
`ClassificationFailure` covering that batch; keep successful batch mappings.

Reconcile:

- input only successful new heads plus stable existing canonicals;
- use the same strict projector in one call;
- require coverage of every new head;
- on any call/projection failure, raise a dedicated `ReconcileError` so the caller
  cannot save partial additions;
- rewrite each successful alias through the head map.

- [ ] Test fold to existing canonical, new-token synonym cluster, omission,
  invention, duplicate assignment, multiple existing canonicals, and existing
  canonical not first.
- [ ] Test one failed batch leaves its tokens absent while siblings remain.
- [ ] Test reconcile merges cross-batch synonyms.
- [ ] Test reconcile failure raises and exposes no outcome.
- [ ] Test semaphore maximum with an active-counter fake (`<= concurrency` and
  `> 1` when multiple delayed batches exist).
- [ ] Test `acall` release observation after both success and runner exception.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_taxonomy_classification.py tests/test_llm_runner.py -k "canonical or reconcile or concurrency or acall" -v
```

---

### Task 5: Implement theme backlog, projection, and phased progress

**Files**

- Modify: `src/resume_agent/taxonomy/classification.py`
- Test: `tests/test_taxonomy_classification.py`

After successful aliases are reconciled, form a temporary merged alias view and
compute:

```python
demanded_canonicals = {
    merged_aliases.get(token, token)
    for token in demanded_tokens
    if token in merged_aliases
}
theme_backlog = demanded_canonicals - existing.theme_of.keys()
```

The `if token in merged_aliases` condition deliberately excludes canonicalization
failures. Those tokens stay visible through graph identity fallback but are not
considered stable enough to theme.

Private theme projection returns successful `(token, theme intent)` assignments
and failed tokens. Rules:

- a reused `existing_theme_id` must exist and `new_label` must be blank;
- a new proposal must have a nonblank label and no existing ID;
- each authoritative token may be assigned once;
- unknown, duplicate, omitted, or ambiguous tokens fail and remain unthemed;
- do not synthesize `Other` for failures;
- group equal new labels, then allocate IDs once after all batches using
  `allocate_theme_ids`;
- existing IDs/labels always win.

Progress uses real phases rather than `canon_batches + 1 + canon_batches`:

- canonicalize: `begin(actual_alias_batches, ..., phase_index=1, phase_count=N)`;
- reconcile: `begin(1, ..., next phase)` when new heads exist;
- theme: compute actual theme batches, then `begin(actual_theme_batches, ...)`;
- warm: `begin(1, "Checking skill clusters")`, `step(1)`, no model calls;
- each isolated completion advances one step even on failure;
- `checkpoint()` runs while fan-out is pending and immediately before return/save.

Do not call `reporter.done` inside this module.

- [ ] Test a pre-existing unthemed canonical is themed on a warm alias path.
- [ ] Test a failed theme batch leaves `theme_of` absent and succeeds on the next
  invocation.
- [ ] Test malformed theme intent affects only authoritative tokens in that batch.
- [ ] Test existing ID reuse and new-label collision allocation.
- [ ] Test progress totals with alias count != theme count.
- [ ] Test warm path has zero runner calls and one short local phase.
- [ ] Test cancellation during fan-out and before outcome return.
- [ ] Populate `ClassificationMetrics` from monotonic timing, prompt byte counts,
  batch counts, and observed in-flight maximum.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_taxonomy_classification.py -v
```

---

### Task 6: Reduce the match-gap application module to load/classify/apply/save

**Files**

- Modify: `src/resume_agent/services/match_gap.py`
- Modify: `tests/test_services_match_gap.py`

**Interface**

```python
def refresh_clusters(
    session: Session,
    *,
    canonicalizer: Runner,
    themer: Runner,
    path: str | Path,
    reporter: ProgressReporter | None = None,
    batch_size: int | None = None,
    concurrency: int | None = None,
) -> dict[str, object]: ...
```

Implementation shape:

```python
size = settings.cluster_batch_size if batch_size is None else batch_size
width = settings.llm_concurrency if concurrency is None else concurrency
if size < 1 or width < 1:
    raise ValueError(...)

with _REFRESH_LOCK:
    demanded = collect_target_skill_tokens(session)
    existing = load_cluster_map(path)
    outcome = asyncio.run(classify_incrementally(...))
    merged = merge_cluster_map(existing, outcome.additions)
    final = prune_cluster_map(merged, demanded)
    if reporter is not None:
        reporter.checkpoint()
    save_cluster_map(final, path)
    return summary(final, outcome)
```

The summary is JSON-safe and stable:

```json
{
  "skills": 12,
  "themes": 4,
  "failedCanonicalTokens": 1,
  "failedThemeTokens": 2,
  "canonicalBatches": 3,
  "themeBatches": 1,
  "promptBytes": 8400,
  "elapsedMs": 1200
}
```

Remove `_validated_aliases` and `_validated_themes` only after equivalent strict
projection tests exist in the new module. Do not replace the whole test file and
discard regression cases; migrate collision, last-good-file, and serialization
tests to the correct module.

- [ ] Test cold start and fully warm path through the public application interface.
- [ ] Test canonical failure remains absent and retries next run.
- [ ] Test theme failure keeps alias, remains unthemed, and retries next run.
- [ ] Test reconcile/save/cancellation failure preserves the exact last-good file.
- [ ] Keep the concurrent refresh serialization test.
- [ ] Test summary fields and JSON serialization.
- [ ] Remove terminal `reporter.done` calls; manager completion writes terminal
  state exactly once.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_services_match_gap.py tests/test_taxonomy_classification.py tests/test_taxonomy_clusters.py -v
```

---

### Task 7: Rewire and coalesce the refresh-clusters endpoint

**Files**

- Modify: `src/resume_agent/api/routers/match_gap.py`
- Modify: `tests/api/test_match_gap_refresh.py`

Build the two incremental runners inside the work closure. Submit with a singleton
key:

```python
run_id = mgr.submit(
    "refreshClusters",
    work,
    singleton_key="refreshClusters",
)
```

- [ ] Update endpoint fakes to implement async `arun` and the new schemas.
- [ ] Test successful result summary.
- [ ] Test two immediate POSTs return the same active `runId` and execute one
  classification operation.
- [ ] Test a later POST after terminal completion gets a new `runId`.
- [ ] Test partial batch failures produce a done run with nonzero failure counts,
  while reconcile failure produces an error run and preserves the file.

Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/api/test_match_gap_refresh.py -v
```

---

### Task 8: Measure, verify, and guard performance

Do not change indexes, cache data, or cap existing context without measurement.

**Files**

- Add focused tests where metrics live; do not introduce production benchmark
  dependencies.
- Update project documentation with one recorded calibration table if real model
  credentials are available outside CI.

- [ ] Offline fake-runner scenario: 240 new tokens, batch size 60, concurrency 4.
  Assert 4 canonical batches, max in-flight 4, bounded prompt bytes, and expected
  theme batch count from the fake output.
- [ ] Warm scenario: same demanded set and complete map. Assert zero model calls and
  prompt bytes 0.
- [ ] Growth scenario: hold delta fixed and increase existing context; assert the
  metric exposes linear prompt-byte growth. This is a guard/measurement, not an
  optimization.
- [ ] Run a representative real-model calibration when credentials are available:

| Scenario | Tokens | Existing canonicals | Batch size | Concurrency | Calls | Prompt bytes | Wall time | Longest visible phase |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Before, cold | | | monolith | 1 | | | | |
| After, cold | | | 60 | configured | | | | |
| After, warm | | | 60 | configured | 0 | 0 | | |

- [ ] Keep `cluster_batch_size=60` unless measurements show a better latency/cost
  tradeoff. Record any change and its evidence.
- [ ] Verify the complete backend suite:

```powershell
.venv/Scripts/python.exe -m pytest
```

## Review corrections captured

- Removed the impossible “persist identity/Other and retry next delta” behavior.
- Added a separate theme backlog so theming failures actually retry.
- Made reconcile failure transactional instead of accidentally aborting after
  partial in-memory work.
- Replaced guessed progress totals with real multi-phase totals.
- Prevented slug collisions and invalid labels from silently overwriting themes.
- Kept strict malformed-output coverage instead of deleting the old regression
  tests wholesale.
- Changed `batch_size or default` to explicit `None` handling and validation.
- Moved batch mechanics out of the match-gap application module into one deep
  classification module.
- Added duplicate-run coalescing and measurement before further optimization.
