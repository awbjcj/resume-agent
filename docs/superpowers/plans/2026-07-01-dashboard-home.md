# Dashboard Home (Phase 3 of dashboard/wizard/config) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A home dashboard at `/` — hero with the actionable total + quick actions, four action-queue cards, a CSS stage rail over the seven pipeline stages, recent runs, and a desk-health card — with Shortlist relocated to `/shortlist`.

**Architecture:** New `web/src/features/dashboard/` composed of small presentational cards fed by one `GET /api/dashboard/summary` query, the existing zustand run store, and the Phase-2 `useSetupStatus` hook. No new backend work: the summary endpoint, setup status, and settings routes all landed in Phases 1–2. The only touches outside the feature folder are the router/nav shuffle, a `?stage=` deep-link for the Pipeline page, and an `updatedAt` stamp on the run store.

**Tech Stack:** React 19, react-router-dom v7, TanStack Query v5, zustand, shadcn (base-ui flavor — `render=` prop, NOT `asChild`), Tailwind v4, vitest + Testing Library + MSW, Playwright.

**Spec:** `docs/superpowers/specs/2026-07-01-dashboard-wizard-config-design.md` (§6 Dashboard, plus §2 route decisions and §8 testing)

## Global Constraints

- **Phases 1 and 2 must be merged first** (plans `2026-07-01-config-api-backend.md`, `2026-07-01-wizard-settings-web.md`): `web/src/lib/api/schema.ts` must contain `/api/dashboard/summary` and `/api/setup/status`; `web/src/features/settings/use-setup-status.ts` must export `useSetupStatus` + `SetupStatus`; `/settings/*` routes and the `SetupGate` must exist.
- Web working dir is `web/`; commands: `npm run test:run`, `npm run lint`, `npm run build`.
- shadcn components live in `web/src/components/ui/` (base-ui flavor: custom triggers use `render={<.../>}`, not `asChild`). Read the installed `ui/*.tsx` source before using a component you haven't used in this plan.
- Semantic color tokens only (`text-muted-foreground`, `bg-card`, `text-destructive`, …); no raw palette classes.
- All copy sentence case, active voice; verbs on buttons/links say what happens.
- **No recharts (or any chart lib) in the dashboard chunk** — the stage rail is pure CSS/flex (spec §6). Charts stay on Analytics.
- Every new page is lazy-loaded in `router.tsx` like the existing pages.
- Zero-count queue cards render muted, never hidden (stable geography, spec §6).
- Tests colocate as `*.test.tsx`/`*.test.ts` next to the code. MSW handlers go through the global server (`@/test/server`, `onUnhandledRequest: "error"` — register a handler for every request a rendered tree fires). Query hooks wrap with `withQueryClient` from `@/test/utils`.
- The API client convention: `unwrap(api.GET(...))` for single resources (see `web/src/lib/api/client.ts`).

---

### Task 1: Dashboard summary hook

**Files:**

- Create: `web/src/features/dashboard/use-dashboard-summary.ts`
- Create: `web/src/features/dashboard/fixtures.ts` (shared `SUMMARY` fixture — later tasks' tests import it; a plain `.ts` file so vitest never collects it as a suite)
- Test: `web/src/features/dashboard/use-dashboard-summary.test.tsx`

**Interfaces:**

- Consumes: `api`, `unwrap` (`@/lib/api/client`); `components["schemas"]["DashboardSummaryOut"]` (`@/lib/api/schema`, generated in Phase 1) — shape `{ statusCounts: Record<string, number>, queues: Record<string, number>, applied: number }` with `statusCounts` keys `raw|extracted|filtered|rejected|shortlisted|approved|tailored|rendered` and `queues` keys `triage|approve|tailor|apply`.
- Produces: `export type DashboardSummary = components["schemas"]["DashboardSummaryOut"]`; `useDashboardSummary(): UseQueryResult<DashboardSummary>` under query key `["dashboard-summary"]`.

- [ ] **Step 1: Write the fixture and the failing test**

```ts
// web/src/features/dashboard/fixtures.ts
export const SUMMARY = {
  statusCounts: {
    raw: 3,
    extracted: 1,
    filtered: 2,
    rejected: 1,
    shortlisted: 4,
    approved: 1,
    tailored: 2,
    rendered: 1,
  },
  queues: { triage: 2, approve: 4, tailor: 1, apply: 1 },
  applied: 5,
};
```

```tsx
// web/src/features/dashboard/use-dashboard-summary.test.tsx
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { SUMMARY } from "./fixtures";
import { useDashboardSummary } from "./use-dashboard-summary";

describe("useDashboardSummary", () => {
  it("loads the summary projection", async () => {
    server.use(
      http.get("/api/dashboard/summary", () => HttpResponse.json(SUMMARY)),
    );

    const { result } = renderHook(() => useDashboardSummary(), {
      wrapper: withQueryClient,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.queues.approve).toBe(4);
    expect(result.current.data?.applied).toBe(5);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/dashboard`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```ts
// web/src/features/dashboard/use-dashboard-summary.ts
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type DashboardSummary = components["schemas"]["DashboardSummaryOut"];

export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: (): Promise<DashboardSummary> =>
      unwrap(api.GET("/api/dashboard/summary")),
  });
}
```

- [ ] **Step 4: Run tests, lint**

Run: `cd web && npx vitest run src/features/dashboard && npm run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/dashboard
git commit -m "feat(web): dashboard summary query hook"
```

---

### Task 2: Pipeline `?stage=` deep link

The Tailor and Apply queue cards (Task 4) link to `/pipeline?stage=approved` and
`/pipeline?stage=rendered`. The Pipeline page currently opens `tailored` +
`rendered` sections; teach it to open exactly the requested stage instead.

**Files:**

- Modify: `web/src/features/pipeline/pipeline-stages.ts`
- Modify: `web/src/features/pipeline/PipelineContainer.tsx:82-89`
- Test: `web/src/features/pipeline/pipeline-stages.test.ts` (new file)

**Interfaces:**

- Consumes: `initialOpenPipelineStages`, `PIPELINE_STAGE_ORDER` (already in `pipeline-stages.ts`).
- Produces: `openStagesFromParam(stage: string | null): Set<string>` — a valid stage name yields `Set([stage])`; `null` or an unknown value yields `initialOpenPipelineStages()`.

- [ ] **Step 1: Write the failing test**

```ts
// web/src/features/pipeline/pipeline-stages.test.ts
import { describe, expect, it } from "vitest";

import {
  initialOpenPipelineStages,
  openStagesFromParam,
} from "./pipeline-stages";

describe("openStagesFromParam", () => {
  it("opens exactly the requested stage", () => {
    expect(openStagesFromParam("approved")).toEqual(new Set(["approved"]));
  });

  it("falls back to the defaults without a param", () => {
    expect(openStagesFromParam(null)).toEqual(initialOpenPipelineStages());
  });

  it("ignores unknown stage names", () => {
    expect(openStagesFromParam("bogus")).toEqual(initialOpenPipelineStages());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/pipeline/pipeline-stages.test.ts`
Expected: FAIL — `openStagesFromParam` is not exported

- [ ] **Step 3: Implement**

Append to `web/src/features/pipeline/pipeline-stages.ts`:

```ts
export function openStagesFromParam(stage: string | null): Set<string> {
  return stage && (PIPELINE_STAGE_ORDER as readonly string[]).includes(stage)
    ? new Set([stage])
    : initialOpenPipelineStages();
}
```

In `PipelineContainer.tsx`, the `useSearchParams()` call (currently line 89)
must move **above** the `openStages` state (currently line 82) so the lazy
initializer can read it:

```tsx
const [params, setParams] = useSearchParams();
const [openStages, setOpenStages] = useState(() =>
  openStagesFromParam(params.get("stage")),
);
```

Add `openStagesFromParam` to the existing `./pipeline-stages` import. This is a
mount-time seed only — no effect re-syncing on param change (the dashboard
always triggers a fresh mount via navigation).

- [ ] **Step 4: Run the pipeline feature tests, lint**

Run: `cd web && npx vitest run src/features/pipeline && npm run lint`
Expected: PASS (including the existing `PipelineContainer.test.tsx` — if it
renders the container without a router, it already must provide one since the
container calls `useSearchParams`; no change expected)

- [ ] **Step 5: Commit**

```bash
git add web/src/features/pipeline
git commit -m "feat(web): pipeline stage deep link via ?stage= param"
```

---

### Task 3: Stage rail

**Files:**

- Create: `web/src/features/dashboard/StageRail.tsx`
- Test: `web/src/features/dashboard/StageRail.test.tsx`

**Interfaces:**

- Consumes: `DashboardSummary` (Task 1), `cn` (`@/lib/utils`).
- Produces: `StageRail({ summary }: { summary: DashboardSummary })`; `RAIL_STAGES` export — seven `{ key, label, count(summary) }` entries in pipeline order.

Stage mapping (the rail's seven stages over the eight DB statuses + applied):
`raw` = `raw + extracted` (both machine-side intake), `triage` = `filtered`
(awaiting the user's triage pass), then `shortlisted`, `approved`, `tailored`,
`rendered` one-to-one, and `applied` = the summary's `applied` count.
`rejected` is terminal-negative and stays off the rail.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/dashboard/StageRail.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SUMMARY } from "./fixtures";
import { StageRail, RAIL_STAGES } from "./StageRail";

describe("StageRail", () => {
  it("renders all seven stages with mapped counts", () => {
    render(<StageRail summary={SUMMARY} />);
    expect(RAIL_STAGES).toHaveLength(7);
    // raw folds in extracted: 3 + 1
    expect(screen.getByText("Raw").previousElementSibling).toHaveTextContent(
      "4",
    );
    expect(screen.getByText("Triage").previousElementSibling).toHaveTextContent(
      "2",
    );
    expect(
      screen.getByText("Applied").previousElementSibling,
    ).toHaveTextContent("5");
  });

  it("mutes zero-count stages without hiding them", () => {
    const zeroed = {
      ...SUMMARY,
      statusCounts: { ...SUMMARY.statusCounts, approved: 0 },
    };
    render(<StageRail summary={zeroed} />);
    const approved = screen.getByText("Approved").closest("li");
    expect(approved).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/dashboard/StageRail.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```tsx
// web/src/features/dashboard/StageRail.tsx
import { cn } from "@/lib/utils";

import type { DashboardSummary } from "./use-dashboard-summary";

type Stage = {
  key: string;
  label: string;
  count: (s: DashboardSummary) => number;
};

const status = (key: string) => (s: DashboardSummary) =>
  s.statusCounts[key] ?? 0;

export const RAIL_STAGES: Stage[] = [
  {
    key: "raw",
    label: "Raw",
    count: (s) => (s.statusCounts.raw ?? 0) + (s.statusCounts.extracted ?? 0),
  },
  { key: "triage", label: "Triage", count: status("filtered") },
  { key: "shortlist", label: "Shortlist", count: status("shortlisted") },
  { key: "approved", label: "Approved", count: status("approved") },
  { key: "tailored", label: "Tailored", count: status("tailored") },
  { key: "rendered", label: "Rendered", count: status("rendered") },
  { key: "applied", label: "Applied", count: (s) => s.applied },
];

export function StageRail({ summary }: { summary: DashboardSummary }) {
  return (
    <ol
      aria-label="Pipeline stages"
      className="flex flex-wrap items-center gap-y-3 rounded-lg border bg-card px-4 py-4 shadow-sm"
    >
      {RAIL_STAGES.map((stage, index) => {
        const count = stage.count(summary);
        return (
          <li key={stage.key} className="flex min-w-0 flex-1 items-center">
            {index > 0 && (
              // Thin connecting tick between stages (spec §6) — decorative only.
              <span
                aria-hidden="true"
                className="mx-2 h-px w-full max-w-8 shrink bg-border"
              />
            )}
            <div className={cn("min-w-0", count === 0 && "opacity-45")}>
              <div className="text-2xl font-semibold tabular-nums leading-none">
                {count}
              </div>
              <div className="mt-1 truncate text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                {stage.label}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
```

- [ ] **Step 4: Run tests, lint**

Run: `cd web && npx vitest run src/features/dashboard && npm run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/dashboard
git commit -m "feat(web): dashboard stage rail over the seven pipeline stages"
```

---

### Task 4: Action queue cards

**Files:**

- Create: `web/src/features/dashboard/ActionQueue.tsx`
- Test: `web/src/features/dashboard/ActionQueue.test.tsx`

**Interfaces:**

- Consumes: `DashboardSummary` (Task 1); `Card`, `CardDescription`, `CardTitle` (`@/components/ui/card`); `Link` (react-router); the Task-2 pipeline deep link.
- Produces: `ActionQueue({ summary })`; `QUEUE_CARDS` export — `{ key, verb, sub, to }[]` in order triage → approve → tailor → apply.

Deep-link targets (grounded in what each board actually serves):

- **Triage** → `/triage` (the triage board is scoped to raw/extracted/filtered/rejected already).
- **Approve** → `/shortlist` (the shortlist board serves only `shortlisted` rows — `queries.shortlist_rows`).
- **Tailor** → `/pipeline?stage=approved` (Task 2 opens that section).
- **Apply** → `/pipeline?stage=rendered`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/dashboard/ActionQueue.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ActionQueue, QUEUE_CARDS } from "./ActionQueue";
import { SUMMARY } from "./use-dashboard-summary.test";

const renderQueue = (summary = SUMMARY) =>
  render(
    <MemoryRouter>
      <ActionQueue summary={summary} />
    </MemoryRouter>,
  );

describe("ActionQueue", () => {
  it("renders four cards linking to their boards", () => {
    renderQueue();
    expect(QUEUE_CARDS.map((c) => c.key)).toEqual([
      "triage",
      "approve",
      "tailor",
      "apply",
    ]);
    expect(screen.getByRole("link", { name: /triage 2/i })).toHaveAttribute(
      "href",
      "/triage",
    );
    expect(screen.getByRole("link", { name: /approve 4/i })).toHaveAttribute(
      "href",
      "/shortlist",
    );
    expect(screen.getByRole("link", { name: /tailor 1/i })).toHaveAttribute(
      "href",
      "/pipeline?stage=approved",
    );
    expect(screen.getByRole("link", { name: /apply 1/i })).toHaveAttribute(
      "href",
      "/pipeline?stage=rendered",
    );
  });

  it("keeps zero-count cards visible", () => {
    renderQueue({
      ...SUMMARY,
      queues: { triage: 0, approve: 0, tailor: 0, apply: 0 },
    });
    expect(screen.getAllByRole("link")).toHaveLength(4);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/dashboard/ActionQueue.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```tsx
// web/src/features/dashboard/ActionQueue.tsx
import { Link } from "react-router-dom";

import { Card, CardDescription, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import type { DashboardSummary } from "./use-dashboard-summary";

export const QUEUE_CARDS = [
  { key: "triage", verb: "Triage", sub: "new jobs to sort", to: "/triage" },
  {
    key: "approve",
    verb: "Approve",
    sub: "shortlisted picks",
    to: "/shortlist",
  },
  {
    key: "tailor",
    verb: "Tailor",
    sub: "approved and ready",
    to: "/pipeline?stage=approved",
  },
  {
    key: "apply",
    verb: "Apply",
    sub: "rendered resumes",
    to: "/pipeline?stage=rendered",
  },
] as const;

export function ActionQueue({ summary }: { summary: DashboardSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      {QUEUE_CARDS.map((card) => {
        const count = summary.queues[card.key] ?? 0;
        return (
          <Link
            key={card.key}
            to={card.to}
            aria-label={`${card.verb} ${count} ${card.sub}`}
            className="group rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Card
              className={cn(
                "gap-1 p-4 transition-colors group-hover:border-primary/40",
                count === 0 && "opacity-55",
              )}
            >
              <div className="text-3xl font-semibold tabular-nums leading-none">
                {count}
              </div>
              <CardTitle className="text-sm">{card.verb}</CardTitle>
              <CardDescription className="text-xs">{card.sub}</CardDescription>
            </Card>
          </Link>
        );
      })}
    </div>
  );
}
```

Before finalizing, read the installed `web/src/components/ui/card.tsx` — if
`Card` applies default padding/gap classes that fight `p-4`/`gap-1`, prefer the
Card's own layout and adjust the test only if the accessible name changes.

- [ ] **Step 4: Run tests, lint**

Run: `cd web && npx vitest run src/features/dashboard && npm run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/dashboard
git commit -m "feat(web): dashboard action queue cards with board deep links"
```

---

### Task 5: Recent runs card (+ `updatedAt` on the run store)

The backend `RunOut` carries no timestamps, so relative time comes from a
client-side stamp: `upsert` records when each run record last changed.

**Files:**

- Modify: `web/src/lib/runs/store.ts`
- Create: `web/src/features/dashboard/RecentRuns.tsx`
- Create: `web/src/features/dashboard/time-ago.ts`
- Test: `web/src/lib/runs/store.test.ts` (extend — read its existing style first), `web/src/features/dashboard/RecentRuns.test.tsx`, `web/src/features/dashboard/time-ago.test.ts`

**Interfaces:**

- Consumes: `useRunStore`, `RunRecord` (`@/lib/runs/store`); `Progress` (`@/components/ui/progress`).
- Produces: `RunRecord.updatedAt?: number` (epoch ms, stamped by `upsert`); `timeAgo(thenMs: number, nowMs?: number): string`; `RecentRuns()` (no props — reads the store).

- [ ] **Step 1: Write the failing tests**

```ts
// web/src/features/dashboard/time-ago.test.ts
import { describe, expect, it } from "vitest";

import { timeAgo } from "./time-ago";

const NOW = 1_700_000_000_000;

describe("timeAgo", () => {
  it("says just now under a minute", () => {
    expect(timeAgo(NOW - 30_000, NOW)).toBe("just now");
  });
  it("reports minutes, hours, days", () => {
    expect(timeAgo(NOW - 5 * 60_000, NOW)).toBe("5m ago");
    expect(timeAgo(NOW - 3 * 3_600_000, NOW)).toBe("3h ago");
    expect(timeAgo(NOW - 2 * 86_400_000, NOW)).toBe("2d ago");
  });
});
```

```tsx
// web/src/features/dashboard/RecentRuns.test.tsx
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useRunStore } from "@/lib/runs/store";
import { RecentRuns } from "./RecentRuns";

const base = { percent: 0, phase: "", current: 0, total: 0, etaText: null };

describe("RecentRuns", () => {
  beforeEach(() => useRunStore.setState({ runs: {} }));

  it("shows an empty hint when there are no runs", () => {
    render(<RecentRuns />);
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
  });

  it("lists active runs before finished ones", () => {
    useRunStore.getState().upsert({
      ...base,
      runId: "a",
      kind: "pull",
      status: "succeeded",
      percent: 100,
    });
    useRunStore.getState().upsert({
      ...base,
      runId: "b",
      kind: "discover",
      status: "running",
      percent: 40,
    });
    render(<RecentRuns />);
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("discover");
    expect(items[1]).toHaveTextContent("pull");
    expect(items[1]).toHaveTextContent(/done/i);
    expect(items[1]).toHaveTextContent(/just now/i);
  });

  it("caps the list at five runs", () => {
    for (let i = 0; i < 7; i++) {
      useRunStore.getState().upsert({
        ...base,
        runId: `r${i}`,
        kind: "pull",
        status: "succeeded",
        percent: 100,
      });
    }
    render(<RecentRuns />);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });
});
```

Store test — append to the existing `web/src/lib/runs/store.test.ts`, matching
its current describe/reset style (read the file first; if it resets via
`useRunStore.setState({ runs: {} })`, do the same):

```ts
it("stamps updatedAt on every upsert", () => {
  useRunStore.getState().upsert({
    runId: "x",
    kind: "pull",
    status: "running",
    percent: 0,
    phase: "",
    current: 0,
    total: 0,
    etaText: null,
  });
  const rec = useRunStore.getState().runs["x"];
  expect(typeof rec.updatedAt).toBe("number");
  expect(rec.updatedAt).toBeGreaterThan(0);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/features/dashboard src/lib/runs`
Expected: the three new specs FAIL (module not found / `updatedAt` undefined)

- [ ] **Step 3: Implement**

`web/src/lib/runs/store.ts` — add the field and stamp it (two edits):

```ts
// in RunRecord:
  subject?: { kind: "skill" | "theme"; key: string };
  /** Epoch ms of the last upsert for this run — client-side only. */
  updatedAt?: number;
```

```ts
// in the store:
  upsert: (r) =>
    set((s) => ({
      runs: { ...s.runs, [r.runId]: { ...s.runs[r.runId], ...r, updatedAt: Date.now() } },
    })),
```

```ts
// web/src/features/dashboard/time-ago.ts
export function timeAgo(thenMs: number, nowMs: number = Date.now()): string {
  const seconds = Math.max(0, Math.floor((nowMs - thenMs) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
```

```tsx
// web/src/features/dashboard/RecentRuns.tsx
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useRunStore, type RunRecord } from "@/lib/runs/store";

import { timeAgo } from "./time-ago";

const ACTIVE: RunRecord["status"][] = ["running", "cancelling", "queued"];

const OUTCOME: Partial<Record<RunRecord["status"], string>> = {
  succeeded: "done",
  failed: "failed",
  cancelled: "cancelled",
};

function order(a: RunRecord, b: RunRecord): number {
  const activeDelta =
    Number(ACTIVE.includes(b.status)) - Number(ACTIVE.includes(a.status));
  return activeDelta || (b.updatedAt ?? 0) - (a.updatedAt ?? 0);
}

export function RecentRuns() {
  // Select the stable map reference (same reasoning as RunPanel): deriving the
  // array inside the selector would return a fresh array every render.
  const runsMap = useRunStore((s) => s.runs);
  const runs = Object.values(runsMap).sort(order).slice(0, 5);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Recent runs
        </CardTitle>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No runs yet — pull or discover to get things moving.
          </p>
        ) : (
          <ul className="flex flex-col gap-3">
            {runs.map((run) => (
              <li key={run.runId} className="min-w-0">
                <div className="flex items-baseline justify-between gap-3 text-xs font-semibold uppercase tracking-[0.14em]">
                  <span className="truncate">
                    {run.kind}
                    {run.phase ? ` · ${run.phase}` : ""}
                  </span>
                  <span
                    className={`shrink-0 tabular-nums ${
                      run.status === "failed"
                        ? "text-destructive"
                        : "text-muted-foreground"
                    }`}
                  >
                    {ACTIVE.includes(run.status)
                      ? `${Math.round(run.percent)}%`
                      : `${OUTCOME[run.status] ?? run.status}${
                          run.updatedAt ? ` · ${timeAgo(run.updatedAt)}` : ""
                        }`}
                  </span>
                </div>
                {ACTIVE.includes(run.status) && (
                  <Progress
                    value={Math.round(run.percent)}
                    aria-label={`${run.kind} progress`}
                    className="mt-1.5 h-1.5"
                  />
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 4: Run the web suite, lint**

Run: `cd web && npm run test:run && npm run lint`
Expected: PASS — including the existing `RunPanel`/store/tracker tests, which
must not care about the extra `updatedAt` field

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/runs web/src/features/dashboard
git commit -m "feat(web): recent runs card with client-side run timestamps"
```

---

### Task 6: Desk health card

**Files:**

- Create: `web/src/features/dashboard/DeskHealth.tsx`
- Test: `web/src/features/dashboard/DeskHealth.test.tsx`

**Interfaces:**

- Consumes: `useSetupStatus`, `SetupStatus` (`@/features/settings/use-setup-status`, Phase 2) — status shape `{ secrets: { anthropicKey, anyLlmKey }, profile: { documentCount, hasResume, factsBuiltAt, githubUsername }, search: { configured }, sources: { enabledCount }, complete }`; `CheckCircle2`, `AlertCircle` (lucide-react).
- Produces: `DeskHealth()`; `HEALTH_ITEMS` export — `{ key, label, to, ok(status) }[]`.

Behavior: five check lines, each linking to the settings page that fixes it;
a "Resume setup" link to `/setup` while `complete` is false; renders `null`
while loading **and on fetch error** (fail-open — the dashboard must never
break because setup-status did, spec §7).

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/dashboard/DeskHealth.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { DeskHealth } from "./DeskHealth";

const STATUS = {
  secrets: { anthropicKey: true, anyLlmKey: true },
  profile: {
    documentCount: 1,
    hasResume: true,
    factsBuiltAt: null,
    githubUsername: null,
  },
  search: { configured: false },
  sources: { enabledCount: 0 },
  complete: false,
};

function renderHealth() {
  return render(
    <MemoryRouter>
      <DeskHealth />
    </MemoryRouter>,
    { wrapper: withQueryClient },
  );
}

describe("DeskHealth", () => {
  it("links each incomplete line to its settings page", async () => {
    server.use(http.get("/api/setup/status", () => HttpResponse.json(STATUS)));
    renderHealth();
    await waitFor(() =>
      expect(screen.getByRole("link", { name: /search/i })).toHaveAttribute(
        "href",
        "/settings/search",
      ),
    );
    expect(screen.getByRole("link", { name: /sources/i })).toHaveAttribute(
      "href",
      "/settings/sources",
    );
    expect(screen.getByRole("link", { name: /resume setup/i })).toHaveAttribute(
      "href",
      "/setup",
    );
  });

  it("shows the ready state when setup is complete", async () => {
    server.use(
      http.get("/api/setup/status", () =>
        HttpResponse.json({
          ...STATUS,
          profile: { ...STATUS.profile, factsBuiltAt: "2026-07-01T00:00:00Z" },
          search: { configured: true },
          sources: { enabledCount: 2 },
          complete: true,
        }),
      ),
    );
    renderHealth();
    await waitFor(() =>
      expect(screen.getByText(/desk is ready/i)).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("link", { name: /resume setup/i }),
    ).not.toBeInTheDocument();
  });

  it("renders nothing when the status endpoint errors", async () => {
    server.use(
      http.get("*/api/setup/status", () =>
        HttpResponse.json(
          { error: { code: "X", message: "boom" } },
          { status: 500 },
        ),
      ),
    );
    const { container } = renderHealth();
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
```

Note the `wrapper: withQueryClient` + `MemoryRouter` combination — if
`withQueryClient` doesn't compose as a `render` wrapper with a router child in
this repo's other tests, nest the providers explicitly the way
`SetupGate.test.tsx` (Phase 2) does.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/dashboard/DeskHealth.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```tsx
// web/src/features/dashboard/DeskHealth.tsx
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Link } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  useSetupStatus,
  type SetupStatus,
} from "@/features/settings/use-setup-status";

type HealthItem = {
  key: string;
  label: string;
  to: string;
  ok: (s: SetupStatus) => boolean;
};

export const HEALTH_ITEMS: HealthItem[] = [
  {
    key: "key",
    label: "Anthropic API key",
    to: "/settings/keys",
    ok: (s) => s.secrets.anthropicKey,
  },
  {
    key: "resume",
    label: "Resume document",
    to: "/settings/profile",
    ok: (s) => s.profile.hasResume,
  },
  {
    key: "facts",
    label: "Profile facts built",
    to: "/settings/profile",
    ok: (s) => s.profile.factsBuiltAt != null,
  },
  {
    key: "search",
    label: "Search configured",
    to: "/settings/search",
    ok: (s) => s.search.configured,
  },
  {
    key: "sources",
    label: "Sources enabled",
    to: "/settings/sources",
    ok: (s) => s.sources.enabledCount > 0,
  },
];

export function DeskHealth() {
  const { data: status, isError, isPending } = useSetupStatus();
  // Fail-open: a broken status endpoint must not break the dashboard (spec §7).
  if (isPending || isError || !status) return null;
  const allOk = HEALTH_ITEMS.every((item) => item.ok(status));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Desk health
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {allOk ? (
          <p className="flex items-center gap-2 text-sm">
            <CheckCircle2 className="size-4 text-primary" aria-hidden="true" />
            Desk is ready — every setup check passes.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {HEALTH_ITEMS.map((item) => {
              const ok = item.ok(status);
              return (
                <li key={item.key} className="flex items-center gap-2 text-sm">
                  {ok ? (
                    <CheckCircle2
                      className="size-4 shrink-0 text-primary"
                      aria-hidden="true"
                    />
                  ) : (
                    <AlertCircle
                      className="size-4 shrink-0 text-destructive"
                      aria-hidden="true"
                    />
                  )}
                  {ok ? (
                    <span className="text-muted-foreground">{item.label}</span>
                  ) : (
                    <Link
                      to={item.to}
                      className="underline-offset-4 hover:underline"
                    >
                      {item.label}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        {!status.complete && (
          <Link
            to="/setup"
            className="mt-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Resume setup
          </Link>
        )}
      </CardContent>
    </Card>
  );
}
```

Check the Phase-2 `useSetupStatus` implementation before wiring: if it exposes
`isLoading` instead of `isPending` (TanStack v5 uses `isPending`), match what
it actually returns.

- [ ] **Step 4: Run tests, lint**

Run: `cd web && npx vitest run src/features/dashboard && npm run lint`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/features/dashboard
git commit -m "feat(web): desk health card from setup status"
```

---

### Task 7: Dashboard page, hero, route shuffle, nav

**Files:**

- Create: `web/src/features/dashboard/DashboardPage.tsx`
- Modify: `web/src/app/router.tsx` (index → dashboard, add `/shortlist`)
- Modify: `web/src/app/AppLayout.tsx` (NAV: Dashboard first, Shortlist at `/shortlist`)
- Test: `web/src/features/dashboard/DashboardPage.test.tsx`

**Interfaces:**

- Consumes: everything from Tasks 1, 3–6; `PullDialog`, `DiscoverDialog` (`@/features/runs/RunLaunchDialogs`), `AddUrlDialog` (`@/features/runs/AddUrlDialog`) — the exact run-trigger components behind the header's `RunActions` (spec §6); `Empty`, `EmptyHeader`, `EmptyTitle`, `EmptyDescription`, `EmptyContent` (`@/components/ui/empty`); `Button` (`@/components/ui/button`).
- Produces: `DashboardPage()`; `heroTitle(waiting: number): string` (exported for the test); route `/` renders the dashboard, `/shortlist` renders `ShortlistPage`.

Hero copy (exact):

- eyebrow: `OPERATIONS · <Jul 2>` — `new Date().toLocaleDateString(undefined, { month: "short", day: "numeric" })`, uppercased by the kicker style.
- `heroTitle(0)` → `"Nothing is waiting on you"`; `heroTitle(1)` → `"1 job is waiting on you"`; `heroTitle(n)` → `` `${n} jobs are waiting on you` ``.
- sub: `"Pull fresh listings, triage the queue, and ship tailored resumes."`

Empty-install degradation (spec §6): when every `statusCounts` value is zero,
replace the queue + rail with an `Empty` block — title `"Add sources and run
your first pull"`, description `"The funnel fills up once discovery has
somewhere to look."`, content: a Button-link to `/settings/sources` plus the
`PullDialog` trigger. Health card and recent runs stay visible.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/dashboard/DashboardPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { withQueryClient } from "@/test/utils";
import { DashboardPage, heroTitle } from "./DashboardPage";
import { SUMMARY } from "./use-dashboard-summary.test";

const READY_STATUS = {
  secrets: { anthropicKey: true, anyLlmKey: true },
  profile: {
    documentCount: 1,
    hasResume: true,
    factsBuiltAt: "2026-07-01T00:00:00Z",
    githubUsername: null,
  },
  search: { configured: true },
  sources: { enabledCount: 2 },
  complete: true,
};

function renderPage() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
    { wrapper: withQueryClient },
  );
}

describe("heroTitle", () => {
  it("states the actionable total grammatically", () => {
    expect(heroTitle(0)).toBe("Nothing is waiting on you");
    expect(heroTitle(1)).toBe("1 job is waiting on you");
    expect(heroTitle(8)).toBe("8 jobs are waiting on you");
  });
});

describe("DashboardPage", () => {
  it("renders hero total, queue cards, and stage rail from the summary", async () => {
    server.use(
      http.get("/api/dashboard/summary", () => HttpResponse.json(SUMMARY)),
      http.get("/api/setup/status", () => HttpResponse.json(READY_STATUS)),
    );
    renderPage();
    // queues sum: 2 + 4 + 1 + 1
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "8 jobs are waiting on you" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("link", { name: /approve 4/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Pipeline stages")).toBeInTheDocument();
    expect(screen.getByText(/recent runs/i)).toBeInTheDocument();
  });

  it("degrades to the onboarding empty state on a fresh install", async () => {
    const zero = Object.fromEntries(
      Object.keys(SUMMARY.statusCounts).map((k) => [k, 0]),
    );
    server.use(
      http.get("/api/dashboard/summary", () =>
        HttpResponse.json({
          statusCounts: zero,
          queues: { triage: 0, approve: 0, tailor: 0, apply: 0 },
          applied: 0,
        }),
      ),
      http.get("/api/setup/status", () =>
        HttpResponse.json({
          ...READY_STATUS,
          complete: false,
          sources: { enabledCount: 0 },
        }),
      ),
    );
    renderPage();
    await waitFor(() =>
      expect(
        screen.getByText("Add sources and run your first pull"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Pipeline stages")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /add sources/i })).toHaveAttribute(
      "href",
      "/settings/sources",
    );
  });
});
```

If rendering the page fires requests beyond these two (MSW errors on unhandled
requests), the culprit is one of the run dialogs prefetching — check which
endpoint it hits and register a stub handler for it rather than removing the
dialog.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/dashboard/DashboardPage.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the page**

```tsx
// web/src/features/dashboard/DashboardPage.tsx
import { Link } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";
import { AddUrlDialog } from "@/features/runs/AddUrlDialog";
import { DiscoverDialog, PullDialog } from "@/features/runs/RunLaunchDialogs";
import { BoardSkeleton } from "@/components/skeletons";

import { ActionQueue } from "./ActionQueue";
import { DeskHealth } from "./DeskHealth";
import { RecentRuns } from "./RecentRuns";
import { StageRail } from "./StageRail";
import { useDashboardSummary } from "./use-dashboard-summary";

export function heroTitle(waiting: number): string {
  if (waiting === 0) return "Nothing is waiting on you";
  return `${waiting} job${waiting === 1 ? " is" : "s are"} waiting on you`;
}

export function DashboardPage() {
  const { data: summary, isPending } = useDashboardSummary();
  if (isPending || !summary) return <BoardSkeleton />;

  const waiting = Object.values(summary.queues).reduce((a, b) => a + b, 0);
  const totalJobs = Object.values(summary.statusCounts).reduce(
    (a, b) => a + b,
    0,
  );
  const eyebrow = `Operations · ${new Date().toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })}`;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        kicker={eyebrow}
        title={heroTitle(waiting)}
        sub="Pull fresh listings, triage the queue, and ship tailored resumes."
      />
      <div className="flex flex-wrap items-center gap-2">
        <PullDialog />
        <DiscoverDialog />
        <AddUrlDialog />
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex min-w-0 flex-col gap-6">
          {totalJobs === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyTitle>Add sources and run your first pull</EmptyTitle>
                <EmptyDescription>
                  The funnel fills up once discovery has somewhere to look.
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <div className="flex flex-wrap items-center justify-center gap-2">
                  <Button
                    render={<Link to="/settings/sources">Add sources</Link>}
                  />
                  <PullDialog />
                </div>
              </EmptyContent>
            </Empty>
          ) : (
            <>
              <ActionQueue summary={summary} />
              <StageRail summary={summary} />
            </>
          )}
          <RecentRuns />
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <DeskHealth />
        </div>
      </div>
    </div>
  );
}
```

Two component caveats to verify against installed source before running:
`Button` in the base-ui flavor takes `render=` for link-buttons (see how
`RunLaunchDialogs` uses `DialogTrigger render={<Button .../>}`) — if the
installed `button.tsx` has no `render` prop, use
`<Button asChild>`-equivalent per its actual API or wrap with the Link outside.
`PageHeader`'s kicker is styled uppercase via `uppercase tracking` classes, so
pass `Operations · Jul 2` in sentence case and let CSS uppercase it.

- [ ] **Step 4: Route shuffle + nav**

`web/src/app/router.tsx` — add the lazy import and swap the index route;
Shortlist keeps its chunk, just moves path:

```tsx
const DashboardPage = lazy(() =>
  import("@/features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
// children:
{ index: true, element: page(<DashboardPage />) },
{ path: "shortlist", element: page(<ShortlistPage />) },
```

`web/src/app/AppLayout.tsx` — NAV becomes (Dashboard above the work pages;
Shortlist stays first among them, spec §6):

```tsx
import { LayoutDashboard } from "lucide-react";

const NAV: { to: string; label: string; end?: boolean; icon: LucideIcon }[] = [
  { to: "/", label: "Dashboard", end: true, icon: LayoutDashboard },
  { to: "/shortlist", label: "Shortlist", icon: Briefcase },
  { to: "/pipeline", label: "Pipeline", icon: Kanban },
  { to: "/triage", label: "Triage", icon: Inbox },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/match-gap", label: "Match-gap", icon: Target },
];
```

(After Phase 2's Task 9 the Sources entry is already gone from NAV; if it is
still present when you get here, leave it — removing it belongs to that task.)

Then sweep for links that meant "the shortlist board" and now hit the
dashboard:

```bash
cd web && grep -rn 'to="/"' src --include='*.tsx' && grep -rn 'navigate("/")' src --include='*.tsx'
```

For each hit, decide by intent: navigation that means "go home" stays `/`
(e.g. the wizard's "Go to dashboard", the sidebar brand); navigation that
means "back to the board" becomes `/shortlist`. Update any test that asserted
the old index route (`ShortlistContainer.test.tsx` renders the container
directly, so it should be unaffected; the a11y test `src/test/a11y.test.tsx`
may mount the router — read it if it fails).

- [ ] **Step 5: Run the full web suite, lint, build**

Run: `cd web && npm run test:run && npm run lint && npm run build`
Expected: PASS; the build output should show the dashboard chunk WITHOUT
recharts (grep the build log for the chunk name if in doubt — recharts must
only appear in the Analytics chunk)

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "feat(web): dashboard home at / with hero, queues, stage rail; shortlist moves to /shortlist"
```

---

### Task 8: E2E smoke + repo gates

**Files:**

- Create or extend: `web/e2e/dashboard.spec.ts` (Phase 2's Task 10 created `web/e2e/setup-wizard.spec.ts` — follow its backend-provisioning convention exactly; read `web/playwright.config.ts` first)

- [ ] **Step 1: Write the smoke spec**

```ts
// web/e2e/dashboard.spec.ts
import { expect, test } from "@playwright/test";

// Assumes a backend with completed setup (or a dismissed gate) — mirror how
// setup-wizard.spec.ts provisions state; if it uses a fresh backend, dismiss
// the gate first via the "Exit setup" button.
test("dashboard is home and queue cards deep-link", async ({ page }) => {
  await page.goto("/");
  if (page.url().includes("/setup")) {
    await page.getByRole("button", { name: "Exit setup" }).click();
  }
  await expect(
    page.getByText(/waiting on you|nothing is waiting/i),
  ).toBeVisible();

  await page.getByRole("link", { name: "Shortlist" }).click();
  await expect(page).toHaveURL(/\/shortlist/);

  await page.goBack();
  await page
    .getByRole("link", { name: /triage/i })
    .first()
    .click();
  await expect(page).toHaveURL(/\/triage/);
});
```

- [ ] **Step 2: Run e2e**

Run: `cd web && npm run e2e`
Expected: PASS (if the e2e infra can't provide a live backend for the summary
endpoint, `test.skip` with a comment explaining why — same escape hatch Phase
2's Task 10 documents)

- [ ] **Step 3: Full repo gates**

```bash
.venv/Scripts/python.exe -m pytest && ruff check
cd web && npm run test:run && npm run lint && npm run build
```

Expected: all green. No backend files changed in this phase, so the pytest run
is a regression check only; the OpenAPI contract is untouched.

- [ ] **Step 4: Commit**

```bash
git add web/e2e
git commit -m "test(web): dashboard e2e smoke"
```

---

## Self-review notes (already applied)

- **Spec §6 coverage:** hero (Task 7), action queue (Task 4), stage rail (Task 3), recent runs (Task 5), desk health (Task 6), empty-install degradation (Task 7), route shuffle + nav (Task 7), single summary call (Task 1). §2 route decisions (dashboard at `/`, Shortlist `/shortlist`) → Task 7. §8 frontend testing → per-task vitest + Task 8 Playwright.
- **Deep-link honesty:** the Tailor/Apply cards need `/pipeline?stage=`, which does not exist today — Task 2 adds it _before_ Task 4 links to it. Approve links to `/shortlist` because `shortlist_rows` serves only `shortlisted` jobs; Triage links to `/triage` unfiltered because the triage board is already scoped.
- **No timestamps on `RunOut`:** verified against `web/src/lib/api/schema.ts` — hence the client-side `updatedAt` stamp in Task 5 rather than a phantom backend field.
- **Places the implementer must adapt to code they'll find, flagged inline:** existing `store.test.ts` style (Task 5), `useSetupStatus`'s pending/error flags (Task 6), installed `card.tsx`/`button.tsx`/`empty.tsx` prop details (Tasks 4, 7), Phase-2 e2e backend provisioning (Task 8), and the `to="/"` intent sweep (Task 7).
- **Type consistency:** `DashboardSummary` defined once (Task 1), consumed by Tasks 3, 4, 7; `SUMMARY` fixture exported from the Task-1 test and imported by Tasks 3, 4, 7 tests (fallback to `fixtures.ts` noted); `timeAgo(thenMs, nowMs?)` signature matches its test; `openStagesFromParam` name identical in Tasks 2's test/impl and referenced nowhere else.
- **Stage-mapping decision made explicit** (raw folds in `extracted`; `rejected` off the rail) rather than left to the implementer.
