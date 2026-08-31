# Taxonomy-Normalized Filters (Industry / Skills / Location / Company-size) — Design

**Date:** 2026-06-21
**Status:** Approved (design); implementation plan aligned
**Surface:** `discovery/` (extract + fit + pipeline), `tracking/` (queries, canonicalize), new `taxonomy/` package, `dashboard/` (control desk + filtering), `cli.py`, `data/`

---

## 1. Problem & Goal

The Shortlist filters and the must-have skill cloud are messy: the same concept
appears many times under different surface forms.

- **Industry** is free-text (`JobCriteria.industry: str | None`). The filter dropdown
  is literally `sorted({r.industry for r in rows if r.industry})` (`pages.py:147`), so
  `Fintech` / `fintech` / `Financial Services` / `finance` all show as distinct options.
- **Skills** are free-text lists (`must_have_skills`, `nice_to_have_skills`,
  `tech_stack`). `normalize_skill` (`match_gap.py:23`) collapses case/punctuation, so
  `Python`==`python` *at filter time*, but two gaps remain: (1) compound items like
  `"Python, C++ or C"` are stored as **one** skill string and never split; (2) true
  synonyms (`k8s`/`kubernetes`, `JS`/`JavaScript`) are merged only by the **LLM**
  `build_skill_canonicalizer` (`canonicalize.py`), which today is wired into the
  `match-gap` CLI command (opt-in `--llm`) **only** — never the Shortlist cloud/filter.
- **Location** (`Job.location`) is free-text, shown on cards but **has no filter**.
- **Company-size** (`JobCriteria.company_size`) is free-text and unconstrained.

**Goal:** give each of these a dense, non-overlapping controlled vocabulary so the
filters and skill cloud are clean and efficient — without breaking the offline test
invariant or adding per-load runtime LLM cost.

---

## 2. Guiding seam (the foundational decision)

A new pure, offline-testable **`taxonomy`** layer is the **canonical authority** for
all normalization and derivation. LLMs run only inside *existing* pipeline passes —
no new API calls, no per-load runtime LLM dependency. Each LLM emits raw-ish values
that the deterministic layer normalizes/derives into the controlled vocabulary.

Consequences:
- Tests stay offline: agents are faked, data files are fixtured, the read/derive path
  is pure.
- Taxonomy fixes are deterministic and (mostly) free to re-apply.
- Cross-job consistency comes from the deterministic layer, not from hoping
  independent per-job LLM calls agree.

`criteria_json` remains the store and filtering stays **in-memory** (per the
2026-06-16 job-metadata-filtering decision) — **no schema migration**.

---

## 3. Decisions (locked during brainstorming)

| Area | Decision |
|---|---|
| Canonicalization seam | **Hybrid (C):** deterministic `taxonomy` layer is canonical; LLM rides existing passes; LLM canonicalizer is a build-time/refresh tool, not a runtime read dependency |
| Industry granularity | **2-digit SIC Major Group** (~83); **Division derived** from the code |
| Industry classification | Fit agent emits `sic_major` at **`run_score`** (filter survivors only); unmappable → `None` internally and displays as **`Unclassified`** |
| Industry filter UI | **Division → Major Group cascade** (replaces the flat multiselect) |
| Skill splitting | Extract agent emits **atomic** skills + deterministic splitter **safety net** (protected-token allowlist); per-job |
| Skill synonyms | **Machine-grown persisted alias map**: `canonicalize.py` runs once over the union after `run_score`; map merged into a file; read path applies it deterministically |
| Alias-map home | **`data/skill_aliases.json`**, grown by **merge** (monotonic) |
| Location parse | Fit agent parses `{city, region, country}` at **`run_score`**; deterministic ISO-2 / USPS normalization + `is_us` derivation |
| Location source | `Job.location` primary, `criteria.location` fallback |
| Location filter UI | **3-level cascade Country → State (US only) → City/County**, "unknown passes" |
| Company-size | Constrain to **{startup, scaleup, enterprise}** via prompt + deterministic read-time snap; optional filter chip |
| Backfill | **Re-score command** over existing shortlisted jobs + alias-map refresh; one-time, no `fit_score`/`status` change |
| Storage | `criteria_json` only; in-memory filtering; **no migration** |

---

## 4. Architecture

### 4.1 New pure package — `src/resume_tailor_harness/taxonomy/`

All modules are pure (no Streamlit, no live network/LLM) and unit-tested in isolation.

- **`sic.py`**
  - Loads bundled `data/sic_codes.json` → `{major_group_code: {label, division}}`
    and `{division_code: division_label}`.
  - `major_group_label(code) -> str | None`, `division_for(code) -> (code, label) | None`.
  - `UNCLASSIFIED = "Unclassified"` display label for jobs with no valid `sic_major`;
    `sic_major` itself remains `None` so unknown-pass filtering stays consistent.
  - Validation helper: a code is valid only if present in the table; unknown/garbage
    agent output coerces to `None`.
- **`skills.py`**
  - `split_skills(items: list[str]) -> list[str]` — deterministic splitter: splits on
    `,`, ` / `, ` or `, ` and ` **only when** the surrounding text is not in the
    protected-token allowlist (`C++`, `C#`, `CI/CD`, `Node.js`, `A/B testing`, `.NET`,
    `F#`, `Objective-C`, … — list lives here, extensible). Idempotent on already-atomic
    input.
  - `load_aliases(path) -> dict[str,str]`, `apply_aliases(token, aliases) -> str`
    (compose with `normalize_skill`: normalize → alias-map → canonical token).
  - `merge_aliases(existing, new) -> dict[str,str]` — monotonic merge; **existing
    canonical choices win** (stability across refreshes).
  - `refresh_aliases(tokens, canonicalizer, path)` — run the canonicalizer over the
    token union, merge into the file, write atomically.
  - Canonical **display name** is intentionally simple in the first implementation:
    the stable canonical token is the filter/display value. Polished display aliases
    can be added later without changing matching semantics.
- **`location.py`**
  - `normalize_country(raw) -> str | None` (→ ISO-2 via bundled map: `United States`/`USA`/`US`→`US`, `UK`/`United Kingdom`/`GB`→`GB`, …).
  - `normalize_region(raw, country) -> str | None` (US → USPS 2-letter via bundled map;
    non-US → leave region `None`, per "foreign = city + country").
  - `is_us(country) -> bool`.
  - `build_location(city, region, country, raw=None) -> StructuredLocation` assembling
    `{city, region, country, is_us, raw}` from the agent's `{city, region, country}` plus
    normalization. Pure transform over agent output (agent faked in tests).
- **`company_size.py`**
  - `snap(raw) -> str | None` → one of `{startup, scaleup, enterprise}` via a small
    deterministic variant map (`Series A/B/seed`→startup, `Series C/D/growth`→scaleup,
    `Fortune 500`/`public`/`10000+`→enterprise, employee-count ranges bucketed).
    Unmappable → `None`.

### 4.2 Bundled & generated data

The repo's `data/` directory is **gitignored** (`.gitignore:18`), so it holds only
runtime state. Bundled *static reference* that must ship with the package lives **inside
the package** instead, loaded via `importlib.resources`.

- **`src/resume_tailor_harness/taxonomy/data/sic_codes.json`** — bundled, tracked, shipped:
  the 2-digit Major Groups with labels and their Division. Source: SEC SIC list rolled
  up to 2-digit. Loaded via `importlib.resources`.
- **USPS-state and ISO-country maps** — bundled as module constants in `location.py`
  (small, stable), or sibling package-data JSON next to `sic_codes.json` if preferred at
  implementation time.
- **`data/skill_aliases.json`** — runtime-generated state under the gitignored `data/`,
  grown by merge (mirrors the existing `data/connector_runs.json` precedent): regenerated
  by the alias refresh, never hand-edited, not version-controlled.

### 4.3 Extraction layer (`discovery/extract.py`)

- Instruction additions:
  - "Emit each skill as a **single atomic skill** — never combine multiple skills into
    one item; e.g. `Python, C++ or C` becomes three entries."
  - "`company_size` must be one of `startup`, `scaleup`, `enterprise` (best fit) or null."
- Schema (`JobCriteriaExtract`) unchanged in shape (skills already `list[str]`,
  `company_size` already `str | None`); only prompt guidance changes.
- The deterministic `split_skills` safety net runs over extracted skill lists at the
  point they are read into rows (covers legacy + agent slips).

### 4.4 Fit / shortlist layer (`discovery/fit.py`, `discovery/pipeline.py`)

- **`FitScore` (schema) gains** structured fields the fit agent now emits:
  ```python
  class FitLocation(BaseModel):   # LLM-facing, extra="forbid"
      city: str | None
      region: str | None
      country: str | None

  class FitScore(ExtensibleModel):
      score: int = Field(ge=0, le=100)
      rationale: str
      sic_major: str | None        # 2-digit SIC code, best fit, null if unknown
      location: FitLocation | None
  ```
- **`compose_fit_input`** additionally includes `Job.location` (fallback
  `criteria.location`) so the agent can parse it.
- **`run_score`** (the second writer of `criteria_json`):
  1. call fit agent → `score`, `rationale`, `sic_major`, `location`.
  2. write `fit_score` / `fit_rationale` columns (unchanged).
  3. read `criteria_json`, set `sic_major` (coerced via `sic.py` to a valid code or
     `None`) and structured `location` (via `location.build_location`), write back.
  4. after the loop, collect the union of (split, normalized) skill tokens across
     shortlisted jobs and call `refresh_aliases(...)` once.
- Fit-agent instruction additions: classify the **domain the JD serves** to the nearest
  2-digit SIC Major Group (it's a controlled vocabulary, not the employer's filing);
  parse the location into city/region/country.

### 4.5 Backfill (`cli.py`, `discovery/pipeline.py`)

- `backfill_rescore(session, profile_facts, fit_agent) -> int` (parallel to
  `reextract`): for each **shortlisted** job, re-run the upgraded fit agent, write
  `sic_major` + `location` into `criteria_json` (does **not** change `fit_score`/`status`),
  then `refresh_aliases`. Returns count.
- CLI surface: `resume-tailor-harness discover --rescore`, mirroring the existing
  `resume-tailor-harness discover --reextract` backfill style.

### 4.6 Data access (`tracking/queries.py`)

`ShortlistRow` widens to carry the canonical/derived values the UI needs:
```python
@dataclass
class ShortlistRow:
    ...
    sic_major: str | None        # code
    sic_label: str | None        # derived major-group label
    sic_division: str | None     # derived division label
    location_country: str | None # ISO-2
    location_region: str | None  # USPS (US only)
    location_city: str | None
    is_us: bool
    company_size: str | None     # snapped bucket
    skills: list[SkillTag]       # names already alias-canonicalized for display + match
```
- `_skill_tags` composes `normalize_skill` → `apply_aliases` (loaded once per build) and
  runs `split_skills` first; dedup by canonical token, must-have > nice > tech_stack.
- SIC/location/company-size flattened from `criteria_json` via the `taxonomy` layer;
  missing `sic_major` → `sic_major=None`, `sic_label="Unclassified"`.

### 4.7 Filtering (`dashboard/filtering.py`)

- **`FilterState` gains**:
  ```python
  industry: set[str]        # now SIC major-group codes (existing field, repurposed)
  country: set[str] = ...
  region: set[str] = ...
  city: set[str] = ...
  company_size: set[str] = ...
  ```
- **Cascade option builders** (pure, for the control desk):
  - `available_industries(rows) -> list[(division_label, [(code, label)])]`
  - `available_countries(rows)`, `available_states(rows, countries)`,
    `available_cities(rows, countries, states)`.
- **`_passes`** extends the existing AND semantics with industry (by code), country /
  region / city, and company_size — all with **"unknown passes"** (a `None` field is
  never excluded by a filter on that field). Skill OR semantics unchanged.

### 4.8 Presentation (`dashboard/pages.py`, `dashboard/ui.py`)

- Control desk: **replace** the flat Industry multiselect with the
  **Division → Major Group cascade**; **add** the **Country → State → City cascade**;
  **optional** company-size chip.
- Skill cloud (`available_skill_cloud`) now reads alias-canonicalized tokens → fewer,
  deduped chips; coverage/required encoding unchanged.
- Cascade selections narrow downstream options live; "Unclassified" / "Unknown"
  surface as display labels while the underlying `None` values keep unknown-pass
  filtering behavior.

---

## 5. Error handling & edge cases

- **Fit agent returns an invalid/garbage SIC code** → coerced to `None` and displayed as `Unclassified`
  (validated against `data/sic_codes.json`).
- **Location unparseable** (`"2 Locations"` the agent can't split) → structured fields
  `None`; row still passes location filters (unknown passes).
- **Non-US job** → `region` left `None`; State level skipped in the cascade for it.
- **Missing `data/skill_aliases.json`** → treated as empty map (identity); no crash.
- **Alias refresh with faked/again-run canonicalizer** → `merge_aliases` is idempotent
  and keeps existing canonical choices (no thrash between refreshes).
- **Legacy compound skill** (`"Java, Go"`) → `split_skills` safety net handles it at read
  time without re-extraction.
- **`split_skills` on protected token** (`C++`, `CI/CD`) → never split.
- **Backfill on a shortlisted job whose JD/location is gone** → skip, continue.
- **Missing `facts.json`** → skill coverage `False` (existing behavior), unaffected.

---

## 6. Testing strategy (offline; agents faked, data fixtured)

Pure modules carry the weight:
- `taxonomy/sic.py` — derive label/division; unknown code → `None` plus `Unclassified`
  display fallback.
- `taxonomy/skills.py` — splitter (commas/or/slash, protected tokens, idempotence);
  `apply_aliases` composition with `normalize_skill`; `merge_aliases` monotonicity &
  idempotence; `refresh_aliases` with a faked canonicalizer.
- `taxonomy/location.py` — country→ISO-2, US state→USPS, `is_us`, non-US region `None`,
  unknown → `None`.
- `taxonomy/company_size.py` — variant snap table; unmappable → `None`.
- `filtering.py` — each new filter in isolation, AND combination, cascade option
  builders, "unknown passes" for every new field, skill OR unchanged.
- `queries.py` — `criteria_json` + taxonomy → widened `ShortlistRow`; canonical skill
  tags; `Unclassified` display fallback.
- `extract.py` / `fit.py` — faked agents return atomic skills / `sic_major` / location;
  `run_score` writes them into `criteria_json` and triggers one alias refresh; backfill
  populates without touching `fit_score`/`status`.
- `ui.py`/`pages.py` pure helpers — cascade rendering inputs (option builders only;
  Streamlit calls remain manual-verified).

---

## 7. Out of scope (YAGNI)

- Promoting any taxonomy field to a SQL column / SQL-level querying.
- 3-digit/4-digit SIC precision (re-fragments; 2-digit chosen).
- A hand-maintained industry alias table (classification is LLM-at-shortlist; only the
  static SIC *reference* is bundled).
- Job-title normalization as a filter facet (title dedup already exists in `dedup.py`).
- Live per-load LLM canonicalization in the dashboard.
- Re-scoring `fit_score` or changing status during backfill.
- County-vs-city disambiguation beyond a single "City/County" locality field.

---

## 8. Build sequence (for the implementation plan)

1. `taxonomy/sic.py` + bundled `src/resume_tailor_harness/taxonomy/data/sic_codes.json` (+ tests).
2. `taxonomy/skills.py` — splitter + alias load/apply/merge/refresh (+ tests).
3. `taxonomy/location.py` — ISO/USPS/is_us normalization (+ tests).
4. `taxonomy/company_size.py` — snap (+ tests).
5. `extract.py` prompt: atomic skills + bucketed company_size (+ faked-agent test).
6. `fit.py` schema + `compose_fit_input` location feed (+ faked-agent test).
7. `pipeline.run_score`: write `sic_major`/location into `criteria_json` + alias refresh
   (+ tests).
8. `pipeline.backfill_rescore` + `cli` command (+ tests).
9. `tracking/queries.py` widened `ShortlistRow` + canonical skills (+ tests).
10. `dashboard/filtering.py` `FilterState` + cascade builders + `_passes` (+ thorough tests).
11. `dashboard/pages.py` control-desk cascades + canonical skill cloud; optional
    company-size chip.
12. Manual headless dashboard verification.
