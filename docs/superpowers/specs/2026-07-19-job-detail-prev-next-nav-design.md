# Job Detail Prev/Next Navigation — Design

**Date:** 2026-07-19
**Status:** Approved for planning

## Problem

When a user opens a job in the `JobModal` detail view from a board (Shortlist,
Triage, Pipeline), the only way to look at the next job is: close the modal,
find the next row, click it. For someone triaging or reviewing a shortlist in
sequence this is a lot of friction. Users expect lightbox-style prev/next
controls to step through the list without leaving the detail view.

## Goal

Add left/right navigation to the job detail modal so the user can switch to the
previous/next job in the list they opened it from, via buttons and arrow keys,
across all three board views.

## Non-goals

- No cross-board navigation (a modal opened from Shortlist never steps into
  Pipeline rows).
- No new server endpoints or query params beyond the existing `?job=` id.
- No reordering, filtering, or sorting changes — navigation follows the row
  order already loaded in the container.
- No wrap-around; no Pipeline cross-stage auto-expansion (see Decisions).

## Decisions (from brainstorming)

1. **Scope:** all three containers — `ShortlistContainer`, `TriageContainer`,
   `PipelineContainer`.
2. **Boundaries:** buttons **disable** at the first (Prev) and last (Next) item.
   No wrap-around.
3. **Pagination (Shortlist & Triage):** these are single flat paginated lists.
   When Next is pressed on the last *loaded* row and `hasNextPage` is true, the
   hook calls `fetchNextPage()` and, once the new rows arrive, advances to the
   first newly-loaded row. Until they land, Next shows a loading state and is
   inert.
4. **Pagination (Pipeline):** each stage section paginates independently and
   fetches lazily on expand. We do **not** auto-expand collapsed stages.
   Navigation is scoped to the flat concatenation of rows currently loaded
   across expanded stages (`loadedRows` order); Next simply disables at that
   edge. (Pipeline passes no `pagination` handle to the hook.)
5. **Keyboard:** ← / → arrow keys trigger Prev/Next while the modal is open,
   **ignored** when focus is inside an `input`, `textarea`, `select`, or
   `contenteditable` element (so editing the Application tab, cover letter
   fields, etc. is unaffected).

## Architecture

### New hook: `useJobNavigation`

`web/src/features/board/use-job-navigation.ts`

```ts
type Pagination = {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => void;
};

type JobNavigation = {
  hasPrev: boolean;
  hasNext: boolean;
  isLoadingNext: boolean;   // true while auto-fetching the next page
  goPrev: () => void;
  goNext: () => void;
};

function useJobNavigation(
  orderedIds: number[],
  currentId: number | null,
  onNavigate: (id: number) => void,
  pagination?: Pagination,
): JobNavigation;
```

Responsibilities:

- Compute `index = orderedIds.indexOf(currentId)`.
- `hasPrev = index > 0`.
- `hasNext = index >= 0 && (index < orderedIds.length - 1 ||
  (pagination?.hasNextPage ?? false))`.
- `goPrev()` → `onNavigate(orderedIds[index - 1])` when `hasPrev`.
- `goNext()`:
  - If there is a loaded next row → `onNavigate(orderedIds[index + 1])`.
  - Else if `pagination?.hasNextPage` → set a "pending advance" flag and call
    `fetchNextPage()`. An effect watches `orderedIds`; when its length grows
    while the flag is set, it navigates to the row at the old `index + 1` and
    clears the flag.
- `isLoadingNext` mirrors the pending-advance flag (and/or
  `pagination.isFetchingNextPage` while pending).
- If `currentId` isn't in `orderedIds` (e.g. deep-linked to a `?job=` id not on
  the current page), `hasPrev`/`hasNext` are both false — navigation is inert
  rather than jumping. Buttons simply disable.

The hook owns **no** row data and knows nothing about which board it serves —
each container feeds it the right `orderedIds` and (optionally) its `pagination`
handle. This keeps it independently testable with plain arrays.

### `JobModal` prop additions

`JobModal` stays presentational about navigation — it receives:

```ts
onPrev?: () => void;
onNext?: () => void;
hasPrev?: boolean;
hasNext?: boolean;
isLoadingNext?: boolean;
```

All optional so existing callers/tests that don't navigate keep compiling. When
`onPrev`/`onNext` are provided, it renders two lightbox-style icon buttons and
binds the arrow-key handler.

- **Buttons:** ghost icon buttons using `ChevronLeft` / `ChevronRight` from
  `lucide-react`, absolutely positioned centered on the modal's left and right
  edges (`absolute top-1/2 -translate-y-1/2`, inset a little from each edge),
  above the content (`z`-ordered), each wrapped in a `Tooltip` reading
  "Previous job (←)" / "Next job (→)". Disabled when `!hasPrev` / `!hasNext`;
  Next shows a spinner via `isLoadingNext`.
- **Keyboard:** a `useEffect` adds a `keydown` listener on `document` while the
  modal is mounted. On `ArrowLeft`/`ArrowRight`, if
  `event.target` is not an editable element (input/textarea/select/
  contenteditable) and the corresponding `hasPrev`/`hasNext` is true, it calls
  `onPrev`/`onNext` and `preventDefault()`. Cleaned up on unmount.

The modal already keys its inner content on `jobId` implicitly via
`useJobDetail(jobId)`; changing `jobId` refetches the detail and swaps content
in place — no remount needed, the nav buttons persist.

### Container wiring (identical shape in all three)

Each container already computes an ordered id list and has `openJob(id)`:

- **Shortlist:** `loadedIds = rows.map(r => r.jobId)`; pass
  `{ hasNextPage, isFetchingNextPage, fetchNextPage }` from `useBoardQuery`.
- **Triage:** same as Shortlist (also flat `useBoardQuery`).
- **Pipeline:** `loadedRows` already exists (flattened across expanded stages);
  `loadedIds = loadedRows.map(r => r.jobId)`. Pass **no** pagination (edge
  disables Next). `openJob` already exists as the row-open handler.

Then:

```tsx
const nav = useJobNavigation(loadedIds, openId ? Number(openId) : null, openJob, pagination);
...
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

## Data flow

```
container rows ──> orderedIds ──┐
                                 ├─> useJobNavigation ──> {hasPrev,hasNext,goPrev,goNext,isLoadingNext}
?job= url param ──> currentId ──┘                              │
                                                    goPrev/goNext call openJob(id)
                                                               │
                                        openJob sets ?job=  ──> JobModal re-reads id
                                                               │
                                        useJobDetail(newId) refetches ──> content swaps
```

The URL param remains the single source of truth for "which job is open," so
navigation is just repeatedly rewriting `?job=` — back/forward and deep links
keep working. (Existing `openJob` uses `{ replace: true }`; we keep that so
stepping through jobs doesn't flood browser history.)

## Error handling / edge cases

- **Current id not in loaded list:** both buttons disabled (inert), no crash.
- **Empty list:** modal wouldn't be open; N/A.
- **Fetch-next fails:** `fetchNextPage` rejection surfaces via the existing
  query error path; the pending-advance flag clears on settle so Next re-enables
  based on the (unchanged) `hasNextPage`. No forced navigation on failure.
- **Rapid arrow presses while a page is loading:** the pending-advance flag is
  idempotent — extra Next presses while `isLoadingNext` are ignored.
- **Editable focus:** arrow keys pass through to inputs untouched.

## Testing

- **`use-job-navigation.test.tsx`** (new, plain hook test with
  `renderHook`): boundaries (first/last disable), prev/next stepping,
  current-id-not-in-list → inert, pagination auto-advance (mock a `pagination`
  whose `fetchNextPage` grows `orderedIds` on a rerender → hook advances to the
  first new row), rapid-press idempotency.
- **`JobModal.test.tsx`** (extend existing): buttons render only when handlers
  passed; disabled states reflect `hasPrev`/`hasNext`; clicking calls handlers;
  ArrowLeft/ArrowRight fire handlers; arrow key inside an `<input>` does **not**
  fire.
- Container tests already exist (`use-board-query`, selection). No new
  container-level tests required beyond ensuring they compile with the added
  props; a light render assertion in one container test that the nav buttons
  appear is optional.

## Files touched

| File | Change |
| --- | --- |
| `web/src/features/board/use-job-navigation.ts` | **New** — the hook |
| `web/src/features/board/use-job-navigation.test.tsx` | **New** — hook tests |
| `web/src/components/JobModal.tsx` | Add optional nav props, buttons, arrow-key effect |
| `web/src/components/JobModal.test.tsx` | Extend for nav buttons + keys |
| `web/src/features/shortlist/ShortlistContainer.tsx` | Wire hook + props |
| `web/src/features/triage/TriageContainer.tsx` | Wire hook + props |
| `web/src/features/pipeline/PipelineContainer.tsx` | Wire hook + props (no pagination) |
