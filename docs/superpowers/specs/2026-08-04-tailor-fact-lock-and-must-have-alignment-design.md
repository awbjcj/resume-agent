# Tailored resume quality: deterministic fact-lock gates and must-have alignment

**Status:** Design
**Date:** 2026-08-04
**Supersedes nothing.** Builds on `2026-07-27-tailor-scoring-and-fact-lock.md`
(tasks 1–10, 12–14 implemented; task 11 and the eval arms remain outstanding).

## Problem

Two symptoms, reported against the deployed instance (Railway service
`d6581b90`, running `5ff1cd1b` — current `main`, so the 2026-07-27 repair is
live):

1. The fact-check gate fails on nearly every round.
2. Tailored content does not align with the job's must-have requirements.

The 2026-07-27 round fixed the *structural* defects behind the first symptom's
mislabelling (fabricated `0` scores, the panel being skipped, the reviser never
seeing the JD, revisions building on regressed rounds). It did not change what
the writer produces. These two symptoms are what remains.

## Evidence

`scripts/tailor_health.py` against the workspace database
(`data/users/1398ad91b2b2/resume_agent.db`, 77 versions / 26 jobs,
2026-07-16 → 07-20):

| metric | value |
| ------ | ----- |
| gate-clean rounds | 8 / 77 |
| fact-check-only failures | 50 |
| provenance-only failures | 19 |
| rounds failing **both** gates | 0 |
| jobs reaching `score_threshold: 85` | 0 / 26 |
| ats-keyword mean | 55.1 |
| hiring-manager mean | 51.7 |

The 142 blocking fact-check issues resolve into four mechanisms:

**M1 — compound skill entries citing one fact id.** `"Unit Testing (pytest,
MATLAB Unit Test)"`, `"Jira & Confluence REST APIs"`, `"AI/LLM Agents &
LangChain"`, `"Data Analysis & Visualization"`. Every compounded half exists in
`facts.json` as its own skill fact with its own id (`confluence api`,
`matlab unit testing`, `data visualization`, `langchain` all verified present).
The writer had two legal single-fact entries available and merged them instead.

**M2 — invented outcomes.** `"saving hours of manual reporting effort"`,
`"reducing preparation time"`, `"improving adoption among non-technical
users"`, `"Reduced test planning effort"`. Largest bucket (53 of 142 tagged
metric/number).

**M3 — scope creep.** `"near real-time triage visibility"` rendered as
`"real-time dashboard"`; `"verification purposes"` rendered as `"L2 ADAS
collision warning"`.

**M4 — derived arithmetic in the summary.** `"3+ years"`, `"5+ years"` —
computed from employment dates that no fact states as a duration.

Two further findings, from the code rather than the data:

**F1 — the deterministic must-have answer is computed and discarded.**
`build_skill_match_context(criteria, matrix, cluster_map)`
(`profile/matrix.py:190`) maps every `must_have_skills` entry to
`covered` / `adjacent` / `gap` with the matching `MatrixRow` and its
`evidence_fact_ids`. `tailor/service.py:194` computes it on every tailor run
and threads it into `workflow.py` — where it is consumed **only** under
`config.match_plan_enabled`, which is `false`. No reviewer, and not the writer,
ever sees it.

**F2 — no reviewer receives `JobCriteria`.** `compose_lean_review_input` gives
the advisory panel only `jd_text` and resume stats; `compose_revise_input`
gives the reviser only `jd_text`. `ats-keyword`'s rubric instructs it to
"distinguish a missing keyword from a genuinely missing qualification" while
supplying no data with which to do so, so it penalizes the resume for skills
the candidate does not have.

**F3 — the local `config/review.yaml` is stale.** The file is gitignored, so
the 2026-07-27 repair updated only `config/review.yaml.example`. The live local
file lacks `score_bands: true` on all four advisory reviewers and lacks
`style_guide_path`. Deployed workspaces are seeded from the `.example` by
`provision_workspace` and are unaffected.

## Non-goals

- `score_threshold: 85` and `match_plan_enabled: false` are **not changed**.
  `evals/RESULTS.md` records that both decisions are gated on eval arms that
  have not run. This design routes coverage data around the match plan rather
  than enabling it, so it does not consume that decision.
- Profile-side enrichment (capturing true outcomes through the coach so
  truthful impact claims exist at all) is the honest root cause of M2 but is a
  different subsystem with a different feedback loop. It gets its own spec.
- No change to `ResumeContent`'s schema. M1 initially looked like a
  single-`provenance` schema hole; it is not, because `skills` is already
  `dict[str, list[TailoredSkill]]` and the dict key is the category line, so
  `{"Testing": [pytest, MATLAB Unit Testing]}` expresses what the writer was
  attempting.

## Design

### 1. Two new deterministic gates

`tailor/verdict.py` already declares the extension point:

```python
DETERMINISTIC_GATES = frozenset({PROVENANCE_REVIEWER})
```

Adding a name to that set makes `aggregate`, `failing_gate_names`, and
`ResumeVersionOut.failedGates` recognize it with no further wiring, and
`_is_citation_slip`'s `failed == {PROVENANCE_REVIEWER}` test automatically
**denies** the free provenance retry to a round that also failed a new gate —
which is correct, since neither new gate is a citation slip.

Both gates run in `workflow.py` alongside `provenance_critique`, before the
panel, and their issues join `critiques` so the reviser receives them in the
same round they were detected.

#### Gate `skill-naming` (targets M1)

For each `TailoredSkill`, the displayed `name` must resolve to the cited fact's
own `name` or one of its `aliases`, compared under `normalize_skill`.

The cluster map's alias table is deliberately **not** consulted. It maps a token
to a canonical *cluster* token, which is precisely the "adjacent skill" relation
fact-lock forbids a writer from claiming as the job's own term — consulting it
would legalize exactly the renames this gate exists to catch. Only the cited
fact speaks for itself.

Two outcomes, deliberately asymmetric:

- **Compound names block.** When the name splits on `&`, `/`, `,`, ` and `, or
  a parenthesized list into two or more segments and any segment fails to
  resolve to the cited fact, the model named a technology it did not cite.
  That is structurally provable, so it is a blocking issue. The suggestion
  names the fact id that would legalize the extra segment as its own entry.
- **Atomic mismatches do not block.** `"AWS"` for a fact reading `"Amazon Web
  Services"` is explicitly legal under `CRAFT_WRITER`, and the alias map cannot
  be trusted to know every such pair. An unresolved atomic name is a **major**
  issue for the reviser, and the LLM fact-checker continues to judge it.

The gate passes when no blocking issue is raised; major issues do not fail it.

#### Gate `numeric-evidence` (targets M2 and M4)

Every standalone numeric token in a bullet must appear in the text of that
bullet's cited fact. Summary numbers check against the union of the facts named
in `summary_provenance`.

Tokenization is conservative: a token counts only when it is not welded to
letters. `267`, `430+`, `9`, `3+`, `500ms`, `95%` are checked; `p95`, `L1–L3`,
`S3`, `GPT-4`, `C++`, `OAuth2` are skipped. Comparison normalizes thousands
separators. Any unmatched token is blocking.

This catches M4 by construction: `"3+ years"` fails because no cited fact
contains a `3`. It fires before any LLM call, so the reviser receives it in
round 1 instead of a premium fact-check round being spent to discover it.

#### Effect on `fact-check`

Its remaining job is what only an LLM can do: scope creep (M3), causality, and
unquantified outcome language. Its pass rate becomes an interpretable signal
rather than a measure of mechanically-detectable violations.

### 2. Must-have coverage as ground truth

New module `tailor/coverage.py`, no agents.

**`format_coverage(ctx: SkillMatchContext) -> str`** renders the existing
context as a block, must-haves before nice-to-haves:

```
MUST-HAVE COVERAGE (deterministic; fact ids are evidence pointers, not claims):
- Python — covered — facts: a1b2c3, d4e5f6
- LangChain — covered — facts: 8142e67c1ad0
- Kubernetes — gap — no profile evidence; do not claim or imply
- Terraform — adjacent (Infrastructure as Code) — may inform emphasis, never named
```

It is wired into three composers, each in the **stable** region of the prompt
so fixed job context keeps the same composition order ahead of round-specific
content:

- `compose_tailor_input` — after `JOB CRITERIA`
- `compose_revise_input` — after `JOB DESCRIPTION`
- `compose_lean_review_input` — so the advisory panel has ground truth (F2)

A missing skill matrix or cluster map degrades to no block, never an error.
The production path already guarantees neither is missing: `tailor_jobs` is the
sole production entry point (`services/tailoring.py:87` — `tailor_job` is used
only by tests), and it is always called with both `skill_matrix` and
`cluster_map`. The degradation path therefore exists for tests and for a
workspace whose profile has not been built, not for the normal run.

**`coverage_report(content, ctx) -> CoverageReport`** measures the other
direction: of the must-haves marked `covered`, which actually appear in the
produced resume, as a skills entry or inside a bullet. Each covered must-have
absent from the output becomes a deterministic **major** issue for the reviser.
It is not a gate: the one-page length budget legitimately forces cuts, and a
gate here could hand the writer an unwinnable round.

The `ats-keyword` rubric gains one authoritative instruction:

> MUST-HAVE COVERAGE is authoritative. A requirement marked `gap` is a
> qualification the candidate genuinely lacks — never score it as a missing
> keyword and never suggest adding it. Score coverage only over requirements
> marked `covered`.

### 3. Prompt changes

Each is tied to an observed mechanism, and most enable a gate rather than
substituting for one.

| Change | Site | Targets |
| ------ | ---- | ------- |
| One skills entry cites exactly one fact; group related skills with the `skills` dict category key | `_TAILOR_INSTRUCTIONS`, `_REVISER_INSTRUCTIONS` | M1 (makes `skill-naming` learnable) |
| Never state tenure, duration, or total years unless a fact states it | `_TAILOR_INSTRUCTIONS`, `_REVISER_INSTRUCTIONS` | M4 |
| Never name a beneficiary, saving, adoption, or improvement the cited fact does not state | `_TAILOR_INSTRUCTIONS`, `_REVISER_INSTRUCTIONS` | M2 |
| Rebalance the bullet rule so the no-number branch is not a consolation prize | `CRAFT_WRITER` | M2 |
| MUST-HAVE COVERAGE is authoritative | `CRAFT_REVIEWERS["ats-keyword"]` | F2, ats-keyword mean |
| Sync live file to `config/review.yaml.example` | `config/review.yaml` | F3 |

`CRAFT_WRITER` and `CRAFT_REVIEWERS` changes remain bound by
`tests/test_tailor_craft.py`: craft guidance teaches HOW to write, never WHAT
is true, and may not contain wording that authorizes embellishment.
`prompts/registry.py` projects the production instruction compositions, so its
snapshot expectations move with these edits.

### 4. Measurement

`scripts/tailor_health.py` gains:

- per-gate counts for `skill-naming` and `numeric-evidence`, alongside the
  existing `provenance` and `fact-check` counts
- a must-have coverage rate from the persisted `CoverageCritique`: its
  serializable extensible metadata carries `covered_total` and
  `rendered_total`, and `tailor_health` sums those totals across stored rounds
  for weighted rendered-over-covered coverage
- for legacy score-only critiques where those totals are absent, the
  `must-have-coverage` value falls back to the reviewer-score mean

Both are deterministic, so the before/after comparison needs no LLM judge —
which matters because `evals/CALIBRATION.md` records the judge as un-anchored,
supporting only relative arm-to-arm claims. The script reads the stored critique
JSON read-only; it does not join `jobs.criteria_json` or change frozen settings,
`ResumeContent`, or other persisted model schemas.

Re-measure against the deployed workspace database after the change and append
the result to `evals/RESULTS.md`.

## Success criteria

Measured by `scripts/tailor_health.py` on a post-change run of comparable size:

1. Zero rounds fail on a compound skill entry — the class is unrepresentable in
   a passing round.
2. Blocking `fact-check` issues in the metric/number bucket fall substantially,
   since `numeric-evidence` intercepts them before the panel.
3. The ats-keyword mean rises without any increase in fact-check failures — the
   test that alignment improved through ground truth rather than through
   keyword stuffing.
4. `fact-check` failures that remain are concentrated in M3-style scope creep,
   the class it is uniquely able to judge.

## Testing

Offline throughout; no API key or network, matching the existing suite.

- `skill-naming`: compound name with one cited fact → blocking; the same two
  skills as separate entries → clean; alias-legal atomic rename (`AWS` for
  `Amazon Web Services`) → major, gate still passes.
- `numeric-evidence`: number present in the cited fact → clean; number absent →
  blocking; `p95` / `L1–L3` / `GPT-4` / `C++` → not treated as numeric claims;
  summary number checked against the `summary_provenance` union.
- `verdict`: a round failing a new gate is not granted the provenance free
  retry; `failedGates` names the new gate.
- `coverage`: block formatting for each of `covered` / `adjacent` / `gap`;
  missing matrix degrades to no block; `coverage_report` counts a must-have
  rendered in a bullet as covered.
- composer tests pinning the coverage block's position, so stable-before-volatile
  ordering does not silently regress.

## Risks

- **False blocks from `numeric-evidence`.** A truthful number the fact states
  in a different form (`"nine"` vs `"9"`, `"~500"` vs `"500"`) blocks a round.
  Mitigated by conservative tokenization and normalization; the reviser can
  restate the bullet using the fact's own wording, so a false block costs a
  round rather than a truth.
- **Alias map incompleteness.** Handled by design: only compounds block, and
  atomic mismatches degrade to advisory.
- **Prompt and code changing together** makes attribution harder in the
  before/after. Accepted: gate `skill-naming` is unlearnable without its
  instruction, so shipping the code alone would raise the failure rate rather
  than lower it.
