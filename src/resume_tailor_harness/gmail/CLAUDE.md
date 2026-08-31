# Gmail integration developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_tailor_harness/gmail/`.

- **The Gmail token exchange must reconcile scopes; oauthlib cannot.** Connect
  sends `include_granted_scopes=true`, so Google returns the union of every
  scope the shared OAuth client holds — the Gmail pair _plus_ the three
  identity scopes from sign-in. oauthlib reads RFC 6749 §3.3 as a raw set
  inequality (`OAuth2Token.scope_changed`) and raises a bare `Warning` from
  inside `fetch_token` on **any** difference, so it cannot tell a harmless
  incremental superset from a grant missing what was asked for. It fired on
  every connect by a Google-signed-in user, and the callback's blanket
  `except Exception` turned it into `?gmail=error` — i.e. adding Google
  sign-in silently broke Gmail connect for exactly the users it targeted.
  `_exchange_token` (`api/routers/gmail.py`) is the one seam that clears
  `oauth2session.scope` to drop that comparison, then makes the distinction
  explicitly: no `gmail.readonly` in the grant raises `GmailScopeMissing`
  rather than storing a token that reports a connection the user never gave.
  It then restores the session scope to what was **granted**, because
  `Flow.credentials` copies it into `Credentials.scopes` and `to_json` persists
  only that list — the one `has_compose`/`draftCapable` later read. Storing the
  _requested_ pair would claim compose access a user may have withheld on
  Google's granular consent screen. Never call `flow.fetch_token` directly
  here. Pinned by `tests/api/test_gmail_oauth_scope.py`, which drives the real
  google-auth-oauthlib stack over a stubbed token endpoint — a faked `Flow`
  exercises none of this.
- **Gmail is multi-user; drafts only, never send.** The platform OAuth client
  (`GOOGLE_OAUTH_CLIENT_ID/SECRET`) can be overridden per user via
  `secrets.env`; per-user tokens live at `{workspace}/gmail_token.json`
  (`gmail/auth.py` is the only credential seam; scopes = readonly + compose).
  The web callback authenticates via a signed link-token state, never the
  session cookie. An in-process scheduler (`gmail/scheduler.py`, every
  `gmail_sync_interval_hours`) runs `services/gmail_sync.run_gmail_sync`
  per connected user — sync proposals land in the notification bell; nothing
  auto-applies. `services/email_writer.py` grounds drafts in facts.json
  only (human gate, no LLM fact-check round) and saves them as in-thread
  Gmail drafts via `EmailDraft` rows; drafts never gate job deletion but
  cascade on delete. `gmail.send` is permanently out of scope.
- **Gmail does not own reminders, and used to by accident.**
  `create_follow_up_reminders` once had exactly one call site — *inside*
  `run_gmail_sync`, after `build_service()` raises for a user with no token —
  and `gmail/scheduler.py` only iterates users owning a `gmail_token.json`. So
  a user who never connected Gmail silently received **no reminders at all**,
  and nothing said so. `services/reminder_scheduler.py` now owns them on its
  own hourly tick that runs for every user regardless of Gmail state;
  `run_gmail_sync` returns `{"pending": n}` and does email classification only.
  Keep it that way: reminders are a property of having dated events, not of
  having connected a mailbox. Pinned by
  `tests/test_reminder_scheduler.py::test_reminder_pass_runs_without_any_gmail_token`
  and by a source-level assertion that `gmail_sync` no longer imports the
  reminder helpers.
