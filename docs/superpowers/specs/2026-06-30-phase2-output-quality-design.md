# Agent Quality & Workflow — Phase 2: Output Quality (design)

**Status:** approved (design); **implementation plan deliberately deferred** (see §6)
**Date:** 2026-06-30
**Branch:** `feat/agent-quality-evals`
**Scope:** Phase 2 of the four-phase effort. The **highest-risk** phase — its changes touch
how content is written and judged, so they can threaten the fact-lock invariant. Design-only;
the TDD plan is deferred until the gates in §6 are met.

---

## 1. Background

- **The tailor is single-shot** (`tailor/tailoring.py:30`): one premium call gets profile +
  criteria + JD + budget and emits `ResumeContent` directly. Selection, framing, ordering,
  budget, and provenance are all done in one pass — there is no explicit pre-draft strategy.
- **Reviewers are self-calibrated with no shared anchors** (`tailor/agents.py:124`:
  *"Calibrate score across the full 0-100 range"*). Each reviewer privately decides what a
  given score means, so scores aren't comparable across reviewers and don't reliably track
  true quality. This is exactly what Phase 0's `panel_agreement` / "weakest reviewer" measures.
- **The revise input is a flat dump** (`tailoring.py:54-64`): all issues then all suggestions,
  concatenated. The reviser *instructions* say "fix blocking first," but the *input* carries no
  severity structure or per-target grouping. And `revise` rewrites the **whole**
  `ResumeContent`, so a fix to one bullet can collaterally damage another — this is the root
  cause of the regression Phase 1 only observes.

## 2. Goals / Non-goals

**Goals**
- Measurably lift relevance/quality (Phase 0 `output_quality` + per-dimension scores).
- Reviewer scores **track true quality** (`panel_agreement` rises, especially for the
  eval-named weakest reviewer).
- Preserve the fact-lock invariant **unconditionally** (`provenance_ok`, `trap_avoided`,
  `trap_recall` must not fall).

**Non-goals (this phase)**
- No change to the authority of the fact-check gate or provenance gate.
- Match-plan stays **default off** until evals justify the extra call.
- The surgical patch protocol (§3.3) is **not** adopted this phase.

## 3. Design (locked)

### 3.1 Match-plan — a separate fact-id-referential agent  *(decision Q5)*

A new **pre-draft** agent emits a structured plan, then the tailor writes from it:

```
MatchPlan:
  requirements: [
    { jd_requirement: str, supporting_fact_ids: list[str], emphasis: str, gap: bool }
  ]
```

- **Referential, not prose.** The plan names profile **fact ids** + emphasis/gap notes; it
  never contains claim text. It cannot smuggle a fabricated claim into the resume because the
  writer still emits provenance and the existing provenance gate + fact-check reviewer run on
  the **written output** regardless of the plan.
- **Config-flagged, default off**, so the harness can A/B plan-on vs plan-off.
- **Adopt only if** it lifts `output_quality` / relevance **without** lowering
  `trap_recall` / `provenance_ok`.
- It is a new premium call → **cost**, justified only by a measured quality lift and re-examined
  in Phase 3's cost work.

### 3.2 Rubric-anchored reviewers  *(decision Q6)*

Add explicit **score-band definitions** to `_COMMON_REVIEWER_INSTRUCTIONS` so all reviewers map
to one scale, keeping each reviewer's dimension text:

```
90-100 : strong, ship-ready
75-89  : solid, minor gaps
60-74  : material gaps
<60    : disqualifying
```

- **Prompt-only.** No schema change, no new calls, fully A/B-able.
- **Targeted, not blanket.** Re-anchor the eval-named weakest reviewer (lowest
  `panel_agreement` / `trap_recall`) **first**; only broaden if the harness shows the others
  also miscalibrated. The weakest reviewer is only known after a real eval run, so this is
  data-driven.

### 3.3 Sharper revise — severity-structured input + preserve-unimplicated  *(decision Q7)*

Restructure `compose_revise_input`:
- Group issues **blocking → major → minor** with precise locations.
- Require each **blocking** issue be addressed explicitly.
- Reinforce the rule: **copy unimplicated records byte-for-byte unchanged.**

This is input-composition only — no schema change, low risk. It **reduces (not eliminates)**
regression and pairs with Phase 1's read-side best-round safety net.

**Deferred candidate (not this phase):** a **surgical patch protocol** where `revise` returns
only changed records, merged onto the prior resume, so untouched records *cannot* regress. This
is the real root-cause fix for regression, but it needs a patch schema + merge logic +
partial-output handling — bigger blast radius. Revisit eval-gated.

## 4. Which eval metric proves it

- `output_quality` (mean + per dimension) — must rise.
- `panel_agreement` per reviewer — must rise for the re-anchored reviewer.
- `trap_recall` + `provenance_ok` — must **not** fall (the fact-lock guard; this is the
  highest-risk phase precisely because these could regress).
- Match-plan A/B: plan-on vs plan-off on the same cases.

## 5. Risk

Highest of the four phases. Mitigations: the fact-lock gate and fact-check reviewer remain the
authority on every written output; match-plan is referential and default-off; rubric and revise
changes are prompt/input-only and reversible; every change is gated on `trap_recall` /
`provenance_ok` not regressing.

## 6. Gating (when the implementation plan may be written)

Deferred until:
1. The Phase 0 eval harness is green in CI **and** a baseline eval run is recorded, and
2. **Phase 1 is merged** — the read-side best-round safety net should exist before quality
   changes that perturb how rounds score, so a quality experiment can never surface a worse or
   gate-failing round.

## 7. Open items for the implementation plan

- `MatchPlan` model location and schema; whether the plan is **persisted** (legibility for
  the eval/convergence story) or transient.
- Exact score-band wording (kept terse to avoid over-steering reviewers).
- The weakest-reviewer **target** is only knowable after a real eval run — the plan must be
  written against actual `panel_agreement` numbers, not guesses.
- Where the new tailor input documents the plan (prompt-injection framing must treat the plan
  as data, like all other inputs).
