# Tailoring pipeline developer reference

Migrated from the project root `CLAUDE.md` (2026-08-15, CLAUDE.md split) — loads only when working under `src/resume_agent/tailor/`.

### Fact-lock

Every bullet on a tailored resume must trace back to a fact in
`data/profile/facts.json`. The `fact-check` reviewer in `review.yaml` is a
**hard gate** (not scored) — any unsupported claim fails the round. Agents
rewrite and reframe; they never invent.

Inferred skills (`Skill.inferred=true`) are evidence pointers: each carries
`evidence_fact_ids` resolving to literal facts. They may appear as
skills-section tokens (hard skills) and guide match-plan emphasis, but never
justify bullet or summary claims. Adjacent-tier matches (same ClusterMap theme,
not same canonical token) are never claimable as the JD's own term.

---

## Review/scoring design notes

- **Tailoring is fast by default.** `config/review.yaml.example` materializes as
  the two-round roster with mid-tier writers and one `MergedPanelReview`
  advisory call; the premium fact-check gate remains separate. Deep mode uses
  `config/review_deep.yaml` through CLI `tailor --deep` or API `deep: true`.
  Advisory critiques are split back into their configured named rows, and each
  `TailorRound` records draft/panel/revise wall-clock seconds.
- **A round's score is a measurement or it is `None` — never `0`.**
  `PanelVerdict.aggregate_score` is the weighted mean over non-gate reviewers;
  with no weighted critique the mean is _unknown_, so it is `None` and `passed`
  falls back to `gate_passed`. It used to be `0`, and the panel used to be
  skipped whenever the provenance gate failed, so 25% of stored rounds reported
  `0` for a resume that was never measured. **The panel now always runs** — a
  broken citation says nothing about quality, and skipping it left the reviser
  with no advisory feedback for that round. `services/revision.py` and
  `evals/metrics.py` already modelled the score as optional; the runtime is the
  one that disagreed. `scripts/tailor_health.py` reports the distribution.
- **The writer only ever sees facts it may render.** `renderable_profile()`
  (`tailor/provenance.py`) strips inferred soft/domain skills from the profile
  handed to the tailor and reviser, because `check_provenance` rejects them
  wherever they are cited. The gate still indexes the **full** facts, so a
  forbidden id arriving via a match plan or a hand-edited resume still fails —
  this narrows the menu, it does not relax the rule. Match-plan input is
  deliberately unfiltered (inferred skills legitimately guide emphasis).
- **The summary carries its own provenance.** `ResumeContent.summary_provenance`
  lists the fact ids the summary draws on, and rides the same `_referenced_uses`
  path as every other citation (as an `entity` use, so an inferred pointer there
  is rejected). Without it the gate could not check the summary at all and
  `resolve_evidence` showed the reviewer only facts cited _elsewhere_, so a true
  summary claim read as unsupported. Empty is valid — versions stored before the
  field still validate.
- **The reviser gets the job description; `jd_text` is required, not defaulted.**
  It is handed `ats-keyword` and `hiring-manager` critiques, which are entirely
  about fit, so without the JD it was being asked to fix complaints it could not
  read. `compose_revise_input` orders stable context (profile, JD) before
  volatile context (revision base, latest reviewed attempt, latest verdict) to
  keep the stable composition order intact across rounds. A revision builds on
  `_best_base` — the best round so far by (gate-clean, score) — not the last, so
  a regressed round cannot become the base for the next one. Feedback is always
  taken from the immediately preceding round, however; if that round is not the
  selected base, its resume is included as diagnostic-only context. Reviewer
  pass/fail, score, summary, issues, suggestions, and failed-gate names all reach
  the reviser, and a failed gate with no issue detail remains an explicit
  blocking item rather than disappearing from the loop.
- **A citation slip is not a quality round.** A round that fails _only_ on
  provenance ids does not consume one of `max_rounds`, up to
  `ReviewConfig.provenance_retry_budget` (default 1; `0` reproduces the old
  counting). `_is_citation_slip` requires provenance to be the sole failing gate
  _and_ a real panel score, so a resume the panel also rejects still pays for its
  round.
- **Gate failures are named, not conflated.** `ResumeVersion.fact_check_passed`
  is the AND of every gate, so it cannot say which one blocked — it labelled a
  provenance-only failure as "Fact-check failed" on rounds where fact-check never
  ran. `verdict.failing_gate_names` owns the rule and `ResumeVersionOut.failedGates`
  carries it to the UI.
- **A mechanically-provable violation never costs a premium round.**
  `skill-naming` and `numeric-evidence` join `provenance` in
  `DETERMINISTIC_GATES` and run before the panel, so the reviser sees them in
  the round they occurred. `skill-naming` legalizes a displayed name only from
  the _cited fact's_ own name/aliases — the cluster map's alias table is
  deliberately not consulted, because it maps a token to a canonical cluster
  token, which is exactly the adjacent-skill rename fact-lock forbids. Only a
  **compound** name blocks (two or more segments, one unresolved: the writer
  named a technology it did not cite); an atomic mismatch (`AWS` for `Amazon
Web Services`) is advisory, since `CRAFT_WRITER` allows it and no alias table
  is complete. `numeric-evidence` blocks any standalone quantity absent from the
  cited fact, tokenized conservatively so `p95`, `L1–L3`, `GPT-4` and `C++` are
  never claims while `$50K` and `95%` are. `_is_citation_slip` therefore denies
  the free provenance retry to a round that also failed a new gate, which is
  correct — neither is a citation slip.
- **The three gate names are declared by the modules that emit them.**
  `RESERVED_REVIEWER_NAMES` (`review_config.py`) imports `PROVENANCE_REVIEWER` /
  `SKILL_NAMING_REVIEWER` / `NUMERIC_EVIDENCE_REVIEWER` rather than restating the
  literals, and `DETERMINISTIC_GATES` is that frozenset. A configured reviewer
  may not claim one of those names; `must-have-coverage` is deliberately _not_
  reserved, because it is also a legal configured reviewer — the deterministic
  measurement is kept out of gate and weighted-score selection by its runtime
  `CoverageCritique` type, never by its name.
- **Must-have coverage is authoritative input and an advisory measurement, not
  a gate.** `format_coverage` renders the `SkillMatchContext` the pipeline
  already computes into the writer's, reviser's, and advisory panel's prompts
  (F1: it used to be computed and discarded under `match_plan_enabled: false`).
  Every line names its tier, because one header covers must-have, nice-to-have,
  and tech-stack rows and ordering alone cannot distinguish them.
  `coverage_report` measures the other direction and each unrendered evidenced
  must-have becomes a **major** issue — never blocking, because a one-page
  budget legitimately forces cuts and a gate here would hand the writer an
  unwinnable round.
- **Under-inclusion of skills has to be measurable, or nothing can see it.**
  `coverage_report` originally skipped every `match.source != "must"`, so the
  only observable failure was claiming too little of the JD's *must-have* list.
  A resume could omit every evidenced nice-to-have and tech-stack skill in the
  profile and no gate, reviewer, or score registered it — measured on live data,
  the writer shipped a median of **17 skills against a 335-skill renderable
  profile**. Two changes close it, and they are a pair: `LengthBudget` gained
  `target_skills` / `max_skills_per_category` (a **target**, not a cap — every
  other budget field is a cap, and the writer was applying cap semantics to
  skills because nothing said otherwise), and `coverage_report` now tallies
  `supporting_*` for the nice/tech tiers. `score` remains the **must-have**
  rendered share so stored rounds' health metrics keep their meaning;
  supporting omissions ride as one **bounded** issue naming at most
  `_SUPPORTING_SAMPLE` (12) requirements plus a remainder count, because one
  issue per omission would bury every other reviewer in the reviser's prompt.
  The prompt states *why* breadth is cheap — the Typst `skills-block()` renders
  one comma-joined line per category, so ~40 entries cost about five lines —
  since "target a single page" is otherwise read as a reason to cut skills like
  bullets. Listing an adjacent skill under **its own true name** is expected and
  legal; renaming it to the JD's term still fails `skill-naming`.
- **The coverage block is never fenced as untrusted; the JD always is.**
  `prompt_blocks.untrusted()` is the one fence, and it is for third-party text.
  Wrapping the coverage block in it would contradict `CRAFT_REVIEWERS`'
  `ats-keyword` rule that "MUST-HAVE COVERAGE is authoritative" in the very same
  prompt. Deterministic self-generated ground truth and attacker-influenced text
  need opposite framings.
- **`score_threshold` and `match_plan_enabled` are unmeasured.** Both shipped
  rosters now set `score_bands: true` on every advisory reviewer (five private
  scales were being averaged against one fixed threshold) and
  `early_stop_on_regression: true`. The threshold stays at 85 and the match plan
  stays off until the eval arms in `evals/RESULTS.md` are actually run — see the
  2026-07-27 baseline entry there.
- **A cap without a floor reads as zero.** `LengthBudget` gives each selected
  evidence owner a source-clamped render range through `format_depth_plan`.
  The writer, reviser, and advisory reviewers receive that deterministic block;
  a floor can never demand more bullets than the profile holds.
- **Depth has two audiences.** `profile/depth.py` reports source supply and
  aspect gaps to the profile owner. `tailor/depth.py` reports only fixable
  under-rendering to the reviser as an advisory, runtime-marked
  `DepthCritique`; `bullet-depth` is deliberately neither a deterministic gate
  nor a reserved configured-reviewer name. Its score denominator is the depth
  plan, so a dropped owner cannot disappear from the measurement.
