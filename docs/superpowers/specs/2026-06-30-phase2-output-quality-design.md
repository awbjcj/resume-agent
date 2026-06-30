# Agent Quality & Workflow — Phase 2: Output Quality (design)

**Status:** approved for implementation by explicit user request; experiments remain default-off until baseline evidence exists
**Date:** 2026-06-30
**Branch:** `feat/agent-quality-evals`
**Scope:** Phase 2 of the four-phase effort. The **highest-risk** phase — its changes touch
how content is written and judged, so they can threaten the fact-lock invariant. Default-off
capabilities are authorized; §6 remains the evidence gate for adoption.

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
- Model output is untrusted: unknown fact ids are removed deterministically, empty support becomes
  a gap, and a requirement marked as a gap cannot retain supporting ids. An enabled workflow with
  no planner is a configuration error rather than a silent plan-off run.
- **Config-flagged, default off**, so the harness can A/B plan-on vs plan-off.
- **Adopt only if** it lifts `output_quality` / relevance **without** lowering
  `trap_recall` / `provenance_ok`.
- It is a new premium call → **cost**, justified only by a measured quality lift and re-examined
  in Phase 3's cost work.

### 3.2 Rubric-anchored reviewers  *(decision Q6)*

Add explicit **score-band definitions** behind a per-reviewer configuration switch so the
eval-named weakest reviewer can be re-anchored first, keeping each reviewer's dimension text:

```
90-100 : strong, ship-ready
75-89  : solid, minor gaps
60-74  : material gaps
<60    : disqualifying
```

- **Prompt-only at runtime.** The config contract gains an additive default-off boolean on each
  reviewer; there are no new calls and the change is fully A/B-able.
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

## 6. Evidence and adoption gate

Production adoption claims remain deferred until:
1. The Phase 0 eval harness is green in CI **and** a baseline eval run is recorded, and
2. **Phase 1 is merged** — the read-side best-round safety net should exist before quality
   changes that perturb how rounds score, so a quality experiment can never surface a worse or
   gate-failing round.

The user explicitly authorized the default-off capability work before a paid live baseline exists.
No reviewer is re-anchored in the production config and match-plan remains off until the recorded
eval gates are satisfied.

## 7. Resolved implementation items

- `MatchPlan` lives under `models/` and remains transient; the eval artifact records the effective
  config and usage, while normalization makes the transient boundary safe.
- Score-band wording is terse and enabled per reviewer. No target is selected without real
  `panel_agreement` numbers.
- Where the new tailor input documents the plan (prompt-injection framing must treat the plan
  as data, like all other inputs).
