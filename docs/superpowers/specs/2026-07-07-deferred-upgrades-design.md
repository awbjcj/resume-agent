# Deferred Upgrades: Dedup Location Guard, Gmail/LinkedIn API, Cover-Letter Evals — Design

**Date:** 2026-07-07
**Status:** Approved (brainstorming interview complete)

## 1. Background and scope

An audit of `docs/superpowers/plans/` against git history found that nearly every
"deferred" plan has shipped. Four items remain genuinely outstanding; this spec
covers the three that need new design, and records the execution decision for the
fourth:

| # | Item | Origin | Design needed? |
| --- | --- | --- | --- |
| 1 | Dedup-key location collision fix | CLAUDE.md follow-up micro-spec | Yes (§2) |
| 2 | Gmail sync + LinkedIn scrape over HTTP | API-layer deferred list | Yes (§3) |
| 3 | Cover-letter evals | Eval-harness spec Phase 2+ note | Yes (§4) |
| 4 | Craft-enrichment ship decision | `2026-07-02-craft-prompt-enrichment.md` Task 5 | No — execute the existing plan verbatim (§5) |

Out of scope (explicitly excluded during the interview): Workday `appliedFacets`,
saved/named views + list virtualization in the bulk jobs UI, any web OAuth flow,
and the remaining tasks of `2026-07-07-architecture-perf-stability.md` (in flight
in another session).

## 2. Dedup location guard

**Problem.** `compute_dedup_key` is `normalize(company)|normalize_title(title)`,
so multi-location same-title reqs (e.g. Workday "Software Engineer" in Austin vs.
Detroit) collapse to one Job row.

**Decision.** Keep the key unchanged; add a location-aware secondary check at
match time. No schema change, no backfill.

### Behavior

- New pure helper `locations_compatible(a: str | None, b: str | None) -> bool` in
  `tracking/dedup.py`:
  - Either side `None`/blank → **compatible** (aggregators often omit location;
    preserves today's cross-source upgrade merging).
  - Both present → normalize with the existing `_normalize` (lowercase, strip
    punctuation), take the **city segment** (text before the first comma), and
    treat the pair as compatible when either city's token set is a subset of the
    other's. "Austin, TX" ↔ "Austin, Texas, United States" → compatible;
    "New York" ↔ "New York City" → compatible; "Austin, TX" ↔ "Detroit, MI" →
    not.
  - "Remote" is its own city: "Remote" ↔ "Austin, TX" → not compatible.
- `find_existing` (`tracking/repository.py`), dedup_key branch only: fetch **all**
  non-archived rows matching the key (today: `.first()`) and return the first
  location-compatible one; if none is compatible, fall through (no match), so the
  incoming job inserts as a sibling row sharing the dedup_key.

### What does not change

- URL match and identical-JD (fingerprint-narrowed) match still win first,
  unconditionally — same URL or byte-identical JD *is* the same posting.
- `compute_dedup_key`, the keyless fingerprint fallback, and all source-priority
  upgrade logic are untouched. Upgrades keep working because a canonical source
  and an aggregator seeing the same posting either share a URL/JD or have
  compatible city segments.
- Existing collapsed rows are not split retroactively; they merely stop absorbing
  future distinct-location pulls.

### Testing

Unit tests for `locations_compatible` (blank sides, state-spelling variants,
remote, multi-token cities) and ingest tests in `tests/test_discovery_ingest.py`:
same key + different city inserts a sibling; same key + compatible city upgrades
in place; archived rows still never block re-ingest.

## 3. Gmail sync + LinkedIn scrape over HTTP

Both follow the established Run + SSE pattern (`202` + run record; worker in the
`RunManager` threadpool **opening its own DB session**; progress via
`GET /api/runs/{id}/events`). Routers stay thin over new `services/` functions.
Credentials are **CLI-provisioned** — no web OAuth flow; a missing token/session
fails the run fast with an actionable error.

### Gmail (propose → apply, mirroring the CLI `sync-status` shape)

- `POST /api/gmail/sync` → `202` + run record. Worker:
  `build_gmail_service()` → `fetch_recent_messages` → `propose_transitions`,
  reporting progress per email. Proposals are stored in the run **result
  payload** (no new table): `[{applicationId, label, currentStatus,
  proposedStatus, evidence}]`. Body accepts optional `maxResults` (default 50).
- `POST /api/gmail/transitions` with `{transitions: [{applicationId,
  proposedStatus}]}` → applies via `update_application_status`, returns
  `{applied: n}`. Synchronous; re-applying a same-status transition is a no-op.
- Missing/expired OAuth token → error envelope code `gmail_not_configured`,
  message naming the CLI login step.
- New service module: `services/gmail_sync.py` (propose + apply use-cases; CLI
  `sync-status` refactors onto it so both surfaces share one seam).

### LinkedIn

- `POST /api/sources/linkedin/scrape` → `202` + run record. Worker builds the
  scraper via the existing `build_linkedin_scraper()` and ingests through the
  same `save_or_upgrade` path as `pull` (fallback-tier source, unchanged).
  Per-item failures land in the run report and never abort the run.
- The visible browser window opening on the server host is documented expected
  behavior (local single-user deployment). Missing session/profile → error code
  `linkedin_not_configured`.
- Service seam: slots into the existing discovery service alongside pull.

### Contract plumbing (both)

New `CamelModel` schemas; OpenAPI export + `bash scripts/gen_ts_client.sh` regen;
`tests/api/test_openapi_contract.py` drift gate updated. Tests are offline: the
Gmail service and the scraper are faked, per repo convention.

## 4. Cover-letter evals (measure-only)

**Decision.** Extend the existing harness in `evals/`; no parallel machinery, no
CI gate, no ship/revert threshold. One baseline run is recorded so future
prompt changes to cover letters have a reference point — mirroring how resume
evals were introduced.

### Harness changes

- Case schema gains a `target` discriminator: `"resume"` (default — existing case
  files untouched) or `"cover_letter"`. The runner branches on it to drive the
  cover-letter generation path instead of the tailor loop.
- Judge gets a cover-letter rubric: **grounding** (every factual claim traces to
  profile facts), **JD/company specificity** (not a template letter), **tone**
  against the house style guide, and **length band**. Trap detection reuses
  `textscan.py`'s planted-token approach. Metrics/report/usage machinery reused
  as-is.

### Cases (4, reusing existing profiles)

1. Standard backend role (`backend_eng`) — baseline quality reading.
2. Adjacent-skill trap — JD names a skill the profile matches only at adjacent
   tier; the letter must not claim the JD's own term (fact-lock invariant).
3. Career changer (`career_changer`) — narrative reframing without invention.
4. Metric-rich (`metric_rich_eng`) — numbers copied faithfully, never inflated.

### Output

One live baseline run recorded to `evals/reports/2026-07-cl-baseline.json` and
noted in `evals/RESULTS.md` as measure-only.

## 5. Craft-enrichment ship decision (execute existing plan)

Task 5 of `docs/superpowers/plans/2026-07-02-craft-prompt-enrichment.md` is
executed **as written**: after-runs for both arms (mp-off, mp-on), fill
`evals/RESULTS.md` from the artifacts, apply the documented ship rule (mean
`output_quality` Δ ≥ +5, no trap/provenance regression, tokens ≤ +20%), and flip
`match_plan_enabled` default-on only if the mp-on arm wins under that rule. An
iterate/revert outcome is recorded and handled per that plan's own loop. Tasks
1–4 of that plan are already committed (`33a50dae`, `8b7b4e8e`, `eda57e10`, and
the agent wiring); nothing is re-planned here.

## 6. Sequencing and verification

Four workstreams, each independently green under the offline suite
(`.venv/Scripts/python.exe -m pytest`) and `ruff check`:

1. **Dedup location guard** — smallest, pure offline.
2. **Gmail/LinkedIn HTTP surface** — offline-tested; contract drift gate covers
   the new endpoints.
3. **Cover-letter eval harness + cases** — harness changes testable without
   spend.
4. **One live sitting at the end** — CL baseline run, craft after-runs, and the
   recorded decision. Bundling all LLM spend into a single final step keeps
   everything before it fully offline-runnable; the sitting's artifacts (report
   JSONs + `evals/RESULTS.md`) are the evidence for the craft decision.

## 7. Risks

- **Live sitting depends on API keys/spend**; the craft rule may resolve to
  iterate, which loops within the existing craft plan rather than blocking the
  other three workstreams (they have no dependency on it).
- **Location strings are messy.** The guard is deliberately loose (blank = wild,
  city-segment tokens only) to bias toward merging; the failure mode of an
  over-loose guard is today's status quo, never a regression.
- **LinkedIn scraping remains best-effort** (bot-gated); the run-report failure
  channel already isolates it.
