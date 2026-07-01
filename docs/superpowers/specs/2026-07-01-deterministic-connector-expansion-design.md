# Deterministic Connector Expansion — Design

**Date:** 2026-07-01
**Branch:** feat/agent-quality-evals (or a fresh feat branch off it)
**Status:** Approved design, pre-plan

## Context

The discovery layer pulls jobs through a family of connectors that share one seam
(`harvest` / `harvest_detailed`), each emitting `RawJob`s that `ingest` dedupes and
merges under a source-priority policy. Every connector today is a **deterministic,
reverse-engineered HTTP/JSON API** (Greenhouse, Lever, Ashby, Workday, Tesla,
Google) plus aggregators (Adzuna, RemoteOK, LinkedIn). The offline test suite fakes
the browser and every LLM call; connectors are tested against fixture payloads.

This spec expands that deterministic layer along three cohesive threads. It does
**not** introduce browser DOM scraping or LLM-inferred structure — that is a
separate, later spec (the "generic learn-and-scrape" system), deliberately deferred
so this work stays pure-HTTP, offline-testable, and on the existing grain.

### Scope decision

The original request bundled four ideas. We split them:

- **This spec (deterministic bundle):** more supported ATS websites (#2),
  server-side filter/search push (#3), skip-known-jobs when pulling (#4).
- **Deferred to its own spec:** the generic LLM-learned Playwright scraper for
  arbitrary company-owned dashboards (#1), which is non-deterministic, token-costed
  per site, browser-driven, and hard to test offline — a different animal that wants
  its own design and test strategy.

## Goals

1. Add coverage for seven more ATSes via the existing detect → backend → register
   recipe, onboarded purely by pasting a careers URL into `companies.urls`.
2. Push search-term + location filters server-side where an ATS supports them, as a
   coarse efficiency pre-narrow — never a correctness boundary.
3. Skip the expensive per-job work (N+1 detail fetch, Adzuna browser render) for
   jobs already known from the same-or-higher-tier source, without ever skipping an
   upgrade.

## Non-goals

- Browser DOM scraping, LLM structure inference (separate spec).
- Browser-gated ATSes: iCIMS, Taleo, SAP SuccessFactors, Jobvite (they need the
  scraper spec; forcing them here would drag Playwright/bot-evasion into a pure-HTTP
  layer).
- Structured facet/department/team/employment-type filters (tenant-specific facet
  IDs, the same reason Workday `appliedFacets` was deferred).
- TTL-based staleness re-fetch (the `--refresh` flag covers the manual case).
- Fixing `dedup_key`'s dropped-location collapse in general (tracked separately;
  this spec only works around it for skip decisions via a location match).

---

## Thread A — Seven new clean-API ATS backends (#2)

### Backends

`smartrecruiters`, `workable`, `recruitee`, `personio`, `breezy`, `jazzhr`,
`bamboohr`. Each is believed to expose a public JSON/XML postings endpoint, keeping
it deterministic and offline-testable against a captured fixture.

Build order: **SmartRecruiters + Workable first** — both also expose server-side
search, so they deliver Thread B in the same stroke.

### Per-backend recipe (unchanged framework pattern)

1. **Detection** in `discovery/connectors/detect.py`:
   - An L1 host/path pattern that yields the ATS + token (single slug in
     `AtsTarget.token`, as Greenhouse/Lever/Ashby do). Add an L2 marker only where
     the ATS is embedded on a company's custom domain.
2. **Backend module** `discovery/connectors/<name>.py` exposing
   `fetch_<name>(target, search, limit) -> list[RawJob]`, using `harvest` (single
   list request) or `harvest_detailed` (if the ATS needs an N+1 list→detail dance).
3. **Register** a thin adapter in `companies._BACKENDS` (the
   `(target, search, limit) -> RawJob[]` shape).

Onboarding is then: user pastes any supported careers URL into `companies.urls`;
`detect_ats` resolves it; `CompaniesConnector` dispatches and isolates per-URL
failures. **No new config sections, no registry wiring.**

### Fixtures & isolation

- Each backend ships a **captured representative payload** under `tests/fixtures/`
  (a research step: hit the live API once to capture real JSON/XML). Parse is tested
  offline against the fixture.
- Breezy / JazzHR / BambooHR endpoints are **reverse-engineered** (no public
  contract). They inherit the Tesla/Google caveat: a parse failure records to
  `FetchResult.failures` for that URL and never aborts the pull. `_failure_reason`
  already classifies HTTP vs parse errors — new backends need no new policy.

### `AtsTarget` shape

Most backends map to a single `token` slug (company/account subdomain), reusing the
existing field. Any backend needing more than a slug adds a narrowly-scoped field to
`AtsTarget` (as Workday did with `tenant`/`datacenter`/`site`); prefer reusing
`token` where the identity is a single slug.

---

## Thread B — Server-side search + location push (#3)

### Approach

Each capable backend maps `SearchConfig` → its own query params:

- **SmartRecruiters:** `?q=<term>` + location param.
- **Workable:** search/filter POST body.
- **Lever:** `?location=` / `?team=` query filters.
- **Workday:** already pushes `searchText` (unchanged); location left as-is for now.
- Extend the same idea to any new backend whose API takes a cheap term/location.

Add a `primary_location(search)` helper in `discovery/connectors/text.py` alongside
the existing `primary_search_term(search)` (first non-empty configured location).

### Rules

- **Best-effort:** if a `SearchConfig` field has no cheap mapping for a given ATS,
  omit that param — never fail the pull.
- **Coarse pre-narrow only:** the push reduces bytes/pages/detail-fetches. The local
  `relevance_gate` remains the **authoritative** filter — server-side search
  over-drops on synonyms, and fact-lock cannot tolerate silently vanishing jobs. The
  kept set after a pull is identical to what the local gate would keep; only the
  fetched volume shrinks.

---

## Thread C — Skip-known pre-fetch early-out (#4)

### Insight

`ingest` already skips duplicate rows (`merge.decide()` returns `Skip` for
same/lower-tier re-pulls) — so skip-known is **not** about avoiding duplicate rows.
Its only value is **avoiding the expensive step that would be thrown away**: the
Workday/Tesla N+1 detail GET and the Adzuna visible-browser render. So the mechanism
is a **pre-detail-fetch early-out**, and it must reuse the same source-priority
policy the ingest skip already trusts, so the two can never diverge.

### Components

- **`KnownJobsIndex`** — built once per pull from a single DB query filtered on
  `archived_at IS NULL` (mirroring `find_existing`). Provides lookup by:
  - `url → (source, status)`
  - `(dedup_key, location) → (source, status)`
- **`should_skip(source, url, company, title, location) -> bool`** — returns True
  iff a known row matches (by `url`, **or** by `dedup_key` with a **matching
  location**) **and** `source_rank(incoming) >= source_rank(existing)`. This mirrors
  `merge.decide()`'s `Skip` branch exactly (skip when the incoming source cannot beat
  the existing row on tier). The location match neutralizes the `dedup_key`
  dropped-location collapse for skip decisions: two same-title reqs in different
  cities won't skip each other.
  - Consequence accepted by design: a same-source `RefreshText` (thin JD → richer
    JD) and later edits are not picked up on a default pull. `--refresh` recovers
    them.

### Threading (connectors stay DB-free)

- `Connector.fetch(search, limit, skip_seen=None)` — new optional predicate
  parameter (default `None` = today's behavior).
- `harvest` and `harvest_detailed` accept `skip_seen` and apply it **before** the
  detail fetch (and before adding to the union). In `harvest_detailed` this short-
  circuits the `fetch_detail` call; in Adzuna enrichment it short-circuits the
  browser render.
- The predicate is a **closure the orchestration layer builds** from the preloaded
  `KnownJobsIndex`. Connectors never touch the `Session` — the "connectors emit
  RawJobs, ingest owns the DB" separation is preserved.

*Rejected alternative:* give connectors a DB session to self-check — rejected, it
breaks the DB-free connector contract.

### Bypass

`resume-agent pull --refresh` (and the API pull-run equivalent) passes
`skip_seen=None`, re-fetching everything to pick up JD refreshes/edits.

---

## Data flow

```
pull
  → orchestration loads KnownJobsIndex        (1 DB query)
  → builds skip_seen closure                  (unless --refresh)
  → build connectors
  → connector.fetch(search, limit, skip_seen)
       → harvest / harvest_detailed apply skip_seen BEFORE detail fetch
       → server-side term+location push shrinks the fetched list
       → local relevance_gate (authoritative) filters the union
  → RawJobs
  → ingest.save_or_upgrade                     (unchanged; correctness authority)
```

## Error handling

- Per-URL/board fail-isolation unchanged (`harvest` `on_error`); new backends reuse
  `_failure_reason` (HTTP vs parse). Reverse-engineered backends isolate parse
  failures to their URL.
- Server-side filter params are best-effort; an unsupported/malformed param is
  omitted, never fatal.
- The skip predicate is pure/in-memory; a lookup miss just means "fetch it" — a safe
  fallback that can only cost an extra fetch, never a wrong skip.

## Testing (all offline; browser + LLM stay faked)

- **Thread A:** per backend, a fixture parse test + a detection test for the new host
  pattern in `detect.py`.
- **Thread B:** assert the outgoing request carries term + location; assert the kept
  set is unchanged (the local gate still runs and remains authoritative).
- **Thread C:**
  - `should_skip` unit matrix over tier × location × url (same-tier → skip;
    lower-tier existing + higher-tier incoming → do NOT skip / upgrade path;
    location mismatch → do NOT skip).
  - A spy test proving `harvest_detailed` does **not** call `fetch_detail` for a
    skipped row.
  - `--refresh` bypass test (skip disabled → detail fetched).

## Invariants preserved

- **Fact-lock:** untouched (no JD invention anywhere in this work).
- **Source priority — upgrade, not drop:** the skip predicate mirrors `decide()`'s
  `Skip` branch, so an upgrade re-pull is never skipped.
- **Archive filtering:** the `KnownJobsIndex` query filters `archived_at IS NULL`.
- **Determinism / offline testability:** no browser or LLM introduced.

## Build phases (for the plan)

1. **Thread C (skip-known)** — smallest surface, highest immediate value, and its
   `skip_seen` seam is independent of new backends. Ship first.
2. **Thread A backends** — SmartRecruiters + Workable (with their Thread B filters),
   then Recruitee + Personio, then Breezy + JazzHR + BambooHR. Each backend is an
   independent, isolated task.
3. **Thread B** for remaining capable backends (e.g. Lever) as a small follow-on.
