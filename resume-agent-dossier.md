---
repo_url: https://github.com/awbjcj/resume-agent
repo_name: resume-agent
role: sole author
generated_at: 2026-07-30
---

# Project: Resume Agent

A local-first, fact-locked AI pipeline that pulls job postings from 16+ sources, scores them against a candidate's real experience, tailors resumes and cover letters through a multi-agent review loop, renders them to PDF, and tracks applications — now shippable as a public multi-user web service with its own authentication, tenancy, and security-hardening layer.

## Summary

Job seekers waste hours manually rewriting a resume for each posting, and generic AI rewriters routinely fabricate experience the candidate never had. Resume Agent solves both: it ingests a person's resume (plus optional GitHub repositories) into a single `facts.json` "fact-lock," then treats that file as the only ground truth any downstream agent may draw from — agents rewrite and reframe, but a hard `fact-check` gate fails any bullet that cannot be traced to a real fact. The system is a full funnel (`pull → discover → approve → tailor → cover-letter → render → track`) exposed identically through a Typer CLI and a FastAPI + React web app. It began as a single-user local tool and was rearchitected into a multi-tenant service — per-user SQLite workspaces addressed through a `contextvars`-propagated tenancy context, email/Google-OAuth authentication, per-user and platform-wide LLM spend governance, and Gmail-based application-status tracking — then hardened through a self-authored threat model and security-best-practices audit that closed several cross-tenant trust-boundary gaps before public registration. It was built and maintained by a single author across 1,650+ commits between 2026-06-08 and 2026-07-30 (`git shortlog`), and remains under active development. The codebase is ~45,500 lines of Python across 328 modules, backed by roughly 2,360 test functions across 344 files that run fully offline.

## Tech stack (evidence-backed)

- Python 3.13+ — entire backend (`pyproject.toml` `requires-python = ">=3.13"`; 328 modules under `src/resume_agent/`).
- agno 2.6.x — LLM agent framework wrapped by the `AgentRunner` adapter in `src/resume_agent/llm_runner.py`.
- Anthropic / OpenAI / google-genai / DeepSeek SDKs — multi-provider LLM access behind a single `build_model()` seam in `llm_runner.py` (lazy per-provider imports).
- FastAPI + uvicorn + sse-starlette — HTTP layer with 35+ routers under `src/resume_agent/api/routers/`; long operations stream via Server-Sent Events; `starlette.middleware.trustedhost.TrustedHostMiddleware` enforces a configured host allowlist in production (`api/app.py`).
- Pydantic v2 + pydantic-settings — the schema/contract source of truth (`api/schemas/base.py` `CamelModel`, fact models in `models/profile.py`, `config.py::Settings`).
- SQLModel over SQLite (WAL mode) — persistence; `make_engine` sets `journal_mode=WAL`, `busy_timeout`, `synchronous=NORMAL`. A separate system-database schema (`tenancy/system_db.py`) holds users, sessions, invites, and usage events, isolated from per-tenant workspace databases.
- Playwright (Chromium) — real-browser automation for LinkedIn scraping, the Tesla portal, and Adzuna redirect enrichment (`discovery/scraper/`, `discovery/connectors/tesla.py`).
- Typst (`typst` Python binding) — resume and cover-letter PDF rendering from `templates/resume.typ` / `templates/cover_letter.typ`, plus tenant-uploaded custom templates validated and compiled through `render/templates.py`.
- React + TypeScript (Vite) — web front end, 300+ `.tsx` files under `web/`, consuming a generated OpenAPI TypeScript client in `contracts/ts/`.
- markitdown (`[docx,pdf,pptx,xlsx]`) + BeautifulSoup + markdownify — resume/supporting-material ingestion and HTML→text extraction.
- Google API client + OAuth (`google-api-python-client`) — Google sign-in (identity-only scopes) and per-user Gmail OAuth for inbox sync, stale-application reminders, and draft email writing (readonly + compose scopes only; never send).
- `hashlib.pbkdf2_hmac` (stdlib, 600,000 iterations) for password hashing and stateless HMAC-signed session/verification tokens (`api/auth.py`) — no third-party auth library.
- `httpx` (HTTPS) + stdlib `smtplib` — dual-backend transactional mail (`mail/mailer.py`): a Resend API backend for hosts that block outbound SMTP, and a direct SMTP backend, with a `NullMailer` console fallback for local development.
- httpx — connector HTTP for every ATS/job-board backend, plus the single SSRF-hardened outbound gateway (`security/outbound.py`) used for every user-influenced URL fetch.
- pytest + pytest-asyncio + ruff — test and lint tooling (344 test files, ~2,360 test functions).

## Architecture highlights

- **Fact-lock invariant enforced by a closed schema.** Every tailored bullet must trace to `data/profile/facts.json`; the `fact-check` reviewer in `review.yaml` is a non-scored hard gate. `profile/project_extractor.py` uses a closed Pydantic boundary (`ProjectDocFacts`, `extra="forbid"`) that can emit exactly one project plus evidenced skills and *cannot* fabricate employment or education.
- **Multi-tenant workspace isolation rides one propagation mechanism.** A `contextvars.ContextVar` (`tenancy/context.py`) holds the active per-request `UserContext` (settings, workspace paths, engine); it is set at exactly three points — the API auth dependency, the background-run worker wrapper, and the CLI callback — so every deeper call site reads `get_settings()`/`current_context()` instead of receiving a threaded parameter (`docs/adr/0003-contextvar-tenancy-propagation.md`).
- **One SSRF-safe egress gateway for every user-influenced URL.** `security/outbound.py::fetch_public_text` validates scheme/credentials, rejects any resolved address that is not globally routable, pins the TCP connection to the address it validated while preserving the original `Host`/SNI (defeating DNS-rebinding), and revalidates every redirect hop under a byte/content-type-bounded response. Every URL-fetching call site in the codebase (profile source intake, job/source URL ingestion, ATS HTML sniffing) was migrated onto this one function (`docs/adr/0008-...md`).
- **Tenant-confined artifact and render storage.** `tenancy/storage.py::artifact_path` is the only path a download route may resolve a stored PDF path through; in multi-user mode it raises rather than returns a path outside the tenant's own output directory — including a path restored from an imported workspace archive, which is validated and normalized before the atomic import swap completes.
- **Registration and shared-LLM-key eligibility are deliberately separate decisions.** `Settings.registration_mode` gates whether an account can be created; `User.shared_key_access` (plus a platform-wide rolling 7-day token-usage circuit breaker in `tenancy/limits.py`) separately gates whether that account may spend the platform's shared provider keys, closing an audited Sybil-multiplication gap without requiring invite-only registration permanently.
- **Single provider seam with lazy imports.** `build_model()` in `llm_runner.py` is the only place that knows about concrete provider SDKs; provider-prefixed model ids (`openai:` / `gemini:` / `deepseek:`, bare = Anthropic) route each of three tiers independently, so a Claude-only run never imports the OpenAI or Gemini libraries.
- **Table-driven connector dispatch with per-URL failure isolation.** `discovery/connectors/companies.py` resolves each careers URL through `detect.py` (singleton → L1 URL pattern → L2 HTML sniff) and calls the matching backend; any URL that fails detection or errors is recorded on `FetchResult.failures` and never aborts the run. 16+ ATS/board backends live in `discovery/connectors/`.
- **Deadlock-safe concurrent LLM fan-out.** Discovery and tailoring run pure-async siblings through `gather_isolated` (`concurrency.py`); a global `asyncio.Semaphore(llm_concurrency)` is acquired *only* inside the leaf `llm_runner.acall`, so nested jobs×panel fan-out cannot self-starve.
- **Source priority is upgrade-not-drop.** When a canonical source re-finds an aggregator job, the existing `Job` row is mutated in place (same id) so tailored resumes, cover letters, and application status are never lost; the dedup key is paired with a location guard (`docs/adr/0001-...md`).
- **Self-authored threat modeling closed the loop before public rollout.** A source-based threat model and a companion best-practices report (both checked into the repository root) enumerate trust boundaries, an attacker model, and a prioritized (P0/P1/P2) findings table; the P0 findings drove the egress-gateway, tenant-storage, canonical-origin, archive-extraction, and registration/budget-governance changes above, each captured in its own ADR.

## Quantified outcomes

- ~2,360 test functions across 344 test files, running fully offline (LLM agents and the Playwright browser are faked; connector backends test against captured fixture JSON) — verified by `grep`/`find` over `tests/`.
- ~45,500 lines of Python across 328 modules under `src/` (`find`/`wc` over the source tree).
- 1,650+ commits from a single author (plus routine dependency-bump commits) between 2026-06-08 and 2026-07-30 (`git shortlog -sne`, `git rev-list --count HEAD`, `git log` date range).
- 16+ ATS/job-board connector backends (`greenhouse`, `lever`, `ashby`, `workday`, `tesla`, `google`, `smartrecruiters`, `workable`, `recruitee`, `personio`, `breezy`, `jazzhr`, `bamboohr`, `adzuna`, `remoteok`, `companies`) enumerated in `discovery/connectors/`.
- 35+ FastAPI routers (`ls src/resume_agent/api/routers/`) and 300+ React `.tsx` components (`find web -name "*.tsx"`).
- Archive-import hardening enforces concrete resource ceilings evidenced in code: 10,000-member cap, 512 MB per-file cap, 2 GB total-expanded-bytes cap, and a 200:1 compression-ratio cap (`services/backup.py::_extract_validated`).
- Eval calibration record (`evals/CALIBRATION.md`): stand-in mean absolute error 3.4 across 5 cases, with the judge explicitly recorded as **not trusted** pending a human anchor — a documented honesty gate, not a shipped quality claim.

## Skills demonstrated

Languages: Python, TypeScript, SQL
Backend: FastAPI, REST API design, Server-Sent Events, asyncio concurrency, bounded-semaphore rate limiting, SQLModel, SQLite WAL tuning
Multi-tenant systems: contextvar-propagated per-request tenancy, per-user workspace/database isolation, tenant-confined filesystem access, platform-wide resource/spend governance layered over per-user quotas
Security engineering: self-authored threat modeling and a prioritized findings audit, SSRF defense with DNS-rebinding-resistant connection pinning, path-traversal/tenant-confinement design, archive compression-bomb mitigation, PBKDF2 password hashing, stateless HMAC-signed tokens, OAuth (Google sign-in + Gmail) integration, production security middleware (trusted-host allowlisting, forced secure cookies, docs disabling)
AI / LLM engineering: multi-provider LLM orchestration (Anthropic, OpenAI, Gemini, DeepSeek), agentic pipelines with agno, multi-agent review panels, structured output via Pydantic schemas, LLM-as-judge evaluation, transient-error retry/backoff, prompt-injection-resistant extraction boundaries
Data & integration: web scraping with Playwright, ATS/portal reverse-engineering, HTML-to-text parsing, document ingestion (PDF/DOCX/PPTX via markitdown), Gmail OAuth integration (readonly + compose scopes), transactional email delivery with a dual HTTPS/SMTP backend
Frontend: React, TypeScript, Vite, contract-first UI against a generated OpenAPI client
Architecture: domain-driven seams, dependency inversion, closed-schema invariant design, ADRs, idempotent upgrade-in-place data merges
Testing & quality: pytest, deterministic offline testing with fakes and fixtures, contract/drift tests, LLM eval harnesses, ruff linting
Tooling & delivery: Typer CLIs, Typst PDF generation, single-service Railway deployment with production hardening (`docs/deploy-railway.md`, `docs/adr/0002-...md`, `docs/adr/0008-...md`, `docs/adr/0009-...md`)
