# React Dashboard — Design Spec

**Date:** 2026-06-22
**Status:** Approved for planning
**Topic:** Replace the Streamlit "Broadsheet" dashboard with a modern React SPA over the FastAPI backend.

---

## 1. Goal & shape

Replace the Streamlit dashboard (`src/resume_agent/dashboard/`) with a **Vite + React + TypeScript SPA** in a new top-level `web/` directory. The SPA consumes the existing FastAPI backend over HTTP + SSE through the already-generated typed client (`contracts/ts/api.ts`). The aesthetic is modern with subtle editorial personality. It reaches **full feature parity** with all five Streamlit pages **and** becomes a control center that launches the long-running operations (`pull` / `discover` / `tailor` / `cover-letters` / add-from-URL) directly.

The SPA is the **fourth thin adapter** over the `services/` use-case layer — parallel to the CLI, Streamlit, and the API — except it reaches the domain *through* the API rather than importing `services/` directly. It introduces **zero new business logic**: even the rich client-side filtering is a direct port of the existing pure functions in `dashboard/filtering.py`.

### Success criteria
- Every capability of the current Streamlit dashboard is reachable in the SPA.
- The SPA launches and live-monitors all run operations via the run/SSE API.
- No business logic lives in the React layer that isn't a verbatim port of an existing pure Python function (with mirrored tests).
- Meets the frontend-ui-engineering bar: WCAG 2.1 AA, real design-system tokens (no AI aesthetic), proper loading/empty/error states, optimistic interactions.

---

## 2. Architecture

```
resume-agent/
  src/resume_agent/api/        FastAPI (existing) + 2 new routers (analytics, match-gap)
  contracts/openapi.json       generated (existing; drift-gated)
  contracts/ts/api.ts          generated typed client (existing)
  web/                         NEW Vite SPA
    src/
      lib/api/                 openapi-fetch client wrapping api.ts; error-envelope unwrap
      lib/filters/             ported filtering / sort / composite-rank engine (+ tests)
      lib/runs/                SSE subscription helper (EventSource)
      features/
        shortlist/             ShortlistContainer + page
        pipeline/              PipelineContainer + page + PipelineCard
        triage/                TriageContainer + page + prune panel
        analytics/             funnel charts + canonical data table
        match-gap/             missing-skill demand
        runs/                  launch actions + live RunPanel
      components/ui/           shadcn primitives (generated)
      components/              shared: JobCard, JobDrawer, FitMeter, StatusBadge,
                               SkillChip, MetricRow, EmptyState, FilterDesk, RunProgressBar
      app/                     router, AppLayout (sidebar+topbar), theme provider, query client
    index.html
    package.json
    vite.config.ts
```

### Data + state layers
- **Server state:** TanStack Query for all reads and mutations.
- **Typed transport:** `openapi-fetch` bound to the generated `api.ts`, for end-to-end type safety against the contract. A single wrapper unwraps the `{ error: { code, message, details? } }` envelope into thrown errors → toasts.
- **Filter state:** URL search params (shareable, back-button-friendly). A `useBoardFilters` hook reads/writes them.
- **Live runs:** a small Zustand store holding active-run records + their SSE-streamed progress.
- **Theme:** React context (light/dark, default = system).

### Serving model
- **Dev:** `vite dev` with a proxy to the uvicorn backend (no CORS friction).
- **Production:** `vite build` emits static assets that **FastAPI mounts and serves**, so `resume-agent serve` hosts API + UI on one port — one command, common case needs no CORS.
- `scripts/gen_ts_client.sh` continues to regenerate the contract; a documented `npm run build` step produces the served bundle.

---

## 3. Backend changes (co-designed contract)

All follow the existing `boards.py` pattern + `CamelModel` (camelCase wire format, snake_case Python, `model_validate` projection). No business logic in routers.

1. **Widen `ShortlistItem`** to whitelist the facet fields already present on the `ShortlistRow` query DTO: `location_country`, `location_region`, `location_city`, `sic_major`, `sic_division`, `sic_label`. Required because filtering moves client-side and an HTTP client can only see whitelisted fields. (Pure projection change — no query work.)
2. **New `GET /api/analytics`** — thin adapter over `tracking/analytics.py` (`source_stats`, `fit_band_stats`) → `AnalyticsOut { bySource: Cohort[], byBand: Cohort[] }`, where `Cohort { label, applications, responses, interviews, offers, interviewRate, offerRate }`.
3. **New `GET /api/match-gap`** — thin adapter over `tracking/match_gap.py` → `MatchGapOut { targetTotal, gaps: Gap[] }`, where `Gap { skill, demandCount, targetTotal, demandShare }`.
4. Regenerate `openapi.json` + `api.ts`; the existing `tests/api/test_openapi_contract.py` drift gate covers the change. New routers get pytest coverage matching the existing router tests.

---

## 4. Information architecture

- **Persistent left sidebar** (shadcn `sidebar`): Shortlist · Pipeline · Triage · Analytics · Match-gap. Collapses to a sheet below 768px.
- **Top bar:** run-launch actions (Pull, Discover, Add job by URL) + a global live-run indicator + theme toggle + token/settings access.
- **Right-side `Sheet` drawer** for single-job detail: opens on any job row/card click, reflects the job id in the URL (`?job=123`) for deep-linking without leaving the board. Contains JD text, criteria, fit rationale, review critiques, resume-version list (PDF download + on-demand render), application editor, and stage/archive/delete actions.

---

## 5. Page-by-page parity

| Page | API source | Carried-over features |
|---|---|---|
| **Shortlist** | `GET /shortlist` (widened) | Full filter desk (≈15 facets), fit/salary/recency/composite sort, composite presets (balanced / pay-first / freshest), fit meter, skill chips, rationale clamp, **Approve for tailoring** |
| **Pipeline** | `GET /pipeline` | Grouped by stage; fit/stage/company sort + text search; PDF download/render; review critiques; application-status editor; set-stage; archive (+ undo); delete-with-confirm |
| **Triage** | `GET /triage` | Show-archived toggle; multi-select with bulk archive / restore / delete; prune panel (preview + run via `POST /prune`); posting-age display |
| **Analytics** | `GET /analytics` (new) | Funnel by source + by fit-band; canonical data table + chart enhancement |
| **Match-gap** | `GET /match-gap` (new) | Most-demanded missing skills, demand share; read-only |

### Ported filter engine (`lib/filters/`)
The composite ranking, salary/recency normalization, the `_passes` facet predicate, location (country→region→city) facet derivation, industry (division→group) grouping, and skill-cloud merging from `dashboard/filtering.py` are ported to TypeScript **verbatim in behavior**, with unit tests mirroring the existing Python tests one-to-one. Constants carried over: `SALARY_CEILING = 250_000`, `RECENCY_WINDOW_DAYS = 30`, `NEUTRAL = 50.0`, and the preset weight tuples.

### Filtering data flow
Each board fetches all rows (`pageSize=200`, paging through if needed), caches them in TanStack Query, and filters/sorts client-side. Facet option lists (available cities, industries, skill cloud) derive from the loaded set — exactly as Streamlit does today.

---

## 6. Run control center + live progress

Top-bar and contextual actions map to the run endpoints:

| Action | Endpoint |
|---|---|
| Pull | `POST /api/pull` |
| Discover | `POST /api/discover` |
| Add job by URL (dialog) | `POST /api/jobs/from-url` |
| Tailor selected (Pipeline/Shortlist selection) | `POST /api/tailor` |
| Generate cover letters (selection) | `POST /api/cover-letters` |

Each launch returns a run id; the UI opens the SSE stream (`GET /api/runs/{id}/events` via `EventSource`) and renders live progress in the `RunPanel` — replacing Streamlit's 2-second poll with true push. On completion, affected TanStack queries invalidate and boards refresh automatically.

---

## 7. Design system — "modern + subtle editorial"

shadcn/ui + Tailwind v4 (the version in `ui/apps/v4`). The palette and type system are **ported from the existing `dashboard/ui.py` `THEME_CSS`** so the UI uses the project's real, deliberate design system rather than a generic AI palette.

| Tailwind token | Existing `ui.py` value | Role |
|---|---|---|
| `background` / `card` | `--paper #f4f1ea` / `--paper-2 #efeae0` | surfaces (light) |
| `foreground` | `--ink #16130f` | primary text |
| `muted-foreground` | `--muted #6c6253` | secondary text |
| `primary` / accent | `--oxblood #8c2f1f` | kickers, the `·`/`/` dots, accents |
| `destructive` | `--danger #9f2f35` | delete / errors |
| `border` | `--rule rgba(22,19,15,.16)` | card borders |
| radius scale | `--radius 8px` / `--radius-sm 4px` | the **entire** radius scale — no `rounded-2xl` |
| fonts | Newsreader / IBM Plex Sans / IBM Plex Mono | display serif (titles) / body / mono eyebrow |

Rules:
- **Borders over shadows** (mirrors the existing `1px solid var(--rule)` cards); shadows only where shadcn specifies for overlays.
- **Editorial restraint:** kicker eyebrow labels ("Human checkpoint", "Mission control") above serif page titles; the human-checkpoint copy voice is retained from the parity copy.
- **Dark mode is net-new:** `ui.py` is light-only, so dark-mode counterparts for each token must be derived (called out as new work, not a port). Default = system.
- Reusable primitives (`FitMeter`, `StatusBadge`, `SkillChip`, `MetricRow`, `EmptyState`, `JobCard`, `JobDrawer`, `RunProgressBar`) are descendants of the `ui.py` helpers.

---

## 8. Accessibility (WCAG 2.1 AA — mandatory)

- **Radix/shadcn primitives** handle focus-trap, Esc-to-close, and focus-return for Sheet/Dialog, plus correct Checkbox/Select semantics. Custom markup must not regress this.
- **Color is never the sole signal:** FitMeter renders the numeric score; StatusBadge and the sponsorship signal carry **text labels**, not just amber/oxblood color.
- **Live run progress:** `role="progressbar"` + `aria-valuenow` inside an `aria-live="polite"` region so screen readers announce progress and completion.
- **Analytics charts:** the data **table is the canonical representation** (SR-accessible); the chart is a visual enhancement.
- **Heading hierarchy:** one `h1` per page = the serif page title; the **kicker is an eyebrow label, not a heading**; drawer rail-heads ("Job description", "Application", "Manage") are real `h2`/`h3`. No skipped levels.
- **Forms:** every input in the drawer (application status, notes, stage) uses `<label htmlFor>` association; triage bulk-select checkboxes keep an accessible name (today's collapsed "Select").
- **Keyboard:** every interactive element is a real `<button>`/control and reachable by Tab; the full sidebar→board→drawer flow is keyboard-operable.

---

## 9. Cross-cutting

- **Auth:** optional bearer token (matches `Settings.api_token`); stored in `localStorage`, set via a settings dialog, attached to every request; on `401`, prompt for it. No-op when the backend runs tokenless.
- **Errors:** one transport-layer place unwraps the `{ error: { code, message } }` envelope into toasts.
- **Loading:** shadcn skeletons for every board and the drawer (the `ui/apps/v4` skeleton cards are direct references) — never content spinners.
- **Optimistic updates:** frequent mutations (Approve, Set stage, Archive, Application status) use TanStack Query `onMutate` + rollback for instant feedback. Destructive operations (Delete, Prune) stay confirm-then-refetch, not optimistic.
- **Component-size discipline:** pages are thin compositions; any unit approaching ~200 lines is split. Container/presentation split is explicit (e.g. `ShortlistContainer` fetches + filters + handles states, renders pure `BoardGrid`/`JobCard`), keeping prop-drilling ≤3 levels and presentation unit-testable without the network.
- **Performance:** fetch-all per board (pageSize 200) cached by TanStack Query; filtering memoized; list virtualization only if a board exceeds ~300 rows.

---

## 10. Responsive stance

**Desktop-first with graceful degradation** (this is a localhost single-user control room). Below 768px the sidebar collapses to a sheet, the filter desk stacks, and card grids become single-column — **layout integrity is maintained at 320 / 768 / 1024 / 1440**, but touch/mobile interactions are not separately optimized. If real phone/tablet use emerges, mobile is promoted to first-class in a follow-up.

---

## 11. Testing

- **Filter engine:** Vitest unit tests ported 1:1 from the existing Python filter tests.
- **Components:** React Testing Library; MSW to mock the API.
- **Accessibility:** **axe-core** automated assertions in Vitest/Playwright; a keyboard tab-through smoke test. Contrast, breakpoint, and no-console-error checks are merge gates.
- **End-to-end:** Playwright smoke for the core flow — load → filter → approve → open drawer → launch run (mocked SSE).
- **Backend:** new analytics/match-gap routers get pytest coverage like existing routers; the contract drift gate already exists.

---

## 12. Rollout / Streamlit retirement

Keep Streamlit in place until the SPA reaches parity, then remove `src/resume_agent/dashboard/` and its dependencies in a final cleanup commit. The CLI and API are untouched throughout.

---

## 13. Out of scope

Gmail sync, profile-build UI, LinkedIn scrape (all deferred in the backend too). No multi-user / accounts — single-user localhost tool. No mobile-first optimization (see §10).
