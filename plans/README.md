# Guided agent workspace UI plans

These plans redesign Profile Coach, Mock Interviews, and Discovery Scout as one
coherent family of agent workspaces. They preserve the existing event contract
and use the AG-UI repository as an interaction reference: streamed text,
reasoning, tool activity, structured artifacts, and human approval should have
distinct visual roles.

| Plan | Title | Severity | Status | Depends on |
| --- | --- | --- | --- | --- |
| 001 | Make agent activity legible | HIGH | DONE | None |
| 002 | Establish the guided workspace shell | MEDIUM | DONE | None |
| 003 | Turn Profile Coach into an evidence workshop | MEDIUM | DONE | 001, 002 |
| 004 | Give Mock Interviews a focused rehearsal layout | HIGH | DONE | 001, 002 |
| 005 | Make Discovery Scout an approval-first research workspace | MEDIUM | DONE | 001, 002 |

## Recommended execution order

1. Execute 001 and 002 first. They create the shared chat/activity and page-shell
   vocabulary used by every page.
2. Execute 003, 004, and 005 after both foundations land. The three page plans
   touch separate feature folders and may then proceed independently.
3. Run the complete frontend suite after the last page plan because 001 and 004
   deliberately improve shared chat and progress primitives.

## Scope guard

- Do not add `@ag-ui/*`, Motion, Framer Motion, or another dependency. The app's
  current SSE event model already provides the required interaction states.
- Do not animate route changes, every message, session-list navigation, or ledger
  rows. Those are frequent functional interactions.
- Keep the existing teal-led brand, Geist typography, light/dark themes, and
  shared card/easing tokens.
