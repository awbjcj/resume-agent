# 003 — Turn Profile Coach into an evidence workshop

- **Status**: DONE
- **Commit**: c07f67b3
- **Severity**: MEDIUM
- **Category**: Hierarchy, structured artifacts, rare-state delight
- **Estimated scope**: 6 files, medium

## Problem

Coach has strong functionality but reads as a generic chat plus a flat list. The
agenda at `web/src/features/coach/AgendaRail.tsx:20-29` gives every topic the same
weight, while draft notes at `DraftNoteCard.tsx:30-66` visually resemble ordinary
cards even though they are the core human-approval artifact. The first-run state
at `CoachPage.tsx:309-335` explains the feature only in one paragraph.

## Target

Make the page feel like a focused evidence workshop:

- integrate `GuidedWorkspaceHeader` with tone `coach`, title `Profile coach`,
  agent identity `Profile coach`, a live/complete status chip, and current counts
  (`topics`, `pending drafts`, `saved notes`) in the meta slot;
- preserve the main-thread/right-rail layout but make both surfaces share the
  same top edge and corner/elevation vocabulary;
- turn the agenda into a vertical evidence path: open topic is visually current,
  saved note is complete, skipped/done is quiet; keep every label in text, not
  color alone;
- treat each pending `DraftNoteCard` as a structured approval artifact with a
  strong title, evidence inset, and clear primary/secondary/destructive actions;
- apply `.agent-artifact-enter` only to a newly rendered pending draft note;
- add a three-step first-run explainer: `Review gaps → Answer one question →
  Approve grounded notes`, followed by one primary CTA.

Use this exact agenda marker treatment:

```tsx
<li className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-3 pb-5 last:pb-0">
  <span className="relative z-10 flex size-6 items-center justify-center rounded-full border bg-card" />
  <div className="min-w-0">...</div>
</li>
```

Add a one-pixel vertical connector as an absolutely positioned pseudo/child
behind the markers. Current item: primary border and a soft primary fill.
Completed item: check icon and muted foreground. Never animate the connector or
loop/pulse the current marker.

For the mobile agenda and past-session panels, keep Base UI content mounted and
use:

```tsx
className="translate-y-0 overflow-hidden opacity-100 transition-[opacity,transform] duration-[160ms] ease-out-strong data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity"
```

## Repo conventions to follow

- Use `GuidedWorkspaceHeader` from plan 002 and assistant identity props from
  plan 001.
- Preserve `CHAT_SURFACE_HEIGHT` and `CHAT_PAGE_WIDTH`.
- Preserve the end-session build checkbox and all archive/delete semantics.
- `DraftNoteCard` is the approval boundary: save/edit/discard must remain visible
  and keyboard accessible.

## Steps

1. Replace the existing header in `CoachPage.tsx:275-305` with the shared header
   and populate status/count meta without adding new requests.
2. Pass `assistantName="Profile coach"` and the Coach icon into `ChatThread`.
3. Redesign the no-session state into the three-step explainer; reuse existing
   `Empty` and `Button` primitives.
4. Refactor `AgendaRail` into the vertical evidence path. Add `aria-current="step"`
   to the open topic and keep the status badge text.
5. Refine `DraftNoteCard` hierarchy and apply `agent-artifact-enter` to pending
   notes. Do not animate edit/preview toggles; they are frequent and contain form
   controls.
6. Apply the exact disclosure transition to the mobile agenda and past sessions.
7. Extend `CoachPage.test.tsx` and add focused `AgendaRail.test.tsx` assertions
   for current-step semantics, status counts, first-run explanation, and
   preserved actions.

## Boundaries

- Do NOT animate individual chat messages or topic markers.
- Do NOT change coach endpoints, session precedence, stream recovery, or note
  mutation behavior.
- Do NOT hide evidence quotes behind a disclosure; approval needs the evidence
  visible at decision time.

## Verification

- **Mechanical**: from `web/`, run `npm run test:run -- src/features/coach
  src/components/chat`, then `npm run lint` and `npm run build`.
- **Feel check**: test empty, starting, active, streaming, pending-note, ended,
  and archived states. At 10% playback, a draft note should travel only 6px and
  settle within 180ms. Rapidly toggle a past session and confirm reversal is
  clean. With reduced motion, confirm the draft only fades.
- **Done when**: the page makes the path from question to approved evidence
  obvious before the user reads body copy.
