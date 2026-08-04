# Perf baseline — 2026-08-04

Measured by `scripts/perf_harness.py`, asserted by `tests/perf/test_baselines.py`.
Every number is exact and offline: no clock sampling, no network. A change that
cannot move one of these rows is not a performance change.

```bash
.venv/Scripts/python.exe -m pytest tests/perf/ -q
```

## Summary

| Unit                                                | Before | After | Delta         | Task  |
| --------------------------------------------------- | ------ | ----- | ------------- | ----- |
| DB statements per LLM call — **policy derivation**  | 13.0   | 0.4   | **−97 %**     | W2    |
| DB statements per LLM call — **end to end**         | 22.2   | 9.7   | **−56 %**     | W2    |
| Exclusive (`BEGIN IMMEDIATE`) on a budget *read*    | 1      | 0     | **removed**   | W2-T2 |
| HTTP requests per client, one host                  | 1.0    | 12.0  | **12× reuse** | W3    |
| Per-job prompt tokens, 20-job fit run               | 65,420 | 280   | **−99.6 %**   | W4-T2 |
| Detail fetches, 20 survivors at 50 ms               | 1.000s | 0.267s | **3.7×**     | W3-T3 |
| Queries to enrich 12 H-1B companies                 | 24     | 2      | **−92 %**     | W5-T3 |

## 1. Spend metering

`test_spend_policy_is_derived_once_per_phase_not_per_call` and
`test_spend_path_statements_per_llm_call`.

**Before** — 222 statements for 10 calls (22.2 each):

```
BEGIN IMMEDIATE=10, INSERT=42, SELECT=159, UPDATE=11
```

The plan estimated ~11 sessions per call from reading the code; the counter said
**22.2 statements**. The same five facts were derived three times per call —
`resolve_api_key` → `shared_key_available`, `enforce_agent_budget`, and
`record_call` → `charge_shared_cost` — and each derivation opened its own
`Session`, which costs more than one statement.

**After** — 97 statements for 10 calls (9.7 each):

```
BEGIN IMMEDIATE=10, INSERT=42, SELECT=34, UPDATE=11
```

**The split matters more than the total, and the test asserts them separately.**

- *Policy derivation* — what `SpendGate` owns — went from ~13.0 statements per
  call to **0.4** (4 statements for 10 calls: one derivation, then cache hits),
  and now takes **zero** exclusive write locks on a read.
- *Settlement* — the `UsageEvent`, its line items, and the quota charge — is the
  remaining 9.7 and is **not cacheable**. It is a durable billing write; making
  it cheaper means making it less durable, which is out of this plan's scope.

Collapsing the two into one number would let a settlement regression hide behind
the gate's win, so `MAX_GATE_STATEMENTS_PER_CALL` and `MAX_STATEMENTS_PER_CALL`
are separate ceilings.

Three smaller wins are inside the "after" figure: `quota_snapshot` and
`charge_shared_cost`'s preflight no longer take SQLite's write lock to read an
allowance; `has_active_rate`/`find_rate` cache near-static rate data per engine;
and `charge_shared_cost` keeps its instances alive across `commit()` while
`record_call` reads `event.id` before committing — both were paying refresh
`SELECT`s nobody asked for.

## 2. HTTP transport

`test_board_requests_share_one_connection_per_host`, 12 requests to one host.

**Before** — 1.0 requests per client. Every ATS connector called module-level
`httpx.get(...)`, so httpx built a fresh `Client` — and therefore a fresh pool,
TCP connection, and TLS handshake — per request.

**After** — **12.0 requests per client, 1 host.** One `BoardSession` per pull
run, HTTP/2 on, keep-alive pool shared. A board pull is list-then-detail against
a single host, which is the shape that benefits most.

## 3. Token economics

`test_fit_prompt_sends_the_run_constant_profile_once_per_run` and
`test_discovery_input_tokens_scale_with_the_job_not_the_profile`, 20 jobs,
profile ≈ 3,250 tokens.

**Before** — **65,420 prompt tokens**, with the full profile JSON present in
**20 of 20** composed prompts. `compose_fit_input` put the entire `ProfileFacts`
JSON first in every per-job user message — the one message kind agno cannot
cache — so ~65,000 of those tokens were 20 identical copies of a run-constant
document.

**After** — **280 prompt tokens across the 20 per-job messages, and 0 of 20
carry the profile.** The profile is one ~3,250-token system block, built once
per run, in the block `cache_system_prompt` actually caches. On a caching
provider that is one cache write plus 19 reads at 0.1×, instead of 20 copies at
full price.

The fake agent derives `input_tokens` from prompt length, so this measures
prompt *structure*, not a provider's tokenizer. That is the point: the
structural claim is what the change makes, and it is checkable offline.

W4-T1 is not in this table because it has no offline number — enabling
`cache_system_prompt` on the nine other N-per-run agent families (fit, extract,
relevance, industry, canonicalize, groups, url-ingest, scraper-learn, and the
profile builders) only changes cost against a real provider. It is recorded
here so its absence is not read as a skipped task.

## 4. Detail fetches

20 survivors against a 50 ms detail endpoint:

- serial: **1.000 s**
- bounded concurrency 4: **0.267 s** (3.7×)

The `limit` early-break survives exactly: a `limit=5` run issues **5** detail
fetches, not 20, because the chunk is sized to `min(concurrency, limit − kept)`
rather than to a fixed width.

## 5. H-1B enrichment cache I/O

`test_enrichment_reads_and_writes_the_cache_in_batches`. Enriching 12 companies
issued one `SELECT` per company on read and one more per company inside the
write loop — **24 queries**. It now uses the batched seam the display path
already had plus one batched load before the writes: **2 queries**.

## What did not move, and why

- `ix_usage_events_own_key_ts` (W2-T1) does not change the statement *count*; it
  changes the query plan. `tests/tenancy/test_usage_indexes.py` asserts neither
  global aggregate contains `SCAN usage_events`.
- `fetch_public_text` did **not** get the connection pool, though it accepts a
  client. The gateway pins each request to the IP it validated and carries the
  hostname in an `sni_hostname` extension, but httpx keys its pool on the
  request origin — the IP. A shared pool could hand a connection negotiated with
  one hostname's SNI to a request for a different hostname on the same address.
  Pooling there needs a pool keyed by SNI. Recorded so a later reader does not
  "finish the job" and reintroduce it.
