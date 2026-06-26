# Source Manager — Design Spec

**Date:** 2026-06-25
**Status:** Approved (brainstorming) → ready for implementation plan
**Scope decision:** Source Manager first; the config wizard for the other YAML
(`search`, `render`, `review`, …) is a **separate, later spec**.

---

## 1. Problem & goal

Today the list of job sources the user pulls from lives in `config/connectors.yaml`
and is **hand-edited only**. `POST /api/pull` builds **every enabled connector** and
runs them all — there is no way to add/remove a source from the UI, and no way to
pull "just this one board" or re-pull a chosen subset.

The user wants a frontend to:

1. Manage the job-posting URLs / boards they've added (view, add, remove, pause).
2. Pull / re-pull jobs from **one** source or **all** sources.
3. On re-pull, "skip the duplicates" — and *see* that happen.

**Key reframing established during brainstorming:** deduplication on re-pull is
**already solved** at the ingest layer. `save_or_upgrade` / `find_existing`
(`discovery/ingest.py`) match on `company|normalized_title` and either skip an
equal-tier re-pull (first-seen-wins) or upgrade a canonical source **in place**,
never touching user progress. So "skip existing jobs" is **not new behavior to
build** — it is **visibility to surface**: a per-source `added / upgraded /
skipped / failed` breakdown.

## 2. Scope

**In scope**

- A **Sources** page in the web UI (`web/`).
- View all sources (boards/careers URLs + aggregators), unified list.
- Add a source by pasting a URL, with live detection + a bounded test-fetch.
- Remove a source; enable/disable (pause) a source.
- Pull/re-pull: one source, a checkbox selection, or all.
- Live per-source `added / upgraded / skipped / failed` result, streamed over the
  existing run/SSE infrastructure.
- Backend: a sources read/write API over `connectors.yaml`, per-source pull
  selection, and the `skipped` telemetry counter.

**Out of scope (explicit non-goals)**

- The config wizard for `search.yaml` / `render.yaml` / `review.yaml` /
  `profile_sources.yaml` / `prune.yaml` — **separate future spec**.
- The one-off `add_job_from_url` single-posting flow — **stays exactly as is**, a
  separate action; the Source Manager only manages **recurring** sources.
- Migrating sources to a database — `connectors.yaml` remains the single source of
  truth (CLI and UI read/write the same file).
- Preserving YAML comments on write (see §8 decision log).

## 3. Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Build order | **Source Manager first**; config wizard later. |
| 2 | Source of truth | **Write back to `connectors.yaml`** (CLI parity, no migration). |
| 3 | Pull granularity | **Per individual board/URL** (one row = one company/URL). |
| 4 | Add flow | **Recurring sources only**; one-off add-from-URL untouched. |
| 5 | Pull result | **Full per-source breakdown** (added/upgraded/skipped/failed). |
| 6 | Source ops | **Add, Remove, Enable/Disable** per source. |
| 7 | Add validation | **Detect + live test-fetch** before saving. |
| 8 | Aggregators | **Separate "Aggregators" section** (toggle + pull, no add/remove). |
| 9 | YAML writes | **PyYAML, accept comment loss**; migrate the commented-out board
parking-lot into `enabled: false` rows so the backlog survives as data. |

## 4. Data model — changes to `connectors.yaml`

File: `src/resume_agent/discovery/connectors/config.py`

- `GreenhouseBoard`, `LeverBoard`: add `enabled: bool = True`
  (back-compatible — an absent flag means enabled).
- `CompaniesConfig.urls`: change `list[str]` → `list[CompanyUrl]`, where:

  ```python
  class CompanyUrl(ExtensibleModel):
      url: str
      enabled: bool = True
      label: str | None = None   # display name captured at add time
  ```

  A `field_validator("urls", mode="before")` on `CompaniesConfig` coerces a bare
  string `"https://…"` into `{"url": "https://…"}`. **This preserves backward
  compatibility** with existing files and hand-edits that still use a plain list
  of URL strings.

- **Source identity** — a stable id per entry, used by pull-selection,
  `PATCH`, and `DELETE`:
  - `greenhouse:{token}`
  - `lever:{token}`
  - `companies:{sha1(url)[:8]}`
  - fixed ids for aggregators: `adzuna`, `remoteok`, `linkedin`

## 5. Backend

### 5.1 New use-case layer: `services/sources.py`

Mirrors the existing `services/` modules (`discovery`, `board`, …). No business
logic in the router. Responsibilities:

- `list_sources(connectors_path, settings) -> list[SourceView]` — project
  `connectors.yaml` + settings into a unified list. Each item:
  `{id, kind, displayName, enabled, type: "board"|"aggregator", detail}`.
  Aggregators carry derived state: Adzuna `keyPresent` (from `settings`),
  LinkedIn `disabled`.
- `preview_source(url) -> SourcePreview` — run `detect_ats(url)` + a **bounded
  test-fetch** through the existing `harvest`/connector seam. Returns
  `{kind, token|label, company?, openRoleCount, ok|error}`. **No write.**
- `add_source(url, label, connectors_path)` — re-validate, then write to the
  correct YAML section: a Greenhouse/Lever token → its typed `boards` list; any
  other detected ATS (Ashby/Workday/Tesla/Google) or unknown → `companies.urls`.
- `set_enabled(id, enabled, connectors_path)` / `remove_source(id, connectors_path)`.
- All writes are **atomic**: serialize to a temp file, then `os.replace` over the
  target, so a concurrent pull or hand-edit never reads a torn file.

### 5.2 New router: `api/routers/sources.py`

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/api/sources` | — | `SourceView[]` |
| POST | `/api/sources/preview` | `{url}` | `SourcePreview` |
| POST | `/api/sources` | `{url, label?}` | `SourceView` (created) |
| PATCH | `/api/sources/{id}` | `{enabled}` | `SourceView` |
| DELETE | `/api/sources/{id}` | — | `204` |

Schemas live in `api/schemas/sources.py` as `CamelModel`s (camelCase wire format,
the project contract). OpenAPI → `contracts/openapi.json` → `contracts/ts/api.ts`
regenerated via `scripts/gen_ts_client.sh`; `test_openapi_contract.py` drift gate
updated.

### 5.3 Per-source pull — selection as config projection

- Extend `PullParams` (`api/schemas/runs.py`) with `sourceIds: list[str] | None`.
- `pull_jobs` (`services/discovery.py`) gains an optional selector. It **projects**
  `ConnectorsConfig` down to the selected entries, then the **existing**
  `build_connectors` + `run_pull` run unchanged. `sourceIds = None` → pull every
  enabled entry ("pull all").
- **Per-entry fan-out (the main backend change):** to produce the per-board
  breakdown (Decision #5), pull builds **one connector per entry**
  (`GreenhouseConnector([anthropic])`, not one connector holding all boards). Then
  `run_pull`'s existing per-connector loop yields per-board telemetry for free, and
  "pull one" and "pull all" become the **same code path** — just a longer or
  shorter list of single-entry connectors.
  - **Consequence (intentional):** the existing global pull's telemetry
    granularity moves from per-**type** to per-**entry**. `record_run` and the
    telemetry file key on `connector.name`, so connector identity becomes the
    per-entry stable id. This is the highest-risk change; it must be covered by
    tests and called out in the implementation plan.
  - Disabled entries (`enabled: false`) are filtered out during projection, so
    they never produce a connector.

### 5.4 Telemetry — surface `skipped`

- `IngestOutcome.skipped` already exists but is **dropped** —
  `ingest_jobs_with_outcomes` (`discovery/ingest.py`) counts only `inserted` and
  `upgraded`. Add a `skipped: Counter` and include `skipped: dict[str,int]` on
  `IngestCounts`.
- Carry `upgraded` + `skipped` per source on `PullReport` (today it carries only
  `totals` = added and `failures`). Each source row then reports all four numbers.
- Surfaced **live** through the existing `RunManager` / `ProgressReporter` / SSE
  (`/api/runs/{id}/events`) — **no new run infrastructure**. Per-URL fetch failures
  already flow through `FetchResult.failures` and render inline per source row.

## 6. Frontend — `web/src/features/sources/`

- New route `/sources` + nav entry; lazy-loaded in `web/src/app/router.tsx` like
  every other page. Typed client regenerated from OpenAPI.
- **Two sections:**
  - **Boards & careers pages** — rows: display name, ATS badge, enable toggle,
    pull button, remove button, selection checkbox.
  - **Aggregators** — Adzuna / RemoteOK / LinkedIn: toggle + pull, **no
    add/remove**; show "needs API key" (Adzuna, when `.env` keys missing) and
    "disabled / scraper" (LinkedIn) states.
- **Add dialog:** paste URL → live preview (`POST /api/sources/preview`) showing
  detected ATS + open-role count + an editable display name → **Add**.
- **Pull controls:** per-row **Pull**, plus **Pull selected** / **Pull all**.
  Results stream into a per-source live panel reusing the existing run/SSE hook.

```
BOARDS & CAREERS PAGES
[x] Anthropic     Greenhouse  [on]   pull  x
[x] Scale AI      Greenhouse  [off]  pull  x     <- paused (enabled:false)
[x] OpenAI        Ashby       [on]   pull  x
[x] GM Careers    Workday     [on]   pull  x
[ + Add source ]

AGGREGATORS
[x] Adzuna (US)   aggregator  [on]   pull        (key set)
[x] RemoteOK      aggregator  [on]   pull
[ ] LinkedIn      aggregator  [off]  pull        (scraper)

[ Pull selected ]   [ Pull all ]

— after a run (live via SSE) —
Anthropic    +3 added   1 upd   8 skip
Scale AI     +0 added   0 upd  14 skip
OpenAI       +1 added   0 upd   5 skip
GM Careers   FAILED  (httpx timeout)
Adzuna (US)  +2 added   0 upd   9 skip
```

## 7. Error handling

- Reuses the one error envelope `{error: {code, message, details?}}`
  (`api/errors.py`, `ApiException`).
- `POST /preview` failure → friendly "couldn't detect or reach this URL"; the Add
  button stays disabled until a successful preview.
- Per-URL pull failures already surface via `FetchResult.failures`, rendered inline
  on the offending source row.
- Atomic YAML writes (temp + `os.replace`) guard against torn reads from a
  concurrent pull or a hand-edit.

## 8. Decision log / risks

- **Per-entry pull fan-out** (§5.3) is the largest change: it alters the existing
  global pull's telemetry granularity from per-type to per-entry. Intentional;
  must be test-covered.
- **YAML comment loss:** the first UI write flattens `connectors.yaml` comments
  (PyYAML, by user choice). Mitigation: migrate the commented-out board
  parking-lot (Kodiak, Nuro, Divergent, Outrider, …) into real `enabled: false`
  rows so the backlog survives as data rather than comments.
- **Test-fetch on add** adds a network round-trip; for most boards this is a bare
  `httpx` call. A `companies` URL needing the Adzuna-style visible browser is the
  only case that could pop a window — rare on add, and bounded.

## 9. Testing strategy

Offline, matching the existing suite (all agent/browser/network seams faked):

- **Schema back-compat:** a bare-string `urls` list still loads; new `enabled` /
  `CompanyUrl` fields round-trip.
- **Config projection:** a selector resolves to exactly the right single-entry
  connector subset; disabled entries are excluded.
- **`skipped` counting:** `ingest_jobs_with_outcomes` tallies the `skipped`
  outcome; `PullReport` carries added/upgraded/skipped/failed per source.
- **Sources service CRUD** against a temp YAML (add routes to the right section;
  enable/disable; remove; atomic write).
- **Router tests** against the in-memory app (`StaticPool` sqlite), including the
  OpenAPI drift gate.
- **Preview/test-fetch** exercised through the faked connector seam.
- **Web:** a component/e2e smoke test for the Sources page (add dialog preview,
  toggle, pull-selected wiring).
