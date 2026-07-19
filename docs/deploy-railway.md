# Deploying to Railway

This is a single-user deployment: one service, one persistent volume, one
replica, and one owner login.

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
   | `BROWSER_ENABLED`    | `false` (also the image default)  |

   Add LLM, GitHub, Adzuna, and LinkedIn secrets after login under Settings →
   Keys. They persist in the volume-backed `.env`. Do not also set those in
   Railway, because platform environment variables take precedence.

5. Deploy and sign in at the Railway-provided domain.

## Gmail OAuth (optional)

Gmail powers scheduled inbox sync, stale-application reminders, and the
email-draft writer (readonly + compose scopes only — it never sends mail).
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
4. Add an **Authorized redirect URI**:
   `https://YOUR-APP.up.railway.app/api/gmail/callback`. The app derives this
   URL itself from the request's `X-Forwarded-Proto`/`X-Forwarded-Host`
   headers, which Railway sets automatically — nothing else to configure on
   the app side. Add a second redirect URI for local testing if you also run
   `resume-agent serve` on your machine, e.g.
   `http://localhost:8000/api/gmail/callback`.
5. Add Railway variables:

   | Variable                    | Value                              |
   | ---------------------------- | ----------------------------------- |
   | `GOOGLE_OAUTH_CLIENT_ID`     | From the credential you just made   |
   | `GOOGLE_OAUTH_CLIENT_SECRET` | From the credential you just made   |

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
