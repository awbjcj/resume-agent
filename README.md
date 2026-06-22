# Resume Agent

A personal, command-line job-hunt pipeline. It pulls job posts from multiple
sources (job-board connectors, LinkedIn, or hand-pasted), scores them against a
**fact-locked** profile of _your_ real experience, helps you tailor a resume
through a panel of reviewer agents, drafts a matching cover letter, renders both
to PDF, and tracks every application — auto-syncing statuses from your Gmail —
all on your own machine, in one SQLite database.

The guiding rule is **fact-lock**: every bullet on a tailored resume must trace
back to a fact you actually provided. The agents rewrite and reframe; they never
invent.

---

## How it works

Jobs flow through a funnel. Each stage has one command that advances it, and two
points where _you_ (not the agent) make the call.

```
              ┌─ pull ───┐
  connectors  │          │
  LinkedIn    │  scrape  │
  paste       └─ addjob ─┘
                   │
                   ▼
   raw ─▶ extracted ─▶ filtered ─▶ shortlisted ──▶ approved ─▶ tailored ─▶ rendered
                          │            ▲   │            ▲           │
                       rejected     discover         👤 you      cover-letter
                                  (extract + score)  approve     (fact-locked)

   then track the application:  ready ─▶ submitted ─▶ interview ─▶ offer / rejected / closed
                                              ▲
                                         sync-status (Gmail proposes the moves)
```

| Stage            | Command                      | What happens                                                                                                                                              |
| ---------------- | ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Ingest**       | `pull` / `scrape` / `addjob` | Raw jobs land in the DB (deduped by URL or JD text). `pull` runs every enabled job-board connector; `scrape` drives LinkedIn; `addjob` takes one by hand. |
| **Discover**     | `discover`                   | Agents extract structured criteria, apply your hard filters, and score fit → `shortlisted`.                                                               |
| **👤 Approve**   | dashboard or `approve`       | The cost gate: you approve only the jobs worth paying to tailor.                                                                                          |
| **Tailor**       | `tailor`                     | A writer agent drafts a fact-locked resume; a reviewer panel critiques and a reviser loops until it passes.                                               |
| **Cover letter** | `cover-letter`               | Drafts a fact-locked cover letter per job, gated by a deterministic provenance check, and renders it to PDF.                                              |
| **Render**       | `render`                     | A chosen resume version becomes a PDF in `output/`.                                                                                                       |
| **👤 Track**     | dashboard / `sync-status`    | Log submission status and notes by hand, or let `sync-status` read Gmail and **propose** status moves for you to apply.                                   |

---

## Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management
- An **LLM provider key** — the discover, tailor, and cover-letter steps default to **Claude**, so an **Anthropic API key** works out of the box. You can instead (or additionally) use **OpenAI**, **Google Gemini**, or **DeepSeek** — see [LLM providers](#env--secrets-and-models)
- _Optional:_ a **GitHub token** (enriches your profile from your repos)
- _Optional:_ a **burner LinkedIn account** (only needed for `scrape`)
- _Optional:_ **job-board connector keys** for `pull` — e.g. [Adzuna API](https://developer.adzuna.com/) credentials (Greenhouse and RemoteOK need no key)
- _Optional:_ **Gmail OAuth credentials** (only needed for `sync-status`; read-only access — see [Gmail setup](#gmail-setup-for-sync-status))

---

## Setup

```bash
# 1. Install dependencies into a managed virtualenv
uv sync

# 1a. (Recommended) Run the guided setup wizard instead of hand-editing config
uv run resume-agent setup

# 2. Install the browser the scraper drives (only needed if you'll use `scrape`)
uv run playwright install chromium

# 3. Configure secrets
cp .env.example .env          # then edit .env and fill in ANTHROPIC_API_KEY

# 4. Create your config files from the examples (drop the .example suffix)
cp config/profile_sources.yaml.example config/profile_sources.yaml
cp config/search.yaml.example          config/search.yaml
cp config/review.yaml.example          config/review.yaml
cp config/render.yaml.example          config/render.yaml
cp config/style_guide.md.example       config/style_guide.md   # optional: house writing style
cp config/connectors.yaml.example      config/connectors.yaml   # only if you'll use `pull`
```

> **Windows PowerShell:** use `Copy-Item .env.example .env` instead of `cp`.

`resume-agent setup` walks you through secrets, search criteria, and connectors, then writes `.env` and `config/*.yaml` for you — the manual steps below are the alternative.

Everything else (the SQLite database, the `output/` and `data/` folders) is
created automatically on first run.

### Gmail setup (for `sync-status`)

`sync-status` reads your inbox **read-only** to propose application-status
updates. It authenticates with a Google OAuth client — there is no password in
`.env`:

1. In the [Google Cloud console](https://console.cloud.google.com/), create (or
   reuse) a project, enable the **Gmail API**, and create an **OAuth client ID**
   of type _Desktop app_.
2. Download the client-secret JSON and save it as `config/gmail_credentials.json`.
3. The first `sync-status` run opens a browser consent screen once; the granted
   token is cached to `data/gmail_token.json` (git-ignored) and reused after that.

Skip this entirely if you'd rather track statuses by hand in the dashboard.

All commands below are shown as `uv run resume-agent …`. If you'd rather not
prefix every call, activate the venv first (`source .venv/bin/activate`, or
`.venv\Scripts\Activate.ps1` on Windows) and drop the `uv run`.

---

## Quickstart — the happy path

```bash
# 1. Build your fact-lock profile from your resume (+ optional GitHub)
uv run resume-agent profile build

# 2. Get some jobs into the pipeline (pick one)
uv run resume-agent pull --limit 10            # job-board connectors, or…
uv run resume-agent scrape --limit 10          # LinkedIn, or…
uv run resume-agent addjob --company "Acme" --title "Backend Engineer" --jd-file jd.txt

# 3. Score them against your profile and your search criteria
uv run resume-agent discover
uv run resume-agent match-gap                 # optional: see missing high-demand skills

# 4. Review the shortlist and approve the keepers (opens the dashboard)
uv run resume-agent dashboard

# 5. Tailor every approved job, and draft matching cover letters
uv run resume-agent tailor --approved
uv run resume-agent cover-letter --approved

# 6. Render a specific resume version to PDF (id shown in the dashboard)
uv run resume-agent render 12

# 7. Track submissions back in the dashboard
uv run resume-agent dashboard

# 8. Later, let Gmail propose status updates (review first, then apply)
uv run resume-agent sync-status               # lists proposals only
uv run resume-agent sync-status --apply        # applies them
```

---

## Command reference

Run `uv run resume-agent --help` for the full list, or `… <command> --help` for
any single command. Every command accepts `--db-url` to point at a different
database (handy for testing).

### `profile build` — create your fact-lock profile

Reads your resume (and GitHub, if configured) into `data/profile/facts.json`.
This file is the **ground truth** every later step is allowed to draw from.

```bash
uv run resume-agent profile build [--sources config/profile_sources.yaml] [--out data/profile/facts.json] [--refresh]
```

`--refresh` rebuilds the file and **discards any manual edits** — otherwise the
command refuses to overwrite an existing `facts.json`.

### `addjob` — add one job by hand

The job description is read from `--jd-file`, or from stdin if you omit it.

```bash
uv run resume-agent addjob --company "Acme" --title "Backend Engineer" --url "https://…" --jd-file jd.txt
```

Duplicates (same URL or identical JD text) are detected and skipped.

### `scrape` — pull jobs from LinkedIn

Searches LinkedIn using your `search.yaml`, then ingests matching posts as raw
jobs. **First run:** a real browser window opens — log in to your burner account
by hand _once_. The session is saved to `.linkedin_profile/` and reused after
that.

```bash
uv run resume-agent scrape [--search config/search.yaml] [--limit 25]
```

`--limit` caps how many postings are processed this run (be a polite scraper).

### `pull` — pull jobs from job-board connectors

Runs every connector enabled in `connectors.yaml`, dedupes results into `raw`
jobs, and prints a per-source count. When a higher-priority (canonical) source
re-finds a job already in the DB from an aggregator, it **upgrades** the stored
URL and JD text in place rather than dropping the duplicate — the pull summary
shows `+N added, N upgraded`. Secrets (e.g. Adzuna keys) come from `.env`;
which boards/sources to hit come from `connectors.yaml`.

| Connector | What it needs |
| --- | --- |
| `greenhouse` | Board tokens in `connectors.yaml` |
| `lever` | Board slugs in `connectors.yaml` |
| `adzuna` | `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` in `.env` |
| `remoteok` | Nothing — open API |
| `linkedin` | Burner credentials in `.env` (same as `scrape`) |
| `companies` | Careers URLs in `connectors.yaml` — auto-detects Greenhouse, Lever, Ashby, Workday, Tesla, Google |

```bash
uv run resume-agent pull [--connectors config/connectors.yaml] [--search config/search.yaml] [--limit 25]
```

`--limit` caps postings **per connector** this run. If `config/connectors.yaml`
is missing, the command tells you to copy it from the example first.

### `sources` — connector run history

Shows each connector's last run: when it ran, how many jobs it added, and the
last error (if any). A quick health check after `pull`.

```bash
uv run resume-agent sources
```

### `discover` — extract, filter, and score

Runs the funnel over every `raw` job already in the DB: extracts structured
criteria, drops anything failing your hard filters, and assigns each survivor a
0–100 fit score with a rationale → `shortlisted`.

```bash
uv run resume-agent discover [--search config/search.yaml] [--facts data/profile/facts.json]
```

### `match-gap` — target-job skills your profile does not show

Compares the `must_have_skills` of every job that survived discovery
(`shortlisted` / `approved` / `tailored` / `rendered`) against your profile's
skill names and aliases. Gaps are ranked by how many target jobs demand them.
This is read-only: it never edits `facts.json`.

```bash
uv run resume-agent match-gap                 # aggregate, most-demanded first
uv run resume-agent match-gap --job-id 7      # gaps for one target job
uv run resume-agent match-gap --llm           # optional synonym pass, e.g. k8s/Kubernetes
```

### `approve` — the cost gate (CLI alternative to the dashboard)

Marks a shortlisted job `approved` so it's eligible for tailoring.

```bash
uv run resume-agent approve 7
```

### `tailor` — draft + review loop

Tailors one job (`--job-id`) or every approved job (`--approved`). Each round is
saved as a `ResumeVersion`; the reviewer panel runs until a draft passes or
`max_rounds` is hit. The **fact-check** reviewer is a hard gate. Optional
`config/style_guide.md` prose is appended beneath the fixed fact-lock rules for
the writer, reviser, and reviewers.

```bash
uv run resume-agent tailor --approved
uv run resume-agent tailor --job-id 7
```

### `cover-letter` — draft a fact-locked cover letter

Writes a cover letter for one job (`--job-id`) or every approved job
(`--approved`), then renders it to a PDF in `output/`. A writer agent drafts only
from your `facts.json`; a **deterministic provenance gate** checks that every
paragraph cites real fact ids and loops a reviser until the draft is clean (or
`fact_check_passed=False` is recorded so you know not to send it). Lower-stakes
than `tailor`, so there's no reviewer panel — just the gate.

```bash
uv run resume-agent cover-letter --approved
uv run resume-agent cover-letter --job-id 7
```

### `render` — version → PDF

Renders a stored resume version (by id) through the Typst template into
`output/`. Filenames are unique per version, so re-rendering never clobbers an
earlier PDF.

```bash
uv run resume-agent render 12 [--config config/render.yaml]
```

### `dashboard` — the visual control room

Launches the Streamlit app with four views:

- **Shortlist** — fit scores + rationales, with an _Approve for tailoring_ button.
- **Pipeline board** — every job by stage, with its PDF download, review
  critiques, and an editable application status + notes.
- **Analytics** — response / interview / offer rates sliced by **source** and by
  **fit-score band**, so you can see which connectors and which scores actually
  convert.
- **Match-gap** — skills your target jobs demand that your profile does not
  show, ranked by frequency.

```bash
uv run resume-agent dashboard [--db-url …]
```

### `sync-status` — let Gmail propose status updates

Scans recent inbox mail (read-only), matches each message to a tracked
application by company, classifies it (rejection / interview / assessment /
offer) with deterministic rules plus an optional cheap-LLM fallback, and
**proposes** forward-only status moves. Nothing changes until you re-run with
`--apply` — statuses are never flipped silently. Requires
[Gmail setup](#gmail-setup-for-sync-status).

```bash
uv run resume-agent sync-status                 # list proposals only
uv run resume-agent sync-status --apply         # apply them
uv run resume-agent sync-status --max-results 100
```

---

## API server

The same pipeline is exposed over HTTP for the future React/shadcn frontend (and
any API client):

```bash
uv run resume-agent serve                       # http://127.0.0.1:8000
uv run resume-agent serve --host 0.0.0.0 --port 8080
```

- Interactive docs at `/docs`; the OpenAPI schema at `/openapi.json`.
- The committed contract the frontend consumes lives in `contracts/`
  (`openapi.json` + generated `ts/api.ts`); regenerate with
  `bash scripts/gen_ts_client.sh` after any schema change.
- Long operations (`POST /api/discover|pull|tailor|cover-letters|jobs/from-url`)
  return a **run** you watch via `GET /api/runs/{id}/events` (Server-Sent Events)
  or poll at `GET /api/runs/{id}`.
- Set `API_TOKEN` in `.env` to require an `Authorization: Bearer <token>` on every
  route except `/api/health`; set `CORS_ORIGINS` (comma-separated) for your
  frontend dev server. Both are off-by-default-friendly for local single-user use.

Deferred (not yet exposed over HTTP): Gmail `sync-status`, analytics, match-gap,
`profile build`, LinkedIn `scrape`.

---

## Configuration

### `.env` — secrets and models

Copied from `.env.example`. Loaded automatically.

| Key                                    | Purpose                                                                      |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| `ANTHROPIC_API_KEY`                    | Powers `discover`, `tailor`, and `cover-letter` with Claude (the default).   |
| `OPENAI_API_KEY`                       | Optional; needed only if a model tier is prefixed `openai:`.                 |
| `GEMINI_API_KEY`                       | Optional; needed only if a model tier is prefixed `gemini:`.                 |
| `DEEPSEEK_API_KEY`                     | Optional; needed only if a model tier is prefixed `deepseek:`.               |
| `GITHUB_TOKEN`                         | Optional; enriches `profile build`.                                          |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`     | Optional; enable the Adzuna connector for `pull`.                            |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | Burner credentials for `scrape`.                                             |
| `LINKEDIN_USER_DATA_DIR`               | Where the logged-in browser session is cached (default `.linkedin_profile`). |
| `DB_URL`                               | Database location (default `sqlite:///data/resume_agent.db`).                |

#### Choosing an LLM provider

Every LLM call resolves through one of three model tiers — `CHEAP_MODEL`,
`MID_MODEL`, `PREMIUM_MODEL` — which default to Claude Haiku / Sonnet / Opus. A
model id is **provider-prefixed**: a bare id stays on Anthropic, while an
`openai:`, `gemini:`, or `deepseek:` prefix routes that tier to another provider.
Each tier uses its own provider's key, so you can mix providers freely:

```bash
CHEAP_MODEL=gemini:gemini-2.0-flash     # cheap extract/fit/relevance on Gemini
MID_MODEL=deepseek:deepseek-chat        # reviewers / cover-letter reviser on DeepSeek
PREMIUM_MODEL=claude-opus-4-8           # bare id → Anthropic for the tailor writer
```

Set only the keys for the providers you actually use; a provider's SDK is loaded
lazily, so a Claude-only run never touches the OpenAI or Gemini libraries.

> **Gmail** uses an OAuth client file (`config/gmail_credentials.json`), not an
> `.env` key — see [Gmail setup](#gmail-setup-for-sync-status).

### `config/*.yaml`

| File                   | Controls                                                                                                                                                      |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `profile_sources.yaml` | Path to your resume and your GitHub username.                                                                                                                 |
| `search.yaml`          | Keywords, titles, locations, and **hard filters** (salary, years of experience, remote policy, sponsorship).                                                  |
| `connectors.yaml`      | Which job-board connectors `pull` runs and their parameters (Greenhouse board tokens, Lever slugs, Adzuna country, RemoteOK, LinkedIn on/off, and `companies.urls` for direct ATS/portal URLs — Greenhouse, Lever, Ashby, Workday, Tesla, Google). Secrets stay in `.env`. |
| `review.yaml`          | The reviewer roster, their weights/model tiers, `max_rounds`, `score_threshold`, optional `length_budget` one-page guidance, and optional `style_guide_path`. |
| `render.yaml`          | Typst `template_path` and the PDF `output_dir`.                                                                                                               |
| `style_guide.md`       | Optional house-style prose appended to the resume tailor loop. Governs how resumes are written, never what is claimed. Missing or empty means no change.      |

Each `*.yaml.example` is annotated — copy it, then edit.

The cover-letter and resume templates live in `templates/` (`cover_letter.typ`,
`resume.typ`) and can be edited directly. `config/gmail_credentials.json` (for
`sync-status`) is the one config file with no example — it's the OAuth
client-secret you download from Google Cloud (see [Gmail setup](#gmail-setup-for-sync-status)).

### Source priority

When the same job is seen by multiple connectors, a **canonical** source always
wins over an **aggregator** copy:

| Tier | Sources |
| --- | --- |
| **Canonical** (higher priority) | `greenhouse`, `lever`, `ashby`, `workday`, `tesla`, `google`, `companies`, `url` (hand-pasted) |
| **Fallback** (lower priority) | `adzuna`, `remoteok`, `linkedin` |

**First-seen-wins** among equal-tier sources — no churn from same-tier re-pulls.

**Upgrade, not drop.** If a canonical source re-finds a job previously ingested
from a fallback source, the stored posting fields (`url`, `jd_text`, `source`,
`title`, `location`) are upgraded in place, keeping the same `Job` id. Your
tailored resumes, cover letters, and application status are never touched.

Once a job's status has advanced past `raw`, only the canonical apply `url` is
updated (the JD text is frozen so a resume already tailored to it is not
silently re-based).

---

## Where things live

| Path                                                  | Contents                                                                         |
| ----------------------------------------------------- | -------------------------------------------------------------------------------- |
| `data/resume_agent.db`                                | All jobs, resume versions, cover letters, and applications (SQLite).             |
| `data/profile/facts.json`                             | Your fact-lock profile.                                                          |
| `data/connector_runs.json`                            | Per-connector run history that `sources` reads.                                  |
| `data/gmail_token.json`                               | Cached Gmail OAuth token for `sync-status` (git-ignored).                        |
| `output/`                                             | Rendered resume **and** cover-letter PDFs (cover letters are suffixed `cl<id>`). |
| `.linkedin_profile/`                                  | Cached LinkedIn browser session (git-ignored).                                   |
| `config/gmail_credentials.json`                       | Your Gmail OAuth client secret (git-ignored; you provide it).                    |
| `templates/resume.typ` / `templates/cover_letter.typ` | The Typst templates the renderers use.                                           |

`data/`, `output/`, `.env`, `.linkedin_profile/`, and `config/gmail_credentials.json`
are all git-ignored.

---

## A note on scraping responsibly

`scrape` is built for **personal, low-volume** use against a **burner** account:
it drives a real logged-in browser, paces its requests deliberately, and caps
how much it pulls per run. Keep `--limit` modest and don't point it at an account
you care about. Manual `addjob` is always available if you'd rather skip scraping.

The `companies` connector's Workday backend issues one detail request per
surviving job listing — keep the relevance filters in `search.yaml` tight so the
title-gate prunes the list before detail fetches begin.

---

## Development

```bash
uv run pytest              # run the full test suite
uv run pytest -k scraper   # run a subset
ruff check                 # lint
```

Tests are pure and offline — agents and the browser are faked, so the suite needs
no API key and no network. Connector backends are tested against fixture JSON
payloads captured from real responses.

v1.5 keeps the tailor loop synchronous. Parallel reviewer panels and job-level
concurrency are deferred while this pass reduces cost through leaner prompts.
