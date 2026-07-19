# Job Detail Prev/Next Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user step to the previous/next job from inside the `JobModal` detail view — via edge buttons and arrow keys — across the Shortlist, Triage, and Pipeline boards.

**Architecture:** A board-agnostic `useJobNavigation` hook takes an ordered list of loaded job ids, the currently-open id, an `onNavigate(id)` callback, and an optional pagination handle. It computes `hasPrev`/`hasNext`, exposes `goPrev`/`goNext`, and — for flat paginated boards — auto-fetches the next page when Next is pressed at the loaded edge, then advances once the new rows land. `JobModal` gains optional nav props and renders lightbox-style chevron buttons plus an arrow-key listener. Each container feeds the hook its own row order; the `?job=` URL param stays the single source of truth for which job is open.

**Tech Stack:** React 19, TypeScript, TanStack Query (`useInfiniteQuery`), react-router-dom (`useSearchParams`), Base UI dialog, Vitest + Testing Library, lucide-react icons.

## Global Constraints

- **Package manager / test runner:** run web tests from the `web/` directory with `npx vitest run <path>` (script `test:run` → `vitest run`). The Python suite is irrelevant to this frontend work.
- **Wire format is camelCase; Python stays snake_case** — this plan touches only the web layer, so all fields are camelCase (`jobId`, `hasNextPage`, `fetchNextPage`).
- **No new dependencies.** Use existing components: `Button` (`@/components/ui/button`), `Spinner` (`@/components/ui/spinner`), and icons from `lucide-react`.
- **Accessibility over tooltips:** nav buttons use `aria-label` + native `title` (no `Tooltip` component) so they need no `TooltipProvider` in unit tests and still expose an accessible name.
- **Boundaries disable, never wrap.** Prev disabled at the first item; Next disabled at the last (or, for flat boards, until an auto-fetched page lands).
- **All `JobModal` nav props are optional** so existing callers and tests compile unchanged.
- **Branch:** work happens on `feat/job-detail-prev-next-nav` (already checked out; the design doc is already committed there).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `web/src/features/board/use-job-navigation.ts` | **New.** The navigation hook — the only place that holds prev/next + auto-fetch logic. Board-agnostic. |
| `web/src/features/board/use-job-navigation.test.tsx` | **New.** Unit tests for the hook (plain arrays, no network). |
| `web/src/components/JobModal.tsx` | **Modify.** Add optional nav props, edge chevron buttons, arrow-key listener. |
| `web/src/components/JobModal.test.tsx` | **Modify.** Extend for button render/disabled/click + arrow-key behavior. |
| `web/src/features/shortlist/ShortlistContainer.tsx` | **Modify.** Wire hook (with pagination) + pass props to `JobModal`. |
| `web/src/features/triage/TriageContainer.tsx` | **Modify.** Wire hook (with pagination) + pass props to `JobModal`. |
| `web/src/features/pipeline/PipelineContainer.tsx` | **Modify.** Wire hook (no pagination) + pass props to `JobModal`. |

---

### Task 1: `useJobNavigation` hook

**Files:**
- Create: `web/src/features/board/use-job-navigation.ts`
- Test: `web/src/features/board/use-job-navigation.test.tsx`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `type JobNavPagination = { hasNextPage: boolean; isFetchingNextPage: boolean; fetchNextPage: () => void }`
  - `type JobNavigation = { hasPrev: boolean; hasNext: boolean; isLoadingNext: boolean; goPrev: () => void; goNext: () => void }`
  - `function useJobNavigation(orderedIds: number[], currentId: number | null, onNavigate: (id: number) => void, pagination?: JobNavPagination): JobNavigation`

- [ ] **Step 1: Write the failing test**

Create `web/src/features/board/use-job-navigation.test.tsx`:

```tsx
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useJobNavigation, type JobNavPagination } from "./use-job-navigation";

describe("useJobNavigation", () => {
  it("disables prev at the first item and next at the last (no pagination)", () => {
    const nav = vi.fn();
    const first = renderHook(() => useJobNavigation([1, 2, 3], 1, nav));
    expect(first.result.current.hasPrev).toBe(false);
    expect(first.result.current.hasNext).toBe(true);

    const last = renderHook(() => useJobNavigation([1, 2, 3], 3, nav));
    expect(last.result.current.hasPrev).toBe(true);
    expect(last.result.current.hasNext).toBe(false);
  });

  it("steps to the neighbouring id on goPrev/goNext", () => {
    const nav = vi.fn();
    const { result } = renderHook(() => useJobNavigation([10, 20, 30], 20, nav));
    act(() => result.current.goPrev());
    expect(nav).toHaveBeenCalledWith(10);
    act(() => result.current.goNext());
    expect(nav).toHaveBeenCalledWith(30);
  });

  it("is inert when the current id is not in the list", () => {
    const nav = vi.fn();
    const { result } = renderHook(() => useJobNavigation([1, 2], 99, nav));
    expect(result.current.hasPrev).toBe(false);
    expect(result.current.hasNext).toBe(false);
    act(() => result.current.goNext());
    act(() => result.current.goPrev());
    expect(nav).not.toHaveBeenCalled();
  });

  it("keeps hasNext true at the loaded edge while more pages exist", () => {
    const nav = vi.fn();
    const pagination: JobNavPagination = {
      hasNextPage: true,
      isFetchingNextPage: false,
      fetchNextPage: vi.fn(),
    };
    const { result } = renderHook(() =>
      useJobNavigation([1, 2], 2, nav, pagination),
    );
    expect(result.current.hasNext).toBe(true);
  });

  it("auto-fetches the next page, then advances once rows land", () => {
    const nav = vi.fn();
    const fetchNextPage = vi.fn();
    const pagination: JobNavPagination = {
      hasNextPage: true,
      isFetchingNextPage: false,
      fetchNextPage,
    };
    const { result, rerender } = renderHook(
      ({ ids }: { ids: number[] }) => useJobNavigation(ids, 2, nav, pagination),
      { initialProps: { ids: [1, 2] } },
    );

    // At the loaded edge: goNext requests the next page instead of navigating.
    act(() => result.current.goNext());
    expect(fetchNextPage).toHaveBeenCalledTimes(1);
    expect(nav).not.toHaveBeenCalled();
    expect(result.current.isLoadingNext).toBe(true);

    // Rapid re-press while pending must not fire a second fetch.
    act(() => result.current.goNext());
    expect(fetchNextPage).toHaveBeenCalledTimes(1);

    // New page lands -> hook advances to the first new row and clears loading.
    rerender({ ids: [1, 2, 3] });
    expect(nav).toHaveBeenCalledWith(3);
    expect(result.current.isLoadingNext).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/board/use-job-navigation.test.tsx`
Expected: FAIL — `Failed to resolve import "./use-job-navigation"` (module does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `web/src/features/board/use-job-navigation.ts`:

```ts
import { useCallback, useEffect, useState } from "react";

export type JobNavPagination = {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
};

export type JobNavigation = {
  hasPrev: boolean;
  hasNext: boolean;
  isLoadingNext: boolean;
  goPrev: () => void;
  goNext: () => void;
};

/**
 * Board-agnostic prev/next navigation over a list of loaded job ids.
 *
 * The `?job=` URL param (mirrored into `currentId`) is the source of truth for
 * which job is open, so navigating just calls `onNavigate(id)` — the caller
 * rewrites the param and the modal re-reads it.
 *
 * For flat paginated boards, pass `pagination`: when Next is pressed on the
 * last loaded row and more pages exist, the hook fetches the next page and
 * advances to its first row once the rows arrive. Boards without pagination
 * (e.g. Pipeline's per-stage sections) omit it, so Next simply disables at the
 * loaded edge.
 */
export function useJobNavigation(
  orderedIds: number[],
  currentId: number | null,
  onNavigate: (id: number) => void,
  pagination?: JobNavPagination,
): JobNavigation {
  const index = currentId == null ? -1 : orderedIds.indexOf(currentId);
  const [pendingAdvance, setPendingAdvance] = useState(false);

  const hasPrev = index > 0;
  const hasNext =
    index >= 0 &&
    (index < orderedIds.length - 1 || (pagination?.hasNextPage ?? false));

  // A page we requested has landed: advance to the row after the current one.
  useEffect(() => {
    if (!pendingAdvance) return;
    if (index >= 0 && index < orderedIds.length - 1) {
      setPendingAdvance(false);
      onNavigate(orderedIds[index + 1]);
    }
  }, [pendingAdvance, orderedIds, index, onNavigate]);

  const goPrev = useCallback(() => {
    if (index > 0) onNavigate(orderedIds[index - 1]);
  }, [index, orderedIds, onNavigate]);

  const goNext = useCallback(() => {
    if (index < 0) return;
    if (index < orderedIds.length - 1) {
      onNavigate(orderedIds[index + 1]);
    } else if (pagination?.hasNextPage && !pendingAdvance) {
      setPendingAdvance(true);
      pagination.fetchNextPage();
    }
  }, [index, orderedIds, onNavigate, pagination, pendingAdvance]);

  return { hasPrev, hasNext, isLoadingNext: pendingAdvance, goPrev, goNext };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/board/use-job-navigation.test.tsx`
Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/board/use-job-navigation.ts web/src/features/board/use-job-navigation.test.tsx
git commit -m "feat(web): board-agnostic useJobNavigation hook"
```

---

### Task 2: `JobModal` nav buttons + arrow keys

**Files:**
- Modify: `web/src/components/JobModal.tsx`
- Test: `web/src/components/JobModal.test.tsx`

**Interfaces:**
- Consumes: nothing from Task 1 directly (props are plain values/callbacks).
- Produces: `JobModal` accepts additional optional props
  `onPrev?: () => void; onNext?: () => void; hasPrev?: boolean; hasNext?: boolean; isLoadingNext?: boolean`.

- [ ] **Step 1: Write the failing test**

Append these tests inside the `describe("JobModal", ...)` block in `web/src/components/JobModal.test.tsx` (the `jobPayload`, `wrap`, `server`, and imports from the existing file are reused). Add `fireEvent` to the existing `@testing-library/react` import and `vi` to the existing `vitest` import:

```tsx
  it("renders prev/next buttons and reflects disabled boundaries", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    wrap(
      <JobModal
        jobId={42}
        onClose={() => {}}
        onPrev={() => {}}
        onNext={() => {}}
        hasPrev={false}
        hasNext={true}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /staff engineer/i })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /previous job/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next job/i })).toBeEnabled();
  });

  it("calls onPrev/onNext when the buttons are clicked", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    const onPrev = vi.fn();
    const onNext = vi.fn();
    wrap(
      <JobModal
        jobId={42}
        onClose={() => {}}
        onPrev={onPrev}
        onNext={onNext}
        hasPrev
        hasNext
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /next job/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /next job/i }));
    fireEvent.click(screen.getByRole("button", { name: /previous job/i }));
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it("navigates with arrow keys but ignores them while editing a field", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    const onNext = vi.fn();
    wrap(
      <JobModal jobId={42} onClose={() => {}} onPrev={() => {}} onNext={onNext} hasPrev hasNext />,
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /next job/i })).toBeInTheDocument(),
    );

    fireEvent.keyDown(document.body, { key: "ArrowRight" });
    expect(onNext).toHaveBeenCalledTimes(1);

    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "ArrowRight" });
    expect(onNext).toHaveBeenCalledTimes(1); // still 1 — ignored inside an input
    input.remove();
  });

  it("omits the nav buttons when no handlers are provided", async () => {
    server.use(http.get("/api/jobs/42", () => HttpResponse.json(jobPayload())));
    wrap(<JobModal jobId={42} onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: /staff engineer/i })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /next job/i })).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/JobModal.test.tsx`
Expected: FAIL — the new tests error because `JobModal` does not accept `onPrev`/`onNext` and renders no nav buttons (e.g. `Unable to find role="button" and name /next job/i`).

- [ ] **Step 3: Write minimal implementation**

In `web/src/components/JobModal.tsx`:

**3a.** Extend the imports. Change the `useState` import line and the lucide-react import at the top:

```tsx
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Mail } from "lucide-react";
```

Add the Spinner import alongside the other UI imports (near the `Button` import):

```tsx
import { Spinner } from "@/components/ui/spinner";
```

**3b.** Widen the component signature and destructure the new optional props:

```tsx
export function JobModal({
  jobId,
  onClose,
  onPrev,
  onNext,
  hasPrev = false,
  hasNext = false,
  isLoadingNext = false,
}: {
  jobId: number;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
  isLoadingNext?: boolean;
}) {
  const { data: job, isLoading } = useJobDetail(jobId);
  const closedLoopJob = job as (NonNullable<typeof job> & ClosedLoopJob) | undefined;
  const coverLetters = closedLoopJob?.coverLetters ?? [];
  const [emailDraftOpen, setEmailDraftOpen] = useState(false);
  const navEnabled = Boolean(onPrev || onNext);

  // Arrow keys step through the list, but never while the user is typing in a
  // field (Application tab, cover-letter editors, etc.).
  useEffect(() => {
    if (!navEnabled) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT")
      ) {
        return;
      }
      if (event.key === "ArrowLeft" && hasPrev) {
        event.preventDefault();
        onPrev?.();
      } else if (event.key === "ArrowRight" && hasNext && !isLoadingNext) {
        event.preventDefault();
        onNext?.();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [navEnabled, hasPrev, hasNext, isLoadingNext, onPrev, onNext]);

  return (
```

**3c.** Render the two edge buttons. Place them as the first children inside `<DialogContent …>`, immediately before the `{isLoading || !job ? (` expression:

```tsx
      <DialogContent className="block max-h-[92vh] w-full max-w-[calc(100%-1.5rem)] gap-0 overflow-hidden rounded-2xl p-0 shadow-[0_40px_120px_-24px_rgba(8,32,40,0.55)] sm:max-w-6xl">
        {navEnabled && (
          <>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              aria-label="Previous job"
              title="Previous job (←)"
              className="absolute top-1/2 left-3 z-20 size-9 -translate-y-1/2 rounded-full shadow-md"
              disabled={!hasPrev}
              onClick={onPrev}
            >
              <ChevronLeft className="size-5" aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="icon"
              aria-label="Next job"
              title="Next job (→)"
              className="absolute top-1/2 right-3 z-20 size-9 -translate-y-1/2 rounded-full shadow-md"
              disabled={!hasNext || isLoadingNext}
              onClick={onNext}
            >
              {isLoadingNext ? (
                <Spinner className="size-5" />
              ) : (
                <ChevronRight className="size-5" aria-hidden="true" />
              )}
            </Button>
          </>
        )}
        {isLoading || !job ? (
```

The rest of the component (the `isLoading` ternary, header, panes, tabs, and `EmailDraftDialog`) is unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/components/JobModal.test.tsx`
Expected: PASS — the original 3 tests plus the 4 new tests all green.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/JobModal.tsx web/src/components/JobModal.test.tsx
git commit -m "feat(web): prev/next buttons and arrow-key nav in JobModal"
```

---

### Task 3: Wire navigation into the three board containers

**Files:**
- Modify: `web/src/features/shortlist/ShortlistContainer.tsx`
- Modify: `web/src/features/triage/TriageContainer.tsx`
- Modify: `web/src/features/pipeline/PipelineContainer.tsx`

**Interfaces:**
- Consumes: `useJobNavigation` (Task 1) and the `JobModal` nav props (Task 2).
- Produces: user-visible navigation on all three boards. No new exports.

There is no isolated unit test for this wiring (container behaviour is covered by existing `use-board-query`/selection tests and the Task 1/2 unit tests); correctness is verified by a passing typecheck + full web suite and a manual smoke check. Do all three edits, then verify together.

- [ ] **Step 1: Wire ShortlistContainer**

In `web/src/features/shortlist/ShortlistContainer.tsx`:

Add the import near the other `@/features/board` imports:

```tsx
import { useJobNavigation } from "@/features/board/use-job-navigation";
```

`rows`, `fetchNextPage`, `hasNextPage`, `isFetchingNextPage`, `openId`, `loadedIds`, and `openJob` already exist. Immediately after `openJob`/`closeJob` are defined (just before `return (`), add:

```tsx
  const nav = useJobNavigation(
    loadedIds,
    openId ? Number(openId) : null,
    openJob,
    { hasNextPage, isFetchingNextPage, fetchNextPage },
  );
```

Replace the closing modal render:

```tsx
      {openId && <JobModal jobId={Number(openId)} onClose={closeJob} />}
```

with:

```tsx
      {openId && (
        <JobModal
          jobId={Number(openId)}
          onClose={closeJob}
          onPrev={nav.goPrev}
          onNext={nav.goNext}
          hasPrev={nav.hasPrev}
          hasNext={nav.hasNext}
          isLoadingNext={nav.isLoadingNext}
        />
      )}
```

- [ ] **Step 2: Wire TriageContainer**

In `web/src/features/triage/TriageContainer.tsx`:

Add the import near the other `@/features/board` imports:

```tsx
import { useJobNavigation } from "@/features/board/use-job-navigation";
```

`rows`, `fetchNextPage`, `hasNextPage`, `isFetchingNextPage`, `openId`, `loadedIds`, and `openJob` already exist. Immediately before `return (`, add:

```tsx
  const nav = useJobNavigation(
    loadedIds,
    openId ? Number(openId) : null,
    openJob,
    { hasNextPage, isFetchingNextPage, fetchNextPage },
  );
```

Replace the closing modal render:

```tsx
      {openId && <JobModal jobId={Number(openId)} onClose={closeJob} />}
```

with:

```tsx
      {openId && (
        <JobModal
          jobId={Number(openId)}
          onClose={closeJob}
          onPrev={nav.goPrev}
          onNext={nav.goNext}
          hasPrev={nav.hasPrev}
          hasNext={nav.hasNext}
          isLoadingNext={nav.isLoadingNext}
        />
      )}
```

- [ ] **Step 3: Wire PipelineContainer (no pagination)**

In `web/src/features/pipeline/PipelineContainer.tsx`:

Add the import near the other `@/features/board` imports:

```tsx
import { useJobNavigation } from "@/features/board/use-job-navigation";
```

`loadedRows`, `loadedIds` (line ~102: `const loadedIds = useMemo(() => loadedRows.map((row) => row.jobId), [loadedRows]);`), `openId`, and `openJob` already exist. Pipeline paginates per-stage and does **not** auto-advance across stages, so pass **no** pagination handle — Next disables at the loaded edge. Immediately after `openJob`/`closeJob` are defined (just before `return (`), add:

```tsx
  const nav = useJobNavigation(loadedIds, openId ? Number(openId) : null, openJob);
```

Replace the closing modal render:

```tsx
      {openId && <JobModal jobId={Number(openId)} onClose={closeJob} />}
```

with:

```tsx
      {openId && (
        <JobModal
          jobId={Number(openId)}
          onClose={closeJob}
          onPrev={nav.goPrev}
          onNext={nav.goNext}
          hasPrev={nav.hasPrev}
          hasNext={nav.hasNext}
          isLoadingNext={nav.isLoadingNext}
        />
      )}
```

- [ ] **Step 4: Typecheck and run the full web suite**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: no TypeScript errors; all tests pass (existing suite + Task 1/2 additions).

- [ ] **Step 5: Manual smoke check**

Run: `cd web && npm run dev`, open a board (Shortlist), click a job to open the modal, then:
- Click the right chevron / press → → the modal content swaps to the next job; the URL `?job=` id changes.
- Click the left chevron / press ← → swaps back.
- Open the last loaded row → Next shows a spinner briefly then advances (Shortlist/Triage) or is disabled (Pipeline).
- Focus a field in the Application tab and press ←/→ → the field handles the key; the modal does not navigate.

Expected: all behave as described. (This step is observation only — no code change.)

- [ ] **Step 6: Commit**

```bash
git add web/src/features/shortlist/ShortlistContainer.tsx web/src/features/triage/TriageContainer.tsx web/src/features/pipeline/PipelineContainer.tsx
git commit -m "feat(web): wire prev/next job navigation into all board containers"
```

---

## Self-Review

**1. Spec coverage:**
- Scope = all three containers → Task 3 wires Shortlist, Triage, Pipeline. ✓
- Disable-at-edge boundaries → Task 1 `hasPrev`/`hasNext` + Task 2 `disabled` props; tested. ✓
- Auto-fetch next page on flat boards → Task 1 pending-advance logic + tested; Task 3 passes pagination for Shortlist/Triage only. ✓
- Pipeline disables at loaded edge → Task 3 Step 3 passes no pagination. ✓
- Arrow keys, ignored in editable fields → Task 2 keydown effect + test. ✓
- `?job=` stays source of truth → hook calls `onNavigate` = each container's existing `openJob` (which sets the param). ✓
- Hook is board-agnostic / independently testable → Task 1 tests use plain arrays. ✓
- `JobModal` nav props all optional → Task 2 defaults + "omits buttons when no handlers" test. ✓
- Current id not in list → inert → Task 1 test. ✓
- Rapid-press idempotency → Task 1 test asserts single `fetchNextPage`. ✓

**2. Placeholder scan:** No TBD/TODO/"add error handling" — every code step shows complete code. ✓

**3. Type consistency:** `useJobNavigation(orderedIds, currentId, onNavigate, pagination?)` and its return shape (`hasPrev`, `hasNext`, `isLoadingNext`, `goPrev`, `goNext`) are used identically in Tasks 2–3. `JobNavPagination` fields (`hasNextPage`, `isFetchingNextPage`, `fetchNextPage`) match `useBoardQuery`'s returned names verbatim. `JobModal` prop names (`onPrev`, `onNext`, `hasPrev`, `hasNext`, `isLoadingNext`) are consistent between Task 2's signature and Task 3's call sites. ✓
