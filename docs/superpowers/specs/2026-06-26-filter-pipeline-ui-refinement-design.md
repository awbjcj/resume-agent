# Filter and Pipeline UI Refinement — Design

**Date:** 2026-06-26  
**Status:** Approved design; awaiting written-spec review  
**Surface:** `web/src/components/FilterDesk.tsx`, `web/src/components/filters/FacetPopover.tsx`, `web/src/components/MinFitInput.tsx`, `web/src/features/pipeline/PipelineContainer.tsx`

---

## 1. Goal

Make filtering and stage navigation faster to scan and easier to control. Status must lead the hierarchy, minimum-fit and minimum-salary controls must read as deliberate threshold controls, only one facet panel may be open at once, and the pipeline must prioritize post-processed jobs without removing access to earlier stages.

## 2. Locked decisions

| Decision | Choice |
|---|---|
| Visual direction | Command desk (approved option A) |
| Filter hierarchy | Status first, followed by Min fit, Min salary, Sort, and Search |
| Facet overlays | Exactly one controlled popover open at a time |
| Pipeline stage order | Tailored, Rendered, Approved, Shortlisted, Raw, Rejected, then unknown statuses |
| Default visibility | Tailored and Rendered expanded; every other stage collapsed |
| User control | Every stage, including Tailored and Rendered, can be collapsed |
| Filtering semantics | Existing server filter and URL behavior remain unchanged |

## 3. Component design

### 3.1 Filter command desk

`FilterDesk` remains the orchestration boundary for draft scalar filters, applied filters, and facet selection. It will render Status as the leading filter control and move Source behind it. The primary controls use a compact, aligned responsive grid rather than unrelated form fields.

Minimum fit becomes a composed threshold control with a numeric value, `/ 100` context, and a slider for fast adjustment. The number input remains available for exact keyboard entry. Minimum salary gains a currency prefix, compact annual-USD context, thousands-aware display, and the existing validation behavior. Zero or blank continues to mean no threshold. Apply remains explicit so dragging or typing does not send repeated board requests.

At narrow widths controls stack without horizontal scrolling; at desktop widths their labels, values, and help text share a consistent baseline.

### 3.2 Exclusive facet popovers

`FilterDesk` owns `openFacet: FacetKey | null`. Each `FacetPopover` receives controlled `open` and `onOpenChange` props. Opening one facet sets that key and closes the previous one; closing clears the key.

The open panel contains:

- a visible title and selected-count badge;
- a searchable, scrollable option list with result counts;
- clear empty-search feedback;
- Clear and Done actions;
- checked state conveyed by both checkbox and text/icon treatment.

Selection remains live and preserves the current server-facet behavior. Closing the panel does not discard selections.

### 3.3 Pipeline status groups

`PipelineContainer` uses an explicit stage metadata list instead of the current order-only array. Each stage renders as a controlled shadcn `Collapsible` with a semantic heading, count badge, and chevron trigger. Tailored and Rendered initialize open; all other stages initialize closed. Users can independently collapse or expand every group.

Post-processed groups appear first in this order: Tailored, Rendered. Pre-processed groups then appear as Approved, Shortlisted, Raw, and Rejected. Unknown statuses are appended in stable alphabetical order so new backend values remain visible.

The pipeline Status filter becomes the first field in its filter form. Collapsed state affects presentation only; it does not alter selection, loaded rows, filters, or bulk-action scope.

## 4. State and data flow

- Scalar drafts stay local until Apply.
- Facet selections continue to update the existing `FilterState` and URL search parameters.
- `openFacet` is ephemeral UI state and is never serialized.
- Stage expansion is ephemeral UI state initialized from `{ tailored, rendered }`.
- Server pagination, grouping, counts, job selection, and bulk actions remain unchanged.
- When a previously unseen stage arrives, its group is added collapsed without resetting other groups.

## 5. Accessibility and responsive behavior

- Every input keeps an associated label and visible focus treatment.
- Invalid salary values use `aria-invalid` and visible error copy.
- Popover triggers expose expanded state through the primitive and remain keyboard operable.
- Collapsible triggers are buttons with `aria-expanded`; headings preserve document hierarchy.
- Counts and status names are text, not color-only signals.
- Layout is verified at 320, 768, 1024, and 1440 pixels.

## 6. Error and edge cases

- No status facets: omit the shared Status popover without leaving an empty grid slot.
- No facet search matches: show a meaningful empty state and retain Clear/Done actions.
- Invalid or negative salary: prevent Apply and explain the constraint inline.
- Empty stage: do not render a stage group unless it exists in returned rows.
- Active status filter: only returned stages render; default expansion rules still apply to Tailored and Rendered when present.
- Unknown status: append alphabetically and default it to collapsed.

## 7. Verification

Component tests will cover:

- Status appearing before all other facet controls;
- opening one facet closing the previously open facet;
- popover title, selected count, empty search, Clear, and Done behavior;
- fit and salary threshold entry, formatting, reset, validation, and Apply behavior;
- Tailored and Rendered ordering and default expansion;
- pre-processed and unknown stages starting collapsed;
- every stage being independently collapsible;
- existing filter URL serialization and bulk-selection behavior remaining intact.

The web test suite, TypeScript build, lint, and targeted responsive browser checks must pass before completion.

## 8. Non-goals

- No API or database changes.
- No new persisted user preferences for open stages.
- No redesign of job cards, bulk actions, or pagination.
- No change to the meaning of pipeline statuses.
