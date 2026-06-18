# Company Careers-Page Connector (ATS detection) — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation
**Surface:** `discovery/connectors/` (new `companies` connector + `detect.py` + Ashby backend),
`discovery/connectors/config.py` (new `CompaniesConfig`), `discovery/connectors/registry.py`
(registration), shared board-fetch helpers lifted out of `greenhouse.py` / `lever.py`.

> This is **subsystem B** of a three-part upgrade brainstormed on 2026-06-17. The three parts are
> independent design→plan→build cycles:
> - **A** — Handshake / Interstride auth-walled connectors (LinkedIn pattern). *Standalone, later.*
> - **B** — Company careers-page → many listings via ATS detection. *This spec.*
> - **C** — Application autofill / submission assist. *Rides on B's ATS detection; later.*
>
> B is first because it is the highest-leverage, lowest-risk piece and it builds the ATS-detection
> spine that C later reuses.

---

## 1. Problem & Goal

Today there are two ingestion shapes:

- **Recurring connectors** (`pull` runs them every time): Greenhouse + Lever by *board token* in
  `config/connectors.yaml`, Adzuna by API, LinkedIn by Playwright scrape.
- **One-off `addjob`**: paste a *single* posting URL → `url_ingest` fetches one page → one `RawJob`.

There is no way to say "watch *this company's* careers page and pull all its current openings every
run." The user must already know a board *token* (`acme` in `boards.greenhouse.io/acme`) to add a
company to the recurring funnel — but what they actually have in hand is a **careers-page URL**, and
they do not know or care which ATS sits behind it.

**Goal:** let the user drop a company **careers URL** into config and have every `pull` re-scrape
all of that company's current openings — auto-detecting the ATS and reusing the robust JSON backends
already in the codebase. No board-token archaeology, no per-company custom scraper.

**Key architectural observation:** most tech-company careers pages are not custom — they are
Greenhouse, Lever, Ashby, or Workday under a vanity skin. Detecting the ATS collapses "scrape any
company" from *N brittle scrapers* into *one detector + a handful of structured backends*. That
detector is also the spine subsystem **C** (application autofill) will reuse, since knowing it is a
Greenhouse form tells you how to fill it.

---

## 2. Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Usage model | **Recurring config list** — careers URLs live in `connectors.yaml`; every `pull` re-scrapes them. (Not a one-off command.) |
| Long-tail policy | **Known-ATS only in v1.** Unrecognized pages report "unsupported — no known ATS detected" rather than guessing. The generic Playwright+LLM listing scrape is a **deferred** later increment. |
| v1 backends | **Greenhouse + Lever + Ashby** fetch natively. **Workday** is *detected* but returns "recognized, not yet supported" — a clean future hook with no cost now. |
| Detection depth | **L1 (URL pattern) + L2 (one HTTP GET + HTML sniff). No Playwright in v1.** Fully fixture-testable. L3 browser render-sniff is deferred with the generic fallback. |
| Config shape | **New `companies:` URL list that coexists** with existing token-based `greenhouse`/`lever` config. Zero migration. The two paths share the same underlying board fetchers internally. |
| Browser in v1 | **None.** Known-ATS backends are JSON over HTTP; Playwright's real home is the deferred generic fallback. |
| Reuse | GH/Lever board fetch lifted into shared helpers so the token-config connectors **and** the new connector call **one** code path. |
| Degradation | **Per-URL fail isolation**, matching Greenhouse/Lever: one dead/unsupported/undetectable URL is recorded in `.failures` and skipped; the rest still ingest. |

---

## 3. Architecture

A new `CompaniesConnector` (`name = "companies"`) implementing the existing `Connector` protocol
(`fetch(search, limit) -> list[RawJob]`). For each configured careers URL:

```
                ┌──────────── per URL, isolated ────────────┐
url ─▶ detect_ats(url) ─▶ AtsTarget(ats, token) ─▶ backend.fetch(token)
                │   L1 URL pattern → L2 GET+sniff           │ ─▶ parse_* ─▶ RawJob[]
                │   miss ─▶ failures[url]="no known ATS"     │
                │   workday ─▶ failures[url]="not yet supp." │
                └────────────────────────────────────────────┘
                                   │
        all RawJobs ─▶ relevance_gate(search) ─▶ return (sets .filtered)
```

The connector exposes `.failures: dict[str,str]` and `.filtered: int` exactly like
`GreenhouseConnector`/`LeverConnector`, so `run_pull`'s telemetry (`_run_note`) and the `pull` CLI's
"skipped N dead source(s)" line work **unchanged**. It registers in `registry.py` after the existing
ATS connectors; `pull` discovers it automatically when `companies.enabled` is true.

### 3.1 Detection — `discovery/connectors/detect.py`

```python
@dataclass(frozen=True)
class AtsTarget:
    ats: str        # "greenhouse" | "lever" | "ashby" | "workday"
    token: str      # board token / org slug

def detect_ats(url: str, *, client: httpx.Client | None = None) -> AtsTarget | None: ...
```

- **L1 — URL pattern (pure, no network).** Match host + path:
  - `boards.greenhouse.io/{token}`, `job-boards.greenhouse.io/{token}` → greenhouse
  - `jobs.lever.co/{token}` → lever
  - `jobs.ashbyhq.com/{token}` → ashby
  - `{tenant}.{dc}.myworkdayjobs.com/...` → workday
- **L2 — one HTTP GET + HTML sniff** (only if L1 misses). Fetch the page once, regex the raw HTML
  for embed markers:
  - Greenhouse: `grnhse_app`, `boards.greenhouse.io/embed/job_board?for={token}`
  - Lever: `jobs.lever.co/{token}` script/iframe src
  - Ashby: `jobs.ashbyhq.com/{org}` iframe/script src, or `__ASHBY` board markers
  - Workday: any `*.myworkdayjobs.com` reference
  Token is captured from the marker.
- **Miss** → `None`. L2's GET is wrapped; a network error is treated as "undetectable" (fail-open).

Detection is deterministic and fixture-testable: L1 needs no network; L2 is exercised with saved
HTML snippets.

### 3.2 Backends — `discovery/connectors/companies.py` (dispatch)

| ATS | Fetch | Parse | Source of truth |
|---|---|---|---|
| greenhouse | `fetch_greenhouse_board(token)` (shared) | `parse_greenhouse` (existing) | reuse |
| lever | `fetch_lever_board(token)` (shared) | `parse_lever` (existing) | reuse |
| ashby | `fetch_ashby_board(token)` (new) | `parse_ashby` (new) | new |
| workday | — | — | detected-only → `failures[url]` |

**Shared lift.** The 2-line httpx calls currently inlined as `GreenhouseConnector._get_board` /
`LeverConnector._get_board` move to module-level `fetch_greenhouse_board(token)` /
`fetch_lever_board(token)` in `greenhouse.py` / `lever.py`. Both the existing token-config connectors
and `CompaniesConnector` call them — **one** code path, asserted in tests.

**Ashby (new).** `GET https://api.ashbyhq.com/posting-api/job-board/{org}` returns `{"jobs": [...]}`.
`parse_ashby(payload, company)` maps each: `title` → title, `location` → location,
`descriptionPlain` (fallback `html_to_text(descriptionHtml)`) → jd_text, `jobUrl` → url,
`publishedAt` → posted_at (ISO via existing `parse_iso_datetime`). `source="ashby"`.

Company display name for `RawJob.company`: derived from the token (or an optional per-URL label if we
later add one); keep it simple in v1 — token-derived.

### 3.3 Relevance gate & limit

After collecting all URLs' `RawJob`s, run the existing `relevance_gate(jobs, search)` and set
`self.filtered = before - len(kept)`, mirroring Greenhouse/Lever. Honor `limit` by slicing the final
list, same as the others. We pull the **whole** board per company and let the relevance gate +
`search.yaml` narrow — on-page ATS filters are not honored (out of scope).

---

## 4. Config changes (`ConnectorsConfig` / `connectors.yaml`)

New section, additive, default-off:

```yaml
companies:
  enabled: false
  urls:
    - https://careers.somestartup.com       # auto-detected via L2 sniff
    - https://boards.greenhouse.io/acme      # direct board URL works too
    - https://jobs.ashbyhq.com/someorg
```

```python
class CompaniesConfig(ExtensibleModel):
    enabled: bool = False
    urls: list[str] = Field(default_factory=list)

class ConnectorsConfig(ExtensibleModel):
    ...
    companies: CompaniesConfig = Field(default_factory=CompaniesConfig)
```

`registry.build_connectors`: append `CompaniesConnector(config.companies.urls)` when
`config.companies.enabled and config.companies.urls`. Existing sections untouched — **no migration**.

---

## 5. Out of scope (v1)

- **Generic Playwright + LLM listing scrape** for non-ATS / custom careers pages. Deferred increment;
  this is where Playwright (and the L3 render-sniff) will live.
- **Workday fetching.** Detected-only in v1 (tenant discovery + `cxs` POST API + pagination is a
  separate effort).
- **On-page filter honoring.** We fetch the full board; narrowing is the relevance gate's job.
- **Resolved-token persistence** across runs. Detection runs in-process per `pull`; no cache file.
- Any change to extract / `apply_filters` / fit scoring — this connector sits entirely upstream, same
  as every other source.

---

## 6. Acceptance criteria

1. `detect_ats` resolves direct Greenhouse, Lever, and Ashby URLs by **pattern alone** (no network),
   returning the right `(ats, token)`.
2. `detect_ats` resolves an **embedded Greenhouse** custom-domain page via the L2 HTML sniff
   (fixtured HTML), capturing the token from the embed marker.
3. A **Workday** URL detects as `workday`; the connector reports
   `failures[url] = "Workday recognized, not yet supported"` and never crashes.
4. An **undetectable** URL is recorded in `.failures` ("no known ATS detected"), does not abort the
   run, and other URLs in the list still ingest.
5. **Ashby** payload (fixtured) maps to `RawJob`s with correct title/location/jd_text/url/posted_at.
6. Greenhouse and Lever fetches in `CompaniesConnector` go through the **shared**
   `fetch_greenhouse_board` / `fetch_lever_board` helpers that the token-config connectors now also
   call (one code path, asserted).
7. `relevance_gate` still applies; `.filtered` and `.failures` surface in `pull` telemetry exactly
   like the existing ATS connectors.
8. Full suite stays green; no existing connector, config, or test requires changes.
