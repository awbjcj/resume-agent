# Resume Agent v2 — Multi-Connector Job Sourcing + Quality-of-Life — Design Spec

- **Date:** 2026-06-11
- **Status:** Approved (design) — ready for implementation planning
- **Scope of this document:** Full v2 design. Builds on the v1 spec (`2026-06-08-resume-agent-design.md`, §10 roadmap memo).
- **Successor planning:** one spec → phased, independently-executable component plans (mirrors v1's spec→multi-plan pattern).

---

## 1. Overview

v1 shipped a single-user job-hunt pipeline with **LinkedIn** as its only real source and a manual `addjob` fallback. v2 turns job sourcing into a **connector framework** that treats API sources, feed sources, and scrapers as equal citizens, adds several concrete connectors across different job markets, and layers on three quality-of-life capabilities (cover letters, Gmail auto-status, application analytics) plus the ease-of-use commands the multi-connector world demands (`pull`, `sources`).

### Primary goal
Widen and harden job intake — from "one brittle scraper" to "several reliable sources behind one seam" — **without multiplying the LinkedIn-style maintenance tax**, and without letting the same posting from multiple sources leak through the cost funnel into paid tailoring twice. Then close two loops the human currently does by hand: writing cover letters and updating application status from email.

### Non-goals (unchanged from v1)
Not a product, not multi-tenant, not an auto-submitter. Still stops before submit; the human stays in control of what is submitted and of any application-status change.

---

## 2. Decisions (resolved during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | What "different job markets" means | **Stable official/ATS APIs *and* more platforms** — reliability + breadth, not international geography (deferred) |
| 2 | Connector interface | **One-shot `Connector.fetch(search) -> list[RawJob]`** — collapse the v1 two-phase `search()`+`fetch_jd()`; `RawJob` carries its own `source` |
| 3 | ATS targeting | **Curated company watchlist** (board tokens) for company-scoped ATS boards **+ one keyword aggregator** for the wide net |
| 4 | Cross-source dedup | **Normalized `(company, title)` key** as a third dedup signal beside URL + JD-hash; canonical copy preferred via **connector ordering**, not merge logic |
| 5 | Widening beyond ATS + aggregator | **Feed-first** — reliable feeds/JSON as API connectors; **no new Playwright scrapers in v2**; LinkedIn stays the sole scraper |
| 6 | New capabilities in v2 | **Cover-letter generation · Gmail auto-status · Application analytics** (match-gap report → v3) |
| 7 | Ease-of-use in v2 | **Unified `pull` command · connector health (`sources`)** (dashboard dedup-merge UI not needed — auto-merge; init wizard → v3) |
| 8 | v2 packaging | **One design spec → phased component plans** |
| 9 | Aggregator choice | **Adzuna** (free keyed API, broad coverage); **Remotive** keyless as fallback |
| 10 | v2-core reference connectors | **Greenhouse + Adzuna + RemoteOK** (one per kind); Lever/Ashby/WWR/HN are copy-the-reference siblings, framework-supported but not all gated on v2 |
| 11 | Gmail safety stance | **`sync-status` proposes** transitions; human confirms in dashboard — never silently flips status |

---

## 3. Cross-cutting principles (inherited + extended)

These v1 principles carry forward and constrain every v2 component:

- **Fact-Lock** (§3.1 v1) — extends to cover letters: a cover letter may select/reorder/rephrase `ProfileFacts`, never invent. The fact-check gate applies.
- **Extensibility** (§3.2 v1) — new structured data rides in JSON columns + `extra`; only stable scalars get indexed columns (the new `dedup_key` is the one scalar v2 adds). `schema_version` stamped on new JSON objects.
- **Resumability** (§3.3 v1) — connectors only ever write `jobs(status=raw)`; everything downstream is unchanged, so a broken connector never blocks the rest of the pipeline.
- **Cost funnel** (§3.4 v1) — v2's dedup is, in effect, a cost-funnel guard: duplicates dropped at intake never reach paid tailoring.

### 3.5 New: connector isolation
Each connector is a self-contained unit answering "what market does it cover, how is it configured, what does it depend on." It is **pre-bound to its own params** and depends only on the shared `SearchConfig` (for client-side filtering) and `RawJob` (its output). A connector failing — bad token, API down, DOM churn — is caught by the runner, logged to connector telemetry, and skipped; other connectors and the rest of the pipeline proceed.

---

## 4. Architecture (v2)

```
  config/connectors.yaml + companies.yaml + .env
                 │  (which connectors enabled + per-connector params + secrets)
                 ▼
        build_connectors() → [ Connector ]   each pre-bound to its params
                 │
 [0] PULL  (resume-agent pull)
     for connector in ORDER(ATS → feeds → aggregator → LinkedIn):
         raw_jobs = connector.fetch(SearchConfig)      # client-side keyword filter
         ingest_jobs(session, raw_jobs)                # normalize + dedupe (url|jd-hash|dedup_key)
     → per-source counts table         ──►  SQLite: jobs (status=raw, source=<connector>)
     connector telemetry (last run, added, last error)  ──► state file / connector_runs
                 │
 [1..4] DISCOVER → APPROVE → TAILOR → RENDER  (UNCHANGED from v1)
                 │
 [+] COVER-LETTER  (resume-agent cover-letter)   fact-locked draft → light review → Typst → PDF
 [+] SYNC-STATUS   (resume-agent sync-status)    Gmail read → match → classify → PROPOSE transitions
 [+] ANALYTICS     (dashboard page)              jobs ⋈ applications → rates by source / fit-band
```

The v1 funnel (discover/approve/tailor/render/track) is untouched. v2 adds a sourcing **stage 0** in front of it and three **leaf** capabilities hanging off the existing data.

---

## 5. Components

### 5.1 Connector framework (backbone)

**Interface** — replaces the v1 `JobSource` protocol and `ScrapedCard`:

```python
class Connector(Protocol):
    name: str
    def fetch(self, search: SearchConfig) -> list[RawJob]: ...

@dataclass
class RawJob:
    source: str            # carried by the job itself → fixes the v1 source="linkedin" bug
    url: str | None
    company: str | None
    title: str | None
    location: str | None
    jd_text: str
```

- **Construction:** `build_connectors(connectors_cfg, settings) -> list[Connector]` instantiates only **enabled** connectors, each pre-bound to its params (board tokens, API keys, feed URLs) and any secrets. Disabled or unauthenticated connectors are omitted (not errored).
- **Ingest:** a new `ingest_jobs(session, raw_jobs: Iterable[RawJob]) -> dict[str,int]` replaces `ingest_scraped`. It routes every `RawJob` through the existing `add_job` (normalize/dedupe/insert) using `raw.source`, and returns per-source added counts. `ingest_scraped` is removed; the LinkedIn path no longer hardcodes a source.
- **LinkedIn refactor:** `LinkedInScraper` is adapted to implement `Connector.fetch` — internally it still does its two HTTP steps (search page → detail pages) and reuses the **unchanged** pure parsers + fixtures. Only the outer method shape changes.

### 5.2 Connector roster + configuration

Three query models, all behind `Connector`:

| Kind | v2-core | Siblings (framework-supported) | Query model | Auth |
|------|---------|-------------------------------|-------------|------|
| **ATS (company-scoped)** | **Greenhouse** | Lever, Ashby | iterate `companies.yaml` board tokens → fetch each board's postings → filter by `SearchConfig` keywords/titles client-side | none (public boards) |
| **Aggregator (keyword)** | **Adzuna** | Remotive (keyless) | `SearchConfig` keywords + location → API search | `.env`: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` |
| **Feed (keyword/remote)** | **RemoteOK** (JSON) | WeWorkRemotely (RSS), HN Who's-Hiring (Algolia) | fetch feed → map → filter by `SearchConfig` | none |
| **Scraper** | LinkedIn (refactored) | — | existing | burner session |

Endpoints (reference):
- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`
- Lever: `https://api.lever.co/v0/postings/{company}?mode=json`
- Ashby: `https://api.ashbyhq.com/posting-api/job-board/{company}`
- Adzuna: `https://api.adzuna.com/v1/api/jobs/{country}/search/{page}?app_id=…&app_key=…&what=…`
- RemoteOK: `https://remoteok.com/api`

**Config split:**
- **`config/connectors.yaml`** — which connectors are enabled + per-connector params. ATS company tokens live here under each provider's section (functionally the "company watchlist"; a separate `companies.yaml` is optional sugar, same data). Example shape:
  ```yaml
  greenhouse:
    enabled: true
    boards: [stripe, airbnb, datadog]
  adzuna:
    enabled: true
    country: us
  remoteok:
    enabled: true
  linkedin:
    enabled: false      # opt-in; brittle
  ```
- **`.env`** — secrets only (`ADZUNA_APP_ID`/`ADZUNA_APP_KEY`, Gmail creds, existing keys).
- **`config/search.yaml` / `SearchConfig`** — unchanged role: the keyword/title/location/filter model every connector uses for client-side filtering. `SearchConfig` gains no source-specific fields (per-source params live in `connectors.yaml`).

### 5.3 Cross-source dedup

- **New scalar column** `jobs.dedup_key` (indexed). Populated at insert as `normalize(company) + "|" + normalize(title)`, where `normalize` lowercases, strips leading seniority tokens (`Sr.`, `Senior`, `Lead`, `Staff`, `Principal`), strips punctuation, and collapses whitespace. Null company *or* title ⇒ null `dedup_key` (skip this signal; fall back to URL/JD-hash).
- **`find_existing` extended** to check, in order: **URL → exact JD-hash → `dedup_key`**. First match ⇒ duplicate ⇒ not inserted.
- **Canonical-copy preference via ordering, not merge:** `pull` runs connectors in a fixed order — **ATS → feeds → aggregator → LinkedIn** — so the fullest/canonical JD (ATS) lands first and first-wins dedup keeps it. No update-on-conflict code needed. (Aggregators truncate JD text; ATS gives canonical full text; running ATS first means the good copy wins.)
- **Migration:** existing DBs need a one-time `dedup_key` backfill (compute from stored company/title). The component plan ships a tiny backfill step; new DBs get the column from `create_all`.

### 5.4 Cover-letter generation (leaf)

- **Model:** `CoverLetterContent` (Pydantic, `schema_version` + `extra`) — greeting, opening hook, 2–3 body paragraphs each provenance-tagged to `ProfileFacts`, closing.
- **Flow:** `cover-letter --job-id N` (or `--approved`) → a tailor-style agent drafts fact-locked from `ProfileFacts` + JD → a **light review** (fact-check gate only; no 5-agent panel — cover letters are lower-stakes than the resume) → render via a new **`templates/cover_letter.typ`** → PDF in `output/`.
- **Storage:** new **`cover_letters`** table (`id`, `job_id` FK, `resume_version_id` FK nullable, `content_json`, `pdf_path`, `schema_version`, `created_at`).
- **Fact-lock:** the cover letter draws only from `ProfileFacts`; provenance pointers + the fact-check gate prevent fabrication, identical in spirit to the resume tailor.

### 5.5 Gmail auto-status (leaf)

- **Scope:** **read-only** Gmail API. Creds/token cache via `.env` + a local token file (git-ignored), like the LinkedIn session.
- **Flow:** `sync-status` → fetch recent messages → **match** each to an `applications` row by company name / sender domain heuristics → **classify** into `rejection | interview | OA | offer | none` via a **rules pre-filter** (keyword/sender patterns) with a **cheap-LLM** fallback for ambiguous mail → produce a list of **proposed** `ApplicationStatus` transitions.
- **Human gate:** proposals are surfaced in the dashboard (and echoed by the command); the human confirms before any status changes. The tool **never** silently flips status — consistent with v1's "human submits / human controls" boundary.
- **Testing:** classification + matching tested against **canned email fixtures**; no live Gmail in CI.

### 5.6 Application analytics (leaf)

- **What:** a new **dashboard page** joining `jobs` ⋈ `applications`: counts and **response / interview / offer rates** sliced by **source** and by **fit-score band** (e.g. 0–59 / 60–79 / 80–100). "Which connectors and which score bands actually convert."
- **How:** pure SQL/pandas aggregation over existing tables — **no LLM, no new tables**. Meaningfulness grows with tracked history; the page degrades gracefully on thin data (shows counts, flags low-n).

### 5.7 CLI / UX surface

| Command | Behavior |
|---------|----------|
| `pull` | Runs every **enabled** connector in canonical order, dedupes, prints a per-source added-count table. Supersedes `scrape`. |
| `scrape` | Kept as a thin back-compat alias that pulls only the LinkedIn connector. |
| `sources` | Connector health: each connector's last run time, jobs added, last error. |
| `cover-letter --job-id N \| --approved` | Draft + light-review + render a cover letter. |
| `sync-status` | Gmail read → propose application-status transitions (human confirms in dashboard). |
| `dashboard` | Adds the analytics page; surfaces `sync-status` proposals. |

### 5.8 Connector telemetry

Per-connector run records (last run timestamp, jobs added, last error string) drive `sources`. **Leaning a JSON state file** (e.g. `data/connector_runs.json`) over a DB table to avoid schema churn; a small `connector_runs` table is the alternative if querying/history is wanted. Final choice deferred to the component plan; either way it is written by `pull` and read by `sources`.

---

## 6. Data model changes

- `jobs`: **+ `dedup_key: str | None`** (indexed). Backfilled for existing DBs.
- **+ `cover_letters`** table (see §5.4).
- **Connector telemetry**: JSON state file (preferred) or small `connector_runs` table.
- `resume_versions`, `applications`: **unchanged** — analytics reads them as-is; Gmail writes only `applications.status` through the existing `update_application_status`.

---

## 7. Project layout (additions)

```
src/resume_agent/discovery/
  connectors/                 # NEW — the connector framework
    __init__.py
    base.py                   # Connector protocol + RawJob
    runner.py                 # build_connectors() + ORDER + pull orchestration
    greenhouse.py  adzuna.py  remoteok.py     # v2-core references
    lever.py  ashby.py  weworkremotely.py  hn.py   # siblings (copy-the-reference)
  scraper/linkedin.py         # MODIFY — implement Connector.fetch
  ingest.py                   # MODIFY — ingest_jobs() + dedup_key
src/resume_agent/cover_letter/   # NEW — model, agent, service
src/resume_agent/gmail/          # NEW — client (read-only), match, classify
src/resume_agent/dashboard/app.py  # MODIFY — analytics page + sync-status proposals
src/resume_agent/cli.py            # MODIFY — pull, sources, cover-letter, sync-status
config/connectors.yaml(.example)   # NEW
templates/cover_letter.typ         # NEW
tests/fixtures/{greenhouse,adzuna,remoteok,gmail}/   # NEW — saved payloads
```

The v1 `JobSource`/`ScrapedCard`/`ingest_scraped` are removed; their tests migrate to the `Connector`/`RawJob` shape.

---

## 8. Tech stack (additions)

- **`httpx`** (already a dep) for all API/feed connectors — no new scraping deps.
- **`feedparser`** for RSS feeds (WeWorkRemotely) — small new dep, only if/when the RSS sibling lands.
- **Google API client** (`google-api-python-client` + `google-auth-oauthlib`) for read-only Gmail — new deps, scoped to the Gmail leaf.
- **`pandas`** (likely already present via Streamlit) for analytics aggregation.
- No new browser/scraping dependencies (feed-first).

---

## 9. Testing strategy

- **Every connector's mapping is a pure function over a saved fixture** — JSON payloads (Greenhouse/Adzuna/RemoteOK) and RSS/HTML for feed/scraper siblings — mirroring v1's LinkedIn HTML-fixture pattern. **No network in CI.** Live calls are manual-calibration tasks (like the scraper's Task 6).
- **Dedup** — `normalize()` and the extended `find_existing` get deterministic unit tests. The headline test is **"same job from three sources (ATS + aggregator + LinkedIn) → one row, canonical JD kept."**
- **`ingest_jobs`** — fake connectors return `RawJob`s; assert per-source counts and correct `source` attribution (regression test for the v1 hardcode bug).
- **Cover letter** — schema-validation + an adversarial fact-check test (inject an unsupported claim → blocked), reusing the resume fact-check harness.
- **Gmail** — matching + classification against canned email fixtures; assert transitions are **proposed**, not applied.
- **Analytics** — aggregation correctness on a seeded jobs/applications fixture, incl. the low-n / empty-history degradation.

---

## 10. Build sequence (what `writing-plans` will emit)

Strict spine, then independent leaves:

1. **Connector framework** — `Connector`/`RawJob`, `ingest_jobs`, dedup (`dedup_key` + `find_existing` + `normalize` + backfill), `connectors.yaml`, and LinkedIn refactored onto the seam. (No new sources yet; LinkedIn must keep working through the new interface.)
2. **Reference connectors** — Greenhouse, Adzuna, RemoteOK (each fixture-tested; siblings are copy-the-reference).
3. **`pull` + `sources`** — unified ordered run + connector telemetry/health.
4. **Cover letters** · 5. **Gmail auto-status** · 6. **Analytics** — independent leaves, any order after (3).

(1)→(2)→(3) is a hard dependency chain; (4)/(5)/(6) depend only on (3) and on existing v1 data.

---

## 11. Risks

- **API churn / rate limits** — ATS and aggregator schemas can change and some rate-limit. Mitigated by fixture-tested mappers (fast to recalibrate), per-connector isolation (one failing source is skipped), and `sources` health surfacing breakage early.
- **Adzuna key/limits** — free tier has call caps; Remotive (keyless) is the fallback. Connector skipped cleanly if unauthenticated.
- **Cross-source dedup false negatives** — title variations the normalizer misses → an occasional duplicate. Accepted at single-user volume; the "deterministic now, LLM adjudicator later" path stays open (v3).
- **Gmail matching precision** — wrong email→application matches could propose bad transitions; mitigated by the human-confirm gate (proposals never auto-apply) and read-only scope.
- **Fabrication in cover letters** — controlled by fact-lock + provenance + the fact-check gate, covered by the adversarial test.

---

## 12. Explicitly deferred (v3 memo)

- **Match-gap report** (`JobCriteria.must_have_skills` − `ProfileFacts.skills`).
- **Dashboard source-filter + manual dedup-merge UI** (auto-merge covers v2).
- **Interactive `init` setup wizard.**
- **More scrapers** (Indeed / Wellfound / Dice) and **international boards** (Reed / StepStone / Naukri).
- **LLM-assisted cross-source dedup adjudicator.**
- **Semi-auto form-fill / response-rate A-B testing** (v3/v4 per the v1 roadmap).
