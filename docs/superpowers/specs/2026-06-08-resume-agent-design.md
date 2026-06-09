# Resume Agent — Design Spec

- **Date:** 2026-06-08
- **Status:** Approved (design) — ready for implementation planning
- **Scope of this document:** Full v1 design + memo for v2–v4

---

## 1. Overview

A single-user, personal tool that automates the front of a job hunt: it **discovers** jobs, **tailors** a resume to each one (multi-agent review for quality *and* truthfulness), **renders** a PDF, and **tracks** every application — stopping just before submission so the human reviews and clicks "submit" themselves.

It is **not** a product, not multi-tenant, and not an auto-submitter (in v1). It is optimized for one person's job hunt.

### Primary goal
Turn "hundreds of raw postings" into "a handful of well-matched jobs, each with a truthful, tailored, ATS-parseable PDF resume, all tracked in one place" — with minimal cost and minimal manual drudgery, while keeping a human in control of what actually gets submitted.

---

## 2. Decisions (resolved during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Audience | **Personal single-user tool** (tuned to the user's profile; no auth/multi-tenancy) |
| 2 | Automation boundary | **Stop before submit** — produce tailored PDF + tracked entry; human submits |
| 3 | Job sources (v1) | **LinkedIn first** (scrape via burner account); Indeed deferred to v2 |
| 4 | Scrape model | **Burner LinkedIn account**, persistent logged-in browser profile |
| 5 | Sponsorship | **Hard requirement.** Inferred from JD prose. `silent` ⇒ flag (keep), `denied` ⇒ reject, `offered` ⇒ keep |
| 6 | Resume ground truth | **Existing resume file + GitHub profile only** (the "fact-lock"), captured **comprehensively** |
| 7 | PDF rendering | **Typst, single-column**, ATS-parseable; content as structured data, never LLM-authored markup |
| 8 | LLM usage | **Mixed by stage** — cheap model for bulk extraction/scoring; premium for tailoring + key reviewers |
| 9 | Tracking | **SQLite (source of truth) + Streamlit dashboard** |
| 10 | Multi-agent framework | **Agno** (`Agent` / `Team` / `Workflow` / `SqliteDb`) |
| 11 | Orchestration | **Hybrid** — Agno `Workflow` owns the tailor→review→revise core; a Typer CLI + plain Python drive deterministic stages |
| 12 | Cover letters | **Deferred to v2** |
| 13 | Tailoring stance | **Truthful but keyword-aware** (surface real matches; never keyword-stuff or fabricate) |

---

## 3. Cross-cutting principles

These apply to every component and must survive into the implementation.

### 3.1 Fact-Lock (anti-fabrication)
The rewriter may **select, reorder, and rephrase** facts; it may **never invent**. Enforcement:
- `ProfileFacts` (built once, human-edited) is the *only* allowed source of claims.
- Every generated claim-bearing resume item carries a **`provenance`** pointer to the source fact ID. Bullets and selected skills carry their own pointers; section-level items such as experiences and projects carry a pointer to the source record.
- A dedicated **Fact-Check reviewer** is a *hard gate*: any claim not traceable to a fact fails the round regardless of other scores. Provenance makes this partially verifiable in plain code before any LLM runs.

### 3.2 Extensibility of fields & text
Schemas must grow without breaking stored data.
- **Schema is the single source of truth.** Pydantic models define fields once; extraction/tailoring prompts are generated from each model's JSON schema + field `description`s. Add a field → it flows into both LLM instructions and structured output automatically (no duplicated field lists).
- **JSON columns, not rigid tables.** `criteria_json`, `content_json`, `critique_json`, and `facts.json` are JSON blobs. Only stable scalars (`status`, `company`, `fit_score`, …) get indexed columns. Adding a field = **zero DB migration**.
- **`schema_version`** stamped on every stored JSON object for explicit future migration.
- **Optional fields with defaults** so existing records stay valid as schemas grow.
- **`extra: dict`** escape hatch on each model for experimental fields before promotion to first-class.
- **Config-driven behavior:** filter dimensions (`search.yaml`) and the reviewer roster (`review.yaml`) are config, so extending them is mostly declarative.

### 3.3 Resumability (SQLite as the seam)
Each stage reads rows in one status and writes rows in the next. Any stage can be re-run in isolation — when the scraper breaks, fix and re-run *only* discovery; already-paid-for tailoring is untouched.

### 3.4 Cost funnel
Cheap LLM screens many jobs; the human approves ~10; premium LLM + the Agno review panel only ever touch the approved few. The human checkpoint sits **before** the expensive step on purpose.

---

## 4. Architecture (v1)

```
   ┌────────────────────────────────────────────────────────────┐
   │  FACT-LOCK: resume + GitHub → parsed ONCE → ProfileFacts    │
   │  (facts.json, human-edited, authoritative)                  │
   └───────────────────────────────┬────────────────────────────┘
                                    │
 [1] DISCOVERY  (deterministic + cheap LLM)
   LinkedIn scrape (Playwright, burner account)
     → clean / dedupe
     → cheap-LLM EXTRACT structured fields (JobCriteria)
     → deterministic HARD filter (sponsorship: silent ⇒ flag, not reject)
     → cheap-LLM FIT-SCORE + rank vs ProfileFacts
     → shortlist ───────────────►  SQLite: jobs (status=shortlisted)
                                    │
        ⏸  HUMAN CHECKPOINT — review shortlist in Streamlit, approve which to tailor
                                    │
 [2] TAILOR + REVIEW  (Agno Workflow — premium models)
   approved job + ProfileFacts
     → Tailor agent → draft ResumeContent (fact-locked, provenance-tagged)
     → Review TEAM (parallel): fact-check · ATS-keyword · recruiter · hiring-mgr · concision
     → aggregate structured critiques (fact-check = hard gate)
     → Reviser agent → loop until (fact-check pass AND score≥threshold) OR max_rounds
     → final ResumeContent ──────►  SQLite: resume_versions
                                    │
 [3] RENDER  (deterministic)
   ResumeContent + Typst template → compile → PDF ──► /output + path in SQLite
                                    │
 [4] TRACK  (Streamlit + SQLite)
   dashboard: job · status · fit-score · PDF link · dates. Human submits externally + marks it.
```

---

## 5. Components

### 5.1 `profile/` — Fact-Lock

The fact-lock captures **everything** available from the resume and GitHub, so any present or future tailoring has the full fact set to draw from. Every atomic fact (bullet, project, skill, …) carries a stable **`id`** (for provenance) and a **`source`** (`resume | github | manual`).

- **`ProfileFacts`** (Pydantic), comprehensive and extensible (`schema_version` + `extra` at every level):
  - **`contact`** — name, headline, email, phone, location (city/region/country), `willing_to_relocate`, **`work_authorization`** (sponsorship need — also feeds the sponsorship filter), links (website, LinkedIn, GitHub, Twitter/X, Scholar, other[]).
  - **`summary`** — professional summary / objective.
  - **`experience[]`** — company, title, employment_type, location, start, end/current, `bullets[]` (each with `id`), `tech[]`, quantified achievements.
  - **`education[]`** — institution, degree, field, start, end, GPA, honors[], relevant_coursework[], activities[].
  - **`projects[]`** — name, description, role, `tech[]`, url, repo_url, highlights[], dates, GitHub repository metadata when applicable (`stars`, `forks`, languages, topics, homepage, last-updated, `is_fork`), `source`.
  - **`skills`** — categorized open-ended map (languages, frameworks, tools, cloud, databases, soft-skills, …) whose values are skill facts with `id`, `source`, `name`, optional aliases/context, not bare strings.
  - **`certifications[]`** — name, issuer, date, credential_id, url.
  - **`publications[]`** — title, venue, date, authors, url.
  - **`awards[]`** — name, issuer, date, description.
  - **`languages[]`** — spoken language + proficiency.
  - **`volunteer[]`** — org, role, dates, description.
  - **`github_profile`** — profile-level GitHub signals (bio, followers, public repos, account age, top languages, total stars), when GitHub ingest is enabled.
  - **`interests[]`**, plus `extra` for anything not modeled.
- **Resume parser:** extract text (`pypdf` / `python-docx`) → cheap-LLM structures into the full `ProfileFacts` (all sections above).
- **GitHub ingest (comprehensive):** GitHub API → profile (bio, followers, public_repos, account age, top languages, total stars) + **all notable public repos** (name, description, stars, forks, primary + all languages, topics, homepage, last-updated, is_fork) + READMEs → cheap-LLM summarizes each repo into a `projects[]` entry (`source=github`) and stores profile-level signals in `github_profile`.
- **Output:** `data/profile/facts.json`, **human-editable and authoritative**. Generated once via `profile build`; the user corrects/augments it; everything downstream trusts it.

### 5.2 `discovery/` — the funnel
- **`config/search.yaml`:** keywords, titles, locations, remote pref, min salary, YoE range, `sponsorship_required: true`.
- **LinkedIn scraper** (Playwright, persistent logged-in burner profile): reuses one saved session, human-like pacing, rate-limited. Result cards → detail pages → full JD text → `jobs` (`status=raw`).
  - **Manual-assist fallback:** `addjob <url|->` lets the user feed a URL or paste a JD; the pipeline continues from extraction. A broken scraper never blocks the user.
  - Scraper sits **behind an interface** so its HTML-parsing logic is testable against saved fixtures.
- **Clean/dedupe:** normalize; dedupe by (company, title, JD-hash).
- **Extract** (cheap LLM → **`JobCriteria`**): `sponsorship_signal (offered|denied|silent)`, `yoe_min`, `salary_range`, `remote_policy`, `location`, `must_have_skills[]`, `schema_version`, `extra`.
- **Hard filter** (deterministic): apply `search.yaml`. Sponsorship rule as in Decision #5. **Rejected rows are kept with a `reject_reason`** for auditing/calibration.
- **Fit-score** (cheap LLM): 0–100 vs `ProfileFacts` + rationale → rank → `status=shortlisted`.

### 5.3 `tailor/` — Agno tailor + review (centerpiece)
An **Agno `Workflow`** (premium models), run once per *approved* job. Input: `JobCriteria` + JD text + `ProfileFacts`.

1. **Tailor agent** (`output_schema=ResumeContent`): selects/reorders/rephrases `ProfileFacts` to the JD; injects must-have keywords only where a real fact supports it; targeted summary. Each claim-bearing output item carries a `provenance` fact ID.
2. **Review `Team`** (parallel members, each `output_schema=ReviewCritique{score, issues[], suggestions[]}`):

   | Agent | Role | Model tier |
   |---|---|---|
   | **Fact-Check** 🚦 | Every claim must trace to a `ProfileFacts` ID. Unsupported → **blocking** | premium |
   | **ATS-Keyword** | JD must-have keywords present & in context | mid |
   | **Recruiter** | 6-second scan: impact, clarity, formatting | mid |
   | **Hiring-Manager** | Technical credibility, project relevance | premium |
   | **Concision/Style** | One page, active voice, quantified, no fluff | mid |

3. **Aggregator** → one structured verdict. Fact-Check is a **hard gate**; the rest combine into a weighted score.
4. **Reviser agent** → applies suggestions, re-emits `ResumeContent`. Loop until *(fact-check passes AND aggregate ≥ threshold)* OR `max_rounds` (default **3**). Every iteration stored in `resume_versions`.

- Reviewer roster + weights + threshold + `max_rounds` live in **`config/review.yaml`** (registry, not hardcoded). Adding a reviewer = one config entry + an Agno `Agent`.

### 5.4 `render/` — Typst (deterministic, no LLM)
- `templates/resume.typ` — single-column, ATS-parseable. `ResumeContent` passed as JSON via Typst `sys.inputs` (or temp data file read with `json()`); `typst compile` → PDF.
- Output: `output/{company}_{role}_{date}.pdf`; path stored on the resume version.
- Template selectable via `config/render.yaml`. Restyling never requires an LLM call.

### 5.5 `tracking/` — SQLite + Streamlit
**Two separated status lifecycles:**
- `jobs.status` (our pipeline): `raw → extracted → filtered|rejected → shortlisted → approved → tailored → rendered`
- `applications.status` (employer funnel): `ready → submitted → interview → offer → rejected|closed`

**Tables** (SQLModel; scalars indexed, extensible data in JSON + `schema_version`):
- `jobs`(id, source, url, company, title, location, jd_text, **criteria_json**, fit_score, fit_rationale, status, reject_reason, schema_version, created_at)
- `resume_versions`(id, job_id, round, **content_json**, pdf_path, review_score, fact_check_passed, **critique_json**, schema_version, created_at)
- `applications`(id, job_id, resume_version_id, status, submitted_at, notes, updated_at)

**Streamlit (two pages):**
1. **Shortlist** — the human checkpoint: shortlisted jobs with fit score, rationale, sponsorship flag; checkbox → `status=approved`.
2. **Pipeline board** — group by status, open PDF, read JD + critiques, edit application status/notes.

### 5.6 Orchestration / CLI (`cli.py`, Typer)
```
resume-agent profile build [--refresh]   # resume + GitHub → facts.json
resume-agent discover                     # scrape → clean → extract → filter → score → shortlist
resume-agent addjob <url|->               # manual-assist fallback
resume-agent tailor --approved            # Agno workflow over approved jobs
resume-agent render <version_id>          # ResumeContent → PDF
resume-agent dashboard                    # launch Streamlit
```
Config: `.env` (API keys, GitHub token, burner LinkedIn creds), `config/{search,profile_sources,review,render}.yaml`.

---

## 6. Project layout
```
src/resume_agent/
  models/      # ProfileFacts, JobCriteria, ResumeContent, ReviewCritique (+ schema_version, extra)
  profile/     # resume parse + github ingest
  discovery/   # scraper, clean, extract, filter, score
  tailor/      # Agno workflow: tailor + review Team + reviser
  render/      # Typst rendering
  tracking/    # SQLModel tables + repository fns
  dashboard/   # Streamlit app
  config.py  db.py  cli.py
config/  (search.yaml · profile_sources.yaml · review.yaml · render.yaml)
templates/resume.typ   ·   data/   ·   output/   ·   tests/
```

---

## 7. Tech stack
- **Runtime:** Python 3.13, `uv`.
- **Core deps:** `agno`, `anthropic` + `openai` (model providers), `pydantic`, `playwright`, `typer`, `streamlit`, `sqlmodel`, `httpx`, `PyGithub`, `pypdf`, `python-docx`, `typst`, `pyyaml`, `tenacity`, `rich`.
- **Dev:** `pytest`, `ruff`.

Component implementation plans may add these dependencies incrementally. The Foundation plan installs only the shared-spine dependencies it directly needs.

---

## 8. Testing strategy
- **Deterministic stages** (filter, dedupe, provenance check) — unit-tested with fixtures.
- **LLM stages** — schema-validation + golden-file tests.
- **Fact-check adversarial test** — inject a fabricated bullet → assert it is blocked.
- **Scraper** — behind an interface; parser tested against saved HTML fixtures (no live scrape in CI).

---

## 9. Risks
- **LinkedIn anti-bot / DOM churn** — highest-risk component. Mitigated by burner account, persistent profile, human-like pacing, and the manual-assist fallback. Expect periodic parser maintenance.
- **Burner account restriction** — accepted; no loss of real identity.
- **LLM cost** — controlled by the cost funnel + human checkpoint before premium steps.
- **Fabrication** — controlled by fact-lock + provenance + fact-check gate; covered by adversarial tests.

---

## 10. Roadmap (memo for later phases)
- **v1 (this spec):** LinkedIn discovery → shortlist checkpoint → Agno tailor+review → Typst PDF → SQLite + Streamlit tracker. Manual submit.
- **v2:** Indeed scraper; Gmail auto-status (parse rejection/interview/OA emails); Greenhouse/Lever/Ashby ATS JSON as a reliable source backbone; cover-letter generation.
- **v3:** Semi-auto form-fill via Playwright for the friendliest ATS (Greenhouse/Lever); human clicks submit.
- **v4:** Full auto-submit for select ATS; response-rate analytics; A/B-test resume strategies.
