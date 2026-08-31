# Board UX, Async Revise, Import Surfaces, Company Names — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the four approved workstreams of
`docs/superpowers/specs/2026-07-12-board-ux-async-revise-import-company-names-design.md`:
board quick actions + list view, revise-as-background-run, four import/export
surfaces, and company display-name resolution/heal/backfill.

**Architecture:** Four independent workstreams sharing almost no code; tasks
are independently green and can execute in any order within a workstream.
Backend follows existing seams (RunManager submit, merge `decide`, backup
staging, CamelModel schemas); frontend follows existing container/presenter +
TanStack Query + zustand run-store patterns.

**Tech Stack:** FastAPI + SQLModel + pytest (offline; agents/browser faked);
React + TypeScript + TanStack Query + zustand + sonner + msw/vitest; Typer CLI;
openapi-typescript contract generation.

## Global Constraints

- Python tests: `.venv/Scripts/python.exe -m pytest <file> -v` (run from repo root; whole suite must stay green).
- Web tests: `cd web && npx vitest run <file>`.
- Lint: `ruff check` must pass before every commit.
- Wire format is camelCase (CamelModel `alias_generator=to_camel`); Python stays snake_case.
- After any change to `api/schemas/*` or router response models: run `bash scripts/gen_ts_client.sh` and include `contracts/openapi.json` + `contracts/ts/api.ts` in the commit; `tests/api/test_openapi_contract.py` is the drift gate.
- Errors use the envelope `{ "error": { code, message, details? } }` via `ApiException(status, code, message, details=None)`.
- Run kinds use the existing camelCase vocabulary: new kinds are `revise`, `coverLetterRevise`, `importUrls` (the spec's snake_case names adapted to convention).
- Never touch `jd_text`, status, Application, ResumeVersion, or CoverLetter from any W4 rename path.
- No new dependencies.

## Correctness Amendments (2026-07-13 repository audit)

These amendments override conflicting snippets later in the plan. They were
validated against the current repository before implementation.

- Extend current surfaces instead of recreating them: `JobTable.test.tsx` and
  `GET /api/account/export` already exist. Task 10 adds the missing import path
  and strengthens round-trip tests; it does not add another export router.
- Revision singleton conflicts use the public error code `CONFLICT`, as the
  design specifies, with `details.runId`. The router-level 409 envelope must be
  tested with a held run; a manager-only test is insufficient API proof.
- Reload-safe revision UI requires artifact metadata to be persisted in the
  server run record and projected through `RunOut`. Client-only zustand metadata
  disappears on reload, so Task 9 must rehydrate `meta` from `GET /api/runs` and
  must implement the promised pending placeholder, failure retry, and completed
  child highlight (not only an inline spinner).
- Workspace import must use `workspace_paths(data_dir, user_id)`, evict the
  caller's engine before the swap, initialize/validate a fresh engine after the
  swap, and rebind the rolled-back workspace if validation fails. Merely
  evicting before `import_data_root` can leave the caller with an unvalidated or
  unbound database.
- New multipart paths use bounded reads/copies. CSV/JSON rows validate scalar
  field types and invalid dates per row; malformed rows become report errors
  instead of aborting the whole import. URL-list imports preserve invalid lines
  as per-line failures rather than silently dropping them.
- Admin/workspace replacement uses a real typed destructive-confirm dialog and
  keeps it open on server failure so the verbatim envelope message is visible.
  Inline inputs alone do not satisfy the approved interaction.
- Board query invalidation awaits all matching prefixes. Archive Undo is itself
  error-handled and reports a failed restore; no floating rejected promise.
- View toggles use the installed Base UI `ToggleGroup`, preserve unrelated URL
  parameters, and use replace navigation for a presentation preference. Links
  remain semantic anchors styled with `buttonVariants`; Base UI `Button`
  `render={<a>}` incorrectly forces `role=button`.
- Workday already reads `jobPostingInfo.companyName` (not `company`); Task 18
  adds fallback provenance (`stale_company`) without regressing that behavior.
  Ashby's current posting payload has no organization field, so configured
  label/token remains the supported precedence.
- Configured company labels preserve the connector's deepest fallback
  provenance (`job.stale_company or job.company`). Rename collision detection is
  one shared DB helper used by organic heal and CLI backfill, including the
  exact compatible live keeper in conflict reports; do not duplicate predicates.
- Backfill covers every configured source unit that exposes a label/token pair,
  including detected `companies` and native Workday entries, and compares token
  names literally/case-insensitively (not wildcard `ILIKE`).
- The duplicate/corrupted preliminary Task 19 block has been removed; the single
  complete Task 19 below is authoritative.

---

## Workstream 1 — Board quick actions + view toggle

### Task 1: `url` on the three board row DTOs and API schemas

**Files:**

- Modify: `src/resume_tailor_harness/tracking/queries.py` (ShortlistRow, TriageRow, PipelineRow dataclasses + their constructor sites)
- Modify: `src/resume_tailor_harness/api/schemas/jobs.py` (ShortlistItem, TriageItem, PipelineItem)
- Test: `tests/test_queries_row_url.py` (new)
- Regenerate: `contracts/openapi.json`, `contracts/ts/api.ts`

**Interfaces:**

- Produces: `ShortlistRow.url`, `TriageRow.url`, `PipelineRow.url` (`str | None`, default `None`); `ShortlistItem.url`, `TriageItem.url`, `PipelineItem.url` (`str | None = None`, camelCase wire field `url`). Tasks 3–5 rely on `row.url` in the web `components["schemas"]` types.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_queries_row_url.py
from resume_tailor_harness.api.schemas.jobs import PipelineItem, ShortlistItem, TriageItem
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.tracking.queries import pipeline_rows, triage_rows
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def _job(**overrides) -> Job:
    fields = dict(
        source="greenhouse",
        jd_text="We build things.",
        url="https://boards.greenhouse.io/acme/jobs/1",
        company="Acme",
        title="Platform Engineer",
        status=JobStatus.raw.value,
    )
    fields.update(overrides)
    return Job(**fields)


def test_triage_and_pipeline_rows_carry_url():
    with _session() as session:
        session.add(_job())
        session.commit()
        t_rows = triage_rows(session)
        p_rows = pipeline_rows(session)
    assert t_rows[0].url == "https://boards.greenhouse.io/acme/jobs/1"
    assert p_rows[0].url == "https://boards.greenhouse.io/acme/jobs/1"


def test_schemas_project_url():
    assert "url" in ShortlistItem.model_fields
    assert "url" in TriageItem.model_fields
    assert "url" in PipelineItem.model_fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_queries_row_url.py -v`
Expected: FAIL (`AttributeError: 'TriageRow' object has no attribute 'url'` / assertion on model_fields)

- [ ] **Step 3: Implement**

In `src/resume_tailor_harness/tracking/queries.py`:

- Add `url: str | None = None` as the **last** field of `ShortlistRow`, `TriageRow`, and `PipelineRow` (they already end with defaulted fields; keep dataclass default ordering valid).
- In `_shortlist_row(...)` (the constructor `shortlist_rows`/`job_detail_row` share), `_triage_row(...)`, and the `PipelineRow(...)` construction inside `pipeline_rows`, add `url=job.url,`.

In `src/resume_tailor_harness/api/schemas/jobs.py`, add to each of `ShortlistItem`, `TriageItem`, `PipelineItem`:

```python
    url: str | None = None
```

- [ ] **Step 4: Run tests + regenerate contracts**

Run: `.venv/Scripts/python.exe -m pytest tests/test_queries_row_url.py tests/api/test_openapi_contract.py -v`
Expected: url test PASS, contract test FAIL (drift) → run `bash scripts/gen_ts_client.sh` → re-run both → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/queries.py src/resume_tailor_harness/api/schemas/jobs.py tests/test_queries_row_url.py contracts/openapi.json contracts/ts/api.ts
git commit -m "feat: expose job url on shortlist/triage/pipeline rows"
```

---

### Task 2: `useArchiveJob` mutation with undo toast

**Files:**

- Create: `web/src/features/board/use-archive-job.ts`
- Test: `web/src/features/board/use-archive-job.test.tsx`

**Interfaces:**

- Consumes: `PATCH /api/jobs/{job_id}` with body `{ archived: boolean }` (exists).
- Produces: `useArchiveJob(): UseMutationResult` accepting `{ jobId: number; archived?: boolean }` (default `archived: true`). Success invalidates `["shortlist"]`, `["pipeline"]`, `["triage"]`, `["job"]` and shows a sonner toast with an **Undo** action that re-PATCHes `{ archived: false }`. Tasks 3–5 call this hook.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/board/use-archive-job.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";

import { useArchiveJob } from "./use-archive-job";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useArchiveJob", () => {
  it("PATCHes archived=true by default", async () => {
    let received: Record<string, unknown> | undefined;
    server.use(
      http.patch("/api/jobs/7", async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({});
      }),
    );
    const { result } = renderHook(() => useArchiveJob(), { wrapper });
    result.current.mutate({ jobId: 7 });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(received).toMatchObject({ archived: true });
  });

  it("PATCHes archived=false for restore", async () => {
    let received: Record<string, unknown> | undefined;
    server.use(
      http.patch("/api/jobs/7", async ({ request }) => {
        received = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({});
      }),
    );
    const { result } = renderHook(() => useArchiveJob(), { wrapper });
    result.current.mutate({ jobId: 7, archived: false });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(received).toMatchObject({ archived: false });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/board/use-archive-job.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

```ts
// web/src/features/board/use-archive-job.ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";

const BOARD_KEYS = ["shortlist", "pipeline", "triage", "job"];

function patchArchived(jobId: number, archived: boolean) {
  return unwrap(
    api.PATCH("/api/jobs/{job_id}", {
      params: { path: { job_id: jobId } },
      body: { archived },
    }),
  );
}

/** Archive (default) or restore one job, with an Undo action on the toast. */
export function useArchiveJob() {
  const qc = useQueryClient();
  const invalidate = () => {
    for (const k of BOARD_KEYS) qc.invalidateQueries({ queryKey: [k] });
  };
  return useMutation({
    mutationFn: (vars: { jobId: number; archived?: boolean }) =>
      patchArchived(vars.jobId, vars.archived ?? true),
    onSuccess: (_data, vars) => {
      invalidate();
      const archived = vars.archived ?? true;
      if (archived) {
        toast.success("Job archived", {
          action: {
            label: "Undo",
            onClick: () => {
              void patchArchived(vars.jobId, false).then(invalidate);
            },
          },
        });
      } else {
        toast.success("Job restored");
      }
    },
    onError: () => toast.error("Failed to update job"),
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/board/use-archive-job.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add web/src/features/board/use-archive-job.ts web/src/features/board/use-archive-job.test.tsx
git commit -m "feat(web): archive/restore mutation with undo toast"
```

---

### Task 3: JobTable actions column + Triage row actions (archive/restore, delete, open posting)

**Files:**

- Modify: `web/src/components/JobTable.tsx`
- Create: `web/src/features/board/use-delete-job.ts`
- Modify: `web/src/features/triage/TriageContainer.tsx`
- Test: `web/src/components/JobTable.test.tsx` (new), `web/src/features/board/use-delete-job.test.tsx` (new)

**Interfaces:**

- Consumes: `useArchiveJob` (Task 2), `DELETE /api/jobs/{job_id}` (exists; 409s on progressed jobs with envelope message), `row.url` (Task 1).
- Produces: `JobTable` prop `actions?: (row: Row) => ReactNode` (adds a trailing right-aligned column when present; `Row` type gains `url?: string | null`); `useDeleteJob(): UseMutationResult` accepting `jobId: number`, surfacing the API error message via toast. Tasks 4–5 reuse both.

- [ ] **Step 1: Write the failing tests**

```tsx
// web/src/components/JobTable.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobTable } from "./JobTable";

const rows = [
  {
    jobId: 1,
    company: "Acme",
    title: "Engineer",
    fitScore: 80,
    url: "https://x.test/1",
  },
];
const selection = { isSelected: () => false };

describe("JobTable actions column", () => {
  it("renders the actions cell when the prop is present", () => {
    render(
      <JobTable
        rows={rows}
        selection={selection}
        onToggle={vi.fn()}
        onOpen={vi.fn()}
        actions={(row) => <button type="button">act-{row.jobId}</button>}
      />,
    );
    expect(screen.getByRole("button", { name: "act-1" })).toBeInTheDocument();
  });

  it("renders no actions column without the prop", () => {
    render(
      <JobTable
        rows={rows}
        selection={selection}
        onToggle={vi.fn()}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByText("Actions")).not.toBeInTheDocument();
  });
});
```

```tsx
// web/src/features/board/use-delete-job.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";

import { useDeleteJob } from "./use-delete-job";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useDeleteJob", () => {
  it("DELETEs the job", async () => {
    let called = false;
    server.use(
      http.delete("/api/jobs/9", () => {
        called = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { result } = renderHook(() => useDeleteJob(), { wrapper });
    result.current.mutate(9);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(called).toBe(true);
  });

  it("surfaces the API refusal as an error", async () => {
    server.use(
      http.delete("/api/jobs/9", () =>
        HttpResponse.json(
          { error: { code: "HAS_PROGRESS", message: "Job has progress" } },
          { status: 409 },
        ),
      ),
    );
    const { result } = renderHook(() => useDeleteJob(), { wrapper });
    result.current.mutate(9);
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/components/JobTable.test.tsx src/features/board/use-delete-job.test.tsx`
Expected: FAIL (unknown prop typing / module not found)

- [ ] **Step 3: Implement**

In `web/src/components/JobTable.tsx`:

- Add `url?: string | null;` to the `Row` type.
- Add `actions?: (row: Row) => ReactNode;` to the props (import `ReactNode` from react).
- In the header row, after the Status head: `{actions && <TableHead className="text-right">Actions</TableHead>}`.
- In the body row, after the Status cell:

```tsx
{
  actions && (
    <TableCell
      className="text-right"
      onClick={(event) => event.stopPropagation()}
    >
      <div className="flex justify-end gap-1">{actions(row)}</div>
    </TableCell>
  );
}
```

```ts
// web/src/features/board/use-delete-job.ts
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";

const BOARD_KEYS = ["shortlist", "pipeline", "triage", "job"];

/** Delete one job; the API refuses jobs with progress and we surface its message. */
export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      unwrap(
        api.DELETE("/api/jobs/{job_id}", {
          params: { path: { job_id: jobId } },
        }),
      ),
    onSuccess: () => {
      for (const k of BOARD_KEYS) qc.invalidateQueries({ queryKey: [k] });
      toast.success("Job deleted");
    },
    onError: (error) => toast.error((error as Error).message),
  });
}
```

In `web/src/features/triage/TriageContainer.tsx`:

- Import `Archive, ArchiveRestore, ExternalLink, Trash2` from `lucide-react`, `Button` (already), `ConfirmDialog` from `@/components/ConfirmDialog`, `useArchiveJob` and `useDeleteJob` from `@/features/board/...`.
- Instantiate `const archiveJob = useArchiveJob(); const deleteJob = useDeleteJob();` inside the component.
- Pass to `JobTable`:

```tsx
actions={(row) => (
  <>
    {row.url && (
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label="Open posting"
        render={<a href={row.url} target="_blank" rel="noreferrer noopener"><ExternalLink aria-hidden="true" /></a>}
      />
    )}
    <Button
      size="icon-sm"
      variant="ghost"
      aria-label={archived ? "Restore job" : "Archive job"}
      onClick={() => archiveJob.mutate({ jobId: row.jobId, archived: !archived })}
    >
      {archived ? <ArchiveRestore aria-hidden="true" /> : <Archive aria-hidden="true" />}
    </Button>
    <ConfirmDialog
      trigger={
        <Button size="icon-sm" variant="ghost" aria-label="Delete job">
          <Trash2 aria-hidden="true" />
        </Button>
      }
      title="Delete this job?"
      description="Deletion is permanent. Jobs with progress are refused by the API."
      confirmLabel="Delete"
      onConfirm={async () => {
        await deleteJob.mutateAsync(row.jobId);
      }}
    />
  </>
)}
```

(Match `ConfirmDialog`'s actual prop names to its existing usage in `web/src/features/admin/AdminPage.tsx` — trigger/title/description/confirmLabel/onConfirm.)

- [ ] **Step 4: Run tests + the existing triage container test**

Run: `cd web && npx vitest run src/components/JobTable.test.tsx src/features/board/use-delete-job.test.tsx src/features/triage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/JobTable.tsx web/src/components/JobTable.test.tsx web/src/features/board/use-delete-job.ts web/src/features/board/use-delete-job.test.tsx web/src/features/triage/TriageContainer.tsx
git commit -m "feat(web): JobTable actions column + triage row actions"
```

---

### Task 4: Shortlist cards/list toggle + card footer action cluster

**Files:**

- Create: `web/src/features/board/use-view-mode.ts`
- Modify: `web/src/features/shortlist/ShortlistContainer.tsx`
- Modify: `web/src/components/JobCard.tsx` (no structural change needed — footer stays a prop; only the Shortlist's footer content changes)
- Test: `web/src/features/board/use-view-mode.test.tsx` (new)

**Interfaces:**

- Consumes: `useArchiveJob` (Task 2), `JobTable.actions` (Task 3), `row.url` (Task 1), existing `useApprove`.
- Produces: `useViewMode(storageKey?: string): ["cards" | "list", (v: "cards" | "list") => void]` — reads `view` URL search param, falls back to `localStorage[storageKey]` (default key `"board-view"`), defaults to `"cards"`; the setter writes both. Task 5 reuses it with key `"pipeline-view"`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/board/use-view-mode.test.tsx
import { renderHook, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { useViewMode } from "./use-view-mode";

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>;
}

describe("useViewMode", () => {
  beforeEach(() => localStorage.clear());

  it("defaults to cards", () => {
    const { result } = renderHook(() => useViewMode("t-view"), { wrapper });
    expect(result.current[0]).toBe("cards");
  });

  it("persists the choice to localStorage", () => {
    const { result } = renderHook(() => useViewMode("t-view"), { wrapper });
    act(() => result.current[1]("list"));
    expect(result.current[0]).toBe("list");
    expect(localStorage.getItem("t-view")).toBe("list");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/board/use-view-mode.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the hook**

```ts
// web/src/features/board/use-view-mode.ts
import { useSearchParams } from "react-router-dom";

export type ViewMode = "cards" | "list";

/** cards/list toggle: URL `view` param wins, then localStorage, then cards. */
export function useViewMode(
  storageKey = "board-view",
): [ViewMode, (v: ViewMode) => void] {
  const [params, setParams] = useSearchParams();
  const fromUrl = params.get("view");
  const stored = localStorage.getItem(storageKey);
  const mode: ViewMode =
    fromUrl === "list" || fromUrl === "cards"
      ? fromUrl
      : stored === "list"
        ? "list"
        : "cards";
  const setMode = (v: ViewMode) => {
    localStorage.setItem(storageKey, v);
    setParams(
      (p) => {
        p.set("view", v);
        return p;
      },
      { replace: true },
    );
  };
  return [mode, setMode];
}
```

- [ ] **Step 4: Wire the Shortlist**

In `web/src/features/shortlist/ShortlistContainer.tsx`:

- `const [view, setView] = useViewMode();` and `const archiveJob = useArchiveJob();` (imports from `@/features/board/use-view-mode` and `@/features/board/use-archive-job`; icons `LayoutGrid, List, Archive, ExternalLink` from lucide-react).
- Render a toggle right after `<FilterDesk … />`:

```tsx
<div className="mb-4 flex justify-end gap-1">
  <Button
    size="icon-sm"
    variant={view === "cards" ? "default" : "ghost"}
    aria-label="Card view"
    onClick={() => setView("cards")}
  >
    <LayoutGrid aria-hidden="true" />
  </Button>
  <Button
    size="icon-sm"
    variant={view === "list" ? "default" : "ghost"}
    aria-label="List view"
    onClick={() => setView("list")}
  >
    <List aria-hidden="true" />
  </Button>
</div>
```

- Extract the shared quick-action cluster as a local function:

```tsx
const quickActions = (row: ShortlistItem) => (
  <>
    {row.url && (
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label="Open posting"
        render={
          <a href={row.url} target="_blank" rel="noreferrer noopener">
            <ExternalLink aria-hidden="true" />
          </a>
        }
      />
    )}
    <Button
      size="icon-sm"
      variant="ghost"
      aria-label="Archive job"
      onClick={() => archiveJob.mutate({ jobId: row.jobId })}
    >
      <Archive aria-hidden="true" />
    </Button>
  </>
);
```

- Cards branch: keep the grid, change each card's `footer` to:

```tsx
footer={
  <div className="flex items-center gap-2">
    <Button className="flex-1" onClick={() => approve.mutate(row.jobId)}>
      Approve for tailoring
    </Button>
    {quickActions(row)}
  </div>
}
```

- List branch (`view === "list"`): render instead of the grid:

```tsx
<JobTable
  rows={rows}
  selection={selection}
  onToggle={(id, index, shift, ordered) =>
    selection.toggle(id, index, shift, ordered)
  }
  onOpen={openJob}
  onToggleAll={(checked) =>
    checked ? selection.selectPage(loadedIds) : selection.clear()
  }
  allChecked={
    rows.length > 0 && rows.every((r) => selection.isSelected(r.jobId))
  }
  actions={(row) => (
    <>
      <Button size="sm" onClick={() => approve.mutate(row.jobId)}>
        Approve
      </Button>
      {quickActions(row as ShortlistItem)}
    </>
  )}
/>
```

(`ShortlistItem` satisfies `JobTable`'s `Row`; `status`/`source` cells render "—".)

- [ ] **Step 5: Run the web suite for shortlist + new test, then commit**

Run: `cd web && npx vitest run src/features/board/use-view-mode.test.tsx src/features/shortlist`
Expected: PASS (existing container tests may need `MemoryRouter` already present — they render the container, adjust snapshots only if a test asserts the removed full-width footer button text; the "Approve for tailoring" text is still rendered in cards view).

```bash
git add web/src/features/board/use-view-mode.ts web/src/features/board/use-view-mode.test.tsx web/src/features/shortlist/ShortlistContainer.tsx
git commit -m "feat(web): shortlist cards/list toggle + quick actions"
```

---

### Task 5: Pipeline quick actions + per-stage list view

**Files:**

- Modify: `web/src/features/pipeline/PipelineContainer.tsx`
- Modify: `web/src/features/pipeline/PipelineStageSection.tsx`
- Modify: `web/src/features/pipeline/PipelineCard.tsx`
- Test: extend `web/src/features/pipeline/PipelineContainer.test.tsx`

**Interfaces:**

- Consumes: `useViewMode("pipeline-view")` (Task 4), `useArchiveJob` (Task 2), `JobTable.actions` (Task 3), `PipelineItem.url` (Task 1).
- Produces: `PipelineStageSection` props gain `view: "cards" | "list"` and `actions: (row: PipelineItem) => ReactNode`; `PipelineCard` props gain `footer?: ReactNode`.

- [ ] **Step 1: Write the failing test (extend the container test)**

Add to `web/src/features/pipeline/PipelineContainer.test.tsx` (follow the file's existing render/msw setup for board data; add one job row with `url`):

```tsx
it("shows per-row quick actions in list view", async () => {
  localStorage.setItem("pipeline-view", "list");
  renderPipeline(); // the file's existing render helper
  expect(
    await screen.findByRole("button", { name: "Archive job" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Open posting" }),
  ).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/pipeline/PipelineContainer.test.tsx`
Expected: FAIL (no such buttons)

- [ ] **Step 3: Implement**

`PipelineCard.tsx`: add `footer?: ReactNode` to the props type and render, immediately before the closing `</Card>` tag (mirroring `JobCard`):

```tsx
{
  footer && <div className="mt-auto border-t pt-4">{footer}</div>;
}
```

`PipelineStageSection.tsx`: add `view: "cards" | "list"` and `actions: (row: PipelineItem) => ReactNode` props. In `CollapsibleContent`, branch:

```tsx
{
  view === "list" ? (
    <div className="pt-4">
      <JobTable
        rows={rows}
        selection={{ isSelected: (id) => isSelected(id) }}
        onToggle={(id) => {
          const row = rows.find((r) => r.jobId === id);
          if (row) onSelect(row);
        }}
        onOpen={(id) => {
          const row = rows.find((r) => r.jobId === id);
          if (row) onOpen(row);
        }}
        actions={(row) => actions(row as PipelineItem)}
      />
    </div>
  ) : (
    <div className="grid grid-cols-1 gap-4 pt-4 xl:grid-cols-2 2xl:grid-cols-3">
      {rows.map((row) => (
        <PipelineCard
          key={row.jobId}
          row={row}
          selected={isSelected(row.jobId)}
          onSelect={() => onSelect(row)}
          onOpen={() => onOpen(row)}
          footer={<div className="flex justify-end gap-1">{actions(row)}</div>}
        />
      ))}
    </div>
  );
}
```

`PipelineContainer.tsx`: add `const [view, setView] = useViewMode("pipeline-view");` and `const archiveJob = useArchiveJob();`; render the same two-button toggle as Task 4 next to the "Tailor approved…" button row; define:

```tsx
const stageActions = (row: PipelineItem) => (
  <>
    {row.url && (
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label="Open posting"
        render={
          <a href={row.url} target="_blank" rel="noreferrer noopener">
            <ExternalLink aria-hidden="true" />
          </a>
        }
      />
    )}
    <Button
      size="icon-sm"
      variant="ghost"
      aria-label="Archive job"
      onClick={() => archiveJob.mutate({ jobId: row.jobId })}
    >
      <Archive aria-hidden="true" />
    </Button>
  </>
);
```

and pass `view={view} actions={stageActions}` to every `PipelineStageSection`.

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/features/pipeline`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/pipeline/
git commit -m "feat(web): pipeline quick actions + per-stage list view"
```

---

## Workstream 2 — Revision as a background run

### Task 6: `singleton_conflict="raise"` on RunManager.submit

**Files:**

- Modify: `src/resume_tailor_harness/api/runs/manager.py`
- Test: `tests/api/test_run_manager.py` (extend)

**Interfaces:**

- Produces: `RunSingletonConflict(Exception)` with attributes `run_id: str` and `code = "RUN_CONFLICT"`, exported from `manager.py`; `RunManager.submit(..., singleton_conflict: str = "join")` — `"join"` keeps today's return-existing-id behavior, `"raise"` raises `RunSingletonConflict(active_run_id)` when the singleton is active. Task 7/8 catch it in the router.

- [ ] **Step 1: Write the failing test (append to tests/api/test_run_manager.py, reusing its existing manager/executor fixtures — the file already constructs RunManager instances; follow its local pattern for a blocking work fn)**

```python
def test_singleton_conflict_raise_mode(manager_with_blocking_run):
    """Second submit with the same key raises instead of joining."""
    import pytest

    from resume_tailor_harness.api.runs.manager import RunSingletonConflict

    mgr, first_run_id, release = manager_with_blocking_run  # fixture: a run holding "k" active

    with pytest.raises(RunSingletonConflict) as exc_info:
        mgr.submit("revise", lambda reporter: None, singleton_key="k",
                   singleton_conflict="raise")
    assert exc_info.value.run_id == first_run_id
    release()
```

If the file has no blocking-run fixture, create the situation inline the way the file's other singleton tests do (submit a work fn that waits on a `threading.Event`, assert, then set the event).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -v -k singleton_conflict`
Expected: FAIL (`ImportError: cannot import name 'RunSingletonConflict'`)

- [ ] **Step 3: Implement**

In `manager.py`, next to `RunQuotaError`:

```python
class RunSingletonConflict(Exception):
    """A run with this singleton key is already active (raise-mode submits only)."""

    code = "RUN_CONFLICT"

    def __init__(self, run_id: str):
        super().__init__(f"run {run_id} is already active for this singleton key")
        self.run_id = run_id
```

In `submit`, add the keyword parameter `singleton_conflict: str = "join"`, and change the active-singleton branch:

```python
            if effective_singleton is not None:
                active_id = self._active_singletons.get(effective_singleton)
                if active_id is not None:
                    snapshot = self.get(active_id)
                    if snapshot is not None and snapshot.state in ACTIVE_RUN_STATES:
                        if singleton_conflict == "raise":
                            raise RunSingletonConflict(active_id)
                        return active_id
                    self._active_singletons.pop(effective_singleton, None)
```

- [ ] **Step 4: Run the whole run-manager test file**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_manager.py -v`
Expected: PASS (join-mode tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/runs/manager.py tests/api/test_run_manager.py
git commit -m "feat: raise-mode singleton conflicts on RunManager.submit"
```

---

### Task 7: Resume revise becomes a 202 background run

**Files:**

- Modify: `src/resume_tailor_harness/api/routers/runs.py` (new endpoint lives here, beside `_submit`/`_workspace_args`)
- Modify: `src/resume_tailor_harness/api/routers/resumes.py` (delete the old sync endpoint + now-unused imports)
- Test: `tests/api/test_runs_launch.py` (extend)
- Regenerate: contracts

**Interfaces:**

- Consumes: `RunSingletonConflict` (Task 6), `revise_resume_version(session, version_id, instruction, *, re_review, review_path, facts_path)` (exists), `ReviseRequest` schema (`instruction: str`, `re_review: bool` — exists in `api/schemas/jobs.py`), `get_resume_version(session, version_id)` (exists).
- Produces: `POST /api/resume-versions/{version_id}/revise` → 202 `RunOut`, kind `revise`, result `{"versionId": int | None, "jobId": int | None}`; 404 unknown version; 409 envelope code `RUN_CONFLICT` with `details={"runId": ...}` while a revise run for the same version is active. Task 9 consumes this contract.

- [ ] **Step 1: Write the failing tests (append to tests/api/test_runs_launch.py)**

```python
def test_revise_launch_returns_run(monkeypatch, tmp_path):
    from types import SimpleNamespace

    def fake_get_resume_version(session, version_id):
        return SimpleNamespace(id=version_id, job_id=3)

    def fake_revise(session, version_id, instruction, *, re_review=False, **kw):
        return SimpleNamespace(id=42, job_id=3)

    monkeypatch.setattr(runs_router, "get_resume_version", fake_get_resume_version)
    monkeypatch.setattr(runs_router, "revise_resume_version", fake_revise)
    client = _client(tmp_path)
    with client:
        resp = client.post(
            "/api/resume-versions/5/revise",
            json={"instruction": "shorter bullets", "reReview": False},
        )
        assert resp.status_code == 202
        run_id = resp.json()["runId"]
        got = client.get(f"/api/runs/{run_id}").json()
    assert got["kind"] == "revise"
    assert got["state"] == "done"
    assert got["result"] == {"versionId": 42, "jobId": 3}


def test_revise_unknown_version_404(monkeypatch, tmp_path):
    monkeypatch.setattr(runs_router, "get_resume_version", lambda session, vid: None)
    client = _client(tmp_path)
    with client:
        resp = client.post(
            "/api/resume-versions/999/revise", json={"instruction": "x", "reReview": False}
        )
    assert resp.status_code == 404
```

(The 409 path is proven at the manager level in Task 6; the InlineExecutor
completes runs synchronously, so an active-singleton state cannot be held
across two requests here.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py -v -k revise`
Expected: FAIL (405/404 — endpoint not in runs router; old sync endpoint returns 200 ResumeVersionOut)

- [ ] **Step 3: Implement**

In `runs.py`:

- Extend imports: `from resume_tailor_harness.api.runs.manager import RunManager, RunQuotaError, RunSingletonConflict`; `from resume_tailor_harness.api.schemas.jobs import ReviseRequest`; `from resume_tailor_harness.services.revision import revise_resume_version`; `from resume_tailor_harness.tracking.repository import get_resume_version`.
- Extend `_submit` with the conflict mode:

```python
def _submit(
    mgr: RunManager,
    kind: str,
    work,
    *,
    singleton_key: str | None = None,
    singleton_conflict: str = "join",
) -> str:
    context = current_context()
    try:
        return mgr.submit(
            kind,
            work,
            singleton_key=singleton_key,
            singleton_conflict=singleton_conflict,
            user_id=context.user_id if context is not None else None,
            max_concurrent=active_limit(
                "max_concurrent_runs", DEFAULT_MAX_CONCURRENT_RUNS
            ),
        )
    except RunSingletonConflict as error:
        raise ApiException(
            409, error.code, "A revision is already running for this item",
            details={"runId": error.run_id},
        ) from error
    except RunQuotaError as error:
        raise ApiException(429, error.code, str(error)) from error
```

- Add the endpoint:

```python
@router.post(
    "/resume-versions/{version_id}/revise", response_model=RunOut, status_code=202
)
def launch_revise(
    version_id: int,
    body: ReviseRequest,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    with get_session(engine) as session:
        if get_resume_version(session, version_id) is None:
            raise ApiException(
                404, "NOT_FOUND", f"Resume version #{version_id} not found"
            )

    def work(reporter):
        reporter.begin(1, f"Revising resume version #{version_id}")
        with get_session(engine) as session:
            context = current_context()
            child = revise_resume_version(
                session,
                version_id,
                body.instruction,
                re_review=body.re_review,
                review_path=str(context.paths.config_dir / "review.yaml")
                if context is not None
                else "config/review.yaml",
                facts_path=_workspace_args()["facts_path"],
            )
            result = {
                "versionId": child.id if child else None,
                "jobId": child.job_id if child else None,
            }
        reporter.step(1)
        return result

    run_id = _submit(
        mgr,
        "revise",
        work,
        singleton_key=f"revise:{version_id}",
        singleton_conflict="raise",
    )
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)
```

In `resumes.py`: delete `revise_endpoint`, the `ReviseRequest` import, and the `revise_resume_version` import (keep render/select/pdf).

- [ ] **Step 4: Run tests + regenerate contracts**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py tests/api/test_openapi_contract.py -v`
Expected: revise tests PASS; contract drift → `bash scripts/gen_ts_client.sh` → PASS. Also run any existing revise-endpoint tests (`.venv/Scripts/python.exe -m pytest tests/api -v -k revise`) and update them to expect 202 + RunOut.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/runs.py src/resume_tailor_harness/api/routers/resumes.py tests/api/test_runs_launch.py contracts/openapi.json contracts/ts/api.ts
git commit -m "feat: resume revise runs in the background (202 + run)"
```

---

### Task 8: Cover-letter revise becomes a 202 background run

**Files:**

- Modify: `src/resume_tailor_harness/api/routers/runs.py`
- Modify: `src/resume_tailor_harness/api/routers/cover_letters.py` (delete old sync revise endpoint + unused imports)
- Test: `tests/api/test_runs_launch.py` (extend)
- Regenerate: contracts

**Interfaces:**

- Consumes: `revise_cover_letter_version(session, cover_letter_id, instruction, *, facts_path)` (exists), `get_cover_letter` from `resume_tailor_harness.tracking.repository`.
- Produces: `POST /api/cover-letters/{cover_letter_id}/revise` → 202 `RunOut`, kind `coverLetterRevise`, result `{"coverLetterId": int | None, "jobId": int | None}`, singleton `cl-revise:{id}` in raise mode. The request body stays `ReviseRequest` (its `reReview` field is accepted and ignored — cover letters have no panel).

- [ ] **Step 1: Write the failing test (append to tests/api/test_runs_launch.py)**

```python
def test_cover_letter_revise_launch_returns_run(monkeypatch, tmp_path):
    from types import SimpleNamespace

    monkeypatch.setattr(
        runs_router, "get_cover_letter", lambda session, cid: SimpleNamespace(id=cid, job_id=8)
    )
    monkeypatch.setattr(
        runs_router,
        "revise_cover_letter_version",
        lambda session, cid, instruction, **kw: SimpleNamespace(id=77, job_id=8),
    )
    client = _client(tmp_path)
    with client:
        resp = client.post(
            "/api/cover-letters/5/revise", json={"instruction": "warmer tone", "reReview": False}
        )
        assert resp.status_code == 202
        got = client.get(f"/api/runs/{resp.json()['runId']}").json()
    assert got["kind"] == "coverLetterRevise"
    assert got["result"] == {"coverLetterId": 77, "jobId": 8}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py -v -k cover_letter_revise`
Expected: FAIL

- [ ] **Step 3: Implement**

In `runs.py` add imports `from resume_tailor_harness.services.cover_letter_revision import revise_cover_letter_version` and `get_cover_letter` (from `resume_tailor_harness.tracking.repository`), then:

```python
@router.post(
    "/cover-letters/{cover_letter_id}/revise", response_model=RunOut, status_code=202
)
def launch_cover_letter_revise(
    cover_letter_id: int,
    body: ReviseRequest,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    with get_session(engine) as session:
        if get_cover_letter(session, cover_letter_id) is None:
            raise ApiException(
                404, "NOT_FOUND", f"Cover letter #{cover_letter_id} not found"
            )

    def work(reporter):
        reporter.begin(1, f"Revising cover letter #{cover_letter_id}")
        with get_session(engine) as session:
            child = revise_cover_letter_version(
                session,
                cover_letter_id,
                body.instruction,
                facts_path=_workspace_args()["facts_path"],
            )
            result = {
                "coverLetterId": child.id if child else None,
                "jobId": child.job_id if child else None,
            }
        reporter.step(1)
        return result

    run_id = _submit(
        mgr,
        "coverLetterRevise",
        work,
        singleton_key=f"cl-revise:{cover_letter_id}",
        singleton_conflict="raise",
    )
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)
```

Delete the sync endpoint from `cover_letters.py` (and its now-unused imports).

- [ ] **Step 4: Run tests + regen contracts**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py tests/api/test_openapi_contract.py -v` then `bash scripts/gen_ts_client.sh` on drift, re-run. Update any existing cover-letter revise tests to expect 202.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/runs.py src/resume_tailor_harness/api/routers/cover_letters.py tests/api/test_runs_launch.py contracts/openapi.json contracts/ts/api.ts
git commit -m "feat: cover-letter revise runs in the background"
```

---

### Task 9: Web — revise launches a tracked run with pending/error state

**Files:**

- Modify: `web/src/lib/runs/store.ts` (RunRecord gains `meta`)
- Modify: `web/src/features/runs/use-launch-run.ts` (launch accepts `meta`)
- Modify: `web/src/features/job/use-job-mutations.ts` (`useReviseVersion`, `useReviseCoverLetter`)
- Modify: `web/src/features/job/VersionRow.tsx`, `web/src/features/job/CoverLetterRow.tsx`
- Test: `web/src/features/job/use-revise-run.test.tsx` (new)

**Interfaces:**

- Consumes: 202 revise endpoints (Tasks 7–8), `useRunStore` (`upsert`, `remove`), `trackRun`.
- Produces: `RunRecord.meta?: { versionId?: number; coverLetterId?: number; jobId?: number; instruction?: string }`; `launch(kind, call, invalidate?, meta?)`; `useReviseVersion(jobId)` / `useReviseCoverLetter(jobId)` now resolve at launch (not completion) and register a tracked run carrying `meta`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/job/use-revise-run.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { server } from "@/test/server";

import { useReviseVersion } from "./use-job-mutations";

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("useReviseVersion (run-backed)", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  it("registers a tracked revise run with version meta", async () => {
    server.use(
      http.post("/api/resume-versions/5/revise", () =>
        HttpResponse.json(
          { runId: "r1", kind: "revise", state: "running" },
          { status: 202 },
        ),
      ),
      http.get("/api/runs/r1", () =>
        HttpResponse.json({
          runId: "r1",
          kind: "revise",
          state: "running",
          percent: 0,
        }),
      ),
    );
    const { result } = renderHook(() => useReviseVersion(3), { wrapper });
    result.current.mutate({
      versionId: 5,
      instruction: "tighter",
      reReview: false,
    });
    await waitFor(() => {
      const run = useRunStore.getState().runs["r1"];
      expect(run).toBeDefined();
      expect(run.kind).toBe("revise");
      expect(run.meta).toMatchObject({
        versionId: 5,
        jobId: 3,
        instruction: "tighter",
      });
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/job/use-revise-run.test.tsx`
Expected: FAIL (`meta` undefined / mutation awaits ResumeVersionOut)

- [ ] **Step 3: Implement**

`store.ts` — add to `RunRecord`:

```ts
  meta?: { versionId?: number; coverLetterId?: number; jobId?: number; instruction?: string };
```

`use-launch-run.ts` — `launch` gains a fourth param and threads it into the upsert:

```ts
const launch = async (
  kind: string,
  call: () => Promise<unknown>,
  invalidate: string[] = DEFAULT_INVALIDATE,
  meta?: import("@/lib/runs/store").RunRecord["meta"],
): Promise<boolean> => {
  try {
    const run = (await call()) as RunOut;
    useRunStore.getState().upsert({
      runId: run.runId,
      kind,
      status: "running",
      percent: 0,
      phase: "",
      current: 0,
      total: 0,
      etaText: null,
      meta,
    });
    trackRun({ runId: run.runId, kind }, (completed) => {
      invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      announceCompletion(completed);
    });
    return true;
  } catch (e) {
    toast.error(`Failed to start ${kind}: ${(e as Error).message}`);
    return false;
  }
};
```

`use-job-mutations.ts` — replace the two revise hooks:

```ts
import { useLaunchRun } from "@/features/runs/use-launch-run";

export function useReviseVersion(jobId: number) {
  const { launch } = useLaunchRun();
  return useMutation({
    mutationFn: async (vars: {
      versionId: number;
      instruction: string;
      reReview?: boolean;
    }) => {
      const ok = await launch(
        "revise",
        () =>
          unwrap(
            api.POST("/api/resume-versions/{version_id}/revise", {
              params: { path: { version_id: vars.versionId } },
              body: {
                instruction: vars.instruction,
                reReview: vars.reReview ?? false,
              },
            }),
          ),
        ["job"],
        { versionId: vars.versionId, jobId, instruction: vars.instruction },
      );
      if (!ok) throw new Error("launch failed");
    },
  });
}

export function useReviseCoverLetter(jobId: number) {
  const { launch } = useLaunchRun();
  return useMutation({
    mutationFn: async (vars: {
      coverLetterId: number;
      instruction: string;
    }) => {
      const ok = await launch(
        "coverLetterRevise",
        () =>
          unwrap(
            api.POST("/api/cover-letters/{cover_letter_id}/revise", {
              params: { path: { cover_letter_id: vars.coverLetterId } },
              body: { instruction: vars.instruction, reReview: false },
            }),
          ),
        ["job"],
        {
          coverLetterId: vars.coverLetterId,
          jobId,
          instruction: vars.instruction,
        },
      );
      if (!ok) throw new Error("launch failed");
    },
  });
}
```

`VersionRow.tsx` — subscribe to the run for this version and render inline state under the revise input row:

```tsx
const reviseRun = useRunStore((s) =>
  Object.values(s.runs).find(
    (r) => r.kind === "revise" && r.meta?.versionId === version.id,
  ),
);
const reviseActive =
  reviseRun?.status === "running" || reviseRun?.status === "queued";
```

- Disable the instruction `Input` and the Revise `Button` while `reviseActive`.
- Below the input grid:

```tsx
{
  reviseRun && reviseActive && (
    <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      Revision running… you can navigate away.
    </p>
  );
}
{
  reviseRun && reviseRun.status === "failed" && (
    <div className="mt-2 flex items-center gap-2 text-sm text-destructive">
      <span>Revision failed: {reviseRun.error ?? "unknown error"}</span>
      <Button
        size="sm"
        variant="outline"
        onClick={() =>
          revise.mutate({
            versionId: version.id,
            instruction: reviseRun.meta?.instruction ?? "",
            reReview,
          })
        }
      >
        Retry
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => useRunStore.getState().remove(reviseRun.runId)}
      >
        Dismiss
      </Button>
    </div>
  );
}
```

- The submit handler keeps `setInstruction("")` — move it out of `onSuccess` into the click handler (instruction clears immediately per spec).

`CoverLetterRow.tsx` — same pattern with `kind === "coverLetterRevise"` and `meta?.coverLetterId === letter.id` (mirror the exact JSX above with the row's own mutate call).

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/features/job src/features/runs`
Expected: PASS (update any existing tests that awaited the old sync revise response)

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/runs/store.ts web/src/features/runs/use-launch-run.ts web/src/features/job/
git commit -m "feat(web): revise as tracked background run with inline pending/error state"
```

---

## Workstream 3 — Import/export surfaces

### Task 10: Complete account workspace round-trip import

**Files:**

- Modify: `src/resume_tailor_harness/api/routers/account.py`
- Test: `tests/api/test_account_backup.py` (new)

**Interfaces:**

- Consumes: the existing `GET /api/account/export` link-token surface,
  `import_data_root(...)`, `workspace_paths(...)`, caller-scoped active runs, and
  `EngineRegistry.evict/get` for validated swap and rollback rebinding.
- Produces: `POST /api/account/import` (multipart `file`, `confirm=REPLACE`;
  400 without confirm, 409 `RUNS_ACTIVE`, bounded upload, 400
  `INVALID_ARCHIVE`/`UNSAFE_ARCHIVE`). The already-registered export router is
  covered by the round-trip tests but is not recreated.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_account_backup.py
"""Workspace export/import — CONTEXT.md: Workspace export, never a custody transfer."""
import io
import tarfile


def _login(mu_client):
    resp = mu_client.post(
        "/api/auth/login", json={"username": "owner", "password": "owner-password"}
    )
    assert resp.status_code == 200


def _link_token(mu_client) -> str:
    resp = mu_client.post("/api/auth/link-token", json={"purpose": "download"})
    assert resp.status_code in (200, 201)
    return resp.json()["token"]


def test_export_downloads_workspace_archive(mu_client):
    _login(mu_client)
    token = _link_token(mu_client)
    resp = mu_client.get(f"/api/account/export?token={token}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    with tarfile.open(fileobj=io.BytesIO(resp.content), mode="r:gz") as tf:
        names = tf.getnames()
    assert names  # non-empty workspace archive


def test_import_requires_confirm(mu_client):
    _login(mu_client)
    resp = mu_client.post(
        "/api/account/import",
        files={"file": ("x.tar.gz", b"not-a-real-archive", "application/gzip")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_import_round_trips_export(mu_client):
    _login(mu_client)
    token = _link_token(mu_client)
    archive = mu_client.get(f"/api/account/export?token={token}").content
    resp = mu_client.post(
        "/api/account/import?confirm=REPLACE",
        files={"file": ("ws.tar.gz", archive, "application/gzip")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "imported"}


def test_import_rejects_invalid_archive(mu_client):
    _login(mu_client)
    resp = mu_client.post(
        "/api/account/import?confirm=REPLACE",
        files={"file": ("x.tar.gz", b"garbage", "application/gzip")},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_ARCHIVE"
```

(Uses the existing `mu_client` fixture from `tests/api/conftest.py` — multi-user app with a seeded owner. Mirror `tests/api/test_admin_backup.py` for the login/link-token details and adjust if that file's helpers differ.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_account_backup.py -v`
Expected: FAIL (404 — endpoints don't exist)

- [ ] **Step 3: Implement**

In `account.py` (follow `admin.py`'s export/import structure — read it first; it already solves temp-dir lifecycle, `UploadFile` staging, and error mapping):

```python
account_link_router = APIRouter()  # download surface; token rides the query string


def _require_workspace_context() -> UserContext:
    context = current_context()
    if context is None:
        raise ApiException(
            400, "NO_WORKSPACE", "Workspace export/import requires multi-user mode"
        )
    return context


def _refuse_if_user_running(request: Request, user_id: str) -> None:
    mgr = request.app.state.run_manager
    if mgr is not None and mgr.list_active(user_id=user_id):
        raise ApiException(
            409, "RUNS_ACTIVE", "Wait for your active runs to finish first"
        )


@account_link_router.get("/account/export")
def export_workspace(request: Request) -> FileResponse:
    context = _require_workspace_context()
    _refuse_if_user_running(request, context.user_id)
    temporary = Path(tempfile.mkdtemp(prefix="ra-ws-export-"))
    try:
        archive = export_data_root(
            context.workspace, context.paths.db_url, temporary
        )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return FileResponse(
        archive,
        media_type="application/gzip",
        filename=f"workspace-{context.username}-{archive.name}",
        background=BackgroundTask(shutil.rmtree, temporary, ignore_errors=True),
    )


@router.post("/account/import")
def import_workspace(
    request: Request, file: UploadFile, confirm: str = ""
) -> dict[str, str]:
    if confirm != "REPLACE":
        raise ApiException(
            400, "CONFIRM_REQUIRED", "Import replaces your workspace; pass ?confirm=REPLACE"
        )
    context = _require_workspace_context()
    _refuse_if_user_running(request, context.user_id)
    registry = request.app.state.engine_registry
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "import.tar.gz"
        with archive.open("wb") as destination:
            shutil.copyfileobj(file.file, destination)
        try:
            import_data_root(
                archive,
                context.workspace,
                before_swap=(lambda: registry.evict(context.user_id))
                if registry is not None
                else None,
            )
        except (InvalidArchiveError, UnsafeArchiveError) as error:
            raise ApiException(400, "INVALID_ARCHIVE", str(error)) from error
    return {"status": "imported"}
```

Add imports (`tempfile`, `shutil`, `Path`, `FileResponse`, `BackgroundTask`, `UploadFile`, `Request`, `export_data_root`, `import_data_root`, `InvalidArchiveError`, `UnsafeArchiveError`, `current_context`, `UserContext`, `ApiException`). Register `account.account_link_router` in `api/app.py` exactly where `resumes.link_router` is registered (same auth dependency chain — the link-token query dependency with `purpose="download"`); check `app.py` for the precise include call and mirror it. If `app.state.run_manager` is named differently, use the attribute `get_run_manager` reads.

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_account_backup.py tests/api/test_admin_backup.py -v`
Expected: PASS (admin backup untouched)

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/account.py src/resume_tailor_harness/api/app.py tests/api/test_account_backup.py
git commit -m "feat: per-user workspace export/import (Workspace export, ADR-0003 scoped)"
```

---

### Task 11: Admin backup & restore card (web)

**Files:**

- Modify: `web/src/features/admin/AdminPage.tsx`
- Test: `web/src/features/admin/AdminPage.backup.test.tsx` (new)

**Interfaces:**

- Consumes: `GET /api/admin/export` via `openDownload("/api/admin/export")` (link-token flow), `POST /api/admin/import?confirm=REPLACE` multipart (raw `fetch` + FormData, same pattern as `postSource` in `web/src/features/profile-sources/use-sources.ts`).
- Produces: a "Backup & restore" `Card` on the admin page.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/admin/AdminPage.backup.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BackupRestoreCard } from "./AdminPage";

describe("BackupRestoreCard", () => {
  it("renders export and disabled import until REPLACE is typed", () => {
    render(<BackupRestoreCard />);
    expect(
      screen.getByRole("button", { name: /download backup/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /import archive/i }),
    ).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/admin/AdminPage.backup.test.tsx`
Expected: FAIL (no `BackupRestoreCard` export)

- [ ] **Step 3: Implement**

In `AdminPage.tsx`, add an exported `BackupRestoreCard` component and render it in the page grid:

```tsx
export function BackupRestoreCard() {
  const [confirmText, setConfirmText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const runImport = async () => {
    if (!file) return;
    setImporting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const headers: HeadersInit = {};
      const token = getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const resp = await fetch(
        `${window.location.origin}/api/admin/import?confirm=REPLACE`,
        { method: "POST", body: form, headers },
      );
      const body = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error(body?.error?.message ?? "Import failed");
      toast.success("Data imported — reloading");
      window.location.reload();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setImporting(false);
    }
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle>Backup &amp; restore</CardTitle>
        <CardDescription>
          The archive contains every workspace and its operational secrets —
          treat it as secret material. Import replaces the deployment&apos;s
          data and is refused while runs are active.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button
          variant="outline"
          onClick={() => void openDownload("/api/admin/export")}
        >
          Download backup
        </Button>
        <div className="space-y-2 rounded-lg border border-destructive/30 p-3">
          <Input
            type="file"
            accept=".tar.gz,.tgz,application/gzip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <Input
            placeholder='Type "REPLACE" to enable import'
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
          />
          <Button
            variant="destructive"
            disabled={confirmText !== "REPLACE" || !file || importing}
            onClick={() => void runImport()}
          >
            Import archive
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
```

Imports: `openDownload` from `@/lib/api/client`, `getToken` from wherever `use-sources.ts` imports it (`@/lib/api/client` or the auth module — copy that file's import), `toast` from sonner, `Input`, `useState`. Render `<BackupRestoreCard />` after the existing System defaults card.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/admin`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/admin/
git commit -m "feat(web): admin backup & restore card"
```

---

### Task 12: Account page workspace export/import UI

**Files:**

- Modify: `web/src/features/account/AccountPage.tsx`
- Test: `web/src/features/account/AccountPage.backup.test.tsx` (new)

**Interfaces:**

- Consumes: Task 10 endpoints; `openDownload("/api/account/export")`; multipart fetch pattern from Task 11.
- Produces: `WorkspaceDataCard` exported from `AccountPage.tsx`, rendered on the account page.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/account/AccountPage.backup.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WorkspaceDataCard } from "./AccountPage";

describe("WorkspaceDataCard", () => {
  it("renders export and gated import", () => {
    render(<WorkspaceDataCard />);
    expect(
      screen.getByRole("button", { name: /export my data/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /import archive/i }),
    ).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/account/AccountPage.backup.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement**

Add `WorkspaceDataCard` to `AccountPage.tsx` — identical structure to Task 11's card with these differences: title "My workspace data"; description explains the round-trip pull ("Export your workspace, run a local browser pull against it, and import it back — browser-only sources work without touching anyone else's data. The archive contains your operational secrets."); export button label **Export my data** calling `openDownload("/api/account/export")`; import posts to `/api/account/import?confirm=REPLACE`; on success `toast.success("Workspace imported")` + `window.location.reload()`. Render it in the page layout after the existing cards.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/account`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/account/
git commit -m "feat(web): workspace export/import card (per-user round-trip pull)"
```

---

### Task 13: Bulk profile document upload

**Files:**

- Modify: `web/src/features/profile-sources/SourceManager.tsx`
- Modify: `web/src/features/profile-sources/use-sources.ts`
- Test: extend `web/src/features/profile-sources/use-sources.test.tsx`

**Interfaces:**

- Consumes: existing `postSource(file, mode, anchor, primary)` single-file uploader.
- Produces: `useUploadSources(): { uploadAll(files: File[], mode?: string, anchor?: string | null): Promise<{ ok: number; failed: [string, string][] }> }` — sequential uploads, per-file failure isolation, one summary toast; the SourceManager file input gains `multiple` and the card accepts drag-and-drop.

- [ ] **Step 1: Write the failing test (append to use-sources.test.tsx, reusing its msw/query wrapper)**

```tsx
it("uploads a batch sequentially and isolates failures", async () => {
  let calls = 0;
  server.use(
    http.post("/api/profile/sources", () => {
      calls += 1;
      if (calls === 2) {
        return HttpResponse.json(
          { error: { code: "BAD_FILE", message: "unsupported" } },
          { status: 400 },
        );
      }
      return HttpResponse.json({ id: `doc-${calls}` });
    }),
  );
  const { result } = renderHook(() => useUploadSources(), { wrapper });
  const files = [
    new File(["a"], "a.md", { type: "text/markdown" }),
    new File(["b"], "b.md", { type: "text/markdown" }),
    new File(["c"], "c.md", { type: "text/markdown" }),
  ];
  const summary = await result.current.uploadAll(files, "literal", null);
  expect(summary.ok).toBe(2);
  expect(summary.failed).toEqual([["b.md", "unsupported"]]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/profile-sources/use-sources.test.tsx`
Expected: FAIL (`useUploadSources` not exported)

- [ ] **Step 3: Implement**

In `use-sources.ts`:

```ts
export function useUploadSources() {
  const qc = useQueryClient();
  const uploadAll = async (
    files: File[],
    mode?: string,
    anchor?: string | null,
  ): Promise<{ ok: number; failed: [string, string][] }> => {
    let ok = 0;
    const failed: [string, string][] = [];
    for (const file of files) {
      try {
        await postSource(file, mode, anchor);
        ok += 1;
      } catch (e) {
        failed.push([file.name, (e as Error).message]);
      }
    }
    qc.invalidateQueries({ queryKey: ["profile-sources"] });
    if (failed.length === 0) toast.success(`${ok} file(s) added`);
    else
      toast.warning(
        `${ok} added, ${failed.length} failed: ${failed.map(([n]) => n).join(", ")}`,
      );
    return { ok, failed };
  };
  return { uploadAll };
}
```

In `SourceManager.tsx`:

- Add `multiple` to the main upload `<input type="file">` and change its `onChange` to `const files = Array.from(e.target.files ?? []); if (files.length) void uploadSources.uploadAll(files, uploadMode, uploadMode === "synthesis" ? uploadAnchor || null : null);` (keep the single-file replace input unchanged).
- Add drag-and-drop on the manager's root card element:

```tsx
onDragOver={(e) => e.preventDefault()}
onDrop={(e) => {
  e.preventDefault();
  const files = Array.from(e.dataTransfer.files);
  if (files.length)
    void uploadSources.uploadAll(
      files, uploadMode, uploadMode === "synthesis" ? uploadAnchor || null : null,
    );
}}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/features/profile-sources`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/profile-sources/
git commit -m "feat(web): bulk + drag-drop profile document upload"
```

---

### Task 14: `POST /api/jobs/import` — CSV/JSON job import

**Files:**

- Create: `src/resume_tailor_harness/services/jobs_import.py`
- Modify: `src/resume_tailor_harness/api/routers/jobs.py`, `src/resume_tailor_harness/api/schemas/jobs.py`
- Test: `tests/test_jobs_import.py` (new)
- Regenerate: contracts

**Interfaces:**

- Consumes: `save_or_upgrade(session, *, source, jd_text, url, company, title, location, posted_at, commit=False)` (exists), `parse_iso_datetime` from `resume_tailor_harness.discovery.connectors.dates`.
- Produces: `import_jobs_file(session, filename: str, data: bytes) -> JobsImportReport` where `JobsImportReport` is a dataclass `{added: int, upgraded: int, skipped: int, errors: list[tuple[int, str]]}` (row numbers 1-based, header excluded for CSV); schema `JobsImportReportOut(CamelModel)` with `added/upgraded/skipped: int`, `errors: list[JobsImportError]` (`row: int`, `reason: str`); endpoint `POST /api/jobs/import` (multipart `file`) → 200 `JobsImportReportOut`, 400 code `UNSUPPORTED_FORMAT` for other extensions, 400 code `INVALID_FILE` for undecodable/unparseable content. Task 16 consumes it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_jobs_import.py
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.services.jobs_import import import_jobs_file

CSV = (
    "title,company,url,location,jd_text,posted_at\n"
    "Platform Engineer,Acme,https://a.test/1,Austin,Build platforms all day.,2026-07-01T00:00:00Z\n"
    "No JD Role,Acme,https://a.test/2,Austin,,\n"
)

JSON = (
    b'[{"title": "Data Engineer", "company": "Beta", "url": "https://b.test/1",'
    b' "location": "Remote", "jd_text": "Pipelines and warehouses."}]'
)


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_csv_import_adds_and_rejects_blank_jd():
    with _session() as session:
        report = import_jobs_file(session, "jobs.csv", CSV.encode("utf-8"))
    assert report.added == 1
    assert report.errors == [
        (2, "jd_text is required; use the URL-list import for postings you only have links for")
    ]


def test_json_import_adds():
    with _session() as session:
        report = import_jobs_file(session, "jobs.json", JSON)
    assert report.added == 1
    assert report.errors == []


def test_duplicate_rows_count_skipped():
    with _session() as session:
        first = import_jobs_file(session, "jobs.json", JSON)
        second = import_jobs_file(session, "jobs.json", JSON)
    assert first.added == 1
    assert second.added == 0
    assert second.skipped == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_jobs_import.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement the service**

```python
# src/resume_tailor_harness/services/jobs_import.py
"""File-based job import: CSV/JSON rows through save_or_upgrade (source='manual').

Rows without jd_text are rejected per row — never silently skipped, never
auto-routed to the URL pipeline (spec 2026-07-12, workstream 3d).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from sqlmodel import Session

from resume_tailor_harness.discovery.connectors.dates import parse_iso_datetime
from resume_tailor_harness.discovery.ingest import IngestOutcome, save_or_upgrade

_COLUMNS = ("title", "company", "url", "location", "jd_text", "posted_at")
_BLANK_JD = (
    "jd_text is required; use the URL-list import for postings you only have links for"
)


@dataclass
class JobsImportReport:
    added: int = 0
    upgraded: int = 0
    skipped: int = 0
    errors: list[tuple[int, str]] = field(default_factory=list)


class UnsupportedFormat(ValueError):
    pass


class InvalidFile(ValueError):
    pass


def _rows_from_csv(data: bytes) -> list[dict]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise InvalidFile("file is not valid UTF-8") from error
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _rows_from_json(data: bytes) -> list[dict]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidFile("file is not valid JSON") from error
    if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
        raise InvalidFile("JSON must be an array of objects")
    return payload


def import_jobs_file(session: Session, filename: str, data: bytes) -> JobsImportReport:
    name = filename.lower()
    if name.endswith(".csv"):
        rows = _rows_from_csv(data)
    elif name.endswith(".json"):
        rows = _rows_from_json(data)
    else:
        raise UnsupportedFormat("only .csv and .json are supported")

    report = JobsImportReport()
    for index, row in enumerate(rows, start=1):
        values = {key: (row.get(key) or None) for key in _COLUMNS}
        jd_text = (values["jd_text"] or "").strip()
        if not jd_text:
            report.errors.append((index, _BLANK_JD))
            continue
        posted_at = (
            parse_iso_datetime(values["posted_at"]) if values["posted_at"] else None
        )
        _, outcome = save_or_upgrade(
            session,
            source="manual",
            jd_text=jd_text,
            url=values["url"],
            company=values["company"],
            title=values["title"],
            location=values["location"],
            posted_at=posted_at,
            commit=False,
        )
        if outcome is IngestOutcome.inserted:
            report.added += 1
        elif outcome is IngestOutcome.upgraded:
            report.upgraded += 1
        else:
            report.skipped += 1
    session.commit()
    return report
```

Router (`jobs.py`) + schemas (`schemas/jobs.py`):

```python
# schemas/jobs.py
class JobsImportError(CamelModel):
    row: int
    reason: str


class JobsImportReportOut(CamelModel):
    added: int
    upgraded: int
    skipped: int
    errors: list[JobsImportError]
```

```python
# routers/jobs.py
@router.post("/jobs/import", response_model=JobsImportReportOut)
def import_jobs_endpoint(file: UploadFile, session: Session = Depends(get_session)):
    from resume_tailor_harness.services.jobs_import import (
        InvalidFile,
        UnsupportedFormat,
        import_jobs_file,
    )

    try:
        report = import_jobs_file(session, file.filename or "", file.file.read())
    except UnsupportedFormat as error:
        raise ApiException(400, "UNSUPPORTED_FORMAT", str(error)) from error
    except InvalidFile as error:
        raise ApiException(400, "INVALID_FILE", str(error)) from error
    return JobsImportReportOut(
        added=report.added,
        upgraded=report.upgraded,
        skipped=report.skipped,
        errors=[JobsImportError(row=r, reason=m) for r, m in report.errors],
    )
```

(Add `UploadFile` to jobs.py's fastapi imports; keep the service import local so the router module stays light.)

- [ ] **Step 4: Run tests + regen contracts**

Run: `.venv/Scripts/python.exe -m pytest tests/test_jobs_import.py tests/api/test_openapi_contract.py -v`; `bash scripts/gen_ts_client.sh` on drift; re-run.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/jobs_import.py src/resume_tailor_harness/api/routers/jobs.py src/resume_tailor_harness/api/schemas/jobs.py tests/test_jobs_import.py contracts/openapi.json contracts/ts/api.ts
git commit -m "feat: CSV/JSON job import through save_or_upgrade"
```

---

### Task 15: `POST /api/jobs/import-urls` — URL-list background run

**Files:**

- Modify: `src/resume_tailor_harness/api/routers/runs.py`
- Test: `tests/api/test_runs_launch.py` (extend)
- Regenerate: contracts

**Interfaces:**

- Consumes: `add_job_from_url(session, *, url, allow_browser=...)` (already imported in runs.py), `_submit` (Task 7 version).
- Produces: `POST /api/jobs/import-urls` (multipart `file`, plain text, one URL per line; `#` comments and blank lines ignored) → 202 `RunOut`, kind `importUrls`, result `{"added": int, "duplicates": int, "failures": {url: reason}}`; 400 code `NO_URLS` when the file has no http(s) lines. Per-URL failure isolation — one bad URL never aborts the batch.

- [ ] **Step 1: Write the failing test (append to tests/api/test_runs_launch.py)**

```python
def test_import_urls_launch_isolates_failures(monkeypatch, tmp_path):
    from types import SimpleNamespace

    def fake_add(session, *, url, **kw):
        if "bad" in url:
            raise ValueError("no reader for host")
        return SimpleNamespace(id=1)

    monkeypatch.setattr(runs_router, "add_job_from_url", fake_add)
    client = _client(tmp_path)
    body = b"https://ok.test/a\n# comment\n\nhttps://bad.test/b\nhttps://ok.test/c\n"
    with client:
        resp = client.post(
            "/api/jobs/import-urls",
            files={"file": ("urls.txt", body, "text/plain")},
        )
        assert resp.status_code == 202
        got = client.get(f"/api/runs/{resp.json()['runId']}").json()
    assert got["kind"] == "importUrls"
    assert got["result"]["added"] == 2
    assert "https://bad.test/b" in got["result"]["failures"]


def test_import_urls_rejects_empty_file(tmp_path):
    client = _client(tmp_path)
    with client:
        resp = client.post(
            "/api/jobs/import-urls", files={"file": ("urls.txt", b"# nothing\n", "text/plain")}
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "NO_URLS"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py -v -k import_urls`
Expected: FAIL (404)

- [ ] **Step 3: Implement (in runs.py; add `UploadFile` to the fastapi import)**

```python
@router.post("/jobs/import-urls", response_model=RunOut, status_code=202)
def launch_import_urls(
    file: UploadFile, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    raw = file.file.read().decode("utf-8", errors="replace")
    urls = [
        line.strip()
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    urls = [u for u in urls if u.startswith(("http://", "https://"))]
    if not urls:
        raise ApiException(400, "NO_URLS", "The file contains no http(s) URLs")
    engine = _engine(request)
    allow_browser = get_settings().browser_enabled

    def work(reporter):
        reporter.begin(len(urls), "Importing job URLs")
        added = 0
        duplicates = 0
        failures: dict[str, str] = {}
        for index, url in enumerate(urls, start=1):
            reporter.checkpoint()
            try:
                with get_session(engine) as session:
                    job = add_job_from_url(
                        session, url=url, allow_browser=allow_browser
                    )
                if job is None:
                    duplicates += 1
                else:
                    added += 1
            except Exception as error:  # noqa: BLE001 — per-URL isolation
                failures[url] = f"{type(error).__name__}: {error}"
            reporter.step(index, label=url)
        return {"added": added, "duplicates": duplicates, "failures": failures}

    run_id = _submit(mgr, "importUrls", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)
```

(If `reporter.checkpoint()` is not a `ProgressReporter` method in this codebase's `RunProgressReporter`, it is — see `manager.py` line 82; it raises on cooperative cancel.)

- [ ] **Step 4: Run tests + regen contracts**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py tests/api/test_openapi_contract.py -v`; regen on drift.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/runs.py tests/api/test_runs_launch.py contracts/openapi.json contracts/ts/api.ts
git commit -m "feat: URL-list job import as background run"
```

---

### Task 16: Import-jobs dialog (web)

**Files:**

- Create: `web/src/features/runs/ImportJobsDialog.tsx`
- Modify: the component that renders `AddUrlDialog`'s trigger (find with `grep -r "AddUrlDialog" web/src --include=*.tsx` — add the new trigger beside it), and `web/src/features/triage/TriageContainer.tsx` (button in the toolbar row next to `QuickFilters`)
- Test: `web/src/features/runs/ImportJobsDialog.test.tsx` (new)

**Interfaces:**

- Consumes: `POST /api/jobs/import` (Task 14, multipart via raw fetch), `POST /api/jobs/import-urls` (Task 15) through `useLaunchRun().launch("importUrls", ...)`.
- Produces: `<ImportJobsDialog open onOpenChange />` — file picker routing by extension: `.csv`/`.json` → synchronous import, renders the report summary (added/upgraded/skipped + per-row errors) inside the dialog; `.txt` → launches the tracked run and closes; other extensions → inline validation message.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/runs/ImportJobsDialog.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { server } from "@/test/server";

import { ImportJobsDialog } from "./ImportJobsDialog";

function Providers({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("ImportJobsDialog", () => {
  it("shows the report after a CSV import", async () => {
    server.use(
      http.post("/api/jobs/import", () =>
        HttpResponse.json({
          added: 3,
          upgraded: 0,
          skipped: 1,
          errors: [
            {
              row: 2,
              reason:
                "jd_text is required; use the URL-list import for postings you only have links for",
            },
          ],
        }),
      ),
    );
    render(
      <Providers>
        <ImportJobsDialog open onOpenChange={vi.fn()} />
      </Providers>,
    );
    const input = screen.getByLabelText(/import file/i);
    await userEvent.upload(
      input,
      new File(["title,company\n"], "jobs.csv", { type: "text/csv" }),
    );
    await userEvent.click(screen.getByRole("button", { name: /import/i }));
    await waitFor(() =>
      expect(screen.getByText(/3 added/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/row 2/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/runs/ImportJobsDialog.test.tsx`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

```tsx
// web/src/features/runs/ImportJobsDialog.tsx
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { getToken } from "@/lib/api/client"; // match use-sources.ts's actual import
import { useLaunchRun } from "./use-launch-run";

type Report = {
  added: number;
  upgraded: number;
  skipped: number;
  errors: { row: number; reason: string }[];
};

export function ImportJobsDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const { launch } = useLaunchRun();

  const runImport = async () => {
    if (!file) return;
    setProblem(null);
    setReport(null);
    const name = file.name.toLowerCase();
    if (name.endsWith(".txt")) {
      const ok = await launch("importUrls", async () => {
        const form = new FormData();
        form.append("file", file);
        const headers: HeadersInit = {};
        const token = getToken();
        if (token) headers.Authorization = `Bearer ${token}`;
        const resp = await fetch(
          `${window.location.origin}/api/jobs/import-urls`,
          {
            method: "POST",
            body: form,
            headers,
          },
        );
        const body = await resp.json();
        if (!resp.ok) throw new Error(body?.error?.message ?? "Import failed");
        return body;
      });
      if (ok) onOpenChange(false);
      return;
    }
    if (!name.endsWith(".csv") && !name.endsWith(".json")) {
      setProblem(
        "Use .csv or .json (with jd_text) — or a .txt of URLs, one per line.",
      );
      return;
    }
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const headers: HeadersInit = {};
      const token = getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const resp = await fetch(`${window.location.origin}/api/jobs/import`, {
        method: "POST",
        body: form,
        headers,
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body?.error?.message ?? "Import failed");
      setReport(body as Report);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Import jobs from a file</DialogTitle>
          <DialogDescription>
            CSV/JSON columns: title, company, url, location, jd_text, posted_at.
            A .txt of URLs (one per line) imports in the background instead.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Input
            aria-label="Import file"
            type="file"
            accept=".csv,.json,.txt"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          {problem && <p className="text-sm text-destructive">{problem}</p>}
          <Button disabled={!file || busy} onClick={() => void runImport()}>
            Import
          </Button>
          {report && (
            <div className="space-y-1 rounded-lg border p-3 text-sm">
              <p>
                {report.added} added · {report.upgraded} upgraded ·{" "}
                {report.skipped} skipped
              </p>
              {report.errors.map((e) => (
                <p key={e.row} className="text-destructive">
                  Row {e.row}: {e.reason}
                </p>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

(Match the Dialog import names to `AddUrlDialog.tsx`'s actual imports; if `getToken` lives elsewhere, copy `use-sources.ts`.) Add trigger buttons: "Import file…" beside wherever `AddUrlDialog` is triggered, and in Triage's toolbar row (after `<QuickFilters …/>`), both managing a `const [importOpen, setImportOpen] = useState(false)` + `<ImportJobsDialog open={importOpen} onOpenChange={setImportOpen} />`.

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/features/runs/ImportJobsDialog.test.tsx src/features/triage`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/runs/ImportJobsDialog.tsx web/src/features/runs/ImportJobsDialog.test.tsx web/src/features/triage/TriageContainer.tsx <file that renders AddUrlDialog trigger>
git commit -m "feat(web): import-jobs dialog (CSV/JSON sync + URL-list run)"
```

---

## Workstream 4 — Company display names

### Task 17: `stale_company` + `RefreshCompany` merge action + collision downgrade

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/base.py` (RawJob)
- Modify: `src/resume_tailor_harness/discovery/merge.py`
- Modify: `src/resume_tailor_harness/discovery/ingest.py`
- Test: `tests/test_merge_refresh_company.py` (new)

**Interfaces:**

- Produces: `RawJob.stale_company: str | None = None`; `IncomingJob.stale_company: str | None = None` (+ `clean(..., stale_company=None)` trims it); `RefreshCompany(company: str, dedup_key: str | None)` added to `MergeAction`; `decide` returns it when the equal/lower-tier branch would Skip **and** `incoming.company` differs from `existing.company` **and** `existing.company` case-insensitively equals `incoming.stale_company`; `save_or_upgrade(..., stale_company=None)` passes it through and downgrades `RefreshCompany` to `Skip` when another non-archived row holds the target dedup_key with a compatible location (ADR-0004); `ingest_jobs_with_outcomes` forwards `raw.stale_company`. Task 18 sets the field; Task 19 reuses the same collision rule.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_merge_refresh_company.py
"""ADR-0004: company renames recompute dedup_key and skip on collision."""
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.discovery.ingest import IngestOutcome, save_or_upgrade
from resume_tailor_harness.discovery.merge import IncomingJob, RefreshCompany, Skip, decide
from resume_tailor_harness.tracking.dedup import compute_dedup_key
from resume_tailor_harness.tracking.tables import Job, JobStatus

JD = "We build rockets and need platform engineers."


def _existing(company="acmecorp", **overrides) -> Job:
    fields = dict(
        source="greenhouse",
        jd_text=JD,
        url="https://boards.greenhouse.io/acmecorp/jobs/1",
        company=company,
        title="Platform Engineer",
        location="Austin",
        status=JobStatus.raw.value,
        dedup_key=compute_dedup_key(company, "Platform Engineer"),
    )
    fields.update(overrides)
    return Job(**fields)


def _incoming(**overrides) -> IncomingJob:
    fields = dict(
        source="greenhouse",
        jd_text=JD,
        url="https://boards.greenhouse.io/acmecorp/jobs/1",
        company="Acme Corp",
        title="Platform Engineer",
        location="Austin",
        stale_company="acmecorp",
    )
    fields.update(overrides)
    return IncomingJob.clean(**fields)


def test_decide_refreshes_company_when_stale_matches():
    action = decide(_existing(), _incoming())
    assert isinstance(action, RefreshCompany)
    assert action.company == "Acme Corp"
    assert action.dedup_key == compute_dedup_key("Acme Corp", "Platform Engineer")


def test_decide_skips_without_stale_company():
    action = decide(_existing(), _incoming(stale_company=None))
    assert isinstance(action, Skip)


def test_decide_skips_when_existing_is_not_the_token():
    action = decide(_existing(company="Acme Corporation"), _incoming())
    assert isinstance(action, Skip)


def test_apply_renames_and_recomputes_key():
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as session:
        session.add(_existing())
        session.commit()
        job, outcome = save_or_upgrade(
            session,
            source="greenhouse",
            jd_text=JD,
            url="https://boards.greenhouse.io/acmecorp/jobs/1",
            company="Acme Corp",
            title="Platform Engineer",
            location="Austin",
            stale_company="acmecorp",
        )
        assert outcome is IngestOutcome.upgraded
        assert job is not None
        assert job.company == "Acme Corp"
        assert job.dedup_key == compute_dedup_key("Acme Corp", "Platform Engineer")
        assert job.jd_text == JD  # frozen-JD rule untouched


def test_apply_downgrades_to_skip_on_collision():
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as session:
        # A properly-named row for the same identity already exists.
        session.add(
            _existing(
                company="Acme Corp",
                url="https://careers.acme.test/1",
                source="manual",
                dedup_key=compute_dedup_key("Acme Corp", "Platform Engineer"),
            )
        )
        session.add(_existing())
        session.commit()
        job, outcome = save_or_upgrade(
            session,
            source="greenhouse",
            jd_text=JD,
            url="https://boards.greenhouse.io/acmecorp/jobs/1",
            company="Acme Corp",
            title="Platform Engineer",
            location="Austin",
            stale_company="acmecorp",
        )
        assert outcome is IngestOutcome.skipped
        token_row = session.exec(
            __import__("sqlmodel").select(Job).where(Job.company == "acmecorp")
        ).first()
        assert token_row is not None  # kept its token name
```

(Replace the dunder-import line with a normal `from sqlmodel import select` at the top — written inline here only for locality.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_merge_refresh_company.py -v`
Expected: FAIL (`ImportError: cannot import name 'RefreshCompany'`)

- [ ] **Step 3: Implement**

`base.py` — append to `RawJob`:

```python
    stale_company: str | None = None
```

`merge.py`:

- `IncomingJob`: add field `stale_company: str | None = None`; add `stale_company: str | None = None` parameter to `clean` and pass `stale_company=_clean(stale_company)`.
- New action (extend the `MergeAction` union):

```python
@dataclass(frozen=True)
class RefreshCompany:
    """Equal-tier heal: replace a token company with the resolved display name.

    dedup_key must change atomically with company (ADR-0004); the applier may
    downgrade to Skip when the new key collides with another live row.
    """

    company: str
    dedup_key: str | None


MergeAction = Insert | Skip | UpgradeUrlOnly | Rebase | RefreshText | RefreshCompany
```

- In `decide`, replace the plain equal-tier skip:

```python
    if source_rank(incoming.source) >= source_rank(existing.source):
        if (
            incoming.company
            and incoming.stale_company
            and existing.company
            and existing.company.strip().lower() == incoming.stale_company.lower()
            and incoming.company.strip().lower() != existing.company.strip().lower()
        ):
            return RefreshCompany(
                company=incoming.company,
                dedup_key=compute_dedup_key(incoming.company, existing.title),
            )
        return Skip()
```

`ingest.py`:

- `save_or_upgrade` gains `stale_company: str | None = None`, passed to `IncomingJob.clean`.
- After `action = decide(existing, incoming)`, add the DB-bound collision downgrade:

```python
    if isinstance(action, RefreshCompany):
        assert existing is not None
        if _rename_collides(session, action.dedup_key, existing):
            action = Skip()
```

with:

```python
def _rename_collides(session: Session, dedup_key: str | None, existing: Job) -> bool:
    """ADR-0004: never rename into another live row's identity."""
    if dedup_key is None:
        return False
    candidates = session.exec(
        select(Job).where(
            col(Job.dedup_key) == dedup_key,
            col(Job.id) != existing.id,
            col(Job.archived_at).is_(None),
        )
    ).all()
    return any(
        locations_compatible(candidate.location, existing.location)
        for candidate in candidates
    )
```

(Import `RefreshCompany` from merge, `locations_compatible` from `resume_tailor_harness.tracking.dedup`, and `select` from sqlmodel — `func`/`select` from sqlalchemy are already imported; use `session.exec(select(...))` in the sqlmodel style used by `pipeline_rows`.)

- In `_apply`, handle the new action before `_persist`:

```python
    elif isinstance(action, RefreshCompany):
        existing.company = action.company
        existing.dedup_key = action.dedup_key
```

- `ingest_jobs_with_outcomes`: pass `stale_company=raw.stale_company` in its `save_or_upgrade` call.

- [ ] **Step 4: Run the merge/ingest suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_merge_refresh_company.py tests/test_discovery_ingest.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/base.py src/resume_tailor_harness/discovery/merge.py src/resume_tailor_harness/discovery/ingest.py tests/test_merge_refresh_company.py
git commit -m "feat: RefreshCompany heal with dedup-key recompute + collision skip (ADR-0004)"
```

---

### Task 18: Connector name resolution (Greenhouse board name, Workday posting company, label plumbing)

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/greenhouse.py`
- Modify: `src/resume_tailor_harness/discovery/connectors/workday.py`
- Modify: `src/resume_tailor_harness/discovery/connectors/companies.py`
- Test: `tests/test_company_resolution.py` (new)

**Interfaces:**

- Consumes: `RawJob.stale_company` (Task 17).
- Produces: precedence **configured label/company → payload-resolved name → raw token**, and `stale_company` set to the token form whenever the final company differs from it:
  - `fetch_greenhouse_board_name(token) -> str | None` — `GET https://boards-api.greenhouse.io/v1/boards/{token}` → `payload.get("name")`; any `httpx.HTTPError` or missing key → `None` (resolution is best-effort decoration, never a Unit failure).
  - `GreenhouseConnector` resolves the name once per board when `board.company` is unset; emitted jobs get `company=resolved or token`, `stale_company=token` when `company != token`.
  - Workday detail parsing: use `jobPostingInfo.get("companyName")` when a non-empty string, else `target.tenant`; `stale_company=target.tenant` when the final value differs.
  - `CompaniesConnector.fetch` label override preserves deepest fallback
    provenance: `job.stale_company = job.stale_company or job.company` before
    `job.company = label` (when they differ).
  - Ashby payload resolution is out of scope: its job-board payload carries no organization name, so configured label/token precedence remains supported.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_company_resolution.py
import httpx

from resume_tailor_harness.discovery.connectors.config import GreenhouseBoard
from resume_tailor_harness.discovery.connectors.greenhouse import (
    GreenhouseConnector,
    fetch_greenhouse_board_name,
    parse_greenhouse,
)
from resume_tailor_harness.discovery.search_config import SearchConfig


def _payload():
    return {
        "jobs": [
            {
                "absolute_url": "https://boards.greenhouse.io/acmecorp/jobs/1",
                "title": "Platform Engineer",
                "location": {"name": "Austin"},
                "content": "<p>Build platforms all day, every day.</p>",
                "updated_at": "2026-07-01T00:00:00Z",
            }
        ]
    }


def test_board_name_failure_returns_none(monkeypatch):
    def boom(url, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", boom)
    assert fetch_greenhouse_board_name("acmecorp") is None


def test_connector_resolves_name_and_sets_stale(monkeypatch):
    connector = GreenhouseConnector([GreenhouseBoard(token="acmecorp")])
    monkeypatch.setattr(connector, "_get_board", lambda token: _payload())
    monkeypatch.setattr(
        "resume_tailor_harness.discovery.connectors.greenhouse.fetch_greenhouse_board_name",
        lambda token: "Acme Corp",
    )
    result = connector.fetch(SearchConfig())
    assert result.jobs[0].company == "Acme Corp"
    assert result.jobs[0].stale_company == "acmecorp"


def test_configured_company_wins_over_resolution(monkeypatch):
    connector = GreenhouseConnector(
        [GreenhouseBoard(token="acmecorp", company="ACME Inc")]
    )
    monkeypatch.setattr(connector, "_get_board", lambda token: _payload())
    monkeypatch.setattr(
        "resume_tailor_harness.discovery.connectors.greenhouse.fetch_greenhouse_board_name",
        lambda token: "Acme Corp",
    )
    result = connector.fetch(SearchConfig())
    assert result.jobs[0].company == "ACME Inc"
    assert result.jobs[0].stale_company == "acmecorp"
```

(If `SearchConfig()` needs arguments in this codebase, copy the construction used by `tests/test_connector_sources.py` or the nearest greenhouse connector test.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_company_resolution.py -v`
Expected: FAIL (`ImportError: fetch_greenhouse_board_name`)

- [ ] **Step 3: Implement**

`greenhouse.py`:

```python
def fetch_greenhouse_board_name(token: str) -> str | None:
    """Best-effort org display name; never a Unit failure (spec W4)."""
    try:
        resp = httpx.get(f"{_BASE}/{token}", timeout=30)
        resp.raise_for_status()
        name = resp.json().get("name")
    except (httpx.HTTPError, ValueError):
        return None
    return name if isinstance(name, str) and name.strip() else None
```

- `parse_greenhouse(payload, company, stale_company=None)`: add the parameter and set `stale_company=stale_company` on each `RawJob`.
- In `GreenhouseConnector.fetch`'s producer lambda:

```python
            lambda board: parse_greenhouse(
                self._get_board(board.token),
                *self._board_identity(board),
            ),
```

with:

```python
    def _board_identity(self, board: GreenhouseBoard) -> tuple[str, str | None]:
        """(company, stale_company) with label > resolved > token precedence."""
        company = board.company or fetch_greenhouse_board_name(board.token) or board.token
        stale = board.token if company != board.token else None
        return company, stale
```

`workday.py` (at the detail-application site around line 164 where `company=target.tenant` is set): read the posting-info company first —

```python
        info_company = job_posting_info.get("companyName")
        company = (
            info_company.strip()
            if isinstance(info_company, str) and info_company.strip()
            else target.tenant
        )
```

and construct the RawJob with `company=company, stale_company=target.tenant if company != target.tenant else None` (adapt the exact local variable names to the function; `job_posting_info` is the dict the JD is read from).

`companies.py` label override block:

```python
        if label:
            # The configured source label is the user's canonical company name.
            # ATS payloads commonly return a lowercase account/token instead.
            for job in jobs:
                if job.company and job.company != label:
                    job.stale_company = job.company
                job.company = label
```

- [ ] **Step 4: Run connector suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_company_resolution.py tests/test_connector_greenhouse.py tests/test_connector_workday.py tests/test_connector_companies.py -v`
(Adjust to the actual connector test filenames — `ls tests | grep -i -E "greenhouse|workday|companies"`.)
Expected: PASS; fix any existing workday/companies fixtures that now assert `company == tenant`.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/discovery/connectors/greenhouse.py src/resume_tailor_harness/discovery/connectors/workday.py src/resume_tailor_harness/discovery/connectors/companies.py tests/test_company_resolution.py
git commit -m "feat: resolve company display names (label > payload > token)"
```

---

### Task 19: `resume-tailor-harness fix-company-names` backfill CLI

**Files:**

- Create: `src/resume_tailor_harness/services/company_fix.py`
- Modify: `src/resume_tailor_harness/cli.py`
- Test: `tests/test_company_fix.py` (new)

**Interfaces:**

- Consumes: `load_connectors_config(path)`, the shared DB-bound rename/collision
  helper from Task 17, connector target detection for configured native/company
  URLs, and `fetch_greenhouse_board_name` (Task 18).
- Produces:

```python
@dataclass(frozen=True)
class CompanyFixReport:
    renamed: dict[str, int]          # token -> rows renamed
    conflicts: list[tuple[int, int]] # (kept_row_id, skipped_row_id) pairs
    unresolved: list[str]            # tokens with no label and no resolvable name

def fix_company_names(
    session: Session,
    config: ConnectorsConfig,
    *,
    dry_run: bool = False,
    resolve: Callable[[str], str | None] | None = None,  # injected for tests; defaults to fetch_greenhouse_board_name
) -> CompanyFixReport
```


  and CLI command `resume-tailor-harness fix-company-names [--dry-run]` printing per-token rename counts, conflicts, and unresolved tokens.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_company_fix.py
"""ADR-0004 backfill: rename token-named rows, skip and report collisions."""
from resume_tailor_harness.db import get_session, init_db, make_engine
from resume_tailor_harness.discovery.connectors.config import ConnectorsConfig
from resume_tailor_harness.services.company_fix import fix_company_names
from resume_tailor_harness.tracking.dedup import compute_dedup_key
from resume_tailor_harness.tracking.tables import Job, JobStatus

JD = "We build rockets and need platform engineers."

CONFIG = ConnectorsConfig.model_validate(
    {
        "greenhouse": {
            "enabled": True,
            "boards": [{"token": "acmecorp", "company": "Acme Corp"}],
        }
    }
)


def _job(company, title="Platform Engineer", location="Austin", **overrides):
    fields = dict(
        source="greenhouse",
        jd_text=JD,
        url=f"https://x.test/{company}/{title}",
        company=company,
        title=title,
        location=location,
        status=JobStatus.raw.value,
        dedup_key=compute_dedup_key(company, title),
    )
    fields.update(overrides)
    return Job(**fields)


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


def test_renames_token_rows_and_recomputes_key():
    with _session() as session:
        session.add(_job("acmecorp"))
        session.commit()
        report = fix_company_names(session, CONFIG)
        row = session.exec(__import__("sqlmodel").select(Job)).first()
    assert report.renamed == {"acmecorp": 1}
    assert row.company == "Acme Corp"
    assert row.dedup_key == compute_dedup_key("Acme Corp", "Platform Engineer")


def test_collision_skips_and_reports():
    with _session() as session:
        session.add(_job("Acme Corp", url="https://y.test/manual"))
        session.add(_job("acmecorp"))
        session.commit()
        report = fix_company_names(session, CONFIG)
        token_rows = [
            row
            for row in session.exec(__import__("sqlmodel").select(Job)).all()
            if row.company == "acmecorp"
        ]
    assert len(report.conflicts) == 1
    assert len(token_rows) == 1  # kept its token name


def test_dry_run_writes_nothing():
    with _session() as session:
        session.add(_job("acmecorp"))
        session.commit()
        report = fix_company_names(session, CONFIG, dry_run=True)
        row = session.exec(__import__("sqlmodel").select(Job)).first()
    assert report.renamed == {"acmecorp": 1}
    assert row.company == "acmecorp"
```

(Again: use a top-level `from sqlmodel import select` in the real file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_company_fix.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

```python
# src/resume_tailor_harness/services/company_fix.py
"""Backfill token company names from configured labels / resolved names.

ADR-0004: renames recompute dedup_key; collisions are skipped and reported,
never merged. Only `company` and `dedup_key` are written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from sqlmodel import Session, col, select

from resume_tailor_harness.discovery.connectors.config import ConnectorsConfig
from resume_tailor_harness.discovery.connectors.greenhouse import fetch_greenhouse_board_name
from resume_tailor_harness.tracking.dedup import compute_dedup_key, locations_compatible
from resume_tailor_harness.tracking.tables import Job


@dataclass(frozen=True)
class CompanyFixReport:
    renamed: dict[str, int] = field(default_factory=dict)
    conflicts: list[tuple[int, int]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def _token_names(
    config: ConnectorsConfig, resolve: Callable[[str], str | None]
) -> tuple[dict[str, str], list[str]]:
    """token -> display name from config labels, then resolution; plus unresolved."""
    mapping: dict[str, str] = {}
    unresolved: list[str] = []
    for board in config.greenhouse.boards:
        name = board.company or resolve(board.token)
        if name and name != board.token:
            mapping[board.token] = name
        elif not board.company:
            unresolved.append(board.token)
    for section in (config.lever, config.ashby):
        for board in section.boards:
            if board.company and board.company != board.token:
                mapping[board.token] = board.company
            else:
                unresolved.append(board.token)
    return mapping, unresolved


def _collides(session: Session, dedup_key: str | None, row: Job) -> bool:
    if dedup_key is None:
        return False
    candidates = session.exec(
        select(Job).where(
            col(Job.dedup_key) == dedup_key,
            col(Job.id) != row.id,
            col(Job.archived_at).is_(None),
        )
    ).all()
    return any(locations_compatible(c.location, row.location) for c in candidates)


def fix_company_names(
    session: Session,
    config: ConnectorsConfig,
    *,
    dry_run: bool = False,
    resolve: Callable[[str], str | None] | None = None,
) -> CompanyFixReport:
    resolve = resolve or fetch_greenhouse_board_name
    mapping, unresolved = _token_names(config, resolve)
    renamed: dict[str, int] = {}
    conflicts: list[tuple[int, int]] = []
    for token, name in mapping.items():
        rows = session.exec(
            select(Job).where(col(Job.company).ilike(token))
        ).all()
        for row in rows:
            new_key = compute_dedup_key(name, row.title)
            if _collides(session, new_key, row):
                keeper = session.exec(
                    select(Job).where(
                        col(Job.dedup_key) == new_key, col(Job.id) != row.id
                    )
                ).first()
                conflicts.append((keeper.id if keeper else -1, row.id or -1))
                continue
            renamed[token] = renamed.get(token, 0) + 1
            if not dry_run:
                row.company = name
                row.dedup_key = new_key
                session.add(row)
    if not dry_run:
        session.commit()
    return CompanyFixReport(
        renamed=renamed, conflicts=conflicts, unresolved=unresolved
    )
```

CLI (in `cli.py`, alongside the other `@app.command` definitions). This mirrors the `pull` command's exact bootstrapping — `DEFAULT_CONNECTORS` option default, `_tenant_cli_path(...)` to resolve the tenant-aware path, `_engine(db_url)` + `get_session(engine)` for the session (all already defined and imported at the top of `cli.py`):

```python
@app.command("fix-company-names")
def fix_company_names_cmd(
    connectors_path: str = typer.Option(
        DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without writing."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Rename token-named companies from labels/resolved names (ADR-0004)."""
    from resume_tailor_harness.discovery.connectors.config import load_connectors_config
    from resume_tailor_harness.services.company_fix import fix_company_names

    if not _tenant_cli_path(connectors_path).exists():
        typer.echo(f"No connectors config found at {connectors_path}.")
        raise typer.Exit(code=1)
    config = load_connectors_config(connectors_path)
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = fix_company_names(session, config, dry_run=dry_run)
    for token, count in sorted(report.renamed.items()):
        typer.echo(f"{token}: {count} row(s) {'would be ' if dry_run else ''}renamed")
    for kept, skipped in report.conflicts:
        typer.echo(f"CONFLICT: row #{skipped} skipped (identity held by #{kept}) — resolve by hand")
    for token in report.unresolved:
        typer.echo(f"unresolved: {token} (no label, no resolvable name)")
```

- [ ] **Step 4: Run tests + smoke the CLI help**

Run: `.venv/Scripts/python.exe -m pytest tests/test_company_fix.py -v` then `.venv/Scripts/python.exe -m resume_tailor_harness --help | grep fix-company-names` (or the repo's CLI entry — check how other CLI tests invoke it in `tests/test_cli_*.py`).
Expected: PASS; command listed.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/company_fix.py src/resume_tailor_harness/cli.py tests/test_company_fix.py
git commit -m "feat: fix-company-names backfill CLI (ADR-0004)"
```

---

## Final verification (after all tasks)

- [ ] Run the full suites: `.venv/Scripts/python.exe -m pytest` and `cd web && npx vitest run` — everything green.
- [ ] `ruff check` — clean.
- [ ] `bash scripts/gen_ts_client.sh` — no residual contract drift (`git status` clean for `contracts/`).
- [ ] Manual smoke (optional, needs a dev server): shortlist toggle + archive undo; a revise launch showing in the RunPanel; the import dialog on Triage.
