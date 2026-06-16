# Job Metadata Extraction, Visualization & Filtering — Design

**Date:** 2026-06-16
**Status:** Approved (design); pending implementation plan
**Surface:** `discovery/` (extraction), `dashboard/` (Shortlist + Pipeline), `tracking/` (queries), connectors (posting date)

---

## 1. Problem & Goal

The pipeline already extracts structured job metadata into `JobCriteria` (salary,
location, remote policy, sponsorship, YoE, skills) and stores it as `criteria_json`
on each `Job`, plus an LLM `fit_score`. **None of this is surfaced for filtering or
ranking** — the Shortlist shows fit + sponsorship + location only, hard-sorted by
fit, with no interactive controls.

**Goal:** turn the Shortlist into a real decision surface — extend the extracted
metadata, visualize it, and let the user filter, rank, and select the most ideal
job by multiple factors (metadata + profile-match score) with skills as
first-class, profile-aware filter tags.

This is two things, both in scope:
1. **Extend extraction** — add new metadata fields.
2. **Surface & act** — visualize, filter, and rank in the dashboard.

---

## 2. Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| New metadata fields | seniority, employment type, tech stack, industry/domain, company size/stage |
| Posting date | Yes — from **source metadata** (connector/scrape), not JD text |
| Data layer | **In-memory** filtering (Approach A) — no SQL columns for criteria fields |
| Ranking model | **Hard filters + single sort key**, with **composite** as an optional sort mode |
| "Profile-match score" | The existing LLM `fit_score` (no new deterministic match metric) |
| Skill filter logic | **OR** by default (job matches if it requires ANY selected skill) |
| Skill tag source | **Both** must-have and nice-to-have (nice-to-haves styled distinctly) |
| Skill chip cross-reference | **Yes** — colour chips by profile coverage |
| Chip encoding | **All 3 channels**: colour = coverage, border = must/nice (+ `+` prefix on nice), oxblood ring = active filter |
| Filter/control home | **Layout B** — full-width "control desk" strip below the masthead; sidebar stays nav-only |
| Shortlist card density | **Rich** (more signal — it's the decision surface) |
| Pipeline board | **Lean** — one compact meta line; no chips, no filters |
| Composite weights | **Named presets**: Balanced / Pay-first / Freshest |
| Composite normalization | fit 0–100 as-is; salary capped at ≈$250k → 100; recency linear decay over ~30d |
| Composite null handling | **Neutral/median** — missing factor does not penalize |
| Backfill | **Add a re-extract path** so existing jobs gain the new fields |

---

## 3. Architecture

Four layers, each independently testable. Data flows:

```
connectors ──(posted_at)──┐
                          ▼
JD text ─▶ extract agent ─▶ JobCriteria (criteria_json) ─┐
                                                         ▼
                          Job row {criteria_json, fit_score, posted_at}
                                                         │
                                  tracking/queries (in-memory load) ─▶ ShortlistRow*
                                                         │
                                  dashboard/filtering.py (pure: filter, sort, rank, coverage)
                                                         │
                                  dashboard/pages.py (control desk + cards)
```

### 3.1 Extraction layer (`discovery/`, `models/job.py`)

**`JobCriteria` gains five fields** (all `| None`, stored in `criteria_json` — no
DB migration needed because it's a JSON blob):

```python
class Seniority(str, Enum):
    junior = "junior"; mid = "mid"; senior = "senior"; staff = "staff"; principal = "principal"

class EmploymentType(str, Enum):
    full_time = "full_time"; contract = "contract"; internship = "internship"; part_time = "part_time"

# added to JobCriteria:
seniority: Seniority | None = None
employment_type: EmploymentType | None = None
tech_stack: list[str] = Field(default_factory=list)   # concrete technologies
industry: str | None = None                            # fintech, healthcare, …
company_size: str | None = None                        # startup | scaleup | enterprise (free-ish, normalized in prompt)
```

`discovery/extract.py` instructions extended to pull these, keeping the existing
"use only what the text supports; leave unknown fields null" rule (medium-signal
fields will frequently be null — handled downstream).

### 3.2 Posting date (`Job.posted_at`, connectors, ingest)

- **`Job` gains `posted_at: datetime | None`** (a real column — source-derived,
  naturally columnar, used for sorting). This is the one schema migration.
- **`RawJob` gains `posted_at: datetime | None = None`.**
- Each connector populates it from its own response where available:
  - Greenhouse, Adzuna, RemoteOK — parse the API date field.
  - LinkedIn scrape — parse relative "N days/hours ago" into an absolute datetime.
  - `addjob` and any source without a date → stays `None`.
- `ingest.add_job` / `ingest_jobs` thread `posted_at` through to the `Job`.
- Null is expected and absorbed by the composite's neutral rule and by the recency
  sort (nulls sort last).

### 3.3 Re-extract path (backfill)

`discover --reextract` (CLI flag): re-runs the extract agent over jobs that already
moved past `raw` (so existing shortlisted/approved jobs gain the new fields) and
re-writes `criteria_json`. Does **not** re-score fit or change status. Honest cost
note: this re-calls the extraction model for each targeted job.

### 3.4 Data access (`tracking/queries.py`)

`ShortlistRow` is widened to carry the full criteria the UI needs, plus
`posted_at`, plus per-skill profile coverage. The page never touches `criteria_json`
shape directly — the query flattens it:

```python
@dataclass
class SkillTag:
    name: str
    covered: bool          # normalize_skill(name) in profile_tokens
    required: bool         # True = must-have, False = nice-to-have

@dataclass
class ShortlistRow:
    job_id: int
    company: str | None; title: str | None; location: str | None
    fit_score: int | None; fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: int | None; salary_max: int | None; salary_currency: str | None
    remote_policy: str | None
    seniority: str | None; employment_type: str | None
    industry: str | None; company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTag]           # must + nice, coverage-tagged
```

Profile tokens come from `match_gap.profile_skill_tokens(load_facts(...))` — reused,
not reimplemented. If `facts.json` is absent, every skill is `covered=False` (graceful).

### 3.5 Filtering / ranking (`dashboard/filtering.py` — NEW, pure)

A new pure module (no Streamlit) so all the logic is unit-testable:

```python
@dataclass
class FilterState:
    salary_min: int | None = None
    remote: set[str] = ...           # subset of {remote, hybrid, onsite}
    sponsorship: set[str] = ...
    seniority: set[str] = ...
    employment_type: set[str] = ...
    industry: set[str] = ...
    fit_min: int | None = None
    skills: set[str] = ...            # OR semantics, normalized
    sort: str = "fit"                # fit | salary | recency | composite
    preset: str = "balanced"         # balanced | pay_first | freshest

def apply_filters(rows, state) -> list[ShortlistRow]: ...
def sort_rows(rows, state) -> list[ShortlistRow]: ...
def composite_score(row, preset) -> float: ...
def available_skill_cloud(rows) -> list[SkillTag]:  # union across rows, coverage-tagged
```

**Filter semantics:**
- All non-skill filters AND together (salary AND remote AND seniority …).
- Skill tags OR within themselves: a row passes if it requires **any** selected skill.
- A `None` metadata value is **not excluded** by a filter on that field unless the
  filter explicitly targets "unknown" (default: unknown rows pass — don't hide a
  job for failing to publish salary). Exception: `salary_min` excludes a row only
  when the row's `salary_max` is known and below the floor (mirrors existing
  `filter.apply_filters` behavior).

**Composite math** (`composite_score`):
- `fit_n` = `fit_score` or neutral 50 if None.
- `salary_n` = `min(salary_max or salary_min, 250_000) / 250_000 * 100`, or neutral 50 if both None.
- `recency_n` = `max(0, 100 - (age_days / 30 * 100))`, or neutral 50 if `posted_at` None.
- Presets (weights sum to 1):
  - **Balanced** — fit .50 / salary .30 / recency .20
  - **Pay-first** — fit .30 / salary .55 / recency .15
  - **Freshest** — fit .35 / salary .20 / recency .45

### 3.6 Presentation (`dashboard/pages.py`, `dashboard/ui.py`)

**Shortlist — Layout B.** Below the masthead/metric row, a "control desk":
- Row 1: filter controls (`st.selectbox`/`st.multiselect`/`st.slider` styled to the
  Broadsheet theme): Salary≥, Remote, Sponsorship, Seniority, Employment type,
  Industry, Fit≥, and the Sort selector (Fit/Salary/Recency/Composite). When Sort =
  Composite, reveal the three preset buttons.
- Row 2: skill-tag cloud — `available_skill_cloud(rows)` rendered as toggle chips
  with a small emerald dot for profile-covered skills. Selection drives
  `FilterState.skills`.
- Filter state held in `st.session_state` (persists across reruns within a session).

**Rich card** (extends the existing flex-column card; Approve stays pinned bottom):
- Fit meter (unchanged) + title + `company · location` + sponsorship badge.
- Meta line (mono): `$min–max · Seniority · Type · Industry · Nd ago` (omit nulls).
- Skill chips: three-channel encoding (colour=coverage, solid/dashed=must/nice with
  `+` prefix on nice, oxblood ring=active filter).
- Pinned Approve footer (unchanged mechanism).

**Pipeline card** gains exactly one compact meta line (`$min–max · remote · seniority`),
omitting nulls. No chips, no filters — the board stays grouped by stage.

### 3.7 New `ui.py` helpers (pure, unit-testable)

- `skill_chip(tag: SkillTag, active: bool) -> str` — the three-channel chip HTML.
- `meta_line(row) -> str` — null-omitting mono meta string.
- CSS additions for `.controldesk`, chip channel classes, and the skill cloud.

---

## 4. Error handling & edge cases

- **Missing `facts.json`** — chips render with `covered=False`; no crash.
- **Empty filter result** — show an `empty_state` ("No jobs match these filters")
  with a reset affordance, not a blank page.
- **All-null metadata job** (e.g. `addjob` with terse JD) — card degrades to title +
  fit; meta line omits all nulls; passes filters that don't explicitly require the
  null field.
- **Re-extract on a job whose JD is gone** — skip, log, continue.
- **Composite with all-null factors** — scores 50 (pure neutral); never NaN.

---

## 5. Testing strategy

Pure modules carry the weight (suite is offline, agents faked):
- `filtering.py` — table-driven tests: each filter in isolation, AND combination,
  skill OR semantics, unknown-value pass-through, salary-floor exclusion, every sort
  key, each composite preset, neutral null scoring, empty result.
- `queries.py` — `criteria_json` → `ShortlistRow` flattening, coverage tagging with a
  faked `ProfileFacts`, missing-facts path.
- `extract.py` — agent instructions/schema include new fields (faked agent returns
  populated `JobCriteria`).
- connectors — each parses its date field into `RawJob.posted_at`; ingest threads it
  to `Job.posted_at`; LinkedIn relative-date parser unit tests.
- `ui.py` — `skill_chip` channel combinations, `meta_line` null omission.
- A migration test for the new `posted_at` column (existing rows default null).

---

## 6. Out of scope (YAGNI)

- SQL-level querying / promoting criteria fields to columns (Approach B).
- Deterministic skill-coverage *score* as a ranking factor (chips show coverage; the
  match metric stays `fit_score`).
- User-tunable composite weight sliders (presets only).
- Filters on the Pipeline board / Analytics.
- Equity/benefits and team/function extraction (low-signal, dropped).
- Posting date from JD text (source metadata only).

---

## 7. Build sequence (for the implementation plan)

1. `JobCriteria` + extract agent fields (+ tests).
2. `Job.posted_at` migration + `RawJob.posted_at` + connector date parsing + ingest thread (+ tests).
3. `discover --reextract` backfill path (+ tests).
4. `tracking/queries.py` widened `ShortlistRow` + coverage tagging (+ tests).
5. `dashboard/filtering.py` pure logic (+ thorough tests).
6. `ui.py` chip/meta/CSS helpers (+ tests).
7. `pages.py` Shortlist control desk + rich cards.
8. `pages.py` Pipeline lean meta line.
9. Manual headless dashboard verification.
