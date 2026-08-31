# Concurrent LLM calls for discover / extract / tailor

**Status:** design approved, pending spec review
**Date:** 2026-06-24
**Branch:** feat/lifecycle-jd-rendering (or a fresh feature branch off it)

## Problem

The discovery and tailor phases issue LLM calls in serial `for` loops. Every
job's network round-trip blocks the next, so wall-clock time grows linearly with
job count even though the calls are independent and I/O-bound. CLAUDE.md's
"Known design notes" already flags this: *"Tailor loop is synchronous. Parallel
reviewer panels and job-level concurrency are deferred."* This spec lifts that
deferral.

The serial loops:

- `discovery/pipeline.py`: `run_relevance`, `run_extract`, `run_score` — one LLM
  call per job, fully serial.
- `tailor/service.py`: `tailor_jobs` loops jobs serially; inside each job
  `tailor/panel.py::run_panel` runs reviewers serially.

## Goal & success criteria

- **Goal:** run independent LLM calls concurrently in discovery (relevance,
  extract, score) and tailor (across jobs *and* across each job's reviewer panel).
- **Success:** for N independent units, wall-clock approaches
  `ceil(N / concurrency) × per-call latency` instead of `N × per-call latency`,
  bounded by a global concurrency cap. On the success path, results and final DB
  state are identical to the serial path. Discovery keeps its existing
  per-item failure isolation; tailor improves the error path by skipping a
  failed job, leaving it in its prior status for retry, and persisting successful
  peers. All existing tests pass; new tests prove the cap, error isolation,
  ordering, and a measurable speedup with delayed fakes.
- **Non-goals:** parallelizing the inherently-sequential draft→review→revise
  *rounds*; changing prompts, models, or the CLI/API surface; touching
  single-call sites (URL ingest, cover letters) — they keep the sync `run()`.

## Decisions (resolved during brainstorming)

1. **Concurrency primitive: asyncio + agno `arun`.** Not threads. Rationale below.
2. **Tailor scope: both axes.** Jobs concurrent *and* each job's reviewer panel
   concurrent (nested fan-out, capped by one shared semaphore).
3. **Rate limiting: global semaphore + agno's built-in backoff retry.** A single
   `asyncio.Semaphore` caps total in-flight calls; retry/backoff is delegated to
   agno's per-agent config, not owned by our code.
4. **New module `src/resume_tailor_harness/concurrency.py`** holds the fan-out helper.

## Why asyncio is safe here (and dodges the Session landmine)

`SQLModel`/SQLite `Session` is not thread-safe (CLAUDE.md; the API opens a fresh
session per worker thread). With asyncio the event loop is single-threaded, so:

- DB reads (load rows) happen before the fan-out, on the main thread.
- LLM calls fan out as coroutines — the only concurrent work.
- DB writes + commit happen after, on the same thread.

No locks, no per-worker sessions. The thread-unsafety only bites with threads.

The LLM functions are **already pure** (no `Session`): `judge_relevance`,
`extract_job_criteria`, `score_fit`, and `run_tailor_review` all take text +
agents and return values. That is the seam the whole design rests on.

## Architecture

### The concurrency seam — `src/resume_tailor_harness/concurrency.py`

```python
async def gather_isolated(
    items: Sequence[T],
    fn: Callable[[T], Awaitable[R]],
    *,
    on_complete: Callable[[int], None] | None = None,
) -> list[Result[R]]:
    ...
```

- Starts one task per item and leaves concurrency limiting to the leaf LLM call.
  This is deliberate: orchestration coroutines must never hold a permit while
  awaiting child calls that also need permits, or nested tailor fan-out can
  deadlock.
- Calls `on_complete(completed_count)` as each item finishes so a progress
  counter can step by completion count (completion order is nondeterministic).
- **Per-item error isolation:** a coroutine that raises is captured as a failed
  `Result` rather than aborting the batch — matching today's per-job `try/except`
  ("one job's bad output doesn't discard every other job's work").
- Returns results in **input order**, each tagged success/failure, so the caller
  applies them deterministically and final DB state matches the serial path.
- **No retry/backoff logic** — delegated to agno (see below).

### Runner protocol gains `arun`

`llm_runner.py`:

- `Runner` protocol adds `async def arun(self, prompt: str) -> Any`.
- `AgentRunner.arun` delegates to agno's native `agent.arun(prompt)`.
- `acall(agent, prompt, *, sem)` is the only function that acquires the shared
  `asyncio.Semaphore`, and it holds the permit only for the leaf agent call.
- Sync `run()` stays for single-call sites (URL ingest, cover letters).
- Test fakes get a trivial `arun` wrapping their existing sync `run` (plus, where
  a test asserts on it, an injectable artificial delay).

> agno's async path (`agno/agent/_run.py::_arun`) uses `await asyncio.sleep` for
> retry backoff — it yields the loop, so a peer's backoff never blocks others.
> (Verified against agno 2.6.12. The plan re-verifies `Agent.arun` routes to the
> non-blocking `_arun` path, not a `time.sleep` one.)

### Retry / backoff — agno per-agent config

A shared helper in `llm_runner.py` (or `config`-adjacent):

```python
def retry_kwargs() -> dict:
    s = get_settings()
    return dict(
        retries=s.llm_retries,
        delay_between_retries=s.llm_retry_delay,
        exponential_backoff=True,
    )
```

Spread into every `Agent(...)` in the `build_*_agent` functions: extract, fit,
relevance, the URL extractor, cover-letter agents, and the tailor/reviser plus
the per-reviewer agents built in `services/agents.py::build_tailor_bundle`.

**Caveat (locked in by decision #3):** agno's retry loop catches bare
`except Exception`, so it retries 429s *and* unrecoverable errors (schema/parse
failures) alike. Today a parse failure is a cheap instant skip; with retries on,
each parse failure burns `retries` extra calls before giving up. Mitigation: a
modest default `llm_retries = 2`.

### Async containment at the orchestration boundary

The async stays behind sync public functions. `discovery/pipeline.py` phase
functions and `tailor/service.py` keep their **sync** signatures; internally they
create a semaphore and call `asyncio.run(...)` for the pure LLM fan-out. `cli.py`
and the API `RunManager` are unchanged — the API's threadpool worker calls the
sync service, which spins its own loop (safe: worker threads have no running
loop). No `await` leaks to adapters.

## Phase-by-phase changes

Each phase follows: **(a)** load rows (sync) → **(b)**
`await gather_isolated(...)` the pure LLM fn → **(c)** apply results + commit
(sync, main thread). Apply order = input order.

### Discovery — `discovery/pipeline.py`

`run_relevance`, `run_extract`, `run_score` each gain an async core. The pure
calls are gathered keyed by job id; failed results are skipped on apply (job left
in its prior status for the next run, exactly as the current `try/except` does).
The cheap deterministic `run_filter` stays serial (no LLM). `discover()`
orchestrates; the phases run in sequence (relevance → extract → filter → score),
but within each phase the per-job calls are concurrent.

### Tailor — `tailor/service.py` + `tailor/panel.py`

- `tailor_jobs` gathers `arun_tailor_review` across jobs via `gather_isolated`.
- `arun_panel` runs its reviewers concurrently through `acall`; reviewer calls
  all settle before a reviewer error is re-raised, so the whole job can be
  isolated by the job-level `gather_isolated`.
- Jobs and panels share the **same** global semaphore, threaded into every leaf
  `acall`, so nested fan-out (jobs × reviewers) cannot exceed `llm_concurrency`.
- `run_tailor_review` becomes async (its `run_panel` call is awaited); the
  draft→review→revise rounds remain sequential within a job.
- DB writes (`save_resume_version`, `save_job`) run **after** each job's review
  completes, serially on the main thread — the coroutines themselves touch no
  `Session`.

## Concurrency control & config

New `Settings` fields (`config.py`):

| Field | Default | Meaning |
| --- | --- | --- |
| `llm_concurrency` | `8` | Max in-flight LLM calls across all phases (semaphore size, validated `>= 1`). |
| `llm_retries` | `2` | agno `retries` per agent (validated `>= 0`). |
| `llm_retry_delay` | `1` | agno `delay_between_retries` seconds, with exponential backoff (validated `>= 0`). |

One semaphore is created per `asyncio.run` invocation, sized from
`llm_concurrency`, and threaded into the async LLM siblings. It is acquired only
inside `llm_runner.acall`.

## Progress reporting under concurrency

`ProgressReporter.step(current)` is driven from the fan-out completion callback:
step a running completed-count, not the input index. ETA stays honest (rate =
completed / elapsed; see `progress_stats`). Phase indices/labels unchanged. The
single-threaded loop means no locking around the reporter or its file writes.

## Error isolation & ordering

- Discovery per-item failures are isolated by `gather_isolated` (matches current
  behaviour). Tailor job failures are also isolated (intentional improvement over
  serial all-or-nothing job iteration on the error path).
- Retries (429 + transient + unrecoverable) handled by agno; our code sees only
  the final success/failure after agno exhausts its attempts.
- Results applied in deterministic input order → success-path DB state identical
  to serial.

## Testing

- `concurrency.gather_isolated`:
  - input-order preservation despite out-of-order completion;
  - a raising item is isolated as a failed `Result`, peers still succeed;
  - progress counter steps once per completion.
- `llm_runner.acall` with a shared semaphore:
  - cap enforced (max simultaneously-running observed <= `llm_concurrency`);
- Per phase (discovery + tailor): a fake agent with an artificial `await` delay
  proves (a) results/DB match the serial baseline and (b) wall-clock with
  `llm_concurrency=N` is meaningfully below the serial sum; a throwing fake proves
  isolation leaves other jobs intact and the bad job in its prior status.
- All existing fakes extended with `arun` (thin async wrapper over `run`).
- Offline: no API key, no network — unchanged test contract.

## Risks

- **agno `arun` + `output_schema` parity** with sync `run` — confirm structured
  output still parses on the async path. Verified early in the plan.
- **Bare-except retry** (above) retries unrecoverable errors; mitigated by low
  default `llm_retries`.
- **429 under burst** despite the cap — the semaphore bounds steady-state, but a
  provider's per-minute budget can still trip; agno backoff absorbs blips. If it
  proves insufficient in practice, lower `llm_concurrency` (config-only change).
- **`asyncio.run` inside an already-running loop** would fail — not a path here
  (CLI main thread, API worker threads have no loop), but noted so a future async
  caller doesn't call the sync service from within a loop.

## Out of scope / follow-ups

- Per-phase or per-provider concurrency limits (single global cap for now).
- Owning a 429-specific backoff (chosen against — agno's blanket retry is the
  trade for less code).
- Streaming progress of individual review rounds.
