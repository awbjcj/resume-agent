# First-run guidance journey + Settings IA cleanup

**Date:** 2026-07-21
**Surface:** `web/` (React 19 + Vite + Tailwind v4 + shadcn/base-ui)
**Goal:** Guide a first-time user along the real job-hunting arc —
**build profile → configure sources → pull → shortlist/approve → tailor** —
using layout and IA, and de-mingle Settings into focused, grouped tabs.

## Decisions (locked with user)

1. **Plan first**, then build the highest-leverage slice.
2. Guidance is carried by **both** a dismissible first-run checklist *and* a
   persistent journey rail that recedes once the user is rolling.
3. **Profile-building is promoted to a top-level section** (`/profile`). It is
   step 1 of job hunting, not configuration. Settings becomes pure config.
4. **Settings tabs are grouped** under section headers (Discovery / Tailoring /
   Output / System).

## Core idea

There is exactly one funnel and it must be told once, consistently. Today the
funnel's true first step (build your profile) lives *inside* Settings, and the
dashboard opens at "Pull" — so a newcomer starts mid-story. We (a) surface the
whole arc as a shared **Journey** model, (b) relocate Profile so the arc's first
step is a real destination, and (c) strip Settings back to configuration.

### The Journey model (single source of truth)

`web/src/features/journey/use-journey.ts` — one hook, derived purely from the
existing `useSetupStatus()` + `useDashboardSummary()` queries (no backend work).

| # | Stage | `done` when | Primary CTA (when it's the next step) |
|---|-------|-------------|----------------------------------------|
| 1 | **Profile** | `profile.hasResume && profile.factsBuiltAt` | → `/profile` "Build your profile" |
| 2 | **Sources** | `search.configured && sources.enabledCount > 0` | → `/settings/sources` "Add sources" |
| 3 | **Pull** | any job exists (`Σ statusCounts − rejected > 0`) | Pull dialog "Pull jobs" |
| 4 | **Shortlist** | `shortlisted + approved + tailored + rendered > 0` | → `/shortlist` "Review shortlist" |
| 5 | **Tailor** | `tailored + rendered > 0` | → `/pipeline?stage=approved` "Tailor a resume" |

`currentStep` = first stage not `done`. `complete` = all `done`.
Exposes `{ stages, currentStep, completedCount, complete }`.

Both guidance components read this hook — the checklist and the rail can never
disagree because they compute nothing themselves.

## Components

### 1. `JourneyRail` (persistent, dashboard) — `features/journey/JourneyRail.tsx`
Replaces the current `StageRail` framing at the top of the dashboard as an
*actionable* rail (StageRail's raw counts move into a smaller "Funnel" strip
lower down, unchanged). Horizontal, 5 nodes, one highlighted "NOW" node with an
inline CTA. Recedes to a slim single-line summary once `complete` (still visible
for orientation, no CTA).

```
┌──────────────────────────────────────────────────────────────┐
│  ①Profile ──── ②Sources ──── ③Pull ──── ④Shortlist ── ⑤Tailor │
│   ✓done         ✓done        ◉ NOW        ○             ○      │
│                                                                │
│  ▶ Run your first pull to fill the funnel      [ Pull jobs ]   │
└──────────────────────────────────────────────────────────────┘
```
- Node states: `done` (check, muted), `current` (ring, primary, count if any),
  `upcoming` (hollow, 45% opacity — mirrors StageRail's existing dimming idiom).
- a11y: `<ol aria-label="Job-search journey">`; current node
  `aria-current="step"`; CTA is a real `<button>`/`<Link>`.

### 2. `GettingStartedChecklist` (first-run, dismissible) — `features/journey/GettingStartedChecklist.tsx`
Shown on the dashboard only while `!complete` and not dismissed
(`localStorage: resume-tailor-harness-getting-started-dismissed`, mirroring the existing
`resume-tailor-harness-setup-dismissed` idiom). Auto-hides once `complete`.
```
┌── Getting started ───────────────── 3 of 5 ── ✕ ──┐
│  ✓ Build your profile                             │
│  ✓ Add job sources                                │
│  ▸ Pull your first jobs              [ Pull ]      │  ← current row emphasised
│  ○ Shortlist & approve                            │
│  ○ Tailor a resume                                │
└───────────────────────────────────────────────────┘
```
Each row: check / current / upcoming; only the current row shows its CTA.

## IA change: promote Profile

- **New top-level nav item `Profile`** (icon `UserRound`) placed **first under
  Dashboard** in `AppLayout` NAV — it is step 1.
- **New route `/profile`** rendering a `ProfileWorkspace` with its own in-page
  sub-tabs so the overloaded page stops mingling:
  - **Documents** — `SourceManager` + GitHub config + Rebuild/build status +
    `BuildReportPanel`
  - **Skills** — `SkillGroupsPanel` + `ManualSkillsPanel`
  - **Coach** — entry card / recent sessions (links to existing `/coach`)
- Move `features/settings/pages/ProfileSettingsPage.tsx` content into
  `features/profile/…`; delete the Settings "Profile & documents" tab.
- **Redirects (no dead links):** `/settings/profile → /profile`.
  `/coach` unchanged (deep tool). Keep `/sources → /settings/sources`.

## IA change: group Settings

`SETTINGS_NAV` becomes grouped sections (render section labels in
`SettingsLayout`, same NavLink list, just bucketed):

```
SETTINGS
  Discovery   · Search · Sources
  Tailoring   · Review panel · Agent prompts · Style guide
  Output      · Rendering · Pruning
  System      · API keys
```
No settings page logic changes — only the nav grouping + removal of Profile.

## Build slices (each independently green: `npm run test:run`, `npm run build`)

- **Slice 1 — Journey guidance (highest leverage, zero backend).**
  `use-journey.ts` (+ unit test on the derivation), `JourneyRail`,
  `GettingStartedChecklist`, wire both into `DashboardPage`, keep `StageRail` as
  the lower "Funnel" strip. Ships the core "guide the first-timer" outcome alone.
- **Slice 2 — Promote Profile.** New `/profile` workspace with sub-tabs, nav
  item, move panels out of `ProfileSettingsPage`, add `/settings/profile`
  redirect, drop the Settings Profile tab. Update tests touching `SETTINGS_NAV`.
- **Slice 3 — Group Settings.** Section-bucketed `SettingsLayout` nav + test.

## Non-goals (this pass)
No backend/schema/contract changes. No visual redesign of Pipeline/Triage/
Analytics/Match-gap internals. No new colors — reuse existing tokens
(`primary`, `muted`, `--covered`/`--ready` for stage states). Setup wizard
(`/setup`) untouched; the checklist is the *post-setup* continuation of it.

## Verification per slice
`npm run test:run` (vitest, incl. vitest-axe on new components) + `npm run build`
(tsc). Drive the dashboard in the browser to confirm the rail highlights the
correct next step across states (fresh → profile built → jobs pulled → tailored).

## Status — 2026-07-21: all three slices implemented ✅

- **Slice 1** — `features/journey/{use-journey,JourneyRail,GettingStartedChecklist}`
  + tests (12); wired into `DashboardPage`; the ad-hoc "Add sources" Empty card
  was removed (rail now owns onboarding *and* drained-funnel guidance — see the
  derivation note that "empty funnel" and "journey complete" are mutually
  exclusive). Dashboard tests updated.
- **Slice 2** — `features/profile/ProfileWorkspace` (coach hero + Documents/Skills
  tabs) replaces `settings/pages/ProfileSettingsPage` (deleted); `/profile` route
  + top-level nav item; `/settings/profile`→`/profile` redirect; settings index →
  `/settings/search`; `DeskHealth` + e2e paths repointed. Refinement vs plan:
  coach is a persistent hero, not a third tab.
- **Slice 3** — `SETTINGS_GROUPS` (Discovery/Tailoring/Output/System) render as
  labelled sections; `SETTINGS_NAV` kept as a flat projection for compatibility.

**Verification run:** 349 vitest tests pass (120 files); new components axe-clean;
`npm run build` (tsc) clean; changed files ESLint-clean. e2e specs updated for the
new routes/tabs but not executed here (need the live backend). No live browser
drive performed (app is auth-gated); MSW integration tests exercise the real
component tree in lieu.
