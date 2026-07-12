# Multi-User Tenancy — Design

**Date:** 2026-07-12
**Status:** Approved
**Scope:** Expand resume-agent from a single-account tool to a small-group
multi-user system: invitation-code registration, admin/user roles, per-user
LLM budgets and resource quotas, user-specific tokens/links, per-user
databases and workspaces, and admin management surfaces (HTTP CLI + web UI),
modeled on vsda-deep-agent's user management and deep-agents-ui's admin panel.

---

## 1. Requirements (decided with the user)

| Decision | Choice |
| --- | --- |
| Limits | Per-user LLM token budgets **and** per-user job/run quotas (no seat cap) |
| LLM keys | Hybrid — shared server keys (budget-enforced) by default; a user-supplied provider key exempts that user's calls from the budget |
| Registration | Single-use, admin-minted invitation codes; no email verification step |
| Roles | Two: `admin` and `user` |
| Tokens | User-scoped session cookie + revocable personal access tokens (PATs) + short-lived signed link tokens for SSE/downloads; the static shared `api_token` is removed |
| Isolation | Full per-user workspace: SQLite DB, profile corpus, config YAMLs, output, runs, non-LLM secrets |
| Admin CLI | Thin HTTP client over an admin API (the same API powers the admin web UI) |
| Migration | Multi-user always (no mode flag); existing env credentials seed the first admin; the existing `data/` contents become that admin's workspace |

**Chosen architecture (Approach A):** request-scoped `UserContext` + per-user
engine registry + one shared `system.db` for auth/budgets. Rejected: row-level
tenancy (`user_id` columns — contradicts the per-user-database requirement and
poisons every query with a tenant filter) and app-instance-per-user (N
RunManagers in memory, fragmented cross-cutting concerns).

---

## 2. Data layout & tenancy core

```
data/
  system.db                 # NEW: users, invite_codes, api_tokens, usage_events, system_settings
  users/
    <user_id>/              # one full workspace per user (today's data/ shape, relocated)
      resume_agent.db       # jobs/applications/resumes/cover letters — schema UNCHANGED
      profile/              # facts.json, corpus, documents/, overrides.yaml
      config/               # search.yaml, connectors.yaml, review.yaml, prune.yaml
      secrets.env           # per-user non-LLM keys (GitHub, Adzuna) + optional own LLM keys
      output/  runs/  scraper_recipes/  workday_facets/  taxonomy/
```

- **`UserContext`** is the single new seam: the authenticated `User` row, the
  workspace paths, a per-user SQLModel engine, and an **effective `Settings`**
  (server settings overlaid with the user's `secrets.env`, config dir, and
  data paths). The auth dependency resolves it per request; routers and
  services stop reading `app.state.engine` / global `data/` / `config/` and
  draw everything from the context.
- **Engine registry:** `user_id → engine` map on `app.state`; engines created
  lazily via the existing `make_engine` (WAL, busy timeout carry over). No
  eviction for a small group; all engines closed on shutdown.
- **Run workers** already open their own DB sessions; run submission captures
  the submitting user's context (engine + paths) so workers never touch the
  request session. Run records gain a `user_id`; `/api/runs` lists only the
  caller's runs.
- **The job DB schema does not change.** Isolation is by file, not by column,
  so `tracking/queries.py` and every invariant (fact-lock, source priority,
  dedup, archive/prune) are untouched.
- The CLI constructs a local `UserContext` directly (no HTTP) — one seam, two
  adapters, same as the existing services architecture.

## 3. Auth, registration, and tokens

New tables in `system.db` (SQLModel, same `init_db` pattern):

- **`User`**: id, unique username, pbkdf2 password hash (reusing the
  `api/auth.py` helpers), role (`admin` | `user`), `disabled_at`, per-user
  limit overrides (`weekly_token_budget`, `max_active_jobs`,
  `max_concurrent_runs` — NULL = system default), timestamps.
- **`InviteCode`**: hashed single-use code, `created_by`, `expires_at`,
  `used_by` / `used_at`, `revoked_at`.
- **`ApiToken`**: user_id, name, sha256-hashed token, `created_at`,
  `last_used_at`, `revoked_at`.
- **`UsageEvent`**: append-only per-LLM-call usage log (user_id, ts, provider,
  model, token counts, weighted total, `own_key` flag).

Flows:

- **Register:** `POST /api/auth/register {username, password, inviteCode}` —
  validates and consumes the code atomically (one code, one account, even
  under concurrent registration), creates the user, provisions the workspace
  from the `.example` config templates.
- **Login/session:** stateless HMAC cookie retained, payload becomes
  `user_id:expiry`; the signature mixes in a fragment of the user's password
  hash so a password change (or admin reset) invalidates that user's sessions
  with no server-side session table.
- **Personal access tokens:** `rat_`-prefixed random secrets shown once,
  stored hashed; sent as `Authorization: Bearer`. Request auth resolves
  session cookie → PAT → 401.
- **Link tokens:** SSE (`EventSource`) and `<a>` downloads cannot set headers,
  so `POST /api/auth/link-token` mints a short-lived (~10 min) signed
  `user_id:purpose:expiry` token accepted only via `?token=`. This replaces
  the static shared `api_token`, which is removed.
- **Bootstrap:** whenever the `users` table is empty (fresh deploy or legacy
  adoption), `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` are **required** and seed
  the admin row; the server refuses to start without them. Registration is
  invite-only, so an instance with no admin would otherwise be permanently
  locked out.

## 4. Budgets, quotas, and enforcement points

**Token budgets (shared-key users only):**

- **Recording** at the one seam every LLM call passes through:
  `llm_runner.acall` appends a `UsageEvent` to `system.db` (own short
  session; WAL absorbs concurrent writers). Weighted totals mirror
  vsda-deep-agent (input + output weighted; cache reads discounted).
- **Enforcement is per phase, not per call:** when a run phase starts (pull
  scoring, discovery, tailor, cover letters, profile build), the service sums
  the user's rolling 7-day usage once; over budget → the run fails fast with
  typed `BUDGET_EXCEEDED`. Mid-run overshoot is tolerated by design — no
  `system.db` read inside the semaphore-guarded leaf.
- **Own-key exemption:** `resolve_api_key` knows the provider; when the
  effective key came from the user's `secrets.env` rather than server env,
  usage is still recorded (`own_key=true`, for visibility) but never counted
  against the budget.

**Resource quotas (all users, own key or not):**

- `max_active_jobs`: checked in the `save_or_upgrade` ingest path — at the
  cap, pulls stop **adding** rows and report `quota reached` in the run
  summary; upgrades to existing rows still apply.
- `max_concurrent_runs`: `RunManager.submit` counts the user's in-flight runs
  and rejects beyond the cap (default 2) with `QUOTA_EXCEEDED` (HTTP 429).
  This is also the fairness lever for the process-global `llm_concurrency`
  semaphore, which stays shared.
- Defaults live in `system_settings` (admin-editable); per-user override
  columns on `User` win when set.

## 5. Admin API, CLI, and web UI

**Admin API** (`/api/admin/users/*`; role check is a second dependency layered
over auth):

- Users: list (with usage summary + limits), set-role, set-limits,
  reset-password, disable/enable, delete. Delete refuses when the target is
  the last admin; deleting removes the workspace directory and requires an
  explicit confirmation flag.
- Invites: mint (`--expires` optional), list active/used, revoke.
- System: get/set default budgets and quotas; aggregate usage view.
- Existing import/export admin endpoints stay, now operating on the whole
  data root (`system.db` + all workspaces) so the Railway backup story is
  preserved.

**Admin CLI** — `resume-agent admin <cmd>`, a thin HTTP client exactly like
vsda's `manage_users.py`: `login`, `logout`, `whoami`, `list-users`,
`invite`, `set-role`, `set-limits`, `usage [user]`, `disable`, `enable`,
`delete`. `admin login` posts username/password to the login endpoint, then
mints a PAT (named `cli`) via the PAT endpoint and caches it at
`~/.resume-agent/credentials.json`; server selected by `RESUME_AGENT_URL`.

**Web UI (React SPA):**

- **Admin page** (admins only; hidden from nav otherwise): user table (role,
  last active, 7-day usage vs budget, job count), invite minting with
  copy-to-clipboard, per-user limit editors, system-defaults panel — the
  `AdminPanel` / `UserManagementSidebar` pattern from deep-agents-ui restyled
  to the existing SPA.
- **Account page** (every user): change password, mint/revoke PATs (secret
  shown once), own usage meter.
- **Register page**: username / password / invite code, linked from login.
- All API additions ride the existing contract pipeline (camelCase schemas →
  `contracts/openapi.json` → generated TS client); the drift gate covers them.

## 6. Migration, local CLI, and deployment

**Legacy adoption (one-time, automatic):** on startup, if the data root has
legacy content (`profile/` or the DB file) but no `system.db`:

1. Seed the admin from `AUTH_USERNAME` / `AUTH_PASSWORD_HASH`; refuse to start
   with a clear message if they are unset (an unowned workspace must not be
   orphaned silently).
2. Move the legacy children (`db`, `profile/`, `config/`, `output/`, …) into
   `users/<admin_id>/` using the rollback-safe child-swap pattern the Railway
   admin import already uses (the mounted volume root cannot be renamed).
   Idempotent: a half-completed move resumes or rolls back.

**Local CLI compatibility:** the domain CLI (`pull`, `tailor`, `render`, …)
keeps working locally by constructing a `UserContext` directly. Resolution:
legacy-shaped root → behave exactly as today; multi-user root → default to
the sole admin's workspace, `--user <username>` to select another.

**Railway:** unchanged topology — one service, one volume. `/app/data` holds
`system.db` + `users/`. Server-level LLM keys stay in service env vars;
per-user secrets live inside workspaces on the volume. Browser-only sources
keep their explicit cloud degradation, now per user.

## 7. Error handling

Typed codes through the existing `ApiException` envelope:

| Code | Meaning |
| --- | --- |
| `INVITE_INVALID` / `INVITE_USED` / `INVITE_EXPIRED` | Registration rejected |
| `BUDGET_EXCEEDED` | Rolling 7-day token budget exhausted (shared-key users) |
| `QUOTA_EXCEEDED` (429) | Concurrent-run cap hit (job cap reports in run summary instead) |
| `FORBIDDEN` (403) | Non-admin on `/api/admin/*` |
| `USER_DISABLED` | Auth succeeds but account is disabled |

Budget/quota failures inside runs surface as failed run records with the same
codes so the SPA renders them distinctly.

## 8. Testing (offline, as always)

- Auth: register/consume-invite atomicity (two concurrent registrations, one
  code), session invalidation on password change, PAT revocation, link-token
  expiry and purpose scoping.
- Tenancy isolation: two seeded users; every list endpoint returns only the
  owner's rows; one user's run/SSE stream is inaccessible to the other.
- Budgets/quotas: synthetic `UsageEvent` rows + faked agents; own-key
  exemption; job-cap ingest behavior; concurrent-run rejection.
- Migration: legacy-shaped temp root → boot → admin seeded, children swapped,
  re-boot is a no-op; unset env credentials → clean startup refusal.
- Admin CLI: exercised against the app via `TestClient`-backed transport.
- Contract drift gate regenerated (`openapi.json` + TS client).

## 9. Implementation decomposition

Three sequential implementation plans, each independently green:

1. **Tenancy core + migration** — `UserContext`, engine registry, workspace
   layout, effective-Settings overlay, legacy adoption, CLI workspace
   resolution.
2. **Auth + limits** — system.db tables, register/login/PAT/link-token flows,
   budget recording + enforcement, quotas, error codes.
3. **Admin surfaces** — admin API, HTTP-client CLI, SPA admin/account/register
   pages, contract regeneration.
