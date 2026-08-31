# Architecture Deepening, Bug Fixes, and Agent/HTTP Performance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close five verified correctness defects, deepen three shallow seams, and cut the per-LLM-call and per-HTTP-request overhead that currently scales with the wrong unit — spend metering per _call_ instead of per _phase_, and TLS handshakes per _request_ instead of per _host_.

**Architecture:** Three seams absorb the work. `SpendGate` (new, `tenancy/spend.py`) becomes the single place key selection and budget policy are resolved, replacing the duplicated `resolve_api_key`/`shared_key_available`/`enforce_agent_budget` derivation that runs twice per call today. `BoardSession` (new, `discovery/connectors/http.py`) becomes the single place connectors talk HTTP, absorbing the connection pool, the `timeout=30` constant copy-pasted across ~15 modules, and the 429/5xx retry that only Workday has. `RunEventSource` unifies run-progress SSE onto the notifier the conversation stream already uses. Everything else is a bug fix or a prompt-cache restructuring behind existing interfaces.

**Tech Stack:** Python 3.13, FastAPI, SQLModel/SQLAlchemy, Pydantic v2, agno 2.6.x, httpx, pytest

**Spec:** none — this plan is the deliverable. Findings are cited to `file:line` below and were read directly, not inferred.

---

## Global Constraints

- **Backend tests:** `.venv/Scripts/python.exe -m pytest` (offline — no API key, no network). All agent calls and the Playwright browser are faked.
- **Lint:** `ruff check` must pass before every commit.
- **No behavioural change to fact-lock, source priority, redo, or tenancy isolation.** Every invariant in the root `CLAUDE.md` "Core invariants" section stays exactly as written. Where this plan touches a documented invariant, the tests decide which side is stale: W1-T1 corrects prose because tests pin the code, and W2-T4 corrects prose because the code is what will change.
- **The egress gateway is not bypassed.** `security/outbound.py` remains the only path for _user-supplied_ URLs. `BoardSession` (W3) serves _configured_ board endpoints only, and `fetch_public_text` gains a client parameter it already accepts — it does not gain a second policy.
- **Measure before and after.** Every performance task in W2/W3/W4 lands with a number from the harness in W0, not an assertion that it is faster. A task whose measured delta is within noise is reverted, not merged.
- **Contract regeneration:** no `api/schemas/*` change is planned. If one becomes necessary, run `bash scripts/gen_ts_client.sh` and commit `contracts/openapi.json` + `contracts/ts/api.ts` + `web/src/lib/api/schema.ts`; `tests/api/test_openapi_contract.py` is a drift gate.

---

## Evidence — what was actually found

Each row was read in the current tree. Severity is impact × likelihood, not effort.

| #   | Finding                                                                                                                                                                                                                                                                                                                                                                        | Where                                                                                                                                                                                                                  | Severity |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| F1  | **Documentation drift, not a code defect.** `CLAUDE.md` and ADR-0009 §Consequences ¶1 state `global_monthly_cost` / `global_weekly_usage` "both filter out `User.role == 'admin'`". Neither query joins `User`. But two tests assert the _opposite_ by name, and ADR-0010 plus ADR-0009's own later paragraph agree with the code. The prose is stale; the runtime is correct. | Docs: `CLAUDE.md`, `docs/adr/0009-…:89-96`. Code: `tenancy/quotas.py:404-415`, `tenancy/limits.py:78-87`. Tests: `tests/tenancy/test_cost_quotas.py:306,338`. Superseding: `docs/adr/0009-…:109`, `docs/adr/0010-…:26` | Medium   |
| F2  | Both H-1B agent call sites bypass `expect_schema`, which `CLAUDE.md` names as a regression. A raw-`str` return (truncation, refusal, or a provider 400 body) raises a bare Pydantic error that the surrounding `except Exception` converts into a generic "unavailable".                                                                                                       | `h1b/service.py:183`, `h1b/service.py:225`, swallowed at `h1b/service.py:334`                                                                                                                                          | High     |
| F3  | Per LLM call the spend path opens ~11 SQLite sessions and 3 exclusive `BEGIN IMMEDIATE` transactions, and runs 2 unindexed full-table `SUM` scans over `usage_events`. `CONTEXT.md` says a Budget is "checked when a phase starts, not per call."                                                                                                                              | `llm_runner.py:100-136`, `tenancy/limits.py:105-218`, `tenancy/usage.py:163-246`                                                                                                                                       | High     |
| F4  | That entire spend path is **synchronous blocking I/O executed inside `AgentRunner.arun`**, i.e. on the asyncio event loop that the concurrent fan-out shares. Every sibling call in a `gather_isolated` batch stalls behind it, including on a `BEGIN IMMEDIATE` lock wait.                                                                                                    | `llm_runner.py:119-136`                                                                                                                                                                                                | High     |
| F5  | `usage_events` has `(user_id, ts)` and `user_id` indexes only. The two global aggregates filter on `own_key` + `ts` with no `user_id` predicate, so they cannot use either index — full scan of a table that grows one row per LLM call forever.                                                                                                                               | `tenancy/system_db.py:151-154`                                                                                                                                                                                         | High     |
| F6  | Every ATS connector calls module-level `httpx.get(...)`: a fresh client, TCP connection, and TLS handshake per request, no keep-alive, no HTTP/2, no shared pool. Board pulls are list-then-detail N+1 against a _single host_.                                                                                                                                                | greenhouse, lever, ashby, workday, breezy, jazzhr, bamboohr, smartrecruiters, …                                                                                                                                        | High     |
| F7  | `harvest_detailed` fetches every surviving row's detail strictly serially, though the fetches are independent.                                                                                                                                                                                                                                                                 | `discovery/connectors/harvest.py:107-127`                                                                                                                                                                              | Medium   |
| F8  | `cache_system_prompt` is enabled for tailor/coach/interview/scout/career-lab but **not** for the agents that run N-times-per-run: fit, extract, relevance, industry, canonicalize, groups, url-ingest, scraper-learn, profile-\*.                                                                                                                                              | `discovery/fit.py:80`, `discovery/extract.py`, `discovery/relevance.py`, …                                                                                                                                             | High     |
| F9  | `compose_fit_input` puts the entire `ProfileFacts` JSON first in **every one of N** per-job user messages. It is identical across the whole run and sits in the one message kind agno cannot cache.                                                                                                                                                                            | `discovery/fit.py:100-119`                                                                                                                                                                                             | High     |
| F10 | `refresh_agent_api_key` mutates `model.api_key`, `model.client = None`, `model.async_client = None` on a model shared by N in-flight coroutines. When the selected key flips mid-run (shared → own on budget exhaustion) it nulls the client sibling requests are using.                                                                                                       | `llm_runner.py:776-812` vs. fan-out at `discovery/pipeline.py:123,310,422`                                                                                                                                             | Medium   |
| F11 | `h1b_tools`'s `finally: await tools.close()` runs even when `connect()` raised, masking the original failure with a secondary one.                                                                                                                                                                                                                                             | `h1b/mcp.py:70-74`                                                                                                                                                                                                     | Low      |
| F12 | Run-progress SSE polls a JSON file from disk every 500 ms inside an async generator (blocking read on the event loop), while the conversation stream already has a `StreamNotifier`. Same problem, fixed once.                                                                                                                                                                 | `api/runs/sse.py:33-57` vs. `api/runs/notify.py`                                                                                                                                                                       | Medium   |
| F13 | `enrich_companies` issues one `SELECT` per company on read and one more per company on write — 2N queries where the display path already has a batched seam (`h1b/cache.py::load_company_evidence`).                                                                                                                                                                           | `h1b/service.py:260-272`, `h1b/service.py:363-393`                                                                                                                                                                     | Low      |
| F14 | `has_active_rate` and `find_rate` open a session per call for near-static reference data, with no caching, on the hot path.                                                                                                                                                                                                                                                    | `tenancy/costs.py:103-131`                                                                                                                                                                                             | Medium   |
| F15 | `bounded_h1b_result` **raises** when a tool result exceeds the cap. The agent loop's contract is that every tool call receives a result — even a denial — so the model can recover; raising aborts instead.                                                                                                                                                                    | `h1b/mcp.py:27-39`                                                                                                                                                                                                     | Medium   |
| F16 | `_industry_scope` runs `criteria_json LIKE '%"_industry_candidate"%'` on every extract pass — an unindexed full scan of the jobs table, despite `CLAUDE.md` describing the pass as scoped.                                                                                                                                                                                     | `discovery/pipeline.py:189-201`                                                                                                                                                                                        | Low      |

---

## Resolved: F1 is a docs bug, and the docs contradict themselves

My first read of F1 was that the code had lost an invariant the docs describe. The tests settle it the other way, and they are named for it:

- `tests/tenancy/test_cost_quotas.py:306` — `test_admin_shared_usage_is_bounded_by_global_cost_quota`
- `tests/tenancy/test_cost_quotas.py:338` — `test_admin_usage_counts_toward_global_cost_quota_for_other_users`

ADR-0010 §26 agrees ("Administrators bypass user allowances but remain inside the UTC [monthly cap]"), and **ADR-0009 already contradicts itself**: line 109 says "Admin shared usage now counts…" while lines 89–96 still describe the superseded exemption. So the runtime is correct and deliberate; three pieces of prose are stale.

Admins are exempt from the **per-user allowance** and **not** exempt from the **platform-wide monthly cap**. That asymmetry is the design, not an oversight: the per-user allowance protects the platform's budget _allocation_, the platform cap protects its _absolute_ spend, and an operator with an unbounded absolute spend is exactly the failure the cap exists to prevent.

**W1-T1 is therefore a documentation-only task.** No behavioural change, no decision needed from you.

---

## File Structure

**Created**

| Path                                            | Responsibility                                                                                 |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `src/resume_tailor_harness/tenancy/spend.py`             | `SpendGate` — the one seam that resolves key selection + budget for a phase and settles usage. |
| `src/resume_tailor_harness/discovery/connectors/http.py` | `BoardSession` — pooled, retrying, timeout-owning HTTP for configured board endpoints.         |
| `scripts/perf_harness.py`                       | Deterministic counters for DB queries, HTTP connections, and prompt tokens per phase.          |
| `tests/tenancy/test_spend_gate.py`              | Gate resolution, phase reuse, invalidation on charge, admin exemption.                         |
| `tests/test_board_session.py`                   | Connection reuse, retry, timeout, per-host politeness.                                         |
| `tests/test_llm_runner_concurrency.py`          | Key-flip race, off-loop budget enforcement, shared-agent safety.                               |

**Modified**

| Path                                               | Change                                                                         |
| -------------------------------------------------- | ------------------------------------------------------------------------------ |
| `src/resume_tailor_harness/tenancy/quotas.py`               | Admin exclusion; `BEGIN DEFERRED` for read-only snapshots.                     |
| `src/resume_tailor_harness/tenancy/limits.py`               | Admin exclusion; delegate to `SpendGate`.                                      |
| `src/resume_tailor_harness/tenancy/costs.py`                | TTL cache for rate lookups.                                                    |
| `src/resume_tailor_harness/tenancy/system_db.py`            | `ix_usage_events_own_key_ts`.                                                  |
| `src/resume_tailor_harness/llm_runner.py`                   | Off-loop gate call; per-runner key resolution; `cache_system_prompt` plumbing. |
| `src/resume_tailor_harness/h1b/service.py`                  | `expect_schema` at both sites; batched cache read/write.                       |
| `src/resume_tailor_harness/h1b/mcp.py`                      | Connect/close asymmetry; bounded result returns instead of raising.            |
| `src/resume_tailor_harness/discovery/connectors/*.py`       | Accept and use the shared `BoardSession`.                                      |
| `src/resume_tailor_harness/discovery/connectors/harvest.py` | Bounded-concurrency detail fetch.                                              |
| `src/resume_tailor_harness/discovery/fit.py`                | Profile into the cacheable system block.                                       |
| `src/resume_tailor_harness/api/runs/sse.py`                 | Notifier-driven; file read off the loop.                                       |

---

## W0 — Measurement first (blocking; nothing else merges without it)

Optimising without a baseline is guessing, and three of the findings below are only worth fixing if the number moves.

### Task W0-T1 — Build the counting harness

- [ ] Add `scripts/perf_harness.py` exposing three context managers:
  - `count_queries(engine)` — SQLAlchemy `before_cursor_execute` event counter, bucketed by statement prefix (`SELECT`/`INSERT`/`BEGIN IMMEDIATE`).
  - `count_connections()` — httpx transport hook counting _new connections_ vs. _requests_, so pooling shows up as a ratio.
  - `count_prompt_tokens()` — accumulates `input_tokens` / `cache_read_tokens` / `cache_write_tokens` off the `record_call` path.
- [ ] Add `tests/perf/test_baselines.py` that runs a 20-job fake-agent discovery and a 10-unit fake-board pull under all three counters and **asserts current numbers as the baseline** (xfail-free, exact).
- [ ] Record the baselines in `docs/notes/perf-baseline-2026-08-04.md`.

**Verification:** the baseline test passes on an unmodified tree. Every later task tightens one of these assertions; a task that cannot tighten one is not a performance task.

---

## W1 — Correctness (bugs)

### Task W1-T1 — Correct the stale admin-exemption prose (F1) — docs only

- [ ] Root `CLAUDE.md`, ADR-0009 §Registration modes bullet: delete the claim that `global_monthly_cost` / `global_weekly_usage` filter out `User.role == "admin"`. Replace with the actual rule: **admins are exempt from the per-user allowance and remain bound by the platform-wide monthly cap**, citing ADR-0010.
- [ ] `docs/adr/0009-registration-modes-platform-budget-governance.md:89-96`: mark that paragraph superseded in place (the ADR's own line 109 already reverses it — make the reversal legible rather than leaving two paragraphs in conflict).
- [ ] **Do not touch `tenancy/quotas.py` or `tenancy/limits.py`.** The two tests named above pin the current behaviour; a "fix" here breaks them, which is the signal that the code was never wrong.

**Verification:** `pytest tests/tenancy/test_cost_quotas.py` green **unchanged**. A reader of `CLAUDE.md` and either ADR now gets one answer instead of three.

### Task W1-T2 — Route H-1B agent output through `expect_schema` (F2)

- [ ] `h1b/service.py::_resolve_company_name` — replace the `getattr`/`model_validate` pair with `expect_schema(result, H1BCompanyResolution, source="h1b-company-resolution")`.
- [ ] `h1b/service.py::_agent_output` — same, with `source="h1b-sponsorship"`. Keep the company-identity check and the `unavailable_reason` backfill after it.
- [ ] The `except Exception` at the fan-out **must stop swallowing `UnparsedAgentOutput` silently**: log it at `error` with the exception's diagnostic message (model, provider, status, tokens, head/tail preview) and keep returning `_unavailable`, so a systematic provider failure is distinguishable in the log from "no filings found".
- [ ] Test: an agent returning a raw `str` produces a log record containing the model id and token counts, and an `unavailable` evidence row — not a bare `ValidationError`.

**Verification:** `pytest tests/ -k h1b` green. Grep proves no bare `getattr(result, "content"` remains outside `llm_runner.py`.

### Task W1-T3 — Remove the shared-agent key-flip race (F10)

- [ ] Resolve the API key **once per `AgentRunner`**, at construction or at first use, not per `run`/`arun` call. `refresh_agent_api_key` stays, but is called from a phase boundary (`SpendGate.open`, W2-T2), never from inside a fan-out.
- [ ] Guard the mutation with a lock so a key change cannot null `async_client` under an in-flight sibling; if a change is detected mid-phase, apply it to the _next_ phase rather than the live model.
- [ ] Test (`tests/test_llm_runner_concurrency.py`): 20 concurrent `arun` calls against one runner while the resolved key flips — no call observes a `None` client, and every call completes.

**Verification:** new test fails on the pre-change tree (make it deterministic by driving the flip from a fake `shared_key_available`).

### Task W1-T4 — Fix the MCP connect/close asymmetry (F11)

- [ ] `h1b/mcp.py::h1b_tools` — only enter the `try`/`finally` after `connect()` succeeds, so a connect failure propagates its own exception.
- [ ] Test: a toolkit whose `connect()` raises surfaces that error, and `close()` is not called.

### Task W1-T5 — Bound the industry revisit scan (F16)

- [ ] Replace the `criteria_json LIKE` full scan in `_industry_scope` with an explicit persisted marker: a nullable `industry_pending` boolean column on `Job`, indexed, set when a candidate cannot be canonicalized and cleared when it can.
- [ ] Keep the `LIKE` branch as a one-shot backfill guarded by a "has any row been marked yet" check, so existing rows migrate on first run without a migration script.
- [ ] Test: the revisit query touches only marked rows; a table of 5,000 unmarked jobs adds zero rows to the pass.

---

## W2 — The spend seam (F3, F4, F5, F14)

**Deepening rationale.** Today the same five facts — the user row, shared-key eligibility, the active rate, the remaining allowance, the platform cap — are derived independently in `resolve_api_key`, in `shared_key_available`, and again in `enforce_agent_budget`, twice per call, from three modules. That is a shallow interface over an expensive implementation: the caller says "give me a key" and pays for a full policy evaluation, then says "may I spend" and pays for it again. Applying the deletion test to `shared_key_available`: deleting it _concentrates_ policy into one gate rather than moving it — the signal we want.

### Task W2-T1 — Index the global aggregates (F5)

- [ ] Add `Index("ix_usage_events_own_key_ts", "own_key", "ts")` to `UsageEvent.__table_args__`.
- [ ] Confirm with `EXPLAIN QUERY PLAN` in a test that both global aggregates use it (assert the plan string does not contain `SCAN usage_events`).

**Verification:** W0 query-counter baseline unchanged; the plan assertion is the win. This is the cheapest item in the plan and can land first.

### Task W2-T2 — Introduce `SpendGate`

- [ ] Create `tenancy/spend.py` with:
  - `@dataclass(frozen=True) SpendDecision(api_key, own_key, provider, model, reason)`.
  - `SpendGate.open(model_id) -> SpendDecision` — resolves eligibility, rate presence, per-user allowance, and platform cap **once**, raising the existing `BudgetExceededError` / `CostRateUnavailableError` / `GlobalCostQuotaExceededError` so no caller's `except` clause changes.
  - `SpendGate.settle(usage)` — the existing `record_call` write path, plus invalidating the gate's cached decision when a charge crosses a threshold.
- [ ] The gate holds its decision for the life of a phase with a short TTL (default 30 s, `Settings.spend_gate_ttl_seconds`) so a long fan-out re-checks periodically without re-checking per call. **Admin and BYOK callers short-circuit before any query**, as they do today.
- [ ] `quota_snapshot`'s read-only path uses `BEGIN DEFERRED`; `BEGIN IMMEDIATE` stays only on `charge_shared_cost`'s mutating branch. A read must not take an exclusive lock.
- [ ] Add a TTL cache (60 s) around `has_active_rate` / `find_rate` keyed by `(provider, model)` (F14), invalidated by the admin rate-editing endpoints.

**Verification:** `tests/tenancy/test_spend_gate.py` covers: decision reuse within TTL, re-evaluation after it, invalidation on charge, admin short-circuit, BYOK short-circuit, and that each error type still surfaces unchanged. W0's query counter for a 20-job discovery must drop by **≥ 80 %** — target ≤ 2 queries per call amortised, from ~11.

### Task W2-T3 — Take the gate off the event loop (F4)

- [ ] `AgentRunner.arun` calls the gate via `await asyncio.to_thread(...)` (or an async gate method that does), so SQLite I/O and any `BEGIN IMMEDIATE` lock wait never block the loop that the fan-out shares.
- [ ] `record_call` likewise moves off-loop on the async path.
- [ ] Hoist the seven function-local imports out of `AgentRunner.run`/`arun`/`stream` hot loops into module scope where they do not reintroduce a cycle; where they do, resolve them once at class level.
- [ ] Test: with a gate that sleeps 100 ms, 10 concurrent `arun` calls complete in ~100 ms wall clock, not ~1 s.

**Verification:** the timing test is the proof. It fails on the pre-change tree.

### Task W2-T4 — Make phase-level checking the documented contract

- [ ] Update `CONTEXT.md`'s **Budget** entry and the root `CLAUDE.md` tenancy section so the doc and the runtime agree on _when_ budget is checked. (`CONTEXT.md` already says "when a phase starts, not per call" — this task makes that true rather than aspirational.)

---

## W3 — The HTTP transport seam (F6, F7)

**Deepening rationale.** Two adapters for "talk HTTP carefully" already exist — `workday.py::_request_with_retry` (throttle handling) and `security/outbound.py` (pinned, bounded, redirect-revalidating). One is a hypothetical seam; two is a real one. Every other connector has neither, plus a copy-pasted `timeout=30`.

### Task W3-T1 — Create `BoardSession`

- [ ] `discovery/connectors/http.py`: one `httpx.Client(http2=True, limits=Limits(max_keepalive_connections=…, max_connections=…), timeout=…)` wrapper exposing `get(url, **kw)` / `post(url, **kw)`.
- [ ] Absorb `workday.py::_request_with_retry` verbatim as the default policy: `Retry-After` honoured, else exponential backoff capped, on `{429, 500, 502, 503, 504}`. Workday's module keeps its constants but delegates.
- [ ] Own the timeout constant. `timeout=30` disappears from every connector module.
- [ ] A `BoardSession` is created per pull run and threaded through `Connector.fetch`; connectors that receive `None` create a private one so single-connector CLI paths and tests still work.

**Verification:** `tests/test_board_session.py` asserts (a) 10 requests to one host open **1** connection, (b) a 429 with `Retry-After: 0` retries and succeeds, (c) a non-transient 404 does not retry.

### Task W3-T2 — Adopt it across the connectors

- [ ] Convert greenhouse, lever, ashby, smartrecruiters, workable, recruitee, personio, breezy, jazzhr, bamboohr, workday, google, remoteok, adzuna, and `url_ingest/ats_readers.py` from module-level `httpx.get` to the injected session.
- [ ] `detect.py`, `url_ingest/fetch.py`, and `profile/intake.py` already accept a `client` parameter — pass the session's underlying client rather than letting them build their own. `security/outbound.fetch_public_text` likewise (F6/C4) — it already accepts `client`; the callers just never supply one.
- [ ] **Do not** route user-supplied URLs through `BoardSession`: the egress gateway's pinning, redirect revalidation, and byte caps remain mandatory for those. `BoardSession` supplies the _pool_, `fetch_public_text` keeps the _policy_.

**Verification:** W0's connection counter for a 10-unit fake-board pull drops from ~1 connection per request to ~1 per host. Existing connector tests stay green unchanged (fixture payloads, not live endpoints).

### Task W3-T3 — Concurrent detail fetches (F7)

- [ ] `harvest_detailed` gains bounded concurrency over the _detail_ fetches only (the title gate and the final relevance gate stay where they are, and results stay in row order).
- [ ] Bound by a new `Settings.detail_fetch_concurrency` (default 4, validated `>= 1`), **per host**, so politeness is preserved and the existing 429 retry is not turned into a thundering herd.
- [ ] The `limit` early-break must survive: fetch in ordered chunks and stop once `limit` survivors are collected, rather than fetching every candidate up front.

**Verification:** a fake detail endpoint with a 50 ms delay and 20 survivors completes in ~250 ms at concurrency 4 instead of ~1 s; a `limit=5` run issues ≤ 8 detail fetches, not 20.

---

## W4 — Token economics (F8, F9)

This is where the money is. Both items are prompt-cache structure, not model changes.

### Task W4-T1 — Enable prompt caching on the N-per-run agents (F8)

- [ ] `discovery/fit.py`, `discovery/extract.py`, `discovery/relevance.py`, `discovery/industry.py`, `tracking/canonicalize.py`, `taxonomy/groups.py`, `discovery/url_ingest/llm.py`, `discovery/scraper/learn.py`, and the `profile/*` builders: pass `cache_system_prompt=provider_capabilities(model_id).supports_prompt_cache` to `build_model`, matching what tailor/coach/interview already do.
- [ ] Gate on `Settings.prompt_cache_enabled` the same way `tailor/agents.py::_prompt_cache` does, so there is one switch.

**Verification:** W0's token counter shows `cache_read_tokens > 0` from the second job onward in a 20-job discovery, and `input_tokens` per job falls by the size of the instruction block.

### Task W4-T2 — Move the stable profile into the cacheable prefix (F9)

- [ ] `build_fit_agent` gains the profile: the `CANDIDATE PROFILE (JSON)` section moves from `compose_fit_input`'s user message into the agent's system/description block, which is built **once per run** and is the block `cache_system_prompt` actually caches.
- [ ] `compose_fit_input` keeps only the per-job volatile sections (skill context, H-1B evidence, location, JD) — which is already the correct stable-before-volatile ordering, just in the wrong message.
- [ ] The same treatment applies to any other N-per-run agent whose input embeds a run-constant document; audit `extract`, `relevance`, and the profile builders for the pattern before assuming fit is the only one.
- [ ] **Fact-lock is untouched.** The profile handed to the fit agent is unchanged in content; only its message position moves. `renderable_profile()`'s filtering for the tailor/reviser path is a different seam and is not in scope.

**Verification:** token counter — a 20-job run pays the profile's tokens **once** as a cache write plus 19 cache reads at 0.1×, instead of 20 full-price copies. Record the measured before/after in the perf note. Existing fit tests must pass unchanged; if any assert on prompt _text_ rather than behaviour, that is the test to fix, not the change.

---

## W5 — Agent-harness best practices (F12, F13, F15)

### Task W5-T1 — Tool results are always results, never aborts (F15)

- [ ] `h1b/mcp.py::bounded_h1b_result` stops raising `H1BResultTooLarge`. It returns a **truncated payload plus an explicit marker** (`{"truncated": true, "reason": "...", "data": <clipped>}`) so the model receives an observation it can act on — the loop's contract is that every tool call gets a result, including a denial.
- [ ] Keep `H1BResultTooLarge` exported for callers that assert on it; it becomes the type of the _recorded_ reason, not a control-flow exception.
- [ ] Test: a 10× oversized result yields a truncated observation and the run still produces validated evidence; the truncation is visible in the tool-completed stream event.

### Task W5-T2 — One run-event transport (F12)

- [ ] `api/runs/sse.py::run_events` subscribes to `StreamNotifier` the way `stream_sse.py` already does, keeping the existing poll interval purely as a dropped-notification fallback (the pattern `RunStreamSink` readers already use).
- [ ] The snapshot read moves off the event loop (`asyncio.to_thread`), so a slow volume cannot stall the API loop for every connected client.
- [ ] Test: a run that completes in 50 ms delivers its terminal event in ~50 ms, not ~500 ms; a notifier that never fires still terminates via the fallback.

### Task W5-T3 — Batch the H-1B enrichment cache I/O (F13)

- [ ] `enrich_companies` reads all cached rows in **one** query (reuse `h1b/cache.py::load_company_evidence`, which exists precisely for this) and writes with one batched upsert pass instead of a per-company `SELECT` inside the write loop.
- [ ] Test: enriching 12 companies issues 2 queries, not 24.

### Task W5-T4 — Give agent runs a trace (documentation + smallest useful implementation)

- [ ] `UsageEvent` is a billing record, not a trace: there is no queryable per-run record of tool calls, retries, cache-hit rate, or which agent family produced which artifact. Add a minimal append-only `agent_runs` NDJSON trace under the run's own directory (reusing `RunStreamSink`'s durability pattern, not a new substrate) recording: run id, agent family, `SkillRef`, model, retries, tool-call count, token/cache split, and terminal status.
- [ ] Keep it operational-events only — **no hidden reasoning content** — matching the existing rule in `_map_stream_event` that the visible answer is never reasoning.
- [ ] This is deliberately the smallest version: one file per run, no schema, no API surface. Expand only if it earns it.

---

## Sequencing

```
W0-T1  ──────────────────────────────────────────────►  (blocks everything)
   │
   ├─ W2-T1 (index)          ─┐  cheap, independent, land first
   ├─ W1-T4, W1-T2, W1-T5    ─┤  correctness, independent
   ├─ W4-T1                  ─┘  one-line-per-file, immediate token win
   │
   ├─ W2-T2 ──► W2-T3 ──► W1-T3 ──► W2-T4     (spend seam, ordered)
   ├─ W3-T1 ──► W3-T2 ──► W3-T3               (HTTP seam, ordered)
   ├─ W4-T2                                    (after W4-T1)
   └─ W5-T1, W5-T2, W5-T3, W5-T4               (independent)
```

W1-T1 is docs-only and can land any time, independent of W0.

---

## Explicitly out of scope

- **Adzuna's visible-browser enrichment.** Documented, deliberate, and browser-bound; concurrency there fights the anti-bot behaviour the current design exists to survive.
- **Any change to fact-lock, provenance, the review roster, or `score_threshold`.** `CLAUDE.md` records those as unmeasured pending the eval arms in `evals/RESULTS.md`; changing them without running the evals would be exactly the guessing this plan is trying to remove.
- **Replacing agno, or introducing a second agent framework.** Every finding here is inside the existing `build_model` / `AgentRunner` seam.
- **Envelope-encrypting user provider keys, OAuth state browser-binding, CSRF tokens, sandboxing Typst/transcription.** Real and recorded in `resume-tailor-harness-threat-model.md`; they are a security workstream, not this one.
- **A multi-agent redesign.** The single-agent loop has not failed a measured eval, so there is nothing to justify one.

---

## Definition of done

- [ ] `.venv/Scripts/python.exe -m pytest` green.
- [ ] `ruff check` clean.
- [ ] `docs/notes/perf-baseline-2026-08-04.md` records before/after for: DB queries per LLM call, HTTP connections per board pull, input vs. cache-read tokens per discovery run, and detail-fetch wall clock.
- [ ] Every performance task moved a number in that file, or was reverted.
- [ ] `CLAUDE.md` and `CONTEXT.md` updated wherever this plan changed a documented behaviour (W1-T1, W2-T4, W3-T1, W4-T2).
