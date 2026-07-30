# 10. Enforce LLM quotas by immutable USD cost while retaining token analytics

## Status

Accepted; supersedes ADR-0009's token-budget enforcement after shadow rollout.

## Date

2026-07-30

## Decision

Shared-key access is governed by integer USD micro-cost, not weighted tokens.
Effective-dated exact provider/model rate cards price each recorded token and
native-search component. BYOK calls retain token and estimated cost telemetry
but have zero quota charge. Missing rates fail closed only for shared keys.

Every non-admin has an anchored tier period and durable credit balance.
Allowance is consumed before credits; bounded in-flight overage is recorded,
then later calls are rejected. Resets forgive period spend and refund its
consumed credits without moving the anchor. Tier changes close the old period
and begin a full new one immediately.

Administration uses preview-frozen bulk target sets, required reasons,
idempotency keys, immutable operation records, and per-user before/after ledger
snapshots. Administrators bypass user allowances but remain inside the UTC
calendar-month platform shared-key cap.

## Consequences

- Token fields and deprecated token-budget responses remain for one release as
  analytics/rollback compatibility; token-budget writes are rejected.
- Historical usage is `LEGACY_UNPRICED`; monetary history is never guessed.
- Rollout starts in `shadow`, requiring complete pricing coverage and telemetry
  comparison before `enforce` makes cost balances authoritative.
