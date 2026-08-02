# 002 — Establish the guided workspace shell

- **Status**: DONE
- **Commit**: c07f67b3
- **Severity**: MEDIUM
- **Category**: Visual cohesion and hierarchy
- **Estimated scope**: 4 files, small

## Problem

The three destinations read like separately designed features. Coach uses a
plain page header (`web/src/features/coach/CoachPage.tsx:275-280`), Interview
places its title inside a selected-session card (`InterviewPage.tsx:204-215`),
and Scout compresses its entire masthead into one line
(`ScoutPage.tsx:109-110`). The inconsistent hierarchy makes navigation feel like
switching products.

## Target

Create `web/src/components/chat/GuidedWorkspaceHeader.tsx`, a semantic shared
header with these props:

```tsx
type GuidedWorkspaceHeaderProps = {
  tone: "coach" | "interview" | "scout";
  icon: ReactNode;
  eyebrow: string;
  title: ReactNode;
  description: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
};
```

The component must render:

- a restrained tone-aware icon well;
- 12px uppercase eyebrow, 28-36px responsive title, and a description capped at
  72 characters per line;
- meta/status below the description and actions aligned top-right on desktop;
- stacked actions and readable wrapping at 320px;
- one material surface: `rounded-2xl bg-card shadow-card ring-1
  ring-foreground/10`.

Add this exact shared visual treatment to `web/src/index.css`:

```css
.guided-workspace-hero { --workspace-tone: var(--primary); }
.guided-workspace-hero[data-tone="interview"] { --workspace-tone: var(--chart-3); }
.guided-workspace-hero[data-tone="scout"] { --workspace-tone: var(--chart-2); }
.guided-workspace-hero {
  background-color: var(--card);
  background-image: radial-gradient(
    80% 140% at 100% 0%,
    color-mix(in oklab, var(--workspace-tone), transparent 87%),
    transparent 62%
  );
}
```

The header does not animate. It is visited too frequently for an entrance
effect, and it contains functional actions.

## Repo conventions to follow

- `CHAT_PAGE_WIDTH` at `web/src/components/chat/layout.ts:16` is the canonical
  page cap.
- Use Geist and the existing theme variables; do not introduce a display font
  or hard-coded light-only colors.
- Use `shadow-card`, not new shadow literals (`web/src/index.css:66-67`).
- Decorative icons must be `aria-hidden="true"`; the eyebrow/title supply the
  accessible text.

## Steps

1. Create `GuidedWorkspaceHeader.tsx` with the exact props and responsive
   structure above.
2. Add the three tone mappings and radial wash to `web/src/index.css`.
3. Add `GuidedWorkspaceHeader.test.tsx` covering semantic heading output,
   actions/meta slots, tone attribute, and no duplicate accessible icon name.
4. Do not integrate the component into pages here; plans 003-005 own those
   diffs, which keeps each page reviewable.

## Boundaries

- Do NOT create three page-specific hero components.
- Do NOT add route entrance, parallax, mouse tracking, animated blobs, or a
  looping gradient.
- Do NOT change global page background or app navigation.

## Verification

- **Mechanical**: from `web/`, run the focused header test, `npm run lint`, and
  `npm run build`.
- **Feel check**: render all three tones in Storybook-equivalent test markup or
  a temporary local harness. Check light/dark themes at 320px, 768px, and
  1440px. Confirm actions wrap below copy without horizontal overflow.
- **Done when**: all three variants feel related, tone remains subtle, and the
  header is fully usable without motion.
