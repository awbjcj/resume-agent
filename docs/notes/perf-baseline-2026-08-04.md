# Perf baseline — 2026-08-04

Measured by `scripts/perf_harness.py`, asserted by `tests/perf/test_baselines.py`.
Every number is exact and offline: no clock sampling, no network. A change that
cannot move one of these rows is not a performance change.

Run them with:

```bash
.venv/Scripts/python.exe -m pytest tests/perf/test_baselines.py -q
```

> **Status:** `TBD` marks a number not yet produced by the suite. Do not cite a
> `TBD` row. Each is filled in from a test run as its workstream lands.

## Summary

| Unit                                   | Before  | After | Delta | Task  |
| -------------------------------------- | ------- | ----- | ----- | ----- |
| DB statements per LLM call             | 22.2    | TBD   | TBD   | W2    |
| Exclusive (`BEGIN IMMEDIATE`) per call | 1.0     | TBD   | TBD   | W2-T2 |
| HTTP requests per client (one host)    | 1.0     | TBD   | TBD   | W3    |
| Input tokens, 20-job fit run           | 65,420  | TBD   | TBD   | W4-T2 |
| Detail fetches, 20 survivors           | serial  | TBD   | TBD   | W3-T3 |

## 1. Spend metering — DB statements per LLM call

`tests/perf/test_baselines.py::test_spend_path_statements_per_llm_call`,
10 calls through `AgentRunner.run` under a tenancy context with a platform key.

**Before** — 222 statements for 10 calls (22.2 each):

```
BEGIN IMMEDIATE=10, INSERT=42, SELECT=159, UPDATE=11
```

The plan estimated ~11 sessions per call from reading the code; the counter says
**22.2 statements**. The gap is that the same five facts are derived three times
per call — once in `resolve_api_key` → `shared_key_available`, once in
`enforce_agent_budget`, and once again in `record_call` → `charge_shared_cost` —
and each derivation opens its own `Session`, which costs more than one statement.

**After** — TBD.

## 2. HTTP transport — connections per board pull

`tests/perf/test_baselines.py::test_board_requests_share_one_connection_per_host`,
12 requests to one host.

**Before** — every ATS connector calls module-level `httpx.get(...)`, so httpx
builds a fresh `Client` (and therefore a fresh pool, TCP connection, and TLS
handshake) per request: **1.0 requests per client**.

**After** — TBD.

## 3. Token economics — input tokens per discovery run

`tests/perf/test_baselines.py::test_discovery_input_tokens_scale_with_the_job_not_the_profile`,
20 jobs, profile ≈ 3,250 tokens.

**Before** — **65,420 input tokens** for the run, and the full profile JSON
appears in **20 of 20** composed prompts. `compose_fit_input` puts the entire
`ProfileFacts` JSON first in every per-job user message, so ~65,000 of those
65,420 tokens are 20 identical copies of a run-constant document sitting in the
one message kind agno cannot cache.

**After** — TBD.

Note the fake agent derives `input_tokens` from prompt length, so this row
measures prompt *structure*, not a provider's tokenizer. That is the point: the
structural claim is what the change makes, and it is checkable offline.

## 4. Detail fetches — `harvest_detailed`

**Before** — strictly serial over every surviving row, though the fetches are
independent.

**After** — TBD.

## What is expected not to move

- `ix_usage_events_own_key_ts` (W2-T1) does not change the statement *count*; it
  changes the query plan. Its test asserts neither global aggregate contains
  `SCAN usage_events`. Recorded here so the absence of a delta in the table
  above is not read as a failed task.
