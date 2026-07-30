# Deploying to Railway

This is a public multi-user deployment: one service, one persistent volume,
one replica, an owner/admin account, and email-verified self-registration.
SQLite plus a Railway volume still requires a single replica.

## One-time setup

1. Create a Railway project from this GitHub repository. `railway.json` selects
   the Dockerfile and `/api/health` healthcheck.
2. Add one volume to the service at `/app/data`. Railway does not support
   replicas on services with volumes, which matches this SQLite deployment.
3. Generate credentials locally:

   ```powershell
   .venv\Scripts\python.exe -m resume_agent.cli hash-password --password "choose-a-password"
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

4. Add Railway variables:

   | Variable             | Value                             |
   | -------------------- | --------------------------------- |
   | `AUTH_USERNAME`      | Owner login name                  |
   | `AUTH_PASSWORD_HASH` | Output from `hash-password`       |
   | `SESSION_SECRET`     | The generated 64-character secret |
   | `API_TOKEN`          | Optional bearer token for scripts |
   | `APP_BASE_URL`       | Canonical HTTPS origin, for example `https://resume.example.com` |
   | `ALLOWED_HOSTS`      | Canonical host, for example `resume.example.com` |
   | `BROWSER_ENABLED`    | `false` (also the image default)  |
   | `REGISTRATION_MODE`  | `open` for public registration; use `invite` for a controlled launch |
   | `SECURE_COOKIES`     | `true` (also the image default; startup fails without HTTPS `APP_BASE_URL`) |
   | `DISABLE_API_DOCS`   | `true` (also the image default) |
   | `GLOBAL_DAILY_SIGNUP_LIMIT` | Maximum verification emails started per rolling day |
   | `COST_QUOTA_ENFORCEMENT` | `shadow` dual-records USD while token enforcement remains active; `enforce` enables cost quotas |
   | `GLOBAL_MONTHLY_COST_QUOTA_MICROS` | Shared-key UTC calendar-month cap in USD micro-units; defaults to `$500` |
   | `GLOBAL_WEEKLY_TOKEN_BUDGET` | Deprecated stage-one token circuit breaker; used only while cost quotas are in `shadow` mode |
   Add `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, and/or
   `DEEPSEEK_API_KEY` as Railway variables. Every admin, free member, and
   subscriber uses a matching shared key first. Users add fallback keys under
   Settings → Keys; those persist only in their tenant workspace and take over
   automatically after the account or platform shared allowance is exhausted.

5. Deploy and sign in at the Railway-provided domain.

## Email delivery

Verification codes, password resets, and security notices need a working
mailer. Confirm `GET /api/health` reports `"mailConfigured": true` after
deploying.

> **Railway blocks outbound SMTP below the Pro plan.** Port 587 fails with
> `[Errno 101] Network is unreachable` regardless of the credentials, because
> the egress is null-routed rather than refused. Use the HTTPS backend below
> unless you are on Pro — and note Railway requires a redeploy after upgrading
> before SMTP starts working.

### Resend (works on every plan)

1. Create an API key at [resend.com](https://resend.com) (the free tier covers
   3,000 emails/month).
2. Verify a sending domain under **Domains**. Without one you can only send
   from `onboarding@resend.dev`, and only to the address that owns the Resend
   account — enough to test, not enough to invite anyone.
3. Add Railway variables:

   | Variable         | Value                                             |
   | ---------------- | ------------------------------------------------- |
   | `RESEND_API_KEY` | The key you just created                          |
   | `MAIL_FROM`      | `noreply@your-verified-domain.com`                |

`RESEND_API_KEY` takes precedence over any `SMTP_*` variables, so you can
leave a previous SMTP attempt in place. `MAIL_FROM` falls back to `SMTP_FROM`
if you already set that.

### SMTP (Pro plan only)

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and
`SMTP_FROM`. All five matter: **omitting `SMTP_USERNAME` silently skips
authentication entirely**, and Gmail refuses unauthenticated relay with
`530 5.7.0 Authentication Required`. The failure log names which one you hit —
it reports `auth=off` when the username is missing.

If `SMTP_HOST` is unset and no Resend key is present, the app falls back to
`NullMailer` and **logs verification codes to the console instead of sending
them**, which is a working local setup but not a working deployment.

## Google sign-in and Gmail OAuth (optional)

One Google OAuth client covers two separate features:

- **Google sign-in** — "Continue with Google" on the login and register pages.
  Identity scopes only (`openid`, `userinfo.email`, `userinfo.profile`).
  Until it is configured, `GET /api/health` reports
  `"googleOauthConfigured": false` and the button renders disabled with
  "Google sign-in is not configured on this server."
- **Gmail** — scheduled inbox sync, stale-application reminders, and the
  email-draft writer (readonly + compose scopes only — it never sends mail).
  This is a separate, incremental consent the user grants later from
  Settings → Keys.

It needs a Google OAuth **Web application** client; this is a different
client type from the **Desktop app** client used by the local CLI's
`config/gmail_credentials.json` flow, which doesn't apply to a deployed app.

1. In the [Google Cloud console](https://console.cloud.google.com/), open (or
   create) a project and enable the **Gmail API** (APIs & Services → Library).
2. Configure the **OAuth consent screen** (APIs & Services → OAuth consent
   screen): External user type, with the `gmail.readonly` and `gmail.compose`
   scopes added. While the app is in **Testing** publishing status (the
   default, and fine for personal/family use), add every Gmail address that
   will connect as a **test user** — Google caps testing apps at 100
   explicitly-added users and refuses sign-in for anyone else.
3. Create credentials (APIs & Services → Credentials → Create Credentials →
   OAuth client ID) of type **Web application**.
4. Add **both** Authorized redirect URIs — the two features use different
   callbacks, and registering only one fails the other with
   `redirect_uri_mismatch`:

   ```
   https://YOUR-APP.up.railway.app/api/auth/google/callback   # sign-in
   https://YOUR-APP.up.railway.app/api/gmail/callback         # Gmail
   ```

   The app derives these URLs only from `APP_BASE_URL`; forwarded host headers
   are never trusted for OAuth callbacks. Add the
   `http://localhost:8000` equivalents too if you also run `resume-agent serve`
   on your machine.
5. Add Railway variables:

   | Variable                     | Value                             |
   | ---------------------------- | --------------------------------- |
   | `GOOGLE_OAUTH_CLIENT_ID`     | From the credential you just made |
   | `GOOGLE_OAUTH_CLIENT_SECRET` | From the credential you just made |

   This becomes the **platform client** every workspace connects through by
   default; any signed-in user can instead paste their own client id/secret
   under Settings → Keys, which overrides the platform client for their
   workspace only.

6. Sign in to the app, open **Settings → Keys**, and click **Connect Gmail**
   on the Gmail card to run the consent flow.

Skip this entirely if you'd rather track application statuses by hand — the
rest of the app works fine without it.

## Seed data

PowerShell:

```powershell
.venv\Scripts\python.exe scripts\pack_data.py --out seed.tar.gz
curl.exe -H "Authorization: Bearer $env:API_TOKEN" -F "file=@seed.tar.gz" `
  "https://YOUR-APP.up.railway.app/api/admin/import?confirm=REPLACE"
```

POSIX shell:

```sh
.venv/Scripts/python.exe scripts/pack_data.py --out seed.tar.gz
curl -H "Authorization: Bearer $API_TOKEN" -F "file=@seed.tar.gz" \
  "https://YOUR-APP.up.railway.app/api/admin/import?confirm=REPLACE"
```

Import validates and stages the archive, refuses while runs are active, and
full-replaces the volume only after `confirm=REPLACE`.

## Back up and restore

```powershell
curl.exe -H "Authorization: Bearer $env:API_TOKEN" `
  -o "backup-$(Get-Date -Format yyyy-MM-dd).tar.gz" `
  "https://YOUR-APP.up.railway.app/api/admin/export"
```

Restore with the import command above. Archives include `.env`; treat them as
secret material.

## Round-trip browser pull

Tesla, LinkedIn, learned scrape recipes, and Adzuna detail enrichment need a
local browser. To update the cloud snapshot:

1. Export a backup and extract it into a temporary directory.
2. Copy the temporary directory's `config/`, `output/`, and `.env` to those
   same paths at the repository root. Copy every other top-level member into
   local `data/`. Do not extract the whole archive with `-C data`, because that
   would incorrectly nest `config/` and `output/` under `data/`.
3. Run `resume-agent pull` locally with `BROWSER_ENABLED=true`.
4. Re-pack with `scripts/pack_data.py` and import it into Railway.
5. Do not mutate the cloud instance between export and import; import is a full
   replacement, not a merge.

## Cloud capability notes

- Tesla company URLs, LinkedIn, and learned scrape targets remain visible as
  per-source failures explaining that a local browser is required.
- Adzuna still imports snippet-only rows without browser enrichment.
- HTTP connectors and manual/URL intake continue normally; URL intake simply
  skips its browser fallback.
- Session cookies last 30 days. Rotate `SESSION_SECRET` to invalidate all live
  sessions; changing only the password hash does not revoke existing cookies.
- The container forces Secure cookies and disables API docs. It refuses to
  start unless `APP_BASE_URL` is an HTTPS origin.
- Shared LLM credentials come only from Railway environment variables. All
  account tiers use them first; per-user limits and the global circuit breaker
  are checked before each provider call, and a configured workspace key becomes
  the fallback after shared capacity is exhausted.
- User-influenced HTTP fetches use a shared public-address policy that pins DNS,
  revalidates redirects, and caps response bytes. Add an external egress
  firewall if your Railway/network plan supports destination controls.
