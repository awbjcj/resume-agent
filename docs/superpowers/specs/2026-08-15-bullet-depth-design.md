# Bullet depth: selection floors, aspect vocabulary, and depth measurement

Date: 2026-08-15
Status: design approved, unimplemented
Scope: Spec A of three (see [Decomposition](#decomposition))

## Problem

Every tailored resume renders five bullets for the most recent role and one to
three for every role after it. Measured across all 30 stored `resume_versions`
in the active workspace, the pattern never varies:

```
v30 exp_bullets=[5, 1, 2, 2]   prj=[2, 2]
v27 exp_bullets=[5, 2, 3, 3]   prj=[2, 2]
v21 exp_bullets=[5, 1, 2, 2]   prj=[2, 4, 2]
v9  exp_bullets=[5, 1, 2, 2]   prj=[1, 1, 1]
```

Role #1 reaches the `max_bullets_per_role: 5` cap in 30 of 30 versions. Role #2
reaches it in 0 of 30. In the older workspace several versions rendered a single
experience and dropped the rest (`v72 exp_bullets=[5]`).

This is not model conservatism. `format_budget` (`tailor/length.py`) tells the
writer *"at most 5 bullets per role … about 20 bullets in total. Prefer the most
relevant facts; drop the rest."* — a cap, a shared global pool, and explicit
permission to drop. Spending the pool top-down is the correct response to that
instruction.

It is the third instance of one recurring bug in this codebase: **an unstated
floor reads as zero.** `LengthBudget`'s own docstring records the second
(`target_skills`, where the writer shipped ~17 of a ~335-skill profile), and
every provider's `thinking` config in `llm_runner.py` records the first
("unset means provider decides").

Nothing in the system can currently observe the problem either. `coverage_report`
measures skill breadth; no reviewer, gate, or score distinguishes `[5,1,1,1]`
from `[5,5,5,5]`.

### Supply

The two halves of the request are different problems.

Projects already hold the supply and under-render it:

| Project | Source highlights | Typically rendered |
| --- | --- | --- |
| Automated_Signal_Plot | 50 | 2 |
| Field-Trip Issue Analytics Pipeline | 13 | 2 |
| Deep Agent | 10 | 2 |
| MCP-Based CI/CD Orchestration Agent | 9 | 2 |
| Résumé Tailor Harness | 8 | 2 |

Experiences are genuinely starved:

| Experience | Source bullets |
| --- | --- |
| Aptiv — Vehicle System Triage Engineer | 9 |
| UMich — Graduate Student Instructor | 4 |
| Varian — Systems Engineering Intern | 5 |
| Contemporary Intelligent Mfg — Co-op | 3 |
| Shanghai MAXIEYE — Systems Engineering Intern | 3 |

The corpus explains the asymmetry: the only experience-bearing sources are
`resume.pdf`, `2025-Goal-Setting.md`, and `2026-Goal-Setting.md`. Every other
entry in `sources/` is a GitHub project dossier.

Bullets are fact-locked — `check_provenance` requires each
`TailoredBullet.provenance` to resolve to a real fact id — so missing bullets
cannot be generated. They must be elicited or extracted. That is Specs B and C.

## Decomposition

| Spec | Contents | Status |
| --- | --- | --- |
| **A (this document)** | Budget floors, aspect vocabulary, project highlight ids, depth measurement | designed |
| B | Coach depth topic + aspect-aware corpus re-extraction | not started |
| C | Per-role material intake (performance reviews, retros, Jira/Confluence exports) | not started |

A ships alone and delivers most of the outcome with no new facts: floors plus a
two-page budget move a resume from `[5,1,2,2] + [2,2]` to roughly
`[5,4,5,3] + [5,5]`.

A also defines B and C's input. A floor can only ever be `min(target,
available)`; A does everything possible with current supply and names precisely
what is missing, and B and C raise supply against that named gap. Measuring
before eliciting is the required order — otherwise the coach is guessing what to
ask.

## Design

### 1. Budget: floors clamped to supply

`LengthBudget` (`tailor/review_config.py`) gains floors alongside its caps:

```python
page_target: int = 2              # new
max_experiences: int = 5          # was 4
max_projects: int = 4             # was 2
max_evidence_owners: int = 8      # was 5
min_bullets_per_role: int = 5     # new
max_bullets_per_role: int = 7     # was 5
min_bullets_per_project: int = 4  # new
max_bullets_per_project: int = 6  # was 3
target_total_bullets: int = 40    # was 20
min_aspects_per_owner: int = 3    # new
```

The numbers are not the load-bearing part. A floor of 5 stated against a role
holding 3 source bullets is an instruction to invent, which `check_provenance`
rejects at the cost of a round. **The floor is therefore always clamped to
supply, computed deterministically per owner, and handed to the writer as a
table rather than as a rule requiring arithmetic.**

A new `format_depth_plan(facts, budget)` in `tailor/length.py` emits:

```
BULLET DEPTH PLAN (deterministic; per evidence owner):
- exp_aptiv  "Aptiv — Vehicle System Triage Engineer": 9 source → render 5–7
- exp_umich  "UMich — Graduate Student Instructor":    4 source → render 4 (supply-limited; do not invent)
- exp_varian "Varian — Systems Engineering Intern":    5 source → render 5
- prj_signal "Automated_Signal_Plot":                 50 source → render 4–6
```

The two page-budget renderings are independent: `templates/resume.typ` sets only
`#set page(margin: ...)` and Typst flows to as many pages as content needs. The
one-page constraint is entirely rhetorical, living in `format_budget`'s prompt
string, so `page_target: 2` costs no renderer change.

`format_budget` is rewritten to state the page target and the per-owner floors.
Its skills paragraph is unchanged — that asymmetry is already correct and
documented.

### 2. Aspect vocabulary

New module `profile/aspects.py` holding one closed enum:

```python
Aspect = Literal[
    "scope",         # scale: team size, system size, users, budget
    "technical",     # what was built and how
    "impact",        # measured outcome, metric, business result
    "collaboration", # cross-functional, stakeholder, partner teams
    "leadership",    # mentoring, owning, driving, deciding
    "process",       # methodology, standards, review, quality gates
    "tooling",       # automation, infra, developer experience
    "problem",       # debugging, incident, root cause, recovery
]
```

Fixed and closed, matching `Skill.category`'s `hard`/`soft`/`domain` and the
constellation taxonomy's fixed categories. Four consumers share this vocabulary
— the depth plan, the depth report, the coach (B), and the extraction prompts
(B) — and a derived or per-role vocabulary would let them silently disagree
about the same role. A fixed list also gives gap measurement a stable
denominator, so "7 of 8 aspects covered" is comparable across roles and over
time.

`Bullet` gains `aspect: Aspect | None = None`. Optional is deliberate: `None`
means unclassified, so every `facts.json` written before this change still
deserializes. Precedent: `ResumeContent.summary_provenance`.

Classification happens in two places:

- **At extraction time.** The fragment, synthesis, and project extractors assign
  an aspect to each bullet they emit, so new facts are classified for free.
- **Backfill.** `profile build` classifies any bullet still carrying
  `aspect=None` — about 24 experience bullets plus ~120 project highlights on the
  current corpus, one or two batched `cheap`-tier calls. The pass is idempotent
  and touches only unclassified bullets, so it is not the "strip and re-derive"
  treatment `profile build` gives inferred skills: an aspect already assigned is
  never recomputed, and a hand-corrected one survives a rebuild.

An unclassified bullet is never an error. It is simply invisible to the aspect
diversity rule and counted as `unclassified` in the depth report.

### 3. Project highlights become addressable facts

```python
class Project(FactItem):
    highlights: list[Bullet] = Field(default_factory=list)   # was list[str]
```

The field keeps its name; `highlights` is domain-accurate for a project and
renaming it would churn all eight consumers for no semantic gain.

A `mode="before"` validator coerces a legacy `list[str]` into `list[Bullet]`
with deterministic ids, so every stored `facts.json` loads unchanged. Precedent:
`ReviewConfig._portfolio_flag_alias`.

`index_facts` (`tailor/provenance.py`) then registers each project bullet id,
and `_referenced_uses` checks project bullet provenance against it.

**Why this is in scope.** Today `index_facts` records `index[proj.id] = proj`
and nothing more, so every project bullet cites the same project id and the gate
cannot distinguish a faithful highlight from a fabricated one — a project bullet
is verified only to the extent that "this project exists." That is tolerable at
2 bullets per project. Raising projects to 5 would multiply an unverifiable
claim surface by 2.5x, which is the wrong direction for a codebase whose central
invariant is fact-lock. The regression test that proves the fix — *a project
bullet citing a highlight id absent from the source project must fail
`check_provenance`* — is unwritable today, because there are no highlight ids to
be wrong about.

Eight consumers update: `profile/merge.py` (two sites — line 531 already holds
`Bullet` objects and discards their ids), `profile/synthesis.py`,
`profile/coach.py`, `profile/project_extractor.py`, and
`tailor/evidence_portfolio.py` (two sites).

To keep downstream code generic, one accessor —
`evidence_owners(facts) -> Iterable[OwnerRef]` yielding `(id, label, bullets)`
for experiences and projects alike. The depth plan, the depth report, and Spec
B's coach consume that instead of branching on record type.

### 4. Measurement: two reports, two audiences

**`profile/depth.py` — supply side.** `owner_depth(facts, target=10)` is a pure
function over facts: source-bullet count and aspect coverage per owner. It knows
nothing about a resume or a job description, and does not import tailor config
(the supply target is an `int` parameter, not a `LengthBudget`). Surfaced by a
new `profile depth` CLI command. Spec B's coach and Spec C's intake consume this
same function.

Note the two targets are different numbers and both come from the request:
**supply target 10+, render floor 5** — ten source bullets from different
aspects so the writer has a real menu to choose five from.

**`tailor/depth.py` — render side.** `depth_report(content, facts, budget)`
mirrors `tailor/coverage.py` in structure, including a
`DepthCritique(ReviewCritique)` runtime marker in the mold of `CoverageCritique`
so a configured reviewer named `bullet-depth` is never shadowed by the
deterministic measurement. Like `must-have-coverage`, `bullet-depth` is
deliberately **not** added to `RESERVED_REVIEWER_NAMES`.

Three findings, whose severities are the design:

| Finding | Severity | Audience |
| --- | --- | --- |
| Owner in the depth plan absent from the resume entirely | major | the reviser |
| Rendered < clamped floor **while supply exists** | major | the reviser |
| ≥3 bullets rendered under a single aspect | minor | the reviser |
| Source bullets < supply target | advisory | the **profile** surface, never the reviser |

The first row is a real observed regression, not a hypothetical: several stored
versions rendered `exp_bullets=[5]`, dropping three roles silently. A dropped
owner is distinct from an under-rendered one and must not be scored as a
vacuous pass.

The third row is the one most likely to be lost in implementation.
`tailor/CLAUDE.md` already records the cost of getting it wrong: must-have
coverage is advisory and never blocking, "because a one-page budget legitimately
forces cuts and a gate here would hand the writer an unwinnable round."
Under-supply is that failure exactly — the reviser cannot conjure a 10th source
bullet for MAXIEYE; only the profile owner can, through Spec B or C. Routing a
supply gap into the tailor loop would burn premium rounds on an unfixable
complaint.

`score` follows the coverage convention: the share of **depth-plan** owners
meeting their clamped floor. The denominator is the plan, not the resume —
scoring only the owners that made it onto the page would let a resume that
dropped three roles score 100%. An owner the budget itself excluded (beyond
`max_experiences` / `max_projects`) never enters the plan and so never enters
the denominator. A measurement or `None`, never `0`.

Depth is advisory, not a gate. Nothing here joins `DETERMINISTIC_GATES`.

### 5. Prompt wiring

`format_budget` and `format_depth_plan` both reach the tailor, the reviser, and
the advisory panel.

The depth plan is **not** wrapped in `prompt_blocks.untrusted()`. That fence is
for third-party text; the depth plan is deterministic self-generated ground
truth with the same standing as the coverage block, and fencing it would
contradict the instruction to obey it. It sits with the stable context (profile,
JD, coverage, depth plan) ahead of volatile round state, preserving the stable
composition order `compose_revise_input` depends on.

## Testing

Offline, with faked agents and no network, per the project's test contract.

- Floors clamp to supply; `format_depth_plan` marks a supply-limited owner and
  never states a floor above what exists.
- A legacy `list[str]` `highlights` payload loads, and its generated ids are
  stable across two independent loads.
- `index_facts` registers project highlight ids.
- **A fabricated project-highlight id fails `check_provenance`.** This invariant
  does not exist today and is the reason §3 is in scope.
- `depth_report`: under-render while supply exists → one major issue;
  under-supply → **no** reviser issue; ≥3 bullets sharing one aspect → one minor
  issue; unclassified bullets never raise.
- A resume that drops a planned owner entirely scores below 100% and raises a
  major issue — the `exp_bullets=[5]` regression observed in stored versions.
- `DepthCritique` and `CoverageCritique` coexist in one panel; neither shadows a
  configured reviewer of the same name, and neither is selected as a gate.
- An aspect-unaware `facts.json` (all `aspect=None`) produces a valid depth
  report with no aspect findings.

## Out of scope

- Any web UI. The supply gap surfaces via the `profile depth` CLI command and
  the stored critique JSON; Spec B's coach consumes `owner_depth` directly.
- The coach depth topic, aspect-aware re-extraction, and per-role material
  intake — Specs B and C.
- Renderer changes. Typst already flows past one page.
- Cover letters. `cover_letter/provenance.py` is untouched.
