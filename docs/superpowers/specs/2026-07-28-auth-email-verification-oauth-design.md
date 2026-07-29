# Email-verified accounts, Google sign-in, and auth hardening

**Date:** 2026-07-28
**Status:** Design approved, ready for planning

## Problem

Accounts today have no email address. `User` (`tenancy/system_db.py:30`) carries a
`username` slug, a password hash, a role, and per-user limits — nothing that can
reach the person behind the account. Three consequences:

- **No recovery.** A forgotten password is unrecoverable without admin
  intervention directly against `system.db`.
- **No proof of identity.** An invite code is the only thing standing between a
  stranger and a workspace backed by a shared LLM key.
- **No security signal.** A password change, a takeover, or a reset request is
  invisible to the account holder.

Sign-up is also more friction than it needs to be — invite code, invented
username, invented password — while the deployment already holds a Google OAuth
client (`Settings.google_oauth_client_id`) used solely for Gmail sync.

This design adds email as the account identity, verifies it, adds Google
sign-in that pre-wires Gmail sync, replaces the emailed-credential recovery
pattern with codes, and hardens the password and rate-limiting surface. The
login and registration screens are rebuilt around the resulting six-screen flow.

## Scope

**In:** platform mail transport; email-verified registration; emailed reset
codes; Google sign-in and account linking; password strength and breach
checking; durable rate limiting and progressive lockout; security
notifications; sign-out-everywhere; the auth UI rebuild.

**Out:** TOTP two-factor (deserves its own spec once this lands); new-device
detection; magic-link passwordless sign-in; OAuth providers other than Google;
`gmail.send` (permanently out of scope, see "Two mail actors" below).

## Decisions taken

| Decision         | Choice                                                                 | Rejected alternative                                                                  |
| ---------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Mail transport   | SMTP via `Settings`, stdlib `smtplib`                                  | Transactional HTTP API — vendor lock for no benefit at this scale                     |
| Login identifier | Email replaces username                                                | Accepting either — two unique identifiers to rate-limit and disambiguate              |
| Signup gate      | Invite code **and** verified email                                     | Verification replacing invites — opens the shared LLM key to the internet             |
| Recovery         | Emailed single-use code                                                | Emailed temporary password — a live credential that persists in the inbox             |
| Google scopes    | `openid email profile` only; Gmail stays a separate, pre-warmed opt-in | One combined consent — asks a stranger for inbox access before they trust the product |
| Login page       | Split canvas (branded panel + form column)                             | Centered card — visibly resizes across a six-screen flow                              |

## Two mail actors

`CLAUDE.md` states `gmail.send` is permanently out of scope. That rule is about
**the user's mailbox**: the product reads a user's Gmail and writes drafts, and
must never send as them. It is not a prohibition on the platform having an
outbound address.

This design introduces a second, unrelated actor: the platform itself, sending
from its own SMTP account to its own users. It never touches a user's Gmail
token, never uses the Google OAuth client, and never sends on a user's behalf.
The two must not be conflated — `gmail.send` remains out of scope.

---

## 1. Mail seam

New package `src/resume_agent/mail/`:

```
mail/mailer.py     Mailer protocol, SmtpMailer, NullMailer
mail/messages.py   plain-text message bodies
```

### Contract

```python
class Mailer(Protocol):
    def send(self, *, to: str, subject: str, body: str) -> None: ...
    def notify(self, *, to: str, subject: str, body: str) -> None: ...
```

The two methods differ **only** in failure handling, and the distinction is
load-bearing:

- `send()` **raises `MailDeliveryError`**. Used where the mail _is_ the flow —
  the verification code, the reset code. If delivery fails, the calling endpoint
  must fail loudly rather than strand the user awaiting an email that will never
  arrive.
- `notify()` **catches every exception and logs**. Used for security notices. A
  dead SMTP host must never make a password change fail _after_ the hash has
  already been rotated.

`SmtpMailer` uses stdlib `smtplib.SMTP` with STARTTLS (or `SMTP_SSL` when
`smtp_port == 465`), a 10-second timeout, and `email.message.EmailMessage`
bodies. Plain text only — no HTML, no tracking pixels, no attachments.

### Settings

New fields on `Settings` (`config.py`), alongside the existing Gmail block:

```python
smtp_host: str = ""
smtp_port: int = Field(default=587, ge=1, le=65535)
smtp_username: str = ""
smtp_password: str = ""
smtp_from: str = ""            # falls back to smtp_username when blank
smtp_starttls: bool = True
app_base_url: str = ""         # absolute base for links in mail bodies
```

`app_base_url` is not used for the codes themselves — those are typed into a
screen the user already has open. It exists for the security notices, which must
give a recipient who did _not_ initiate the action somewhere to go: the
"password changed" and "Google linked" messages link to `{app_base_url}/login`
and `{app_base_url}/forgot-password`. When blank the notices omit the links
rather than emitting a relative URL.

These are platform-level and read from process environment only. They are
deliberately **not** part of the per-workspace `secrets.env` overlay — a tenant
must not be able to redirect platform verification mail.

### Null transport and its hazard

`app.state.mailer` is built once in `create_app`. When `smtp_host` is blank the
mailer is `NullMailer`, which logs each message at WARNING prefixed
`MAIL NOT CONFIGURED —` including the code body. This is what keeps local
development and the offline test suite working with no network and no
credentials.

The hazard is a production deployment with SMTP misconfigured silently logging
live verification codes instead of failing. Two guards:

- `GET /api/health` returns `mailConfigured: bool` (this changes the endpoint's
  return type from `dict[str, str]` to a `HealthOut` schema — a contract change).
- The admin UI shows a persistent warning banner when session auth is enabled
  and the mailer is null.

`NullMailer.send` still succeeds — it does not raise — because a developer
running locally must be able to complete registration.

---

## 2. Data model

`system.db` has no migration runner; `init_system_db` is a bare `create_all`.
This design adds `tenancy/migrate_system.py`, copying the idempotent
`PRAGMA table_info` → `ALTER TABLE … ADD COLUMN` idiom proven in
`tracking/migrate.py:10`. It runs from the app lifespan immediately after
`init_system_db`, before `ensure_bootstrapped`.

### `users` — new columns

| Column               | Type                                           | Notes                                                                                            |
| -------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `email`              | `String(320)`, unique, indexed, **nullable**   | The login identifier. Nullable solely so pre-existing rows survive migration. Stored casefolded. |
| `email_verified_at`  | `DateTime(tz)` nullable                        | Timestamp, not a flag — you will want to know when.                                              |
| `google_sub`         | `String(64)`, unique, nullable                 | Google's stable subject id.                                                                      |
| `session_epoch`      | `Integer`, not null, default 0                 | Mixed into the session HMAC.                                                                     |
| `failed_login_count` | `Integer`, not null, default 0                 | Consecutive failures; drives lockout tiers. Reset to 0 on any success.                           |
| `locked_until`       | `DateTime(tz)` nullable                        | Progressive lockout.                                                                             |
| `password_hash`      | unchanged `NOT NULL`; `""` means "no password" | Google-only accounts.                                                                            |

`password_hash` stays `NOT NULL` with an empty-string sentinel rather than
becoming nullable: SQLite cannot relax a `NOT NULL` constraint via
`ALTER TABLE`, so nullability would force a full table rebuild (create, copy,
drop, rename) on a live volume for no behavioral gain. The sentinel also keeps
a freshly-created schema byte-identical to a migrated one, which a rebuild
would not. `verify_password(pw, "")` already fails closed — it raises inside
`split(":")` and returns `False` — so the sentinel is safe by construction. A
`has_password(user) -> bool` helper is the single reader of that meaning.

`username` is **kept** and demoted to a display name. It is not dropped: SQLite
cannot drop a unique constraint without a full table rebuild, the column is
harmless, and legacy rows need it for the migration login fallback (§7).

`email` is unique but nullable — SQLite treats `NULL` as distinct in a unique
index, so any number of legacy rows may coexist with no email.

### New tables

```python
class PendingRegistration(SystemBase):     # __tablename__ = "pending_registrations"
    id: str                                # 12-hex
    email: str                             # unique — one pending signup per address
    password_hash: str
    display_name: str | None
    invite_code_hash: str                  # the invite is NOT consumed yet
    code_hash: str                         # sha256 of the 6-digit code
    created_at: datetime
    expires_at: datetime
    attempts: int = 0

class PasswordResetCode(SystemBase):       # __tablename__ = "password_reset_codes"
    id: str
    user_id: str                           # indexed
    code_hash: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None
    attempts: int = 0

class LoginAttempt(SystemBase):            # __tablename__ = "login_attempts"
    id: int                                # autoincrement
    scope: str                             # 'email' | 'ip' | 'email_ip'
    identifier: str                        # indexed with scope
    occurred_at: datetime                  # indexed
```

`login_attempts` records **failures only** — successes are not written. One
failure writes three rows, one per scope, so the three budgets in §5 are
independent counts over the same event.

Two purpose-built code tables rather than one polymorphic table with a `purpose`
discriminator: a pending registration carries fields a reset code has no use for
(`invite_code_hash`, `password_hash`, `display_name`) and has no `user_id`,
because no user exists yet. Merging them would mean four nullable columns and a
constraint the type system cannot express.

### Code format

Six digits, generated with `secrets.randbelow(1_000_000)` zero-padded. Stored
only as `sha256(code + session_secret)` — never in plaintext, never in a
response body, never in a log except under `NullMailer`. TTL 15 minutes.
Five failed attempts destroys the row.

Six digits is 10⁶, brute-forceable in seconds against an unthrottled endpoint.
The five-attempt cap is the primary defense; the endpoint rate limits (§5) are
the backstop. Both are required.

---

## 3. Registration

### The ordering rule

`POST /api/auth/register` **does not create a `User` and does not consume the
invite.** It writes a `PendingRegistration` and sends a code. `POST
/api/auth/verify-email` creates the user.

This is the central correctness property of the flow. Creating the account at
`register` time means a typo'd address burns a one-time invite code and leaves
an orphan workspace directory on the Railway volume, recoverable only by an
admin. Invites are the budget control on a shared LLM key, so burning one on an
unreachable address is a real loss. Nothing is allocated until the address is
proven reachable.

### `POST /api/auth/register` → `202`

Request: `{ email, password, inviteCode, displayName? }`

1. Rate gate on email and IP (§5).
2. Validate the password against the policy (§4). **This is the only point the
   plaintext password exists** — it is hashed into `PendingRegistration`
   immediately, so `verify-email` never re-validates.
3. Validate the invite: exists, not revoked, not expired, not used. Invalid →
   `400 INVITE_INVALID` / `INVITE_EXPIRED` / `INVITE_USED`. Invite validity is
   _not_ enumeration-sensitive; the code is a secret the caller already holds.
4. If a `User` with this email already exists → **return the same `202`** and
   `notify()` the real account holder that someone attempted signup with their
   address, pointing at password reset. (§5, enumeration.)
5. Upsert the `PendingRegistration` for this email, replacing any prior row —
   re-requesting is how a user gets a fresh code. A third party holding a valid
   invite can therefore overwrite someone else's pending signup, invalidating
   their code. Accepted: it costs the attacker a scarce invite, grants nothing
   (verification still requires reading that mailbox), and the victim recovers
   by requesting a new code.
6. `send()` the code. On `MailDeliveryError` → `503 MAIL_UNAVAILABLE`, and the
   pending row is rolled back.

Response body is a fixed `{ "status": "sent" }` in every branch — no field
distinguishes case 4 from case 5.

### `POST /api/auth/verify-email` → `200`

Request: `{ email, code }`

1. Rate gate.
2. Load the `PendingRegistration`; missing/expired → `400 CODE_INVALID`.
3. Compare `sha256`; mismatch → increment `attempts`, delete the row at 5,
   → `400 CODE_INVALID`.
4. Open `BEGIN IMMEDIATE` (the pattern already at `routers/auth.py:142`) and,
   in one transaction: re-check the invite is still unused, create the `User`
   with `email_verified_at = now`, mark the invite used, delete the pending row.
   The re-check matters — two pending registrations may hold the same invite
   code, and only the first to verify may have it.
5. `provision_workspace(...)`.
6. Issue the session cookie; return `MeResponse`.

### `POST /api/auth/resend-code`

Request `{ email }` → always `202`. Regenerates the code if a pending row
exists, resets `attempts` to 0. Rate limited hard: 3 per email per hour.

---

## 4. Password policy

New module `api/password_policy.py`, the single validator called from register,
password reset, and change-password.

```python
def validate_password(
    password: str, *, email: str, display_name: str | None, checker: BreachChecker
) -> None:                                  # raises ApiException(400, "PASSWORD_WEAK", …)
```

Rules, in order of cost:

1. Length 12–1024 (the existing floor, unchanged).
2. Rejected if it contains the email local-part or the display name as a
   case-insensitive substring of ≥4 characters.
3. Rejected if present in a bundled top-1000 common-password list, shipped as
   `src/resume_agent/api/data/common_passwords.txt` (~8 KB, one entry per line,
   loaded once and memoized). This is the **offline floor** — the rule that
   still applies when the network is gone.
4. Rejected if breached, per HIBP.

### HIBP k-anonymity

SHA-1 the candidate, `GET https://api.pwnedpasswords.com/range/{first 5 hex}`,
scan the response lines for the remaining 35 hex characters. Only a 5-character
prefix leaves the process; the password itself never does, and the prefix maps
to roughly 800 hashes, so the service cannot identify the candidate.

**Fails open**, logged at WARNING, on any timeout or non-200. Registration
availability beats perfect enforcement, and rules 1–3 still hold. The checker is
a protocol with a `NullBreachChecker` used by the offline suite.

### Frontend meter

A local heuristic in `web/src/features/auth/strength.ts` — length bands,
character-class diversity, obvious sequence/repeat detection. **No new
dependency** (zxcvbn is not worth 400 KB here). It is explicitly advisory: it
renders a bar and a hint, never blocks submit, and the server remains the only
authority. The user learns the real verdict from the server's `PASSWORD_WEAK`
message, which names the specific failed rule.

---

## 5. Rate limiting, lockout, enumeration

### Why the current limiter is insufficient

`FailedAttemptLimiter` (`api/rate_limit.py`) keys on `(username, ip)` in
process memory. Two gaps: rotating the source IP produces a fresh key, so a
distributed attempt against one account never trips it; and the counters die on
restart, so a redeploy hands an attacker a clean budget.

### Replacement

`api/attempts.py`, backed by `login_attempts`. Three concurrent scopes:

| Scope      | Budget      | Catches                             |
| ---------- | ----------- | ----------------------------------- |
| `email_ip` | 10 / 15 min | today's rule, preserved             |
| `email`    | 20 / hour   | distributed attempts on one account |
| `ip`       | 50 / hour   | spraying across many accounts       |

Exceeding any scope → `429 RATE_LIMITED`. Rows older than the longest window are
pruned on each write, so the table stays small without a sweeper.

Applied to `login`, `register`, `verify-email`, `resend-code`,
`password/forgot`, and `password/reset` on all three scopes. The Google
`start`/`callback` pair is limited on the **`ip` scope only** — the account
email is not known until after the token exchange, so there is nothing to key
an email-scoped budget on at gate time.

### Progressive lockout

Each failed authentication against a known account increments
`users.failed_login_count` and, at a tier boundary, writes `users.locked_until`:

| `failed_login_count` | Lock       |
| -------------------- | ---------- |
| 5                    | 1 minute   |
| 10                   | 15 minutes |
| 15                   | 60 minutes |
| every 5 thereafter   | 60 minutes |

Both fields reset — count to 0, `locked_until` to `NULL` — on any successful
authentication, including a successful password reset or Google sign-in. The
counter lives on `users` rather than being derived from `login_attempts`
because "consecutive" needs a success marker, and successes are not recorded. A locked account returns the same
generic `401` as a wrong password — the lock is not disclosed, because doing so
tells an attacker their guesses are landing on a real account.

### Enumeration defense

Endpoints must not reveal whether an address is registered. This **changes
existing behavior**: `register` currently answers `409 USERNAME_TAKEN`.

| Endpoint          | Existing address                              | Unknown address                         |
| ----------------- | --------------------------------------------- | --------------------------------------- |
| `register`        | `202 {status: sent}` + notice email to holder | `202 {status: sent}` + code email       |
| `password/forgot` | `202 {status: sent}` + code email             | `202 {status: sent}`, no email          |
| `login`           | `401 UNAUTHORIZED`                            | `401 UNAUTHORIZED` (dummy-hash compare) |

The tradeoff, accepted: a user who forgets they already have an account is told
by email rather than on screen. The existing `DUMMY_PASSWORD_HASH` compare
(`api/auth.py:16`) already equalizes login timing and is retained; register and
forgot do the same amount of hashing work in both branches.

---

## 6. Sessions and revocation

The session HMAC key is currently derived from `session_secret` and the user's
`password_hash` (`api/auth.py:90`), so rotating the hash already invalidates
every outstanding cookie. This design extends the key material to include
`session_epoch`:

```python
key = hmac.new(session_secret, f"{namespace}:{password_hash or ''}:{epoch}", sha256)
```

Two consequences, both free:

- **Google-only accounts work.** `password_hash` is the empty-string sentinel,
  contributing nothing to the key; sessions stay unique because the signed
  payload carries `user_id`.
- **Sign out everywhere is one integer.** `POST /api/account/sessions/revoke-all`
  increments `session_epoch` and re-issues the caller's own cookie so the
  current device stays signed in. No session table, no sweep.

Password reset and password change both bump the epoch. Reset signs the user in
immediately afterward with a fresh cookie.

### Password reset flow

`POST /api/auth/password/forgot` — `{ email }` → always `202`. If the account
exists, write a `PasswordResetCode` and `send()` the code; otherwise do nothing
observable. Works for Google-only accounts too: setting a password on one is
simply a reset against a verified address, needing no special UI.

`POST /api/auth/password/reset` — `{ email, code, newPassword }`:

1. Rate gate; verify the code (hash, TTL, attempts, not consumed).
2. Validate the new password (§4); reject if it matches the current hash.
3. Rotate `password_hash`, bump `session_epoch`, mark the code consumed.
4. `notify()` the "password changed" notice.
5. Issue a fresh session; return `MeResponse`.

### Change password

`POST /api/account/password` keeps its existing shape — `PasswordChangeRequest`
already requires `current_password` (`schemas/account.py:30`). Added: the §4
policy, an epoch bump with the caller's cookie re-issued, and the "password
changed" notice.

---

## 7. Legacy accounts

The bootstrap admin is created from `AUTH_USERNAME` / `AUTH_PASSWORD_HASH`
(`bootstrap.py:46`) and has no email. Email-only login would lock them out on
the first deploy after this ships.

Three pieces:

1. A new optional `AUTH_EMAIL` setting, used by `ensure_bootstrapped` for fresh
   deployments. When present the admin is created with
   `email_verified_at = now` — the operator who set the env var owns the box.
2. **A login fallback:** the identifier resolves as
   `email == identifier OR (email IS NULL AND username == identifier)`. Only
   rows that never got an email are reachable by username, so the fallback
   cannot be used to bypass email identity on a migrated account.
3. Accounts authenticated through the fallback receive `needsEmail: true` on
   `MeResponse`. `AuthGate` routes them to `/complete-profile`, which collects
   and verifies an address before the app is usable. On verification the row
   gains an email and drops out of the fallback permanently.

The fallback is dead code once every row has an email. It ships with a comment
saying so and a test asserting it is unreachable for rows that have one.

---

## 8. Google sign-in

### Endpoints

`GET /api/auth/google/start?mode=login|register&invite=…` → `{ authUrl }`.
Scopes: `openid email profile`. Nothing else — a stranger is never asked for
inbox access.

`GET /api/auth/google/callback` — **unguarded**, mounted on the same
`callback_router` pattern as `gmail_callback`, because Google's top-level
redirect does not carry SameSite cookies.

### State signing

`issue_link_token` cannot be reused: it is keyed on a `user_id` that does not
exist during signup. A sibling pair in `api/auth.py`:

```python
def issue_oauth_state(settings, *, mode, invite_hash, now=None) -> str
def verify_oauth_state(settings, state, *, now=None) -> OAuthState | None
```

signs `(mode, invite_hash, nonce, expiry)` under a new `"oauth"` namespace with
the same `session_secret`, 10-minute TTL. The invite rides inside the signed
state so it cannot be swapped between the start call and the callback.

### Callback resolution

Resolved in this order, first match wins:

1. **`google_sub` matches a user** → sign in. Authoritative; email is ignored.
2. **No `google_sub`, email matches a user, and Google asserts
   `email_verified: true`** → link: set `google_sub`, `notify()` a
   "Google account linked" message, sign in.
3. **No match, `mode=register`, invite valid** → create the `User` with
   `email_verified_at = now`, consume the invite under `BEGIN IMMEDIATE`,
   `provision_workspace`, sign in.
4. **No match, `mode=login`** → redirect `/login?error=no_account`.
5. **Email matches but `email_verified` is false** → refuse, redirect
   `/login?error=unverified_google`.

Branch 5 is not a formality. Matching an OAuth identity on email alone is a
known takeover vector: an attacker registers a victim's address at a provider
that does not verify ownership, signs in, and inherits the account. Requiring
`email_verified` at link time and pinning to `sub` thereafter closes both halves.

The `id_token` is verified with `google.oauth2.id_token.verify_oauth2_token`
against the configured client id — the claims are never read unverified.

Users created through branch 3 have `password_hash = ""` and no password.

### Gmail sync pre-wiring

Gmail stays a separate opt-in in Settings; the existing connect flow, scopes,
callback, and per-user token file are **untouched**. Two parameters make it one
click for a Google-authenticated user, in `routers/gmail.py::gmail_connect`:

- `login_hint=<account email>` — skips the Google account picker.
- `include_granted_scopes=true` — incremental authorization on the existing
  grant, so consent shows only the Gmail scopes being added.

An account that signed in with Google therefore reaches connected Gmail sync in
one click with no account picker, while a stranger evaluating the product is
never asked for inbox access.

### Unlink

`DELETE /api/account/google` clears `google_sub` and `notify()`s. Refused with
`409 PASSWORD_REQUIRED` when the account has no password hash — unlinking would
otherwise lock the user out permanently. The remedy shown is to set a password
via reset first.

---

## 9. API surface

| Method   | Path                               | Auth    | Purpose                                      |
| -------- | ---------------------------------- | ------- | -------------------------------------------- |
| `POST`   | `/api/auth/register`               | none    | Start signup; writes pending row, sends code |
| `POST`   | `/api/auth/verify-email`           | none    | Consume code, create user, sign in           |
| `POST`   | `/api/auth/resend-code`            | none    | New code for a pending signup                |
| `POST`   | `/api/auth/login`                  | none    | `email` + `password` (was `username`)        |
| `POST`   | `/api/auth/password/forgot`        | none    | Send reset code                              |
| `POST`   | `/api/auth/password/reset`         | none    | Consume code, rotate hash, sign in           |
| `GET`    | `/api/auth/google/start`           | none    | Authorization URL                            |
| `GET`    | `/api/auth/google/callback`        | none    | Exchange, resolve, sign in                   |
| `POST`   | `/api/account/email`               | session | Set/change email on a legacy account         |
| `POST`   | `/api/account/email/verify`        | session | Verify that address                          |
| `POST`   | `/api/account/sessions/revoke-all` | session | Bump epoch                                   |
| `DELETE` | `/api/account/google`              | session | Unlink                                       |

### Contract changes (breaking)

- `LoginRequest.username` → `email` (`EmailStr`, casefolded).
- `RegisterRequest`: `username` → `email` + optional `displayName`.
- `MeResponse` gains `email`, `emailVerified`, `needsEmail`, `googleLinked`.
- `GET /api/health` returns `HealthOut { status, mailConfigured }`.

Regenerate with `bash scripts/gen_ts_client.sh`;
`tests/api/test_openapi_contract.py` is the drift gate.

---

## 10. Web UI

### Layout — split canvas

A new `AuthLayout` shell used by all six auth routes. At `lg` and above, two
columns:

- **Left ≈55%** — branded panel: deep-teal gradient wash over `--primary`, the
  product wordmark, a one-line value proposition, and a subtle animated
  constellation motif reusing the skill-constellation aesthetic so the page
  reads as this product rather than a template. Decorative, `aria-hidden`.
- **Right ≈45%** — the form column on `--background`, vertically centered,
  `max-w-sm` content.

Below `lg` the panel drops entirely and the form becomes today's centered card.

The structural reason for the split, over the current centered card: this flow
grows from two screens to six, and their heights differ sharply — a six-box code
input is short, a password screen with a strength meter and a Google button is
tall. A centered card visibly jumps size between steps. With a fixed split only
the right column changes and the composition holds still.

Tokens are unchanged: Geist Variable, teal primary (`#08708a` light /
`#5bd8e7` dark), `--radius: 0.5rem`. Both themes must be legible; the panel
gradient has a dark-mode variant rather than a single fixed image.

### Routes

| Route               | Screen                                                                |
| ------------------- | --------------------------------------------------------------------- |
| `/login`            | Google button, `or` divider, email + password, forgot link            |
| `/register`         | Google button, `or` divider, email + password + invite + display name |
| `/verify-email`     | 6-box code entry, resend with cooldown                                |
| `/forgot-password`  | Email field, always-succeeds confirmation                             |
| `/reset-password`   | Code + new password + strength meter                                  |
| `/complete-profile` | Legacy email collection, then verification                            |

### New components

- `AuthLayout` — the split shell.
- `OtpInput` — six single-character boxes, paste-aware (a pasted 6-digit string
  fills all boxes), auto-advancing, arrow-key navigable, one accessible label
  for the group.
- `PasswordStrengthMeter` — advisory bar and hint (§4).
- `GoogleButton` — official mark, correct wording, disabled with an explanatory
  tooltip when no OAuth client is configured.

### Account page

A new `SecurityCard` beside the existing `PasswordCard`: Google link state with
link/unlink, and "Sign out everywhere" with a confirmation dialog.

---

## 11. Testing

Everything stays offline: no SMTP, no HIBP, no Google.

- **`FakeMailer`** captures messages in a list. A standing assertion across every
  code-issuing endpoint: **the code never appears in a response body.** That is
  the single bug that would silently reduce this whole feature to theater.
- **HIBP** is faked at the `httpx` transport, with an assertion that the request
  path carries exactly a 5-character prefix and no more. Plus a test that a
  transport error fails open and registration still succeeds.
- **Google callback** — one test per resolution branch, including the explicit
  rejection of email-linking when `email_verified` is false, and register with a
  missing or spent invite.
- **Enumeration** — register and forgot return byte-identical bodies and status
  for an existing versus unknown address; only `FakeMailer` contents differ.
- **Rate limits** — each of the three scopes trips independently; lockout
  escalates and clears on success; a locked account is indistinguishable from a
  wrong password.
- **Migration** — build a `system.db` at the old schema, migrate, assert the
  legacy admin logs in by username, receives `needsEmail`, completes
  verification, and afterward can no longer log in by username.
- **Sessions** — an epoch bump invalidates a previously-valid cookie; revoke-all
  keeps the caller signed in; a Google-only account (`password_hash == ""`)
  gets a valid, verifiable session and still cannot log in with a password.
- **Codes** — expiry, five-attempt destruction, single use, and that a consumed
  reset code cannot be replayed.
- **Web** — `OtpInput` paste and keyboard navigation; `AuthLayout` at mobile and
  desktop widths; the strength meter never blocking submit.

## 12. Implementation sequencing

The spec is large but not decomposable — the mail seam has no purpose without
the flows, and the flows cannot be verified without the seam. It is one plan,
sequenced so every phase leaves the suite green and the app usable:

1. **Substrate** — `mail/`, `Settings` fields, `migrate_system.py`, the new
   columns and tables, `session_epoch` in the HMAC. No behavior change.
2. **Password policy** — `password_policy.py` + breach checker, wired into the
   existing change-password endpoint only.
3. **Rate limiting** — `attempts.py` replaces `FailedAttemptLimiter` behind the
   existing call sites.
4. **Email registration + reset** — the new endpoints, the legacy username
   fallback, `needsEmail`.
5. **Google sign-in** — state signing, callback resolution, Gmail pre-wiring.
6. **Web** — `AuthLayout`, the six routes, new components, `SecurityCard`.

Phase 4 is where the breaking contract change lands; the TypeScript client is
regenerated in that same phase.

## Risks

| Risk                                                 | Mitigation                                                                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| SMTP misconfigured in production silently logs codes | `mailConfigured` on `/api/health`; admin banner; documented in the deploy guide                                                             |
| SMTP provider rate limits or greylists the sender    | Resend capped at 3/hour/email; `MailDeliveryError` surfaces as `503`, not a hang                                                            |
| HIBP outage blocks all registration                  | Fails open by design; rules 1–3 still enforced                                                                                              |
| Legacy admin locked out on deploy                    | Username fallback (§7), covered by the migration test                                                                                       |
| Google consent screen unverified-app warning         | Pre-existing — the same client already requests sensitive Gmail scopes today; sign-in scopes are non-sensitive and add no new review burden |
| Breaking contract change to `login`                  | Single-owner deployment; contract regenerated and gated in the same change                                                                  |
