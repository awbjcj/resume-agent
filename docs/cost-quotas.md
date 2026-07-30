# Cost quota operations

LLM quota enforcement uses integer USD micro-units (`$1 = 1_000_000`) so
accounting is deterministic. Token counts remain first-class analytics for both
platform keys and bring-your-own-key calls, but they stop controlling access
when `COST_QUOTA_ENFORCEMENT=enforce`.

## Rollout

1. Run in `shadow` mode. Every `AgentRunner` and direct transcription call
   records provider/model-specific token lines and an effective-dated rate-card
   snapshot while the legacy weighted-token guard remains active.
2. Resolve every rate coverage warning, compare computed costs to provider/Agno
   telemetry, then set `COST_QUOTA_ENFORCEMENT=enforce`. Shared calls with an
   unknown rate fail closed; BYOK calls remain available and are marked unpriced.

## Defaults and resets

- `FREE` starts with `$1` every seven days from assignment.
- `SUBSCRIBER` starts with `$20` monthly from assignment. Month-end assignments
  clamp without drifting (January 31 → February 28 → March 31).
- Shared platform keys have a `$500` UTC calendar-month cap by default.
- Credits survive resets and tier changes. Recurring allowance is spent first.
- Resetting a current period forgives its spend, refunds credits consumed in the
  period, and preserves its anchor.

Administrators use `/admin/quotas` for tier, account, bulk operation, rate-card,
and audit views. Bulk operations require a frozen preview, reason, and
idempotency key; all-member scope includes disabled non-admin accounts.
