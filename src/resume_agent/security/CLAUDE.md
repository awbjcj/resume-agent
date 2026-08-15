# Security boundary developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/security/`.

### Public network trust boundary (ADR-0008)

A source-based threat model (`resume-agent-threat-model.md`,
`security_best_practices_report.md`, repo root) drove mandatory chokepoints
that every future user-influenced fetch, download, render, or archive import
must go through — see ADR-0008.

- **One egress gateway for user-influenced URLs.** `security/outbound.py`'s
  `fetch_public_text`/`resolve_public_url` is the only place allowed to make an
  HTTP(S) request to a URL a user supplied. It rejects non-`http(s)` schemes,
  embedded credentials, and any resolved address that is not globally routable
  (`ip_address(...).is_global`), then **pins the connection to the address it
  validated** while preserving the original `Host`/SNI — so a second,
  attacker-controlled DNS answer after the check (rebinding) can't steer the
  real request at a private address. Every redirect hop is revalidated the
  same way (`follow_redirects=False`, manual hop loop, capped at 5), and the
  response is capped by declared and actual byte count with a content-type
  allowlist (`text/*`, `application/xhtml+xml`). `profile/intake.py`,
  `discovery/url_ingest/fetch.py::fetch_static`, and
  `discovery/connectors/detect.py::_get_html` all call through it instead of a
  bare `httpx.get`; `services/sources.py` re-exports its resolver rather than
  keeping its own copy. A bare `httpx.get`/`.get(follow_redirects=True)` on a
  user-supplied URL anywhere in the codebase is a regression.
- **Tenant-confined artifact and render paths.** `tenancy/storage.py::artifact_path`
  is the only way a download route may turn a stored `pdf_path` into a
  `FileResponse` target. In multi-user mode (a tenancy context is active) it
  resolves the path beneath the tenant's own `output/` directory and raises
  `TenantPathError` for anything that resolves outside it — including an
  absolute path or `..` restored from an **imported** workspace archive, which
  is the actual attack: a tenant controls their own exported/re-imported
  `resume_versions`/`cover_letters` rows, so a sink that trusts stored paths
  verbatim lets an import plant a path pointing at another tenant's (or the
  host's) files. `api/routers/account.py::_validate_workspace_stage` normalizes
  every `pdf_path` in an imported database to a tenant-relative `output/...`
  value _before_ the atomic swap and refuses the import outright
  (`INVALID_ARCHIVE`) if a row can't be normalized; `resumes.py` and
  `cover_letters.py`'s download handlers resolve through `artifact_path` and
  treat `TenantPathError` as "not found," never as a 500. `render/service.py`
  and `cover_letter/render.py` write new artifacts under the active tenant's
  `context.paths.output_dir` rather than `RenderConfig.output_dir`, and
  `render/templates.py::template_path_for` refuses a legacy `template_path` in
  multi-user mode (`TemplateNotFoundError`) except the one literal legacy
  value that maps to the bundled `classic` template — a persisted or imported
  custom path can no longer select an arbitrary file. Local single-user mode
  (no tenancy context) keeps the historical explicit-path behavior for all of
  the above unchanged.
- **Callback and cookie decisions read configuration, never forwarded
  headers.** `api/public_url.py::public_url` builds the Google sign-in and
  Gmail OAuth redirect URIs from `Settings.app_base_url` when set, never from
  `X-Forwarded-Host`/`-Proto` — those are attacker-controlled unless a proxy
  strips them, and Railway's default Uvicorn setup does not declare a trusted
  proxy policy. `Settings.secure_cookies` forces the session cookie's `Secure`
  flag independent of `request.url.scheme` (also proxy-dependent);
  `Settings.allowed_hosts` wires `TrustedHostMiddleware`; `Settings.disable_api_docs`
  hides `/docs`, `/redoc`, and `/openapi.json`. The Dockerfile sets
  `SECURE_COOKIES=true` and `DISABLE_API_DOCS=true` by default and refuses to
  start unless `APP_BASE_URL` is an HTTPS origin — a production deploy
  additionally needs `ALLOWED_HOSTS` set (see `docs/deploy-railway.md`).
- **Archive extraction is resource-bounded, not just path-validated.**
  `services/backup.py::_extract_validated` streams `tarfile` members instead of
  materializing `getmembers()`, and rejects an archive during the scan (before
  `extractall`) once it exceeds `max_members` (10,000), any single member's
  size (512 MB), total expanded bytes (2 GB), or a >200:1 compression ratio
  against the compressed file's own size. `services/settings_bundle.py`'s
  bundle extractor now delegates to the same function with its own tighter
  bundle-sized limits instead of duplicating the size/member checks — one
  compression-bomb policy, two configured budgets.

---

## Threat-model gaps not yet implemented

The threat-model documents still record items **not yet implemented**: OAuth
state is not bound to the initiating browser or atomically consumed
(browser-binding, not just the existing HMAC), there is no explicit CSRF
token/Origin check for cookie-authenticated mutations, Typst/document
parsing/transcription still run in the API process rather than an isolated
worker, user provider keys are plaintext in `secrets.env` rather than
envelope-encrypted, and there is no dedicated security audit-event stream.
Check `resume-agent-threat-model.md` and `security_best_practices_report.md`
before assuming a related gap is already closed.
