# Resume Agent v1.5 — Quality + Lean-Cost — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tailor/render pipeline faithfully reproduce and improve on the user's LaTeX sample resume — restoring the fact types it currently drops — while strengthening fact-lock and cutting per-run token cost.

**Architecture:** Additive, surgical changes on the existing sync `Runner` pipeline. New behavior is concentrated in small, deep modules (`tailor/provenance.py`, `tailor/length.py`) that several callers reuse; the review panel gains a real seam (lean vs. evidence input per reviewer); the Typst template gains an ordering wrapper. No concurrency. New parameters are optional-with-defaults so existing tests stay green.

**Tech Stack:** Python 3.13, Pydantic v2, SQLModel, Typst (`typst` pkg), `pypdf`, `pytest`, `uv`. Spec: `docs/superpowers/specs/2026-06-10-resume-agent-v1.5-design.md`.

**Conventions:**
- Run tests with `uv run pytest`.
- Every commit message ends with the trailer line: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` (omitted from the short commands below for brevity — add it).
- TDD: write the failing test, see it fail, implement minimally, see it pass, commit.
- Branch is already `v1.5`.

---

## File structure (what changes and why)

| File | Responsibility | Change |
|------|----------------|--------|
| `src/resume_agent/models/resume.py` | The structured, fact-locked resume the renderer consumes | Add `Tailored{Publication,Certification,Award,Volunteer}`; add `publications/certifications/awards/languages/volunteer/section_order` to `ResumeContent` |
| `src/resume_agent/tailor/provenance.py` *(new)* | **Deep module:** the single place that indexes profile fact ids, finds referenced ids, checks them, and resolves the evidence subset | Create |
| `src/resume_agent/tailor/length.py` *(new)* | One-page budget formatting + deterministic resume size stats | Create |
| `src/resume_agent/tailor/review_config.py` | Reviewer roster + thresholds | Add optional `LengthBudget` |
| `src/resume_agent/tailor/panel.py` | Run reviewers; **seam:** compose input per reviewer (lean vs evidence) | Replace single shared input with per-reviewer composition |
| `src/resume_agent/tailor/verdict.py` | Aggregate critiques into a verdict | Thread `provenance_passed` into the gate |
| `src/resume_agent/tailor/workflow.py` | The draft→gate→review→revise loop | Run the deterministic provenance gate first; short-circuit broken provenance; pass the budget to tailor/reviser |
| `src/resume_agent/tailor/tailoring.py` | Compose tailor/reviser prompts | Add the optional budget line |
| `src/resume_agent/profile/extractor.py` | Resume-text → `ProfileFacts` | Default to the mid model |
| `src/resume_agent/profile/merge.py` | Combine resume + GitHub facts | Dedupe GitHub projects against resume projects; enrich |
| `src/resume_agent/profile/validate.py` *(new)* | Deterministic coverage report over `ProfileFacts` + raw text | Create |
| `src/resume_agent/profile/build.py` | Orchestrate profile build | Return the coverage report alongside facts |
| `src/resume_agent/cli.py` | `profile build` command | Print the coverage report |
| `src/resume_agent/discovery/pipeline.py` | Discovery funnel stages | Commit once per stage, not per row |
| `templates/resume.typ` | PDF layout (LLM-free) | Rework to hybrid layout; render new sections + enriched education; honor `section_order` |
| `config/review.yaml.example` | Reviewer config doc | Document `length_budget` |

Test files mirror these under `tests/` (one per task below).

---

## Task 1: Extend `ResumeContent` with the restored sections

**Files:**
- Modify: `src/resume_agent/models/resume.py`
- Test: `tests/test_models_resume.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_models_resume.py`:

```python
from resume_agent.models.profile import Language
from resume_agent.models.resume import (
    ResumeContent,
    TailoredAward,
    TailoredCertification,
    TailoredPublication,
    TailoredVolunteer,
)


def test_new_sections_default_empty():
    rc = ResumeContent(contact=Contact(name="Ada"))
    assert rc.publications == []
    assert rc.certifications == []
    assert rc.awards == []
    assert rc.languages == []
    assert rc.volunteer == []
    assert rc.section_order is None


def test_tailored_publication_requires_provenance():
    with pytest.raises(ValidationError):
        TailoredPublication.model_validate({"title": "On Computable Numbers"})


def test_resume_content_carries_new_sections_round_trip():
    rc = ResumeContent(
        contact=Contact(name="Ada"),
        publications=[TailoredPublication(title="Notes on the Engine", venue="Memoirs", provenance="pub000000001")],
        certifications=[TailoredCertification(name="PE", issuer="NSPE", provenance="cer000000001")],
        awards=[TailoredAward(name="Best Paper", provenance="awa000000001")],
        languages=[Language(language="English", proficiency="native")],
        volunteer=[TailoredVolunteer(organization="OSS", role="Maintainer", provenance="vol000000001")],
        section_order=["experience", "education", "publications"],
    )
    restored = ResumeContent.model_validate_json(rc.model_dump_json())
    assert restored.publications[0].title == "Notes on the Engine"
    assert restored.section_order == ["experience", "education", "publications"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_models_resume.py -q`
Expected: FAIL — `ImportError` / `cannot import name 'TailoredPublication'`.

- [ ] **Step 3: Implement** — in `src/resume_agent/models/resume.py`, add the import and new models, and extend `ResumeContent`.

Change the import line at the top:

```python
from resume_agent.models.profile import Contact, Education, Language
```

Add these classes after `TailoredProject`:

```python
class TailoredPublication(ExtensibleModel):
    title: str
    venue: str | None = None
    date: str | None = None
    authors: list[str] = Field(default_factory=list)
    url: str | None = None
    provenance: str  # id of the source Publication


class TailoredCertification(ExtensibleModel):
    name: str
    issuer: str | None = None
    date: str | None = None
    url: str | None = None
    provenance: str  # id of the source Certification


class TailoredAward(ExtensibleModel):
    name: str
    issuer: str | None = None
    date: str | None = None
    description: str | None = None
    provenance: str  # id of the source Award


class TailoredVolunteer(ExtensibleModel):
    organization: str
    role: str | None = None
    start: str | None = None
    end: str | None = None
    bullets: list[TailoredBullet] = Field(default_factory=list)
    provenance: str  # id of the source Volunteer record
```

Extend `ResumeContent` (add the new fields after `education`):

```python
class ResumeContent(ExtensibleModel):
    """Structured, fact-locked resume content. The renderer turns this into a PDF;
    the LLM never emits markup."""

    contact: Contact  # carried verbatim from ProfileFacts (no invention)
    summary: str | None = None
    experience: list[TailoredExperience] = Field(default_factory=list)
    projects: list[TailoredProject] = Field(default_factory=list)
    skills: dict[str, list[TailoredSkill]] = Field(default_factory=dict)
    education: list[Education] = Field(default_factory=list)  # carried verbatim
    publications: list[TailoredPublication] = Field(default_factory=list)
    certifications: list[TailoredCertification] = Field(default_factory=list)
    awards: list[TailoredAward] = Field(default_factory=list)
    languages: list[Language] = Field(default_factory=list)  # carried verbatim
    volunteer: list[TailoredVolunteer] = Field(default_factory=list)
    section_order: list[str] | None = None  # optional per-JD ordering hint
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_models_resume.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/models/resume.py tests/test_models_resume.py
git commit -m "feat(models): restore publications/certs/awards/languages/volunteer + section_order on ResumeContent"
```

---

## Task 2: Deterministic provenance core (`index_facts`, `referenced_ids`, `check_provenance`)

**Architecture note (deletion test):** these three functions are the *only* place that walks the fact graph. Deleting the module would scatter identical traversal logic across the workflow gate, the evidence view, and tests — complexity reappears across callers, so the module earns its keep. Its interface is small (ids in, report out); its implementation is the tedious traversal. That is a deep module.

**Files:**
- Create: `src/resume_agent/tailor/provenance.py`
- Test: `tests/test_tailor_provenance.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_tailor_provenance.py`:

```python
from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Project,
    Skill,
)
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
    TailoredSkill,
)
from resume_agent.tailor.provenance import (
    ProvenanceReport,
    check_provenance,
    index_facts,
    referenced_ids,
)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(id="e1", company="AE", title="Engineer", bullets=[Bullet(id="b1", text="Built X")])
        ],
        projects=[Project(id="p1", name="Looms")],
        skills={"languages": [Skill(id="s1", name="Python")]},
    )


def _content(bullet_prov="b1", skill_prov="s1") -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE", title="Engineer", provenance="e1",
                bullets=[TailoredBullet(text="Built X", provenance=bullet_prov)],
            )
        ],
        projects=[TailoredProject(name="Looms", provenance="p1")],
        skills={"languages": [TailoredSkill(name="Python", provenance=skill_prov)]},
    )


def test_index_facts_collects_every_id():
    idx = index_facts(_facts())
    assert set(idx) == {"e1", "b1", "p1", "s1"}


def test_referenced_ids_walks_content():
    assert referenced_ids(_content()) == {"e1", "b1", "p1", "s1"}


def test_check_provenance_passes_when_all_resolve():
    report = check_provenance(_content(), _facts())
    assert isinstance(report, ProvenanceReport)
    assert report.ok is True
    assert report.missing == []


def test_check_provenance_flags_fabricated_id():
    # adversarial fact test: a bullet cites a fact id that does not exist
    report = check_provenance(_content(bullet_prov="ghost999"), _facts())
    assert report.ok is False
    assert report.missing == ["ghost999"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tailor_provenance.py -q`
Expected: FAIL — module `resume_agent.tailor.provenance` does not exist.

- [ ] **Step 3: Implement** — create `src/resume_agent/tailor/provenance.py`:

```python
from typing import Any

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent


class ProvenanceReport(ExtensibleModel):
    """Result of the deterministic provenance check."""

    ok: bool
    missing: list[str] = Field(default_factory=list)  # referenced ids absent from the fact graph


def index_facts(facts: ProfileFacts) -> dict[str, Any]:
    """Map every provenance-addressable fact id to its fact object.

    This is the single source of truth for what a ``provenance`` pointer may
    target: experiences and their bullets, projects, skills, education,
    publications, certifications, awards, languages, and volunteer records.
    """
    index: dict[str, Any] = {}
    for exp in facts.experience:
        index[exp.id] = exp
        for bullet in exp.bullets:
            index[bullet.id] = bullet
    for proj in facts.projects:
        index[proj.id] = proj
    for skills in facts.skills.values():
        for skill in skills:
            index[skill.id] = skill
    for record in (*facts.education, *facts.publications, *facts.certifications,
                   *facts.awards, *facts.languages, *facts.volunteer):
        index[record.id] = record
    return index


def referenced_ids(content: ResumeContent) -> set[str]:
    """Every provenance id the resume claims to draw from."""
    ids: set[str] = set()
    for exp in content.experience:
        ids.add(exp.provenance)
        ids.update(b.provenance for b in exp.bullets)
    for proj in content.projects:
        ids.add(proj.provenance)
        ids.update(b.provenance for b in proj.bullets)
    for skills in content.skills.values():
        ids.update(s.provenance for s in skills)
    ids.update(p.provenance for p in content.publications)
    ids.update(c.provenance for c in content.certifications)
    ids.update(a.provenance for a in content.awards)
    for vol in content.volunteer:
        ids.add(vol.provenance)
        ids.update(b.provenance for b in vol.bullets)
    return ids


def check_provenance(content: ResumeContent, facts: ProfileFacts) -> ProvenanceReport:
    """Fail fast in plain code: every referenced id must resolve to a real fact."""
    valid = set(index_facts(facts))
    missing = sorted(i for i in referenced_ids(content) if i not in valid)
    return ProvenanceReport(ok=not missing, missing=missing)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_tailor_provenance.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/provenance.py tests/test_tailor_provenance.py
git commit -m "feat(tailor): deterministic provenance index + check"
```

---

## Task 3: Evidence view (`resolve_evidence`)

**Files:**
- Modify: `src/resume_agent/tailor/provenance.py`
- Test: `tests/test_tailor_provenance.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_tailor_provenance.py`:

```python
from resume_agent.tailor.provenance import resolve_evidence


def test_resolve_evidence_returns_only_referenced_facts():
    facts = _facts()
    # add an unreferenced extra skill that must NOT leak into the evidence view
    facts.skills["languages"].append(Skill(id="s2", name="Rust"))
    evidence = resolve_evidence(_content(), facts)
    assert set(evidence) == {"e1", "b1", "p1", "s1"}
    assert evidence["b1"]["text"] == "Built X"
    assert "s2" not in evidence
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tailor_provenance.py::test_resolve_evidence_returns_only_referenced_facts -q`
Expected: FAIL — `cannot import name 'resolve_evidence'`.

- [ ] **Step 3: Implement** — append to `src/resume_agent/tailor/provenance.py`:

```python
def resolve_evidence(content: ResumeContent, facts: ProfileFacts) -> dict[str, Any]:
    """The provenance-resolved subset: only the facts the resume actually cites.

    This is what the fact-check reviewer receives instead of the whole profile,
    so the prompt never re-ships unrelated facts (e.g. every GitHub repo).
    """
    index = index_facts(facts)
    return {i: index[i].model_dump(mode="json") for i in sorted(referenced_ids(content)) if i in index}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_tailor_provenance.py -q`
Expected: PASS (all provenance tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/provenance.py tests/test_tailor_provenance.py
git commit -m "feat(tailor): provenance-resolved evidence view for the fact-checker"
```

---

## Task 4: Length budget + resume stats (`tailor/length.py`, config)

**Files:**
- Create: `src/resume_agent/tailor/length.py`
- Modify: `src/resume_agent/tailor/review_config.py`
- Test: `tests/test_tailor_length.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_tailor_length.py`:

```python
from resume_agent.models.profile import Contact
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredProject,
)
from resume_agent.tailor.length import format_budget, resume_stats
from resume_agent.tailor.review_config import LengthBudget, ReviewConfig


def test_length_budget_defaults_present_on_config():
    cfg = ReviewConfig()
    assert cfg.length_budget.max_experiences == 4
    assert cfg.length_budget.max_bullets_per_role == 5
    assert cfg.length_budget.target_total_bullets == 20


def test_format_budget_mentions_one_page_and_numbers():
    text = format_budget(LengthBudget(max_experiences=3, max_bullets_per_role=4, target_total_bullets=15))
    assert "single page" in text
    assert "3" in text and "4" in text and "15" in text


def test_resume_stats_counts_experiences_projects_and_bullets():
    rc = ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(company="AE", title="Eng", provenance="e1", bullets=[
                TailoredBullet(text="a", provenance="b1"),
                TailoredBullet(text="b", provenance="b2"),
            ])
        ],
        projects=[TailoredProject(name="Looms", provenance="p1", bullets=[
            TailoredBullet(text="c", provenance="p1b1"),
        ])],
    )
    stats = resume_stats(rc)
    assert "experiences=1" in stats
    assert "projects=1" in stats
    assert "total_bullets=3" in stats
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tailor_length.py -q`
Expected: FAIL — `LengthBudget` and module `tailor.length` do not exist.

- [ ] **Step 3a: Implement config** — in `src/resume_agent/tailor/review_config.py`, add `LengthBudget` and wire it onto `ReviewConfig`:

```python
class LengthBudget(ExtensibleModel):
    """One-page guidance handed to the tailor and surfaced to the concision reviewer."""

    max_experiences: int = 4
    max_bullets_per_role: int = 5
    target_total_bullets: int = 20


class ReviewConfig(ExtensibleModel):
    max_rounds: int = Field(default=3, ge=1)
    score_threshold: int = 85
    reviewers: list[ReviewerSpec] = Field(default_factory=list)
    length_budget: LengthBudget = Field(default_factory=LengthBudget)
```

- [ ] **Step 3b: Implement length helpers** — create `src/resume_agent/tailor/length.py`:

```python
from resume_agent.models.resume import ResumeContent
from resume_agent.tailor.review_config import LengthBudget


def format_budget(budget: LengthBudget) -> str:
    """Render the budget as an instruction line for the tailor/reviser prompt."""
    return (
        f"Target a single page. Use at most {budget.max_experiences} experiences, "
        f"at most {budget.max_bullets_per_role} bullets per role, and about "
        f"{budget.target_total_bullets} bullets in total. Prefer the most relevant facts; drop the rest."
    )


def resume_stats(content: ResumeContent) -> str:
    """Deterministic size summary shown to non-gate reviewers (esp. concision)."""
    total_bullets = sum(len(e.bullets) for e in content.experience) + sum(
        len(p.bullets) for p in content.projects
    )
    return (
        f"experiences={len(content.experience)} projects={len(content.projects)} "
        f"total_bullets={total_bullets}"
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_tailor_length.py tests/test_tailor_review_config.py -q`
Expected: PASS (new tests pass; existing review_config tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/length.py src/resume_agent/tailor/review_config.py tests/test_tailor_length.py
git commit -m "feat(tailor): length budget config + deterministic resume stats"
```

---

## Task 5: Per-reviewer payload trimming (the panel seam)

**Architecture note (real seam):** the panel now has two adapters at one seam — a *lean* input (resume + JD + stats) for non-gate reviewers and an *evidence* input (resume + JD + only-referenced facts) for the gate reviewer. Two adapters = a real seam, not a hypothetical one. The raw profile stops flowing to four of five reviewers.

**Files:**
- Modify: `src/resume_agent/tailor/panel.py`
- Modify: `src/resume_agent/tailor/workflow.py` (call site only; full rewrite is Task 6)
- Test: `tests/test_tailor_panel.py`

- [ ] **Step 1: Rewrite the test** — replace the whole body of `tests/test_tailor_panel.py`:

```python
import pytest

from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Skill,
)
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.panel import (
    compose_evidence_review_input,
    compose_lean_review_input,
    review_one,
    run_panel,
)
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self._content = content
        self.received = None

    def run(self, prompt):
        self.received = prompt
        return _Result(self._content)


def _facts() -> ProfileFacts:
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="e1", company="AE", title="Eng", bullets=[Bullet(id="b1", text="Built X")])],
        skills={"languages": [Skill(id="s1", name="Python"), Skill(id="s2", name="SecretRust")]},
    )
    return facts


def _content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[TailoredExperience(company="AE", title="Eng", provenance="e1",
                                       bullets=[TailoredBullet(text="Built X", provenance="b1")])],
        skills={"languages": [TailoredSkill(name="Python", provenance="s1")]},
    )


def test_lean_input_has_no_raw_profile():
    text = compose_lean_review_input(_content(), "Backend role", "experiences=1")
    assert "Backend role" in text
    assert "experiences=1" in text
    assert "SecretRust" not in text  # the raw profile never reaches non-gate reviewers


def test_evidence_input_carries_only_referenced_facts():
    from resume_agent.tailor.provenance import resolve_evidence
    evidence = resolve_evidence(_content(), _facts())
    text = compose_evidence_review_input(_content(), "Backend role", evidence)
    assert "b1" in text
    assert "SecretRust" not in text  # s2 is unreferenced, so it is not in the evidence


def test_review_one_rejects_wrong_type():
    with pytest.raises(TypeError):
        review_one("x", _Agent("nope"))


def test_run_panel_routes_gate_to_evidence_and_others_to_lean():
    config = ReviewConfig(
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ]
    )
    agents = {
        "fact-check": _Agent(ReviewCritique(reviewer="fact-check", score=100, passed=True)),
        "ats-keyword": _Agent(ReviewCritique(reviewer="ats-keyword", score=80, passed=True)),
    }
    critiques = run_panel(_content(), _facts(), "Backend role", config, agents)

    assert [c.reviewer for c in critiques] == ["fact-check", "ats-keyword"]
    # the non-gate reviewer never saw the unreferenced fact
    assert "SecretRust" not in agents["ats-keyword"].received
    # the gate reviewer received supporting evidence
    assert "SUPPORTING FACTS" in agents["fact-check"].received
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tailor_panel.py -q`
Expected: FAIL — `compose_lean_review_input` / `compose_evidence_review_input` do not exist; `run_panel` signature mismatch.

- [ ] **Step 3: Implement** — replace the whole body of `src/resume_agent/tailor/panel.py`:

```python
import json
from collections.abc import Mapping
from typing import Any

from resume_agent.llm_runner import Runner
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.length import resume_stats
from resume_agent.tailor.provenance import resolve_evidence
from resume_agent.tailor.review_config import ReviewConfig


def compose_lean_review_input(content: ResumeContent, jd_text: str, stats: str) -> str:
    """Input for non-gate reviewers: the resume + JD + size stats. No raw profile."""
    return (
        "RESUME UNDER REVIEW (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "RESUME STATS:\n"
        f"{stats}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def compose_evidence_review_input(
    content: ResumeContent, jd_text: str, evidence: Mapping[str, Any]
) -> str:
    """Input for the fact-check (gate) reviewer: resume + JD + only-referenced facts."""
    return (
        "RESUME UNDER REVIEW (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "SUPPORTING FACTS (the only profile facts this resume cites, keyed by id):\n"
        f"{json.dumps(evidence)}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def review_one(input_text: str, agent: Runner) -> ReviewCritique:
    result = agent.run(input_text)
    critique = result.content
    if not isinstance(critique, ReviewCritique):
        raise TypeError(f"Expected ReviewCritique from reviewer, got {type(critique).__name__}")
    return critique


def run_panel(
    content: ResumeContent,
    profile_facts: ProfileFacts,
    jd_text: str,
    config: ReviewConfig,
    reviewer_agents: Mapping[str, Runner],
) -> list[ReviewCritique]:
    """Run every configured reviewer, composing the smallest sufficient input per role."""
    evidence = resolve_evidence(content, profile_facts)
    stats = resume_stats(content)
    critiques: list[ReviewCritique] = []
    for spec in config.reviewers:
        if spec.gate:
            text = compose_evidence_review_input(content, jd_text, evidence)
        else:
            text = compose_lean_review_input(content, jd_text, stats)
        critiques.append(review_one(text, reviewer_agents[spec.name]))
    return critiques
```

- [ ] **Step 4: Patch the workflow call site** — in `src/resume_agent/tailor/workflow.py`, the `run_panel(...)` call and the now-dead `compose_review_input` import will break. Update the import line:

```python
from resume_agent.tailor.panel import run_panel
```

and change the panel call inside the loop from:

```python
        critiques = run_panel(
            compose_review_input(content, profile_facts, jd_text), config, reviewer_agents
        )
```

to:

```python
        critiques = run_panel(content, profile_facts, jd_text, config, reviewer_agents)
```

(Task 6 rewrites this file fully; this keeps the suite green in between.)

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_tailor_panel.py tests/test_tailor_workflow.py tests/test_tailor_service.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/tailor/panel.py src/resume_agent/tailor/workflow.py tests/test_tailor_panel.py
git commit -m "perf(tailor): per-reviewer payload trimming (lean vs evidence input)"
```

---

## Task 6: Provenance pre-gate in the loop

**Files:**
- Modify: `src/resume_agent/tailor/verdict.py`
- Modify: `src/resume_agent/tailor/workflow.py`
- Test: `tests/test_tailor_verdict.py`, `tests/test_tailor_workflow.py`

- [ ] **Step 1: Write the failing verdict test** — append to `tests/test_tailor_verdict.py`:

```python
def test_provenance_failure_blocks_gate_even_if_reviewers_pass():
    critiques = [
        ReviewCritique(reviewer="fact-check", score=100, passed=True),
        ReviewCritique(reviewer="ats-keyword", score=100, passed=True),
        ReviewCritique(reviewer="recruiter", score=100, passed=True),
    ]
    verdict = aggregate(critiques, _config(), provenance_passed=False)
    assert verdict.gate_passed is False
    assert verdict.passed is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tailor_verdict.py::test_provenance_failure_blocks_gate_even_if_reviewers_pass -q`
Expected: FAIL — `aggregate()` got an unexpected keyword argument `provenance_passed`.

- [ ] **Step 3: Implement verdict change** — in `src/resume_agent/tailor/verdict.py`, change the `aggregate` signature and the gate computation:

```python
def aggregate(
    critiques: list[ReviewCritique], config: ReviewConfig, provenance_passed: bool = True
) -> PanelVerdict:
    """Combine critiques: gate reviewers are blocking; the rest are a weighted average.

    ``provenance_passed`` is the deterministic structural gate; it is ANDed with the
    LLM fact-checker so a broken provenance id can never pass.
    """
    by_name = {c.reviewer: c for c in critiques}

    gate_names = [r.name for r in config.reviewers if r.gate and r.name in by_name]
    gate_passed = provenance_passed and all(by_name[name].passed for name in gate_names)

    weighted = [
        (r.weight, by_name[r.name].score)
        for r in config.reviewers
        if not r.gate and r.weight > 0 and r.name in by_name
    ]
    total_weight = sum(weight for weight, _ in weighted)
    aggregate_score = (
        round(sum(weight * score for weight, score in weighted) / total_weight) if total_weight else 0
    )

    passed = gate_passed and aggregate_score >= config.score_threshold
    return PanelVerdict(
        passed=passed,
        gate_passed=gate_passed,
        aggregate_score=aggregate_score,
        critiques=critiques,
    )
```

- [ ] **Step 4: Write the failing workflow test** — append to `tests/test_tailor_workflow.py`:

```python
def test_broken_provenance_short_circuits_panel():
    from resume_agent.models.profile import Bullet, Experience
    from resume_agent.models.resume import TailoredBullet, TailoredExperience

    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="e1", company="AE", title="Eng", bullets=[Bullet(id="b1", text="X")])],
    )

    class _BadTailor:
        """Tailor cites a fabricated id, so the structural gate must block."""

        def run(self, prompt):
            return _Result(ResumeContent(
                contact=Contact(name="Ada"),
                experience=[TailoredExperience(company="AE", title="Eng", provenance="e1",
                                               bullets=[TailoredBullet(text="X", provenance="ghost")])],
            ))

    class _ExplodingReviewer:
        """Must never be called when provenance is structurally broken."""

        def run(self, prompt):
            raise AssertionError("panel should be skipped when provenance is broken")

    config = ReviewConfig(
        max_rounds=1,  # one round is enough to observe the short-circuit
        score_threshold=1,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    rounds = run_tailor_review(
        jd_text="role",
        criteria=JobCriteria(),
        profile_facts=facts,
        config=config,
        tailor_agent=_BadTailor(),
        reviewer_agents={"fact-check": _ExplodingReviewer()},
        reviser_agent=_BadTailor(),
    )

    assert len(rounds) == 1
    assert rounds[0].verdict.gate_passed is False
    assert rounds[0].verdict.critiques[0].reviewer == "provenance"  # synthetic, no LLM call
```

- [ ] **Step 5: Run to verify it fails**

Run: `uv run pytest tests/test_tailor_workflow.py -q`
Expected: FAIL — no `"provenance"` synthetic critique yet (panel runs and the exploding reviewer raises, or gate logic missing).

- [ ] **Step 6: Implement the workflow** — replace the whole body of `src/resume_agent/tailor/workflow.py`:

```python
from collections.abc import Mapping

from resume_agent.llm_runner import Runner
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tailor.panel import run_panel
from resume_agent.tailor.provenance import ProvenanceReport, check_provenance
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.tailoring import compose_revise_input, compose_tailor_input, revise, tailor
from resume_agent.tailor.verdict import PanelVerdict, aggregate


class TailorRound(ExtensibleModel):
    round_num: int
    content: ResumeContent
    verdict: PanelVerdict


def _provenance_verdict(report: ProvenanceReport) -> PanelVerdict:
    """Build a blocking verdict from a failed structural check — no LLM involved."""
    critique = ReviewCritique(
        reviewer="provenance",
        score=0,
        passed=False,
        issues=[
            ReviewIssue(severity=Severity.blocking, message=f"provenance id not found in profile facts: {mid}")
            for mid in report.missing
        ],
    )
    return PanelVerdict(passed=False, gate_passed=False, aggregate_score=0, critiques=[critique])


def run_tailor_review(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: Mapping[str, Runner],
    reviser_agent: Runner,
) -> list[TailorRound]:
    """Draft, then gate→review/revise until the round passes or max_rounds is hit.

    The deterministic provenance gate runs first each round. A broken id blocks the
    round immediately and skips every reviewer LLM call; only structurally valid
    drafts reach the panel (which still semantically fact-checks via the LLM).
    """
    content = tailor(compose_tailor_input(jd_text, criteria, profile_facts), tailor_agent)
    rounds: list[TailorRound] = []
    for round_num in range(1, config.max_rounds + 1):
        report = check_provenance(content, profile_facts)
        if not report.ok:
            verdict = _provenance_verdict(report)
        else:
            critiques = run_panel(content, profile_facts, jd_text, config, reviewer_agents)
            verdict = aggregate(critiques, config, provenance_passed=True)
        rounds.append(TailorRound(round_num=round_num, content=content, verdict=verdict))
        if verdict.passed or round_num == config.max_rounds:
            break
        content = revise(
            compose_revise_input(content, verdict.critiques, profile_facts), reviser_agent
        )
    return rounds
```

The budget is threaded into these two `compose_*` calls in Task 7, after the compose functions learn to accept it. Keeping the 3-arg calls here means this task is green on its own.

- [ ] **Step 7: Run verdict + workflow tests**

Run: `uv run pytest tests/test_tailor_verdict.py tests/test_tailor_workflow.py tests/test_tailor_service.py -q`
Expected: PASS — the deterministic gate blocks the fabricated-id round without calling the panel.

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/tailor/verdict.py src/resume_agent/tailor/workflow.py tests/test_tailor_verdict.py tests/test_tailor_workflow.py
git commit -m "feat(tailor): deterministic provenance pre-gate short-circuits the panel"
```

---

## Task 7: Length budget into the tailor/reviser contract

**Files:**
- Modify: `src/resume_agent/tailor/tailoring.py`
- Test: `tests/test_tailor_tailoring.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_tailor_tailoring.py`:

```python
from resume_agent.tailor.review_config import LengthBudget


def test_compose_tailor_input_includes_budget_when_given():
    text = compose_tailor_input("Backend role", JobCriteria(), _facts(),
                                LengthBudget(max_experiences=3, max_bullets_per_role=4, target_total_bullets=15))
    assert "single page" in text
    assert "3" in text


def test_compose_revise_input_includes_budget_when_given():
    rc = ResumeContent(contact=Contact(name="Ada"))
    text = compose_revise_input(rc, [], _facts(), LengthBudget())
    assert "single page" in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_tailor_tailoring.py -q`
Expected: FAIL — `compose_tailor_input()` takes 3 positional args but 4 were given.

- [ ] **Step 3: Implement** — in `src/resume_agent/tailor/tailoring.py`:

Add the import at the top:

```python
from resume_agent.tailor.length import format_budget
from resume_agent.tailor.review_config import LengthBudget
```

Change `compose_tailor_input` to accept an optional budget (keeps the old 3-arg call working):

```python
def compose_tailor_input(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    length_budget: LengthBudget | None = None,
) -> str:
    budget_line = f"\n\nLENGTH BUDGET:\n{format_budget(length_budget)}" if length_budget else ""
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "JOB CRITERIA (JSON):\n"
        f"{criteria.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
        f"{budget_line}"
    )
```

Change `compose_revise_input` the same way (append an optional `length_budget` param and a budget line):

```python
def compose_revise_input(
    content: ResumeContent,
    critiques: list[ReviewCritique],
    profile_facts: ProfileFacts,
    length_budget: LengthBudget | None = None,
) -> str:
    issues = "\n".join(
        f"- [{c.reviewer}] {issue.severity.value}: {issue.message}"
        + (f" (suggestion: {issue.suggestion})" if issue.suggestion else "")
        for c in critiques
        for issue in c.issues
    )
    suggestions = "\n".join(
        f"- [{c.reviewer}] {suggestion}"
        for c in critiques
        for suggestion in c.suggestions
    )
    budget_line = f"\n\nLENGTH BUDGET:\n{format_budget(length_budget)}" if length_budget else ""
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT RESUME (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "REVIEWER ISSUES:\n"
        f"{issues}\n\n"
        "REVIEWER SUGGESTIONS:\n"
        f"{suggestions}"
        f"{budget_line}"
    )
```

- [ ] **Step 4: Thread the budget through the workflow** — in `src/resume_agent/tailor/workflow.py`, pass `config.length_budget` into the two `compose_*` calls. Change:

```python
    content = tailor(compose_tailor_input(jd_text, criteria, profile_facts), tailor_agent)
```

to:

```python
    content = tailor(
        compose_tailor_input(jd_text, criteria, profile_facts, config.length_budget), tailor_agent
    )
```

and change:

```python
        content = revise(
            compose_revise_input(content, verdict.critiques, profile_facts), reviser_agent
        )
```

to:

```python
        content = revise(
            compose_revise_input(content, verdict.critiques, profile_facts, config.length_budget),
            reviser_agent,
        )
```

- [ ] **Step 5: Run the full tailor suite**

Run: `uv run pytest tests/test_tailor_tailoring.py tests/test_tailor_workflow.py tests/test_tailor_service.py -q`
Expected: PASS (old 3-arg compose tests still work; the workflow now passes the budget; the broken-provenance test stays green).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/tailor/tailoring.py src/resume_agent/tailor/workflow.py tests/test_tailor_tailoring.py
git commit -m "feat(tailor): one-page length budget in the tailor/reviser contract"
```

---

## Task 8: Profile extractor → mid tier

**Files:**
- Modify: `src/resume_agent/profile/extractor.py`
- Test: `tests/test_profile_extractor.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_profile_extractor.py`:

```python
def test_extractor_defaults_to_mid_tier(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    captured = {}

    import resume_agent.profile.extractor as extractor_mod

    class _FakeClaude:
        def __init__(self, id):
            captured["id"] = id

    class _FakeAgent:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(extractor_mod, "Claude", _FakeClaude)
    monkeypatch.setattr(extractor_mod, "Agent", _FakeAgent)

    extractor_mod.build_extractor_agent()
    assert captured["id"] == extractor_mod.get_settings().mid_model
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_profile_extractor.py::test_extractor_defaults_to_mid_tier -q`
Expected: FAIL — `captured["id"]` equals the cheap model, not the mid model.

- [ ] **Step 3: Implement** — in `src/resume_agent/profile/extractor.py`, change the one line in `build_extractor_agent`:

```python
    resolved = model_id or get_settings().mid_model
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_profile_extractor.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/extractor.py tests/test_profile_extractor.py
git commit -m "feat(profile): extract with the mid model for higher fidelity on dense resumes"
```

---

## Task 9: Merge dedupe (GitHub vs resume projects)

**Files:**
- Modify: `src/resume_agent/profile/merge.py`
- Test: `tests/test_profile_merge.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_profile_merge.py`:

```python
def test_merge_dedupes_github_project_by_normalized_name_and_enriches():
    resume_facts = ProfileFacts(
        contact=Contact(name="Ada"),
        projects=[Project(name="Resume Agent", source=Source.resume)],  # no stars/repo_url yet
    )
    gh_projects = [Project(name="resume-agent", source=Source.github, stars=42, repo_url="https://github.com/ada/resume-agent")]

    merged = merge_facts(resume_facts, github_projects=gh_projects)

    names = [p.name for p in merged.projects]
    assert names == ["Resume Agent"]  # the github duplicate is folded in, not appended
    assert merged.projects[0].stars == 42  # empty fields enriched from github
    assert merged.projects[0].repo_url == "https://github.com/ada/resume-agent"


def test_merge_keeps_distinct_github_project():
    resume_facts = ProfileFacts(contact=Contact(name="Ada"), projects=[Project(name="from-resume")])
    gh = [Project(name="totally-different", source=Source.github)]
    merged = merge_facts(resume_facts, github_projects=gh)
    assert [p.name for p in merged.projects] == ["from-resume", "totally-different"]
```

Keep the existing `test_merge_appends_github_projects_and_sets_profile` only if its names are non-duplicate — they are (`from-resume` vs `from-github`), so it stays valid.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_profile_merge.py -q`
Expected: FAIL — duplicate is appended (names == ["Resume Agent", "resume-agent"]).

- [ ] **Step 3: Implement** — replace the body of `src/resume_agent/profile/merge.py`:

```python
import re

from resume_agent.models.profile import GitHubProfile, ProfileFacts, Project

# fields a resume project may be missing that GitHub can fill in
_ENRICH_FIELDS = ("stars", "forks", "repo_url", "primary_language", "homepage_url", "last_updated")


def _norm(name: str) -> str:
    """Normalize a project name for duplicate detection: casefold, drop non-alphanumerics."""
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def _enrich(resume_project: Project, github_project: Project) -> None:
    """Fill empty resume-project fields from its GitHub twin. Resume facts win on conflict."""
    for field in _ENRICH_FIELDS:
        if getattr(resume_project, field) in (None, [], "") and getattr(github_project, field) is not None:
            setattr(resume_project, field, getattr(github_project, field))


def merge_facts(
    resume_facts: ProfileFacts,
    github_projects: list[Project] | None = None,
    github_profile: GitHubProfile | None = None,
) -> ProfileFacts:
    """Combine resume-derived facts with GitHub-derived facts into one ProfileFacts.

    Returns a copy; the resume facts are not mutated. A GitHub project whose
    normalized name matches a resume project is folded into that project
    (enriching empty fields) rather than appended, so the same work never
    appears twice.
    """
    merged = resume_facts.model_copy(deep=True)
    if github_projects:
        by_norm = {_norm(p.name): p for p in merged.projects}
        for gh in github_projects:
            twin = by_norm.get(_norm(gh.name))
            if twin is not None:
                _enrich(twin, gh)
            else:
                merged.projects.append(gh)
    if github_profile is not None:
        merged.github_profile = github_profile
    return merged
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_profile_merge.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/merge.py tests/test_profile_merge.py
git commit -m "feat(profile): dedupe GitHub projects against resume projects and enrich"
```

---

## Task 10: Deterministic profile coverage report

**Files:**
- Create: `src/resume_agent/profile/validate.py`
- Modify: `src/resume_agent/profile/build.py`
- Modify: `src/resume_agent/cli.py`
- Test: `tests/test_profile_validate.py`, `tests/test_cli_profile.py`

- [ ] **Step 1: Write the failing validate test** — create `tests/test_profile_validate.py`:

```python
from resume_agent.models.profile import Contact, Experience, ProfileFacts, Publication
from resume_agent.profile.validate import validate_profile


def test_clean_profile_has_no_warnings():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(company="AE", title="Eng", bullets=[__import__("resume_agent.models.profile", fromlist=["Bullet"]).Bullet(text="X")])],
    )
    report = validate_profile(facts, raw_text="Ada, Engineer at AE")
    assert report.ok is True
    assert report.warnings == []


def test_missing_name_is_flagged():
    facts = ProfileFacts(contact=Contact(name=""))
    report = validate_profile(facts, raw_text="")
    assert report.ok is False
    assert any("name" in w for w in report.warnings)


def test_experience_without_bullets_is_flagged():
    facts = ProfileFacts(contact=Contact(name="Ada"), experience=[Experience(company="AE", title="Eng")])
    report = validate_profile(facts, raw_text="x")
    assert any("no bullets" in w for w in report.warnings)


def test_publications_in_text_but_not_extracted_is_flagged():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    report = validate_profile(facts, raw_text="PUBLICATIONS\nSmith, A. Great Paper. 2022.")
    assert any("publication" in w.lower() for w in report.warnings)


def test_publications_present_when_extracted():
    facts = ProfileFacts(contact=Contact(name="Ada"), publications=[Publication(title="Great Paper")])
    report = validate_profile(facts, raw_text="PUBLICATIONS\nSmith, A. Great Paper. 2022.")
    assert not any("publication" in w.lower() for w in report.warnings)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_profile_validate.py -q`
Expected: FAIL — module `resume_agent.profile.validate` does not exist.

- [ ] **Step 3: Implement validate** — create `src/resume_agent/profile/validate.py`:

```python
from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts

# (section keyword in the raw resume text, attribute on ProfileFacts) pairs we expect to co-occur
_SECTION_CUES = (
    ("publication", "publications"),
    ("certification", "certifications"),
    ("award", "awards"),
    ("volunteer", "volunteer"),
)


class CoverageReport(ExtensibleModel):
    """Advisory, deterministic checks over an extracted profile. Never blocks."""

    ok: bool
    warnings: list[str] = Field(default_factory=list)


def validate_profile(facts: ProfileFacts, raw_text: str) -> CoverageReport:
    warnings: list[str] = []

    if not facts.contact.name.strip():
        warnings.append("contact.name is empty")

    for exp in facts.experience:
        if not exp.bullets:
            warnings.append(f"experience '{exp.title} @ {exp.company}' has no bullets")

    lowered = raw_text.lower()
    for cue, attr in _SECTION_CUES:
        if cue in lowered and not getattr(facts, attr):
            warnings.append(f"raw text mentions '{cue}' but no {attr} were extracted")

    return CoverageReport(ok=not warnings, warnings=warnings)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_profile_validate.py -q`
Expected: PASS.

- [ ] **Step 5: Thread the report through `build_profile`** — change `src/resume_agent/profile/build.py` to also return the raw text so the CLI can validate. Update the return type to a tuple `(ProfileFacts, str)`:

Change the signature and the two `return` statements:

```python
def build_profile(
    resume_path: str | Path,
    github_username: str | None,
    extractor_agent: Runner | None = None,
    github_client=None,
) -> tuple[ProfileFacts, str]:
    """Build merged ProfileFacts from a resume file and (optionally) GitHub.

    Returns the facts plus the raw resume text (for the deterministic coverage report).
    """
    text = read_resume_text(resume_path)
    agent = extractor_agent if extractor_agent is not None else build_extractor_agent()
    resume_facts = extract_profile_facts(text, agent)

    if not github_username:
        return merge_facts(resume_facts), text

    gh = github_client if github_client is not None else GitHubClient()
    profile_data = gh.fetch_profile(github_username)
    repos = gh.fetch_repos(github_username)
    gh_profile = build_github_profile(profile_data, repos)
    projects = [repo_to_project(repo) for repo in repos]
    return merge_facts(resume_facts, github_projects=projects, github_profile=gh_profile), text
```

- [ ] **Step 6: Update the CLI** — in `src/resume_agent/cli.py`, add the import near the other profile imports:

```python
from resume_agent.profile.validate import validate_profile
```

and update `profile_build` to unpack the tuple and print warnings:

```python
    cfg = load_yaml(sources)
    facts, raw_text = build_profile(
        resume_path=_require_str(cfg.get("resume_path"), "resume_path"),
        github_username=cast(str | None, cfg.get("github_username")),
    )
    report = validate_profile(facts, raw_text)
    path = save_facts(facts, out)
    typer.echo(
        f"Wrote {len(facts.experience)} experiences and {len(facts.projects)} projects to {path}"
    )
    for warning in report.warnings:
        typer.echo(f"  ⚠ {warning}")
```

- [ ] **Step 7: Update the CLI profile tests** — in `tests/test_cli_profile.py`, the monkeypatched `build_profile` must now return a tuple. Change all three `lambda` stubs from:

```python
    monkeypatch.setattr(cli, "build_profile", lambda resume_path, github_username: facts)
```

to:

```python
    monkeypatch.setattr(cli, "build_profile", lambda resume_path, github_username: (facts, "raw text"))
```

- [ ] **Step 8: Run to verify the CLI tests pass**

Run: `uv run pytest tests/test_cli_profile.py tests/test_profile_build.py -q`
Expected: PASS. (`tests/test_profile_build.py` asserts on `build_profile`'s result — if it indexes the facts directly it must unpack the tuple; update those assertions to `facts, _ = build_profile(...)` as needed.)

- [ ] **Step 9: Commit**

```bash
git add src/resume_agent/profile/validate.py src/resume_agent/profile/build.py src/resume_agent/cli.py tests/test_profile_validate.py tests/test_cli_profile.py tests/test_profile_build.py
git commit -m "feat(profile): deterministic coverage report surfaced by 'profile build'"
```

---

## Task 11: Rework the Typst template (hybrid layout + new sections + ordering)

**Files:**
- Modify: `templates/resume.typ`
- Test: `tests/test_render_template_sections.py`

- [ ] **Step 1: Write the failing golden test** — create `tests/test_render_template_sections.py`:

```python
from pypdf import PdfReader

from resume_agent.models.profile import Contact, Education, Language
from resume_agent.models.resume import (
    ResumeContent,
    TailoredAward,
    TailoredBullet,
    TailoredCertification,
    TailoredExperience,
    TailoredPublication,
)
from resume_agent.render.renderer import render_pdf


def _rich_content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Jiajin Wu", email="x@example.com", location="Ann Arbor, MI"),
        summary="Vehicle systems engineer.",
        experience=[
            TailoredExperience(company="Aptiv", title="Triage Engineer", start="2023", end="Present",
                               location="Troy, MI", provenance="e1",
                               bullets=[TailoredBullet(text="Triaged L1-L3 ADAS issues", provenance="b1")])
        ],
        education=[Education(institution="U-Mich", degree="M.Eng", field="Systems", end="2022", gpa="3.9",
                             honors=["Dean's List"])],
        publications=[TailoredPublication(title="On ADAS Triage", venue="SAE", date="2022", provenance="pub1")],
        certifications=[TailoredCertification(name="Six Sigma", issuer="ASQ", provenance="cer1")],
        awards=[TailoredAward(name="Best Intern", provenance="awa1")],
        languages=[Language(language="English", proficiency="native")],
        section_order=["summary", "experience", "education", "publications", "certifications", "awards", "languages"],
    )


def _text_of(pdf_path) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(pdf_path)).pages)


def test_template_renders_all_new_sections(tmp_path):
    out = tmp_path / "rich.pdf"
    render_pdf(_rich_content(), out, template_path="templates/resume.typ")
    assert out.read_bytes().startswith(b"%PDF")
    text = _text_of(out)
    for needle in ["PUBLICATIONS", "CERTIFICATIONS", "AWARDS", "LANGUAGES", "EDUCATION", "3.9", "Six Sigma"]:
        assert needle in text, f"missing {needle!r} in rendered PDF"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_render_template_sections.py -q`
Expected: FAIL — current template renders none of publications/certifications/awards/languages and drops GPA.

- [ ] **Step 3: Implement** — replace `templates/resume.typ` entirely:

```typst
// Single-column, ATS-parseable resume. Data arrives as a JSON string in
// `sys.inputs.data` (see render/renderer.py) and is decoded here.
#let data = json(bytes(sys.inputs.data))
#let contact = data.contact

#set document(title: contact.name)
#set page(margin: (x: 1.6cm, y: 1.4cm))
#set text(size: 10pt)
#set par(justify: false)

#let section-title(t) = [
  #v(6pt)
  #text(size: 12pt, weight: "bold", upper(t))
  #v(-4pt)
  #line(length: 100%, stroke: 0.5pt)
  #v(3pt)
]

#let present(key, obj: data) = key in obj and obj.at(key) != none and obj.at(key) != "" and obj.at(key) != ()

// ---- Header ----
#align(center)[
  #text(size: 18pt, weight: "bold")[#contact.name]
  #if present("headline", obj: contact) [ \ #text(size: 11pt)[#contact.headline] ]
  #let parts = (
    contact.at("location", default: none),
    contact.at("email", default: none),
    contact.at("phone", default: none),
  ).filter(x => x != none)
  #if parts.len() > 0 [ \ #parts.join("  •  ") ]
  #let links = contact.at("links", default: ())
  #if links.len() > 0 [ \ #links.map(l => link(l.url)[#l.label]).join("  •  ") ]
]

// ---- Section blocks (built once, placed by order) ----
#let summary-block = {
  if present("summary") { section-title("Summary"); data.summary }
}

#let experience-block = {
  let xs = data.at("experience", default: ())
  if xs.len() > 0 {
    section-title("Experience")
    for e in xs {
      grid(columns: (1fr, auto),
        [*#e.title*, #e.company],
        [#e.at("start", default: "") #h(2pt)–#h(2pt) #e.at("end", default: "Present")])
      if e.at("location", default: none) != none [ #emph(e.location) \ ]
      for b in e.at("bullets", default: ()) [ - #b.text ]
      v(2pt)
    }
  }
}

#let education-block = {
  let xs = data.at("education", default: ())
  if xs.len() > 0 {
    section-title("Education")
    for ed in xs {
      grid(columns: (1fr, auto),
        [*#ed.institution*#if ed.at("degree", default: none) != none [ — #ed.degree#if ed.at("field", default: none) != none [, #ed.field]]],
        [#ed.at("end", default: "")])
      let tail = (
        if ed.at("gpa", default: none) != none { "GPA: " + ed.gpa } else { none },
        if ed.at("honors", default: ()).len() > 0 { ed.honors.join(", ") } else { none },
      ).filter(x => x != none)
      if tail.len() > 0 [ #emph(tail.join("  •  ")) \ ]
      let cw = ed.at("relevant_coursework", default: ())
      if cw.len() > 0 [ #emph("Coursework: " + cw.join(", ")) \ ]
      v(2pt)
    }
  }
}

#let projects-block = {
  let xs = data.at("projects", default: ())
  if xs.len() > 0 {
    section-title("Projects")
    for p in xs {
      [*#p.name*#if p.at("description", default: none) != none [ — #p.description]]
      let tech = p.at("tech", default: ())
      if tech.len() > 0 [ \ #emph("Tech: " + tech.join(", ")) ]
      for b in p.at("bullets", default: ()) [ - #b.text ]
      v(2pt)
    }
  }
}

#let skills-block = {
  let sk = data.at("skills", default: (:))
  if sk.len() > 0 {
    section-title("Skills")
    for (category, items) in sk [
      *#category:* #items.map(s => s.name).join(", ") \
    ]
  }
}

#let publications-block = {
  let xs = data.at("publications", default: ())
  if xs.len() > 0 {
    section-title("Publications")
    for p in xs {
      let meta = (p.at("venue", default: none), p.at("date", default: none)).filter(x => x != none)
      [- #p.title#if meta.len() > 0 [ — #emph(meta.join(", "))]]
    }
  }
}

#let certifications-block = {
  let xs = data.at("certifications", default: ())
  if xs.len() > 0 {
    section-title("Certifications")
    for c in xs {
      let meta = (c.at("issuer", default: none), c.at("date", default: none)).filter(x => x != none)
      [- *#c.name*#if meta.len() > 0 [ — #meta.join(", ")]]
    }
  }
}

#let awards-block = {
  let xs = data.at("awards", default: ())
  if xs.len() > 0 {
    section-title("Awards")
    for a in xs {
      let meta = (a.at("issuer", default: none), a.at("date", default: none)).filter(x => x != none)
      [- *#a.name*#if meta.len() > 0 [ — #meta.join(", ")]#if a.at("description", default: none) != none [. #a.description]]
    }
  }
}

#let languages-block = {
  let xs = data.at("languages", default: ())
  if xs.len() > 0 {
    section-title("Languages")
    [#xs.map(l => l.language + if l.at("proficiency", default: none) != none { " (" + l.proficiency + ")" } else { "" }).join("  •  ")]
  }
}

#let volunteer-block = {
  let xs = data.at("volunteer", default: ())
  if xs.len() > 0 {
    section-title("Volunteer")
    for v in xs {
      [*#v.organization*#if v.at("role", default: none) != none [ — #v.role]]
      for b in v.at("bullets", default: ()) [ - #b.text ]
      v(2pt)
    }
  }
}

#let blocks = (
  "summary": summary-block,
  "experience": experience-block,
  "education": education-block,
  "projects": projects-block,
  "skills": skills-block,
  "publications": publications-block,
  "certifications": certifications-block,
  "awards": awards-block,
  "languages": languages-block,
  "volunteer": volunteer-block,
)

#let default-order = (
  "summary", "experience", "education", "projects", "skills",
  "publications", "certifications", "awards", "languages", "volunteer",
)

#let order = data.at("section_order", default: none)
#let chosen = if order == none { default-order } else { order }

#for s in chosen {
  if s in blocks { blocks.at(s) }
}
```

Note: Typst is whitespace- and mode-sensitive. The golden test (Step 4) compiles this template, so any syntax error surfaces immediately — if `typst compile` reports one, fix it in place and re-run; a passing `test_template_renders_all_new_sections` is the success criterion.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_render_template_sections.py tests/test_renderer.py -q`
Expected: PASS — both the new rich-sections test and the existing renderer test compile to valid PDFs.

- [ ] **Step 5: Commit**

```bash
git add templates/resume.typ tests/test_render_template_sections.py
git commit -m "feat(render): hybrid template — new sections, enriched education, section_order"
```

---

## Task 12: Batch DB commits in the discovery funnel

**Files:**
- Modify: `src/resume_agent/discovery/pipeline.py`
- Test: `tests/test_discovery_pipeline.py`

- [ ] **Step 1: Write the failing test** — append to `tests/test_discovery_pipeline.py`:

```python
def test_discover_commits_once_per_stage(monkeypatch):
    cfg = SearchConfig(sponsorship_required=True)
    facts = ProfileFacts(contact=Contact(name="Ada"))
    with _session() as s:
        add_job(s, source="manual", jd_text="good role, will sponsor")
        add_job(s, source="manual", jd_text="another good role")

        commits = {"n": 0}
        real_commit = s.commit

        def _counting_commit():
            commits["n"] += 1
            return real_commit()

        monkeypatch.setattr(s, "commit", _counting_commit)
        discover(s, cfg, facts, _ExtractAgent(), _FitAgent())

    # 3 stage-level commits (extract, filter, score) — not one per job per stage
    assert commits["n"] == 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_discovery_pipeline.py::test_discover_commits_once_per_stage -q`
Expected: FAIL — current code commits once per job per stage (more than 3).

- [ ] **Step 3: Implement** — in `src/resume_agent/discovery/pipeline.py`, stop calling `save_job` (which commits per row) inside the loops; `add` in the loop and `commit` once per stage. Replace the three stage functions:

```python
def run_extract(session: Session, agent: Runner) -> None:
    for job in jobs_by_status(session, JobStatus.raw.value):
        criteria = extract_job_criteria(job.jd_text, agent)
        job.criteria_json = criteria.model_dump(mode="json")
        job.status = JobStatus.extracted.value
        session.add(job)
    session.commit()


def run_filter(session: Session, config: SearchConfig) -> None:
    for job in jobs_by_status(session, JobStatus.extracted.value):
        criteria = JobCriteria.model_validate(job.criteria_json or {})
        decision = apply_filters(criteria, config)
        if decision.keep:
            job.status = JobStatus.filtered.value
        else:
            job.status = JobStatus.rejected.value
            job.reject_reason = decision.reject_reason
        session.add(job)
    session.commit()


def run_score(session: Session, profile_facts: ProfileFacts, agent: Runner) -> None:
    for job in jobs_by_status(session, JobStatus.filtered.value):
        fit = score_fit(compose_fit_input(job.jd_text, profile_facts), agent)
        job.fit_score = fit.score
        job.fit_rationale = fit.rationale
        job.status = JobStatus.shortlisted.value
        session.add(job)
    session.commit()
```

Remove the now-unused `save_job` import if nothing else in the file uses it (keep `status_counts`, `jobs_by_status`).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_discovery_pipeline.py -q`
Expected: PASS — both the existing funnel test and the commit-count test.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/pipeline.py tests/test_discovery_pipeline.py
git commit -m "perf(discovery): commit once per funnel stage instead of per row"
```

---

## Task 13: Document the new config + v1.6 deferral

**Files:**
- Modify: `config/review.yaml.example`
- Modify: `README.md` (the `review.yaml` row + a brief note)

- [ ] **Step 1: Document `length_budget`** — append to `config/review.yaml.example` (match the file's existing comment style):

```yaml
# Optional one-page budget handed to the tailor and surfaced to the concision
# reviewer. Omit the block to accept these defaults.
length_budget:
  max_experiences: 4
  max_bullets_per_role: 5
  target_total_bullets: 20
```

- [ ] **Step 2: Note it in the README** — in the `config/*.yaml` table row for `review.yaml`, extend the "Controls" cell to mention the optional `length_budget` (one-page guidance). No behavior change; documentation only.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS — the entire suite is green.

- [ ] **Step 4: Commit**

```bash
git add config/review.yaml.example README.md
git commit -m "docs: document length_budget and the v1.5 quality pass"
```

---

## Final verification

- [ ] **Full suite green:** `uv run pytest -q`
- [ ] **Manual smoke (optional, needs an API key):** rebuild the profile from `resume-latex/`, tailor against a sample JD, `render` the passing version, and eyeball the PDF against `resume-latex/resume.pdf` — confirm Publications, GPA-bearing Education, and the education-under-experience order all appear.
- [ ] **Branch:** all commits are on `v1.5`.

---

## Self-review (completed against the spec)

**Spec coverage:**
- Restored sections (pubs/certs/awards/languages/volunteer, enriched education) → Tasks 1, 11. ✅
- `section_order` hint + default order → Tasks 1, 11. ✅
- Deterministic provenance pre-gate → Tasks 2, 6. ✅
- Per-agent payload trimming (lean vs evidence) → Tasks 3, 5. ✅
- Length budget guiding the tailor + counts to concision → Tasks 4, 5 (stats in lean input), 7. ✅
- Profile: mid-tier extractor, coverage validation, merge dedupe → Tasks 8, 10, 9. ✅
- Batch DB commits → Task 12. ✅
- Concurrency deferred → not implemented, documented in spec §4.5 and Task 13. ✅

**Placeholder scan:** No placeholders, no deliberate typos, no "TBD". Every code step is complete and copy-runnable. The only judgment call left to the implementer is fixing any Typst syntax error the golden test surfaces (Task 11), which is inherent to not being able to compile Typst at plan time.

**Task independence:** Each task is internally green. The one cross-task seam (length budget) is threaded explicitly: Task 6 calls the 3-arg `compose_*`; Task 7 adds the optional `length_budget` param *and* updates the workflow's two call sites in the same task. No task depends on a later task to compile.

**Type consistency:** `ProvenanceReport(ok, missing)`, `CoverageReport(ok, warnings)`, `LengthBudget(max_experiences, max_bullets_per_role, target_total_bullets)`, `run_panel(content, profile_facts, jd_text, config, reviewer_agents)`, and `aggregate(critiques, config, provenance_passed=True)` are used identically wherever they appear. `build_profile` returns `(ProfileFacts, str)` consistently in Tasks 10's callers.
