# Resume Agent v3 — House-Style Customization + Match-Gap Intelligence — Design Spec

- **Date:** 2026-06-13
- **Status:** Approved (design) — ready for implementation planning
- **Scope of this document:** Full v3 design. Builds on the v1 spec (`2026-06-08-resume-agent-design.md`) and the v2 spec (`2026-06-11-resume-agent-v2-connectors-design.md`).
- **Successor planning:** one spec → two independent component plans (mirrors the v1/v2 spec→multi-plan pattern).

---

## 1. Overview

v1 built the fact-locked tailor→review→render→track pipeline. v2 widened intake into a multi-connector framework and added cover letters, Gmail auto-status, and conversion analytics. v3 adds **two small, independent, additive capabilities** that make the existing pipeline *smarter about how it writes* and *smarter about the gap between you and the market* — without crossing any of the boundaries the product has held since v1.

### Primary goal
Two things, kept deliberately small:

1. **House-style layer (Pillar 2):** let the user inject their own resume-writing guidance — industry conventions, tone, structure, emphasis — into the **system message** of the resume-rewrite agents, *on top of* the non-removable fact-lock core.
2. **Match-gap report (Pillar 1):** turn data the pipeline already stores into intelligence — for the jobs you're actually targeting, show which required skills your profile doesn't surface, so you know what to add to `facts.json` or what to go learn.

### Defining property
v3 is the **smallest-surface major version** to date: **zero database migrations**, no new tables, no new columns. Pillar 2 is a config file plus agent-instruction wiring; Pillar 1 is a pure read over existing data, computed on demand like `analytics.py`.

### Non-goals (unchanged from v1/v2)
Not a product, not multi-tenant, not an auto-submitter. Still stops before submit; the human still owns what is submitted, what `facts.json` says, and any application-status change. v3 adds **no** new outward-facing I/O (no form-fill, no new scrapers, no writes to ground-truth files).

---

## 2. Decisions (resolved during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | v3 theme | **Two independent pillars** — house-style customization **and** match-gap intelligence. Not the original roadmap's form-fill; not the v2 §12 grab-bag. |
| 2 | House-style boundary vs fact-lock | **Additive, layered.** Fact-lock core stays hardcoded and non-removable; user text is appended beneath it. The fact-check gate remains the sole authority over claims. |
| 3 | House-style reach | **Entire resume tailor loop** — writer, reviser, **and** reviewers receive the same block, so the loop honors the style instead of reverting it. |
| 4 | House-style artifact scope | **Resumes only.** Cover letters out of v3 (identical mechanism, trivial to add later). |
| 5 | House-style form | **Single prose `config/style_guide.md`** (+ `.example`); path via a new `review.yaml` key `style_guide_path:`. Injected verbatim into each loop agent's `instructions` as a labeled block. Opt-in; missing/empty ⇒ today's behavior. |
| 6 | Match-gap input set | **Jobs that survived discovery** (`shortlisted`/`approved`/`tailored`/`rendered`), aggregated + per-job drill-down. No employer-rejection lens. |
| 7 | Match-gap matching | **Deterministic** normalize+match against profile `name`+aliases, **plus an opt-in cheap-LLM canonicalization pass** (faked in tests). |
| 8 | Match-gap surface | **Both CLI and dashboard**, over one pure `match_gap()` in `tracking/`. |
| 9 | Match-gap actionability | **Read-only.** Never writes `facts.json`; the human acts on the report. |
| 10 | Match-gap ranking | **By frequency** ("demanded by N of M target jobs," descending). Fit-score weighting deferred. |
| 11 | Packaging | **One spec → two independent component plans.** No dependency edge; either order; each independently green. |

---

## 3. Cross-cutting principles (inherited)

Every v1/v2 principle carries forward and constrains v3:

- **Fact-Lock** (§3.1 v1) — v3 *reinforces* it. The house-style layer is appended *beneath* the fixed fact-lock instructions and can never remove them; the fact-check reviewer stays the hard gate over every claim. The match-gap report is read-only and never injects claims.
- **Extensibility** (§3.2 v1) — honored, but v3 needs no schema growth at all: Pillar 2 is config; Pillar 1 reads existing JSON columns (`Job.criteria_json.must_have_skills`, `ProfileFacts.skills`).
- **Resumability** (§3.3 v1) — untouched. Neither pillar adds pipeline stages or new statuses; the match-gap report is a pure query, the house-style layer is prompt configuration.
- **Cost funnel** (§3.4 v1) — untouched. The match-gap report adds no per-job LLM cost by default (deterministic); its optional canonicalization pass is a single cheap-model call, opt-in.
- **Human control / authoritative `facts.json`** (§5.1 v1) — the match-gap report is deliberately read-only so it can never overwrite the human-edited ground truth, mirroring `profile build`'s refusal to clobber without `--refresh`.

---

## 4. Architecture (v3)

```
  ┌─────────────────────── PILLAR 2: house-style layer ───────────────────────┐
  │  config/style_guide.md  (+ path in review.yaml: style_guide_path)          │
  │            │  (free-text prose, opt-in; missing/empty ⇒ no-op)             │
  │            ▼                                                                │
  │   load_style_guide() → str | None                                          │
  │            │   appended verbatim as a labeled block beneath the fixed       │
  │            │   fact-lock instructions of EVERY tailor-loop agent           │
  │            ▼                                                                │
  │   build_tailor_agent(style) · build_reviser_agent(style)                   │
  │   build_reviewer_agent(name, style)   ← writer, reviser, reviewers all     │
  │                                          see the same house-style block     │
  └────────────────────────────────────────────────────────────────────────────┘
        (TAILOR loop otherwise UNCHANGED — fact-check gate still authoritative)

  ┌─────────────────────── PILLAR 1: match-gap report ────────────────────────┐
  │   jobs(status ∈ {shortlisted,approved,tailored,rendered})                  │
  │      .criteria_json.must_have_skills          ProfileFacts.skills          │
  │            │                                        │ (name + aliases)     │
  │            └───────────────► match_gap() ◄──────────┘                      │
  │                 deterministic normalize+match                              │
  │                 (+ opt-in cheap-LLM canonicalization, faked in tests)      │
  │                          │                                                 │
  │             ┌────────────┴────────────┐                                    │
  │             ▼                         ▼                                    │
  │   `match-gap` CLI            dashboard "Match-gap" page                    │
  │   (aggregate + --job-id N)   (sortable aggregate + per-job drill-down)     │
  └────────────────────────────────────────────────────────────────────────────┘
                       (READ-ONLY — never writes facts.json)
```

The two pillars share no code and have no ordering dependency.

---

## 5. Components

### 5.1 House-style layer (Pillar 2)

**Where today's code stands.** In `tailor/agents.py`, each loop agent is built with a hardcoded `instructions` list — `_TAILOR_INSTRUCTIONS`, `_REVISER_INSTRUCTIONS`, and `REVIEWER_INSTRUCTIONS[name]`. Lines 2–3 of `_TAILOR_INSTRUCTIONS` ("Use ONLY facts present in the candidate profile. Never invent anything." + the provenance mandate) are exactly what make the fact-check gate enforceable.

**The change.**
- **Loader:** a new `load_style_guide(path: str | None) -> str | None`. Reads the prose file if present and non-empty; returns `None` otherwise. Path comes from a new optional `style_guide_path` key in `review.yaml` (default `config/style_guide.md`). A missing or empty file is a no-op — the feature is purely opt-in.
- **Injection:** `build_tailor_agent`, `build_reviser_agent`, and `build_reviewer_agent` gain an optional `style_guide: str | None` parameter. When present, the agent's `instructions` become `[...fixed instructions..., HOUSE_STYLE_HEADER, style_guide]` — the user text is **appended beneath** the fixed core, never interleaved or replacing it. The header (e.g. `"HOUSE STYLE (user writing guidance — applies to how you write, never to what is true):"`) labels the block so the model distinguishes house style from the non-negotiable fact-lock rules.
- **Reach:** the writer, the reviser, **and every reviewer** receive the identical block. This is deliberate: if only the writer saw the style, a reviewer (e.g. `concision`, `recruiter`) could flag the deliberate style as an issue and the reviser would revert it next round. Sharing the block makes reviewers evaluate *against* the stated style.
- **Wiring:** `cli.py`'s `tailor_cmd` (and the `build_reviewer_agents` helper) load the style guide once from the review config and thread it into all three builders.

**Fact-lock invariant (unchanged).** The house-style block cannot remove or weaken the fixed fact-lock instructions; every claim still requires a `provenance` id into `facts.json`; the fact-check reviewer remains a hard gate. House style governs **how** the resume is written (tone, emphasis, ordering, formatting conventions, industry positioning); it is never a source of claims.

### 5.2 Match-gap report (Pillar 1)

- **Pure core:** a new `match_gap()` in `tracking/` (sibling to `analytics.py`), following the same "pure function, multiple consumers" pattern. It:
  1. Selects jobs whose `status ∈ {shortlisted, approved, tailored, rendered}`.
  2. Reads each job's `criteria_json.must_have_skills`.
  3. Builds the profile's known-skill set from `ProfileFacts.skills` — every skill fact's `name` plus its `aliases` — normalized (lowercase, strip punctuation, collapse whitespace).
  4. A required skill is a **gap** if its normalized form is not in the profile set.
  5. Aggregates gaps across the target jobs, ranked by **frequency** — "demanded by N of M target jobs," descending — and also exposes the per-job gap list.
- **Optional cheap-LLM canonicalization (opt-in):** behind a flag/config, a single cheap-model pass canonicalizes JD skills and profile skills to a shared vocabulary before set-difference, catching fuzzy equivalents (`k8s`≈`Kubernetes`, `CI/CD`≈`continuous integration`) the alias table misses. Off by default; **faked in tests** like every other agent, preserving the offline suite.
- **Surfaces (both over the one core):**
  - **CLI `match-gap`:** prints the aggregate table; `--job-id N` prints one job's gaps.
  - **Dashboard page:** sortable aggregate + per-job drill-down.
- **Read-only:** the report frames each gap ("demanded by N of M target jobs; add to `facts.json` if you have it, otherwise a real gap to close") but never edits `facts.json`. The loop closes through the human.
- **Output shape (sketch):** a small `@dataclass` per gap row — `skill: str`, `demand_count: int`, `target_total: int` — and a per-job structure mapping `job_id → list[str]` of missing skills. Derived rates/labels computed as properties, mirroring `CohortStat`.

---

## 6. Data model changes

**None.** No new tables, no new columns, no migrations.

- Pillar 2 touches only configuration and agent construction.
- Pillar 1 reads existing data: `Job.status`, `Job.criteria_json.must_have_skills`, `ProfileFacts.skills` (`name` + `aliases`). The report is computed on demand and persisted nowhere.

---

## 7. Project layout (additions / modifications)

```
src/resume_agent/tailor/agents.py        # MODIFY — style_guide param on the 3 builders + labeled append
src/resume_agent/tailor/style_guide.py   # NEW — load_style_guide(path) -> str | None
src/resume_agent/tailor/review_config.py # MODIFY — optional style_guide_path key
src/resume_agent/tracking/match_gap.py    # NEW — pure match_gap() core (+ gap dataclasses)
src/resume_agent/tracking/canonicalize.py # NEW (optional pillar) — cheap-LLM skill canonicalizer
src/resume_agent/dashboard/app.py         # MODIFY — Match-gap page
src/resume_agent/cli.py                   # MODIFY — match-gap command; thread style guide into tailor
config/style_guide.md(.example)           # NEW — prose house-style guidance
tests/fixtures/...                         # NEW — seeded jobs/profile for match-gap; style-guide cases
```

(Exact filenames are the component plans' call; the seams are: a style loader, a pure `match_gap`, and an optional canonicalizer.)

---

## 8. Tech stack (additions)

- **No new runtime dependencies.** Pillar 2 is file I/O + string assembly. Pillar 1 is pure Python set logic over existing models; its optional canonicalization reuses the existing cheap-model agent path. Dashboard/pandas already present.

---

## 9. Testing strategy

- **House-style layer** — unit tests assert: (a) with a style guide present, the appended block appears in the `instructions` of the writer, the reviser, **and** every reviewer; (b) the fixed fact-lock instructions are still present and precede the house-style block; (c) a missing/empty file yields exactly the pre-v3 instruction lists (no-op); (d) the existing fact-check adversarial test still blocks a fabricated claim even with a permissive style guide loaded (style cannot disable fact-lock).
- **Match-gap core** — deterministic unit tests on a seeded jobs+profile fixture: correct gap set, correct frequency aggregation/ranking, alias hits excluded, and only `shortlisted`+ jobs counted (a `filtered`/`rejected` job's skills never appear). Headline test: "a skill demanded by 2 of 3 target jobs and absent from the profile ranks first; an aliased skill the profile has under another name is not a gap."
- **Canonicalization (optional)** — with a **faked** cheap model, assert `k8s`/`Kubernetes` collapse and a true gap survives; assert the deterministic path is unchanged when the pass is off. No network in CI.
- **Surfaces** — CLI prints aggregate and `--job-id N`; the pure core is exercised directly so the dashboard needs no live render test.

---

## 10. Build sequence (what `writing-plans` will emit)

Two **independent** plans, no dependency edge — either order, parallelizable:

- **Plan A — House-style layer.** `load_style_guide` + `review.yaml` key → `style_guide` param threaded through `build_tailor_agent`/`build_reviser_agent`/`build_reviewer_agent` with the labeled append → wire into `tailor_cmd`/`build_reviewer_agents` → tests (reach, ordering, no-op, fact-lock survives).
- **Plan B — Match-gap report.** Pure `match_gap()` core + dataclasses + tests → optional cheap-LLM canonicalizer (faked) → `match-gap` CLI (`--job-id`) → dashboard page.

---

## 11. Risks

- **House-style vs reviewer tension** — even with reviewers seeing the block, an aggressive style guide could fight a reviewer's intrinsic rubric (e.g. demanding a register the `recruiter` rubric dislikes), costing extra revision rounds or a lower aggregate score. Mitigated by sharing the block loop-wide and by the layer being opt-in; the user tunes their guide.
- **Fact-lock erosion attempt** — a user could *write* a style guide that tries to license embellishment. Mitigated structurally: the block is appended beneath the fixed fact-lock core (which it cannot remove) and the fact-check gate is unaffected; covered by the test that fabrication is still blocked under a permissive guide.
- **Deterministic match-gap false positives** — a skill held under an unlisted alias shows as a gap. Accepted at single-user volume; surfaces as a nudge to curate `facts.json` aliases; the opt-in canonicalization pass exists for when recall matters.
- **Thin `must_have_skills`** — jobs whose extraction produced sparse skills weaken the aggregate. The report degrades gracefully (shows counts, low-n is visible in "N of M").

---

## 12. Explicitly deferred (v4 memo)

- **Submission assistance / Playwright form-fill** (the original v1-roadmap v3).
- **Outcome-feedback into fit-scoring** (use `Application.status` history to re-weight scoring/tailoring) — data-hungry at single-user volume.
- **Employer-rejection "what cost me" lens** and **fit-score-weighted gap ranking.**
- **Guided write-back** that drafts candidate skill-facts into `facts.json` for accept/reject.
- **Cover-letter house-style** (same mechanism, easy to add).
- **More connectors** (Indeed/Wellfound/international), **`init` wizard**, **dashboard source-filter / manual dedup-merge UI**, **LLM cross-source dedup adjudicator** (the v2 §12 leftovers).
- **An `industry` / `role_family` field** on `JobCriteria` (dropped when Pillar 2 narrowed; match-gap doesn't need it, but it would enable industry-routed guides and an industry analytics slice if a future version revives auto-routing).
