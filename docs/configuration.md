# Environment configuration

`resume-agent` loads process settings from environment variables and then from
the repository-root `.env` file. Copy `.env.example` to `.env` for local use;
hosted deployments should set the same names in the platform environment.

This page is the complete reference for the environment-backed fields in
`resume_agent.config.Settings`. Blank values mean that the integration or
override is disabled. Boolean values accept the normal Pydantic settings forms,
including `true` and `false`. Restart the API and workers after changing a
setting because process settings are cached.

The Docker image intentionally overrides four local defaults:
`BROWSER_ENABLED=false`, `SECURE_COOKIES=true`, `DISABLE_API_DOCS=true`, and
`REGISTRATION_MODE=open`.

## LLM providers and models

| Variable | Default | Accepted values and purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | empty | Shared Anthropic credential. Bare model IDs route to Anthropic. |
| `OPENAI_API_KEY` | empty | Shared OpenAI credential for `openai:` model IDs and optional embeddings. |
| `GEMINI_API_KEY` | empty | Shared Google Gemini credential for `gemini:` model IDs. |
| `DEEPSEEK_API_KEY` | empty | Shared DeepSeek credential for `deepseek:` model IDs. |
| `CHEAP_MODEL` | `claude-haiku-4-5` | Model used for inexpensive extraction and classification work. |
| `MID_MODEL` | `claude-sonnet-5` | Model used for intermediate reasoning and review work. |
| `PREMIUM_MODEL` | `claude-opus-5` | Model used for the highest-quality writing and escalation paths. |
| `CHEAP_REASONING_EFFORT` | unset | Optional provider-specific reasoning setting for the cheap tier. |
| `MID_REASONING_EFFORT` | unset | Optional provider-specific reasoning setting for the mid tier. |
| `PREMIUM_REASONING_EFFORT` | unset | Optional provider-specific reasoning setting for the premium tier. |
| `TRANSCRIBE_MODEL` | `gemini:gemini-3.5-flash-lite` | Model used by audio transcription. |
| `PROMPT_CACHE_ENABLED` | `true` | Enables supported providers' static system-prompt cache. |
| `LLM_CONCURRENCY` | `8` | Maximum LLM fan-out; integer at least 1. |
| `LLM_RETRIES` | `2` | Structured/provider retry count; non-negative integer. |
| `LLM_RETRY_DELAY` | `1` | Base retry delay in seconds; non-negative integer. |

Model IDs can use `openai:`, `gemini:`, or `deepseek:` prefixes. A bare model
ID uses Anthropic. Reasoning-effort strings are deliberately provider-specific;
leave them unset unless the selected provider/model documents support for the
chosen value.

## API, storage, and runtime

| Variable | Default | Accepted values and purpose |
| --- | --- | --- |
| `DB_URL` | `sqlite:///data/resume_agent.db` | SQLAlchemy database URL. The supported Railway topology uses one SQLite replica and one persistent volume. |
| `API_TOKEN` | empty | Optional bearer token for scripts in hosted mode. Local mode ignores API/account authentication. |
| `BROWSER_ENABLED` | `true` | Enables browser-backed connectors. The Docker image sets this to `false`. |
| `STREAM_ENABLED` | `true` | Enables streamed conversational turns; `false` uses the blocking fallback. |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed browser origins. |
| `PULL_CONCURRENCY` | `4` | Concurrent connector fetches; integer at least 1. |
| `DETAIL_FETCH_CONCURRENCY` | `4` | Per-host detail-fetch workers; integer at least 1. |
| `SUGGESTION_BATCH_CONCURRENCY` | `3` | Suggestion worker lane size; integer from 1 through 16. |

## Hosted authentication, registration, and quotas

| Variable | Default | Accepted values and purpose |
| --- | --- | --- |
| `AUTH_USERNAME` | empty | Bootstrap administrator username in hosted mode. |
| `AUTH_PASSWORD_HASH` | empty | Bootstrap administrator password hash produced by `resume-agent hash-password`. |
| `SESSION_SECRET` | empty | Secret used to sign hosted sessions; use a long random value. |
| `AUTH_EMAIL` | empty | Optional verified email assigned to the bootstrap administrator. |
| `APP_BASE_URL` | empty | Canonical public origin used for OAuth callbacks and email links. Use HTTPS in production. |
| `ALLOWED_HOSTS` | empty | Comma-separated `Host` header allowlist. |
| `SECURE_COOKIES` | `false` | Forces secure session cookies. The Docker image sets this to `true`. |
| `DISABLE_API_DOCS` | `false` | Disables `/docs`, `/redoc`, and `/openapi.json`. The Docker image sets this to `true`. |
| `REGISTRATION_MODE` | `invite` | `closed`, `invite`, or `open`. The Docker image sets `open`. |
| `GLOBAL_DAILY_SIGNUP_LIMIT` | `50` | Platform-wide rolling daily verification-email limit; integer at least 1. |
| `GLOBAL_WEEKLY_TOKEN_BUDGET` | `50000000` | Legacy shared-key weekly token circuit breaker; non-negative integer, used while cost enforcement is in shadow mode. |
| `COST_QUOTA_ENFORCEMENT` | `shadow` | `shadow` dual-records USD while token enforcement remains active; `enforce` makes cost quotas authoritative. |
| `SPEND_GATE_TTL_SECONDS` | `30.0` | Seconds a spend decision may be reused; non-negative number, with `0` disabling reuse. |
| `GLOBAL_MONTHLY_COST_QUOTA_MICROS` | `500000000` | UTC calendar-month platform cap in USD micro-units; non-negative integer (`500000000` = USD 500). |
| `OPEN_SIGNUP_WEEKLY_TOKEN_BUDGET` | `250000` | Initial weekly token allowance for open-signup accounts; non-negative integer. |
| `OPEN_SIGNUP_MAX_ACTIVE_JOBS` | `100` | Initial active-job cap for open-signup accounts; non-negative integer. |
| `OPEN_SIGNUP_MAX_CONCURRENT_RUNS` | `1` | Initial concurrent-run cap for open-signup accounts; non-negative integer. |

See [Deploying to Railway](deploy-railway.md) for the production values that
must differ from local defaults, and [Cost quotas](cost-quotas.md) for quota
units and rollout behavior.

## Discovery and external sources

| Variable | Default | Accepted values and purpose |
| --- | --- | --- |
| `GITHUB_TOKEN` | empty | Optional GitHub token used for repository enrichment and API rate limits. |
| `ADZUNA_APP_ID` | empty | Adzuna connector application ID. |
| `ADZUNA_APP_KEY` | empty | Adzuna connector application key. |
| `LINKEDIN_EMAIL` | empty | Optional burner LinkedIn account email for browser-backed scraping. |
| `LINKEDIN_PASSWORD` | empty | Optional burner LinkedIn account password. |
| `LINKEDIN_USER_DATA_DIR` | `.linkedin_profile` | Browser profile directory that persists the LinkedIn session. |
| `SEARCH_MODE` | `auto` | `auto`, `native`, `tool`, or `off` for grounded advisor/source search. |
| `ADVISOR_MODEL` | empty | Advisor model override; blank falls back to `PREMIUM_MODEL`. |

## Skill taxonomy

| Variable | Default | Accepted values and purpose |
| --- | --- | --- |
| `CLUSTER_BATCH_SIZE` | `60` | First-pass taxonomy batch size; integer from 1 through 500. |
| `CLUSTER_RECONCILE_BATCH_SIZE` | `150` | Taxonomy reconciliation batch size; integer from 1 through 1000. |
| `DOMAINS_PER_CATEGORY_TARGET` | `12` | Soft domain-count target; integer from 3 through 50. The deprecated `DOMAINS_PER_CATEGORY_CAP` alias remains accepted for one compatibility release. |
| `SKILL_EMBEDDING_MODEL` | `openai:text-embedding-3-small` | Embedding model used to shortlist taxonomy candidates; lexical retrieval is the fallback. |
| `SKILL_EMBEDDING_BATCH_SIZE` | `256` | Embedding request/cache batch size; integer from 1 through 256. |
| `TAXONOMY_MAINTENANCE_MAX_CHURN` | `0.2` | Maximum maintenance churn ratio; number from 0.01 through 1.0. |
| `TAXONOMY_ESCALATION_MAX_SKILLS` | `300` | Maximum unresolved skills escalated per run; integer from 0 through 5000. |
| `TAXONOMY_PLACEMENT_FLOOR` | `true` | Places eligible unresolved skills into deterministic general categories; `false` restores historical unassigned behavior. |


## Career skills and H-1B enrichment

| Variable | Default | Accepted values and purpose |
| --- | --- | --- |
| `CAREER_SKILL_ROOT` | `skills` | Root directory containing approved local career-skill packages. |
| `CAREER_SKILL_MANIFEST` | `skills-lock.json` | Hash-pinned career-skill manifest. |
| `H1B_MCP_ENABLED` | `false` | Enables optional historical H-1B enrichment. |
| `H1B_MCP_TRANSPORT` | `stdio` | `stdio` or `streamable-http`. |
| `H1B_MCP_COMMAND` | empty | Required only for enabled `stdio`; `H1B_MCP_URL` must then be empty. |
| `H1B_MCP_URL` | empty | Absolute credential-free HTTP(S) URL required only for enabled `streamable-http`; command must then be empty. |
| `H1B_MCP_TIMEOUT_SECONDS` | `30` | MCP timeout in seconds; integer from 1 through 300. |
| `H1B_MCP_MAX_RESULT_CHARS` | `200000` | Maximum accepted tool-result characters; integer from 1000 through 1000000. |
| `H1B_CACHE_TTL_DAYS` | `30` | Company-cache lifetime; integer from 1 through 365 days. |
| `H1B_ENRICH_MAX_COMPANIES_PER_RUN` | `50` | Maximum uncached companies researched per run; non-negative integer, with `0` meaning unlimited. |

Historical H-1B data is an advisory signal only. It never confirms current
sponsorship policy and never hard-rejects a job.

## Gmail and platform mail

| Variable | Default | Accepted values and purpose |
| --- | --- | --- |
| `GOOGLE_OAUTH_CLIENT_ID` | empty | Platform Google OAuth Web application client used by web sign-in and Gmail. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | empty | Platform Google OAuth Web application secret. |
| `GMAIL_SYNC_INTERVAL_HOURS` | `6` | Hosted Gmail scheduler interval; non-negative integer, with `0` disabling the scheduler. |
| `FOLLOW_UP_DAYS` | `14` | Age at which stale-application reminders are proposed; non-negative integer, with `0` disabling reminders. |
| `GMAIL_MAX_MESSAGES` | `50` | Maximum recent messages read per sync/draft lookup; integer at least 1. |
| `RESEND_API_KEY` | empty | Resend HTTPS mail credential. When present, Resend wins over SMTP. |
| `MAIL_FROM` | empty | Backend-neutral sender address; falls back to `SMTP_FROM`. |
| `SMTP_HOST` | empty | SMTP server; blank selects the null mailer unless Resend is configured. |
| `SMTP_PORT` | `587` | SMTP port; integer from 1 through 65535. |
| `SMTP_USERNAME` | empty | SMTP authentication username. Blank skips SMTP authentication. |
| `SMTP_PASSWORD` | empty | SMTP authentication password. |
| `SMTP_FROM` | empty | SMTP sender and fallback for `MAIL_FROM`. |
| `SMTP_STARTTLS` | `true` | Enables SMTP STARTTLS. |

The local CLI Gmail flow uses `config/gmail_credentials.json` instead of the
platform OAuth variables. Railway plans below Pro block outbound SMTP; use the
Resend backend there unless the deployment plan supports SMTP egress.
