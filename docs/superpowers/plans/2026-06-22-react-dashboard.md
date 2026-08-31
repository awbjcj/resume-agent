# React Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit dashboard with a Vite + React + TypeScript SPA in `web/` that reaches full feature parity over the FastAPI backend and adds a run control center.

**Architecture:** The SPA is the fourth thin adapter over `services/`, reaching the domain through the existing API (HTTP + SSE) via the generated typed client. Filtering is a verbatim TypeScript port of `dashboard/filtering.py` running client-side over fetch-all board data. Two new read-only API endpoints (analytics, match-gap) and a widened `ShortlistItem` close the contract gap. Design tokens are ported from `dashboard/ui.py`.

**Tech Stack:** FastAPI + Pydantic (backend, existing); Vite, React 19, TypeScript, Tailwind v4, shadcn/ui, TanStack Query, openapi-fetch, Zustand, Vitest + React Testing Library + MSW, Playwright + axe-core.

**Reference spec:** `docs/superpowers/specs/2026-06-22-react-dashboard-design.md`

**Conventions for every task below:**

- Backend tests: `.venv/Scripts/python.exe -m pytest <path> -v`; lint: `ruff check`.
- Web tests: `cd web && npm run test -- --run <path>`.
- Commit after each task with the message shown. Work on the current branch `feat/migrate-to-api-backend`.
- Commit message footer (append to EVERY commit):

  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01X5xupHcqViNoSABNeMwcQC
  ```

---

## Phase 0 — Backend contract prep

### Task 0.1: Widen `ShortlistItem` schema with facet fields

**Files:**

- Modify: `src/resume_tailor_harness/api/schemas/jobs.py:17-34`
- Test: `tests/api/test_boards.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/api/test_boards.py`:

```python
def test_shortlist_item_exposes_facet_fields(client, seeded_session):
    # seeded_session must contain at least one shortlisted job with location + sic data.
    resp = client.get("/api/shortlist")
    assert resp.status_code == 200
    item = resp.json()["data"][0]
    # camelCase wire format
    for key in ("locationCountry", "locationRegion", "locationCity",
                "sicMajor", "sicDivision", "sicLabel"):
        assert key in item
```

If `seeded_session`/`client` fixtures differ in this file, reuse the existing fixtures already used by the other tests in `tests/api/test_boards.py` (do not invent new ones — read the top of the file first).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_boards.py::test_shortlist_item_exposes_facet_fields -v`
Expected: FAIL with `KeyError`/assertion — keys absent.

- [ ] **Step 3: Add the fields to the schema**

In `src/resume_tailor_harness/api/schemas/jobs.py`, add to `ShortlistItem` (after `skills: list[SkillTagOut]`):

```python
    sic_major: str | None = None
    sic_label: str | None = None
    sic_division: str | None = None
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
```

No mapper change is needed: `ShortlistItem.model_validate(row)` reads these snake_case attributes off the `ShortlistRow` DTO (defined in `tracking/queries.py:54-60`), which already populates them.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_boards.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/schemas/jobs.py tests/api/test_boards.py
git commit -m "feat(api): widen ShortlistItem with location + sic facet fields"
```

---

### Task 0.2: Analytics schemas

**Files:**

- Create: `src/resume_tailor_harness/api/schemas/analytics.py`
- Test: `tests/api/test_schemas_analytics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_schemas_analytics.py`:

```python
from resume_tailor_harness.api.schemas.analytics import AnalyticsOut, CohortOut
from resume_tailor_harness.tracking.analytics import CohortStat


def test_cohort_out_projects_rates_from_dto():
    dto = CohortStat(label="greenhouse", applications=10, responses=4, interviews=2, offers=1)
    out = CohortOut.model_validate(dto)
    assert out.label == "greenhouse"
    assert out.applications == 10
    assert out.interview_rate == 20  # derived property on the dataclass
    assert out.offer_rate == 10


def test_cohort_out_serializes_camelcase():
    dto = CohortStat(label="x", applications=1, responses=0, interviews=0, offers=0)
    body = CohortOut.model_validate(dto).model_dump(by_alias=True)
    assert "interviewRate" in body and "offerRate" in body and "responseRate" in body


def test_analytics_out_holds_two_cohort_lists():
    out = AnalyticsOut(by_source=[], by_band=[])
    assert out.model_dump(by_alias=True) == {"bySource": [], "byBand": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_analytics.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the schema**

Create `src/resume_tailor_harness/api/schemas/analytics.py`:

```python
"""Analytics API schemas: conversion cohorts by source and fit-band."""

from __future__ import annotations

from resume_tailor_harness.api.schemas.base import CamelModel


class CohortOut(CamelModel):
    label: str
    applications: int
    responses: int
    interviews: int
    offers: int
    response_rate: int
    interview_rate: int
    offer_rate: int


class AnalyticsOut(CamelModel):
    by_source: list[CohortOut]
    by_band: list[CohortOut]
```

`CohortStat` (`tracking/analytics.py`) exposes `response_rate`/`interview_rate`/`offer_rate` as `@property`; `from_attributes=True` on `CamelModel` reads them like fields.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_analytics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/schemas/analytics.py tests/api/test_schemas_analytics.py
git commit -m "feat(api): add analytics cohort schemas"
```

---

### Task 0.3: Analytics router

**Files:**

- Create: `src/resume_tailor_harness/api/routers/analytics.py`
- Modify: `src/resume_tailor_harness/api/app.py:14-18,71-75`
- Test: `tests/api/test_analytics.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_analytics.py` (reuse the `client`/session fixtures from `tests/api/conftest.py`):

```python
def test_analytics_endpoint_returns_source_and_band(client):
    resp = client.get("/api/analytics")
    assert resp.status_code == 200
    body = resp.json()
    assert "bySource" in body and "byBand" in body
    assert isinstance(body["bySource"], list)
    assert isinstance(body["byBand"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_analytics.py -v`
Expected: FAIL — 404 (route absent).

- [ ] **Step 3: Create the router and register it**

Create `src/resume_tailor_harness/api/routers/analytics.py`:

```python
"""Read-only conversion analytics: by source and by fit-band."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.schemas.analytics import AnalyticsOut, CohortOut
from resume_tailor_harness.tracking.analytics import fit_band_stats, source_stats

router = APIRouter()


@router.get("/analytics", response_model=AnalyticsOut)
def get_analytics(session: Session = Depends(get_session)):
    return AnalyticsOut(
        by_source=[CohortOut.model_validate(c) for c in source_stats(session)],
        by_band=[CohortOut.model_validate(c) for c in fit_band_stats(session)],
    )
```

In `src/resume_tailor_harness/api/app.py`, add the import alongside the other routers:

```python
from resume_tailor_harness.api.routers import analytics as analytics_router
```

and register it (in the guarded block, after the runs router):

```python
    app.include_router(analytics_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_analytics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/analytics.py src/resume_tailor_harness/api/app.py tests/api/test_analytics.py
git commit -m "feat(api): add GET /api/analytics router"
```

---

### Task 0.4: Match-gap schemas

**Files:**

- Create: `src/resume_tailor_harness/api/schemas/match_gap.py`
- Test: `tests/api/test_schemas_match_gap.py`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_schemas_match_gap.py`:

```python
from resume_tailor_harness.api.schemas.match_gap import GapOut, MatchGapOut
from resume_tailor_harness.tracking.match_gap import GapRow


def test_gap_out_projects_demand_share():
    dto = GapRow(skill="Kubernetes", demand_count=3, target_total=4)
    out = GapOut.model_validate(dto)
    assert out.skill == "Kubernetes"
    assert out.demand_count == 3
    assert out.demand_share == 75  # derived property


def test_gap_out_serializes_camelcase():
    body = GapOut.model_validate(GapRow(skill="Go", demand_count=1, target_total=2)).model_dump(by_alias=True)
    assert set(body) == {"skill", "demandCount", "targetTotal", "demandShare"}


def test_match_gap_out_shape():
    out = MatchGapOut(target_total=0, gaps=[])
    assert out.model_dump(by_alias=True) == {"targetTotal": 0, "gaps": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_match_gap.py -v`
Expected: FAIL — module absent.

- [ ] **Step 3: Create the schema**

Create `src/resume_tailor_harness/api/schemas/match_gap.py`:

```python
"""Match-gap API schemas: missing-skill demand across target jobs."""

from __future__ import annotations

from resume_tailor_harness.api.schemas.base import CamelModel


class GapOut(CamelModel):
    skill: str
    demand_count: int
    target_total: int
    demand_share: int


class MatchGapOut(CamelModel):
    target_total: int
    gaps: list[GapOut]
```

`GapRow` exposes `demand_share` as a `@property`; `from_attributes` reads it.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_match_gap.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/schemas/match_gap.py tests/api/test_schemas_match_gap.py
git commit -m "feat(api): add match-gap schemas"
```

---

### Task 0.5: Match-gap router

**Files:**

- Create: `src/resume_tailor_harness/api/routers/match_gap.py`
- Modify: `src/resume_tailor_harness/api/app.py`
- Test: `tests/api/test_match_gap.py`

The domain function `match_gap(session, facts)` needs `ProfileFacts`. Load them from `data/profile/facts.json` via `resume_tailor_harness.profile.store.load_facts`; when the file is absent, return an empty report (parity with the Streamlit page's "No profile yet" guard).

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_match_gap.py`:

```python
def test_match_gap_without_profile_returns_empty(client):
    # No facts.json in the isolated test root -> empty report, 200.
    resp = client.get("/api/match-gap")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"targetTotal": 0, "gaps": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_match_gap.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Create the router and register it**

Create `src/resume_tailor_harness/api/routers/match_gap.py`:

```python
"""Read-only match-gap: skills target jobs demand that the profile lacks."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.schemas.match_gap import GapOut, MatchGapOut
from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.tracking.match_gap import match_gap

router = APIRouter()

_FACTS_PATH = "data/profile/facts.json"


@router.get("/match-gap", response_model=MatchGapOut)
def get_match_gap(session: Session = Depends(get_session)):
    if not Path(_FACTS_PATH).exists():
        return MatchGapOut(target_total=0, gaps=[])
    report = match_gap(session, load_facts(_FACTS_PATH))
    return MatchGapOut(
        target_total=report.target_total,
        gaps=[GapOut.model_validate(g) for g in report.gaps],
    )
```

Register in `src/resume_tailor_harness/api/app.py`:

```python
from resume_tailor_harness.api.routers import match_gap as match_gap_router
```

```python
    app.include_router(match_gap_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_match_gap.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/match_gap.py src/resume_tailor_harness/api/app.py tests/api/test_match_gap.py
git commit -m "feat(api): add GET /api/match-gap router"
```

---

### Task 0.6: Serve the built SPA from FastAPI

**Files:**

- Modify: `src/resume_tailor_harness/api/app.py`
- Test: `tests/api/test_static_spa.py`

Mount `web/dist` as static files at `/` when the directory exists, with SPA fallback (unknown non-`/api` paths return `index.html`). Absent build dir → no mount (tests/dev without a build still pass).

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_static_spa.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app


def test_spa_served_when_dist_exists(tmp_path, monkeypatch):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    monkeypatch.setattr("resume_tailor_harness.api.app.spa_dist_dir", lambda: dist)
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        # API still works
        assert client.get("/api/health").status_code == 200
        # Deep link falls back to index.html
        deep = client.get("/pipeline")
        assert deep.status_code == 200
        assert "<title>app</title>" in deep.text


def test_no_spa_mount_without_dist(tmp_path, monkeypatch):
    monkeypatch.setattr("resume_tailor_harness.api.app.spa_dist_dir", lambda: tmp_path / "missing")
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/pipeline").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_static_spa.py -v`
Expected: FAIL — `spa_dist_dir` undefined / no fallback.

- [ ] **Step 3: Implement the mount**

In `src/resume_tailor_harness/api/app.py`, add near the top:

```python
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def spa_dist_dir() -> Path:
    # repo_root/web/dist — app.py is src/resume_tailor_harness/api/app.py
    return Path(__file__).resolve().parents[3] / "web" / "dist"
```

At the END of `create_app`, just before `return app`:

```python
    dist = spa_dist_dir()
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            # API + docs are registered before this catch-all and take precedence.
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_static_spa.py tests/api/test_app_health.py -v`
Expected: PASS (health unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/app.py tests/api/test_static_spa.py
git commit -m "feat(api): serve built SPA from web/dist with SPA fallback"
```

---

### Task 0.7: Regenerate the OpenAPI contract + TS client

**Files:**

- Modify (generated): `contracts/openapi.json`, `contracts/ts/api.ts`
- Test: `tests/api/test_openapi_contract.py` (existing drift gate)

- [ ] **Step 1: Regenerate**

Run: `bash scripts/gen_ts_client.sh`
Expected: writes `contracts/openapi.json` and `contracts/ts/api.ts`; the new `/api/analytics`, `/api/match-gap`, and widened `ShortlistItem` appear.

- [ ] **Step 2: Verify the drift gate passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 3: Run the full backend suite + lint**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q && ruff check`
Expected: PASS, no lint errors.

- [ ] **Step 4: Commit**

```bash
git add contracts/openapi.json contracts/ts/api.ts
git commit -m "chore(contracts): regenerate after analytics/match-gap + shortlist facets"
```

---

## Phase 1 — Web scaffold

### Task 1.1: Scaffold the Vite app

**Files:** Create `web/` (Vite React-TS template).

- [ ] **Step 1: Scaffold**

Run:

```bash
cd D:/Fun/resume-tailor-harness
npm create vite@latest web -- --template react-ts
cd web && npm install
```

- [ ] **Step 2: Add a `.gitignore`**

Create `web/.gitignore`:

```
node_modules
dist
*.local
.vite
coverage
playwright-report
test-results
```

- [ ] **Step 3: Verify dev server boots**

Run: `cd web && npm run build`
Expected: a `dist/` is produced without errors.

- [ ] **Step 4: Commit**

```bash
git add web
git commit -m "chore(web): scaffold Vite React-TS app"
```

---

### Task 1.2: Tailwind v4 + shadcn init + ported design tokens

**Files:** Modify `web/vite.config.ts`, create `web/src/index.css`, `web/components.json`, `web/tsconfig` path aliases.

- [ ] **Step 1: Install Tailwind v4 + deps**

Run:

```bash
cd web
npm install tailwindcss @tailwindcss/vite class-variance-authority clsx tailwind-merge lucide-react
npm install -D @types/node
```

- [ ] **Step 2: Configure Vite (Tailwind plugin + `@` alias + API proxy)**

Replace `web/vite.config.ts`:

```ts
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
```

Add to `web/tsconfig.app.json` under `compilerOptions`:

```json
"baseUrl": ".",
"paths": { "@/*": ["./src/*"] }
```

- [ ] **Step 3: Write the theme tokens (ported from `dashboard/ui.py`)**

Replace `web/src/index.css`:

```css
@import "tailwindcss";

@theme {
  --font-sans: "IBM Plex Sans", ui-sans-serif, system-ui, sans-serif;
  --font-serif: "Newsreader", Georgia, serif;
  --font-mono: "IBM Plex Mono", ui-monospace, monospace;
  --radius: 8px;
  --radius-sm: 4px;
}

:root {
  --background: #f4f1ea; /* --paper */
  --card: #efeae0; /* --paper-2 */
  --foreground: #16130f; /* --ink */
  --muted-foreground: #6c6253; /* --muted */
  --primary: #8c2f1f; /* --oxblood */
  --destructive: #9f2f35; /* --danger */
  --border: rgba(22, 19, 15, 0.16); /* --rule */
}

.dark {
  --background: #16130f;
  --card: #1f1b16;
  --foreground: #f4f1ea;
  --muted-foreground: #a89a85;
  --primary: #c8553d; /* lightened oxblood for contrast on dark */
  --destructive: #d4565b;
  --border: rgba(244, 241, 234, 0.16);
}

body {
  background: var(--background);
  color: var(--foreground);
  font-family: var(--font-sans);
}
```

Import the three Google fonts in `web/index.html` `<head>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link
  href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600;6..72,700&family=IBM+Plex+Mono:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap"
  rel="stylesheet"
/>
```

- [ ] **Step 4: Init shadcn**

Run:

```bash
cd web && npx --yes shadcn@latest init -d
```

When prompted (or via `-d` defaults), select the **Neutral** base color; we override colors via the CSS above. Confirm `components.json` was created and `@/components`/`@/lib/utils` resolve.

- [ ] **Step 5: Add the shadcn primitives used throughout**

Run:

```bash
cd web && npx --yes shadcn@latest add button card badge sheet dialog alert-dialog input label select checkbox slider table tabs skeleton sidebar separator switch dropdown-menu accordion collapsible sonner chart tooltip progress scroll-area
```

(`toast` is deprecated in favor of `sonner` — do not add it. `alert-dialog`, `tooltip`, `progress`, and `scroll-area` back the user-friendly components in Tasks 1.4, 3.4, 3.5, 6.2.)

- [ ] **Step 6: Verify build**

Run: `cd web && npm run build`
Expected: builds clean.

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "chore(web): Tailwind v4 + shadcn with tokens ported from ui.py"
```

---

### Task 1.3: API client wrapper (openapi-fetch + error envelope + auth)

**Files:** Create `web/src/lib/api/client.ts`, `web/src/lib/api/types.ts`; copy contract.

- [ ] **Step 1: Install openapi-fetch and copy the contract type**

Run:

```bash
cd web && npm install openapi-fetch
mkdir -p src/lib/api
cp ../contracts/ts/api.ts src/lib/api/schema.ts
```

(Document in `scripts/gen_ts_client.sh` later that the file is also copied to `web/src/lib/api/schema.ts`; handled in Task 8.4.)

- [ ] **Step 2: Write the failing test**

Create `web/src/lib/api/client.test.ts`:

```ts
import { describe, expect, it, beforeEach } from "vitest";
import { getToken, setToken, unwrap } from "./client";

describe("token storage", () => {
  beforeEach(() => localStorage.clear());
  it("round-trips the bearer token", () => {
    expect(getToken()).toBeNull();
    setToken("abc");
    expect(getToken()).toBe("abc");
  });
});

describe("unwrap", () => {
  it("returns data when present", async () => {
    const r = await unwrap(
      Promise.resolve({ data: { ok: 1 }, error: undefined } as any),
    );
    expect(r).toEqual({ ok: 1 });
  });
  it("throws the error envelope message", async () => {
    const env = {
      error: { error: { code: "NOT_FOUND", message: "nope" } },
      data: undefined,
    };
    await expect(unwrap(Promise.resolve(env as any))).rejects.toThrow("nope");
  });
});
```

(Vitest setup added in Task 1.5; if running this task first, install vitest+jsdom now: `npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event`.)

- [ ] **Step 3: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/lib/api/client.test.ts`
Expected: FAIL — `./client` not found.

- [ ] **Step 4: Implement the client**

Create `web/src/lib/api/client.ts`:

```ts
import createClient from "openapi-fetch";
import type { paths } from "./schema";

const TOKEN_KEY = "resume-tailor-harness-token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export const api = createClient<paths>({ baseUrl: "/" });

api.use({
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

type ErrorEnvelope = {
  error?: { code: string; message: string; details?: unknown };
};

/** Unwrap an openapi-fetch result, throwing the API error-envelope message. */
export async function unwrap<T>(
  p: Promise<{ data?: T; error?: ErrorEnvelope | unknown }>,
): Promise<T> {
  const { data, error } = await p;
  if (error) {
    const env = error as ErrorEnvelope;
    throw new Error(env?.error?.message ?? "Request failed");
  }
  return data as T;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/lib/api/client.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/api web/package.json web/package-lock.json
git commit -m "feat(web): typed API client with auth + error-envelope unwrap"
```

---

### Task 1.4: App shell — providers, router, theme, layout

**Files:** Create `web/src/app/{providers.tsx,router.tsx,AppLayout.tsx,theme.tsx}`, rewrite `web/src/main.tsx`, `web/src/App.tsx`.

- [ ] **Step 1: Install router + query**

Run: `cd web && npm install @tanstack/react-query react-router-dom zustand`

- [ ] **Step 2: Theme provider**

Create `web/src/app/theme.tsx`:

```tsx
import { createContext, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark" | "system";
const ThemeContext = createContext<{
  theme: Theme;
  setTheme: (t: Theme) => void;
}>({
  theme: "system",
  setTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme) ?? "system",
  );
  useEffect(() => {
    const root = document.documentElement;
    const dark =
      theme === "dark" ||
      (theme === "system" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    root.classList.toggle("dark", dark);
    localStorage.setItem("theme", theme);
  }, [theme]);
  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}
export const useTheme = () => useContext(ThemeContext);
```

- [ ] **Step 3: Providers + query client**

Create `web/src/app/providers.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "./theme";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: false },
  },
});

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
      </ThemeProvider>
      <Toaster richColors position="top-right" />
    </QueryClientProvider>
  );
}
```

- [ ] **Step 4: Layout with sidebar + topbar**

Create `web/src/app/AppLayout.tsx`:

```tsx
import { NavLink, Outlet } from "react-router-dom";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { RunActions } from "@/features/runs/RunActions";
import { RunPanel } from "@/features/runs/RunPanel";
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV = [
  { to: "/", label: "Shortlist", end: true },
  { to: "/pipeline", label: "Pipeline" },
  { to: "/triage", label: "Triage" },
  { to: "/analytics", label: "Analytics" },
  { to: "/match-gap", label: "Match-gap" },
];

export function AppLayout() {
  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="p-4">
          <div className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--primary)]">
            Résumé Tailor Harness
          </div>
          <div className="font-serif text-2xl font-bold leading-tight">
            The Broadsheet
          </div>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.map((n) => (
                  <SidebarMenuItem key={n.to}>
                    {/* asChild keeps a single interactive element (the NavLink) — no
                        button-inside-anchor nesting. NavLink sets aria-current="page". */}
                    <SidebarMenuButton asChild>
                      <NavLink to={n.to} end={n.end}>
                        {n.label}
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
      </Sidebar>
      <SidebarInset>
        <header className="flex items-center gap-3 border-b border-[var(--border)] px-6 py-3">
          {/* Mobile trigger opens the sidebar as a sheet; hidden once the rail is docked. */}
          <SidebarTrigger className="md:hidden" />
          <RunActions />
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>
        <RunPanel />
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
```

Active-link styling: NavLink sets `aria-current="page"` on the active route; add to `web/src/index.css`:

```css
[data-sidebar="menu-button"][aria-current="page"] {
  background: var(--card);
  font-weight: 600;
}
```

(`RunActions`, `RunPanel`, `ThemeToggle` are stubbed now and implemented in later tasks. Create one-line placeholder components returning `null` so the build passes; replace in Phase 6 / below.)

Create `web/src/components/ThemeToggle.tsx`:

```tsx
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTheme } from "@/app/theme";

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Toggle theme"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        >
          <Sun className="h-4 w-4 dark:hidden" />
          <Moon className="hidden h-4 w-4 dark:block" />
        </Button>
      </TooltipTrigger>
      <TooltipContent>Toggle light / dark</TooltipContent>
    </Tooltip>
  );
}
```

Create placeholders `web/src/features/runs/RunActions.tsx` and `RunPanel.tsx`:

```tsx
export function RunActions() {
  return null;
}
```

```tsx
export function RunPanel() {
  return null;
}
```

- [ ] **Step 5: Router + main**

Create `web/src/app/router.tsx`:

```tsx
import { createBrowserRouter } from "react-router-dom";
import { AppLayout } from "./AppLayout";
import { ShortlistPage } from "@/features/shortlist/ShortlistPage";
import { PipelinePage } from "@/features/pipeline/PipelinePage";
import { TriagePage } from "@/features/triage/TriagePage";
import { AnalyticsPage } from "@/features/analytics/AnalyticsPage";
import { MatchGapPage } from "@/features/match-gap/MatchGapPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <ShortlistPage /> },
      { path: "pipeline", element: <PipelinePage /> },
      { path: "triage", element: <TriagePage /> },
      { path: "analytics", element: <AnalyticsPage /> },
      { path: "match-gap", element: <MatchGapPage /> },
    ],
  },
]);
```

Create each page as a placeholder returning `<div>` with its name (replaced in later phases), e.g. `web/src/features/shortlist/ShortlistPage.tsx`:

```tsx
export function ShortlistPage() {
  return <div>Shortlist</div>;
}
```

(Repeat for Pipeline, Triage, Analytics, MatchGap with their own names.)

Replace `web/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { Providers } from "./app/providers";
import { router } from "./app/router";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </React.StrictMode>,
);
```

Delete `web/src/App.tsx`, `web/src/App.css` if present.

- [ ] **Step 6: Verify build + manual smoke**

Run: `cd web && npm run build`
Expected: builds clean. Then `npm run dev` shows the sidebar with five nav links routing to placeholder pages.

- [ ] **Step 7: Commit**

```bash
git add web/src
git commit -m "feat(web): app shell — providers, router, theme, layout"
```

---

### Task 1.5: Test harness (Vitest + RTL + MSW)

**Files:** Create `web/vitest.config.ts`, `web/src/test/setup.ts`, `web/src/test/server.ts`, modify `web/package.json` scripts.

- [ ] **Step 1: Install**

Run:

```bash
cd web && npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event msw @vitest/coverage-v8 vitest-axe
```

- [ ] **Step 2: Vitest config**

Create `web/vitest.config.ts`:

```ts
import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
```

- [ ] **Step 3: Setup + MSW server**

Create `web/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
```

Create `web/src/test/server.ts`:

```ts
import { setupServer } from "msw/node";
export const server = setupServer();
```

- [ ] **Step 4: package.json scripts**

In `web/package.json` `"scripts"` add:

```json
"test": "vitest",
"test:run": "vitest run",
"e2e": "playwright test"
```

- [ ] **Step 5: Verify**

Run: `cd web && npm run test -- --run src/lib/api/client.test.ts`
Expected: PASS (the Task 1.3 test now runs under the configured harness).

- [ ] **Step 6: Commit**

```bash
git add web
git commit -m "chore(web): vitest + RTL + MSW + axe harness"
```

---

## Phase 2 — Ported filter engine

### Task 2.1: Types + skill normalization

**Files:** Create `web/src/lib/filters/types.ts`, `web/src/lib/filters/normalize.ts`, `web/src/lib/filters/normalize.test.ts`.

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/filters/normalize.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { normalizeSkill } from "./normalize";

describe("normalizeSkill (port of match_gap.normalize_skill)", () => {
  it("lowercases, drops punctuation, collapses whitespace", () => {
    expect(normalizeSkill("  Node.JS / TypeScript!! ")).toBe(
      "node.js typescript",
    );
    expect(normalizeSkill("C++")).toBe("c++");
    expect(normalizeSkill("C#")).toBe("c#");
    expect(normalizeSkill("Go-lang")).toBe("go lang");
  });
});
```

The Python regex keeps `a-z0-9+#.` and space, replacing other runs with a single space, then collapses whitespace and trims.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/lib/filters/normalize.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `web/src/lib/filters/normalize.ts`:

```ts
// Port of resume_tailor_harness.tracking.match_gap.normalize_skill
const PUNCT = /[^a-z0-9+#. ]+/g;
const WS = /\s+/g;

export function normalizeSkill(skill: string): string {
  return skill.toLowerCase().replace(PUNCT, " ").replace(WS, " ").trim();
}
```

Create `web/src/lib/filters/types.ts`:

```ts
import type { components } from "@/lib/api/schema";

export type ShortlistItem = components["schemas"]["ShortlistItem"];
export type SkillTag = components["schemas"]["SkillTagOut"];

export type SortKey = "fit" | "salary" | "recency" | "composite";
export type Preset = "balanced" | "pay_first" | "freshest";

export interface FilterState {
  salaryMin: number | null;
  remote: Set<string>;
  sponsorship: Set<string>;
  seniority: Set<string>;
  employmentType: Set<string>;
  industry: Set<string>;
  country: Set<string>;
  region: Set<string>;
  city: Set<string>;
  companySize: Set<string>;
  fitMin: number | null;
  skills: Set<string>;
  sort: SortKey;
  preset: Preset;
}

export function emptyFilterState(): FilterState {
  return {
    salaryMin: null,
    remote: new Set(),
    sponsorship: new Set(),
    seniority: new Set(),
    employmentType: new Set(),
    industry: new Set(),
    country: new Set(),
    region: new Set(),
    city: new Set(),
    companySize: new Set(),
    fitMin: null,
    skills: new Set(),
    sort: "fit",
    preset: "balanced",
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/lib/filters/normalize.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/filters
git commit -m "feat(web): filter types + skill normalization (port)"
```

---

### Task 2.2: `applyFilters` predicate

**Files:** Create `web/src/lib/filters/apply.ts`, `web/src/lib/filters/apply.test.ts`.

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/filters/apply.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { applyFilters } from "./apply";
import { emptyFilterState, type ShortlistItem } from "./types";

const base = (over: Partial<ShortlistItem> = {}): ShortlistItem =>
  ({
    jobId: 1,
    company: "Acme",
    title: "Eng",
    location: "NYC",
    fitScore: 70,
    fitRationale: null,
    sponsorshipSignal: null,
    salaryMin: null,
    salaryMax: 120000,
    salaryCurrency: "USD",
    remotePolicy: "remote",
    seniority: "senior",
    employmentType: "full_time",
    industry: "tech",
    companySize: "large",
    postedAt: null,
    skills: [],
    sicMajor: "73",
    sicLabel: "Services",
    sicDivision: "I",
    locationCountry: "US",
    locationRegion: "NY",
    locationCity: "New York",
    ...over,
  }) as ShortlistItem;

describe("applyFilters (port of filtering._passes)", () => {
  it("filters by USD salary max below salaryMin", () => {
    const rows = [
      base({ salaryMax: 90000 }),
      base({ jobId: 2, salaryMax: 150000 }),
    ];
    const s = { ...emptyFilterState(), salaryMin: 100000 };
    expect(applyFilters(rows, s).map((r) => r.jobId)).toEqual([2]);
  });
  it("does NOT gate non-USD salaries", () => {
    const rows = [base({ salaryMax: 10, salaryCurrency: "JPY" })];
    const s = { ...emptyFilterState(), salaryMin: 100000 };
    expect(applyFilters(rows, s)).toHaveLength(1);
  });
  it("gates by fitMin only when score present", () => {
    const rows = [base({ fitScore: 50 }), base({ jobId: 2, fitScore: null })];
    const s = { ...emptyFilterState(), fitMin: 60 };
    expect(applyFilters(rows, s).map((r) => r.jobId)).toEqual([2]);
  });
  it("multi-select facets keep rows with null value (neutral)", () => {
    const rows = [
      base({ remotePolicy: null }),
      base({ jobId: 2, remotePolicy: "onsite" }),
    ];
    const s = { ...emptyFilterState(), remote: new Set(["remote"]) };
    // null is neutral (kept); 'onsite' not in selection (dropped)
    expect(applyFilters(rows, s).map((r) => r.jobId)).toEqual([1]);
  });
  it("skills require any-token overlap", () => {
    const rows = [
      base({ skills: [{ name: "Go", covered: false, required: true }] }),
      base({
        jobId: 2,
        skills: [{ name: "Rust", covered: false, required: true }],
      }),
    ];
    const s = { ...emptyFilterState(), skills: new Set(["go"]) };
    expect(applyFilters(rows, s).map((r) => r.jobId)).toEqual([1]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/lib/filters/apply.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement (port of `_passes`)**

Create `web/src/lib/filters/apply.ts`:

```ts
import { normalizeSkill } from "./normalize";
import type { FilterState, ShortlistItem } from "./types";

function passes(row: ShortlistItem, s: FilterState): boolean {
  if (s.salaryMin !== null && row.salaryMax != null) {
    const currency = (row.salaryCurrency ?? "USD").toUpperCase();
    if (currency === "USD" && row.salaryMax < s.salaryMin) return false;
  }
  if (s.fitMin !== null && row.fitScore != null && row.fitScore < s.fitMin)
    return false;

  const facets: [Set<string>, string | null | undefined][] = [
    [s.remote, row.remotePolicy],
    [s.sponsorship, row.sponsorshipSignal],
    [s.seniority, row.seniority],
    [s.employmentType, row.employmentType],
    [s.industry, row.sicMajor],
    [s.country, row.locationCountry],
    [s.region, row.locationRegion],
    [s.city, row.locationCity],
    [s.companySize, row.companySize],
  ];
  for (const [selected, value] of facets) {
    if (selected.size && value != null && !selected.has(value)) return false;
  }

  if (s.skills.size) {
    const tokens = new Set(row.skills.map((t) => normalizeSkill(t.name)));
    let overlap = false;
    for (const t of s.skills)
      if (tokens.has(t)) {
        overlap = true;
        break;
      }
    if (!overlap) return false;
  }
  return true;
}

export function applyFilters(
  rows: ShortlistItem[],
  s: FilterState,
): ShortlistItem[] {
  return rows.filter((r) => passes(r, s));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/lib/filters/apply.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/filters
git commit -m "feat(web): applyFilters predicate (port of _passes)"
```

---

### Task 2.3: `sortRows` + `compositeScore`

**Files:** Create `web/src/lib/filters/sort.ts`, `web/src/lib/filters/sort.test.ts`.

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/filters/sort.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { compositeScore, sortRows } from "./sort";
import { emptyFilterState, type ShortlistItem } from "./types";

const NOW = new Date("2026-06-22T00:00:00Z");
const row = (over: Partial<ShortlistItem>): ShortlistItem =>
  ({
    jobId: 0,
    salaryMin: null,
    salaryMax: null,
    salaryCurrency: "USD",
    fitScore: null,
    postedAt: null,
    skills: [],
    ...over,
  }) as ShortlistItem;

describe("compositeScore (port of filtering.composite_score)", () => {
  it("uses NEUTRAL 50 for missing fit/salary/recency under balanced", () => {
    expect(compositeScore(row({}), "balanced", NOW)).toBe(50);
  });
  it("clamps future-dated recency to 100, not above", () => {
    const future = new Date(NOW.getTime() + 10 * 86400000).toISOString();
    const s = compositeScore(
      row({ postedAt: future, fitScore: 50 }),
      "freshest",
      NOW,
    );
    expect(s).toBeLessThanOrEqual(100);
  });
});

describe("sortRows", () => {
  it("sorts by fit desc with nulls last", () => {
    const rows = [
      row({ jobId: 1, fitScore: 40 }),
      row({ jobId: 2, fitScore: null }),
      row({ jobId: 3, fitScore: 90 }),
    ];
    const out = sortRows(rows, { ...emptyFilterState(), sort: "fit" }, NOW);
    expect(out.map((r) => r.jobId)).toEqual([3, 1, 2]);
  });
  it("sorts by salary desc using salaryMax then salaryMin", () => {
    const rows = [
      row({ jobId: 1, salaryMax: 100 }),
      row({ jobId: 2, salaryMin: 200 }),
      row({ jobId: 3, salaryMax: null }),
    ];
    const out = sortRows(rows, { ...emptyFilterState(), sort: "salary" }, NOW);
    expect(out.map((r) => r.jobId)).toEqual([2, 1, 3]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/lib/filters/sort.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement (port of `composite_score` + `sort_rows`)**

Create `web/src/lib/filters/sort.ts`:

```ts
import type { FilterState, Preset, ShortlistItem } from "./types";

const SALARY_CEILING = 250_000;
const RECENCY_WINDOW_DAYS = 30;
const NEUTRAL = 50.0;
const PRESETS: Record<Preset, [number, number, number]> = {
  balanced: [0.5, 0.3, 0.2],
  pay_first: [0.3, 0.55, 0.15],
  freshest: [0.35, 0.2, 0.45],
};

function salaryValue(r: ShortlistItem): number | null {
  return r.salaryMax != null ? r.salaryMax : r.salaryMin;
}
function ageDays(r: ShortlistItem, now: Date): number | null {
  if (!r.postedAt) return null;
  return (now.getTime() - new Date(r.postedAt).getTime()) / 86_400_000;
}

export function compositeScore(
  r: ShortlistItem,
  preset: Preset,
  now: Date,
): number {
  const [wFit, wSalary, wRecency] = PRESETS[preset] ?? PRESETS.balanced;
  const fitN = r.fitScore != null ? r.fitScore : NEUTRAL;
  const salary = salaryValue(r);
  const salaryN =
    salary != null
      ? (Math.min(salary, SALARY_CEILING) / SALARY_CEILING) * 100
      : NEUTRAL;
  const age = ageDays(r, now);
  const recencyN =
    age != null
      ? Math.min(100, Math.max(0, 100 - (age / RECENCY_WINDOW_DAYS) * 100))
      : NEUTRAL;
  return (
    Math.round(
      (wFit * fitN + wSalary * salaryN + wRecency * recencyN) * 10000,
    ) / 10000
  );
}

// Mirror Python's reverse-sorted tuple keys with a comparator.
export function sortRows(
  rows: ShortlistItem[],
  s: FilterState,
  now: Date = new Date(),
): ShortlistItem[] {
  const arr = [...rows];
  if (s.sort === "salary") {
    return arr.sort((a, b) => {
      const av = salaryValue(a),
        bv = salaryValue(b);
      return Number(bv != null) - Number(av != null) || (bv ?? 0) - (av ?? 0);
    });
  }
  if (s.sort === "recency") {
    return arr.sort((a, b) => {
      const aa = ageDays(a, now),
        ba = ageDays(b, now);
      return (
        Number(!!b.postedAt) - Number(!!a.postedAt) ||
        Number(ba != null) - Number(aa != null) ||
        (aa ?? 0) - (ba ?? 0) // smaller age first => -(age) reverse in Python
      );
    });
  }
  if (s.sort === "composite") {
    return arr.sort(
      (a, b) =>
        compositeScore(b, s.preset, now) - compositeScore(a, s.preset, now),
    );
  }
  // fit (default)
  return arr.sort((a, b) => {
    return (
      Number(b.fitScore != null) - Number(a.fitScore != null) ||
      (b.fitScore ?? 0) - (a.fitScore ?? 0)
    );
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/lib/filters/sort.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/filters
git commit -m "feat(web): sortRows + compositeScore (port)"
```

---

### Task 2.4: Facet derivation (`availableCountries/States/Cities/Industries/SkillCloud`)

**Files:** Create `web/src/lib/filters/facets.ts`, `web/src/lib/filters/facets.test.ts`.

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/filters/facets.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  availableCities,
  availableCountries,
  availableSkillCloud,
  availableStates,
} from "./facets";
import type { ShortlistItem } from "./types";

const r = (o: Partial<ShortlistItem>): ShortlistItem =>
  ({ skills: [], ...o }) as ShortlistItem;

describe("location facets (port of filtering.available_*)", () => {
  const rows = [
    r({
      locationCountry: "US",
      locationRegion: "NY",
      locationCity: "New York",
    }),
    r({
      locationCountry: "US",
      locationRegion: "CA",
      locationCity: "San Jose",
    }),
    r({ locationCountry: "UK", locationRegion: null, locationCity: "London" }),
  ];
  it("countries are sorted + unique", () => {
    expect(availableCountries(rows)).toEqual(["UK", "US"]);
  });
  it("states honor the selected-country filter", () => {
    expect(availableStates(rows, new Set(["US"]))).toEqual(["CA", "NY"]);
  });
  it("cities honor country + state filters", () => {
    expect(availableCities(rows, new Set(["US"]), new Set(["NY"]))).toEqual([
      "New York",
    ]);
  });
});

describe("availableSkillCloud", () => {
  it("merges by normalized token, covered/required OR-ed, covered-first (matches Python key)", () => {
    const rows = [
      r({ skills: [{ name: "Go", covered: false, required: true }] }),
      r({ skills: [{ name: "go", covered: true, required: false }] }),
      r({ skills: [{ name: "Rust", covered: false, required: false }] }),
    ];
    const cloud = availableSkillCloud(rows);
    const go = cloud.find((t) => t.name.toLowerCase() === "go")!;
    expect(go.covered).toBe(true);
    expect(go.required).toBe(true);
    // Python key is (not covered, name): covered=True -> (False, ...) sorts FIRST.
    expect(cloud[0].name).toBe("Go");
    expect(cloud[1].name).toBe("Rust");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/lib/filters/facets.test.ts`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement (port of facet helpers)**

Create `web/src/lib/filters/facets.ts`:

```ts
import { normalizeSkill } from "./normalize";
import type { ShortlistItem, SkillTag } from "./types";

const uniqSorted = (vals: (string | null | undefined)[]): string[] =>
  [...new Set(vals.filter((v): v is string => !!v))].sort();

export function availableCountries(rows: ShortlistItem[]): string[] {
  return uniqSorted(rows.map((r) => r.locationCountry));
}

export function availableStates(
  rows: ShortlistItem[],
  countries: Set<string>,
): string[] {
  return uniqSorted(
    rows
      .filter(
        (r) =>
          !countries.size ||
          (r.locationCountry && countries.has(r.locationCountry)),
      )
      .map((r) => r.locationRegion),
  );
}

export function availableCities(
  rows: ShortlistItem[],
  countries: Set<string>,
  states: Set<string>,
): string[] {
  return uniqSorted(
    rows
      .filter(
        (r) =>
          !countries.size ||
          (r.locationCountry && countries.has(r.locationCountry)),
      )
      .filter(
        (r) =>
          !states.size || (r.locationRegion && states.has(r.locationRegion)),
      )
      .map((r) => r.locationCity),
  );
}

/** [(divisionLabel, [[code, label], ...]), ...] grouped + sorted, port of available_industries. */
export function availableIndustries(
  rows: ShortlistItem[],
): [string, [string, string][]][] {
  const byDiv = new Map<string, Set<string>>(); // division -> set of "code\x00label"
  for (const r of rows) {
    if (r.sicMajor && r.sicDivision && r.sicLabel) {
      const set = byDiv.get(r.sicDivision) ?? new Set();
      set.add(`${r.sicMajor} ${r.sicLabel}`);
      byDiv.set(r.sicDivision, set);
    }
  }
  return [...byDiv.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([div, codes]) => [
      div,
      [...codes]
        .map((c) => c.split(" ") as [string, string])
        .sort((a, b) => a[0].localeCompare(b[0])),
    ]);
}

export function availableSkillCloud(rows: ShortlistItem[]): SkillTag[] {
  const merged = new Map<string, SkillTag>();
  for (const r of rows) {
    for (const tag of r.skills) {
      const token = normalizeSkill(tag.name);
      if (!token) continue;
      const existing = merged.get(token);
      if (!existing) merged.set(token, { ...tag });
      else {
        existing.covered = existing.covered || tag.covered;
        existing.required = existing.required || tag.required;
      }
    }
  }
  return [...merged.values()].sort((a, b) => {
    // Python key is (not covered, name.lower()) ascending: covered (False) sorts FIRST.
    const ac = a.covered ? 0 : 1;
    const bc = b.covered ? 0 : 1;
    return ac - bc || a.name.toLowerCase().localeCompare(b.name.toLowerCase());
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/lib/filters/facets.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/filters
git commit -m "feat(web): facet derivation helpers (port of available_*)"
```

---

## Phase 3 — Shared primitives

### Task 3.1: `FitMeter` + `StatusBadge` + `SkillChip`

**Files:** Create `web/src/components/{FitMeter,StatusBadge,SkillChip}.tsx` and colocated tests.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/FitMeter.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FitMeter } from "./FitMeter";

describe("FitMeter", () => {
  it("shows the numeric score (color is never the sole signal)", () => {
    render(<FitMeter score={72} />);
    expect(screen.getByText("72")).toBeInTheDocument();
  });
  it("renders an em dash when score is null", () => {
    render(<FitMeter score={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
  it("exposes an accessible label", () => {
    render(<FitMeter score={50} />);
    expect(screen.getByLabelText(/fit score 50/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/components/FitMeter.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `web/src/components/FitMeter.tsx`:

```tsx
export function FitMeter({ score }: { score: number | null }) {
  const label = score == null ? "no fit score" : `fit score ${score}`;
  return (
    <div className="flex flex-col items-center" aria-label={label}>
      <span className="font-serif text-2xl font-bold leading-none">
        {score ?? "—"}
      </span>
      <span className="font-mono text-[0.6rem] uppercase tracking-widest text-[var(--muted-foreground)]">
        fit
      </span>
    </div>
  );
}
```

Create `web/src/components/StatusBadge.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";

export function StatusBadge({ status }: { status: string }) {
  // text label always present; color is supplementary
  return (
    <Badge
      variant="outline"
      className="font-mono text-[0.65rem] uppercase tracking-wider"
    >
      {status.replace(/_/g, " ")}
    </Badge>
  );
}
```

Create `web/src/components/SkillChip.tsx`:

```tsx
export function SkillChip({
  name,
  active,
}: {
  name: string;
  active?: boolean;
}) {
  return (
    <span
      className={`inline-block rounded-[var(--radius-sm)] border border-[var(--border)] px-2 py-0.5 text-xs ${
        active
          ? "bg-[var(--primary)] text-white"
          : "text-[var(--muted-foreground)]"
      }`}
    >
      {name}
    </span>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/components/FitMeter.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components
git commit -m "feat(web): FitMeter, StatusBadge, SkillChip primitives"
```

---

### Task 3.2: `MetricRow` + `EmptyState`

**Files:** Create `web/src/components/{MetricRow,EmptyState}.tsx` + tests.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/EmptyState.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("renders a status region with title + body", () => {
    render(
      <EmptyState title="Nothing here" body="Run a pull to ingest jobs." />,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    expect(screen.getByText(/Run a pull/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/components/EmptyState.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `web/src/components/EmptyState.tsx`:

```tsx
export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div role="status" className="py-12 text-center">
      <h3 className="font-serif text-lg font-semibold">{title}</h3>
      <p className="mt-1 text-sm text-[var(--muted-foreground)]">{body}</p>
    </div>
  );
}
```

Create `web/src/components/MetricRow.tsx`:

```tsx
export function MetricRow({ items }: { items: [string, string][] }) {
  return (
    <div className="mb-6 flex flex-wrap gap-3">
      {items.map(([label, value]) => (
        <div
          key={label}
          className="min-w-[150px] flex-1 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4"
        >
          <div className="font-serif text-2xl font-bold leading-none">
            {value}
          </div>
          <div className="mt-2 font-mono text-[0.7rem] uppercase tracking-widest text-[var(--muted-foreground)]">
            {label}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/components/EmptyState.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components
git commit -m "feat(web): MetricRow + EmptyState primitives"
```

---

### Task 3.3: `PageHeader` (kicker eyebrow + serif title)

**Files:** Create `web/src/components/PageHeader.tsx` + test.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/PageHeader.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("title is the single h1; kicker is NOT a heading", () => {
    render(
      <PageHeader
        kicker="Human checkpoint"
        title="The Shortlist"
        sub="Approve keepers."
      />,
    );
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("The Shortlist");
    // kicker text exists but not as a heading
    expect(screen.getByText("Human checkpoint").tagName).not.toMatch(
      /^H[1-6]$/,
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/components/PageHeader.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `web/src/components/PageHeader.tsx`:

```tsx
export function PageHeader({
  kicker,
  title,
  sub,
}: {
  kicker: string;
  title: string;
  sub?: string;
}) {
  return (
    <header className="mb-6 border-b-2 border-[var(--foreground)] pb-4">
      <p className="font-mono text-xs uppercase tracking-[0.3em] text-[var(--primary)]">
        {kicker}
      </p>
      <h1 className="font-serif text-4xl font-bold leading-tight">{title}</h1>
      {sub && (
        <p className="mt-2 max-w-[70ch] text-[var(--muted-foreground)]">
          {sub}
        </p>
      )}
    </header>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/components/PageHeader.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components
git commit -m "feat(web): PageHeader (eyebrow kicker + serif h1)"
```

---

### Task 3.4: Content-shaped skeletons

**Files:** Create `web/src/components/skeletons.tsx` + test. Models the per-card skeleton pattern from `ui/apps/v4/.../cards/skeleton/*` (skeletons echo the real layout instead of a single grey block).

- [ ] **Step 1: Write the failing test**

Create `web/src/components/skeletons.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BoardSkeleton } from "./skeletons";

describe("BoardSkeleton", () => {
  it("is announced as busy to assistive tech", () => {
    render(<BoardSkeleton />);
    expect(screen.getByLabelText(/loading/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/components/skeletons.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `web/src/components/skeletons.tsx`:

```tsx
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function JobCardSkeleton() {
  return (
    <Card className="flex gap-4 p-4">
      <Skeleton className="h-12 w-10 rounded-md" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-5 w-2/3 rounded-md" />
        <Skeleton className="h-4 w-1/2 rounded-md" />
        <div className="flex gap-1 pt-1">
          <Skeleton className="h-5 w-12 rounded-full" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-10 rounded-full" />
        </div>
      </div>
    </Card>
  );
}

export function BoardSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div
      aria-busy="true"
      aria-label="Loading jobs"
      className="grid grid-cols-1 gap-4 xl:grid-cols-2"
    >
      {Array.from({ length: count }).map((_, i) => (
        <JobCardSkeleton key={i} />
      ))}
    </div>
  );
}

export function DrawerSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading job" className="mt-8 space-y-3">
      <Skeleton className="h-7 w-2/3 rounded-md" />
      <Skeleton className="h-4 w-1/2 rounded-md" />
      <Skeleton className="mt-6 h-40 w-full rounded-lg" />
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/components/skeletons.test.tsx`
Expected: PASS.

- [ ] **Step 5: Replace the generic loaders**

In every board container (`ShortlistContainer`, `PipelineContainer`, `TriageContainer`, `AnalyticsContainer`, `MatchGapContainer`) replace `<Skeleton className="h-64 w-full" />` with `<BoardSkeleton />` and import it from `@/components/skeletons`. In `JobDrawer`, replace `<Skeleton className="mt-8 h-96 w-full" />` with `<DrawerSkeleton />`. (When implementing the later tasks, use these from the start rather than the generic block.)

- [ ] **Step 6: Commit**

```bash
git add web/src/components
git commit -m "feat(web): content-shaped skeletons (board + drawer)"
```

---

### Task 3.5: `ConfirmDialog` (accessible destructive confirm)

**Files:** Create `web/src/components/ConfirmDialog.tsx` + test. Replaces `window.confirm` with a focus-trapped, keyboard-dismissible shadcn `AlertDialog` (the spec's "delete-with-confirm" intent, done accessibly).

- [ ] **Step 1: Write the failing test**

Create `web/src/components/ConfirmDialog.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("fires onConfirm only after the confirm action", async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        trigger={<button>Delete</button>}
        title="Delete job?"
        description="This cannot be undone."
        confirmLabel="Confirm delete"
        onConfirm={onConfirm}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: /confirm delete/i }),
    );
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/components/ConfirmDialog.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

Create `web/src/components/ConfirmDialog.tsx`:

```tsx
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel = "Confirm",
  onConfirm,
}: {
  trigger: React.ReactNode;
  title: string;
  description: string;
  confirmLabel?: string;
  onConfirm: () => void;
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/components/ConfirmDialog.test.tsx`
Expected: PASS.

- [ ] **Step 5: Use it for every destructive action**

When implementing Tasks 4.5 (Triage "Delete selected"), 4.5 PrunePanel ("Prune now"), and 5.1 StageManager ("Delete"), wrap the destructive button in `ConfirmDialog` instead of calling `window.confirm(...)`. Example for StageManager delete:

```tsx
<ConfirmDialog
  trigger={
    <Button variant="destructive" disabled={job.hasProgress}>
      Delete
    </Button>
  }
  title="Delete this job?"
  description="This cannot be undone."
  confirmLabel="Confirm delete"
  onConfirm={() => {
    del.mutate(job.id);
    onDeleted();
  }}
/>
```

- [ ] **Step 6: Commit**

```bash
git add web/src/components
git commit -m "feat(web): accessible ConfirmDialog for destructive actions"
```

---

## Phase 4 — Boards

### Task 4.1: Board query hooks

**Files:** Create `web/src/features/shortlist/use-shortlist.ts`, `web/src/features/pipeline/use-pipeline.ts`, `web/src/features/triage/use-triage.ts`.

These fetch-all (pageSize 200) and return `{ data, isLoading, error }`. Each uses `api.GET` + `unwrap`.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/shortlist/use-shortlist.test.tsx`:

```tsx
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { useShortlist } from "./use-shortlist";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useShortlist", () => {
  it("returns the fetched rows", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [{ jobId: 1, company: "Acme", title: "Eng", skills: [] }],
          pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
        }),
      ),
    );
    const { result } = renderHook(() => useShortlist(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data?.[0].jobId).toBe(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/shortlist/use-shortlist.test.tsx`
Expected: FAIL — hook missing.

- [ ] **Step 3: Implement the three hooks**

Create `web/src/features/shortlist/use-shortlist.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";
import type { ShortlistItem } from "@/lib/filters/types";

export function useShortlist() {
  return useQuery({
    queryKey: ["shortlist"],
    queryFn: async (): Promise<ShortlistItem[]> => {
      const page = await unwrap(
        api.GET("/api/shortlist", { params: { query: { pageSize: 200 } } }),
      );
      return (page as { data: ShortlistItem[] }).data;
    },
  });
}
```

Create `web/src/features/pipeline/use-pipeline.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type PipelineItem = components["schemas"]["PipelineItem"];

export function usePipeline() {
  return useQuery({
    queryKey: ["pipeline"],
    queryFn: async (): Promise<PipelineItem[]> => {
      const page = await unwrap(
        api.GET("/api/pipeline", { params: { query: { pageSize: 200 } } }),
      );
      return (page as { data: PipelineItem[] }).data;
    },
  });
}
```

Create `web/src/features/triage/use-triage.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type TriageItem = components["schemas"]["TriageItem"];

export function useTriage(archived: boolean) {
  return useQuery({
    queryKey: ["triage", archived],
    queryFn: async (): Promise<TriageItem[]> => {
      const page = await unwrap(
        api.GET("/api/triage", {
          params: { query: { archived, pageSize: 200 } },
        }),
      );
      return (page as { data: TriageItem[] }).data;
    },
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/shortlist/use-shortlist.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features
git commit -m "feat(web): board query hooks (fetch-all)"
```

---

### Task 4.2: `useBoardFilters` URL-state hook

**Files:** Create `web/src/features/shortlist/use-board-filters.ts` + test.

Serializes `FilterState` to/from URL search params so filters are shareable.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/shortlist/use-board-filters.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { paramsToState, stateToParams } from "./use-board-filters";
import { emptyFilterState } from "@/lib/filters/types";

describe("filter URL serialization", () => {
  it("round-trips a populated state", () => {
    const s = {
      ...emptyFilterState(),
      fitMin: 70,
      sort: "composite" as const,
      preset: "pay_first" as const,
      remote: new Set(["remote", "hybrid"]),
      skills: new Set(["go"]),
    };
    const round = paramsToState(stateToParams(s));
    expect(round.fitMin).toBe(70);
    expect(round.sort).toBe("composite");
    expect(round.preset).toBe("pay_first");
    expect([...round.remote].sort()).toEqual(["hybrid", "remote"]);
    expect([...round.skills]).toEqual(["go"]);
  });
  it("empty state produces no params", () => {
    expect(stateToParams(emptyFilterState()).toString()).toBe("");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/shortlist/use-board-filters.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `web/src/features/shortlist/use-board-filters.ts`:

```ts
import { useSearchParams } from "react-router-dom";
import { useMemo } from "react";
import {
  emptyFilterState,
  type FilterState,
  type Preset,
  type SortKey,
} from "@/lib/filters/types";

const SET_KEYS = [
  "remote",
  "sponsorship",
  "seniority",
  "employmentType",
  "industry",
  "country",
  "region",
  "city",
  "companySize",
  "skills",
] as const;

export function stateToParams(s: FilterState): URLSearchParams {
  const p = new URLSearchParams();
  if (s.salaryMin != null) p.set("salaryMin", String(s.salaryMin));
  if (s.fitMin != null) p.set("fitMin", String(s.fitMin));
  if (s.sort !== "fit") p.set("sort", s.sort);
  if (s.preset !== "balanced") p.set("preset", s.preset);
  for (const k of SET_KEYS) {
    const set = s[k];
    if (set.size) p.set(k, [...set].join(","));
  }
  return p;
}

export function paramsToState(p: URLSearchParams): FilterState {
  const s = emptyFilterState();
  const salary = p.get("salaryMin");
  const fit = p.get("fitMin");
  if (salary) s.salaryMin = Number(salary);
  if (fit) s.fitMin = Number(fit);
  if (p.get("sort")) s.sort = p.get("sort") as SortKey;
  if (p.get("preset")) s.preset = p.get("preset") as Preset;
  for (const k of SET_KEYS) {
    const raw = p.get(k);
    if (raw) s[k] = new Set(raw.split(","));
  }
  return s;
}

export function useBoardFilters(): [FilterState, (s: FilterState) => void] {
  const [params, setParams] = useSearchParams();
  const state = useMemo(() => paramsToState(params), [params]);
  return [state, (s) => setParams(stateToParams(s), { replace: true })];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/shortlist/use-board-filters.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/shortlist
git commit -m "feat(web): useBoardFilters URL-state hook"
```

---

### Task 4.3: `FilterDesk` component

**Files:** Create `web/src/components/FilterDesk.tsx` + test.

Renders the ~15-facet desk; derives option lists from the loaded rows via the facet helpers; calls back with a new `FilterState`. The preset radio shows only when `sort === "composite"`.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/FilterDesk.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FilterDesk } from "./FilterDesk";
import { emptyFilterState, type ShortlistItem } from "@/lib/filters/types";

const rows: ShortlistItem[] = [
  {
    jobId: 1,
    locationCountry: "US",
    locationRegion: "NY",
    locationCity: "New York",
    skills: [{ name: "Go", covered: false, required: true }],
  } as ShortlistItem,
];

describe("FilterDesk", () => {
  it("emits an updated fitMin when the slider changes", async () => {
    const onChange = vi.fn();
    render(
      <FilterDesk rows={rows} state={emptyFilterState()} onChange={onChange} />,
    );
    // min-fit control is labelled
    expect(screen.getByLabelText(/min fit/i)).toBeInTheDocument();
  });
  it("shows preset control only for composite sort", () => {
    const { rerender } = render(
      <FilterDesk rows={rows} state={emptyFilterState()} onChange={() => {}} />,
    );
    expect(screen.queryByLabelText(/preset/i)).not.toBeInTheDocument();
    rerender(
      <FilterDesk
        rows={rows}
        state={{ ...emptyFilterState(), sort: "composite" }}
        onChange={() => {}}
      />,
    );
    expect(screen.getByLabelText(/preset/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/components/FilterDesk.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `web/src/components/FilterDesk.tsx`. Build with shadcn `Slider`, `Input` (number), `Select` (sort), and a labelled multi-select pattern. Each control has an associated `<label htmlFor>`. Below is the structural implementation; multi-selects use a `MultiSelect` helper (a `DropdownMenu` of checkbox items) — create `web/src/components/MultiSelect.tsx` in the same task.

```tsx
import { useMemo } from "react";
import { Slider } from "@/components/ui/slider";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MultiSelect } from "./MultiSelect";
import {
  availableCities,
  availableCountries,
  availableIndustries,
  availableSkillCloud,
  availableStates,
} from "@/lib/filters/facets";
import { normalizeSkill } from "@/lib/filters/normalize";
import type {
  FilterState,
  ShortlistItem,
  SortKey,
  Preset,
} from "@/lib/filters/types";

const SORTS: [SortKey, string][] = [
  ["fit", "Fit"],
  ["salary", "Salary"],
  ["recency", "Recency"],
  ["composite", "Composite"],
];
const PRESETS: [Preset, string][] = [
  ["balanced", "Balanced"],
  ["pay_first", "Pay-first"],
  ["freshest", "Freshest"],
];

export function FilterDesk({
  rows,
  state,
  onChange,
}: {
  rows: ShortlistItem[];
  state: FilterState;
  onChange: (s: FilterState) => void;
}) {
  const set = (patch: Partial<FilterState>) => onChange({ ...state, ...patch });
  const countries = useMemo(() => availableCountries(rows), [rows]);
  const states = useMemo(
    () => availableStates(rows, state.country),
    [rows, state.country],
  );
  const cities = useMemo(
    () => availableCities(rows, state.country, state.region),
    [rows, state.country, state.region],
  );
  const industries = useMemo(() => availableIndustries(rows), [rows]);
  const skills = useMemo(() => availableSkillCloud(rows), [rows]);
  const sizes = useMemo(
    () =>
      [
        ...new Set(rows.map((r) => r.companySize).filter(Boolean) as string[]),
      ].sort(),
    [rows],
  );

  return (
    <section
      aria-label="Filter and sort"
      className="mb-6 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-4"
    >
      <div className="mb-3 font-mono text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
        Filter &amp; sort
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <Label htmlFor="f-salary">Min salary (USD)</Label>
          <Input
            id="f-salary"
            type="number"
            min={0}
            step={10000}
            value={state.salaryMin ?? 0}
            onChange={(e) => set({ salaryMin: Number(e.target.value) || null })}
          />
        </div>
        <div>
          <Label htmlFor="f-fit">Min fit</Label>
          <Slider
            id="f-fit"
            min={0}
            max={100}
            step={1}
            value={[state.fitMin ?? 0]}
            onValueChange={([v]) => set({ fitMin: v || null })}
          />
        </div>
        <div>
          <Label htmlFor="f-sort">Sort by</Label>
          <Select
            value={state.sort}
            onValueChange={(v) => set({ sort: v as SortKey })}
          >
            <SelectTrigger id="f-sort">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORTS.map(([k, l]) => (
                <SelectItem key={k} value={k}>
                  {l}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <MultiSelect
          label="Company size"
          options={sizes}
          selected={state.companySize}
          onChange={(s) => set({ companySize: s })}
        />

        <MultiSelect
          label="Remote"
          options={["remote", "hybrid", "onsite"]}
          selected={state.remote}
          onChange={(s) => set({ remote: s })}
        />
        <MultiSelect
          label="Sponsorship"
          options={["offered", "silent", "denied"]}
          selected={state.sponsorship}
          onChange={(s) => set({ sponsorship: s })}
        />
        <MultiSelect
          label="Seniority"
          options={["junior", "mid", "senior", "staff", "principal"]}
          selected={state.seniority}
          onChange={(s) => set({ seniority: s })}
        />
        <MultiSelect
          label="Type"
          options={["full_time", "contract", "internship", "part_time"]}
          selected={state.employmentType}
          onChange={(s) => set({ employmentType: s })}
        />

        <MultiSelect
          label="Country"
          options={countries}
          selected={state.country}
          onChange={(s) => set({ country: s })}
        />
        <MultiSelect
          label="State (US)"
          options={states}
          selected={state.region}
          onChange={(s) => set({ region: s })}
        />
        <MultiSelect
          label="City"
          options={cities}
          selected={state.city}
          onChange={(s) => set({ city: s })}
        />
        <MultiSelect
          label="Industry — division"
          options={industries.map(([d]) => d)}
          selected={state.industry /* division uses sic_division? see note */}
          onChange={() => {}}
          disabled
        />

        <MultiSelect
          label="Skills (any match)"
          options={skills.map((t) => t.name)}
          selected={new Set([...state.skills])}
          onChange={(picked) =>
            set({ skills: new Set([...picked].map(normalizeSkill)) })
          }
        />
        {state.sort === "composite" && (
          <div>
            <Label htmlFor="f-preset">Preset</Label>
            <Select
              value={state.preset}
              onValueChange={(v) => set({ preset: v as Preset })}
            >
              <SelectTrigger id="f-preset">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRESETS.map(([k, l]) => (
                  <SelectItem key={k} value={k}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    </section>
  );
}
```

Note on industry: Streamlit's desk has a division multiselect that then narrows a SIC-group multiselect; `state.industry` holds the `sic_major` codes. For v1 parity, wire the **group** multiselect to `state.industry` (codes from `availableIndustries`) and keep the division multiselect as a client-side narrowing of which groups are offered. Implement the group select using the flattened `[code,label]` pairs from `availableIndustries`, filtered by chosen divisions, exactly as `pages.py:_control_desk` does (lines 192-216). Replace the `disabled` placeholder accordingly.

Create `web/src/components/MultiSelect.tsx`:

```tsx
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

export function MultiSelect({
  label,
  options,
  selected,
  onChange,
  disabled,
}: {
  label: string;
  options: string[];
  selected: Set<string>;
  onChange: (s: Set<string>) => void;
  disabled?: boolean;
}) {
  const id = `ms-${label.replace(/\W+/g, "-").toLowerCase()}`;
  const toggle = (opt: string) => {
    const next = new Set(selected);
    next.has(opt) ? next.delete(opt) : next.add(opt);
    onChange(next);
  };
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            id={id}
            variant="outline"
            disabled={disabled}
            className="w-full justify-start font-normal"
          >
            {selected.size ? `${selected.size} selected` : "Any"}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="max-h-64 overflow-auto">
          {options.map((opt) => (
            <DropdownMenuCheckboxItem
              key={opt}
              checked={selected.has(opt)}
              onCheckedChange={() => toggle(opt)}
            >
              {opt.replace(/_/g, " ")}
            </DropdownMenuCheckboxItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/components/FilterDesk.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components
git commit -m "feat(web): FilterDesk + MultiSelect (15-facet parity)"
```

---

### Task 4.4: `JobCard` + Shortlist page with Approve

**Files:** Create `web/src/components/JobCard.tsx`, `web/src/features/shortlist/ShortlistContainer.tsx`, rewrite `ShortlistPage.tsx`, create `web/src/features/shortlist/use-approve.ts` (optimistic).

- [ ] **Step 1: Write the failing test**

Create `web/src/features/shortlist/ShortlistContainer.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { ShortlistContainer } from "./ShortlistContainer";

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("ShortlistContainer", () => {
  it("shows empty state when no rows", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [],
          pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
        }),
      ),
    );
    wrap(<ShortlistContainer />);
    await waitFor(() =>
      expect(screen.getByText(/nothing shortlisted yet/i)).toBeInTheDocument(),
    );
  });
  it("renders a card per row", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [
            {
              jobId: 7,
              company: "Acme",
              title: "Staff Engineer",
              location: "Remote",
              fitScore: 81,
              skills: [],
            },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
        }),
      ),
    );
    wrap(<ShortlistContainer />);
    await waitFor(() =>
      expect(screen.getByText("Staff Engineer")).toBeInTheDocument(),
    );
    expect(screen.getByText("81")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/shortlist/ShortlistContainer.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement card, approve hook, container, page**

Create `web/src/components/JobCard.tsx`:

```tsx
import { Card } from "@/components/ui/card";
import { FitMeter } from "./FitMeter";
import { SkillChip } from "./SkillChip";
import type { ShortlistItem } from "@/lib/filters/types";

export function JobCard({
  row,
  activeSkills,
  onOpen,
  footer,
}: {
  row: ShortlistItem;
  activeSkills: Set<string>;
  onOpen: () => void;
  footer?: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col gap-3 p-4">
      <button onClick={onOpen} className="flex gap-4 text-left">
        <FitMeter score={row.fitScore} />
        <div className="min-w-0">
          <div className="font-serif text-lg font-semibold">
            {row.title ?? "—"}
          </div>
          <div className="text-sm text-[var(--muted-foreground)]">
            {row.company ?? "—"} · {row.location ?? "location n/a"}
          </div>
          {row.skills.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {row.skills.slice(0, 6).map((t) => (
                <SkillChip
                  key={t.name}
                  name={t.name}
                  active={activeSkills.has(t.name.toLowerCase())}
                />
              ))}
            </div>
          )}
          {row.fitRationale && (
            <p className="mt-2 line-clamp-4 text-sm text-[var(--muted-foreground)]">
              {row.fitRationale}
            </p>
          )}
        </div>
      </button>
      {footer && <div className="mt-auto">{footer}</div>}
    </Card>
  );
}
```

Create `web/src/features/shortlist/use-approve.ts` (optimistic stage→approved):

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, unwrap } from "@/lib/api/client";
import type { ShortlistItem } from "@/lib/filters/types";

export function useApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          body: { status: "approved" },
        }),
      ),
    onMutate: async (jobId) => {
      await qc.cancelQueries({ queryKey: ["shortlist"] });
      const prev = qc.getQueryData<ShortlistItem[]>(["shortlist"]);
      qc.setQueryData<ShortlistItem[]>(["shortlist"], (old) =>
        old?.filter((r) => r.jobId !== jobId),
      );
      return { prev };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(["shortlist"], ctx.prev);
      toast.error("Failed to approve job");
    },
    onSuccess: () => toast.success("Approved for tailoring"),
    onSettled: () => qc.invalidateQueries({ queryKey: ["shortlist"] }),
  });
}
```

Create `web/src/features/shortlist/ShortlistContainer.tsx`:

```tsx
import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { FilterDesk } from "@/components/FilterDesk";
import { JobCard } from "@/components/JobCard";
import { JobDrawer } from "@/components/JobDrawer";
import { applyFilters } from "@/lib/filters/apply";
import { sortRows } from "@/lib/filters/sort";
import { useShortlist } from "./use-shortlist";
import { useBoardFilters } from "./use-board-filters";
import { useApprove } from "./use-approve";

export function ShortlistContainer() {
  const { data: rows, isLoading, error } = useShortlist();
  const [filters, setFilters] = useBoardFilters();
  const approve = useApprove();
  const [params, setParams] = useSearchParams();

  const visible = useMemo(
    () => (rows ? sortRows(applyFilters(rows, filters), filters) : []),
    [rows, filters],
  );

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error)
    return (
      <EmptyState title="Failed to load" body={(error as Error).message} />
    );

  const avg = rows?.length
    ? Math.round(rows.reduce((a, r) => a + (r.fitScore ?? 0), 0) / rows.length)
    : 0;
  const sponsored =
    rows?.filter((r) => r.sponsorshipSignal === "offered").length ?? 0;
  const openId = params.get("job");

  return (
    <>
      <PageHeader
        kicker="Human checkpoint"
        title="The Shortlist"
        sub="The cost gate before the premium tailoring step. Approve only the jobs worth the spend."
      />
      <MetricRow
        items={[
          ["Awaiting review", String(rows?.length ?? 0)],
          ["Avg fit", String(avg)],
          ["Sponsorship offered", String(sponsored)],
        ]}
      />
      {!rows?.length ? (
        <EmptyState
          title="Nothing shortlisted yet"
          body="Run a discover to score jobs and surface the keepers here."
        />
      ) : (
        <>
          <FilterDesk rows={rows} state={filters} onChange={setFilters} />
          {visible.length === 0 ? (
            <EmptyState
              title="No jobs match these filters"
              body="Loosen a filter or clear the skill tags."
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {visible.map((row) => (
                <JobCard
                  key={row.jobId}
                  row={row}
                  activeSkills={filters.skills}
                  onOpen={() =>
                    setParams(
                      (p) => {
                        p.set("job", String(row.jobId));
                        return p;
                      },
                      { replace: true },
                    )
                  }
                  footer={
                    <Button
                      className="w-full"
                      onClick={() => approve.mutate(row.jobId)}
                    >
                      Approve for tailoring →
                    </Button>
                  }
                />
              ))}
            </div>
          )}
        </>
      )}
      {openId && (
        <JobDrawer
          jobId={Number(openId)}
          onClose={() =>
            setParams(
              (p) => {
                p.delete("job");
                return p;
              },
              { replace: true },
            )
          }
        />
      )}
    </>
  );
}
```

Rewrite `web/src/features/shortlist/ShortlistPage.tsx`:

```tsx
import { ShortlistContainer } from "./ShortlistContainer";
export function ShortlistPage() {
  return <ShortlistContainer />;
}
```

(`JobDrawer` is implemented in Phase 5; create a temporary stub `web/src/components/JobDrawer.tsx` returning `null` with the `{ jobId, onClose }` signature so this compiles, replaced in Task 5.1.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/shortlist/ShortlistContainer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): Shortlist page — cards, filters, optimistic approve"
```

---

### Task 4.5: Triage page (multi-select + bulk actions + prune)

**Files:** Create `web/src/features/triage/{TriageContainer,TriageCard,PrunePanel}.tsx`, `use-triage-mutations.ts`, rewrite `TriagePage.tsx`.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/triage/TriageContainer.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { TriageContainer } from "./TriageContainer";

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("TriageContainer", () => {
  it("selecting a row enables Archive selected", async () => {
    server.use(
      http.get("/api/triage", () =>
        HttpResponse.json({
          data: [
            {
              jobId: 3,
              company: "Acme",
              title: "Eng",
              location: "NYC",
              source: "adzuna",
              status: "raw",
              fitScore: 40,
              postedAt: null,
              archivedAt: null,
              hasProgress: false,
            },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
        }),
      ),
    );
    wrap(<TriageContainer />);
    await waitFor(() => expect(screen.getByText("Eng")).toBeInTheDocument());
    const archive = screen.getByRole("button", { name: /archive selected/i });
    expect(archive).toBeDisabled();
    await userEvent.click(
      screen.getByRole("checkbox", { name: /select job 3/i }),
    );
    expect(archive).toBeEnabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/triage/TriageContainer.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `web/src/features/triage/use-triage-mutations.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, unwrap } from "@/lib/api/client";

export function useArchive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          body: { archived: true },
        }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: ["triage"] }),
  });
}

export function useRestore() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          body: { archived: false },
        }),
      ),
    onSettled: () => qc.invalidateQueries({ queryKey: ["triage"] }),
  });
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.DELETE("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
        }),
      ),
    onError: () => toast.error("Job has progress and cannot be deleted"),
    // Invalidate every board: delete is reachable from the drawer over any of them.
    onSettled: () => {
      for (const k of ["triage", "pipeline", "shortlist"])
        qc.invalidateQueries({ queryKey: [k] });
    },
  });
}
```

Create `web/src/features/triage/TriageCard.tsx`:

```tsx
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { FitMeter } from "@/components/FitMeter";
import { StatusBadge } from "@/components/StatusBadge";
import type { TriageItem } from "./use-triage";

export function TriageCard({
  row,
  checked,
  onCheck,
  onOpen,
}: {
  row: TriageItem;
  checked: boolean;
  onCheck: (v: boolean) => void;
  onOpen: () => void;
}) {
  return (
    <Card className="flex items-start gap-3 p-4">
      <Checkbox
        checked={checked}
        onCheckedChange={(v) => onCheck(!!v)}
        aria-label={`Select job ${row.jobId}`}
      />
      <button onClick={onOpen} className="min-w-0 flex-1 text-left">
        <div className="font-serif text-base font-semibold">
          {row.title ?? "—"}
        </div>
        <div className="text-sm text-[var(--muted-foreground)]">
          {row.company ?? "—"} · {row.location ?? "location n/a"}
        </div>
        <div className="mt-1 flex items-center gap-2">
          <StatusBadge status={row.status} />
          <span className="font-mono text-xs text-[var(--muted-foreground)]">
            {row.source}
          </span>
        </div>
      </button>
      <FitMeter score={row.fitScore} />
    </Card>
  );
}
```

Create `web/src/features/triage/TriageContainer.tsx`:

```tsx
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { JobDrawer } from "@/components/JobDrawer";
import { TriageCard } from "./TriageCard";
import { PrunePanel } from "./PrunePanel";
import { useTriage } from "./use-triage";
import { useArchive, useRestore, useDeleteJob } from "./use-triage-mutations";

export function TriageContainer() {
  const [archived, setArchived] = useState(false);
  const { data: rows, isLoading } = useTriage(archived);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [params, setParams] = useSearchParams();
  const archive = useArchive();
  const restore = useRestore();
  const del = useDeleteJob();

  const toggle = (id: number, on: boolean) =>
    setSelected((s) => {
      const n = new Set(s);
      on ? n.add(id) : n.delete(id);
      return n;
    });

  if (isLoading) return <Skeleton className="h-64 w-full" />;

  const deletable = new Set(
    (rows ?? []).filter((r) => !r.hasProgress).map((r) => r.jobId),
  );
  const allSelectedDeletable =
    selected.size > 0 && [...selected].every((id) => deletable.has(id));
  const openId = params.get("job");

  return (
    <>
      <PageHeader
        kicker="Intake"
        title="Triage Desk"
        sub="Raw and rejected jobs before the shortlist. Archive noise, delete dead-ends, prune in bulk."
      />
      <div className="mb-4 flex items-center gap-2">
        <Switch
          id="show-archived"
          checked={archived}
          onCheckedChange={setArchived}
        />
        <Label htmlFor="show-archived">Show archived</Label>
      </div>
      <MetricRow
        items={[
          ["In view", String(rows?.length ?? 0)],
          ["Deletable", String(deletable.size)],
        ]}
      />
      <PrunePanel />
      {!rows?.length ? (
        <EmptyState
          title="Nothing to triage"
          body="Run a pull to bring in jobs, or toggle archived."
        />
      ) : (
        <>
          <div className="mb-4 flex items-center gap-3">
            <span className="text-sm">
              <strong>{selected.size}</strong> selected
            </span>
            {archived ? (
              <Button
                disabled={!selected.size}
                onClick={() => {
                  selected.forEach((id) => restore.mutate(id));
                  setSelected(new Set());
                }}
              >
                Restore selected
              </Button>
            ) : (
              <Button
                disabled={!selected.size}
                onClick={() => {
                  selected.forEach((id) => archive.mutate(id));
                  setSelected(new Set());
                }}
              >
                Archive selected
              </Button>
            )}
            <Button
              variant="destructive"
              disabled={!allSelectedDeletable}
              onClick={() => {
                if (
                  confirm(
                    `Delete ${selected.size} job(s)? This cannot be undone.`,
                  )
                ) {
                  selected.forEach((id) => del.mutate(id));
                  setSelected(new Set());
                }
              }}
            >
              Delete selected
            </Button>
          </div>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            {rows.map((row) => (
              <TriageCard
                key={row.jobId}
                row={row}
                checked={selected.has(row.jobId)}
                onCheck={(v) => toggle(row.jobId, v)}
                onOpen={() =>
                  setParams(
                    (p) => {
                      p.set("job", String(row.jobId));
                      return p;
                    },
                    { replace: true },
                  )
                }
              />
            ))}
          </div>
        </>
      )}
      {openId && (
        <JobDrawer
          jobId={Number(openId)}
          onClose={() =>
            setParams(
              (p) => {
                p.delete("job");
                return p;
              },
              { replace: true },
            )
          }
        />
      )}
    </>
  );
}
```

Create `web/src/features/triage/PrunePanel.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type PruneReport = components["schemas"]["PruneReportOut"];

export function PrunePanel() {
  const qc = useQueryClient();
  const [fit, setFit] = useState(40);
  const [stale, setStale] = useState(45);
  const [retain, setRetain] = useState(30);

  const preview = useMutation({
    mutationFn: (): Promise<PruneReport> =>
      unwrap(
        api.POST("/api/prune", {
          body: {
            dryRun: true,
            fitThreshold: fit,
            staleDays: stale,
            retentionDays: retain,
          },
        }),
      ) as Promise<PruneReport>,
  });
  const run = useMutation({
    mutationFn: (): Promise<PruneReport> =>
      unwrap(
        api.POST("/api/prune", {
          body: {
            dryRun: false,
            fitThreshold: fit,
            staleDays: stale,
            retentionDays: retain,
          },
        }),
      ) as Promise<PruneReport>,
    onSettled: () => qc.invalidateQueries({ queryKey: ["triage"] }),
  });

  return (
    <Accordion type="single" collapsible className="mb-4">
      <AccordionItem value="prune">
        <AccordionTrigger>Prune (archive junk, expire old)</AccordionTrigger>
        <AccordionContent>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label htmlFor="p-fit">Fit below</Label>
              <Input
                id="p-fit"
                type="number"
                value={fit}
                onChange={(e) => setFit(Number(e.target.value))}
              />
            </div>
            <div>
              <Label htmlFor="p-stale">Stale days</Label>
              <Input
                id="p-stale"
                type="number"
                value={stale}
                onChange={(e) => setStale(Number(e.target.value))}
              />
            </div>
            <div>
              <Label htmlFor="p-ret">Retention days</Label>
              <Input
                id="p-ret"
                type="number"
                value={retain}
                onChange={(e) => setRetain(Number(e.target.value))}
              />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <Button variant="outline" onClick={() => preview.mutate()}>
              Preview
            </Button>
            <Button
              onClick={() => {
                if (confirm("Run prune? Expiry cannot be undone."))
                  run.mutate();
              }}
            >
              Prune now
            </Button>
          </div>
          {preview.data && (
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">
              {preview.data.rejected} rejected · {preview.data.lowFit} low-fit ·{" "}
              {preview.data.stale} stale → {preview.data.archived} archive ·{" "}
              {preview.data.expired} expire · {preview.data.skipped} skipped
            </p>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
```

Rewrite `web/src/features/triage/TriagePage.tsx`:

```tsx
import { TriageContainer } from "./TriageContainer";
export function TriagePage() {
  return <TriageContainer />;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/triage/TriageContainer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/triage
git commit -m "feat(web): Triage page — multi-select, bulk actions, prune"
```

---

### Task 4.6: Pipeline page (stage groups + actions)

**Files:** Create `web/src/features/pipeline/{PipelineContainer,PipelineCard}.tsx`, `use-pipeline-filters.ts`, rewrite `PipelinePage.tsx`.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/pipeline/PipelineContainer.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { PipelineContainer } from "./PipelineContainer";

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("PipelineContainer", () => {
  it("groups cards by stage", async () => {
    server.use(
      http.get("/api/pipeline", () =>
        HttpResponse.json({
          data: [
            {
              jobId: 1,
              company: "A",
              title: "Eng",
              status: "approved",
              fitScore: 70,
              jdText: "x",
              critiqueJson: null,
              pdfPath: null,
              applicationStatus: null,
              hasProgress: false,
            },
            {
              jobId: 2,
              company: "B",
              title: "Dev",
              status: "rendered",
              fitScore: 88,
              jdText: "y",
              critiqueJson: null,
              pdfPath: null,
              applicationStatus: null,
              hasProgress: true,
            },
          ],
          pagination: { page: 1, pageSize: 200, totalItems: 2, totalPages: 1 },
        }),
      ),
    );
    wrap(<PipelineContainer />);
    await waitFor(() => expect(screen.getByText("Eng")).toBeInTheDocument());
    expect(screen.getByText(/approved/i)).toBeInTheDocument();
    expect(screen.getByText(/rendered/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/pipeline/PipelineContainer.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `web/src/features/pipeline/PipelineCard.tsx`:

```tsx
import { Card } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";
import type { PipelineItem } from "./use-pipeline";

export function PipelineCard({
  row,
  onOpen,
}: {
  row: PipelineItem;
  onOpen: () => void;
}) {
  return (
    <Card className="p-4">
      <button onClick={onOpen} className="w-full text-left">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-serif text-base font-semibold">
              {row.title ?? "—"}
            </div>
            <div className="text-sm text-[var(--muted-foreground)]">
              {row.company ?? "—"}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={row.status} />
            <span className="font-mono text-xs">fit {row.fitScore ?? "—"}</span>
          </div>
        </div>
        <p className="mt-2 line-clamp-3 whitespace-pre-line text-sm text-[var(--muted-foreground)]">
          {row.jdText}
        </p>
      </button>
    </Card>
  );
}
```

Create `web/src/features/pipeline/PipelineContainer.tsx`:

```tsx
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { JobDrawer } from "@/components/JobDrawer";
import { PipelineCard } from "./PipelineCard";
import { usePipeline } from "./use-pipeline";

const STAGE_ORDER = [
  "raw",
  "shortlisted",
  "approved",
  "tailored",
  "rendered",
  "rejected",
];

export function PipelineContainer() {
  const { data: rows, isLoading } = usePipeline();
  const [q, setQ] = useState("");
  const [minFit, setMinFit] = useState(0);
  const [params, setParams] = useSearchParams();

  const visible = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (rows ?? []).filter(
      (r) =>
        (r.fitScore == null || r.fitScore >= minFit) &&
        (!needle ||
          `${r.company ?? ""} ${r.title ?? ""}`.toLowerCase().includes(needle)),
    );
  }, [rows, q, minFit]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;

  const byStage = new Map<string, typeof visible>();
  for (const r of visible)
    byStage.set(r.status, [...(byStage.get(r.status) ?? []), r]);
  const stages = [
    ...STAGE_ORDER.filter((s) => byStage.has(s)),
    ...[...byStage.keys()].filter((s) => !STAGE_ORDER.includes(s)),
  ];
  const rendered = byStage.get("rendered")?.length ?? 0;
  const openId = params.get("job");

  return (
    <>
      <PageHeader
        kicker="Mission control"
        title="Pipeline / Board"
        sub="Every job by pipeline stage, with its tailored PDF, review critiques, and your application status."
      />
      <MetricRow
        items={[
          ["In view", String(visible.length)],
          ["Rendered", String(rendered)],
          ["Stages active", String(byStage.size)],
        ]}
      />
      <div className="mb-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="pipe-q">Company/title</Label>
          <Input id="pipe-q" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="pipe-fit">Min fit</Label>
          <Slider
            id="pipe-fit"
            min={0}
            max={100}
            value={[minFit]}
            onValueChange={([v]) => setMinFit(v)}
          />
        </div>
      </div>
      {!rows?.length ? (
        <EmptyState
          title="No jobs in the pipeline"
          body="Start by adding a job or running a pull."
        />
      ) : (
        stages.map((stage) => (
          <section key={stage} className="mb-6">
            <h2 className="mb-2 font-mono text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              {stage} · {byStage.get(stage)!.length}
            </h2>
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              {byStage.get(stage)!.map((row) => (
                <PipelineCard
                  key={row.jobId}
                  row={row}
                  onOpen={() =>
                    setParams(
                      (p) => {
                        p.set("job", String(row.jobId));
                        return p;
                      },
                      { replace: true },
                    )
                  }
                />
              ))}
            </div>
          </section>
        ))
      )}
      {openId && (
        <JobDrawer
          jobId={Number(openId)}
          onClose={() =>
            setParams(
              (p) => {
                p.delete("job");
                return p;
              },
              { replace: true },
            )
          }
        />
      )}
    </>
  );
}
```

Rewrite `web/src/features/pipeline/PipelinePage.tsx`:

```tsx
import { PipelineContainer } from "./PipelineContainer";
export function PipelinePage() {
  return <PipelineContainer />;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/pipeline/PipelineContainer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/pipeline
git commit -m "feat(web): Pipeline page — stage groups, filter, search"
```

---

## Phase 5 — Job drawer

### Task 5.1: `useJobDetail` + `JobDrawer` (JD, criteria, critiques, versions)

**Files:** Replace stub `web/src/components/JobDrawer.tsx`; create `web/src/features/job/use-job-detail.ts`, `web/src/features/job/use-job-mutations.ts` + test.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/JobDrawer.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { JobDrawer } from "./JobDrawer";

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

describe("JobDrawer", () => {
  it("renders job detail with a proper heading and JD", async () => {
    server.use(
      http.get("/api/jobs/42", () =>
        HttpResponse.json({
          id: 42,
          source: "greenhouse",
          url: null,
          company: "Acme",
          title: "Staff Engineer",
          location: "Remote",
          jdText: "Build things.",
          status: "approved",
          fitScore: 80,
          fitRationale: "Strong match.",
          criteriaJson: null,
          postedAt: null,
          archivedAt: null,
          createdAt: "2026-06-01T00:00:00Z",
          hasProgress: false,
          application: null,
          resumeVersions: [],
        }),
      ),
    );
    wrap(<JobDrawer jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /staff engineer/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Build things.")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/components/JobDrawer.test.tsx`
Expected: FAIL (stub renders null).

- [ ] **Step 3: Implement detail hook, mutations, and drawer**

Create `web/src/features/job/use-job-detail.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type JobDetail = components["schemas"]["JobDetail"];

export function useJobDetail(jobId: number) {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: (): Promise<JobDetail> =>
      unwrap(
        api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } }),
      ) as Promise<JobDetail>,
  });
}
```

Create `web/src/features/job/use-job-mutations.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, unwrap } from "@/lib/api/client";

function invalidateBoards(
  qc: ReturnType<typeof useQueryClient>,
  jobId: number,
) {
  for (const key of [
    "shortlist",
    "pipeline",
    "triage",
    ["job", jobId],
  ] as const) {
    qc.invalidateQueries({ queryKey: Array.isArray(key) ? key : [key] });
  }
}

export function useSetStage(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (status: string) =>
      unwrap(
        api.PATCH("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
          body: { status },
        }),
      ),
    onSuccess: () => {
      invalidateBoards(qc, jobId);
      toast.success("Stage updated");
    },
    onError: () => toast.error("Failed to update stage"),
  });
}

export function useUpsertApplication(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { status: string; notes?: string | null }) =>
      unwrap(
        api.PUT("/api/jobs/{job_id}/application", {
          params: { path: { job_id: jobId } },
          body,
        }),
      ),
    onSuccess: () => {
      invalidateBoards(qc, jobId);
      toast.success("Application saved");
    },
  });
}

export function useRenderVersion(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: number) =>
      unwrap(
        api.POST("/api/resume-versions/{version_id}/render", {
          params: { path: { version_id: versionId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
}
```

Replace `web/src/components/JobDrawer.tsx`:

```tsx
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "./StatusBadge";
import { ApplicationEditor } from "@/features/job/ApplicationEditor";
import { StageManager } from "@/features/job/StageManager";
import { useJobDetail } from "@/features/job/use-job-detail";
import { useRenderVersion } from "@/features/job/use-job-mutations";

export function JobDrawer({
  jobId,
  onClose,
}: {
  jobId: number;
  onClose: () => void;
}) {
  const { data: job, isLoading } = useJobDetail(jobId);
  const render = useRenderVersion(jobId);

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-xl">
        {isLoading || !job ? (
          <Skeleton className="mt-8 h-96 w-full" />
        ) : (
          <>
            <SheetHeader>
              <SheetTitle className="font-serif text-2xl">
                {job.title ?? "—"}
              </SheetTitle>
              <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
                {job.company ?? "—"} · {job.location ?? "location n/a"}{" "}
                <StatusBadge status={job.status} />
              </div>
            </SheetHeader>
            <Tabs defaultValue="jd" className="mt-4">
              <TabsList>
                <TabsTrigger value="jd">Job description</TabsTrigger>
                <TabsTrigger value="versions">Versions</TabsTrigger>
                <TabsTrigger value="application">Application</TabsTrigger>
                <TabsTrigger value="manage">Manage</TabsTrigger>
              </TabsList>
              <TabsContent value="jd">
                {job.fitRationale && (
                  <p className="mb-3 text-sm">{job.fitRationale}</p>
                )}
                <h3 className="font-mono text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
                  Job description
                </h3>
                <pre className="mt-1 whitespace-pre-wrap font-sans text-sm">
                  {job.jdText}
                </pre>
              </TabsContent>
              <TabsContent value="versions">
                <h3 className="font-mono text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
                  Resume versions
                </h3>
                {job.resumeVersions.length === 0 && (
                  <p className="text-sm text-[var(--muted-foreground)]">
                    Not tailored yet.
                  </p>
                )}
                <ul className="mt-2 space-y-2">
                  {job.resumeVersions.map((v) => (
                    <li
                      key={v.id}
                      className="flex items-center justify-between rounded-[var(--radius-sm)] border border-[var(--border)] p-2"
                    >
                      <span className="text-sm">
                        Round {v.round} · score {v.reviewScore ?? "—"} ·{" "}
                        {v.factCheckPassed ? "fact-check ✓" : "fact-check ✗"}
                      </span>
                      {v.pdfPath ? (
                        <a
                          className="text-sm underline"
                          href={`/api/resume-versions/${v.id}/pdf`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Download PDF
                        </a>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => render.mutate(v.id)}
                        >
                          Render
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              </TabsContent>
              <TabsContent value="application">
                <ApplicationEditor
                  jobId={jobId}
                  application={job.application}
                />
              </TabsContent>
              <TabsContent value="manage">
                <StageManager job={job} onDeleted={onClose} />
              </TabsContent>
            </Tabs>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

Create `web/src/features/job/ApplicationEditor.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useUpsertApplication } from "./use-job-mutations";
import type { components } from "@/lib/api/schema";

const STATUSES = ["ready", "submitted", "interview", "offer", "rejected"];

export function ApplicationEditor({
  jobId,
  application,
}: {
  jobId: number;
  application: components["schemas"]["ApplicationOut"] | null;
}) {
  const [status, setStatus] = useState(application?.status ?? "ready");
  const [notes, setNotes] = useState(application?.notes ?? "");
  const save = useUpsertApplication(jobId);
  return (
    <div className="space-y-3">
      <div>
        <Label htmlFor="app-status">Application status</Label>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger id="app-status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label htmlFor="app-notes">Notes</Label>
        <Input
          id="app-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="e.g. applied via referral"
        />
      </div>
      <Button onClick={() => save.mutate({ status, notes: notes || null })}>
        Save
      </Button>
    </div>
  );
}
```

Create `web/src/features/job/StageManager.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSetStage } from "./use-job-mutations";
import { useDeleteJob } from "@/features/triage/use-triage-mutations";
import type { JobDetail } from "./use-job-detail";

const STAGES = [
  "raw",
  "shortlisted",
  "approved",
  "tailored",
  "rendered",
  "rejected",
];

export function StageManager({
  job,
  onDeleted,
}: {
  job: JobDetail;
  onDeleted: () => void;
}) {
  const [stage, setStage] = useState(job.status);
  const setStageMut = useSetStage(job.id);
  const del = useDeleteJob();
  return (
    <div className="space-y-3">
      <div>
        <Label htmlFor="mng-stage">Stage</Label>
        <Select value={stage} onValueChange={setStage}>
          <SelectTrigger id="mng-stage">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STAGES.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex gap-2">
        <Button onClick={() => setStageMut.mutate(stage)}>Set stage</Button>
        <Button
          variant="destructive"
          disabled={job.hasProgress}
          onClick={() => {
            if (confirm("Delete this job? This cannot be undone.")) {
              del.mutate(job.id);
              onDeleted();
            }
          }}
        >
          Delete
        </Button>
      </div>
      {job.hasProgress && (
        <p className="text-xs text-[var(--muted-foreground)]">
          Has progress — delete disabled.
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/components/JobDrawer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): JobDrawer — detail, versions/PDF, application, manage"
```

---

## Phase 6 — Run control center + SSE

### Task 6.1: Run store + SSE subscription

**Files:** Create `web/src/lib/runs/store.ts`, `web/src/lib/runs/sse.ts` + test.

- [ ] **Step 1: Write the failing test**

Create `web/src/lib/runs/store.test.ts`:

```ts
import { describe, expect, it, beforeEach } from "vitest";
import { useRunStore } from "./store";

describe("run store", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));
  it("upserts run progress by id", () => {
    useRunStore
      .getState()
      .upsert({
        runId: "r1",
        kind: "pull",
        status: "running",
        percent: 10,
        phase: "adzuna",
      });
    useRunStore
      .getState()
      .upsert({
        runId: "r1",
        kind: "pull",
        status: "running",
        percent: 60,
        phase: "adzuna",
      });
    expect(useRunStore.getState().runs["r1"].percent).toBe(60);
  });
  it("removes a run", () => {
    useRunStore
      .getState()
      .upsert({
        runId: "r2",
        kind: "discover",
        status: "running",
        percent: 0,
        phase: "",
      });
    useRunStore.getState().remove("r2");
    expect(useRunStore.getState().runs["r2"]).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/lib/runs/store.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement store + SSE**

Create `web/src/lib/runs/store.ts`:

```ts
import { create } from "zustand";

export interface RunRecord {
  runId: string;
  kind: string;
  status: "running" | "succeeded" | "failed";
  percent: number;
  phase: string;
  error?: string;
}

interface RunState {
  runs: Record<string, RunRecord>;
  upsert: (r: RunRecord) => void;
  remove: (id: string) => void;
}

export const useRunStore = create<RunState>((set) => ({
  runs: {},
  upsert: (r) => set((s) => ({ runs: { ...s.runs, [r.runId]: r } })),
  remove: (id) =>
    set((s) => {
      const { [id]: _, ...rest } = s.runs;
      return { runs: rest };
    }),
}));
```

Create `web/src/lib/runs/sse.ts`:

```ts
import { useRunStore } from "./store";

/** Subscribe to a run's SSE stream; resolves when the run terminates. */
export function watchRun(
  runId: string,
  kind: string,
  onDone?: () => void,
): () => void {
  const source = new EventSource(`/api/runs/${runId}/events`);
  const update = (data: any, status: RunStatus) =>
    useRunStore.getState().upsert({
      runId,
      kind,
      status,
      percent: typeof data?.percent === "number" ? data.percent : 0,
      phase: data?.phase ?? "",
      error: data?.error,
    });
  type RunStatus = "running" | "succeeded" | "failed";

  source.onmessage = (e) => {
    try {
      update(JSON.parse(e.data), "running");
    } catch {
      /* ignore keep-alive */
    }
  };
  source.addEventListener("done", (e) => {
    try {
      update(JSON.parse((e as MessageEvent).data), "succeeded");
    } catch {
      update({}, "succeeded");
    }
    source.close();
    onDone?.();
    setTimeout(() => useRunStore.getState().remove(runId), 4000);
  });
  source.addEventListener("error", () => {
    useRunStore
      .getState()
      .upsert({
        runId,
        kind,
        status: "failed",
        percent: 0,
        phase: "",
        error: "stream error",
      });
    source.close();
    onDone?.();
  });
  return () => source.close();
}
```

Note: confirm the SSE event names/payload shape against `src/resume_tailor_harness/api/runs/sse.py` (`run_events`) — adapt the `data` field names (`percent`, `phase`) to whatever `record_to_run`/the event serializer emits. Read that file before implementing and match exactly.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/lib/runs/store.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/runs
git commit -m "feat(web): run store + SSE subscription"
```

---

### Task 6.2: `RunActions` + `RunPanel` (live progress)

**Files:** Replace stubs `web/src/features/runs/RunActions.tsx`, `RunPanel.tsx`; create `use-launch-run.ts`, `AddUrlDialog.tsx` + test.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/runs/RunPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, beforeEach } from "vitest";
import { RunPanel } from "./RunPanel";
import { useRunStore } from "@/lib/runs/store";

describe("RunPanel", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));
  it("renders an accessible progressbar for an active run", () => {
    useRunStore
      .getState()
      .upsert({
        runId: "r1",
        kind: "pull",
        status: "running",
        percent: 42,
        phase: "adzuna",
      });
    render(<RunPanel />);
    const bar = screen.getByRole("progressbar", { name: /pull/i });
    expect(bar).toHaveAttribute("aria-valuenow", "42");
  });
  it("renders nothing when no runs", () => {
    const { container } = render(<RunPanel />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/runs/RunPanel.test.tsx`
Expected: FAIL (stub returns null → second test passes but first fails).

- [ ] **Step 3: Implement launch hook, actions, panel**

Create `web/src/features/runs/use-launch-run.ts`:

```ts
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, unwrap } from "@/lib/api/client";
import { watchRun } from "@/lib/runs/sse";
import { useRunStore } from "@/lib/runs/store";

type RunOut = { runId: string; kind: string };

export function useLaunchRun() {
  const qc = useQueryClient();
  return {
    launch: async (
      kind: string,
      call: () => Promise<unknown>,
      invalidate: string[] = ["shortlist", "pipeline", "triage"],
    ) => {
      try {
        const run = (await call()) as RunOut;
        useRunStore
          .getState()
          .upsert({
            runId: run.runId,
            kind,
            status: "running",
            percent: 0,
            phase: "",
          });
        watchRun(run.runId, kind, () =>
          invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
        );
      } catch (e) {
        toast.error(`Failed to start ${kind}: ${(e as Error).message}`);
      }
    },
  };
}

export const launchers = {
  pull: () => unwrap(api.POST("/api/pull", { body: { limit: null } })),
  discover: () => unwrap(api.POST("/api/discover", {})),
};
```

(Match the `pull` body to `PullParams` in the contract; if `limit` is required, pass a sensible default rather than `null`.)

Create `web/src/features/runs/AddUrlDialog.tsx`:

```tsx
import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, unwrap } from "@/lib/api/client";
import { useLaunchRun } from "./use-launch-run";

export function AddUrlDialog() {
  const [url, setUrl] = useState("");
  const [open, setOpen] = useState(false);
  const { launch } = useLaunchRun();
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">+ Add URL</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add job by URL</DialogTitle>
        </DialogHeader>
        <Label htmlFor="add-url">Job posting URL</Label>
        <Input
          id="add-url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…"
        />
        <Button
          onClick={async () => {
            await launch("addJobUrl", () =>
              unwrap(
                api.POST("/api/jobs/from-url", {
                  body: { url, allowBrowser: true },
                }),
              ),
            );
            setOpen(false);
            setUrl("");
          }}
        >
          Add job
        </Button>
      </DialogContent>
    </Dialog>
  );
}
```

Replace `web/src/features/runs/RunActions.tsx`:

```tsx
import { Button } from "@/components/ui/button";
import { AddUrlDialog } from "./AddUrlDialog";
import { launchers, useLaunchRun } from "./use-launch-run";

export function RunActions() {
  const { launch } = useLaunchRun();
  return (
    <div className="flex items-center gap-2">
      <Button onClick={() => launch("pull", launchers.pull)}>Pull</Button>
      <Button onClick={() => launch("discover", launchers.discover)}>
        Discover
      </Button>
      <AddUrlDialog />
    </div>
  );
}
```

Replace `web/src/features/runs/RunPanel.tsx`:

```tsx
import { Progress } from "@/components/ui/progress";
import { useRunStore } from "@/lib/runs/store";

export function RunPanel() {
  const runs = useRunStore((s) => Object.values(s.runs));
  if (runs.length === 0) return null;
  return (
    // aria-live announces start/progress/completion to screen readers (SSE push, accessibly).
    <div
      aria-live="polite"
      className="space-y-2 border-b border-[var(--border)] px-6 py-3"
    >
      {runs.map((r) => (
        <div
          key={r.runId}
          className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--card)] p-2"
        >
          <div className="flex items-baseline justify-between font-mono text-xs uppercase tracking-widest">
            <span>
              {r.kind}
              {r.phase ? ` · ${r.phase}` : ""}
            </span>
            <span>
              {r.status === "failed" ? "failed" : `${Math.round(r.percent)}%`}
            </span>
          </div>
          {/* Radix Progress provides role="progressbar" + aria-valuenow; we add the label. */}
          <Progress
            value={Math.round(r.percent)}
            aria-label={`${r.kind} progress`}
            className="mt-1 h-1.5"
          />
          {r.error && (
            <p className="mt-1 text-xs text-[var(--destructive)]">{r.error}</p>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/runs/RunPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/runs
git commit -m "feat(web): run control center — launch actions + live SSE panel"
```

---

### Task 6.3: Contextual Tailor / Cover-letter actions

**Files:** Modify `web/src/features/pipeline/PipelineContainer.tsx` (selection + bulk tailor); create `web/src/features/runs/use-bulk-run.ts`.

For v1, add an "Tailor approved" and "Cover letters (approved)" button to the Pipeline page header that call `/api/tailor` and `/api/cover-letters` with `{ approved: true }`.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/runs/use-bulk-run.test.tsx`:

```tsx
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { useBulkRun } from "./use-bulk-run";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient();
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useBulkRun", () => {
  it("exposes tailorApproved and coverLettersApproved callables", () => {
    const { result } = renderHook(() => useBulkRun(), { wrapper });
    expect(typeof result.current.tailorApproved).toBe("function");
    expect(typeof result.current.coverLettersApproved).toBe("function");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/runs/use-bulk-run.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement + wire into Pipeline header**

Create `web/src/features/runs/use-bulk-run.ts`:

```ts
import { api, unwrap } from "@/lib/api/client";
import { useLaunchRun } from "./use-launch-run";

export function useBulkRun() {
  const { launch } = useLaunchRun();
  return {
    tailorApproved: () =>
      launch("tailor", () =>
        unwrap(
          api.POST("/api/tailor", { body: { approved: true, jobIds: null } }),
        ),
      ),
    coverLettersApproved: () =>
      launch("coverLetter", () =>
        unwrap(
          api.POST("/api/cover-letters", {
            body: { approved: true, jobIds: null },
          }),
        ),
      ),
  };
}
```

(Match `TailorParams`/`CoverLetterParams` field names from the contract; drop `jobIds` if the schema treats it as optional.)

In `web/src/features/pipeline/PipelineContainer.tsx`, add to the header area (after `<PageHeader .../>`):

```tsx
import { Button } from "@/components/ui/button";
import { useBulkRun } from "@/features/runs/use-bulk-run";
// inside component:
const bulk = useBulkRun();
// in JSX, below PageHeader:
<div className="mb-4 flex gap-2">
  <Button variant="outline" onClick={bulk.tailorApproved}>
    Tailor approved
  </Button>
  <Button variant="outline" onClick={bulk.coverLettersApproved}>
    Cover letters (approved)
  </Button>
</div>;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/runs/use-bulk-run.test.tsx`
Expected: PASS. Then `npm run build` to confirm the Pipeline wiring compiles.

- [ ] **Step 5: Commit**

```bash
git add web/src/features
git commit -m "feat(web): contextual tailor + cover-letter run actions"
```

---

## Phase 7 — Analytics + Match-gap

### Task 7.1: Analytics page (table + chart)

**Files:** Create `web/src/features/analytics/{AnalyticsContainer}.tsx`, `use-analytics.ts`, rewrite `AnalyticsPage.tsx` + test.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/analytics/AnalyticsContainer.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { AnalyticsContainer } from "./AnalyticsContainer";

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

describe("AnalyticsContainer", () => {
  it("renders an accessible source table", async () => {
    server.use(
      http.get("/api/analytics", () =>
        HttpResponse.json({
          bySource: [
            {
              label: "greenhouse",
              applications: 10,
              responses: 4,
              interviews: 2,
              offers: 1,
              responseRate: 40,
              interviewRate: 20,
              offerRate: 10,
            },
          ],
          byBand: [],
        }),
      ),
    );
    wrap(<AnalyticsContainer />);
    await waitFor(() =>
      expect(
        screen.getByRole("table", { name: /by source/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("greenhouse")).toBeInTheDocument();
  });
  it("shows empty state when no applications", async () => {
    server.use(
      http.get("/api/analytics", () =>
        HttpResponse.json({ bySource: [], byBand: [] }),
      ),
    );
    wrap(<AnalyticsContainer />);
    await waitFor(() =>
      expect(screen.getByText(/no applications tracked/i)).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/analytics/AnalyticsContainer.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `web/src/features/analytics/use-analytics.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type Analytics = components["schemas"]["AnalyticsOut"];

export function useAnalytics() {
  return useQuery({
    queryKey: ["analytics"],
    queryFn: (): Promise<Analytics> =>
      unwrap(api.GET("/api/analytics", {})) as Promise<Analytics>,
  });
}
```

Create `web/src/features/analytics/AnalyticsContainer.tsx`:

```tsx
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { useAnalytics } from "./use-analytics";
import type { components } from "@/lib/api/schema";

type Cohort = components["schemas"]["CohortOut"];

function CohortTable({
  caption,
  header,
  rows,
}: {
  caption: string;
  header: string;
  rows: Cohort[];
}) {
  return (
    <Table>
      <caption className="mb-2 text-left font-mono text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
        {caption}
      </caption>
      <TableHeader>
        <TableRow>
          <TableHead>{header}</TableHead>
          <TableHead>Apps</TableHead>
          <TableHead>Responses</TableHead>
          <TableHead>Interviews</TableHead>
          <TableHead>Offers</TableHead>
          <TableHead>Interview %</TableHead>
          <TableHead>Offer %</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((c) => (
          <TableRow key={c.label}>
            <TableCell>{c.label}</TableCell>
            <TableCell>{c.applications}</TableCell>
            <TableCell>{c.responses}</TableCell>
            <TableCell>{c.interviews}</TableCell>
            <TableCell>{c.offers}</TableCell>
            <TableCell>{c.interviewRate}</TableCell>
            <TableCell>{c.offerRate}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function AnalyticsContainer() {
  const { data, isLoading } = useAnalytics();
  if (isLoading) return <Skeleton className="h-64 w-full" />;
  const totalApps = data?.bySource.reduce((a, c) => a + c.applications, 0) ?? 0;
  const totalOffers = data?.bySource.reduce((a, c) => a + c.offers, 0) ?? 0;
  return (
    <>
      <PageHeader
        kicker="Conversion"
        title="Analytics / Funnel"
        sub="Which sources and fit-score bands actually convert. Rates are share of submitted applications."
      />
      <MetricRow
        items={[
          ["Submitted", String(totalApps)],
          ["Offers", String(totalOffers)],
          ["Sources tracked", String(data?.bySource.length ?? 0)],
        ]}
      />
      {totalApps === 0 ? (
        <EmptyState
          title="No applications tracked yet"
          body="Mark applications as submitted in the Pipeline board to populate analytics."
        />
      ) : (
        <div className="space-y-8">
          <CohortTable
            caption="By source"
            header="Source"
            rows={data!.bySource}
          />
          <CohortTable
            caption="By fit-score band"
            header="Fit band"
            rows={data!.byBand}
          />
        </div>
      )}
    </>
  );
}
```

Rewrite `web/src/features/analytics/AnalyticsPage.tsx`:

```tsx
import { AnalyticsContainer } from "./AnalyticsContainer";
export function AnalyticsPage() {
  return <AnalyticsContainer />;
}
```

- [ ] **Step 3b: Add the funnel chart (visual enhancement over the canonical table)**

Create `web/src/features/analytics/ConversionChart.tsx` using the shadcn `chart` wrapper (recharts). The table above remains the accessible source of truth; this chart is supplementary and marked `aria-hidden`.

```tsx
import { Bar, BarChart, XAxis, YAxis } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { components } from "@/lib/api/schema";

type Cohort = components["schemas"]["CohortOut"];

const config: ChartConfig = {
  applications: { label: "Apps", color: "var(--muted-foreground)" },
  interviews: { label: "Interviews", color: "var(--primary)" },
  offers: { label: "Offers", color: "var(--foreground)" },
};

export function ConversionChart({ rows }: { rows: Cohort[] }) {
  return (
    <div aria-hidden="true">
      <ChartContainer config={config} className="h-56 w-full">
        <BarChart data={rows} accessibilityLayer>
          <XAxis dataKey="label" tickLine={false} axisLine={false} />
          <YAxis allowDecimals={false} width={28} />
          <ChartTooltip content={<ChartTooltipContent />} />
          <Bar
            dataKey="applications"
            fill="var(--color-applications)"
            radius={4}
          />
          <Bar dataKey="interviews" fill="var(--color-interviews)" radius={4} />
          <Bar dataKey="offers" fill="var(--color-offers)" radius={4} />
        </BarChart>
      </ChartContainer>
    </div>
  );
}
```

Render it in `AnalyticsContainer` above the "By source" table (only when `totalApps > 0`):

```tsx
import { ConversionChart } from "./ConversionChart";
// inside the non-empty branch, before <CohortTable caption="By source" ...>:
<ConversionChart rows={data!.bySource} />;
```

`recharts` is a transitive dependency of the shadcn `chart` component installed in Task 1.2; if `npx tsc` reports it missing, run `npm install recharts`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/analytics/AnalyticsContainer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/analytics
git commit -m "feat(web): Analytics page — accessible cohort tables"
```

---

### Task 7.2: Match-gap page

**Files:** Create `web/src/features/match-gap/{MatchGapContainer}.tsx`, `use-match-gap.ts`, rewrite `MatchGapPage.tsx` + test.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/match-gap/MatchGapContainer.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/server";
import { MatchGapContainer } from "./MatchGapContainer";

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

describe("MatchGapContainer", () => {
  it("lists missing skills with demand share", async () => {
    server.use(
      http.get("/api/match-gap", () =>
        HttpResponse.json({
          targetTotal: 4,
          gaps: [
            {
              skill: "Kubernetes",
              demandCount: 3,
              targetTotal: 4,
              demandShare: 75,
            },
          ],
        }),
      ),
    );
    wrap(<MatchGapContainer />);
    await waitFor(() =>
      expect(screen.getByText("Kubernetes")).toBeInTheDocument(),
    );
    expect(screen.getByText("75")).toBeInTheDocument();
  });
  it("shows no-profile empty state when targetTotal is 0", async () => {
    server.use(
      http.get("/api/match-gap", () =>
        HttpResponse.json({ targetTotal: 0, gaps: [] }),
      ),
    );
    wrap(<MatchGapContainer />);
    await waitFor(() =>
      expect(screen.getByText(/no target jobs yet/i)).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- --run src/features/match-gap/MatchGapContainer.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `web/src/features/match-gap/use-match-gap.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type MatchGap = components["schemas"]["MatchGapOut"];

export function useMatchGap() {
  return useQuery({
    queryKey: ["match-gap"],
    queryFn: (): Promise<MatchGap> =>
      unwrap(api.GET("/api/match-gap", {})) as Promise<MatchGap>,
  });
}
```

Create `web/src/features/match-gap/MatchGapContainer.tsx`:

```tsx
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { useMatchGap } from "./use-match-gap";

export function MatchGapContainer() {
  const { data, isLoading } = useMatchGap();
  if (isLoading) return <Skeleton className="h-64 w-full" />;
  return (
    <>
      <PageHeader
        kicker="Closed loop"
        title="Match / Gap"
        sub="Skills your target jobs demand that your profile does not show yet. Read-only."
      />
      <MetricRow
        items={[
          ["Target jobs", String(data?.targetTotal ?? 0)],
          ["Distinct gaps", String(data?.gaps.length ?? 0)],
        ]}
      />
      {!data || data.targetTotal === 0 ? (
        <EmptyState
          title="No target jobs yet"
          body="Shortlist or approve jobs to populate the gap report."
        />
      ) : data.gaps.length === 0 ? (
        <EmptyState
          title="No gaps"
          body="Your profile covers every required skill across your target jobs."
        />
      ) : (
        <Table>
          <caption className="mb-2 text-left font-mono text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
            Most-demanded missing skills
          </caption>
          <TableHeader>
            <TableRow>
              <TableHead>Skill</TableHead>
              <TableHead>Demanded by</TableHead>
              <TableHead>Share %</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.gaps.map((g) => (
              <TableRow key={g.skill}>
                <TableCell>{g.skill}</TableCell>
                <TableCell>
                  {g.demandCount}/{g.targetTotal}
                </TableCell>
                <TableCell>{g.demandShare}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  );
}
```

Rewrite `web/src/features/match-gap/MatchGapPage.tsx`:

```tsx
import { MatchGapContainer } from "./MatchGapContainer";
export function MatchGapPage() {
  return <MatchGapContainer />;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm run test -- --run src/features/match-gap/MatchGapContainer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/match-gap
git commit -m "feat(web): Match-gap page"
```

---

## Phase 8 — A11y, E2E, build wiring, retirement

### Task 8.1: axe-core a11y assertions on each page

**Files:** Create `web/src/test/a11y.test.tsx`.

- [ ] **Step 1: Write the test**

Create `web/src/test/a11y.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { axe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { server } from "./server";
import { ShortlistContainer } from "@/features/shortlist/ShortlistContainer";

const wrap = (ui: React.ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("a11y", () => {
  it("shortlist (empty) has no axe violations", async () => {
    server.use(
      http.get("/api/shortlist", () =>
        HttpResponse.json({
          data: [],
          pagination: { page: 1, pageSize: 200, totalItems: 0, totalPages: 0 },
        }),
      ),
    );
    const { container, findByText } = wrap(<ShortlistContainer />);
    await findByText(/nothing shortlisted yet/i);
    expect(await axe(container)).toHaveNoViolations();
  });
});
```

Add the matcher in `web/src/test/setup.ts`:

```ts
import * as matchers from "vitest-axe/matchers";
import { expect } from "vitest";
expect.extend(matchers);
```

- [ ] **Step 2: Run + fix violations**

Run: `cd web && npm run test -- --run src/test/a11y.test.tsx`
Expected: PASS. If violations appear, fix the offending component (labels, roles, contrast) before continuing.

- [ ] **Step 3: Commit**

```bash
git add web/src/test
git commit -m "test(web): axe-core a11y assertions"
```

---

### Task 8.2: Playwright E2E smoke (mocked backend)

**Files:** Create `web/playwright.config.ts`, `web/e2e/smoke.spec.ts`.

- [ ] **Step 1: Install**

Run: `cd web && npm install -D @playwright/test && npx playwright install chromium`

- [ ] **Step 2: Config + spec**

Create `web/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:4173" },
  webServer: {
    command: "npm run build && npm run preview -- --port 4173",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
```

Create `web/e2e/smoke.spec.ts`:

```ts
import { test, expect } from "@playwright/test";

// Intercept the API so the smoke test is hermetic.
test.beforeEach(async ({ page }) => {
  await page.route("**/api/shortlist*", (route) =>
    route.fulfill({
      json: {
        data: [
          {
            jobId: 1,
            company: "Acme",
            title: "Staff Engineer",
            location: "Remote",
            fitScore: 81,
            skills: [],
          },
        ],
        pagination: { page: 1, pageSize: 200, totalItems: 1, totalPages: 1 },
      },
    }),
  );
});

test("loads shortlist and opens a job drawer", async ({ page }) => {
  await page.route("**/api/jobs/1", (route) =>
    route.fulfill({
      json: {
        id: 1,
        source: "greenhouse",
        url: null,
        company: "Acme",
        title: "Staff Engineer",
        location: "Remote",
        jdText: "Build.",
        status: "shortlisted",
        fitScore: 81,
        fitRationale: null,
        criteriaJson: null,
        postedAt: null,
        archivedAt: null,
        createdAt: "2026-06-01T00:00:00Z",
        hasProgress: false,
        application: null,
        resumeVersions: [],
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("Staff Engineer")).toBeVisible();
  await page.getByText("Staff Engineer").click();
  await expect(
    page.getByRole("heading", { name: /staff engineer/i }),
  ).toBeVisible();
});
```

- [ ] **Step 3: Run**

Run: `cd web && npm run e2e`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/playwright.config.ts web/e2e web/package.json web/package-lock.json
git commit -m "test(web): Playwright smoke (mocked API)"
```

---

### Task 8.3: Full suites + lint gate

- [ ] **Step 1: Web unit suite**

Run: `cd web && npm run test:run`
Expected: all PASS.

- [ ] **Step 2: Web typecheck + build**

Run: `cd web && npx tsc --noEmit && npm run build`
Expected: no type errors; `dist/` built.

- [ ] **Step 3: Backend suite + lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: all PASS, no lint errors.

- [ ] **Step 4: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "chore: green full web + backend suites"
```

---

### Task 8.4: Wire contract copy into the gen script

**Files:** Modify `scripts/gen_ts_client.sh`.

- [ ] **Step 1: Append the copy step**

Add to the end of `scripts/gen_ts_client.sh` (after the `openapi-typescript` line):

```bash
# Keep the SPA's local copy in sync with the committed contract.
if [ -d web/src/lib/api ]; then
  cp contracts/ts/api.ts web/src/lib/api/schema.ts
  echo "Copied contract to web/src/lib/api/schema.ts"
fi
```

- [ ] **Step 2: Verify**

Run: `bash scripts/gen_ts_client.sh && git diff --stat`
Expected: regenerates and copies; `web/src/lib/api/schema.ts` updates if the contract changed.

- [ ] **Step 3: Commit**

```bash
git add scripts/gen_ts_client.sh web/src/lib/api/schema.ts
git commit -m "chore(contracts): copy generated client into web/ on regen"
```

---

### Task 8.5: Retire Streamlit

**Files:** Delete `src/resume_tailor_harness/dashboard/`; modify `pyproject.toml` (drop the `dashboard`/`streamlit` entrypoint + dep); modify `CLAUDE.md`.

Do this ONLY after the SPA is verified at parity in a manual run (`resume-tailor-harness serve`, build present, click through all five pages + launch a run).

- [ ] **Step 1: Confirm parity manually**

Run: `cd web && npm run build && cd .. && .venv/Scripts/python.exe -m resume_tailor_harness serve` (or `resume-tailor-harness serve`), open `http://127.0.0.1:8000`, verify all five pages render, a job drawer opens, and a Pull run streams progress.

- [ ] **Step 2: Remove the Streamlit code + entrypoint**

```bash
git rm -r src/resume_tailor_harness/dashboard
```

Remove the Streamlit dependency and any `dashboard` script/entrypoint from `pyproject.toml`. Search for residual imports:

Run: `grep -rn "resume_tailor_harness.dashboard\|streamlit" src tests pyproject.toml`
Expected after edits: no hits in `src`/`pyproject.toml` (delete or port any test that imported the dashboard).

- [ ] **Step 3: Update docs**

In `CLAUDE.md`, update the "third thin adapter" wording to reflect that the SPA (`web/`) replaces Streamlit as the human UI over the API; note `web/` build + `resume-tailor-harness serve` serving it.

- [ ] **Step 4: Verify**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: retire Streamlit dashboard in favor of web/ SPA"
```

---

## Self-review notes (coverage map)

- Spec §2 stack/layout → Phase 1. Serving model → Task 0.6 + 8.5 manual.
- Spec §3 backend changes → Tasks 0.1–0.7.
- Spec §4 IA (sidebar, topbar, drawer) → Tasks 1.4, 5.1; drawer deep-link via `?job=` → Tasks 4.4/4.5/4.6.
- Spec §5 parity table → Shortlist 4.4, Pipeline 4.6, Triage 4.5, Analytics 7.1, Match-gap 7.2; ported filter engine → Phase 2.
- Spec §6 run control + SSE → Phase 6.
- Spec §7 design tokens → Task 1.2; primitives → Phase 3.
- Spec §8 a11y → embedded per component + Task 8.1; progressbar/aria-live → Task 6.2; canonical table for charts → 7.1.
- Spec §9 cross-cutting (auth, errors, skeletons, optimistic, component size, perf) → Tasks 1.3, 1.4, 4.4, 5.1.
- Spec §10 responsive → grid breakpoints in board containers + sidebar `md:` in 1.4.
- Spec §11 testing → Phase 8 + per-task tests.
- Spec §12 retirement → Task 8.5.

**Known follow-ups (not blockers):** the FilterDesk industry division→group narrowing (Task 4.3 note) is a parity-optional enhancement; SSE payload field names must be reconciled with `api/runs/sse.py` during Task 6.1.

---

## frontend-ui-engineering review pass (applied)

**Bugs fixed in-plan:**

1. **Filter-engine port mismatch (Task 2.4):** `availableSkillCloud` ordering and its test contradicted the Python source key `(not covered, name)`. Corrected to covered-first with a clean comparator and matching test — preserves "verbatim behavior" parity.
2. **Stale boards after delete (Task 4.5):** `useDeleteJob` invalidated only `triage`; since delete is reachable from the drawer over any board, it now invalidates `shortlist`, `pipeline`, and `triage`.
3. **No mobile navigation (Task 1.4):** the hand-rolled `<aside>` was `hidden md:block`, leaving zero navigation below 768px. Replaced with the shadcn `Sidebar` primitive (mobile sheet + trigger + `Cmd/Ctrl+B`), restoring §10 responsive integrity.
4. **Deprecated `toast` installed (Task 1.2):** dropped in favor of `sonner`.

**User-friendly `ui/` components adopted (real registry components, verified present):**

- `Sidebar` (+ `SidebarProvider`/`SidebarInset`/`SidebarTrigger`) — collapsible, keyboard- and mobile-aware nav (ref: `cards/sidebar-nav.tsx`).
- Content-shaped `Skeleton` compositions `BoardSkeleton`/`DrawerSkeleton` (Task 3.4) replacing generic grey blocks (ref: `cards/skeleton/*`) — satisfies the skill's loading-state guidance.
- `AlertDialog`-based `ConfirmDialog` (Task 3.5) replacing `window.confirm` for all destructive actions — focus-trapped, keyboard-dismissible.
- `Tooltip` (+ `TooltipProvider`) on icon-only buttons.
- `Progress` for live run bars (Task 6.2) — native `role="progressbar"` + `aria-valuenow`.
- `chart` (recharts wrapper) for the Analytics funnel (Task 7.1 Step 3b), with the data table kept as the canonical accessible representation.
- `sonner` `Toaster` for all success/error feedback (Providers).

**Coverage delta:** new Tasks 3.4 and 3.5; Tasks 1.2, 1.4, 6.2, 7.1, and the Providers/ThemeToggle code updated. All other tasks unchanged.
