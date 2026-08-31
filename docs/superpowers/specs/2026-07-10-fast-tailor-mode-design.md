# Fast Tailor Mode + Selective Tailoring — Design

**Date:** 2026-07-10
**Status:** Approved (brainstorm/grill session)
**Problem:** A single job's tailor run measured 3.5–10.5 minutes (run records
`data/runs/`, 2026-07-10). Worst case is ~19 LLM calls: optional match-plan +
draft + 3 rounds × 5 reviewers + 2 revisions, with the tailor/reviser writers
hardcoded to the premium tier (Opus) in `tailor/agents.py`.
**Goal:** Default tailoring at ~60–90 s per passing job — without weakening the
fact-lock invariant — plus user-selected subsets of approved jobs and a per-run
fast/deep choice on every surface.

## Measured baseline

| Evidence | Value |
| --- | --- |
| Tailor run 1 (1 job) | 3 m 32 s |
| Tailor run 2 (1 job) | 10 m 27 s |
| Panel concurrency | already parallel (`arun_panel`), `llm_concurrency=8` > 5 reviewers |
| Prompt caching | already on (`prompt_cache_enabled=True`) |

Per-job time ≈ `draft + N_rounds × (max(reviewer latencies) + revise)`. Rounds
are inherently serial (revise consumes critiques), so the levers are: fewer
rounds, fewer serial stages, and faster models on the long-output writer calls
— not more parallelism.

## Decisions (grill outcomes)

1. **Target:** the tailor review loop (not the eval harness, not discovery).
2. **Shape:** fast path by default; the full 5-reviewer/3-round panel becomes
   an opt-in deep mode. The fact-check gate stays in both modes.
3. **Merged advisory output:** per-dimension critiques from one call (not a
   single combined score) so downstream shape is identical between modes.
4. **Round policy:** fast mode reuses the existing loop with `max_rounds=2`
   and `early_stop_on_regression=true`; no new loop code.
5. **Mode surface:** two config files + a `--deep`/`deep` switch.
6. **Tiers:** fast mode runs Sonnet writers, Opus stays on the fact-check gate.
7. **V1 surfaces:** CLI, API, web UI toggle; cover letters inherit only the
   selection dialog (see Correction below).
8. **Tailor UX:** a launch dialog (job checklist + deep switch), not board
   multi-select.
9. **Validation:** per-stage timing instrumentation + a live fast-vs-deep spot
   check; full `make eval` comparison deferred until the judge is anchored.

## Correctness clarifications

- Writer/reviser tier values are boundary-validated to `cheap | mid | premium`;
  a typo must fail config loading instead of silently selecting another model.
- The launch dialog queries **all** approved jobs across the paginated pipeline,
  not only rows already loaded on the current board page. It remains open when
  a launch fails and represents loading, empty, and error states explicitly.
- The web implementation follows the repository's installed Base UI shadcn
  primitives and accessibility composition (`Field*`, `DialogDescription`,
  `Empty`, `Spinner`) rather than the illustrative raw layout below.

## 1. Config: fast default, deep escape hatch

- `config/review.yaml` (and its `.example`) becomes the **fast roster**:

  ```yaml
  max_rounds: 2
  early_stop_on_regression: true
  score_threshold: 85
  merged_advisory: true
  tailor_tier: mid
  reviser_tier: mid
  reviewers:
    - { name: fact-check,     gate: true,  weight: 0, model_tier: premium }
    - { name: ats-keyword,    gate: false, weight: 1, model_tier: mid }
    - { name: recruiter,      gate: false, weight: 1, model_tier: mid }
    - { name: hiring-manager, gate: false, weight: 1, model_tier: mid }
    - { name: concision,      gate: false, weight: 1, model_tier: mid }
  ```

  The four non-gate entries keep their names/weights as the source of truth;
  `merged_advisory: true` changes *how* they are produced (one call), not what
  they are.

- `config/review_deep.yaml` (+ `.example`) holds today's roster verbatim
  (5 separate reviewers, `max_rounds: 3`, hiring-manager premium, no writer
  tier overrides → premium writers).

- `ReviewConfig` gains three optional fields, all back-compatible:
  `merged_advisory: bool = False`, `tailor_tier: str = "premium"`,
  `reviser_tier: str = "premium"`. Existing customized `review.yaml` files
  load unchanged and behave exactly as before (they just *are* that user's
  fast config until they adopt the new example).

- `build_tailor_bundle` passes `config.tailor_tier` / `config.reviser_tier`
  through `model_for_tier` into `build_tailor_agent` / `build_reviser_agent`
  (both already accept `model_id`; callers simply start using it).

- Setup wizard (`setup/writer.py`, `preflight.py`, `screens.py`) writes both
  files from their examples.

## 2. Merged advisory reviewer

- When `merged_advisory` is true, `panel.py` issues **one** LLM call for all
  non-gate reviewers instead of N. Gate reviewers always run as separate calls
  with their evidence-scoped input.
- New output schema:

  ```python
  class MergedPanelReview(ExtensibleModel):
      critiques: list[ReviewCritique]
  ```

- The merged agent's instructions are composed from the configured non-gate
  reviewers' existing rubrics (reuse `_reviewer_instructions` per name,
  concatenated with a framing preamble). Model tier: `mid`.
- A validator/splitter checks the returned critiques cover **exactly** the
  configured non-gate reviewer names (no missing, no extras, no duplicates);
  a violation raises like any reviewer failure — the job is skipped and
  retried next run. On success the critiques ride into `aggregate()` as the
  same 4 named rows, so verdict weighting, persistence, UI, and evals are
  byte-identical between fast and deep modes.
- `workflow.py` is untouched; the branch lives in `_panel_inputs`/`run_panel`/
  `arun_panel`.

## 3. Surfaces

- **CLI:** `resume-tailor-harness tailor --deep` swaps the default config path to
  `config/review_deep.yaml`; an explicit `--review <path>` still wins.
- **API:** `TailorRunParams` gains `deep: bool = False` (camelCase `deep` on
  the wire); the runs router maps it to the deep path before calling
  `services/tailoring.run_tailoring`. Contract regenerated via
  `scripts/gen_ts_client.sh` (drift gate: `tests/api/test_openapi_contract.py`).
- **Web — tailor launch dialog:** clicking *Tailor* opens a dialog listing
  approved not-yet-tailored jobs (all pre-checked) with a **Deep review**
  switch (off by default) and a rough time estimate; submit posts
  `{ jobIds, deep }`. Backend `job_ids` targeting already exists
  (`resolve_targets`); the web simply never used it (`use-bulk-run.ts` sends
  `{approved: true}` today). The dialog replaces the blind
  "tailor all approved" action.
- **Cover letters — selection only (Correction):** the cover-letter loop has
  *no LLM review panel* — it is draft → deterministic provenance → revise,
  already capped at 2 rounds (~2–3 calls). There is nothing to make "fast",
  so no fast/deep config split exists for cover letters. They inherit the
  same launch-dialog pattern (job checklist → `{ jobIds }`) without a deep
  switch.

## 4. Timing instrumentation

- `run_tailor_review` / `arun_tailor_review` record wall-clock per stage
  (draft, per-round panel, per-round revise) using `time.monotonic()`.
- Durations land as an additive field on `TailorRound`
  (`stage_seconds: dict[str, float]`) — `ExtensibleModel` keeps old persisted
  rounds loadable — and a per-job total is logged at persist time so every
  future run is measurable for free (no DB migration).

## 5. Error handling & invariants

- **Fact-lock unchanged:** the deterministic provenance gate still
  short-circuits the panel; fact-check remains a blocking gate at premium
  tier in *both* modes. Inferred-skill rules are untouched.
- Merged-call schema violations raise; the job stays in its prior status and
  is retried next run (existing failure-isolation behavior).
- Still-failing final rounds surface as `needs_attention` via
  `select_surfaced`, exactly as today.

## 6. Testing & acceptance

- **Offline pytest:** config loading (fast file, deep file, legacy flat
  files), merged-reviewer instruction composition + splitter validation
  (missing/extra/duplicate names), writer-tier plumbing, CLI `--deep` path
  selection, API `deep` param mapping + contract drift gate, web dialog
  component tests (selection, deep toggle, payload).
- **Live acceptance (evidence gate):** tailor 2–3 real approved jobs in fast
  and deep. Pass criteria: fast median ≤ 90 s per passing job **and**
  ≤ ~50 % of the deep wall-clock, with a manual quality eyeball of both
  outputs. Timing comes from the new instrumentation.
- **Deferred:** `make eval` fast-vs-deep quality comparison waits for the
  judge-anchoring task (2026-07-10 skill-groups plan).

## Expected call budget

| Mode | Typical pass | Worst case |
| --- | --- | --- |
| Fast | 3 calls (draft, fact-check, merged advisory) ≈ 45–90 s | 6 calls ≈ 2–3 min |
| Deep (today) | 6 calls ≈ 2–4 min | ~19 calls ≈ 10+ min |

## Out of scope

- Discovery-pipeline latency (already concurrent; separate effort).
- Eval-harness runtime.
- Board-wide multi-select state (launch dialog covers v1).
- Cover-letter review architecture changes (none needed — see Correction).
