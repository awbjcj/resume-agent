# Structured-Backend Family + Dispatch Generalization — Design (Spec A)

**Date:** 2026-06-19
**Status:** Draft (design); pending user review
**Branch:** `feat/discovery-structured-backends-and-priority`
**Surface:** `discovery/connectors/detect.py` (descriptor + Workday/Tesla/Google detection),
`discovery/connectors/companies.py` (dispatch seam), new backend modules
`discovery/connectors/workday.py`, `tesla.py`, `google.py`. **No new config section.**

> This is **Spec A** of a two-part upgrade brainstormed on 2026-06-19. The parts are independent
> design→plan→build cycles split along a layer boundary:
> - **A — structured-backend family + dispatch generalization** (this spec). *Touches `connectors/`.*
> - **B — source-priority upgrade-merge** (`2026-06-19-source-priority-upgrade-merge-design.md`).
>   *Touches `ingest.py` / `repository.py`.* Newly urgent **because** of A.
>
> A deferred **Spec C** — generic Playwright + cached-pattern scraper for genuinely custom
> (Notion/Webflow/bespoke-HTML) careers pages — is **out of scope** here; it gets its own brainstorm
> later. Its trigger condition is already known: detector returns `None` **and** the host is not a
> known singleton.

---

## 1. Problem & Goal

The `companies` connector (Spec from 2026-06-17) resolves a careers URL to an ATS and fetches its
board. Today it handles **Greenhouse, Lever, Ashby** via:

```
detect_ats(url) -> AtsTarget(ats: str, token: str)  ->  backend.fetch(token) -> RawJob[]
```

**Workday** is *detected but not pulled* (`failures[url] = "Workday recognized, not yet supported"`),
and **Tesla / Google** are not handled at all. Yet for the user's real target set (Tesla, Nvidia,
OpenAI, Ford, GM, Google, Hyundai NA, KLA, Woven by Toyota), the population splits cleanly into:

| Bucket | Companies | Backend reality |
|---|---|---|
| Workday | GM, Nvidia, KLA, Ford, Hyundai NA (auto sector is Workday-saturated) | cxs JSON POST API, paginated |
| Already supported | OpenAI (Ashby), Woven by Toyota (Lever) | ✅ no work |
| Bespoke JSON portal | Tesla, Google | own search API, host-identified |

**None are Playwright/LLM HTML-scrape targets.** Every one exposes a *structured endpoint*. The goal
is therefore to add **three structured backends** (Workday, Tesla, Google) reusing the existing
detect→fetch→`RawJob` spine — and to **generalize the dispatch seam** so it can carry the richer
identity and request-shaping these backends need.

### Why the current seam can't absorb them (the forcing functions)

- **`token: str` is too thin.** Workday's identity is a **triple** — `generalmotors · wd5 ·
  Careers_GM` (tenant · data-center · site). `detect.py` today captures only the tenant
  (`_WORKDAY_HOST` `group(1)`) and silently drops the data-center and site path.
- **Backends must become `search`-aware.** Greenhouse/Lever/Ashby fetch a fixed board and gate
  locally. A GM Workday board is **thousands of global reqs** with a **10,000-result hard cap** and
  is **N+1** (the list call returns no `jd_text`; each description is a second request). Pulling the
  whole board and gating locally is infeasible — Workday must **shape its request** from `search`.
- **Tesla/Google have no token.** Their identity *is* the host; the backend is selected by domain
  and there is nothing to pass.

---

## 2. Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| What to build | **Workday, Tesla, Google** as structured backends. (Ashby/Lever already cover OpenAI/Woven.) |
| Generic long-tail scrape | **Deferred** to Spec C. Not in this spec. |
| Dispatch model | **(1) Unified.** `detect_ats` returns a **structured descriptor**; Tesla/Google resolve by **host-match singletons** inside the same "paste any careers URL" flow. |
| Identity type | `AtsTarget(ats, token)` → **`AtsTarget(ats, params)`** where `params` is an ats-specific mapping (`{"token": …}`, or `{"tenant","datacenter","site"}`, or `{}`). |
| Backend signature | Unify to `fetch(target, search, limit) -> list[RawJob]`. Existing backends ignore `search` (or use it only for the local list-gate). |
| Workday volume | **(A) request-shaping** — push `search` keywords into the cxs `searchText`; **+ (C) list-gate** — relevance-gate on list-row title/location **before** spending the N+1 detail request. |
| Config | **No new section.** Tesla/Google/Workday careers URLs go in the **existing** `companies.urls`; the unified detector routes them. Zero migration. |
| Degradation | **Per-URL fail isolation**, unchanged. One dead/undetectable/unsupported URL is recorded in `.failures`; the rest ingest. |
| Endpoint certainty | Workday cxs shape is **confirmed**. Tesla/Google exact endpoints are **reverse-engineered at build time** from the network tab (flagged risk §6). |

---

## 3. Architecture

### 3.1 Descriptor — `detect.py`

```python
@dataclass(frozen=True)
class AtsTarget:
    ats: str                       # "greenhouse"|"lever"|"ashby"|"workday"|"tesla"|"google"
    params: Mapping[str, str]      # ats-specific; backends read their own keys
```

- Greenhouse / Lever / Ashby → `params = {"token": <slug>}` (behavior identical to today).
- Workday → `params = {"tenant": "generalmotors", "datacenter": "wd5", "site": "Careers_GM"}`.
- Tesla / Google → `params = {}` (host *is* the identity).

`detect_ats` gains, **before** the generic L1/L2 ATS logic:

- **Host-match singletons (new, highest precedence).** `www.tesla.com`/`tesla.com` + path under
  `/careers` → `AtsTarget("tesla", {})`. `careers.google.com` (and `google.com/about/careers`) →
  `AtsTarget("google", {})`.
- **Workday triple (fix existing).** `{tenant}.{dc}.myworkdayjobs.com/{site}/...` → capture **all
  three** (`_WORKDAY_HOST` currently drops dc+site). `site` = first non-empty path segment.

L1/L2 for Greenhouse/Lever/Ashby is unchanged except for wrapping the captured slug in
`{"token": …}`. Detection stays deterministic and fixture-testable (host-match and Workday-triple
need no network; Tesla/Google detection is pure URL parsing).

### 3.2 Dispatch seam — `companies.py`

`CompaniesConnector._fetch_target` dispatches on `target.ats` through a table:

```python
_BACKENDS = {
    "greenhouse": fetch_greenhouse_target,   # wraps existing fetch_greenhouse_board
    "lever":      fetch_lever_target,
    "ashby":      fetch_ashby_target,
    "workday":    fetch_workday,
    "tesla":      fetch_tesla,
    "google":     fetch_google,
}

def _fetch_target(self, url, target):
    backend = _BACKENDS.get(target.ats)
    if backend is None:
        self.failures[url] = f"{target.ats.title()} recognized, not yet supported"
        return []
    return backend(target, self.search, self.limit)
```

Each backend has signature `(target: AtsTarget, search: SearchConfig, limit: int | None) ->
list[RawJob]`. Greenhouse/Lever/Ashby adapters read `target.params["token"]` and call the existing
shared `fetch_*_board` + `parse_*` (one code path preserved). The connector passes `search`/`limit`
down so Workday can shape its request; the final `relevance_gate(jobs, search)` in `fetch()` stays as
the backstop for backends that don't filter server-side.

### 3.3 Workday backend — `workday.py`

```
https://{tenant}.{datacenter}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs   (POST, no auth)
body: {"limit": 20, "offset": N, "searchText": <from search>, "appliedFacets": {}}
```

1. **List, request-shaped (A).** POST with `searchText` derived from `search` keywords. Offset
   pagination: page until `jobPostings` is empty **or** `offset+limit >= total` **or** the 10k cap /
   a configured page ceiling is hit. Each row → `{title, locationsText, postedOn, externalPath}`.
2. **List-gate (C).** Run a title/location relevance pre-gate on the rows **before** any detail
   request, so descriptions are never fetched for rows the gate will reject. Honor `limit` here.
3. **Detail (N+1, survivors only).** For each surviving row, GET/POST
   `…/wday/cxs/{tenant}/{site}/job/{externalPath}` → `jobPostingInfo.jobDescription` (HTML) →
   `html_to_text`. Build `RawJob(source="workday", url=externalUrl, company=<tenant/site label>,
   title, location, jd_text, posted_at=<startDate/postedOn via parse_iso_datetime>)`.
4. **Fail isolation.** Per-URL try/except like the others; a dead tenant → `failures[url]`.

*v1 facet scope:* request-shaping uses **`searchText` only**. Location/category `appliedFacets` IDs
are tenant-specific (discovered via a separate facets call) and are a **later refinement** (§5).

### 3.4 Tesla backend — `tesla.py` (singleton)

Tesla's careers search is JSON-backed (a `state` lookup payload of all listings + a per-id detail
call). **Exact endpoints confirmed at build time** (§6). Shape: one list call returns all listings
with lookup tables for departments/locations (no server-side search) → **client-side list-gate (C)**
on title/location, then per-id detail for survivors → `jd_text`. `source="tesla"`.

### 3.5 Google backend — `google.py` (singleton)

```
https://careers.google.com/api/v3/search/?q=<query>&page=N    (GET, JSON)
```

Server-side `q` → **request-shaping (A)** from `search`. Paginate by `page` until exhausted/`limit`.
Each job → title, locations, description (HTML → text), apply URL, posted date.
`source="google"`. **Exact path confirmed at build time** (§6).

---

## 4. Config

**Unchanged.** `companies.urls` already accepts arbitrary careers URLs; the unified detector now
routes Workday/Tesla/Google too. Example (no schema change):

```yaml
companies:
  enabled: true
  urls:
    - https://generalmotors.wd5.myworkdayjobs.com/Careers_GM   # workday (tenant·dc·site)
    - https://www.tesla.com/careers                            # tesla singleton
    - https://careers.google.com/jobs/results/                 # google singleton
    - https://jobs.ashbyhq.com/openai                          # already supported
    - https://jobs.lever.co/woven-by-toyota                    # already supported
```

---

## 5. Out of scope (this spec)

- **Generic Playwright + LLM long-tail scrape** (Spec C, deferred).
- **Workday location/category facet IDs.** v1 shapes with `searchText` only; facet discovery is a
  refinement.
- **Source-priority / dedup-merge.** That overlap problem is **Spec B**; this spec only *emits*
  `RawJob`s, it does not change how ingest dedupes them.
- **Auth-walled portals** (Handshake/Interstride — the separate "subsystem A" from 2026-06-17).
- **`dedup_key` location collapse** (noted as a risk in Spec B).

---

## 6. Risks

- **Tesla/Google endpoints are undocumented.** They must be reverse-engineered from the network tab
  and could change without notice. Mitigation: isolate each in its own module behind `_BACKENDS`, fail
  to `failures[url]` (never crash the run), fixture the parser against a captured payload.
- **Workday rate-limiting / IP reputation.** N+1 over many survivors per run; pace requests and keep
  the list-gate aggressive so detail calls stay few. A per-run page ceiling caps worst case.
- **Descriptor change is a refactor.** `AtsTarget(ats, token)` → `AtsTarget(ats, params)` touches the
  three existing backends; covered by the existing connector tests (must stay green).

---

## 7. Acceptance criteria

1. `detect_ats` returns `AtsTarget("workday", {"tenant","datacenter","site"})` with **all three**
   fields from a real Workday URL (e.g. `generalmotors.wd5.myworkdayjobs.com/Careers_GM`).
2. `detect_ats` returns `AtsTarget("tesla", {})` / `AtsTarget("google", {})` by **host match**, with
   precedence over generic L1/L2.
3. Greenhouse/Lever/Ashby still resolve to `AtsTarget(ats, {"token": …})` and fetch through the
   **shared** `fetch_*_board` helpers (one code path, asserted) — no behavior change.
4. Workday backend (fixtured cxs payloads): paginates the list, **list-gates before detail**, issues
   detail requests **only** for survivors, maps to `RawJob`s, honors `limit` and a page ceiling, and
   sends a `searchText` derived from `search`.
5. Tesla and Google backends (fixtured JSON) map to `RawJob`s with correct
   title/location/jd_text/url/posted_at and the right `source`.
6. An unsupported/undetectable/dead URL is recorded in `.failures`, never aborts the run, and other
   URLs still ingest.
7. `relevance_gate` + `.filtered` + `.failures` still surface in `pull` telemetry exactly as today.
8. Full suite green; **no config schema change**; existing connector/config tests unmodified.
