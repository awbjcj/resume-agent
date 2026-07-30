# 8. One egress gateway, tenant-confined storage, and configuration-only origin trust

## Status

Accepted

## Date

2026-07-30

## Context

A source-based threat model of the public multi-user deployment
(`resume-agent-threat-model.md`, `security_best_practices_report.md`) found
three trust-boundary gaps that a normal authenticated tenant — not just an
external attacker — could exploit:

1. **SSRF.** `profile/intake.py` already implemented DNS-pinned, redirect-
   revalidated, size/content-type-bounded public-URL fetching for profile
   source URLs, but job/source URL ingestion (`discovery/url_ingest/fetch.py`,
   `discovery/connectors/detect.py`) and `services/sources.py` used plain
   `httpx.get(url, follow_redirects=True)` with no destination policy. Two
   different fetch paths for the same class of user-influenced URL meant the
   hardened one was incidental, not architectural.
2. **Cross-tenant file reads via import.** Resume/cover-letter downloads
   passed a stored `pdf_path` straight to `FileResponse`. A tenant fully
   controls their own exported-then-reimported workspace database, so nothing
   stopped an imported row's `pdf_path` from pointing at an absolute path
   outside that tenant's `output/` directory — reachable because the API
   process runs as one UID across all tenant workspaces.
3. **Proxy-dependent security decisions.** Session-cookie `Secure`, and the
   Google/Gmail OAuth redirect URI, were derived from `request.url.scheme` and
   `X-Forwarded-Host`/`-Proto` — correct only if the edge proxy is guaranteed
   to strip/replace those headers, which Railway's default Uvicorn setup does
   not declare.

Fixing each call site ad hoc would leave the same class of bug reachable the
next time someone adds a URL fetch, a download route, or an OAuth-adjacent
redirect — exactly the "several trusted helpers exist, but sensitive paths can
bypass them" pattern the report calls out as the main weakness.

## Decision

Introduce three narrow, mandatory seams and route every existing call site
through them:

- `security/outbound.py` (`fetch_public_text`, `resolve_public_url`,
  `validate_public_url`) is the only code allowed to make an HTTP(S) request
  to a user-supplied URL. `profile/intake.py` was rewritten to delegate to it
  instead of keeping a parallel copy of the same logic.
- `tenancy/storage.py::artifact_path` is the only way a download route may
  turn a stored artifact path into a filesystem path, and is fail-closed: in
  multi-user mode it raises `TenantPathError` for anything outside the active
  tenant's `output/` root. `account.py`'s workspace-import validator
  normalizes every imported `pdf_path` to a tenant-relative value (or rejects
  the import) *before* the atomic swap, so the confinement holds even for
  data the tenant fully controls.
- `api/public_url.py::public_url` builds OAuth callback URIs from
  `Settings.app_base_url`, never forwarded headers. `Settings.secure_cookies`,
  `Settings.allowed_hosts` (→ `TrustedHostMiddleware`), and
  `Settings.disable_api_docs` make the remaining proxy-dependent decisions
  explicit configuration instead of implicit header trust.

Fixing each finding independently (patching `fetch_static`'s client, adding a
one-off path check in each router) was rejected: it reproduces the same
"trusted helper, bypassable path" shape the audit flagged, and gives the next
new URL-fetching or download-serving call site nothing to fail closed against.

## Consequences

- Any new code that fetches a user-supplied URL must call through
  `security/outbound.py`; a bare `httpx.get`/`follow_redirects=True` on such a
  URL is a regression, not a style preference.
- Any new download or render-output route must resolve its path through
  `tenancy/storage.py::artifact_path` (or an equivalent tenant-confined
  helper) rather than trusting a stored string directly.
- Local single-user mode (no tenancy context) is intentionally exempt from the
  confinement — `artifact_path` returns the path unchanged when
  `current_context()` is `None` — preserving existing CLI behavior with
  explicit `--config`/`--out` paths.
- This closes the P0 items reachable from normal (non-privileged) tenant
  action. It does **not** close the remaining P0/P1 items the threat model
  records as separate work: platform-wide shared-key budgets, OAuth state
  browser-binding, archive-expansion resource limits, and worker-process
  isolation for Typst/document parsing still need their own seams.
