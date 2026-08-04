# Tailor Fact-Lock Gates and Must-Have Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the tailored-resume loop from failing its fact-check gate on
mechanically-detectable violations, and give the writer and reviewers the
must-have coverage data the pipeline already computes and discards.

**Architecture:** Two new deterministic gates (`skill-naming`,
`numeric-evidence`) register through the existing `DETERMINISTIC_GATES` seam in
`tailor/verdict.py` and run in `tailor/workflow.py` beside `provenance_critique`,
before the LLM panel. A third deterministic, non-gating critique
(`must-have-coverage`) measures how much of the JD's evidenced must-have list
reached the resume. The `SkillMatchContext` that `tailor/service.py` already
builds on every run is rendered into a text block and injected into the writer,
reviser, and advisory-panel prompts.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, SQLModel/SQLAlchemy, agno.
Frontend untouched — `failedGateLabel` in `web/src/features/job/VersionRow.tsx`
joins gate names generically, so new gate names surface with no web change.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-tailor-fact-lock-and-must-have-alignment-design.md`
- Tests run offline. No API key, no network. Run with
  `.venv/Scripts/python.exe -m pytest`.
- Lint with `ruff check` before every commit.
- **Do not change `score_threshold: 85` or `match_plan_enabled: false`** in any
  config. Both are frozen pending eval arms recorded in `evals/RESULTS.md`.
- **Do not change `ResumeContent` or any `models/` schema.** The skills field is
  already `dict[str, list[TailoredSkill]]`; the dict key is the category line.
- New deterministic critiques must set `passed` from **blocking** issues only.
  A `major` issue never fails a gate.
- Craft guidance (`tailor/craft.py`) teaches HOW to write, never WHAT is true.
  `tests/test_tailor_craft.py` enforces that no craft string authorizes
  invention or embellishment.
- The cluster map's alias table is **never** consulted when validating a
  displayed skill name. It maps tokens to a canonical cluster token, which is
  exactly the "adjacent skill" relation fact-lock forbids claiming as the job's
  own term. Only the cited `Skill`'s own `name` and `aliases` legalize a name.

## File Structure

**Create:**

| Path | Responsibility |
| ---- | -------------- |
| `src/resume_agent/tailor/skill_naming.py` | Gate: a displayed skill name resolves to its cited fact |
| `src/resume_agent/tailor/numeric_evidence.py` | Gate: every number in generated prose appears in its cited fact |
| `src/resume_agent/tailor/coverage.py` | Must-have coverage block + coverage measurement critique |
| `tests/test_tailor_skill_naming.py` | Gate 1 unit tests |
| `tests/test_tailor_numeric_evidence.py` | Gate 2 unit tests |
| `tests/test_tailor_coverage.py` | Coverage module unit tests |

**Modify:**

| Path | Change |
| ---- | ------ |
| `src/resume_agent/tailor/verdict.py:12` | Register both gates in `DETERMINISTIC_GATES` |
| `src/resume_agent/tailor/workflow.py` | Run the two gates and the coverage critique each round |
| `src/resume_agent/tailor/tailoring.py` | Coverage block into tailor + revise inputs |
| `src/resume_agent/tailor/panel.py` | Coverage block into the lean review input |
| `src/resume_agent/tailor/agents.py` | Writer/reviser instructions; ats-keyword rubric |
| `src/resume_agent/tailor/craft.py` | Rebalance the bullet-outcome rule |
| `config/review.yaml` | Sync to `config/review.yaml.example` |
| `scripts/tailor_health.py` | Report the new gates |

---

### Task 1: `skill-naming` gate

Targets mechanism M1. A displayed skill name must resolve to the fact it cites.
Compound names block; atomic mismatches are advisory.

**Files:**
- Create: `src/resume_agent/tailor/skill_naming.py`
- Test: `tests/test_tailor_skill_naming.py`

**Interfaces:**
- Consumes: `index_facts` from `tailor/provenance.py`; `normalize_skill` from
  `tracking/match_gap.py`.
- Produces: `SKILL_NAMING_REVIEWER: str = "skill-naming"`,
  `split_name(name: str) -> list[str]`,
  `skill_naming_critique(content: ResumeContent, facts: ProfileFacts) -> ReviewCritique`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tailor_skill_naming.py`:

```python
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.models.resume import ResumeContent, TailoredSkill
from resume_agent.models.review import Severity
from resume_agent.tailor.skill_naming import (
    SKILL_NAMING_REVIEWER,
    skill_naming_critique,
    split_name,
)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        skills={
            "hard": [
                Skill(id="s1", name="LLM Agents", aliases=["llm", "ai agents"]),
                Skill(id="s2", name="LangChain"),
                Skill(id="s3", name="Amazon Web Services"),
                Skill(id="s4", name="Research & Development"),
            ]
        },
    )


def _resume(*skills: TailoredSkill) -> ResumeContent:
    return ResumeContent(contact=Contact(name="Ada"), skills={"Core": list(skills)})


def test_compound_name_citing_one_fact_blocks():
    content = _resume(TailoredSkill(name="AI/LLM Agents & LangChain", provenance="s1"))

    critique = skill_naming_critique(content, _facts())

    assert critique.reviewer == SKILL_NAMING_REVIEWER
    assert critique.passed is False
    assert critique.score == 0
    blocking = [i for i in critique.issues if i.severity is Severity.blocking]
    assert blocking, "a compound name must raise a blocking issue"
    assert "LangChain" in " ".join(i.message for i in blocking)
    assert blocking[0].location == "skills/Core/AI/LLM Agents & LangChain"


def test_the_same_two_skills_as_separate_entries_pass():
    content = _resume(
        TailoredSkill(name="LLM Agents", provenance="s1"),
        TailoredSkill(name="LangChain", provenance="s2"),
    )

    critique = skill_naming_critique(content, _facts())

    assert critique.passed is True
    assert critique.score == 100
    assert critique.issues == []


def test_alias_rename_is_legal():
    content = _resume(TailoredSkill(name="AI Agents", provenance="s1"))

    assert skill_naming_critique(content, _facts()).issues == []


def test_atomic_mismatch_is_major_not_blocking():
    content = _resume(TailoredSkill(name="AWS", provenance="s3"))

    critique = skill_naming_critique(content, _facts())

    assert critique.passed is True
    assert [i.severity for i in critique.issues] == [Severity.major]


def test_fact_name_containing_a_separator_is_not_split():
    """Regression guard: 'Research & Development' cited and displayed verbatim
    must not be split into two unresolvable segments."""
    content = _resume(TailoredSkill(name="Research & Development", provenance="s4"))

    assert skill_naming_critique(content, _facts()).issues == []


def test_unknown_provenance_id_is_left_to_the_provenance_gate():
    content = _resume(TailoredSkill(name="Rust & Go", provenance="nope"))

    assert skill_naming_critique(content, _facts()).issues == []


def test_split_name_drops_empty_segments_and_parentheses():
    assert split_name("Unit Testing (pytest, MATLAB Unit Test)") == [
        "Unit Testing",
        "pytest",
        "MATLAB Unit Test",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_skill_naming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tailor.skill_naming'`

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/tailor/skill_naming.py`:

```python
"""Deterministic gate: a displayed skill name must resolve to the fact it cites.

The writer merges two real facts into one entry ("AI/LLM Agents & LangChain"
citing only the LLM Agents id) to save space in the skills section. Both halves
exist as separate facts with separate ids, and `skills` is already
`dict[str, list[TailoredSkill]]`, so the category key -- not the entry name --
is where grouping belongs.

Only the *cited fact's* own name and aliases legalize a displayed name. The
cluster map's alias table is deliberately not consulted: it maps a token to a
canonical cluster token, which is exactly the "adjacent skill" relation the
fact-lock forbids a writer from claiming as the job's own term.
"""

import re

from resume_agent.models.profile import ProfileFacts, Skill
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tailor.provenance import index_facts
from resume_agent.tracking.match_gap import normalize_skill

SKILL_NAMING_REVIEWER = "skill-naming"

# Separators a writer uses to merge technologies into one entry. `+` is
# deliberately absent: it would split "C++" into a fragment.
_SEPARATORS = re.compile(r"\s*(?:&|/|,|;|\band\b)\s*", re.IGNORECASE)
_BRACKETS = re.compile(r"[()\[\]]")


def split_name(name: str) -> list[str]:
    """Segments of a displayed skill name, in order, with empties dropped."""
    # A bracket becomes a separator, not whitespace: "Unit Testing (pytest, ...)"
    # must split at the parenthesis, and substituting a space would leave
    # "Unit Testing  pytest" as one segment.
    flattened = _BRACKETS.sub(",", name)
    return [segment.strip() for segment in _SEPARATORS.split(flattened) if segment.strip()]


def _legal_tokens(fact: Skill) -> set[str]:
    tokens = {normalize_skill(fact.name)}
    tokens.update(normalize_skill(alias) for alias in fact.aliases)
    tokens.discard("")
    return tokens


def skill_naming_critique(
    content: ResumeContent, facts: ProfileFacts
) -> ReviewCritique:
    """Blocking when an entry names a technology its cited fact does not cover."""
    index = index_facts(facts)
    issues: list[ReviewIssue] = []
    for category, entries in content.skills.items():
        for entry in entries:
            fact = index.get(entry.provenance)
            # A missing or wrong-kind provenance id belongs to the provenance
            # gate; raising it here too would double-report one defect.
            if not isinstance(fact, Skill):
                continue
            legal = _legal_tokens(fact)
            # Check the whole name first: a fact legitimately named
            # "Research & Development" must not be split into two segments
            # that individually resolve to nothing.
            if normalize_skill(entry.name) in legal:
                continue
            segments = split_name(entry.name)
            unresolved = [
                segment for segment in segments if normalize_skill(segment) not in legal
            ]
            if not unresolved:
                continue
            location = f"skills/{category}/{entry.name}"
            if len(segments) >= 2:
                issues.append(
                    ReviewIssue(
                        severity=Severity.blocking,
                        location=location,
                        message=(
                            f"skill entry {entry.name!r} names "
                            f"{', '.join(repr(s) for s in unresolved)}, which its cited "
                            f"fact {fact.name!r} ({fact.id}) does not cover"
                        ),
                        suggestion=(
                            "cite one fact per skills entry; list each named technology "
                            "as its own entry under the same skills category key"
                        ),
                    )
                )
            else:
                issues.append(
                    ReviewIssue(
                        severity=Severity.major,
                        location=location,
                        message=(
                            f"skill entry {entry.name!r} does not match its cited fact "
                            f"{fact.name!r} ({fact.id}) or any alias listed on it"
                        ),
                        suggestion=(
                            "use the fact's own name, or an alias listed on that fact"
                        ),
                    )
                )
    blocking = any(issue.severity is Severity.blocking for issue in issues)
    return ReviewCritique(
        reviewer=SKILL_NAMING_REVIEWER,
        score=0 if blocking else 100,
        passed=not blocking,
        issues=issues,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_skill_naming.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tailor/skill_naming.py tests/test_tailor_skill_naming.py
git add src/resume_agent/tailor/skill_naming.py tests/test_tailor_skill_naming.py
git commit -m "feat(tailor): deterministic skill-naming gate

A displayed skills entry that merges two technologies while citing one fact id
is structurally provable fabrication, so it blocks. An atomic name that does
not resolve through the cited fact's own aliases is advisory only -- 'AWS' for
'Amazon Web Services' is explicitly legal and the alias map cannot be trusted
to know every such pair."
```

---

### Task 2: `numeric-evidence` gate

Targets mechanisms M2 and M4. Every standalone number in generated prose must
appear in the text of the fact that prose cites.

**Files:**
- Create: `src/resume_agent/tailor/numeric_evidence.py`
- Test: `tests/test_tailor_numeric_evidence.py`

**Interfaces:**
- Consumes: `index_facts` from `tailor/provenance.py`.
- Produces: `NUMERIC_EVIDENCE_REVIEWER: str = "numeric-evidence"`,
  `claim_numbers(text: str) -> list[str]`,
  `fact_numbers(fact: object) -> set[str]`,
  `numeric_evidence_critique(content: ResumeContent, facts: ProfileFacts) -> ReviewCritique`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tailor_numeric_evidence.py`:

```python
from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
)
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
)
from resume_agent.models.review import Severity
from resume_agent.tailor.numeric_evidence import (
    NUMERIC_EVIDENCE_REVIEWER,
    claim_numbers,
    fact_numbers,
    numeric_evidence_critique,
)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="AE",
                title="Engineer",
                start="2023-02",
                bullets=[
                    Bullet(id="b1", text="Triaged 267 tickets across 9 programs"),
                    Bullet(id="b2", text="Facilitated the test procedures"),
                ],
            )
        ],
        projects=[
            Project(id="p1", name="Looms", highlights=["Cut p95 latency to 500ms"])
        ],
    )


def _resume(**kwargs) -> ResumeContent:
    return ResumeContent(contact=Contact(name="Ada"), **kwargs)


def _bullet_resume(text: str, provenance: str) -> ResumeContent:
    return _resume(
        experience=[
            TailoredExperience(
                company="AE",
                title="Engineer",
                provenance="e1",
                bullets=[TailoredBullet(text=text, provenance=provenance)],
            )
        ]
    )


def test_number_present_in_the_cited_fact_passes():
    content = _bullet_resume("Triaged 267 tickets", "b1")

    critique = numeric_evidence_critique(content, _facts())

    assert critique.reviewer == NUMERIC_EVIDENCE_REVIEWER
    assert critique.passed is True
    assert critique.score == 100
    assert critique.issues == []


def test_number_absent_from_the_cited_fact_blocks():
    content = _bullet_resume("Reduced test planning effort by 40%", "b2")

    critique = numeric_evidence_critique(content, _facts())

    assert critique.passed is False
    assert critique.score == 0
    assert [i.severity for i in critique.issues] == [Severity.blocking]
    assert "40" in critique.issues[0].message


def test_a_sibling_bullets_number_does_not_license_the_claim():
    """Citing b2 must not inherit b1's numbers."""
    content = _bullet_resume("Triaged 267 tickets", "b2")

    assert numeric_evidence_critique(content, _facts()).passed is False


def test_summary_numbers_check_against_summary_provenance():
    content = _resume(
        summary="3+ years building automation", summary_provenance=["b2"]
    )

    critique = numeric_evidence_critique(content, _facts())

    assert critique.passed is False
    assert critique.issues[0].location == "summary"


def test_unresolvable_provenance_is_left_to_the_provenance_gate():
    content = _bullet_resume("Shipped 12 releases", "nope")

    assert numeric_evidence_critique(content, _facts()).issues == []


def test_project_description_and_bullets_are_checked():
    content = _resume(
        projects=[
            TailoredProject(
                name="Looms",
                description="Cut latency to 500ms",
                provenance="p1",
                bullets=[TailoredBullet(text="Served 4000 users", provenance="p1")],
            )
        ]
    )

    critique = numeric_evidence_critique(content, _facts())

    assert critique.passed is False
    messages = " ".join(i.message for i in critique.issues)
    assert "4000" in messages
    assert "500" not in messages, "500ms is stated by the project highlight"


def test_claim_numbers_skips_numbers_welded_to_letters():
    assert claim_numbers("Cut p95 latency on GPT-4 and L1-L3 in C++") == []


def test_claim_numbers_reads_standalone_values_with_units():
    assert claim_numbers("Handled 430+ tickets, 95% clean, in 500ms (1,200 runs)") == [
        "430",
        "95",
        "500",
        "1200",
    ]


def test_fact_numbers_ignores_child_bullets():
    experience = _facts().experience[0]

    numbers = fact_numbers(experience)

    assert "267" not in numbers
    assert "2023" in numbers
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_numeric_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tailor.numeric_evidence'`

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/tailor/numeric_evidence.py`:

```python
"""Deterministic gate: a number in generated prose must come from a cited fact.

The largest class of fact-check failures is an invented quantity -- "saving
hours of manual reporting effort", "3+ years", "reduced planning effort by 40%".
A number is mechanically checkable, so a premium reviewer should not be spending
a round to notice it.

Tokenization is conservative in the permissive direction. A token counts as a
claim only when it stands alone, so `p95`, `L1-L3`, `GPT-4`, `S3`, and `C++` are
never treated as quantities; and a fact's evidence set is every digit run
anywhere in its own fields, so a number the fact states in passing still
legalizes the claim. False blocks cost a round, which is worse than a miss the
LLM fact-checker can still catch.
"""

import re
from typing import Any

from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tailor.provenance import index_facts

NUMERIC_EVIDENCE_REVIEWER = "numeric-evidence"

# A whole whitespace token that is a bare quantity, optionally carrying one
# common unit. Anything welded to letters fails this and is ignored.
_QUANTITY = re.compile(r"^\d[\d,]*(?:\.\d+)?(?:%|\+|x|k|m|b|ms|s)?$", re.IGNORECASE)
# The digit core of a token, and every digit run inside a fact's text.
_DIGITS = re.compile(r"\d[\d,]*(?:\.\d+)?")
_EDGE_PUNCTUATION = "\"'`()[]{}<>,.;:!?—–-"

# Identity and structure, not evidence. `bullets` is excluded so citing a parent
# Experience does not inherit the numbers stated by its child bullets -- the
# writer is required to cite the narrowest supporting fact.
_SKIP_FIELDS = frozenset({"id", "schema_version", "source", "source_ref", "bullets"})


def claim_numbers(text: str) -> list[str]:
    """Standalone numeric claims in prose, normalized to their digit core."""
    numbers: list[str] = []
    for raw in text.split():
        token = raw.strip(_EDGE_PUNCTUATION)
        if not token or not _QUANTITY.match(token):
            continue
        core = _DIGITS.match(token)
        if core:
            numbers.append(core.group().replace(",", ""))
    return numbers


def fact_numbers(fact: object) -> set[str]:
    """Every digit run stated anywhere in a fact's own evidence fields."""
    parts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key not in _SKIP_FIELDS:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif value is not None and not isinstance(value, bool):
            parts.append(str(value))

    walk(fact.model_dump(mode="json"))  # type: ignore[attr-defined]
    return {
        match.group().replace(",", "") for match in _DIGITS.finditer(" ".join(parts))
    }


def numeric_evidence_critique(
    content: ResumeContent, facts: ProfileFacts
) -> ReviewCritique:
    """Blocking for every number no cited fact states."""
    index = index_facts(facts)
    issues: list[ReviewIssue] = []

    def check(text: str | None, fact_ids: list[str], location: str) -> None:
        if not text:
            return
        resolved = [index[fact_id] for fact_id in fact_ids if fact_id in index]
        # Nothing resolved means the citation itself is broken; that is the
        # provenance gate's finding, not a numeric one.
        if not resolved:
            return
        allowed: set[str] = set()
        for fact in resolved:
            allowed |= fact_numbers(fact)
        cited = ", ".join(fact_ids)
        for number in claim_numbers(text):
            if number in allowed:
                continue
            issues.append(
                ReviewIssue(
                    severity=Severity.blocking,
                    location=location,
                    message=(
                        f"the number {number!r} does not appear in the cited "
                        f"fact(s) {cited}"
                    ),
                    suggestion=(
                        "delete the quantity, or restate the claim using a value the "
                        "cited fact states"
                    ),
                )
            )

    check(content.summary, content.summary_provenance, "summary")
    for exp in content.experience:
        for position, bullet in enumerate(exp.bullets):
            check(
                bullet.text,
                [bullet.provenance],
                f"experience/{exp.company}/bullet {position + 1}",
            )
    for project in content.projects:
        check(project.description, [project.provenance], f"projects/{project.name}")
        for position, bullet in enumerate(project.bullets):
            check(
                bullet.text,
                [bullet.provenance],
                f"projects/{project.name}/bullet {position + 1}",
            )
    for vol in content.volunteer:
        for position, bullet in enumerate(vol.bullets):
            check(
                bullet.text,
                [bullet.provenance],
                f"volunteer/{vol.organization}/bullet {position + 1}",
            )

    return ReviewCritique(
        reviewer=NUMERIC_EVIDENCE_REVIEWER,
        score=0 if issues else 100,
        passed=not issues,
        issues=issues,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_numeric_evidence.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tailor/numeric_evidence.py tests/test_tailor_numeric_evidence.py
git add src/resume_agent/tailor/numeric_evidence.py tests/test_tailor_numeric_evidence.py
git commit -m "feat(tailor): deterministic numeric-evidence gate

Every standalone number in generated prose must appear in the fact that prose
cites. Catches the invented-metric class and derived tenure arithmetic ('3+
years' fails because no cited fact contains a 3) before any LLM call, so the
reviser receives it in round 1 rather than a premium fact-check round being
spent to discover it. Citing a parent Experience does not inherit its child
bullets' numbers."
```

---

### Task 3: must-have coverage module

Renders the already-computed `SkillMatchContext` for prompts, and measures how
much evidenced must-have coverage reached the resume.

**Files:**
- Create: `src/resume_agent/tailor/coverage.py`
- Test: `tests/test_tailor_coverage.py`

**Interfaces:**
- Consumes: `SkillMatchContext`, `SkillMatch`, `MatrixRow` from
  `profile/matrix.py`; `normalize_skill` from `tracking/match_gap.py`.
- Produces: `COVERAGE_REVIEWER: str = "must-have-coverage"`,
  `format_coverage(context: SkillMatchContext | None) -> str`,
  `CoverageReport` (fields `covered_total: int`, `rendered: list[str]`,
  `missed: list[str]`),
  `coverage_report(content: ResumeContent, context: SkillMatchContext | None) -> CoverageReport`,
  `coverage_critique(content: ResumeContent, context: SkillMatchContext | None) -> ReviewCritique | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tailor_coverage.py`:

```python
from resume_agent.models.profile import Contact
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)
from resume_agent.models.review import Severity
from resume_agent.profile.matrix import MatrixRow, SkillMatch, SkillMatchContext
from resume_agent.tailor.coverage import (
    COVERAGE_REVIEWER,
    coverage_critique,
    coverage_report,
    format_coverage,
)


def _context() -> SkillMatchContext:
    return SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="Python",
                source="must",
                coverage="covered",
                row=MatrixRow(key="python", display="Python", evidence_fact_ids=["s1"]),
            ),
            SkillMatch(
                requirement="LangChain",
                source="must",
                coverage="covered",
                row=MatrixRow(key="langchain", display="LangChain", evidence_fact_ids=["s2"]),
            ),
            SkillMatch(requirement="Kubernetes", source="must", coverage="gap", row=None),
            SkillMatch(
                requirement="Terraform",
                source="must",
                coverage="adjacent",
                row=MatrixRow(key="iac", display="Infrastructure as Code"),
            ),
            SkillMatch(
                requirement="Docker",
                source="nice",
                coverage="covered",
                row=MatrixRow(key="docker", display="Docker", evidence_fact_ids=["s3"]),
            ),
        ]
    )


def test_format_coverage_lists_must_haves_before_nice_to_haves():
    block = format_coverage(_context())

    assert block.startswith("MUST-HAVE COVERAGE")
    assert "- Python — covered — facts: s1" in block
    assert "- Kubernetes — gap — no profile evidence; do not claim or imply" in block
    assert (
        "- Terraform — adjacent (Infrastructure as Code) — may inform emphasis, "
        "never named" in block
    )
    assert block.index("Python") < block.index("Docker")


def test_format_coverage_degrades_to_empty_without_a_context():
    assert format_coverage(None) == ""
    assert format_coverage(SkillMatchContext()) == ""


def test_coverage_report_counts_a_skills_entry_as_rendered():
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="Python", provenance="s1")]},
    )

    report = coverage_report(content, _context())

    assert report.covered_total == 2
    assert report.rendered == ["Python"]
    assert report.missed == ["LangChain"]


def test_coverage_report_counts_a_bullet_mention_as_rendered():
    content = ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Engineer",
                provenance="e1",
                bullets=[
                    TailoredBullet(text="Built agents with LangChain", provenance="b1")
                ],
            )
        ],
        skills={"Core": [TailoredSkill(name="Python", provenance="s1")]},
    )

    report = coverage_report(content, _context())

    assert sorted(report.rendered) == ["LangChain", "Python"]
    assert report.missed == []


def test_coverage_critique_scores_the_rendered_share_and_never_blocks():
    content = ResumeContent(
        contact=Contact(name="Ada"),
        skills={"Core": [TailoredSkill(name="Python", provenance="s1")]},
    )

    critique = coverage_critique(content, _context())

    assert critique is not None
    assert critique.reviewer == COVERAGE_REVIEWER
    assert critique.passed is True
    assert critique.score == 50
    assert [i.severity for i in critique.issues] == [Severity.major]
    assert "LangChain" in critique.issues[0].message


def test_coverage_critique_is_none_without_evidenced_must_haves():
    content = ResumeContent(contact=Contact(name="Ada"))

    assert coverage_critique(content, None) is None
    assert coverage_critique(content, SkillMatchContext()) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_coverage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tailor.coverage'`

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/tailor/coverage.py`:

```python
"""Must-have coverage: the deterministic answer the pipeline already computes.

`build_skill_match_context` maps every JD requirement to covered / adjacent /
gap with the matching matrix row and its evidence fact ids, and
`tailor/service.py` builds it on every run -- but it was consumed only under
`match_plan_enabled`, which is off. So no agent ever saw it.

Two consumers here. `format_coverage` renders it for the writer, the reviser,
and the advisory panel, which gives `ats-keyword` the ground truth its rubric
already assumes ("distinguish a missing keyword from a genuinely missing
qualification"). `coverage_critique` measures the other direction -- how much of
the evidenced must-have list reached the resume -- as an advisory critique, not
a gate: the one-page length budget legitimately forces cuts, and a gate here
could hand the writer an unwinnable round.
"""

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.profile.matrix import SkillMatch, SkillMatchContext
from resume_agent.tracking.match_gap import normalize_skill

COVERAGE_REVIEWER = "must-have-coverage"

_HEADER = (
    "MUST-HAVE COVERAGE (deterministic; fact ids are evidence pointers, not claims):"
)


class CoverageReport(ExtensibleModel):
    """Which evidenced must-haves reached the produced resume."""

    covered_total: int = 0
    rendered: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)


def _line(match: SkillMatch) -> str:
    if match.coverage == "covered":
        facts = ", ".join(match.row.evidence_fact_ids) if match.row else ""
        return f"- {match.requirement} — covered — facts: {facts}"
    if match.coverage == "adjacent":
        label = match.row.display if match.row else "a related skill"
        return (
            f"- {match.requirement} — adjacent ({label}) — may inform emphasis, "
            "never named"
        )
    return f"- {match.requirement} — gap — no profile evidence; do not claim or imply"


def format_coverage(context: SkillMatchContext | None) -> str:
    """The coverage block, must-haves first. Empty string when unavailable."""
    if context is None or not context.matches:
        return ""
    order = {"must": 0, "nice": 1, "tech": 2}
    ordered = sorted(
        context.matches, key=lambda match: order.get(match.source, 3)
    )
    return "\n".join([_HEADER, *(_line(match) for match in ordered)])


def _rendered_tokens(content: ResumeContent) -> set[str]:
    """Normalized skill names, plus bullet and summary prose, for containment."""
    tokens = {
        normalize_skill(entry.name)
        for entries in content.skills.values()
        for entry in entries
    }
    tokens.discard("")
    return tokens


def _prose(content: ResumeContent) -> str:
    """All generated prose, normalized and space-padded for word containment.

    Padding matters: a one-letter requirement like 'R' or 'C' would match almost
    any prose under a bare substring test, silently reporting coverage that is
    not there.
    """
    parts = [content.summary or ""]
    for exp in content.experience:
        parts.extend(bullet.text for bullet in exp.bullets)
    for project in content.projects:
        parts.append(project.description or "")
        parts.extend(bullet.text for bullet in project.bullets)
    for vol in content.volunteer:
        parts.extend(bullet.text for bullet in vol.bullets)
    return f" {normalize_skill(' '.join(parts))} "


def coverage_report(
    content: ResumeContent, context: SkillMatchContext | None
) -> CoverageReport:
    """Of the must-haves with evidence, which appear in the produced resume."""
    if context is None:
        return CoverageReport()
    tokens = _rendered_tokens(content)
    prose = _prose(content)
    rendered: list[str] = []
    missed: list[str] = []
    for match in context.matches:
        if match.source != "must" or match.coverage != "covered":
            continue
        token = normalize_skill(match.requirement)
        if not token:
            continue
        if token in tokens or f" {token} " in prose:
            rendered.append(match.requirement)
        else:
            missed.append(match.requirement)
    return CoverageReport(
        covered_total=len(rendered) + len(missed), rendered=rendered, missed=missed
    )


def coverage_critique(
    content: ResumeContent, context: SkillMatchContext | None
) -> ReviewCritique | None:
    """Advisory critique carrying the coverage rate. Never a gate, never blocking.

    `None` when the job has no evidenced must-have: there is nothing to measure
    and a 0 would read as a quality failure rather than an empty set.
    """
    report = coverage_report(content, context)
    if not report.covered_total:
        return None
    return ReviewCritique(
        reviewer=COVERAGE_REVIEWER,
        score=round(100 * len(report.rendered) / report.covered_total),
        passed=True,
        issues=[
            ReviewIssue(
                severity=Severity.major,
                location="skills",
                message=(
                    f"must-have {requirement!r} has profile evidence but does not "
                    "appear in this resume"
                ),
                suggestion=(
                    "add it as a skills entry, or show it in a bullet, if a truthful "
                    "cited fact supports it"
                ),
            )
            for requirement in report.missed
        ],
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_coverage.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tailor/coverage.py tests/test_tailor_coverage.py
git add src/resume_agent/tailor/coverage.py tests/test_tailor_coverage.py
git commit -m "feat(tailor): must-have coverage block and measurement

build_skill_match_context is computed on every tailor run and was consumed only
under match_plan_enabled (off), so no agent ever saw which must-haves have
evidence. format_coverage renders it for prompts; coverage_critique measures
how much evidenced coverage reached the resume as an advisory critique -- not a
gate, because the length budget legitimately forces cuts."
```

---

### Task 4: register and run the two gates

**Files:**
- Modify: `src/resume_agent/tailor/verdict.py:12`
- Modify: `src/resume_agent/tailor/workflow.py` (both `run_tailor_review` and
  `arun_tailor_review`)
- Test: `tests/test_tailor_verdict.py`, `tests/test_tailor_workflow.py`

**Interfaces:**
- Consumes: `skill_naming_critique`, `SKILL_NAMING_REVIEWER` (Task 1);
  `numeric_evidence_critique`, `NUMERIC_EVIDENCE_REVIEWER` (Task 2).
- Produces: both names present in `DETERMINISTIC_GATES`; both critiques present
  in every `TailorRound.verdict.critiques`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tailor_verdict.py`:

```python
def test_new_deterministic_gates_are_registered():
    from resume_agent.tailor.verdict import DETERMINISTIC_GATES

    assert "skill-naming" in DETERMINISTIC_GATES
    assert "numeric-evidence" in DETERMINISTIC_GATES


def test_a_new_gate_failure_blocks_the_round_and_is_named():
    from resume_agent.models.review import ReviewCritique
    from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
    from resume_agent.tailor.verdict import aggregate, failing_gate_names

    config = ReviewConfig(reviewers=[ReviewerSpec(name="recruiter", weight=1)])
    critiques = [
        ReviewCritique(reviewer="provenance", score=100, passed=True),
        ReviewCritique(reviewer="numeric-evidence", score=0, passed=False),
        ReviewCritique(reviewer="recruiter", score=90, passed=True),
    ]

    verdict = aggregate(critiques, config)

    assert verdict.gate_passed is False
    assert verdict.passed is False
    assert verdict.aggregate_score == 90
    assert failing_gate_names(critiques, {"recruiter"}) == ["numeric-evidence"]
```

Append to `tests/test_tailor_workflow.py` (follow the existing fake-agent
helpers already in that file for building `tailor_agent` / `reviewer_agents` /
`reviser_agent`):

```python
def test_every_round_carries_the_deterministic_critiques():
    rounds = _run_one_round()  # existing helper in this module

    names = {critique.reviewer for critique in rounds[0].verdict.critiques}
    assert {"provenance", "skill-naming", "numeric-evidence"} <= names


def test_a_new_gate_failure_is_not_granted_the_provenance_free_retry():
    """A citation slip is provenance ONLY; a numeric failure is a real round."""
    from resume_agent.models.review import ReviewCritique
    from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
    from resume_agent.tailor.workflow import _is_citation_slip
    from resume_agent.tailor.verdict import aggregate

    config = ReviewConfig(reviewers=[ReviewerSpec(name="recruiter", weight=1)])
    verdict = aggregate(
        [
            ReviewCritique(reviewer="provenance", score=0, passed=False),
            ReviewCritique(reviewer="numeric-evidence", score=0, passed=False),
            ReviewCritique(reviewer="recruiter", score=70, passed=True),
        ],
        config,
    )

    assert _is_citation_slip(verdict, config) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_verdict.py tests/test_tailor_workflow.py -v`
Expected: FAIL — `assert 'skill-naming' in frozenset({'provenance'})`

- [ ] **Step 3: Register the gates**

In `src/resume_agent/tailor/verdict.py`, replace lines 7 and 12:

```python
from resume_agent.tailor.numeric_evidence import NUMERIC_EVIDENCE_REVIEWER
from resume_agent.tailor.provenance import PROVENANCE_REVIEWER
from resume_agent.tailor.skill_naming import SKILL_NAMING_REVIEWER
```

```python
# Gates decided in-process, not by a configured reviewer agent. They ride in the
# critiques list like any gate, so aggregate stays the only verdict constructor.
DETERMINISTIC_GATES = frozenset(
    {PROVENANCE_REVIEWER, SKILL_NAMING_REVIEWER, NUMERIC_EVIDENCE_REVIEWER}
)
```

- [ ] **Step 4: Run the gates every round**

In `src/resume_agent/tailor/workflow.py`, add the imports:

```python
from resume_agent.tailor.numeric_evidence import numeric_evidence_critique
from resume_agent.tailor.skill_naming import skill_naming_critique
```

In **both** `run_tailor_review` and `arun_tailor_review`, replace the line
`provenance = provenance_critique(content, profile_facts)` with:

```python
        # Deterministic gates run before the panel: each is mechanically
        # provable, and their issues reach the reviser in the same round they
        # were detected rather than costing a premium fact-check round.
        deterministic = [
            provenance_critique(content, profile_facts),
            skill_naming_critique(content, profile_facts),
            numeric_evidence_critique(content, profile_facts),
        ]
```

and replace `critiques = [provenance, *panel]` with:

```python
        critiques = [*deterministic, *panel]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_verdict.py tests/test_tailor_workflow.py -v`
Expected: PASS

- [ ] **Step 6: Run the full tailor suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k tailor -v`
Expected: PASS. If `tests/test_tailor_review_e2e.py` fails because a fixture
resume cites facts it does not support, fix the **fixture** to be fact-locked —
that is the gate working, not a bug.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/resume_agent/tailor/
git add src/resume_agent/tailor/verdict.py src/resume_agent/tailor/workflow.py tests/test_tailor_verdict.py tests/test_tailor_workflow.py
git commit -m "feat(tailor): run skill-naming and numeric-evidence every round

Registering both names in DETERMINISTIC_GATES is the whole wiring: aggregate,
failing_gate_names, and ResumeVersionOut.failedGates all read that frozenset,
and _is_citation_slip's 'failed == {provenance}' test now correctly denies the
free retry to a round that also tripped a new gate."
```

---

### Task 5: wire the coverage block into the prompts

**Files:**
- Modify: `src/resume_agent/tailor/tailoring.py` (`compose_tailor_input`,
  `compose_revise_input`)
- Modify: `src/resume_agent/tailor/panel.py` (`compose_lean_review_input`,
  `run_panel`, `arun_panel`, `_panel_inputs`)
- Modify: `src/resume_agent/tailor/workflow.py`
- Test: `tests/test_tailor_tailoring.py`, `tests/test_tailor_panel.py`

**Interfaces:**
- Consumes: `format_coverage`, `coverage_critique` (Task 3).
- Produces: `compose_tailor_input(..., coverage: str = "")`,
  `compose_revise_input(..., coverage: str = "")`,
  `compose_lean_review_input(content, jd_text, stats, coverage: str = "")`,
  `run_panel(..., coverage: str = "")`, `arun_panel(..., coverage: str = "")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tailor_tailoring.py`:

```python
def test_tailor_input_places_coverage_between_criteria_and_jd():
    """Stable-first ordering: coverage is fixed for the job, so it belongs in
    the cacheable prefix ahead of the volatile blocks."""
    from resume_agent.models.job import JobCriteria
    from resume_agent.models.profile import Contact, ProfileFacts
    from resume_agent.tailor.tailoring import compose_tailor_input

    text = compose_tailor_input(
        "JD body",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        coverage="MUST-HAVE COVERAGE (x):\n- Python — covered — facts: s1",
    )

    assert text.index("JOB CRITERIA") < text.index("MUST-HAVE COVERAGE")
    assert text.index("MUST-HAVE COVERAGE") < text.index("JOB DESCRIPTION")


def test_tailor_input_omits_the_block_when_coverage_is_empty():
    from resume_agent.models.job import JobCriteria
    from resume_agent.models.profile import Contact, ProfileFacts
    from resume_agent.tailor.tailoring import compose_tailor_input

    text = compose_tailor_input(
        "JD body", JobCriteria(), ProfileFacts(contact=Contact(name="Ada"))
    )

    assert "MUST-HAVE COVERAGE" not in text


def test_revise_input_places_coverage_before_the_current_resume():
    from resume_agent.models.profile import Contact, ProfileFacts
    from resume_agent.models.resume import ResumeContent
    from resume_agent.tailor.tailoring import compose_revise_input

    text = compose_revise_input(
        ResumeContent(contact=Contact(name="Ada")),
        [],
        ProfileFacts(contact=Contact(name="Ada")),
        "JD body",
        coverage="MUST-HAVE COVERAGE (x):\n- Python — covered — facts: s1",
    )

    assert text.index("JOB DESCRIPTION") < text.index("MUST-HAVE COVERAGE")
    assert text.index("MUST-HAVE COVERAGE") < text.index("CURRENT RESUME")
```

Append to `tests/test_tailor_panel.py`:

```python
def test_lean_review_input_carries_the_coverage_block():
    from resume_agent.models.profile import Contact
    from resume_agent.models.resume import ResumeContent
    from resume_agent.tailor.panel import compose_lean_review_input

    text = compose_lean_review_input(
        ResumeContent(contact=Contact(name="Ada")),
        "JD body",
        "stats",
        coverage="MUST-HAVE COVERAGE (x):\n- Kubernetes — gap — no profile evidence",
    )

    assert "MUST-HAVE COVERAGE" in text
    assert "Kubernetes" in text


def test_lean_review_input_omits_the_block_when_empty():
    from resume_agent.models.profile import Contact
    from resume_agent.models.resume import ResumeContent
    from resume_agent.tailor.panel import compose_lean_review_input

    text = compose_lean_review_input(
        ResumeContent(contact=Contact(name="Ada")), "JD body", "stats"
    )

    assert "MUST-HAVE COVERAGE" not in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_tailoring.py tests/test_tailor_panel.py -v`
Expected: FAIL — `TypeError: compose_tailor_input() got an unexpected keyword argument 'coverage'`

- [ ] **Step 3: Add the parameter to the composers**

In `src/resume_agent/tailor/tailoring.py`, `compose_tailor_input` gains
`coverage: str = ""` as its final parameter, and the return becomes:

```python
    coverage_line = f"\n\n{coverage}" if coverage else ""
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{renderable_profile(profile_facts).model_dump_json()}\n\n"
        "JOB CRITERIA (JSON):\n"
        f"{criteria.model_dump_json()}"
        f"{coverage_line}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
        f"{budget_line}"
        f"{plan_line}"
    )
```

`compose_revise_input` gains `coverage: str = ""` as its final parameter, and
the return becomes:

```python
    coverage_line = f"\n\n{coverage}" if coverage else ""
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{renderable_profile(profile_facts).model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
        f"{coverage_line}\n\n"
        "CURRENT RESUME (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "REVIEWER ISSUES (fix every BLOCKING issue first, then MAJOR, then MINOR; copy "
        "every record not named here byte-for-byte unchanged):\n"
        f"{issues}\n\n"
        "REVIEWER SUGGESTIONS:\n"
        f"{suggestions}"
        f"{budget_line}"
    )
```

In `src/resume_agent/tailor/panel.py`, `compose_lean_review_input` becomes:

```python
def compose_lean_review_input(
    content: ResumeContent, jd_text: str, stats: str, coverage: str = ""
) -> str:
    """Input for non-gate reviewers: resume + JD + size stats. No raw profile."""
    coverage_line = f"\n\n{coverage}" if coverage else ""
    return (
        "RESUME UNDER REVIEW (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "RESUME STATS:\n"
        f"{stats}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
        f"{coverage_line}"
    )
```

Add `coverage: str = ""` as the final keyword parameter of `run_panel`,
`arun_panel`, and `_panel_inputs`, and thread it into every
`compose_lean_review_input(...)` call site inside them.

- [ ] **Step 4: Thread coverage through the workflow**

In `src/resume_agent/tailor/workflow.py`, add the import:

```python
from resume_agent.tailor.coverage import coverage_critique, format_coverage
```

In **both** `run_tailor_review` and `arun_tailor_review`, immediately before the
`content = tailor(...)` / `content = await atailor(...)` call, add:

```python
    coverage = format_coverage(skill_context)
```

Pass `coverage` as the final argument to `compose_tailor_input(...)`,
`compose_revise_input(...)`, and `run_panel(...)` / `arun_panel(...)`.

Then extend the deterministic list built in Task 4 so the coverage measurement
rides along:

```python
        deterministic = [
            provenance_critique(content, profile_facts),
            skill_naming_critique(content, profile_facts),
            numeric_evidence_critique(content, profile_facts),
        ]
        # Advisory, never a gate: it is not in DETERMINISTIC_GATES and not a
        # configured reviewer, so it neither blocks the round nor enters the
        # weighted score. It carries the coverage rate for tailor_health.
        if (coverage_measure := coverage_critique(content, skill_context)) is not None:
            deterministic.append(coverage_measure)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_tailoring.py tests/test_tailor_panel.py tests/test_tailor_workflow.py -v`
Expected: PASS

- [ ] **Step 6: Verify the coverage critique does not enter the score**

Run: `.venv/Scripts/python.exe -m pytest tests/ -k "tailor or verdict" -v`
Expected: PASS. `aggregate` weights only `config.reviewers`, so
`must-have-coverage` cannot shift `aggregate_score`.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/resume_agent/tailor/
git add src/resume_agent/tailor/ tests/test_tailor_tailoring.py tests/test_tailor_panel.py tests/test_tailor_workflow.py
git commit -m "feat(tailor): give the writer, reviser, and panel must-have coverage

The coverage block goes into the stable region of each prompt so the cacheable
prefix survives across rounds. ats-keyword's rubric already told it to
distinguish a missing keyword from a genuinely missing qualification while
supplying no data to do so; now it has the data."
```

---

### Task 6: prompt and config changes

**Files:**
- Modify: `src/resume_agent/tailor/agents.py`
  (`_TAILOR_INSTRUCTIONS`, `_REVISER_INSTRUCTIONS`)
- Modify: `src/resume_agent/tailor/craft.py`
  (`CRAFT_WRITER`, `CRAFT_REVIEWERS["ats-keyword"]`)
- Modify: `config/review.yaml`
- Test: `tests/test_tailor_agents.py`, `tests/test_tailor_craft.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. Makes Task 1's gate learnable.
- Produces: no new symbols.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tailor_agents.py`:

```python
def test_writer_and_reviser_forbid_merging_two_facts_into_one_skill_entry():
    from resume_agent.tailor.agents import (
        _REVISER_INSTRUCTIONS,
        _TAILOR_INSTRUCTIONS,
    )

    for block in (_TAILOR_INSTRUCTIONS, _REVISER_INSTRUCTIONS):
        text = " ".join(block).lower()
        assert "exactly one" in text and "skills entry" in text
        assert "category key" in text


def test_writer_and_reviser_forbid_derived_tenure():
    from resume_agent.tailor.agents import (
        _REVISER_INSTRUCTIONS,
        _TAILOR_INSTRUCTIONS,
    )

    for block in (_TAILOR_INSTRUCTIONS, _REVISER_INSTRUCTIONS):
        text = " ".join(block).lower()
        assert "years of experience" in text or "total years" in text


def test_writer_and_reviser_forbid_unstated_beneficiaries():
    from resume_agent.tailor.agents import (
        _REVISER_INSTRUCTIONS,
        _TAILOR_INSTRUCTIONS,
    )

    for block in (_TAILOR_INSTRUCTIONS, _REVISER_INSTRUCTIONS):
        text = " ".join(block).lower()
        assert "adoption" in text
```

Append to `tests/test_tailor_craft.py`:

```python
def test_ats_keyword_rubric_treats_coverage_as_authoritative():
    from resume_agent.tailor.craft import CRAFT_REVIEWERS

    text = " ".join(CRAFT_REVIEWERS["ats-keyword"]).lower()
    assert "must-have coverage" in text
    assert "gap" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_agents.py tests/test_tailor_craft.py -v`
Expected: FAIL — `assert 'exactly one' in ...`

- [ ] **Step 3: Edit the writer and reviser instructions**

In `src/resume_agent/tailor/agents.py`, replace the skills bullet of
`_TAILOR_INSTRUCTIONS` (currently beginning "Every selected skill must cite the
matching ProfileFacts Skill id.") with:

```python
    "Every selected skill must cite the matching ProfileFacts Skill id, and each skills "
    "entry names exactly one skill fact. Never merge two technologies into one entry: "
    "'Jira & Confluence REST APIs' and 'Unit Testing (pytest, MATLAB Unit Test)' each "
    "name a technology the cited fact does not cover. Group related skills using the "
    "skills category key instead, which is what renders as the section line. You may "
    "adjust casing and punctuation, or use an alias already listed on that fact, but "
    "never rename it to a broader, adjacent, or different technology: 'Jira API' is not "
    "'Jira and Confluence APIs', and 'Vehicle Log Signal Analysis' is not "
    "'Log Analysis / Telemetry'.",
```

Replace the outcome bullet of `_TAILOR_INSTRUCTIONS` (currently beginning "State
an outcome, benefit, saving, or improvement only when the source fact states
it.") with:

```python
    "State an outcome, benefit, saving, or improvement only when the source fact states "
    "it, and never name a beneficiary, adoption, saving, or efficiency the fact does not "
    "state. When a fact records an activity, describe the activity - an unquantified "
    "claim such as 'saving hours of manual effort' or 'improving adoption among "
    "non-technical users' is as unsupported as an invented number.",
```

Add one new bullet to `_TAILOR_INSTRUCTIONS`, after the summary bullet:

```python
    "Never state a tenure, duration, or total years of experience unless a fact states "
    "that figure. Employment dates are facts; the span between them is arithmetic you "
    "may not perform, so '3+ years building X' needs a fact that says so.",
```

Apply the same three changes to `_REVISER_INSTRUCTIONS`: extend its provenance
bullet with the one-entry-one-fact and category-key rule, extend its outcome
bullet with the beneficiary clause, and add the tenure bullet.

- [ ] **Step 4: Edit the craft guidance**

In `src/resume_agent/tailor/craft.py`, replace the first entry of `CRAFT_WRITER`
with:

```python
    "Write every bullet as an accomplishment. When a cited profile fact supplies "
    "a number, lead with the outcome and its number, then the action that "
    "produced it. When the cited facts carry no number, lead with the concrete "
    "action, its scope, and the specific systems involved - that is a complete "
    "accomplishment bullet, not a lesser one, and inventing an outcome to fill "
    "the gap fails the round.",
```

Append to `CRAFT_REVIEWERS["ats-keyword"]`:

```python
        "When MUST-HAVE COVERAGE is present it is authoritative. A requirement "
        "marked 'gap' is a qualification the candidate genuinely lacks: never "
        "score it as a missing keyword and never suggest adding it. Score "
        "coverage only over requirements marked 'covered', and treat one marked "
        "'adjacent' as emphasis material that may never be named as the job's "
        "own term.",
```

- [ ] **Step 5: Sync the live review config**

```bash
cp config/review.yaml.example config/review.yaml
```

Then confirm the live file did not lose local customization:

Run: `git diff --no-index config/review.yaml.example config/review.yaml`
Expected: no output. `config/review.yaml` is gitignored, so this file is the
reason the 2026-07-27 `score_bands` fix never reached local runs.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_agents.py tests/test_tailor_craft.py tests/test_prompt_registry.py tests/test_agent_prompt_contracts.py -v`
Expected: PASS. `tests/test_tailor_craft.py`'s existing guard that no craft
string authorizes invention must still pass — the new wording forbids invention
rather than licensing it.

- [ ] **Step 7: Lint and commit**

```bash
ruff check src/resume_agent/tailor/
git add src/resume_agent/tailor/agents.py src/resume_agent/tailor/craft.py tests/test_tailor_agents.py tests/test_tailor_craft.py
git commit -m "feat(tailor): teach the writer the rules the new gates enforce

One skills entry names one fact and grouping belongs to the category key;
tenure is not arithmetic the writer may perform; a beneficiary or adoption the
fact does not state is as unsupported as an invented number. The craft rule's
no-number branch is no longer phrased as a consolation prize, which is what
pushed the writer to invent an outcome to fill it.

config/review.yaml is gitignored and stays out of this commit; it was resynced
from the .example, which is how the 2026-07-27 score_bands fix reaches local
runs."
```

---

### Task 7: report the new gates in `tailor_health.py`

**Files:**
- Modify: `scripts/tailor_health.py`
- Test: `tests/test_tailor_health_script.py` (create)

**Interfaces:**
- Consumes: critique names produced by Tasks 1–3 and 5.
- Produces: `collect()` returns `gate_failures` keyed by all four gate names and
  `blocking_issue_kinds` keyed by `"<reviewer>: <kind>"`; `reviewer_means`
  automatically includes `must-have-coverage`, which **is** the coverage rate.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tailor_health_script.py`:

```python
import importlib.util
import json
import sqlite3
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "tailor_health", Path(__file__).resolve().parents[1] / "scripts" / "tailor_health.py"
)
assert _SPEC and _SPEC.loader
tailor_health = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tailor_health)


def _db(tmp_path: Path, critiques: list[dict]) -> Path:
    path = tmp_path / "resume_agent.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "create table resume_versions (id integer, job_id integer, round integer, "
        "review_score integer, fact_check_passed integer, critique_json text)"
    )
    connection.execute(
        "insert into resume_versions values (1, 1, 1, 70, 0, ?)",
        (json.dumps(critiques),),
    )
    connection.commit()
    connection.close()
    return path


def test_new_gates_are_counted_as_gate_failures(tmp_path):
    path = _db(
        tmp_path,
        [
            {"reviewer": "provenance", "score": 100, "passed": True, "issues": []},
            {
                "reviewer": "numeric-evidence",
                "score": 0,
                "passed": False,
                "issues": [{"severity": "blocking", "message": "the number '40'"}],
            },
            {
                "reviewer": "skill-naming",
                "score": 0,
                "passed": False,
                "issues": [{"severity": "blocking", "message": "skill entry names"}],
            },
        ],
    )

    report = tailor_health.collect(path)

    assert report["gate_failures"]["numeric-evidence"] == 1
    assert report["gate_failures"]["skill-naming"] == 1
    assert "provenance" not in report["gate_failures"]


def test_coverage_rate_rides_the_reviewer_means(tmp_path):
    path = _db(
        tmp_path,
        [{"reviewer": "must-have-coverage", "score": 60, "passed": True, "issues": []}],
    )

    report = tailor_health.collect(path)

    assert report["reviewer_means"]["must-have-coverage"] == 60.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_health_script.py -v`
Expected: FAIL — `KeyError: 'numeric-evidence'`

- [ ] **Step 3: Widen the gate set and the issue breakdown**

In `scripts/tailor_health.py`, add below `_ISSUE_KINDS`:

```python
# Every gate that can block a round. `provenance` and `fact-check` were the
# original two; `skill-naming` and `numeric-evidence` are deterministic gates
# added 2026-08-04 that intercept mechanically-provable violations before the
# panel runs.
_GATE_REVIEWERS = frozenset(
    {"provenance", "fact-check", "skill-naming", "numeric-evidence"}
)
```

Replace the two `if` blocks inside the critique loop with:

```python
            if not critique.get("passed", True) and reviewer in _GATE_REVIEWERS:
                gate_failures[reviewer] += 1
                for issue in critique.get("issues") or []:
                    if issue.get("severity") == "blocking":
                        kind = _issue_kind(issue.get("message", ""))
                        issue_kinds[f"{reviewer}: {kind}"] += 1
```

Rename the returned key and its label:

```python
        "blocking_issue_kinds": dict(issue_kinds.most_common()),
```

```python
        "blocking issues by gate and kind:",
        *(f"  {k:>32}  {v}" for k, v in report["blocking_issue_kinds"].items()),
```

Update the module docstring's third bullet to read:

```
  * which blocking issues each gate is raising
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tailor_health_script.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run it against the real workspace database**

Run: `.venv/Scripts/python.exe scripts/tailor_health.py data/users/1398ad91b2b2/resume_agent.db`
Expected: the historical numbers still print (77 versions, 26 jobs,
`fact-check 50`, `provenance 19`). The new gates report zero because no stored
round predates them — that is correct, not a failure.

- [ ] **Step 6: Lint and commit**

```bash
ruff check scripts/tailor_health.py tests/test_tailor_health_script.py
git add scripts/tailor_health.py tests/test_tailor_health_script.py
git commit -m "chore(tailor): report the new gates in tailor_health

Blocking-issue kinds are now keyed by gate, so a fact-check failure and a
numeric-evidence failure are separable. must-have-coverage rides reviewer_means
with no extra query: its score IS the share of evidenced must-haves that reached
the resume, which gives a judge-free before/after signal -- the judge in
evals/CALIBRATION.md is still un-anchored and supports only relative claims."
```

---

### Task 8: full-suite verification and results log

**Files:**
- Modify: `evals/RESULTS.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Run the whole backend suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS. Any failure in a fixture-driven test where the fixture resume
cites facts it does not support is the gate working — fix the fixture, not the
gate.

- [ ] **Step 2: Lint the whole tree**

Run: `ruff check`
Expected: no findings.

- [ ] **Step 3: Record the measurement plan**

Append to `evals/RESULTS.md`:

```markdown
## 2026-08-04 deterministic fact-lock gates + must-have coverage

Ships `skill-naming` and `numeric-evidence` as deterministic gates and wires the
already-computed `SkillMatchContext` into the writer, reviser, and advisory
panel. `score_threshold: 85` and `match_plan_enabled: false` remain untouched —
the Phase D arms below are still unrun.

Pre-change reference is the 2026-07-27 baseline above (77 versions / 26 jobs,
8/77 gate-clean, ats-keyword mean 55.1, 0/26 jobs reaching threshold).

Re-measure with `python scripts/tailor_health.py <workspace-db>` after a tailor
run of comparable size and fill in:

| metric | before | after |
| ------ | ------ | ----- |
| gate-clean rounds | 8 / 77 | |
| gate failures — fact-check | 50 | |
| gate failures — skill-naming | n/a | |
| gate failures — numeric-evidence | n/a | |
| ats-keyword mean | 55.1 | |
| must-have-coverage mean | n/a | |

Success criteria from the spec: zero rounds failing on a compound skill entry;
the fact-check metric/number bucket falls; the ats-keyword mean rises **without**
fact-check failures rising; remaining fact-check failures concentrate in
scope-creep claims.
```

- [ ] **Step 4: Commit**

```bash
git add evals/RESULTS.md
git commit -m "docs(evals): record the 2026-08-04 gate change measurement plan"
```

---

## Self-Review

**Spec coverage.** Gate `skill-naming` → Task 1. Gate `numeric-evidence` →
Task 2. `DETERMINISTIC_GATES` registration and per-round execution → Task 4.
`format_coverage` + three composer wirings → Tasks 3 and 5. `coverage_report`
and the missed-must-have major issue → Task 3, emitted in Task 5. `ats-keyword`
authoritative rubric → Task 6. All six prompt/config rows of the spec's Section
3 table → Task 6. `tailor_health` metrics → Task 7. Success criteria and the
results log → Task 8. No spec requirement is unclaimed.

**Deviation from the spec, deliberate.** The spec's Section 1 describes the
alias chain as `Skill.aliases` → `MatrixRow.aliases` → `cluster_map.aliases`.
Task 1 uses **only the cited `Skill`'s own name and aliases**. Consulting the
cluster map would be actively wrong: its alias table maps a token to a canonical
cluster token, which is precisely the "adjacent skill" relation fact-lock
forbids claiming as the job's own term — it would legalize exactly the renames
the gate exists to catch. It also avoids threading `ClusterMap` through
`arun_tailor_review`. This is recorded in the Global Constraints above, and the
spec's Section 1 has been amended to match, so plan and spec agree.

**Type consistency.** `skill_naming_critique`, `numeric_evidence_critique`, and
`coverage_critique` all take `(content, ...)` and return `ReviewCritique`
(`coverage_critique` returns `ReviewCritique | None`). `format_coverage` returns
`str` and every consumer treats `""` as "omit the block". `coverage` is the
parameter name in all five composer/panel signatures. Gate name constants are
`SKILL_NAMING_REVIEWER`, `NUMERIC_EVIDENCE_REVIEWER`, `COVERAGE_REVIEWER`, and
the string literals in the `tailor_health` and verdict tests match them.
