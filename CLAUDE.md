# Resume Agent — Developer Reference

## Commands

```bash
# Test (offline — no API key, no network needed)
.venv/Scripts/python.exe -m pytest

# Lint
ruff check
```

All agent calls and the Playwright browser are faked in tests. Connector backends
are tested against fixture JSON payloads, not live endpoints.

---

## Core invariants (never break these)

### Fact-lock
Every bullet on a tailored resume must trace back to a fact in
`data/profile/facts.json`. The `fact-check` reviewer in `review.yaml` is a
**hard gate** (not scored) — any unsupported claim fails the round. Agents
rewrite and reframe; they never invent.

### Source priority — upgrade, not drop
When two sources see the same job, the canonical source wins over an aggregator.
The existing `Job` row is **mutated in place** (same id); user progress — status,
`Application`, `ResumeVersion`, `CoverLetter` — is never touched.

| Tier | Sources |
| --- | --- |
| **Canonical** | `greenhouse`, `lever`, `ashby`, `workday`, `tesla`, `google`, `companies`, `url` |
| **Fallback** | `adzuna`, `remoteok`, `linkedin` |

Equal-tier re-pulls are no-ops (first-seen-wins). Once a job's status has
advanced past `raw`, only the apply `url` is upgraded; `jd_text` is frozen so a
resume already tailored to the old text is not silently re-based.

---

## ATS detection flow (`detect.py`)

`detect_ats(url)` resolves in order — stop at the first match:

1. **Singleton host match** — `tesla.com/careers` → `AtsTarget("tesla")`;
   `careers.google.com` → `AtsTarget("google")`. No token; the host is the
   identity. Checked before L1/L2.
2. **L1 URL pattern** — host + path directly reveals ATS and board token
   (Greenhouse, Lever, Ashby, Workday triple from `{tenant}.{dc}.myworkdayjobs.com/{site}`).
3. **L2 HTML sniff** — fetches the page, scans for embedded ATS markers
   (Greenhouse embed `?for=`, Lever/Ashby slugs, Workday full URL in HTML).

`AtsTarget` fields: `ats`, `token` (Greenhouse/Lever/Ashby slug), `tenant` +
`datacenter` + `site` (Workday triple). Tesla/Google carry only `ats`.

---

## Companies connector dispatch (`companies.py`)

`CompaniesConnector.fetch` delegates to the `harvest` seam: for each URL in
`self.urls` it calls `detect_ats`, looks up the backend in `_BACKENDS`, and calls
`backend(target, search, limit)`. Any URL that fails detection or whose backend
raises `httpx.HTTPError` / a parse error is recorded on the returned
`FetchResult.failures` (url → reason) — it never aborts the run. The relevance
gate `harvest` runs over the union is the backstop for backends that don't filter
server-side.

To add a new backend: write `fetch_<name>(target, search, limit) -> list[RawJob]`
in a new module, add detection logic to `detect.py`, register in `_BACKENDS`.

---

## Workday N+1 pattern (`workday.py`)

Workday boards can have thousands of global listings — pulling all then gating
locally is infeasible.

1. **POST** `…/wday/cxs/{tenant}/{site}/jobs` with `{"searchText": ..., "limit": 20, "offset": N}` — paginated list, title + location only.
2. **`title_relevance_gate`** prunes the list _before_ any detail fetch.
3. **GET** `…/wday/cxs/{tenant}/{site}{externalPath}` for each survivor → `jobPostingInfo.jobDescription` (HTML → text via `html_to_text`).

Safety ceiling: `_MAX_OFFSET = 1000` (≤51 pages) even if the tenant ignores
`searchText`. Keep `search.yaml` role anchors tight — the title-gate's
aggressiveness determines how many detail fetches are issued.

---

## Relevance gates (`text.py`)

| Function | When used |
| --- | --- |
| `title_relevance_gate` | Before JD text is available (Workday list rows, Tesla listing state) |
| `relevance_gate` | Full gate on title + JD; falls back to keyword search when no `role_anchors` are configured |
| `primary_search_term` | Picks the strongest term to send as `searchText` to Workday / Google; falls back to `role_anchors` if `titles` and `keywords` are empty |

---

## Hot paths (most-edited files)

| Path | Role |
| --- | --- |
| `src/resume_agent/discovery/connectors/detect.py` | ATS detection (singleton → L1 → L2) |
| `src/resume_agent/discovery/connectors/companies.py` | Dispatch table + per-URL fail isolation |
| `src/resume_agent/discovery/connectors/workday.py` | Workday CXS list → gate → detail |
| `src/resume_agent/discovery/connectors/tesla.py` | Tesla bespoke JSON portal |
| `src/resume_agent/discovery/connectors/google.py` | Google Careers JSON API |
| `src/resume_agent/discovery/connectors/text.py` | Relevance gates + `html_to_text` |
| `src/resume_agent/discovery/connectors/runner.py` | Pull orchestration, `+N added, N upgraded` telemetry |
| `src/resume_agent/discovery/ingest.py` | `save_or_upgrade`, source-priority logic |
| `src/resume_agent/tracking/dedup.py` | `compute_dedup_key` — `company|normalized_title` |
| `tests/test_discovery_ingest.py` | Ingest + dedup + priority tests |

---

## Known design notes

- **`dedup_key` drops location.** `compute_dedup_key` is `normalize(company)|normalize_title(title)`.
  Multi-location same-title Workday reqs (e.g. "Software Engineer" in Austin vs. Detroit at GM)
  collapse to one job. Flagged as a follow-up micro-spec — fix is adding location to the key or a
  location-aware secondary check.
- **Workday `appliedFacets` not used.** v1 shapes requests with `searchText` only. Location/category
  facet IDs are tenant-specific (require a separate facets call) and are a later refinement.
- **Tesla/Google endpoints are reverse-engineered.** They have no public API contract and could change
  without notice. Each is isolated to its own module behind `_BACKENDS`; a parse failure records to
  `.failures` and never aborts the pull.
- **Tailor loop is synchronous.** Parallel reviewer panels and job-level concurrency are deferred
  while this pass reduces cost through leaner prompts.
