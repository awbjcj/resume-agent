# 005 — Make Discovery Scout an approval-first research workspace

- **Status**: TODO
- **Commit**: c07f67b3
- **Severity**: MEDIUM
- **Category**: Human-in-the-loop clarity, interruptibility, hierarchy
- **Estimated scope**: 7 files, medium

## Problem

Scout has the strongest AG-UI-style human approval flow, but its hierarchy hides
that strength. The masthead is compressed at `web/src/features/scout/ScoutPage.tsx:109-110`,
session history is detached below the workspace (`:119-120`), and both proposal
groups and proposal details snap open via conditional/hidden rendering:

```tsx
// ProposalRail.tsx:32
{open ? <ul>{children}</ul> : null}

// ProposalCard.tsx:77
<div id={detailId} hidden={!expanded} className="space-y-2 ... [&[hidden]]:hidden">
```

The chevrons at `ProposalRail.tsx:26` and `ProposalCard.tsx:58` use bare
`transition-transform`, so their timing is browser/default-token dependent.

## Target

- integrate `GuidedWorkspaceHeader` with tone `scout`, agent identity
  `Discovery Scout`, active/ended status, proposal counts, and session actions;
- label the right rail as an approval surface: `Review proposals`, pending count,
  and explicit “Nothing is added until you approve it” copy;
- preserve the bounded ledger height and dense two-line rows;
- use Base UI Collapsible panels for proposal groups and proposal details so
  open/close can reverse smoothly;
- keep errors and dismissal editors force-open and visible;
- replace `window.confirm` in session history with the existing `AlertDialog`
  pattern used by Coach and Interview;
- keep session history compact and move its archived filter into the history
  section header, so related controls are grouped.

Use this exact panel motion for group and row details:

```tsx
className="translate-y-0 overflow-hidden opacity-100 transition-[opacity,transform] duration-[160ms] ease-out-strong data-starting-style:-translate-y-1 data-starting-style:opacity-0 data-ending-style:-translate-y-1 data-ending-style:opacity-0 motion-reduce:translate-y-0 motion-reduce:transition-opacity"
```

Use this exact chevron motion:

```tsx
className={cn(
  "size-3.5 shrink-0 text-muted-foreground transition-transform duration-[160ms] ease-out-strong motion-reduce:transition-none",
  expanded && "rotate-90",
)}
```

Do not stagger or animate ledger row arrival. A productive session can add many
rows, and the user is scanning functional data.

## Repo conventions to follow

- Keep the explicit `CHAT_SURFACE_HEIGHT` rationale at
  `ProposalRail.tsx:37-44` and `:77-80` intact.
- Keep `canAddProposal` as the single readiness predicate for row and batch
  actions.
- Preserve `aria-expanded`, `aria-controls`, focus return after Escape, and
  visible error behavior in `ProposalCard`.
- Reuse `AlertDialog` from `@/components/ui/alert-dialog`; no native confirm.

## Steps

1. Replace Scout's compact header with the shared header and populate status,
   pending/added counts, and existing actions without new API calls.
2. Pass `assistantName="Discovery Scout"` and the Scout icon to `ChatThread`.
3. Refine the proposal ledger header as the human-approval surface while keeping
   Add All, summary live region, and internal scrolling.
4. Convert `ProposalRail.Section` to controlled Base UI `Collapsible`; always
   render its panel and apply the exact transition.
5. Convert `ProposalCard` detail to a controlled Base UI `CollapsibleContent`;
   retain force-open rules for editing/error and the existing accessible trigger
   name. Apply the exact chevron timing.
6. Refactor `SessionHistory` into readable JSX, group Show Archived with its
   heading, and replace `window.confirm` with a controlled `AlertDialog`.
7. Extend Scout, ProposalRail, and ProposalCard tests for reversible disclosure,
   forced-open errors/editor, archive filter placement, delete confirmation,
   and preserved batch readiness.

## Boundaries

- Do NOT animate proposal row insertion, Add All iterations, or chat messages.
- Do NOT turn the ledger back into full-height cards or remove its internal
  scroll boundary.
- Do NOT change proposal approval/dismissal rules, optimistic `added` tracking,
  session precedence, or stream recovery.
- Do NOT add automatic approvals; human confirmation remains explicit.

## Verification

- **Mechanical**: from `web/`, run `npm run test:run -- src/features/scout
  src/components/chat`, then `npm run lint` and `npm run build`.
- **Feel check**: test empty, active, streaming, ended-with-pending, batch partial
  failure, dismissal editor, and archived history states. Rapidly toggle group
  and row disclosures; they must reverse cleanly. At 10% playback, only opacity
  and 4px movement occur. Reduced motion keeps the fade and drops translation.
  Verify 20+ proposals remain easy to scan with no page-length growth.
- **Done when**: conversation, agent activity, and human approval read as three
  coordinated layers, and every destructive session action uses an accessible
  in-app confirmation.
