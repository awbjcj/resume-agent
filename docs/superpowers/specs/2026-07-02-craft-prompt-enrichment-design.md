# Craft-Informed Prompt Enrichment (Eval-Gated)

**Date:** 2026-07-02
**Status:** Approved design, pre-implementation
**Branch target:** new branch off `main` (builds on merged phases 1–3 loop work)

## Goal

Improve the quality of tailored resumes — stronger bullets, better keyword
coverage, recruiter-scannable structure — by distilling craft knowledge from six
resume-writing skill playbooks into role-targeted agent instructions. Quality is
primary; efficiency (first-round gate-pass rate, tokens per case) is tracked as a
side metric. Every change is measured with the existing eval harness (`evals/`,
`make eval`), which exists but has never been run.

Sources distilled (user skill library, `~/.claude/skills/`):
`resume-tailor`, `tech-resume-optimizer`, `resume-quantifier`,
`resume-bullet-writer`, `resume-ats-optimizer`, `resume-section-builder`.

Dropped as out of scope: `resume-version-manager` (the app's `ResumeVersion`
rows already supersede it) and `resume-formatter` (visual/ATS-safe layout belongs
to the render templates — a separate follow-up audit, not prompt work).

## Non-negotiable constraint: fact-lock filter

Some skill advice violates the fact-lock invariant (e.g. resume-quantifier's
"estimate numbers when exact data unavailable"). Every distilled instruction is
filtered to the truthful form: **quantify only when a profile fact supplies the
number**. Craft never overrides the integrity instructions; composition order is
always _integrity rules → craft block → house style_, and the existing
`STYLE_GUIDE_HEADER` precedence statement continues to apply.

## Order of operations

1. **Author ~4 craft eval cases** (offline authoring, no API cost) so the
   baseline covers them:
   - metric-rich profile → does the writer surface truthful numbers (X-Y-Z form)?
   - keyword-mismatch JD (profile uses different terminology for the same
     genuine skills) → does faithful terminology mapping happen?
   - over-long profile → selection and concision under the length budget.
   - career-changer profile → section ordering and summary targeting.

   Cases follow the existing schema (`id`, `profile_ref`, `jd_text`, `criteria`,
   `traps`, `must_cite`, `rubric`). Craft cases may carry light or no traps;
   their `rubric` entries emphasize craft dimensions so the judge's
   `output_quality` has room to move. New profiles go in `evals/profiles/` as
   needed.

2. **Anchor the judge + record the baseline.** Run `make eval` on the full
   (~12-case) set, in two arms: match-plan **off** and match-plan **on**
   (`config/review.match_plan.yaml`) — this settles the A/B the phase-2 spec
   left open, since we are paying for baseline runs anyway. Complete the human
   anchoring procedure in `evals/CALIBRATION.md` (~5 cases, blind rating; trust
   requires MAE < 10, no single error > 20). Retain report artifacts in
   `evals/reports/`.

3. **Distill and wire the craft blocks** (below).

4. **After-runs and ship decision** (below).

## Craft distillation — hybrid, role-targeted

New module `src/resume_tailor_harness/tailor/craft.py` holds per-role instruction lists.
`tailor/agents.py` appends them after the integrity instructions and before the
style guide. `config/style_guide.md` is untouched and remains the user's short
preference doc. The **fact-check reviewer receives no craft block** — it is the
safety gate, and holding it fixed keeps `trap_recall` attributable to writer
changes rather than checker drift.

| Constant                                                                                                                                                                                                                                                      | Distilled from                                                       | Injected into           |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ----------------------- |
| `CRAFT_WRITER` — X-Y-Z bullet form ("accomplished X measured by Y by doing Z"), strong action verbs, no duty-listing ("responsible for"), quantify only from profile facts, order sections by JD relevance, summary names the target role only when supported | bullet-writer, quantifier (filtered), section-builder, resume-tailor | tailor + reviser agents |
| `CRAFT_MATCH_PLAN` — must-have coverage first, evidence-strength ranking                                                                                                                                                                                      | resume-tailor                                                        | match-plan agent        |
| `CRAFT_REVIEWERS["ats-keyword"]` — exact term vs industry-equivalent, dual placement (skills list + in-context bullet), must-have coverage weighting                                                                                                          | ats-optimizer                                                        | ats-keyword reviewer    |
| `CRAFT_REVIEWERS["recruiter"]` — 6-second-scan heuristics: strongest evidence in top third, target-role clarity, scannable bullet lead-words                                                                                                                  | resume-tailor, tech-optimizer                                        | recruiter reviewer      |
| `CRAFT_REVIEWERS["hiring-manager"]` — scale/impact signals, depth vs breadth, seniority-consistent evidence                                                                                                                                                   | tech-optimizer                                                       | hiring-manager reviewer |
| `CRAFT_REVIEWERS["concision"]` — bullet-length caps, weak-verb/passive detection, one-page density                                                                                                                                                            | bullet-writer, formatter (text rules only)                           | concision reviewer      |

Scope guards:

- No roster, weight, threshold, or loop changes. `review.yaml` tuning becomes
  possible with baseline data but is a follow-up.
- No schema, API, or contract changes.
- Cover-letter agents untouched (follow-up once this pattern is proven —
  they currently have no eval coverage).

## Testing (offline, free)

- Unit tests on composition: integrity instructions first, craft block present
  per role, style guide last; fact-check reviewer composition contains no craft
  content.
- Fabrication-language guard test: no craft string may contain
  fabrication-adjacent phrasing (e.g. "estimate", "assume", "approximate the
  number") — the fact-lock filter made durable against future edits.
- Existing suite and `ruff check` stay green.

## Ship rule (measured, not vibes)

After the craft blocks land, rerun the same eval arms. Ship if all hold:

- mean judge `output_quality` improves by **≥ +5** (0–100) across the expanded set;
- `fact_check_trap_recall` and offline invariants (`trap_avoided`,
  `provenance_ok`) show **no regression**;
- mean tokens per case grows **≤ +20%**.

Match-plan flips default-on only if its arm wins under the same rule.
Otherwise iterate on the craft blocks or revert them; the eval artifacts make
either call cheap.

## Follow-ups recorded, not designed here

- Render-template ATS-parseability audit (resume-formatter knowledge).
- Cover-letter prompt enrichment + cover-letter eval cases.
- `review.yaml` weight/threshold tuning against the recorded baseline.
- Correct the stale `agent-quality-roadmap` memory (phases 0–3 are implemented;
  baseline still unrecorded until step 2 runs).
