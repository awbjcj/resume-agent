# 12. Application status is a progression plus a terminal set, not a high-water mark

Date: 2026-08-29

## Status

Accepted

## Context

`tracking/CLAUDE.md` documents status as a forward-only high-water mark, by
analogy with `JobStatus` and `tracking/stages.py::advance`. That analogy does
not hold for `ApplicationStatus`.

`ApplicationStatus` has no defined ordering, and `rejected` is not behind
`interview` — it is an exit from the funnel. A flat high-water mark blocks
`interview -> rejected`, the single most common transition in a job hunt, and
`offer -> rejected`, which is what a rescinded offer is.

The codebase already encodes the distinction: `gmail/propose.py:13` defines
`_TERMINAL = {rejected, closed}` and handles it separately from progression.

## Decision

Status has two halves, in `tracking/status_rules.py`:

- **Progression** `ready < submitted < interview < offer` advances forward
  only. A late-logged earlier stage never demotes.
- **Terminal** `{rejected, closed}` is reachable from any progression state,
  including `offer`. A terminal state is not undone by logging an earlier
  stage; it is replaceable only by the other terminal state.

`ApplicationEvent` creation applies `KIND_IMPLIES_STATUS` through this rule.
Manual edits and Gmail proposals continue to write status directly.

## Consequences

- Two clarifications this rule deliberately makes:
  - `EventResult.rejected` on a round does **not** move status. A weak round
    is not a dead application; only a `rejected` *event* is terminal.
  - Deleting an event never moves status back. Progression is forward-only,
    so a mis-logged event is undone with the manual override, not by deletion.
- `tracking/CLAUDE.md`'s "status is a high-water mark" wording applies to
  `JobStatus` only and is amended for `ApplicationStatus`.
- Do not add ordering comparisons against `ApplicationStatus` members; the
  ordering lives in `PROGRESSION` and nowhere else.
