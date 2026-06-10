# Resume Agent

A personal, command-line job-hunt pipeline. It scrapes or ingests job posts,
scores them against a **fact-locked** profile of *your* real experience, helps
you tailor a resume through a panel of reviewer agents, renders a PDF, and
tracks every application — all on your own machine, in one SQLite database.

The guiding rule is **fact-lock**: every bullet on a tailored resume must trace
back to a fact you actually provided. The agents rewrite and reframe; they never
invent.

---

## How it works

Jobs flow through a funnel. Each stage has one command that advances it, and two
points where *you* (not the agent) make the call.

```
                  ┌─ scrape ─┐
  LinkedIn / paste│          │
                  └─ addjob ─┘
                       │
                       ▼
   raw ─▶ extracted ─▶ filtered ─▶ shortlisted ──▶ approved ─▶ tailored ─▶ rendered
                          │            ▲   │            ▲
                       rejected     discover         👤 you approve
                                  (extract + score)  (dashboard / approve)

   then track the application:  ready ─▶ submitted ─▶ interview ─▶ offer / rejected / closed
```

| Stage | Command | What happens |
|-------|---------|--------------|
| **Ingest** | `scrape` / `addjob` | Raw jobs land in the DB (deduped by URL or JD text). |
| **Discover** | `discover` | Agents extract structured criteria, apply your hard filters, and score fit → `shortlisted`. |
| **👤 Approve** | dashboard or `approve` | The cost gate: you approve only the jobs worth paying to tailor. |
| **Tailor** | `tailor` | A writer agent drafts a fact-locked resume; a reviewer panel critiques and a reviser loops until it passes. |
| **Render** | `render` | A chosen version becomes a PDF in `output/`. |
| **👤 Track** | dashboard | Log submission status, notes, and download the PDF. |

---

## Prerequisites

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management
- An **Anthropic API key** (the discover and tailor steps call Claude)
- *Optional:* a **GitHub token** (enriches your profile from your repos)
- *Optional:* a **burner LinkedIn account** (only needed for `scrape`)

---

## Setup

```bash
# 1. Install dependencies into a managed virtualenv
uv sync

# 2. Install the browser the scraper drives (only needed if you'll use `scrape`)
uv run playwright install chromium

# 3. Configure secrets
cp .env.example .env          # then edit .env and fill in ANTHROPIC_API_KEY

# 4. Create your config files from the examples (drop the .example suffix)
cp config/profile_sources.yaml.example config/profile_sources.yaml
cp config/search.yaml.example          config/search.yaml
cp config/review.yaml.example          config/review.yaml
cp config/render.yaml.example          config/render.yaml
```

> **Windows PowerShell:** use `Copy-Item .env.example .env` instead of `cp`.

Everything else (the SQLite database, the `output/` and `data/` folders) is
created automatically on first run.

All commands below are shown as `uv run resume-agent …`. If you'd rather not
prefix every call, activate the venv first (`source .venv/bin/activate`, or
`.venv\Scripts\Activate.ps1` on Windows) and drop the `uv run`.

---

## Quickstart — the happy path

```bash
# 1. Build your fact-lock profile from your resume (+ optional GitHub)
uv run resume-agent profile build

# 2. Get some jobs into the pipeline (pick one)
uv run resume-agent scrape --limit 10          # LinkedIn, or…
uv run resume-agent addjob --company "Acme" --title "Backend Engineer" --jd-file jd.txt

# 3. Score them against your profile and your search criteria
uv run resume-agent discover

# 4. Review the shortlist and approve the keepers (opens the dashboard)
uv run resume-agent dashboard

# 5. Tailor every approved job
uv run resume-agent tailor --approved

# 6. Render a specific resume version to PDF (id shown in the dashboard)
uv run resume-agent render 12

# 7. Track submissions back in the dashboard
uv run resume-agent dashboard
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
by hand *once*. The session is saved to `.linkedin_profile/` and reused after
that.

```bash
uv run resume-agent scrape [--search config/search.yaml] [--limit 25]
```
`--limit` caps how many postings are processed this run (be a polite scraper).

### `discover` — extract, filter, and score
Runs the funnel over every `raw` job already in the DB: extracts structured
criteria, drops anything failing your hard filters, and assigns each survivor a
0–100 fit score with a rationale → `shortlisted`.

```bash
uv run resume-agent discover [--search config/search.yaml] [--facts data/profile/facts.json]
```

### `approve` — the cost gate (CLI alternative to the dashboard)
Marks a shortlisted job `approved` so it's eligible for tailoring.

```bash
uv run resume-agent approve 7
```

### `tailor` — draft + review loop
Tailors one job (`--job-id`) or every approved job (`--approved`). Each round is
saved as a `ResumeVersion`; the reviewer panel runs until a draft passes or
`max_rounds` is hit. The **fact-check** reviewer is a hard gate.

```bash
uv run resume-agent tailor --approved
uv run resume-agent tailor --job-id 7
```

### `render` — version → PDF
Renders a stored resume version (by id) through the Typst template into
`output/`. Filenames are unique per version, so re-rendering never clobbers an
earlier PDF.

```bash
uv run resume-agent render 12 [--config config/render.yaml]
```

### `dashboard` — the visual control room
Launches the Streamlit app with two views:
- **Shortlist** — fit scores + rationales, with an *Approve for tailoring* button.
- **Pipeline board** — every job by stage, with its PDF download, review
  critiques, and an editable application status + notes.

```bash
uv run resume-agent dashboard [--db-url …]
```

---

## Configuration

### `.env` — secrets and models
Copied from `.env.example`. Loaded automatically.

| Key | Purpose |
|-----|---------|
| `ANTHROPIC_API_KEY` | **Required** for `discover` and `tailor`. |
| `GITHUB_TOKEN` | Optional; enriches `profile build`. |
| `LINKEDIN_EMAIL` / `LINKEDIN_PASSWORD` | Burner credentials for `scrape`. |
| `LINKEDIN_USER_DATA_DIR` | Where the logged-in browser session is cached (default `.linkedin_profile`). |
| `DB_URL` | Database location (default `sqlite:///data/resume_agent.db`). |

Model tiers are also configurable via env (`CHEAP_MODEL`, `MID_MODEL`,
`PREMIUM_MODEL`) and default to Claude Haiku / Sonnet / Opus.

### `config/*.yaml`
| File | Controls |
|------|----------|
| `profile_sources.yaml` | Path to your resume and your GitHub username. |
| `search.yaml` | Keywords, titles, locations, and **hard filters** (salary, years of experience, remote policy, sponsorship). |
| `review.yaml` | The reviewer roster, their weights/model tiers, `max_rounds`, and `score_threshold`. |
| `render.yaml` | Typst `template_path` and the PDF `output_dir`. |

Each `*.yaml.example` is annotated — copy it, then edit.

---

## Where things live

| Path | Contents |
|------|----------|
| `data/resume_agent.db` | All jobs, resume versions, and applications (SQLite). |
| `data/profile/facts.json` | Your fact-lock profile. |
| `output/` | Rendered resume PDFs. |
| `.linkedin_profile/` | Cached LinkedIn browser session (git-ignored). |
| `templates/resume.typ` | The Typst resume template the renderer uses. |

`data/`, `output/`, `.env`, and `.linkedin_profile/` are all git-ignored.

---

## A note on scraping responsibly

`scrape` is built for **personal, low-volume** use against a **burner** account:
it drives a real logged-in browser, paces its requests deliberately, and caps
how much it pulls per run. Keep `--limit` modest and don't point it at an account
you care about. Manual `addjob` is always available if you'd rather skip scraping.

---

## Development

```bash
uv run pytest          # run the full test suite
uv run pytest -k scraper   # run a subset
```

Tests are pure and offline — the agents and the browser are faked, so the suite
needs no API key and no network.
