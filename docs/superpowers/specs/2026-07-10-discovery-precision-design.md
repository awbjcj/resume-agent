# Discovery Precision — Design

**Date:** 2026-07-10
**Status:** Approved (grilled 2026-07-10)
**Plans:** two — (1) Google + Tesla connectors, (2) per-source limits + Workday location facets.

## Problem

Four precision gaps in discovery, confirmed by live probes on 2026-07-10:

1. **Google connector is dead.** `careers.google.com/api/v3/search/` returns 404.
   The live surface is `https://www.google.com/about/careers/applications/jobs/results`,
   which serves plain HTML (200, no bot gate) with job data embedded in
   `AF_initDataCallback` JSON blobs.
2. **Tesla connector is blocked.** `tesla.com/cua-api/apps/careers/state` returns
   403 (Akamai) even with full browser headers — bare `httpx` can never work.
3. **Job counts per source are unpredictable.** One global `--limit N` is passed
   to every connector; inside `CompaniesConnector` it caps *both* each URL's
   backend *and* the union (`harvest`'s `gate_and_limit`), so with several
   careers URLs the first prolific board eats the budget and later boards get
   nothing. There is no per-source knob.
4. **Workday pulls are searchText-only.** Global tenants return thousands of
   irrelevant rows that the title gate must chew through; `appliedFacets` was
   deferred because facet IDs are tenant-specific.

## Non-goals

- Workday job-category/jobFamily facets (location only in v1 — category
  vocabularies vary per tenant and mis-mapping silently hides jobs).
- "Exact rows inserted" limit semantics (fetch stays decoupled from ingest;
  `skip_seen` keeps fetched ≈ added).
- Changing match-gap, tailoring, or any LLM behavior.

---

## 1. Google Careers connector rebuild (`google.py`)

Pure `httpx`, no browser. Same public shape: `fetch_google(target, search,
limit, skip_seen)` registered in `_BACKENDS`.

- **List:** `GET https://www.google.com/about/careers/applications/jobs/results`
  with `q=primary_search_term(search)` and `page=N`. Parse the
  `AF_initDataCallback` blob that carries job rows (the exact `ds:` key is
  pinned at build time from saved fixture HTML) into list rows: job id, title,
  locations, detail slug (`jobs/results/<id>-<slug>`). Keep a `_MAX_PAGES`
  ceiling. Stop early when a page yields no rows.
- **No detail fetch needed (verified 2026-07-10):** the list blob embeds each
  job's full description — about, responsibilities, and qualifications HTML —
  plus locations, publish timestamps, and the result total. The connector is
  list-only: parse rows, `html_to_markdown` the joined description sections,
  cap to `limit`. Relevance gating stays in the companies `harvest` union as
  today.
- **Detection:** already covered — `_SINGLETON_HOSTS` in `detect.py` maps
  `www.google.com` + `/about/careers/` and `careers.google.com` to
  `AtsTarget("google")`. No change needed.
- **Failure isolation:** blob-shape drift raises a parse error that
  `companies._failure_reason` records per-URL (`parse error: …`) — never aborts
  the pull. This stays a reverse-engineered surface; the design note in
  CLAUDE.md remains true.
- **Tests:** fixture HTML files (one list page, one detail page) checked into
  `tests/fixtures/`; parser unit tests + a connector test with `httpx` faked.
  Offline suite stays network-free.

## 2. Tesla browser-based connector (`tesla.py`)

`fetch_tesla` keeps its signature and its `_BACKENDS` registration but drives
the shared **visible** browser (the Adzuna precedent — headless is challenged
by Akamai).

- **List:** render the configured Tesla careers URL
  (`tesla.com/careers/search/…`) via the browser seam; capture the JSON body of
  the `cua-api/apps/careers/state` response the page itself issues (response
  interception). `parse_listings` is unchanged.
- **Detail:** for each title-gated, unseen survivor, evaluate an in-page
  `fetch` of `cua-api/apps/careers/job/{id}` inside the same browser context
  (same origin, carries the Akamai cookies) and parse with the existing
  `apply_tesla_detail`. `harvest_detailed` still owns gate/limit/skip logic;
  only `_fetch_detail`'s transport changes.
- **Serialization:** `CompaniesConnector` stays `concurrent_fetch=True`; the
  browser seam itself owns a process-wide single visible context (as for
  Adzuna), so a Tesla backend call blocks on that seam's own lock while other
  httpx backends fetch concurrently.
- **UX consequence (accepted):** a pull whose companies list includes Tesla
  pops a browser window and runs slower. Documented in CLAUDE.md next to the
  Adzuna note.
- **Tests:** fixture state JSON + fixture detail JSON; the browser is faked as
  it is for Adzuna/dashboard scraper. Enrichment path is un-exercised live by
  the offline suite — same status quo as Adzuna.

## 3. Per-source pull limits

**Contract change:** `limit` becomes a *per-unit* cap — a unit is one board,
one careers URL, or one singleton connector (the same granularity as
`ConnectorUnit` in `registry.py`). Union caps are removed.

- **Config:** every unit model in `connectors/config.py` (`GreenhouseBoard`,
  `LeverBoard`, `CompanyUrl`, `ScrapeTarget`, and the singleton sections
  `remoteok`/`adzuna`/`linkedin`) gains optional `limit: int | None = None`
  (all are `ExtensibleModel`, so this is additive; existing YAML keeps
  loading).
- **Payload shape:** `registry.py` currently passes bare payloads that drop
  the config entry (e.g. companies passes `e.url`, a string). Units whose
  entries gain a limit pass the entry model itself (or an equivalent
  value+limit pair) so the connector can resolve each unit's cap.
- **Resolution:** effective unit limit = `unit.limit` if set, else the global
  `--limit` value. The global flag's meaning shifts from "cap per connector"
  to "default cap per unit" — this is the deliberate fix: with 5 companies
  URLs and `--limit 10`, each URL may now yield up to 10 (previously the union
  was capped at 10 in board order).
- **Enforcement point:** the `harvest` seam gates and caps **per unit** (gate →
  `skip_seen` → cap inside each unit's produce), instead of gating/capping the
  union; `filtered` counts sum across units. `harvest_detailed` already caps
  per call and is passed the resolved unit limit. Multi-board connectors
  (greenhouse/lever) apply the same per-unit cap.
- **Semantics:** max *unseen, relevant* jobs fetched per unit per pull —
  `skip_seen` runs before the cap (already true in `gate_and_limit`), so the
  cap fills with new rows and fetched ≈ added.
- **Surface:** sources config API schemas gain the field (camelCase `limit`),
  the web Source Manager shows an optional per-source limit input, and
  `bash scripts/gen_ts_client.sh` regenerates the contract.
  `tests/api/test_openapi_contract.py` gates drift.

## 4. Workday location facets (`workday.py`)

- The CXS list response itself carries a `facets` array. On the first page of
  a pull, match the configured `search.yaml` locations against the facet
  descriptors (case-insensitive containment on facet value labels) to resolve
  tenant-specific facet parameter + ID pairs.
- Cache the resolved mapping per tenant under `data/workday_facets/{tenant}-{site}.json`
  with the source location strings as the cache key — re-resolve when
  `search.yaml` locations change.
- Subsequent list POSTs include `appliedFacets: {<param>: [ids…]}` alongside
  `searchText`. Any resolution miss (no facet matches a configured location,
  malformed facet block) falls back silently to today's searchText-only
  behavior — never fewer results than the status quo from a mapping failure,
  and the `_MAX_OFFSET` ceiling stays.
- The CLAUDE.md "appliedFacets not used" design note is replaced by a
  description of this behavior.
- **Tests:** fixture list responses with facet blocks; cases for resolve-hit,
  resolve-miss fallback, and cache reuse/invalidation.

## Cross-cutting constraints

- Offline suite green with no key/network: `.venv/Scripts/python.exe -m pytest`; `ruff check` clean.
- Any API-surface change regenerates `contracts/` and keeps the drift gate green.
- Source-priority, dedup + location guard, and fact-lock invariants untouched.
- Per-URL failure isolation (`FetchResult.failures`) remains the error model
  for both rebuilt connectors.
