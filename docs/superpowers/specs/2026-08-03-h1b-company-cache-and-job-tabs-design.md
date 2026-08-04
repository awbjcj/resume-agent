# H-1B company cache, quarterly evidence, and job-detail tab refinement

**Date:** 2026-08-03
**Status:** Approved design, not yet implemented
**Supersedes nothing.** Extends `2026-08-02-career-skills-h1b-agent-wiring-design.md`.

---

## Problem

Three defects and one gap, all in the historical H-1B surface.

**1. Every job re-checks a company that is already cached.** A company-level cache
already exists — `h1b_company_evidence` (`tracking/tables.py:168`), keyed by
`normalized_company` with a TTL of `Settings.h1b_cache_ttl_days` (default 30) —
and `enrich_companies` already de-dupes companies and serves cache hits. The
defect is on the **read** path: `_job_detail_response`
(`api/routers/jobs.py:99`) and `_h1b_sponsorship_status`
(`tracking/queries.py:152`) both read `JobAnalysisMeta.h1b_evidence_snapshot`,
a per-job frozen copy stashed in `analysis_meta_json`. A job whose company was
researched via a _different_ job has no snapshot of its own, so its card reads
"No H-1B evidence has been checked for this job yet" while a fresh answer sits
in the cache one query away.

**2. Most jobs never get a snapshot at all.** `run_h1b_enrichment`
(`services/discovery.py:103`) enriches only jobs at status `filtered` whose
`criteria_json.sponsorship_signal == "silent"`. Every other job is snapshot-less
by construction, so most cards start empty even after a full discovery run.

**3. Evidence has no quarterly resolution.** `H1BSponsorshipEvidence` carries
`fiscal_periods: list[str]` — labels only — alongside a single flat set of
`filing_count` / `certified_count` / `wage_summary`. It records _which_ periods
were examined but collapses their numbers into one total. There is nowhere for
per-quarter figures to live, so "are they still filing?" is unanswerable.

**4. The job-detail tab set has grown incoherent.** `Management` mixes pipeline
stage, job deletion, and H-1B research; `Application` holds application status
and notes. Two tabs that both mean "where does this job stand" are separated,
while an unrelated research panel is buried inside one of them.

### Terminology note

`JobStatus.filtered` does **not** mean "filtered out". It is the stage between
extract and score: `run_filter` advances survivors to `filtered` and sends
rejects to `rejected`; `run_score` then reads `filtered` jobs and advances them
to `shortlisted`. So `run_h1b_enrichment` already runs over every _surviving_
job — the narrowing that matters is `sponsorship_signal == "silent"`, not the
status.

---

## Decisions

| #   | Decision                                                                                                               | Rationale                                                                                                                                   |
| --- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | The company cache is the **only** display source.                                                                      | One company = one row = one truth. A refresh on any job instantly updates every card at that company.                                       |
| D2  | One cache row per company holds a **per-period breakdown plus a rolling 4-quarter total**.                             | One research call per company; the selector switches views over already-fetched data.                                                       |
| D3  | Discovery **widens** to every surviving job's company, still one call per company.                                     | Cards get answers without the user clicking; the cache and TTL keep marginal cost to one call per genuinely new company.                    |
| D4  | Expired rows **still render**, labelled stale. Nothing auto-refreshes.                                                 | Historical filings do not rot. Hiding usable data is worse than dating it; auto-refresh on view would spend LLM budget without being asked. |
| D5  | The merged tab is **"Tracking"** — stage, then application, then a fenced danger zone. Sponsorship becomes a peer tab. | Reads in causal order; tab count stays at 6, so the tab bar does not wrap.                                                                  |

---

## Data model

### `H1BPeriodStat` (new, `h1b/models.py`)

```python
class H1BPeriodStat(BaseModel):
    period: str = Field(min_length=1, max_length=32)   # provider label, e.g. "FY2026-Q1"
    filing_count: int | None = Field(default=None, ge=0)
    certified_count: int | None = Field(default=None, ge=0)
    denied_count: int | None = Field(default=None, ge=0)
    wage_summary: dict[str, float] | None = None
```

A `model_validator` rejects the period when `certified_count + denied_count >
filing_count` and all three parts are present, mirroring the existing
`certified_count <= filing_count` rule on the parent.

### `H1BSponsorshipEvidence` (extended)

Gains two fields:

```python
periods: list[H1BPeriodStat] = Field(default_factory=list, max_length=4)
denied_count: int | None = Field(default=None, ge=0)
```

`denied_count` is added to the parent so the rollup has exactly one computation
site (the server) rather than a second one in the browser. It stays `None` for
`schema_version = 1` rows, which is why the flat fallback view has no denied
tile.

`periods` is validated as follows:

- **Bounded.** At most 4 entries. The product presents a rolling four-quarter
  total, so accepting five through eight entries would make the UI's label
  false. Agent output is untrusted; this is the same
  posture as `_project_domains` capping clustered domains rather than trusting
  the model.
- **Unique.** Duplicate `period` labels reject the whole evidence object.
- **Ordered newest-first by the agent.** Period labels are opaque provider
  strings, so the application cannot reliably re-sort them; ordering is the
  agent's responsibility and is **not** validated. Disorder is cosmetic only —
  it changes the selector's option order and nothing else, because the rollup is
  order-independent and each period's figures are self-contained.
- **The count rollup is derived, never trusted.** When `periods` is non-empty,
  a `model_validator` **overwrites** top-level `filing_count`,
  `certified_count`, and `denied_count` with the sum across periods, treating a
  period's `None` as a zero contribution but yielding `None` for a metric no
  period reports. The invariant "the count total equals the parts" is therefore
  unbreakable rather than something the model might get wrong. A top-level
  `wage_summary` remains the provider's report-level aggregate: medians and
  percentiles cannot be summed across quarters without underlying distributions.
  For legacy flat rows, if all three top-level counts are present,
  `certified_count + denied_count <= filing_count` is also required.

**"Past 4 quarters" means the 4 most recent quarters the provider has, latest
included** — not the latest _plus_ four more.

`fiscal_periods: list[str]` is retained unchanged for backward compatibility. It
remains the labels-only record; `periods` is the numeric one. When `periods` is
non-empty, all display labels come from it; `fiscal_periods` is used only by the
legacy flat fallback so stale labels cannot contradict the selected figures.

### Schema evolution

Additive, **no migration**. `periods` defaults to `[]`, so every existing
`evidence_json` payload still validates. Cache rows written after this change
set `H1BCompanyEvidence.schema_version = 2`; a `schema_version = 1` row renders
exactly as it does today — no selector, flat counts. This is the same posture as
D4: old data stays readable and is refreshed only when the user asks.

`H1BCompanyEvidence` needs **no structural change**; `evidence_json` carries
`periods`.

---

## Read path

### One batched seam

New module `h1b/cache.py`:

```python
def load_company_evidence(
    session: Session, companies: Sequence[str | None]
) -> dict[str, H1BSponsorshipEvidence]:
    """Load cached evidence for the given company labels, keyed by normalized name."""
```

- Normalizes each input with `normalize_company()`, drops blanks, de-dupes.
- Issues **one** `SELECT ... WHERE normalized_company IN (...)`.
- Validates each `evidence_json`; a row that fails validation is **skipped, not
  raised**, preserving the fail-closed behaviour of today's
  `_h1b_sponsorship_status`.
- Returns fresh **and** expired rows alike. Expiry is a display concern (D4),
  not a filter.

### Consumers

| Site                                                          | Change                                                                                                                                                                                                               |
| ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `api/routers/jobs.py::_job_detail_response`                   | Replace the `analysis_meta_json` read with `load_company_evidence(session, [job.company])`.                                                                                                                          |
| `services/board.py::list_board` and the three page projectors | Load one map for the materialized page and thread it to shortlist, pipeline, and triage row builders. `project_shortlist_jobs` must receive the session too; it is the production path for paginated shortlist rows. |

The map is derived **once per request** and threaded in, exactly as
`derive_filter_values` is already threaded into `board_page` and
`board_facet_counts`. Doing the lookup inside the row projection would issue one
query per row and reintroduce the N+1 the board page was explicitly built to
avoid. `job_detail_row` does not need a status-map lookup: the router performs
the one full-evidence lookup used by the detail response, avoiding a redundant
cache query whose status-only result is discarded by `JobDetail`.

### Retiring the per-job snapshot

- `JobAnalysisMeta.h1b_evidence_snapshot` **stops being written** and **stops
  being read**. The field stays on the model so existing rows still deserialize;
  existing values go inert. This matches the established posture that dangling
  references are inert rather than errors.
- `JobAnalysisMeta.h1b_evidence_id` **keeps being written** for every in-scope,
  normalizable job whose company has available cache evidence (including a fresh
  cache hit). It remains a cheap provenance pointer answering "which cache row
  answered this job"; it is never a display fallback.

### Staleness

`H1BSponsorshipOut` gains `stale: bool`, computed server-side as
`evidence.expires_at <= now`. The server already owns "now" for every other TTL
decision; deriving it in the browser would put a second clock in play for no
gain. `stale` is `false` when there is no evidence.

### API projection

`H1BSponsorshipEvidenceOut` (`api/schemas/jobs.py:169`) gains `periods:
list[H1BPeriodStatOut]` and `denied_count`, and `from_evidence` projects them.
`H1BPeriodStatOut` is a new `CamelModel` mirroring `H1BPeriodStat`, so the wire
format is `{period, filingCount, certifiedCount, deniedCount, wageSummary}`.
Without this the browser cannot see the breakdown at all.

---

## Discovery

### Widening

`run_h1b_enrichment` gates on two conditions today:
`config.sponsorship_required` **and** `criteria.sponsorship_signal == "silent"`.
**Only the second is dropped.**

- `config.sponsorship_required` **stays**. If the user does not need
  sponsorship, researching every company is pure spend.
- The `silent` narrowing **goes**, so every surviving job's company enters the
  cache and every card gets an answer.

### The widening stops at the cache

Evidence threaded into `compose_fit_input` (`discovery/pipeline.py:320`) stays
restricted to `silent` jobs. A job whose JD explicitly states no sponsorship is
available must not have its fit score lifted by the employer's filing history —
the JD is authoritative for _this_ role, the filings are historical.

**`run_h1b_enrichment`'s signature and return type do not change.** It keeps
returning `dict[int, H1BSponsorshipEvidence]` containing **only** `silent` jobs.
Cards read the cache through `load_company_evidence`, not through this return
value, so a second `by_company` map would be dead weight — the widened research
reaches the cards purely as a side effect of populating
`h1b_company_evidence`.

What changes inside the function:

- **Research set widens** to every in-scope `filtered` job with a normalizable
  company (still gated on `config.sponsorship_required`).
- **Returned map stays narrow** — built only for jobs whose
  `sponsorship_signal == "silent"`.

The provenance update is deliberately broader than the returned scoring map:
after fresh cache hits and newly researched rows are merged, every research job
with available evidence receives `h1b_evidence_id`, but only silent jobs enter
the return value. This preserves a useful pointer without allowing an
explicit-no job to influence fit scoring.

`discovery/pipeline.py:482` and `run_score` therefore need **no change at all**.
Existing scoring behaviour is byte-identical; only card coverage grows. A test
pins this (see Testing).

A company dropped by the per-run cap simply yields no scoring evidence that run,
exactly as an unreachable provider already does — `run_score` reads
`(sponsorship_evidence or {}).get(job.id, None)` and tolerates a miss.

### Per-run spend cap

A fresh workspace with 300 jobs can hold roughly 180 distinct companies — 180
mid-tier tool-calling agent runs on the first pull.

New setting: `Settings.h1b_enrich_max_companies_per_run: int = 50`, with
`0 = unlimited` per the repo's limits convention.

- Bounds **uncached** companies researched per run. A fresh cache hit means
  `expires_at > now` and never counts against it. A row that exists but has
  expired counts as uncached, since refreshing it costs a call. The read seam
  intentionally returns expired rows for display, but those rows are
  display-only until refreshed: they must not enter the scorer merely because
  the cap deferred their refresh.
- Selection is deterministic and highest-leverage-first: **descending count of
  eligible jobs at that company within this enrichment pass, ties broken by
  ascending normalized company name.**
- The remainder is picked up on the next run — no error, no partial-failure
  record. A never-cached company reads "Not checked" until then; an existing
  expired row remains visibly stale but does not enter scoring. The user can
  still force any one of them with a manual check.

When every company is already fresh, enrichment is skipped but the fresh-cache
map still reaches the silent-job scorer. The no-work branch must therefore build
the return map rather than returning `{}` early.

---

## Provider assumption and degradation

`H1B_MCP_COMMAND` is empty in `.env`, so the real signatures of
`get_company_stats`, `search_h1b_jobs`, and `get_available_data` could not be
introspected while designing this. **The design assumes a quarterly breakdown is
obtainable and is built so that being wrong costs nothing.**

The sponsorship agent's instructions gain: when `get_available_data` is exposed,
use it to identify the 4 most recent quarters and populate `periods` for each.

| Provider reality                   | Result                                                                                                              |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Quarterly slice available          | `periods` has up to 4 entries; selector renders.                                                                    |
| No quarterly slice                 | `periods: []`. Evidence is still **valid**; the UI renders today's flat view. **Not an error, not a failed check.** |
| Partial coverage (2 of 4 quarters) | 2 entries stored; UI labels the rollup "Last 2 quarters".                                                           |

The prompt's existing constraints are unchanged: the `caveat` field must match
`HISTORICAL_ONLY_CAVEAT` exactly, the company name remains untrusted data, and
no current-sponsorship claim may be made.

---

## UI

### Tab set

From `jd | versions | coverLetters | application | interview | manage`
to `jd | versions | coverLetters | tracking | interview | sponsorship`.

Same count, so the tab bar does not wrap. `Application` and `Management`
triggers are removed.

### `TrackingTab` (new, `web/src/features/job/TrackingTab.tsx`)

```
┌──────────────────────────────────────────────────────────────┐
│  PIPELINE STAGE                                              │
│  ┌─────────────────────────────────┐                         │
│  │ shortlisted                  ▾  │  [ Set stage ]          │
│  └─────────────────────────────────┘                         │
│  Moving this forward overrides its discovery filter…         │
│  ──────────────────────────────────────────────────────────  │
│  APPLICATION                                                 │
│  ┌─────────────────────────────────┐                         │
│  │ submitted                    ▾  │                         │
│  └─────────────────────────────────┘                         │
│  Notes  [ applied via referral                        ]      │
│                                          [ Save ]            │
│  ──────────────────────────────────────────────────────────  │
│  ⚠ Danger zone                          [ Delete job ]       │
│    Has progress — delete disabled.                           │
└──────────────────────────────────────────────────────────────┘
```

`ApplicationEditor` and `StageManager` are **kept as separate components** and
composed by a thin `TrackingTab`. The merge requested is a _tab_ merge, not a
component merge; fusing two mutation hooks and two lifecycles into one file
would buy nothing.

`Delete` moves out of `StageManager` into the danger zone, so a destructive
action is no longer adjacent to the routine `Set stage` button. The
`job.hasProgress` guard and its explanatory copy move with it.

### Sponsorship tab

`H1BSponsorshipPanel` moves out of `Management` into its own tab and gains a
period selector.

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 🛡  Historical H-1B sponsorship                        [ Refresh check ]    │
│    Stripe, Inc.                                                            │
│    ⓘ Refreshing updates every job at this company.                         │
│                                                                            │
│ ┌────────────────────────────────────────────────────────────────────────┐ │
│ │ ✓ Historical filings found                            [ matched ]      │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
│  Period  ┌──────────────────────────────────┐   Checked 3 days ago         │
│          │ Last 4 quarters (total)       ▾  │                              │
│          └──────────────────────────────────┘                              │
│            · Last 4 quarters (total)                                       │
│            · FY2026 Q1     · FY2025 Q4                                     │
│            · FY2025 Q3     · FY2025 Q2                                     │
│                                                                            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│  │ TOTAL FILINGS│ │ CERTIFIED    │ │ DENIED       │ │ CONFIDENCE   │       │
│  │ 412          │ │ 398          │ │ 14           │ │ 92%          │       │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘       │
│                                                                            │
│  WAGE SUMMARY  (median $184,000 · p25 $161,000 · p75 $212,000)             │
│  Open source record ↗          Data version: FY2026Q1-2026-04-14           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Historical H-1B filings do not confirm current sponsorship for this  │  │
│  │ role or current employer policy.                                     │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

Behaviour:

- **Default selection** is `Last N quarters (total)`, where `N = periods.length`.
- **Changing the period swaps only the metric tiles and wage summary — not the
  status banner.** Status is a property of the company research, not of a
  quarter. A quarter with zero filings shows `0`, which is a fact, not a
  `no_match`.
- **`periods: []`** hides the selector entirely and renders the existing flat
  `EvidenceDetails` view unchanged — including no denied tile, since
  `denied_count` is `None` on such rows.
- **Stale rows** replace `Checked 3 days ago` with
  `⚠ Checked 47 days ago — may be out of date`, still render every tile, and
  switch the button label to `Refresh`. Nothing auto-fires. The button's
  disabled/spinner state continues to come from the run store, not from the
  mutation. The stale notice is independent of the selector, so a stale legacy
  row with `periods: []` shows it too.
- The refresh button's helper line states that refreshing updates every job at
  this company — a consequence of D1 the user must not discover by surprise.
- If a detail-query refresh replaces the selected period, the rendered value
  falls back to the rollup unless that period still exists. The control must
  never retain a stale, raw provider label.

**The period `<Select>` must use a children resolver function, not a bare
`<SelectValue/>`.** This repo's Base UI Select renders the raw value
(`"FY2026-Q1"`) instead of the label (`"FY2026 Q1"`) until the dropdown has been
opened once. A test pins the label rendering before any interaction.

---

## Error handling

> **Baseline note.** The manual check is a **background run**, not a synchronous
> call: `POST /api/jobs/{id}/h1b-sponsorship` returns `202 RunOut` through the
> launch seam with `singleton_key=f"h1b-sponsorship:{job_id}"`, and the panel
> derives its checking/failed state from the run store via
> `latestArtifactRun(runs, "h1bSponsorship", "jobId", jobId)`. Evidence reaches
> the panel only through the invalidated `["job"]` query, never from the
> mutation response. This design keeps that contract untouched.

| Condition                                                         | Behaviour                                                                                                                                                                                 |
| ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| MCP unreachable                                                   | `_unavailable(reason=H1B_MCP_UNAVAILABLE_REASON)` with the 5-minute TTL — **unchanged**. Card shows "Research unavailable" plus a retry affordance; never rendered as `no_match`.         |
| `h1b_mcp_enabled = false`                                         | `GET /api/jobs/{id}` reports `capability: "disabled"`; `POST …/h1b-sponsorship` raises `409 H1B_DISABLED`. The Sponsorship tab is still present and explains how to enable it. Unchanged. |
| No cache row for the company                                      | `capability: "unavailable"`, "Not checked", button reads `Check H-1B`.                                                                                                                    |
| Corrupt `evidence_json`                                           | Row skipped by `load_company_evidence`; card reads as unchecked. Fail closed.                                                                                                             |
| Agent returns >4 periods, duplicate labels, or an oversized label | Whole evidence object rejects → `_unavailable`.                                                                                                                                           |
| Blank company on manual check                                     | Existing `422 VALIDATION_ERROR`. Unchanged.                                                                                                                                               |
| Per-run cap reached                                               | Never-cached companies remain unchecked; expired rows remain visible as stale and are refreshed on a later run. Not a failure.                                                            |

---

## Testing

### Backend

- `load_company_evidence` issues **one** query for N companies (assert query
  count).
- A `schema_version = 1` row loads with `periods == []`.
- The rollup validator **overwrites** a model-supplied `filing_count` that
  disagrees with the sum of its parts, and does the same for `certified_count`
  and `denied_count`.
- A metric that **no** period reports rolls up to `None`, not `0`.
- Period cap (>4) and duplicate labels reject the evidence object; legacy flat
  totals also reject `certified_count + denied_count > filing_count`.
- `H1BSponsorshipEvidenceOut.from_evidence` projects `periods` and
  `denied_count` onto the wire in camelCase.
- `stale` flips exactly at `expires_at`.
- Widened enrichment covers non-`silent` companies **while** `run_score`'s
  `sponsorship_evidence` map still contains only `silent` jobs — the regression
  guard for scoring behaviour. All researched/cache-hit jobs receive only the
  provenance pointer.
- The per-run cap selects deterministically (most jobs first, then name), fresh
  cache hits do not consume it, all-fresh runs still reach the scorer, and a
  stale row deferred by the cap does not.

### Contract

Regenerate with `bash scripts/gen_ts_client.sh`;
`tests/api/test_openapi_contract.py` is the drift gate.

### Web

- Period selector renders its **label** before first open (the Base UI
  `SelectValue` regression).
- Selecting a quarter changes the tiles but **not** the status banner.
- A `periods: []` result renders the flat view with no selector.
- A stale row — including the flat legacy fallback — shows the warning and still
  shows its available tiles.
- `JobModal` exposes exactly the six new tabs and no `Application` or
  `Management` trigger.
- `TrackingTab` renders both editors and the fenced delete; delete stays
  disabled when `hasProgress` and closes the modal only after mutation success.

### Board N+1 pin

A test exercising the production `services.board.list_board` path for each board
proves H-1B status resolves without per-row queries, mirroring
`test_shortlist_and_triage_rows_never_touch_jd_text`.

---

## Out of scope

- Lifetime (all-history) filing totals. The user asked for the latest plus the
  past four quarters; a lifetime figure would need a second provider call and a
  second number on the card that contradicts the "Last 4 quarters" label.
- Making H-1B evidence a board **filter**. The board's existing `sponsorship`
  filter reads `criteria.sponsorship_signal` (the JD signal) and is untouched.
- Per-quarter independent refresh. One cache row refreshes as a unit.
- Any change to the fit-scoring prompt or to how `compose_fit_input` consumes
  evidence.
