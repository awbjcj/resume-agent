# 004 — Give Mock Interviews a focused rehearsal layout

- **Status**: DONE
- **Commit**: c07f67b3
- **Severity**: HIGH
- **Category**: Performance, state indication, hierarchy
- **Estimated scope**: 7 files, medium

## Problem

The session rail precedes the task in DOM and layout
(`web/src/features/interview/InterviewPage.tsx:200-203`), so history competes with
the active rehearsal. The selected-session title is embedded in its own card
(`:204-246`) instead of matching the other guided workspaces. The shared progress
indicator uses `transition-all` at `web/src/components/ui/progress.tsx:48`, which
can animate unintended properties and relies on layout-driven width changes.

The completed debrief at `InterviewPage.tsx:310` appears instantly even though it
is a rare, high-emotion result.

## Target

- place `GuidedWorkspaceHeader` first with tone `interview`, title/company,
  stage/demeanor/difficulty chips, active/completed status, progress, and the end
  action;
- below it, make the live interview the dominant left column and Sessions a
  narrower right rail, matching Coach and Scout's conversation/context rhythm;
- keep the sessions rail sticky only at `lg` and above, with 16rem-20rem width;
- retain the empty hub CTA and session navigation semantics;
- animate the progress fill with a GPU `scaleX()` transform over 200ms using
  `var(--ease-in-out-strong)`; reduced motion snaps the transform;
- apply `.agent-artifact-enter` to the completed `DebriefCard` only.

Refactor the internal progress indicator so its value is applied directly to
the indicator element:

```tsx
<div
  data-slot="progress-indicator"
  className="h-full w-full origin-left bg-primary transition-transform duration-200 ease-in-out-strong motion-reduce:transition-none"
  style={{ transform: `scaleX(${Math.max(0, Math.min(100, value ?? 0)) / 100})` }}
/>
```

`Progress.Root` remains the accessible owner of `aria-valuenow`; `ProgressTrack`
remains a Base UI track. Remove the unused exported Base UI indicator wrapper
only after `rg "ProgressIndicator" web/src` confirms there are no external
consumers. This exact approach is required because Base UI 1.6 otherwise writes
percentage width inline on its Indicator.

## Repo conventions to follow

- Use the shared header and assistant identity from plans 001-002.
- The existing Sessions row style at `SessionsRail.tsx:37-38` is already crisp;
  preserve its color-only hover and selected inset rule.
- Preserve alert-dialog confirmation for ending/deleting interviews.
- Use the existing `DebriefCard` content model and accordion; do not summarize
  away question-level detail.

## Steps

1. Move the page header above the active/empty workspace grid and integrate the
   shared header for every session state.
2. Reorder the active workspace to `<main>` then `<SessionsRail>` in DOM. Use a
   two-column grid at `lg` with the rail on the right; stack main before history
   on smaller screens.
3. Pass `assistantName="Interviewer"` and the interview icon to `ChatThread`.
4. Update `SessionsRail` width/sticky classes and make its New Interview action
   remain visible without crowding 320px layouts.
5. Refactor `Progress` to direct `scaleX` as specified; add
   `web/src/components/ui/progress.test.tsx` covering 0, partial, 100, and clamped
   values plus accessible root values.
6. Apply `agent-artifact-enter` to `DebriefCard`. Do not animate its accordion
   as a whole beyond the primitive's existing disclosure behavior.
7. Extend Interview and SessionsRail tests for DOM order, header metadata,
   progress, debrief, CTA, and all destructive confirmations.

## Boundaries

- Do NOT animate question changes or keyboard answer submission.
- Do NOT auto-collapse the sessions rail or hide it behind a desktop drawer.
- Do NOT change interview selection precedence, query-string routing, streaming,
  conclusion, or scoring behavior.
- Do NOT introduce an animated score dial or confetti.

## Verification

- **Mechanical**: from `web/`, run `npm run test:run -- src/features/interview
  src/components/ui/progress.test.tsx src/components/chat`, then `npm run lint`
  and `npm run build`.
- **Feel check**: update progress from question 1 to 2 and confirm a smooth 200ms
  horizontal fill with no relayout. Test active, concluded-awaiting-debrief, and
  ended states at 320px, 768px, and 1440px. At 10% playback, debrief movement is
  6px only. Reduced motion removes both progress interpolation and debrief
  movement while preserving the debrief fade.
- **Done when**: the active rehearsal is unquestionably primary, history remains
  available, and progress never uses `transition-all` or animated width.
