# Agent Quality & Workflow — Phase 1: Loop Reliability (design)

**Status:** approved for implementation by explicit user request; live-baseline adoption claims remain gated (see §6)
**Date:** 2026-06-30
**Branch:** `feat/agent-quality-evals`
**Scope:** Phase 1 of the four-phase effort to improve the tailoring/generation agents.
The implementation is authorized; §6 remains the evidence gate for improvement claims.

---

## 1. Background

The tailoring loop (`run_tailor_review`, `tailor/workflow.py`) persists **every** round as a
`ResumeVersion` (`tailor/service.py` `_persist_rounds`), each carrying `round`,
`review_score`, `fact_check_passed`, and the critiques. The round surfaced downstream as
"the resume" is chosen by `latest_resume_version` (`tracking/repository.py:156`):
`ORDER BY round DESC, id DESC` — **highest round number wins; score and gate are ignored.**

Two consequences:

1. **Regression.** If round 2 is gate-passing at score 90 and a round-3 revision regresses to
   82, the default surfaced resume is the *worse* round 3.
2. **Latent safety bug.** If the **final** round failed the fact-check gate
   (`fact_check_passed=False` — reachable when `max_rounds` is hit on a gate-failing
   revision), `latest_resume_version` still surfaces it: a resume that failed the fact-lock
   gate becomes the default. The loop breaks on `verdict.passed` (`workflow.py:55`), so this
   only bites when no round fully passes — but it is real, and it violates the project's
   hard fact-lock invariant at the surfacing layer.

Crucially, the loop **already** early-exits when the whole verdict passes, so "stop looping
once everything passes" needs no work. And because all rounds are already persisted,
keep-best-round is a **selection-side** problem, not a loop rewrite.

## 2. Goals / Non-goals

**Goals**
- The resume surfaced by default is the **best round that respects the fact-lock gate**.
- A gate-failing round is never silently surfaced as the default (close the safety bug).
- Regression is **visible** (a marker), so the eval harness and the UI can see it.
- **Zero behavior change** to `src/resume_tailor_harness/tailor/` — all rounds still persist; the loop
  is untouched (this phase stays observation-respecting, like Phase 0).

**Non-goals (this phase)**
- No loop rewrite, no schema migration.
- No early-**stop** on regression (a cost lever → Phase 3, gated on cost numbers).
- No skip-passed-reviewers (unsound here → Phase 3, eval-gated).

## 3. Design (locked)

### 3.1 `best_resume_version` — read-side selection  *(decision Q2)*

New selector `best_resume_version(session, job_id)`:

- Among persisted `ResumeVersion`s for the job, pick the **highest `review_score` among rows
  with `fact_check_passed=True`**, tie-broken by latest `round` (then `id`).
- A missing `review_score` ranks below every valid score (`0..100`), rather than being
  conflated with score `0`.
- If **no** round passed the gate, fall back to `latest_resume_version` **and** surface a
  *"no clean round"* signal so callers can flag the job as needing attention rather than
  silently shipping a gate-failing resume.

Properties:
- Loop untouched; all rounds persist; the manual `select_resume_version` override is unchanged.
- Becomes the default surfaced by the JobDetail projection (today `queries.py:297` calls
  `latest_resume_version`).
- Honors the core invariant: a gate-failing round is never *silently* chosen.

### 3.2 Regression marker — detect + report only  *(decision Q3)*

Computed **read-side** (no schema migration), consistent with §3.1: a job is *regressed* when
the best gate-passing round is **not** the latest round (a later revision scored lower or broke
the gate). Surface it on the JobDetail projection and in the eval report; Phase 0's
`convergence` metric already measures rounds + improved/regressed per round.

The eval harness must judge and report the same surfaced round selected by the read side, not
unconditionally judge the final generated round. Otherwise Phase 1's stated verification is
impossible and later experiments can be scored against a resume the product will not show.

Phase 1 does **not act** on regression. Early-stop is a cost lever, deferred to Phase 3 where
the harness can prove it saves cost without hurting quality.

### 3.3 Dropped from Phase 1  *(decision Q4)*

"Early-exit on passed reviewers" leaves Phase 1:
- The loop already exits on a full verdict pass — nothing to add there.
- Skipping re-run of already-passed reviewers inside a revise round is **unsound**: `revise`
  rewrites the whole `ResumeContent`, so a carried-forward pass is stale (an ATS-keyword fix
  can hurt concision), and the fact-check **gate must always re-run** because revision is
  exactly when new fabrication can enter. Deferred to Phase 3 as an eval-gated cost lever.

## 4. Which eval metric proves it

- Phase 0 `convergence` (rounds-to-pass + improved/regressed) and the deterministic
  `provenance_ok` / `trap_avoided` checks.
- Concretely, after Phase 1: for every case the **surfaced** resume equals the best
  gate-passing round, and **no** case surfaces a `fact_check_passed=False` resume by default.
- The regression rate is **reported**, not yet reduced (reducing it is Phase 2's sharper
  revise + Phase 3's early-stop).

## 5. Risk

Lowest of the four phases. Read-side only; the loop and persisted data are unchanged, so the
change is fully reversible by pointing the projection back at `latest_resume_version`.

## 6. Evidence and adoption gate

Production adoption claims remain deferred until **both**:
1. The Phase 0 eval harness is green in CI, and
2. A baseline eval run is recorded — so "surfaced == best gate-passing" and the regression
   rate can be **verified** as an improvement against a baseline, not asserted.

The user explicitly authorized implementation before a paid live baseline exists. This does not
waive the evidence gate: no live improvement claim follows from offline tests alone.

## 7. Resolved implementation items

- Tie-break is score, then round, then id; `None` score ranks below `0`. The wire signal is
  `needsAttention` and the selected id is `bestResumeVersionId`.
- Render/export stays latest-rendered in this phase; changing an already-rendered artifact is a
  separate behavior.
- The pipeline critique projection switches to best; job detail exposes the selected id while
  retaining all versions; the eval harness uses the same selection semantics.
