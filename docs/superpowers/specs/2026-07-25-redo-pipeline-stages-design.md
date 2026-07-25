# Redo any pipeline stage

**Date:** 2026-07-25
**Status:** Approved, not yet implemented

## Problem

Work in this app is one-way. Once a job advances past `raw`, three independent
guards stop you redoing any earlier stage:

1. **Re-pull is frozen.** `discovery/merge.py:179` — when `existing.status !=
   raw`, a re-pull upgrades only the apply `url`; `jd_text` is frozen so a
   resume already tailored to the old text is not silently re-based.
2. **Re-extract is skipped.** `discovery/pipeline.py:480` — `reprocess()` skips
   every job where `has_progress()` holds (status in approved/tailored/rendered,
   or any `Application`/`ResumeVersion`/`CoverLetter` child). A tailored job can
   never have its criteria or fit score rebuilt.
3. **Re-tailor is unreachable from the UI.** Tailoring itself is ungated, but
   `resolve_targets` and the web `LaunchDialog` only ever offer *approved* jobs.

Each guard is individually correct — they protect automatic bulk runs from
clobbering user investment. Together they mean a user who wants to re-tailor one
job against a different model has no path to it.

Resetting the status by hand and re-tailoring then fails with:

```
RuntimeError: Tailoring failed for 1 of 1 jobs (job IDs: 42)
```

This message is a separate defect. `gather_isolated` (`concurrency.py:45`)
captures each job's exception into `Result.error`, but `tailor_jobs`
(`tailor/service.py:157`) does `if not res.ok: continue` — the exception is
never logged and never re-raised. `services/tailoring.py:86` then reports a bare
count. The same silent-`continue` pattern exists in `run_extract:93`,
`run_score:277`, and `run_relevance:369`; tailoring is simply the only place the
silence becomes user-visible.

## Goals

- Every stage — pull, extract/score, tailor, render — can be redone on
  explicitly chosen jobs, at any status.
- Redoing never destroys prior work and never moves a job backwards.
- Tailor a board selection regardless of status ("Tailor selected").
- A failing run names its actual cause.
- Per-job failures are durable, formatted, and triageable from the dashboard —
  with a retry that closes the loop.

## Non-goals

- Changing the automatic paths. `pull`, `discover`, `refresh`, and `reprocess`
  keep their existing guards and transitions unchanged. Redo is a separate,
  explicitly-targeted act.
- Marking versions stale when the JD text changes.
- Redo surfaces on the shortlist and triage boards.
- A dedicated `/errors` route. Failure triage extends the existing dashboard
  `AttentionCard`.
- Replacing `reprocess()`'s destructive raw-reset. `StageScope` makes that
  possible later; it is out of scope here.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Redo never deletes. New work stacks on top of old. | Prior versions and PDFs are user investment; comparison is the point. |
| 2 | Redo is explicit and targeted; bulk paths untouched. | The guards exist for a reason. Redo is an escape hatch, not a mode. |
| 3 | Stages are independent, chained by default in the dialog. | Fresh JD text with stale criteria is a trap; ticking re-pull pre-ticks re-extract, and you can untick it. |
| 4 | Status is a high-water mark. Redo never regresses it. | Status drives board placement and `has_progress`. Demoting a rendered job to `shortlisted` mid-redo is destructive in effect. |
| 5 | Redo never rejects. | Falls out of #4: `rejected` ranks below every ladder status. Rejection stays the job of `discover`/`reprocess`. |
| 6 | Per-job outcomes in the run result; every cause logged. | A partial run should finish green and say which jobs failed; a total failure should name the exception. |
| 7 | One `Redo…` bulk action, tailor pre-ticked. | "Tailor selected" *is* redo with one stage ticked. One dialog, one launch path. |
| 8 | Confirm with an explicit count; no hard cap. | `enforce_active_budget()` is the real ceiling. An arbitrary cap blocks legitimate large redos. |
| 9 | Per-job failures persist as `ErrorRecord` rows with structured details plus a truncated traceback tail. | The substrate already exists with dedupe, counts, and retention. Structured fields drive a formatted row; the tail is there when a provider SDK error needs real diagnosis. |
| 10 | A stage success auto-resolves that job+stage's open failure. | Without it the card becomes a graveyard of already-fixed failures and stops being read, which defeats triage. |
| 11 | Triage extends `AttentionCard`, grouped by kind, with a Retry action. | Retry is what makes it triage rather than a log. A dedicated route is more surface than the volume justifies. |
| 12 | `RedoParams` validates at the API boundary; `redo_jobs` trusts its inputs. | Validation belongs at system edges, not scattered through internal calls. |
| 13 | Job failure details are a typed schema, not a free-form map. | Hyrum's Law — an exposed map's keys become a contract with nothing holding them stable. A typed schema also flows into the generated TS client. |
| 14 | `GET /api/errors` is paginated. | One failed 400-job redo makes this list unbounded, and each row carries a 4 KB traceback tail. |
| 15 | `POST /api/redo` keeps the codebase's verb-style run-launch naming. | `/api/tailor`, `/api/pull`, `/api/discover`, `/api/reprocess` are all RPC-style launchers already. Consistency beats REST purity for a surface that starts a job rather than mutating a resource. |

## Architecture

### The status ladder — `tracking/stages.py` (new)

```python
_RANK = {
    JobStatus.rejected:    -1,
    JobStatus.raw:          0,
    JobStatus.extracted:    1,
    JobStatus.filtered:     2,
    JobStatus.shortlisted:  3,
    JobStatus.approved:     4,
    JobStatus.tailored:     5,
    JobStatus.rendered:     6,
}

def advance(job: Job, target: JobStatus, *, never_regress: bool) -> bool:
    """Write job.status toward target. Returns whether it wrote."""
```

With `never_regress=True` a write lands only when it moves the job forward.
`rejected` ranking below `raw` is what makes decision #5 fall out rather than
needing its own branch.

### `StageScope` — one parameter for the funnel

Every stage function in `discovery/pipeline.py` fuses three concerns: which rows
(a status query), what LLM work, and what status to write next. Redo needs the
middle concern with different answers for the other two. Replace the loose
`job_ids` argument with:

```python
@dataclass(frozen=True)
class StageScope:
    job_ids: set[int] | None = None
    any_status: bool = False      # select these ids whatever their status
    never_regress: bool = False   # advance status only forward
```

`StageScope()` reproduces today's behaviour exactly, and is pinned by a
regression test. `_stage_jobs` honours `any_status`; every `job.status = ...`
assignment routes through `advance(..., never_regress=scope.never_regress)`.

Redo passes `StageScope(ids, any_status=True, never_regress=True)`.

Rejected alternatives: redo-specific stage functions calling the exported pure
helpers directly (duplicates industry normalization, skill-alias refresh, and
location taxonomy — two copies that will drift); and temporarily demoting jobs
to `raw`, running `discover`, then restoring status (a crash mid-run strands a
rendered job at `raw` with its criteria wiped).

### `services/redo.py` (new) — the use-case

```python
RedoStage = Literal["pull", "extract", "tailor", "render"]

@dataclass(frozen=True)
class StageOutcome:
    job_id: int
    stage: RedoStage
    status: Literal["ok", "skipped", "failed"]
    detail: str | None = None

def redo_jobs(
    session: Session,
    *,
    job_ids: Sequence[int],
    stages: Sequence[RedoStage],
    deep: bool = False,
    reporter: ProgressReporter | None = None,
) -> list[StageOutcome]
```

Execution is **stage-major**: every targeted job passes through `pull`, then
every job through `extract`, and so on, in pipeline order regardless of tick
order. Stage-major is what lets `extract` and `tailor` keep their existing
`gather_isolated` fan-out over a job list, and gives one `ProgressReporter`
phase per stage. A job whose earlier stage failed still enters later stages —
its data is simply the pre-existing data.

#### `pull` — `repull_job(session, job, *, agent, allow_browser)`

Reuses `discovery/url_ingest/service.job_from_url`, so ATS-specific readers
(`_READERS`, keyed off `identify_host`) apply and only unknown hosts fall back
to LLM extraction.

- No `job.url` → `skipped("no source URL")`. Manual-source jobs land here.
- Fetch/parse failure, or empty extracted text → `failed(reason)`, **`jd_text`
  untouched**.
- Success → write `jd_text` and `content_fingerprint`; write `company`, `title`,
  `location` only where the fetch produced a value; recompute `dedup_key` when
  company or title changed.
- If the recomputed `dedup_key` would collide with a sibling row (existing
  `tracking/repository.py::company_rename_collides` guard), keep the old
  company/title/key and take **only** `jd_text`.
- `job.source` is not rewritten — provenance stays whatever originally pulled it.
- `allow_browser = get_settings().browser_enabled`, so cloud degrades with an
  explicit failure rather than hanging.

Re-pull deliberately does **not** route through `find_existing` → `decide()` →
`_apply`. That machinery answers "is this incoming posting the same job as one I
hold, and does it outrank it?" — already settled for a row the user explicitly
selected — and it is precisely what freezes `jd_text` at `merge.py:179`.
`decide()` is left untouched so the automatic pull path keeps its freeze.

#### `extract` — the funnel under a redo scope

`run_extract` → `run_filter` → `run_score` with
`StageScope(ids, any_status=True, never_regress=True)`. Produces fresh
`criteria_json`, industry normalization, location parts, skill aliases,
`fit_score`, and `fit_rationale`, with no status movement and no rejection.

`run_relevance` is not run during redo: it exists only to cheaply reject
off-target `raw` rows, so under `never_regress` it is a guaranteed no-op.

#### `tailor` — existing service, two changes

Calls `services/tailoring.tailor(job_ids=[...], deep=deep)`. In
`tailor/service.py`:

- `_persist_rounds` routes its status write through `advance(...)` instead of
  assigning `tailored` directly, so a rendered job stays rendered.
- Two additive columns on `ResumeVersion`:
  - `attempt: int = 0` — `max(existing attempt for job) + 1` per re-tailor.
    Rounds restart at 0 on every run, so without this the version list is an
    undifferentiated pile of duplicate round numbers.
  - `tailor_model: str | None = None` — the model id that produced the version.
    The motivating use case is re-tailoring against a different model; without
    this the two results are indistinguishable.

Existing rows read back as `attempt=0, tailor_model=None`. No existing version
or `pdf_path` is modified.

#### `render` — existing service

`render_version` is already unconditional and needs no change. The only new
decision is which version a job-level re-render targets: **the version the job's
`Application.resume_version_id` names, else the highest `id` among the job's
`resume_versions_for_job` rows**. Highest `id` rather than newest `created_at`
because `id` is the tiebreak the export path (`render/export.py`) already sorts
by. Deterministic, no new state. A job with no versions →
`skipped("no resume version")`.

### Failure surfacing

`tailor_jobs` returns

```python
@dataclass(frozen=True)
class TailorOutcome:
    versions: dict[int, list[ResumeVersion]]
    failures: dict[int, StageFailure]   # see Failure triage below
```

and logs each captured `Result.error` with `exc_info` and the job id.
`services/tailoring.tailor` carries `failures` through. `fail_on_partial` raises
**only when every job failed**, and the message names the first actual
exception rather than a count. Partial runs finish successfully with per-job
outcomes in the run result.

The same one-line logging fix lands in `run_extract`, `run_score`, and
`run_relevance`, which are silent today for the same reason.

### Failure triage

The `ErrorRecord` substrate already provides what triage needs — dedupe on
`(kind, source_label, status="open")`, a `count`, first/last-seen timestamps,
`open`/`dismissed`/`resolved` states, 30-day retention — and is already wired to
the dashboard's `AttentionCard`. Two gaps block per-job failures from using it:

1. `services/errors.py:15` — `_KINDS = {"run", "source"}` has no job kind.
2. `api/routers/errors.py:28` — `_row()` builds `ErrorRecordOut` from ten fields
   and omits `details_json`. Structured detail is persisted on write and then
   dropped at the API boundary, so the UI has nothing to format.

#### `StageFailure` — the shared failure value object

Built once, where the exception is still in hand:

```python
@dataclass(frozen=True)
class StageFailure:
    error_type: str        # "ValueError"
    message: str           # truncated to 300 chars
    traceback_tail: str    # last 5 frames, capped at 4000 chars

    @classmethod
    def from_exception(cls, exc: BaseException) -> StageFailure: ...
```

This is why `TailorOutcome.failures` is `dict[int, StageFailure]` rather than
`dict[int, str]` — a bare string cannot carry the traceback. The full traceback
still goes to the log via `exc_info`; only the tail is persisted.

#### Recording

Add `"job"` to `_KINDS`, plus one writer delegating to the existing
`record_error`:

```python
record_job_failure(
    session, *, job, stage, failure, run_id, model: str | None = None
) -> ErrorRecord
```

`model` is `None` for stages with no LLM model in play (a `pull` HTTP failure);
it is the resolved model id for `extract` and `tailor`.

- `source_label = f"job:{job_id}:{stage}"` — the dedupe key, so a redo that
  fails the same way twice increments `count` instead of doubling rows.
- `message = f"{error_type}: {message}"`, truncated.
- `details_json` = `jobId`, `company`, `title`, `stage`, `errorType`, `message`,
  `model`, `tracebackTail`, stored camelCase so `JobFailureDetails`
  (a `CamelModel`, which validates by alias) reads it directly. `model` is
  present because the motivating case is model-switching: when a re-tailor
  fails, the first question is which model produced it. No `attempt` — the
  failure means no version was created, so there is no attempt to name.

Both `redo_jobs` and a plain `tailor` run record through this writer, so per-job
failures land in one place regardless of which run produced them.

`StageOutcome` and `StageFailure` are not the same thing and should not be
merged: `StageOutcome` is the transient per-job row in a run's result payload
(covering `ok`/`skipped`/`failed`), while `StageFailure` is the durable
diagnostic written to `ErrorRecord`. A failed `StageOutcome.detail` carries the
same one-line message the record's `message` does.

#### Auto-resolve on success

```python
resolve_job_failures(session, job_id, stage) -> int
```

Flips matching `open` records to `resolved`; called on every stage success.
Without it a failure survives the fix that cured it, the card fills with stale
rows, and it stops being read. Manual `dismiss` remains the "I don't care about
this one" action.

### API

`POST /api/redo` → `202` + run record, through the standard `launch()` +
`session_work()` seam (`api/runs/launch.py`), run kind `"redo"`.

```python
class RedoParams(CamelModel):
    job_ids: list[int] = Field(min_length=1)
    stages: list[RedoStage] = Field(min_length=1)
    deep: bool = False

    @field_validator("job_ids", "stages")
    @classmethod
    def _dedupe(cls, v): ...   # order-preserving dedupe
```

Validation happens at this boundary and nowhere deeper: an empty `jobIds` or
`stages` is a `422`, and duplicates are collapsed so `["tailor", "tailor"]`
cannot bill twice. `redo_jobs` trusts its inputs.

Result payload is a declared schema, not an ad-hoc dict:

```python
class StageOutcomeOut(CamelModel):
    job_id: int
    stage: RedoStage
    status: Literal["ok", "skipped", "failed"]
    detail: str | None = None

class RedoResultOut(CamelModel):
    outcomes: list[StageOutcomeOut] = Field(default_factory=list)
```

#### Error records

`ErrorRecordOut` gains one **typed** field:

```python
class JobFailureDetails(CamelModel):
    job_id: int
    stage: RedoStage
    error_type: str
    message: str
    company: str | None = None
    title: str | None = None
    model: str | None = None
    traceback_tail: str = ""

class ErrorRecordOut(CamelModel):
    ...
    job_details: JobFailureDetails | None = None   # set when kind == "job"
```

`_row()` projects `details_json` through `JobFailureDetails` when
`kind == "job"`. A row whose stored JSON fails validation yields `None` rather
than a `500` — persisted JSON from an older schema is untrusted input at a read
boundary, exactly like a third-party response.

A typed field rather than a raw `details: dict[str, Any]` for two reasons.
Hyrum's Law: an exposed free-form map becomes a de facto contract on whatever
keys happen to be in it, with nothing to hold it stable. And a typed schema
flows through `openapi-typescript` into `contracts/ts/api.ts`, so the web client
gets real types instead of the hand-written shape this spec previously called
for — that hand-typing was a symptom of an untyped contract, not a solution.

Source and run records get **no** details field. Neither writes `details` today
(`record_source_failures` passes none), so exposing one would be speculative.

#### Pagination

`GET /api/errors` gains `page` (default 1) and `pageSize` (default 50, max 200),
and `ErrorRecordsOut` gains a `pagination` block built by the existing
`services/pagination.py::page_from_slice`. Both additions are additive and
backward compatible.

This is not optional polish: a single failed 400-job redo writes 400 open
records, and every job record carries a traceback tail capped at 4 KB. Unpaged,
that is a multi-megabyte response on a dashboard that loads on every visit.

Schemas are `CamelModel`, so the wire format is camelCase. OpenAPI →
`contracts/openapi.json` → `contracts/ts/api.ts` regenerated via
`bash scripts/gen_ts_client.sh`.

### Web

**`features/runs/RedoDialog.tsx`** — four stage checkboxes:

| Stage | Label | Behaviour |
|---|---|---|
| `pull` | Re-pull job description | Ticking pre-ticks Re-extract |
| `extract` | Re-extract criteria & fit score | |
| `tailor` | Re-tailor resume | Reveals the Deep review switch |
| `render` | Re-render PDF | |

Below them, an explicit count line — *"Re-pull + re-tailor 412 jobs"* — and a
confirm. No hard cap. Reuses `LaunchDialog`'s `openSeq` remount guard, which
exists because Base UI's Dialog stays mounted through its exit animation.

**`features/runs/use-redo-run.ts`** — launches through the existing
`useLaunchRun`.

**Pipeline board** — `BulkActionBar` gains a `Redo…` action beside *Set status*
and *Archive*, opening the dialog for the current selection with **Re-tailor
pre-ticked**. `selectAllMatching` resolves to ids via `fetchAllPages` over
`/api/pipeline`, the pattern `useApprovedLaunchJobs` already uses. Status is
irrelevant to eligibility — approved, tailored, and rendered jobs are all valid
targets.

**Job detail** — the same dialog from `JobModal`, scoped to one job.

The existing `Tailor approved…` button and `LaunchDialog` are kept as-is. They
serve a different purpose — a roster of approved work — and folding them into
Redo would conflate "start the pipeline" with "run it again."

**`features/dashboard/AttentionCard.tsx`** — rows group under **Sources / Jobs /
Runs** headings. A job row renders:

```
Acme — Staff Engineer                    [tailor] ×3
ValueError: match_plan_enabled requires a match-plan agent
openai:gpt-5 · 4 minutes ago
  ▸ Technical details                    [Retry] [Dismiss] [Resolve]
```

- **Retry** opens `RedoDialog` pre-filled with that job and that stage, closing
  the loop without leaving the dashboard.
- Company/title links into the job.
- **Technical details** is a collapsed expander holding `tracebackTail`.
- Top 8 shown; **Show all N** expands inline, so no new route. The existing
  **Clear all** is unchanged.
- Source and run rows keep today's rendering — they have no `jobId` to format
  around — and render `details` as a plain key/value list when present.

The card is currently a single dense JSX expression; it gets broken into
`AttentionCard` + a `JobFailureRow` component. `jobDetails` arrives fully typed
from `contracts/ts/api.ts`, so no hand-written shape is needed.

## Data flow

```
RedoDialog (stages, jobIds, deep)
  └─ POST /api/redo → 202 + runId
       └─ RunManager worker (own session, copied UserContext)
            └─ redo_jobs
                 ├─ pull     → repull_job → job_from_url → jd_text in place
                 ├─ extract  → run_extract/filter/score @ StageScope(redo)
                 ├─ tailor   → tailor(job_ids=…) → new ResumeVersion attempt
                 └─ render   → render_version(selected|newest)
       └─ GET /api/runs/{id}/events (SSE) → per-stage progress
       └─ run result: [{ jobId, stage, status, detail }]

per stage, per job:
  failed  → record_job_failure  → ErrorRecord(kind="job",
                                    source_label="job:{id}:{stage}")
  ok      → resolve_job_failures → that row flips to "resolved"

AttentionCard ← GET /api/errors?status=open
  └─ Retry → RedoDialog(jobIds=[jobId], stages=[stage]) → POST /api/redo
```

## Error handling

| Condition | Behaviour |
|---|---|
| Job id not found | `skipped("job not found")`; other jobs proceed. |
| No `url` on re-pull | `skipped("no source URL")`. |
| Fetch/parse failure | `failed(reason)`; `jd_text` preserved. |
| Browser needed, `browser_enabled=false` | `failed` with the standard cloud degradation message. |
| Per-job LLM failure | Isolated by `gather_isolated`, logged with the job id, reported as `failed`, and written to an `ErrorRecord` with structured details. |
| Same job+stage fails twice | One `ErrorRecord`, `count` incremented, `last_seen_at` bumped. |
| A previously-failed job+stage succeeds | Its open `ErrorRecord` flips to `resolved`. |
| `record_job_failure` itself raises | Logged and swallowed. Recording a failure must never turn a partial run into a total one. |
| Every job failed in a stage | Stage reports all failures; the run still reports other stages. |
| Over active-job budget | `enforce_active_budget()` raises; mapped to `429` by `launch()`. |
| Concurrent run conflict | Existing launch-seam mapping (`409`). |

## Testing

Offline; agents and the browser faked, per the existing suite.

- `test_redo_never_regresses_status` — rendered job through all four stages,
  still rendered.
- `test_redo_never_rejects` — a re-extract whose filter verdict is *reject*
  leaves status untouched and still writes the fresh fit score.
- `test_redo_never_destroys_versions` — existing `ResumeVersion` rows and
  `pdf_path`s survive a full redo; new rows carry `attempt = n + 1`.
- `test_repull_failure_preserves_jd_text` — fetch raises; `jd_text` unchanged;
  outcome `failed`.
- `test_repull_skips_job_without_url`.
- `test_repull_bypasses_frozen_jd_text` — the motivating case: a tailored job's
  `jd_text` is replaced.
- `test_repull_dedup_collision_keeps_identity`.
- `test_default_stage_scope_matches_current_behaviour` — `StageScope()`
  regression guard over `discover`.
- `test_tailor_failure_surfaces_cause` — a failing job yields a failure entry
  carrying the exception message.
- `test_all_failed_raises_with_cause` — `RuntimeError` names the first
  exception, not just a count.
- `test_render_targets_selected_version_else_newest`.
- `test_job_failure_recorded_with_details` — payload carries jobId, company,
  stage, errorType, and model.
- `test_repeated_failure_dedupes_and_counts` — same job+stage twice → one row,
  `count = 2`.
- `test_success_resolves_open_failure` — the auto-resolve invariant.
- `test_error_row_exposes_job_details` — regression guard on the `_row()`
  omission.
- `test_error_row_tolerates_unparseable_details` — legacy JSON → `jobDetails`
  is `None`, not a `500`.
- `test_traceback_tail_is_truncated` — frame and character caps hold.
- `test_errors_list_paginates`.
- `test_redo_rejects_empty_job_ids` / `test_redo_rejects_empty_stages` — `422`.
- `test_redo_dedupes_repeated_stages` — `["tailor","tailor"]` runs once.
- Web: `RedoDialog.test.tsx`, `use-redo-run.test.tsx`, a
  `PipelineContainer.test.tsx` case for Redo over a selection, and
  `AttentionCard.test.tsx` for kind grouping, formatted job rows, and Retry
  wiring into `RedoDialog`.
- Contract: `tests/api/test_openapi_contract.py` drift gate after regenerating
  the TS client.

## Files

| Path | Change |
|---|---|
| `src/resume_agent/tracking/stages.py` | New — rank ladder + `advance`. |
| `src/resume_agent/services/redo.py` | New — `redo_jobs`, `repull_job`, `StageOutcome`. |
| `src/resume_agent/discovery/pipeline.py` | `StageScope` replaces `job_ids`; status writes via `advance`; per-job failure logging. |
| `src/resume_agent/tailor/service.py` | `TailorOutcome`; `advance` in `_persist_rounds`; `attempt`/`tailor_model`; failure logging. |
| `src/resume_agent/services/tailoring.py` | Carry failures; `fail_on_partial` raises only on total failure, naming the cause. |
| `src/resume_agent/tracking/tables.py` | `ResumeVersion.attempt`, `.tailor_model`. |
| `src/resume_agent/api/schemas/runs.py` | `RedoParams`. |
| `src/resume_agent/api/routers/runs.py` | `POST /api/redo`. |
| `src/resume_agent/services/errors.py` | `"job"` kind, `StageFailure`, `record_job_failure`, `resolve_job_failures`. |
| `src/resume_agent/api/schemas/errors.py` | `JobFailureDetails`, `ErrorRecordOut.job_details`, `ErrorRecordsOut.pagination`. |
| `src/resume_agent/api/routers/errors.py` | `_row()` projects typed job details; `page`/`pageSize` on the list. |
| `web/src/features/runs/RedoDialog.tsx` | New. |
| `web/src/features/runs/use-redo-run.ts` | New. |
| `web/src/features/pipeline/PipelineContainer.tsx` | `Redo…` bulk action. |
| `web/src/components/JobModal.tsx` | Per-job `Redo…`. |
| `web/src/features/dashboard/AttentionCard.tsx` | Grouped by kind; split out `JobFailureRow`; Retry action. |
| `web/src/features/errors/use-errors.ts` | Hand-typed `details` shape. |
| `CLAUDE.md` | Document the redo path, the high-water invariant, and job-kind error records. |
