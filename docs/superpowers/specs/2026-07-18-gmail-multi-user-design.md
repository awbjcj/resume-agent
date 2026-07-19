# Gmail Multi-User Integration — Design

**Date:** 2026-07-18
**Status:** Approved (brainstorming session)

## Problem

The existing `gmail/` package (fetch → match → classify → propose status
transitions) is hardwired single-user: module-level constants
`config/gmail_credentials.json` / `data/gmail_token.json` bypass
`resolve_tenant_path`, and `InstalledAppFlow.run_local_server()` pops a local
browser — impossible on the Railway deployment and shared across all tenants.

This design rewires Gmail into the multi-user tenancy architecture (ADR-0003)
and extends it with three features: scheduled inbox sync, follow-up reminders,
and an LLM email writer that produces Gmail drafts.

## Decisions made

| Decision             | Choice                                                                                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| OAuth architecture   | Platform OAuth client + per-user client override (mirrors shared-LLM-key + own-key pattern)                                                             |
| Feature set          | Scheduled inbox sync, follow-up reminders, email writer (drafts). Recruiter contact tracking dropped — replies address the matched Gmail thread instead |
| Reminder scope       | Stale applications only — deterministic, no date parsing                                                                                                |
| Writer entry points  | Both: "Draft email" on job/application detail AND "Draft follow-up" on reminders                                                                        |
| Background machinery | In-process asyncio scheduler in the FastAPI lifespan (Approach A; no external cron, no sync-on-activity)                                                |
| Sending email        | Never. `gmail.compose` (drafts) only; `gmail.send` is permanently out of scope                                                                          |

## 1. Credential management & OAuth flow

**Platform OAuth client, per-user tokens, per-user override.**

- **New Settings fields:** `google_oauth_client_id` / `google_oauth_client_secret`
  (env: `GOOGLE_OAUTH_CLIENT_ID/SECRET`). As `str` fields they automatically join
  `_OVERLAY_FIELDS` in `tenancy/workspace.py`, so a user who sets their own
  client in `secrets.env` (two new rows in `SECRET_FIELDS`, editable via
  Settings > Secrets) overrides the platform client with zero extra plumbing.
- **Per-user token storage:** `{workspace}/gmail_token.json` — a new
  `gmail_token` property on `WorkspacePaths`. Tokens never enter the shared DB;
  deleting a user's workspace deletes their token, and workspace export/import
  carries it automatically. The legacy single-user path `data/gmail_token.json`
  keeps working in local no-tenancy mode: `resolve_tenant_path` returns it
  unchanged with no active context and rebases into the workspace when one is.
- **Web connect flow:**
  - `GET /api/gmail/connect` → builds the Google authorization URL (offline
    access, consent prompt) with a signed `state` parameter — HMAC over user id
    - expiry using `session_secret` (same signing material as session cookies).
      Returns `{authUrl}`; the web UI opens it.
  - `GET /api/gmail/callback?code=&state=` → verifies `state`, exchanges the
    code using the _effective_ (overlay-resolved) client, writes the token JSON
    into that user's workspace, redirects back to Settings with a
    success/failure flag. The callback authenticates via the signed state, not
    the session cookie (Google's top-level redirect may not carry SameSite
    cookies); a forged state fails the HMAC.
  - `GET /api/gmail/status` → `{connected, email?, scopes, clientSource:
"platform"|"own"}` for the Settings card.
  - `DELETE /api/gmail/token` → disconnect (revoke best-effort, then delete the
    token file).
- **Scopes:** `gmail.readonly` + `gmail.compose` requested at connect time. An
  existing readonly-only token remains connected-for-sync but not
  draft-capable; the Settings card and writer UI show "reconnect to enable
  drafts". (`gmail.readonly` is a Google restricted scope: a platform OAuth app
  in "testing" mode serves up to 100 explicitly-added test users without
  Google verification.)
- **CLI/local:** `build_gmail_service` refactors into `gmail/auth.py`:
  `load_credentials(paths)` (token file → refresh if expired → None if
  absent/revoked) shared by both modes, with `InstalledAppFlow` retained as the
  CLI-only interactive fallback. Refresh failures surface as typed
  `GmailNotConnected`, never a stack trace.

## 2. Scheduled inbox sync + upgraded classification

**Scheduler** (`gmail/scheduler.py`): one asyncio background task started in
the API lifespan alongside `init_db`.

- Every `Settings.gmail_sync_interval_hours` (default 6, `0` = disabled), list
  users with a workspace token file; for each, enter their `UserContext` (the
  same seam `RunManager.submit` uses) and run sync pass + reminder pass.
- Per-user try/except: one user's revoked token or quota error is logged and
  skipped, never aborting the loop (same isolation philosophy as
  `FetchResult.failures`).
- Serial per tick — inbox scans are cheap, and serializing avoids stampeding
  the shared LLM key. The existing `singleton_key="gmailSync"` mechanism
  becomes per-user so a manual `POST /api/gmail/sync` and a scheduled tick
  can't overlap for the same user.
- Process restart resets the timer; no persisted schedule state.
- Each pass writes a normal run record under the user's `runs/` dir via
  `ProgressReporter`, so the Runs page shows scheduled syncs like manual ones,
  labeled `gmailSync (scheduled)`.

**Classification upgrade.** Today classification sees only subject + snippet.

- `fetch_recent_messages` gains a second phase: only for messages that _match_
  an application, fetch `format="full"` and extract text/plain (or html →
  `html_to_text`), truncated to a few KB. Match first, fetch bodies second —
  most inbox mail matches nothing.
- `classify_email` stays rule-first; rules and the LLM fallback now see the
  body. The LLM fallback becomes actually wired: cheap tier via
  `model_for_tier("cheap")`, invoked only when rules say `none` and the message
  matched an application. Budget enforcement applies automatically via
  `llm_runner`.
- Sync results still land exclusively as reviewable `Notification` rows —
  scheduled sync never auto-applies a status change.

## 3. Follow-up reminders (stale applications)

**Detection is deterministic — no LLM, no email parsing.** A
`services/reminders.py` pass runs right after each sync (scheduled or manual):

- An application is **stale** when `status ∈ {submitted, interview}` and
  `updated_at` is older than `Settings.follow_up_days` (default 14, `0` =
  disabled). Any status change, note edit, or manual touch resets the clock
  because those bump `updated_at`.
- A stale app produces a `Notification` with `kind="follow_up"`,
  `evidence="No activity for N days"`, and a synthetic dedupe key in the
  existing `message_id` column: `followup:{app_id}:{updated_at.date()}`. The
  existing `notification_by_key` uniqueness check then yields **one reminder
  per staleness episode** — a dismissal stays dismissed until real activity
  moves `updated_at`, which starts a new episode.

**Model impact:** `Notification.proposed_status` is `""` for reminders (column
stays non-null; no migration). `NotificationOut` gains `kind` plus
`jobId`/`company`/`title` projected from the join.

**Action semantics branch by kind:**

- `kind="follow_up"` + accept → does _not_ touch status
  (`accept_notification` branches: status-proposal kinds apply the transition;
  reminder kinds just mark `accepted`). The UI renders accept as **"Draft
  follow-up"** — marks the reminder accepted and opens the email writer
  pre-filled.
- Dismiss works unchanged for every kind.
- The bell grows kind-aware rendering but stays one list, one badge.

## 4. Email writer (Gmail drafts, never sends)

**Generation.** New `services/email_writer.py`, one entry point: job + type
(`follow_up` | `thank_you` | `withdrawal` | `cold_outreach`) + optional
free-text instruction. The prompt grounds on:

- profile facts (`facts.json`) as the _only_ permitted source for claims about
  the user — same evidence discipline as tailoring, but with a **human gate
  instead of an LLM gate**: no fact-check reviewer round, because the output is
  a Gmail draft the user must open, edit, and send themselves.
- the job (company, title, JD excerpt), application status + dates, and — when
  matched inbox mail exists — the latest matched message (sender, subject,
  body excerpt) so replies sound like replies.
- Mid-tier model via the normal `llm_runner` path (budget-enforced, retries
  included).

**Persistence:** one small table —
`EmailDraft(id, job_id, draft_type, subject, body, to_addr, gmail_thread_id?,
gmail_draft_id?, state: generated|saved, created_at)`. The generation run
writes a row; the UI fetches it. Gives draft history and makes save
idempotent-ish (re-save updates the same Gmail draft via `drafts.update`).

**Recipient logic.** Matched thread exists → pre-fill `to_addr` from the last
inbound sender and set `gmail_thread_id` so the Gmail draft is created
in-thread (a proper reply). Otherwise → `to_addr` empty; the user fills it in
the review modal.

**API + flow.**

- `POST /api/jobs/{id}/email-draft` `{type, instructions?}` → `202` Run
  (existing RunManager pattern). On completion,
  `GET /api/jobs/{id}/email-drafts` returns rows.
- Web modal: editable subject/body/to → "Save to Gmail drafts" →
  `POST /api/email-drafts/{id}/save` → `users.drafts.create/update` with
  compose scope. Success shows a Gmail deep link.
- Degradation: Gmail not connected, or token readonly-only → generation still
  works; save is replaced by "Copy to clipboard" + a reconnect hint.

**Entry points:** "Draft email" action (type picker) on job/application
detail, and the reminder's "Draft follow-up" button pre-selecting `follow_up`.

## 5. Cross-cutting

**New Settings fields** (platform-level, env-overridable):
`google_oauth_client_id` + `google_oauth_client_secret` (also per-user via
`SECRET_FIELDS`/`secrets.env`), `gmail_sync_interval_hours` (default 6, `0`
disables scheduler), `follow_up_days` (default 14, `0` disables reminders),
`gmail_max_messages` (default 50, replaces the hardcoded fetch cap).

**Error taxonomy** (`gmail/errors.py`): `GmailNotConnected` (no/revoked token
→ 409 `GMAIL_NOT_CONNECTED`), `GmailScopeMissing` (readonly token asked to
save a draft → 409 `GMAIL_SCOPE_MISSING`), `GmailApiError` (quota/5xx
wrapped). The scheduler catches all three per user and records them in run
failure telemetry; routers map them through the `ApiException` envelope. The
OAuth callback never renders raw errors — it redirects to Settings with an
error-code query param.

**Testing (offline).** The Google SDK joins the faked-in-tests club: a
`FakeGmailService` fixture serving canned payloads (list/get/full-format/
drafts.create); OAuth flow tested with a fake token file + monkeypatched code
exchange; scheduler tested by invoking one tick directly with a fake clock;
body extraction tested against fixture MIME payloads. No live Google calls;
`google-api-python-client` stays a lazy import (mirrors the lazy provider-SDK
pattern in `build_model`).

**What deliberately doesn't change:** fact-lock (drafts never touch
`facts.json` or resumes), `has_progress` (drafts/reminders never gate job
deletion — but `delete_job` cascades `EmailDraft` rows), source priority, and
the existing manual `POST /api/gmail/sync` + notifications accept/dismiss
contract (extended, not broken).
