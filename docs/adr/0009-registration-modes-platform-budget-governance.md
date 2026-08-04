# 9. Registration mode is a separate decision from shared-key eligibility, backed by a global budget

## Status

Accepted

## Date

2026-07-30

## Context

The threat model's release-blocker for open registration (RA-SEC-003 /
TM-003) was economic, not cryptographic: per-user weekly token budgets already
existed (`tenancy/limits.py::enforce_budget`), but nothing capped total spend
across accounts. If registration required only a verified email, an attacker
could create arbitrarily many accounts and multiply the platform's shared LLM
key budget by the number of accounts they were willing to verify — the
per-account limit did not become a platform limit just because email
verification is required to get one.

The report's recommended fix was explicit: "make registration and shared-key
eligibility separate decisions." Folding budget policy into the registration
flow itself (e.g. a fixed shared quota split across however many users sign
up) would recreate the same problem under load — the quota still degrades
with account count, just proportionally instead of unboundedly.

## Decision

`Settings.registration_mode` (`closed` / `invite` / `open`) controls whether
an account can be created at all. `User.shared_key_access` is a separate
column that controls whether *that* account may use the platform's shared LLM
keys versus needing its own — invited users default to `True` (matching prior
behavior), self-registered open-signup users default to
`Settings.open_signup_shared_keys` (`False`), and an admin can flip it per
user afterward through the existing admin-users API.

Two more governance layers sit above the existing per-user weekly budget:

- `api/attempts.py::consume_global_signup` — a platform-wide rolling-24h cap
  (`Settings.global_daily_signup_limit`) on verification emails started,
  independent of per-email/per-IP attempt budgets, so registration itself
  can't be used to spam the mailer or system database.
- `tenancy/limits.py::enforce_agent_budget` — called from `AgentRunner` before
  every LLM invocation, checking (in order) `shared_key_access` eligibility,
  the existing per-user weekly budget, and a new platform-wide rolling-7-day
  sum (`Settings.global_weekly_token_budget`) over every shared-key
  `UsageEvent`. A user's own provider key is exempt from both budgets, same as
  before.
- `Settings.open_signup_weekly_token_budget` / `_max_active_jobs` /
  `_max_concurrent_runs` seed a tighter per-account ceiling onto open
  self-registered users specifically, so an operator can run
  `registration_mode=open` more conservatively than an invited/admin-created
  account without a second code path.

An account-verification cost (payment, risk review, abuse challenge) was
considered and rejected for this iteration — it is a product decision the
report frames as optional ("...require payment, or manual promotion..."), and
the global circuit breaker already bounds worst-case shared-key spend to a
single, operator-visible number regardless of signup volume.

## Consequences

- Creating an account is no longer sufficient to gain platform-funded LLM
  access; `shared_key_access` must also be true, and even then the global
  budget can reject a call that a per-user budget alone would have allowed.
- `enforce_agent_budget` is a required call in `AgentRunner.run`/`arun` (not
  optional per call site) — any new agent-invocation path that bypasses it
  would let that path evade both the per-account and platform-wide governance
  established here.
- Operators choosing `registration_mode=open` should keep
  `open_signup_shared_keys=false` (the default) and promote trusted users
  individually; the threat model still frames unrestricted open signup with
  shared keys enabled as a distinct, higher-risk configuration.
- This does not address the threat model's remaining Sybil-adjacent gap: there
  is still no cross-account identity/device signal, so an attacker who only
  wants BYOK-tier resources (compute/storage, not LLM spend) is not
  meaningfully slowed by this decision alone.

## Amendment (2026-07-30) — SUPERSEDED by Amendment 2, below

> **This paragraph no longer describes the runtime.** It is kept for the
> rationale trail only. `global_monthly_cost` and `global_weekly_usage` do
> **not** filter out `User.role == "admin"` — neither query joins `User` — and
> `enforce_agent_budget` does not exempt admins from the platform-wide cap.
> Admins are exempt from the **per-user allowance** and remain bound by the
> **platform-wide monthly cap**; see Amendment 2 and ADR-0010 §26. Pinned by
> `tests/tenancy/test_cost_quotas.py::test_admin_shared_usage_is_bounded_by_global_cost_quota`
> and `::test_admin_usage_counts_toward_global_cost_quota_for_other_users`.

The platform-wide cap (`global_weekly_token_budget` in shadow mode,
`global_monthly_cost_quota_micros` in enforce mode) originally applied to
every shared-key call regardless of role, on the reasoning above that "even
then the global budget can reject a call that a per-user budget alone would
have allowed." In practice this meant the sole trusted operator account could
be locked out of their own platform by the cumulative spend of every other
user, with no override — `enforce_agent_budget` (`tenancy/limits.py`) now
exempts `role == "admin"` from the platform-wide cap in both modes, and
`global_monthly_cost` / `global_weekly_usage` exclude admin-attributed
`UsageEvent` rows from the sum entirely, so admin usage neither triggers nor
counts toward exhausting the cap for other accounts. The cap's Sybil-defense
purpose — bounding spend an attacker can generate via *newly registered*
accounts — is unaffected, since `shared_key_access` and the per-account
budgets still gate every non-admin account exactly as before; only the
single, operator-controlled admin role is now unbounded.

## Amendment 2 (2026-07-30)

The product policy now grants shared-key access by default to administrators,
free members, and subscribers, including open-registration accounts. Platform
provider credentials come from Railway environment variables and are selected
before a user's workspace credential. When the applicable account allowance or
global platform cap is exhausted, calls fall back to the user's credential for
that provider; without one, the existing quota error remains fail-closed.

This supersedes the earlier `open_signup_shared_keys=false` recommendation and
the admin-cap exemption. A one-time migration enables existing accounts, while
later explicit admin revocations remain durable. Admin shared usage now counts
toward, and is bounded by, the global platform cap. The signup-rate limit,
per-member allowance, and global cap remain the economic-abuse controls for
open registration.
