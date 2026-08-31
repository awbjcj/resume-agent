# Résumé Tailor Harness v1.5 — Quality + Lean-Cost Pass — Design Spec

- **Date:** 2026-06-10
- **Status:** Approved (design) — ready for implementation planning
- **Branch:** `v1.5` (off `main`)
- **Predecessor:** `docs/superpowers/specs/2026-06-08-resume-tailor-harness-design.md` (v1)

---

## 1. Overview

v1 built the end-to-end funnel: profile fact-lock → discovery → tailor/review loop → Typst PDF → SQLite/Streamlit tracking. v1.5 is a **quality-first refinement** of the back half of that pipeline — *profile*, *re-writing*, and *rendering* — with a contained set of *cost* improvements riding along.

### Primary goal
The tailor/render pipeline can faithfully reproduce **and improve on** the user's own LaTeX sample resume (`resume-latex/`), restoring the fact types it currently drops, while cutting the token cost of every tailor run.

### The two problems v1.5 fixes
1. **Silent narrowing.** `ProfileFacts` captures publications, certifications, awards, languages, volunteer, and GPA/honors/coursework — but `ResumeContent` and `templates/resume.typ` only carry contact, summary, experience, projects, skills, and a stripped-down education. The agent literally cannot reproduce the user's sample, which has a Publication section and GPA-bearing education.
2. **Fan-out cost.** `compose_review_input` ships the **entire** `profile_facts.model_dump_json()` (all GitHub repos included) to every agent — tailor, all reviewers, reviser — every round. This is the dominant cost driver and is mostly wasted: non-fact-check reviewers don't need the raw profile at all.

### Non-goals
Concurrency/parallelism (deferred to v1.6), new job sources, cover letters, auto-submit, and any change to the fact-lock philosophy. Multi-column or colored layouts are explicitly rejected (ATS-safety).

---

## 2. Decisions (resolved during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Primary optimization axis | **Output quality** (resume fidelity to the sample); cost is a supporting win |
| 2 | Render target | **Hybrid** — single linear ATS-safe column with refined typography (right-aligned dates, bold section rules, grouped inline skills). No color, no multi-column |
| 3 | Section model | **Typed fields mirroring `ProfileFacts` + an optional `section_order` hint** the tailor sets per job |
| 4 | Provenance enforcement | **Deterministic pre-gate** in plain code, *before* the LLM fact-checker runs |
| 5 | Length control | **Guide the tailor** with an explicit one-page budget + surface counts to the concision reviewer. No hard truncation |
| 6 | Profile refinement | **Higher fidelity** (mid-tier extractor) + **deterministic coverage validation** + **GitHub/resume project dedupe** on merge |
| 7 | Perf scope | **Payload trimming + batch DB commits** this round; parallel panel and job-level concurrency **deferred to v1.6** |
| 8 | Implementation approach | **Incremental, pure-function** changes; keep the sync `Runner` protocol and the offline/faked-agent test suite |

### Default `section_order` (when the tailor sets none)
`summary → experience → education → projects → skills → publications → certifications → awards → languages → volunteer`

Education sits directly under work experience (academic-to-industry convention). Unknown or empty sections are skipped by the renderer.

---

## 3. Cross-cutting principles (carried from v1, reaffirmed)

- **Fact-lock.** The rewriter selects/reorders/rephrases facts; it never invents. v1.5 *strengthens* this: provenance is now verified in plain code (Decision #4), delivering the v1 spec's promise that provenance is "partially verifiable before any LLM runs."
- **Schema is the single source of truth.** New `ResumeContent` sections are Pydantic models; prompts derive from their JSON schema + field descriptions. No duplicated field lists.
- **Extensibility.** New fields are optional with defaults; `schema_version` + `extra` escape hatch preserved on every model. Adding a section is additive — no DB migration (`content_json` is a JSON blob).
- **Resumability.** SQLite stage seams are unchanged. Batch commits still commit at each stage boundary, so a stage can still be re-run in isolation.

---

## 4. Component designs

### 4.1 Data model (`models/resume.py`, `models/profile.py`)

`ResumeContent` gains typed, provenance-tagged sections that mirror `ProfileFacts`:

- `publications: list[TailoredPublication]` — title, venue, date, authors, url, `provenance`.
- `certifications: list[TailoredCertification]` — name, issuer, date, url, `provenance`.
- `awards: list[TailoredAward]` — name, issuer, date, description, `provenance`.
- `volunteer: list[TailoredVolunteer]` — organization, role, start, end, bullets/description, `provenance`.
- `languages: list[Language]` — carried verbatim (like `education`); the source fact `id` is retained so the provenance gate can verify it.
- `section_order: list[str] | None` — the tailor's per-JD section ordering hint.

`education` is **unchanged** — `ProfileFacts.Education` already carries `gpa`, `honors`, and `relevant_coursework`; only the template drops them today (fixed in §4.4).

Each new `Tailored*` item carries a `provenance` string pointing at the `id` of the source `FactItem` in `ProfileFacts` (publications/certifications/awards/volunteer/languages are all `FactItem`s with stable ids).

### 4.2 Profile refinement (`profile/`)

- **Extractor model tier → mid.** `build_extractor_agent` defaults to `get_settings().mid_model` (was `cheap_model`) for higher-fidelity structuring of dense, multi-section resumes. Still overridable via `model_id`.
- **`profile/validate.py` (new, deterministic).** A `validate_profile(facts, raw_text) -> CoverageReport` function with no LLM:
  - required fields present (`contact.name`; each experience has `company` + `title`),
  - experiences with zero bullets,
  - a keyword heuristic: if `raw_text` contains section cues (e.g. "Publication", "Certification", "Award", "Volunteer") but the corresponding `ProfileFacts` list is empty, flag a probable miss.
  - Report is **advisory**, printed by `profile build`; the human still edits `facts.json`. No hard failure.
- **`merge_facts` dedupe.** Skip a GitHub `Project` whose normalized name (casefold + strip non-alphanumerics) matches an existing resume `Project`. When skipped, optionally enrich the surviving resume project with GitHub-only metadata (`stars`, `repo_url`, `primary_language`) if those fields are empty. Resume facts always win on conflict.

### 4.3 Rewrite / tailor refinement (`tailor/`)

- **`tailor/provenance.py` (new, deterministic gate).**
  - `collect_fact_ids(profile_facts) -> set[str]` — every `FactItem.id` across experiences (and their bullets), projects, skills, publications, certifications, awards, languages, volunteer, education.
  - `check_provenance(content, fact_ids) -> ProvenanceReport` — walks every provenance-bearing item in `ResumeContent`; returns the list of ids that don't resolve.
  - **Round integration:** the gate runs *before* the panel each round.
    - Broken ids ⇒ a blocking, deterministically-built verdict; the loop revises immediately and **skips the LLM fact-check call** that round (cost win).
    - Valid ids ⇒ the panel runs, *including* the LLM fact-checker, which verifies the text stays **faithful** to the referenced fact (structure ≠ semantics — the deterministic check only proves the id exists).
  - Overall gate: `gate_passed = provenance_passed AND llm_fact_check_passed`. Implemented by threading `provenance_passed` into `verdict.aggregate`.
- **Per-reviewer payload trimming (`panel.py`).** Replace the single shared `compose_review_input` with per-reviewer composition keyed off the existing `gate: bool` in `review.yaml`:
  - **Non-gate reviewers** (recruiter, ATS-keyword, hiring-manager, concision): base input = `ResumeContent` + JD only — the raw profile is dropped entirely. A reviewer may receive small, deterministically-computed annotations on top (e.g. the concision reviewer also gets the length budget + actual counts, see below); these are cheap scalars, not profile dumps.
  - **Gate reviewer** (fact-check): input = `ResumeContent` + JD + a **provenance-resolved evidence view** = only the `ProfileFacts` facts referenced by the resume's provenance ids (built via `tailor/provenance.py`). Never the whole profile / all repos.
- **Length budget.** An optional `length_budget` block in `review.yaml` (`max_experiences`, `max_bullets_per_role`, `target_total_bullets`) is:
  - injected into the tailor (and reviser) contract as an explicit one-page target, and
  - passed to the concision reviewer alongside **deterministically-computed actual counts**, so it judges against a concrete target.
  - Sensible defaults when the block is absent; **no hard truncation** anywhere.

### 4.4 Render refinement (`templates/resume.typ`, `render/`)

Rework the Typst template to the hybrid target:

- **Layout:** single linear column (one text run per line for clean ATS parsing), bold section headings with a horizontal rule, right-aligned dates via `grid`, grouped inline skills (`Category: a, b, c`). No color, no multi-column.
- **New sections rendered:** publications, certifications, awards, languages, volunteer.
- **Enriched education:** GPA, honors, relevant coursework.
- **Ordering:** iterate sections per `content.section_order`; fall back to the default order (§2) when absent; skip unknown/empty sections.
- **Header:** name, headline/role, then a single contact line (`location • email • phone`) and a links line. Deterministic; no LLM involvement (render stays LLM-free).

### 4.5 Perf (cost-only this round)

- **Payload trimming** (§4.3) — the primary cost *and* latency lever (shorter prompts everywhere).
- **Batch DB commits.** `discovery/pipeline.py` stages (`run_extract`, `run_filter`, `run_score`) `add` rows in the loop and `commit` **once per stage**, instead of once per row. Stage boundaries remain the resumability seam.
- **Deferred to v1.6 (documented):** parallel reviewer panel and job-level concurrency. Rationale: the SQLModel `Session` is not thread-safe, and payload trimming already captures most of the per-run latency win by shrinking every prompt.

---

## 5. File change map

| File | Change |
|------|--------|
| `models/resume.py` | Add `TailoredPublication/Certification/Award/Volunteer`; add `publications/certifications/awards/volunteer/languages/section_order` to `ResumeContent` |
| `models/profile.py` | (No structural change; `Education`/`Language` already sufficient) |
| `profile/extractor.py` | Default extractor to mid tier |
| `profile/validate.py` | **New** — deterministic coverage report |
| `profile/merge.py` | GitHub/resume project dedupe + enrichment |
| `profile/build.py` | Wire in validation report output |
| `tailor/provenance.py` | **New** — `collect_fact_ids`, `check_provenance`, evidence view |
| `tailor/panel.py` | Per-reviewer input composition (lean vs evidence) |
| `tailor/tailoring.py` | Tailor/reviser contract: length budget; evidence-aware compose |
| `tailor/agents.py` | Length-budget instructions; reviewer instructions unchanged otherwise |
| `tailor/verdict.py` | Thread `provenance_passed` into the gate |
| `tailor/workflow.py` | Run deterministic gate before panel; short-circuit on broken provenance |
| `tailor/review_config.py` | Optional `length_budget` block |
| `discovery/pipeline.py` | Batch commits per stage |
| `tracking/repository.py` | Add a commit-less `add`/stage-commit seam if needed |
| `templates/resume.typ` | Full rework: new sections, enriched education, `section_order`, refined typography |
| `cli.py` | `profile build` prints the coverage report |
| `config/review.yaml.example` | Document `length_budget` |

---

## 6. Testing strategy

All agents remain faked/offline — no API key, no network.

- **Provenance gate (deterministic).** Valid ids pass; a broken/fabricated provenance id is blocked **without any LLM call** — this becomes the adversarial fact-check test.
- **Per-reviewer input shape.** Assert non-gate reviewers receive no raw profile; the gate reviewer receives only referenced facts (not all repos).
- **Merge dedupe.** A GitHub repo named like a resume project is dropped/merged; resume facts win; enrichment fills empty fields only.
- **Profile coverage report.** Raw text mentioning "Publications" with an empty list raises a flag.
- **Section ordering.** `section_order` is honored; default applies when absent; empty sections skipped.
- **Length counts.** Deterministic counts surfaced to the concision reviewer match the content.
- **Render golden.** Compile a `ResumeContent` containing publications + GPA-bearing education; assert the PDF compiles and the new sections are present (text extraction).

---

## 7. Rollout

1. Branch `v1.5` off `main` (done).
2. Land changes in the §5 order, each with its tests, keeping the suite green.
3. Manual check: rebuild the profile from `resume-latex/`, tailor against a sample JD, render, and eyeball the PDF against `resume-latex/resume.pdf`.

---

## 8. Roadmap delta (for v1.6+)

- **v1.6:** parallel reviewer panel + job-level concurrency (with a thread-safe session strategy); response-rate analytics.
- Unchanged from v1's memo: Indeed scraper, Gmail auto-status, ATS JSON backbone, cover letters (v2); semi-auto and full auto-submit (v3–v4).
