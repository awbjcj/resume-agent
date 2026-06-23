# Pull/Discover Lifecycle Refinement + JD Rendering — Design

**Date:** 2026-06-23
**Status:** Approved (design); pending implementation plan

## Problem

Five user-reported pain points, all rooted in how the discovery lifecycle and job
display behave today:

1. **JD rendering is unformatted.** The job modal dumps `jd_text` into a `<pre>`
   block. By the time text reaches the DB it is already flattened — connectors run
   `html_to_text` (`soup.get_text(separator="\n", strip=True)`), destroying every
   structural marker (no `-` for `<li>`, no heading level for `<h2>`, no emphasis).
2. **"Best-have" skills label** should read "Nice-to-have".
3. **Discover re-processes rejected jobs / doesn't clearly skip them.** Users want
   discover to only touch new, untracked jobs and to leave previously-rejected jobs
   alone unless deliberately asked.
4. **"Re-extract" and "Re-score" appear broken.** Root causes:
   - `backfill_rescore` ("Re-score") only writes SIC + location onto already-
     `shortlisted` jobs; it deliberately never recomputes `fit_score` or status — so
     editing `facts.json` produces no visible change.
   - `reextract` ("Re-extract") rewrites `criteria_json` but never re-runs
     filter/score, so the new fields never propagate to fit or status.
5. **Redundant re-work / duplicate leakage.** When `company` or `title` is missing,
   `compute_dedup_key` returns `None`; dedup falls back to exact-`jd_text` match only,
   so a re-pulled near-duplicate can slip in as a new `raw` row and get re-discovered.

## Decisions (resolved during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Re-evaluation model | **Explicit scoped reprocess** — discover stays incremental; a separate `reprocess` action does heavy re-evaluation. |
| 2 | Reconsidering rejected jobs | **By rejection reason** — requires a classifiable `reject_category`. |
| 3 | JD formatting source | **Markdown at ingest + frontend renderer (hybrid)** — high fidelity forward, graceful for legacy plain-text rows. |
| 4 | Command surface | **One `refresh` command/button + keep standalone `pull`/`discover`/`reprocess`.** |
| 5 | Dedup identity | **Stay location-agnostic** (`company\|title`) + add a content-fingerprint fallback and better title normalization. |

Unilateral calls confirmed with the user:
- **Delete** the broken `--reextract`/`--rescore` modes (do not keep as aliases).
- `reprocess` with no scope defaults to `shortlisted`.

## Non-goals (YAGNI)

- Multi-location row schema (one row listing all locations).
- LLM-based JD reformat pass.
- Re-fetching legacy postings to recover lost HTML structure.
- Any change to the tailoring / render pipeline.

---

## Workstream 1 — Lifecycle: incremental discover + scoped reprocess

The backbone. Three moves:

1. **Discover stays incremental.** `discover()` already processes only
   `status == raw`, so it inherently skips rejected/shortlisted jobs. Document this
   as the contract. Remove the misleading `--reextract`/`--rescore` modes from the
   CLI (`discover_cmd`) and the web `DiscoverDialog`.
2. **New `reprocess(session, scope, ...)` use-case** in `discovery/pipeline.py`,
   wrapped by `services/discovery.py`. Re-runs the **full** funnel
   (extract → filter → score) over a chosen scope and **may flip status and
   `fit_score`** — this is the real "re-score". It **never touches** progress-guarded
   jobs (`has_progress()` → status in {approved, tailored, rendered} OR any
   Application/ResumeVersion/CoverLetter child).
3. **Scope vocabulary** (`reprocess --scope X`, comma-separated / repeatable):
   - `shortlisted` — recompute fit on the current shortlist (default when no scope given).
   - `rejected:relevance` — reconsider off-target jobs (after broadening role anchors).
   - `rejected:filtered` — reconsider hard-constraint rejects (after editing search.yaml).
   - `all` — every non-progressed job.

**Mechanism:** `reprocess` resets each in-scope job to `raw` internally, then runs
the standard funnel so a single code path serves every scope. Rejected jobs only
re-enter when their reason-scope is explicitly named.

## Workstream 1b — Classifiable rejections (schema)

`reprocess --scope rejected:relevance` needs to know *why* a job was rejected.

- Add nullable `Job.reject_category` with values `"relevance" | "filtered"`.
- `run_filter` sets `reject_category="filtered"` alongside its existing `reject_reason`.
- `run_relevance` sets `reject_category="relevance"`.
- **Backfill migration** derives the category from existing `reject_reason` strings:
  reasons starting with `"off-target role:"` → `relevance`; all other non-null reject
  reasons → `filtered`. No agents are re-run.

## Workstream 2 — Dedup hardening

Identity stays `normalize(company)|normalize_title(title)` (location-agnostic — the
same role in two cities collapses to one row, keeping row count low). Two robustness
fixes:

1. **Title normalization** — extend `_normalize_title` with a small, conservative
   abbreviation map (`sr`→`senior`, `swe`→`software engineer`, `eng`→`engineer`, …)
   so cross-aggregator title variants collapse to one key.
2. **Content-fingerprint fallback** — add `Job.content_fingerprint` (nullable),
   computed at ingest from normalized `jd_text` (lowercased, whitespace-collapsed,
   hashed). When `dedup_key is None` (missing company/title), `find_existing` falls
   back to fingerprint match instead of only exact-text match, closing the
   near-duplicate leak.

## Workstream 3 — `refresh` command

New thin orchestrator: `refresh()` = `pull_jobs()` → `discover_jobs()` over the
newly-added raw rows → one combined report: `+N pulled · M shortlisted · K rejected`.

- CLI: `resume-agent refresh`.
- API/web: a **Refresh** action (one Run + SSE, identical plumbing to existing
  long-running ops via `RunManager`); a Refresh button in the web `RunActions`.
- `pull`, `discover`, and `reprocess` remain as standalone power commands.

## Workstream 4 — JD markdown rendering (hybrid)

1. **Ingest.** Add `html_to_markdown(raw)` (via `markdownify`, which rides the
   existing BeautifulSoup dependency) preserving `#` headings, `-` bullets,
   `**bold**`. Connectors that currently call `html_to_text` on HTML payloads switch
   to it. Plain-text API connectors (Google/Tesla JSON) are unaffected. `jd_text`
   now stores markdown — still readable to the extract/fit/fact-check agents, so no
   parallel field and no data migration.
2. **Frontend.** Replace the `<pre>` in `JobModal.tsx` with a `react-markdown`
   renderer plus a `prettifyPlainText()` preprocessor that gives legacy flat-text
   rows best-effort paragraph/bullet structure. One renderer handles both eras.

## Workstream 5 — Nice-to-have rename

Purely cosmetic:
- `SkillMatrix.tsx` label `"Best-have"` → `"Nice-to-have"`.
- Stale `"best-have"` comments in `SkillMatrix.tsx` and `JobCard.tsx`.
- The data field is already `nice_to_have_skills`; the `required` boolean and `+`
  chip marker are unchanged.

---

## Data model / migration

Two additive nullable columns on `Job`:
- `reject_category: str | None`
- `content_fingerprint: str | None`

One backfill migration: derive `reject_category` from `reject_reason`; compute
`content_fingerprint` for rows whose `dedup_key` is null. No data loss.

## Testing (all offline; agents + connectors faked per existing fixtures)

- **Lifecycle** (`test_discovery_pipeline.py`): `reprocess` flips fit/status for
  in-scope jobs; never touches progress-guarded jobs; rejected excluded unless
  reason-scoped; default scope = `shortlisted`.
- **Dedup** (`test_discovery_ingest.py`): abbreviation variants collapse to one key;
  a keyless near-duplicate collapses via fingerprint instead of inserting.
- **Markdown:** `html_to_markdown` preserves list/heading structure; plain-text
  input passes through unchanged.
- **Contract** (`test_openapi_contract.py`): new `reprocess`/`refresh` run modes
  regenerate `openapi.json` → `api.ts`.
- **Frontend** (Vitest): markdown renders bullets/headings; `prettifyPlainText`
  structures a flat sample.

## Risks / verification points

- **Markdown in `jd_text`** shifts `is_materially_richer` word counts (`#`/`-` count
  as tokens) and breaks exact-`jd_text` dedup across the plaintext→markdown
  transition. `dedup_key` / `content_fingerprint` must carry dedup through it —
  explicit test required.
- **`markdownify`** is a new (pure-Python, BeautifulSoup-based) dependency — add to
  `pyproject.toml`.
- **Abbreviation expansion** in title normalization risks over-collapsing distinct
  roles — keep the map small and conservative.

## Sequencing

Six loosely-coupled, independently-shippable workstreams:
schema (1b) → lifecycle (1) → dedup (2) → refresh (3) → markdown (4) → rename (5).
