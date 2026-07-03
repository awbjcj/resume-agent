# Resume Agent — Tailor + Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Tailor + Review component: take an approved job + your `facts.json`, have an Agno **tailor** agent draft a fact-locked `ResumeContent`, run it through a multi-agent **review panel** (fact-check **gate** + ATS/recruiter/hiring-manager/concision), and **revise** in a loop until the fact-check passes and the weighted score clears the threshold (or `max_rounds`). Persist every round to `resume_versions` and expose `resume-agent approve` + `resume-agent tailor`.

**Architecture:** Every LLM role is an Agno `Agent` with an `output_schema` (`ResumeContent` for tailor/reviser, `ReviewCritique` for each reviewer). The loop + aggregation are **plain Python** (deterministic, unit-testable with fake agents): a hard gate on the fact-check reviewer plus a weighted average of the rest. Roster/weights/thresholds come from `config/review.yaml`.

**Tech Stack:** Python 3.13, uv, Agno (`Agent` + `Claude`), Pydantic v2, SQLModel, Typer, pytest. (No new dependencies.)

**Depends on:** Foundation (`models.resume`, `models.review`, `models.job`, `models.profile`, `tracking.tables`, `config`, `db`), Profile (`profile.store.load_facts`, `config.cheap_model`, Agno patterns), Discovery (`tracking.repository`, the `_engine` CLI helper, `jobs_by_status`). All merged to `main`, suite green (78 tests).

> **Commit convention:** every commit ends with a second `-m`:
> `-m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"`

---

## Reference & scoped decisions

Design spec §5.3. Decisions for this plan:

- **Python-orchestrated loop** driving Agno agents (rationale above) — not the Agno `Loop` primitive.
- **Model tiers** (spec Decision #8, "mix by stage"): tailor + reviser + fact-check → premium; ATS/recruiter/concision → mid. Tiers map to model ids via new `Settings.mid_model`/`premium_model` (cheap_model already exists).
- **Aggregation:** fact-check is a binary **gate** (any `passed=False` from a `gate: true` reviewer fails the round, regardless of score). Non-gate reviewers contribute a **weighted average**. Round passes when `gate_passed AND aggregate_score >= score_threshold`.
- **Approval gate:** until the Streamlit dashboard exists, a CLI `approve <job_id>` moves `shortlisted → approved`; `tailor --approved` processes approved jobs. (Dashboard approval comes in the Tracking plan.)

## File Structure (created/modified)

```
src/resume_agent/
  config.py                 # MODIFY: add mid_model, premium_model
  cli.py                    # MODIFY: add `approve` and `tailor` commands
  tracking/
    repository.py           # MODIFY: get_job, save_resume_version, resume_versions_for_job
  tailor/
    __init__.py             # CREATE
    review_config.py        # CREATE: ReviewerSpec + ReviewConfig + load_review_config()
    agents.py               # CREATE: model_for_tier + tailor/reviser/reviewer agent factories
    tailoring.py            # CREATE: compose+wrappers for tailor() and revise()
    panel.py                # CREATE: compose_review_input + review_one + run_panel
    verdict.py              # CREATE: PanelVerdict + aggregate()
    workflow.py             # CREATE: TailorRound + run_tailor_review() loop
    service.py              # CREATE: tailor_job() persistence integration
tests/
  test_config.py            # MODIFY: add mid/premium model assertions
  test_tailor_review_config.py
  test_tailor_agents.py
  test_tailor_tailoring.py
  test_tailor_panel.py
  test_tailor_verdict.py
  test_tailor_workflow.py
  test_tailor_service.py
  test_cli_tailor.py
```

---

## Task 1: Model-tier settings + ReviewConfig

**Files:**

- Modify: `src/resume_agent/config.py`, `tests/test_config.py`
- Create: `src/resume_agent/tailor/__init__.py`, `src/resume_agent/tailor/review_config.py`
- Test: `tests/test_tailor_review_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_settings_has_model_tier_defaults():
    settings = Settings(_env_file=None)
    assert settings.mid_model == "claude-sonnet-4-6"
    assert settings.premium_model == "claude-opus-4-8"
```

Create `tests/test_tailor_review_config.py`:

```python
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec, load_review_config


def test_defaults():
    cfg = ReviewConfig()
    assert cfg.max_rounds == 3
    assert cfg.score_threshold == 85
    assert cfg.reviewers == []


def test_load_from_yaml(tmp_path):
    f = tmp_path / "review.yaml"
    f.write_text(
        "max_rounds: 2\nscore_threshold: 80\nreviewers:\n"
        "  - name: fact-check\n    gate: true\n    weight: 0\n    model_tier: premium\n"
        "  - name: ats-keyword\n    weight: 1\n    model_tier: mid\n",
        encoding="utf-8",
    )
    cfg = load_review_config(f)
    assert cfg.max_rounds == 2
    assert len(cfg.reviewers) == 2
    assert cfg.reviewers[0] == ReviewerSpec(name="fact-check", gate=True, weight=0, model_tier="premium")
    assert cfg.reviewers[1].gate is False  # default
```

- [ ] **Step 2: Run to verify they fail**

Run:

```bash
uv run pytest tests/test_config.py::test_settings_has_model_tier_defaults tests/test_tailor_review_config.py -v
```

Expected: FAIL (`AttributeError: ... 'mid_model'` and `ModuleNotFoundError: ... 'resume_agent.tailor'`).

- [ ] **Step 3: Implement**

In `src/resume_agent/config.py`, add these two lines to `Settings` immediately after `cheap_model`:

```python
    mid_model: str = "claude-sonnet-4-6"
    premium_model: str = "claude-opus-4-8"
```

Create `src/resume_agent/tailor/__init__.py`:

```python
"""Tailor + Review component: draft, review, and revise a fact-locked resume."""
```

Create `src/resume_agent/tailor/review_config.py`:

```python
from pathlib import Path

from pydantic import Field

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class ReviewerSpec(ExtensibleModel):
    name: str
    gate: bool = False
    weight: int = 1
    model_tier: str = "mid"  # cheap | mid | premium


class ReviewConfig(ExtensibleModel):
    max_rounds: int = 3
    score_threshold: int = 85
    reviewers: list[ReviewerSpec] = Field(default_factory=list)


def load_review_config(path: str | Path) -> ReviewConfig:
    return ReviewConfig.model_validate(load_yaml(path))
```

- [ ] **Step 4: Run to verify they pass**

Run:

```bash
uv run pytest tests/test_config.py tests/test_tailor_review_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/config.py src/resume_agent/tailor/__init__.py src/resume_agent/tailor/review_config.py tests/test_config.py tests/test_tailor_review_config.py
git commit -m "feat(tailor): model-tier settings + ReviewConfig" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Agent factories

**Files:**

- Create: `src/resume_agent/tailor/agents.py`
- Test: `tests/test_tailor_agents.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tailor_agents.py`:

```python
from agno.agent import Agent

from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.agents import (
    build_reviewer_agent,
    build_reviser_agent,
    build_tailor_agent,
    model_for_tier,
)


def test_model_for_tier_maps_known_tiers():
    assert model_for_tier("cheap")
    assert model_for_tier("mid")
    assert model_for_tier("premium")
    # unknown tier falls back to the mid model
    assert model_for_tier("bogus") == model_for_tier("mid")


def test_build_tailor_and_reviser_agents(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(build_tailor_agent(model_id="claude-haiku-4-5-20251001"), Agent)
    assert isinstance(build_reviser_agent(model_id="claude-haiku-4-5-20251001"), Agent)


def test_build_reviewer_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = build_reviewer_agent("fact-check", model_id="claude-haiku-4-5-20251001")
    assert isinstance(agent, Agent)
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_tailor_agents.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tailor.agents'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/tailor/agents.py`:

```python
from agno.agent import Agent
from agno.models.anthropic import Claude

from resume_agent.config import get_settings
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique


def model_for_tier(tier: str) -> str:
    s = get_settings()
    return {"cheap": s.cheap_model, "mid": s.mid_model, "premium": s.premium_model}.get(tier, s.mid_model)


_TAILOR_INSTRUCTIONS = [
    "Rewrite the candidate's resume to target the given job.",
    "Use ONLY facts present in the candidate profile. Never invent anything.",
    "Every bullet, experience, project, and selected skill MUST set 'provenance' to the id of the source fact it came from.",
    "Surface real matches to the job's keywords; do not keyword-stuff or exaggerate.",
]

_REVISER_INSTRUCTIONS = [
    "Revise the resume content to address the reviewer issues and suggestions.",
    "Keep every claim fact-locked: use only the candidate profile facts and preserve correct 'provenance' ids.",
    "Do not introduce any claim that lacks a provenance id pointing at a real profile fact.",
]

REVIEWER_INSTRUCTIONS: dict[str, list[str]] = {
    "fact-check": [
        "You are a fact-checker. Verify every claim in the resume traces to a fact in the candidate profile.",
        "A bullet/skill is supported only if its 'provenance' id exists in the profile and the text stays faithful to that fact.",
        "Set passed=False with a 'blocking' issue for ANY unsupported or exaggerated claim; otherwise passed=True.",
    ],
    "ats-keyword": [
        "You assess ATS keyword coverage: are the job's must-have skills/keywords present and in context?",
        "Score 0-100; list missing keywords as issues with suggestions (only if truthfully supported). Set passed accordingly.",
    ],
    "recruiter": [
        "You are a recruiter doing a 6-second scan. Judge clarity, impact, and formatting.",
        "Score 0-100, give concise actionable issues, and set passed.",
    ],
    "hiring-manager": [
        "You are the hiring manager. Judge technical credibility and the relevance of experience/projects to the role.",
        "Score 0-100, give specific issues, and set passed.",
    ],
    "concision": [
        "You assess concision and style: one page, active voice, quantified impact, no fluff.",
        "Score 0-100, give trimming/rewrite suggestions, and set passed.",
    ],
}

_DEFAULT_REVIEWER_INSTRUCTIONS = [
    "Review the resume and return a structured critique with a 0-100 score, a pass/fail, and issues.",
]


def build_tailor_agent(model_id: str | None = None) -> Agent:
    return Agent(
        model=Claude(id=model_id or model_for_tier("premium")),
        description="You are an expert resume writer who never fabricates.",
        instructions=_TAILOR_INSTRUCTIONS,
        output_schema=ResumeContent,
    )


def build_reviser_agent(model_id: str | None = None) -> Agent:
    return Agent(
        model=Claude(id=model_id or model_for_tier("premium")),
        description="You revise resume content while keeping it strictly fact-locked.",
        instructions=_REVISER_INSTRUCTIONS,
        output_schema=ResumeContent,
    )


def build_reviewer_agent(name: str, model_id: str | None = None) -> Agent:
    return Agent(
        model=Claude(id=model_id or model_for_tier("mid")),
        description=f"You are the '{name}' resume reviewer.",
        instructions=REVIEWER_INSTRUCTIONS.get(name, _DEFAULT_REVIEWER_INSTRUCTIONS),
        output_schema=ReviewCritique,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_tailor_agents.py -v
```

Expected: PASS (3 tests). The agent-construction tests must not make network calls; if they error on credentials, STOP and report BLOCKED.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/agents.py tests/test_tailor_agents.py
git commit -m "feat(tailor): tailor/reviser/reviewer Agno agent factories" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Tailor + revise wrappers

**Files:**

- Create: `src/resume_agent/tailor/tailoring.py`
- Test: `tests/test_tailor_tailoring.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tailor_tailoring.py`:

```python
import pytest

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue
from resume_agent.tailor.tailoring import (
    compose_revise_input,
    compose_tailor_input,
    revise,
    tailor,
)


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


def _facts():
    return ProfileFacts(contact=Contact(name="Ada Lovelace"))


def test_compose_tailor_input_includes_profile_criteria_jd():
    text = compose_tailor_input("Backend role", JobCriteria(), _facts())
    assert "Ada Lovelace" in text
    assert "Backend role" in text


def test_tailor_returns_resume_content():
    rc = ResumeContent(contact=Contact(name="Ada"))
    agent = _Agent(rc)
    assert tailor("input", agent) is rc
    assert agent.received == "input"


def test_tailor_rejects_wrong_type():
    with pytest.raises(TypeError):
        tailor("x", _Agent("nope"))


def test_compose_revise_input_includes_issue_messages():
    rc = ResumeContent(contact=Contact(name="Ada"))
    critiques = [
        ReviewCritique(
            reviewer="ats-keyword",
            score=70,
            passed=False,
            issues=[ReviewIssue(severity="major", message="Missing keyword: Kubernetes", suggestion="Add it if true")],
            suggestions=["Tighten the summary around backend systems"],
        )
    ]
    text = compose_revise_input(rc, critiques, _facts())
    assert "Missing keyword: Kubernetes" in text
    assert "Add it if true" in text
    assert "Tighten the summary around backend systems" in text


def test_revise_returns_resume_content():
    rc = ResumeContent(contact=Contact(name="Ada"))
    assert revise("input", _Agent(rc)) is rc
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_tailor_tailoring.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tailor.tailoring'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/tailor/tailoring.py`:

```python
from typing import Any, Protocol

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


def compose_tailor_input(jd_text: str, criteria: JobCriteria, profile_facts: ProfileFacts) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "JOB CRITERIA (JSON):\n"
        f"{criteria.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def tailor(input_text: str, agent: Runner) -> ResumeContent:
    result = agent.run(input_text)
    content = result.content
    if not isinstance(content, ResumeContent):
        raise TypeError(f"Expected ResumeContent from tailor agent, got {type(content).__name__}")
    return content


def compose_revise_input(
    content: ResumeContent, critiques: list[ReviewCritique], profile_facts: ProfileFacts
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
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT RESUME (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "REVIEWER ISSUES:\n"
        f"{issues}\n\n"
        "REVIEWER SUGGESTIONS:\n"
        f"{suggestions}"
    )


def revise(input_text: str, agent: Runner) -> ResumeContent:
    result = agent.run(input_text)
    content = result.content
    if not isinstance(content, ResumeContent):
        raise TypeError(f"Expected ResumeContent from reviser agent, got {type(content).__name__}")
    return content
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_tailor_tailoring.py -v
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/tailoring.py tests/test_tailor_tailoring.py
git commit -m "feat(tailor): tailor + revise wrappers and prompt composition" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Review panel

**Files:**

- Create: `src/resume_agent/tailor/panel.py`
- Test: `tests/test_tailor_panel.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tailor_panel.py`:

```python
import pytest

from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.panel import compose_review_input, review_one, run_panel
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _Result(self._content)


def test_compose_review_input_has_profile_resume_jd():
    rc = ResumeContent(contact=Contact(name="Ada Lovelace"))
    facts = ProfileFacts(contact=Contact(name="Ada Lovelace"))
    text = compose_review_input(rc, facts, "Backend role")
    assert "Ada Lovelace" in text
    assert "Backend role" in text


def test_review_one_returns_critique():
    crit = ReviewCritique(reviewer="fact-check", score=100, passed=True)
    assert review_one("input", _Agent(crit)) is crit


def test_review_one_rejects_wrong_type():
    with pytest.raises(TypeError):
        review_one("x", _Agent("nope"))


def test_run_panel_runs_every_configured_reviewer():
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
    critiques = run_panel("input", config, agents)
    assert [c.reviewer for c in critiques] == ["fact-check", "ats-keyword"]
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_tailor_panel.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tailor.panel'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/tailor/panel.py`:

```python
from typing import Any, Protocol

from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


def compose_review_input(content: ResumeContent, profile_facts: ProfileFacts, jd_text: str) -> str:
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "RESUME UNDER REVIEW (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
    )


def review_one(input_text: str, agent: Runner) -> ReviewCritique:
    result = agent.run(input_text)
    critique = result.content
    if not isinstance(critique, ReviewCritique):
        raise TypeError(f"Expected ReviewCritique from reviewer, got {type(critique).__name__}")
    return critique


def run_panel(input_text: str, config: ReviewConfig, reviewer_agents: dict[str, Runner]) -> list[ReviewCritique]:
    """Run every configured reviewer over the same input and collect their critiques."""
    return [review_one(input_text, reviewer_agents[spec.name]) for spec in config.reviewers]
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_tailor_panel.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/panel.py tests/test_tailor_panel.py
git commit -m "feat(tailor): review panel (review_one + run_panel)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Verdict aggregation

**Files:**

- Create: `src/resume_agent/tailor/verdict.py`
- Test: `tests/test_tailor_verdict.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tailor_verdict.py`:

```python
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.verdict import PanelVerdict, aggregate


def _config(threshold=85):
    return ReviewConfig(
        score_threshold=threshold,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
            ReviewerSpec(name="recruiter", weight=1),
        ],
    )


def test_gate_failure_fails_round_even_with_high_scores():
    critiques = [
        ReviewCritique(reviewer="fact-check", score=0, passed=False),
        ReviewCritique(reviewer="ats-keyword", score=100, passed=True),
        ReviewCritique(reviewer="recruiter", score=100, passed=True),
    ]
    verdict = aggregate(critiques, _config())
    assert verdict.gate_passed is False
    assert verdict.passed is False
    assert verdict.aggregate_score == 100  # weighted score still computed


def test_gate_pass_but_below_threshold_fails():
    critiques = [
        ReviewCritique(reviewer="fact-check", score=100, passed=True),
        ReviewCritique(reviewer="ats-keyword", score=80, passed=True),
        ReviewCritique(reviewer="recruiter", score=80, passed=True),
    ]
    verdict = aggregate(critiques, _config(threshold=85))
    assert verdict.gate_passed is True
    assert verdict.aggregate_score == 80
    assert verdict.passed is False


def test_gate_pass_and_meets_threshold_passes():
    critiques = [
        ReviewCritique(reviewer="fact-check", score=100, passed=True),
        ReviewCritique(reviewer="ats-keyword", score=90, passed=True),
        ReviewCritique(reviewer="recruiter", score=80, passed=True),
    ]
    verdict = aggregate(critiques, _config(threshold=85))
    assert verdict.passed is True
    assert verdict.aggregate_score == 85
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_tailor_verdict.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tailor.verdict'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/tailor/verdict.py`:

```python
from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig


class PanelVerdict(ExtensibleModel):
    passed: bool
    gate_passed: bool
    aggregate_score: int
    critiques: list[ReviewCritique] = Field(default_factory=list)


def aggregate(critiques: list[ReviewCritique], config: ReviewConfig) -> PanelVerdict:
    """Combine critiques: gate reviewers are blocking; the rest are a weighted average."""
    by_name = {c.reviewer: c for c in critiques}

    gate_names = [r.name for r in config.reviewers if r.gate and r.name in by_name]
    gate_passed = all(by_name[name].passed for name in gate_names)

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

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_tailor_verdict.py -v
```

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/verdict.py tests/test_tailor_verdict.py
git commit -m "feat(tailor): panel verdict aggregation (gate + weighted score)" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Tailor→review→revise loop

**Files:**

- Create: `src/resume_agent/tailor/workflow.py`
- Test: `tests/test_tailor_workflow.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tailor_workflow.py`:

```python
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.workflow import TailorRound, run_tailor_review


class _Result:
    def __init__(self, content):
        self.content = content


class _ContentAgent:
    """Tailor/reviser: always returns a minimal ResumeContent."""

    def run(self, prompt):
        return _Result(ResumeContent(contact=Contact(name="Ada")))


class _FactCheck:
    """Fails the first round, passes afterward (simulating a fix after revise)."""

    def __init__(self):
        self.calls = 0

    def run(self, prompt):
        self.calls += 1
        passed = self.calls > 1
        issues = [] if passed else [ReviewIssue(severity="blocking", message="unsupported claim")]
        return _Result(ReviewCritique(reviewer="fact-check", score=100 if passed else 0, passed=passed, issues=issues))


class _Good:
    def __init__(self, name):
        self.name = name

    def run(self, prompt):
        return _Result(ReviewCritique(reviewer=self.name, score=95, passed=True))


def test_loop_revises_until_gate_passes():
    config = ReviewConfig(
        max_rounds=3,
        score_threshold=80,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ],
    )
    reviewer_agents = {"fact-check": _FactCheck(), "ats-keyword": _Good("ats-keyword")}

    rounds = run_tailor_review(
        jd_text="Backend role",
        criteria=JobCriteria(),
        profile_facts=ProfileFacts(contact=Contact(name="Ada")),
        config=config,
        tailor_agent=_ContentAgent(),
        reviewer_agents=reviewer_agents,
        reviser_agent=_ContentAgent(),
    )

    assert [r.round_num for r in rounds] == [1, 2]
    assert isinstance(rounds[0], TailorRound)
    assert rounds[0].verdict.passed is False
    assert rounds[-1].verdict.passed is True


def test_loop_stops_at_max_rounds_when_never_passing():
    config = ReviewConfig(
        max_rounds=2,
        score_threshold=80,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    class _AlwaysFail:
        def run(self, prompt):
            return _Result(ReviewCritique(reviewer="fact-check", score=0, passed=False))

    rounds = run_tailor_review(
        jd_text="x",
        criteria=JobCriteria(),
        profile_facts=ProfileFacts(contact=Contact(name="Ada")),
        config=config,
        tailor_agent=_ContentAgent(),
        reviewer_agents={"fact-check": _AlwaysFail()},
        reviser_agent=_ContentAgent(),
    )
    assert len(rounds) == 2
    assert rounds[-1].verdict.passed is False
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_tailor_workflow.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tailor.workflow'`.

- [ ] **Step 3: Implement**

Create `src/resume_agent/tailor/workflow.py`:

```python
from typing import Any, Protocol

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.tailor.panel import compose_review_input, run_panel
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.tailoring import compose_revise_input, compose_tailor_input, revise, tailor
from resume_agent.tailor.verdict import PanelVerdict, aggregate


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


class TailorRound(ExtensibleModel):
    round_num: int
    content: ResumeContent
    verdict: PanelVerdict


def run_tailor_review(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: dict[str, Runner],
    reviser_agent: Runner,
) -> list[TailorRound]:
    """Draft, then review/revise until the round passes or max_rounds is hit.

    Returns one TailorRound per iteration (content + its panel verdict).
    """
    content = tailor(compose_tailor_input(jd_text, criteria, profile_facts), tailor_agent)
    rounds: list[TailorRound] = []
    for round_num in range(1, config.max_rounds + 1):
        critiques = run_panel(
            compose_review_input(content, profile_facts, jd_text), config, reviewer_agents
        )
        verdict = aggregate(critiques, config)
        rounds.append(TailorRound(round_num=round_num, content=content, verdict=verdict))
        if verdict.passed or round_num == config.max_rounds:
            break
        content = revise(
            compose_revise_input(content, verdict.critiques, profile_facts), reviser_agent
        )
    return rounds
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_tailor_workflow.py -v
```

Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/workflow.py tests/test_tailor_workflow.py
git commit -m "feat(tailor): tailor->review->revise loop" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Repository extension + persistence service

**Files:**

- Modify: `src/resume_agent/tracking/repository.py`
- Create: `src/resume_agent/tailor/service.py`
- Test: `tests/test_tailor_service.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tailor_service.py`:

```python
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.service import tailor_job
from resume_agent.tracking.repository import resume_versions_for_job, save_job
from resume_agent.tracking.tables import Job, JobStatus


class _Result:
    def __init__(self, content):
        self.content = content


class _ContentAgent:
    def run(self, prompt):
        return _Result(ResumeContent(contact=Contact(name="Ada")))


class _FactCheck:
    def run(self, prompt):
        return _Result(ReviewCritique(reviewer="fact-check", score=100, passed=True))


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_tailor_job_persists_versions_and_marks_tailored():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    with _session() as s:
        job = save_job(
            s,
            Job(source="manual", jd_text="jd", status=JobStatus.approved.value,
                criteria_json=JobCriteria().model_dump(mode="json")),
        )
        versions = tailor_job(
            s, job, ProfileFacts(contact=Contact(name="Ada")), config,
            tailor_agent=_ContentAgent(), reviewer_agents={"fact-check": _FactCheck()}, reviser_agent=_ContentAgent(),
        )

        assert len(versions) == 1
        assert versions[0].fact_check_passed is True
        assert versions[0].round == 1
        assert versions[0].content_json["contact"]["name"] == "Ada"

        stored = resume_versions_for_job(s, job.id)
        assert len(stored) == 1
        assert job.status == JobStatus.tailored.value
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_tailor_service.py -v
```

Expected: FAIL — `ImportError`/`ModuleNotFoundError` (`resume_versions_for_job`, `resume_agent.tailor.service`).

- [ ] **Step 3: Implement**

Append to `src/resume_agent/tracking/repository.py` (add the `ResumeVersion` import to the existing tables import line, and add the functions):

```python
from resume_agent.tracking.tables import Job, ResumeVersion


def get_job(session: Session, job_id: int) -> Job | None:
    return session.get(Job, job_id)


def save_resume_version(session: Session, version: ResumeVersion) -> ResumeVersion:
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def resume_versions_for_job(session: Session, job_id: int) -> list[ResumeVersion]:
    return list(session.exec(select(ResumeVersion).where(ResumeVersion.job_id == job_id)).all())
```

(The existing file already imports `Job` from `resume_agent.tracking.tables` and `select` from `sqlmodel`; change the `Job` import to `Job, ResumeVersion` rather than adding a duplicate import line.)

Create `src/resume_agent/tailor/service.py`:

```python
from typing import Any, Protocol

from sqlmodel import Session

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.tailor.review_config import ReviewConfig
from resume_agent.tailor.workflow import run_tailor_review
from resume_agent.tracking.repository import save_job, save_resume_version
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


class Runner(Protocol):
    def run(self, prompt: str) -> Any: ...


def tailor_job(
    session: Session,
    job: Job,
    profile_facts: ProfileFacts,
    config: ReviewConfig,
    tailor_agent: Runner,
    reviewer_agents: dict[str, Runner],
    reviser_agent: Runner,
) -> list[ResumeVersion]:
    """Run the loop for one job, persist each round as a ResumeVersion, mark the job tailored."""
    criteria = JobCriteria.model_validate(job.criteria_json or {})
    rounds = run_tailor_review(
        job.jd_text, criteria, profile_facts, config, tailor_agent, reviewer_agents, reviser_agent
    )
    versions: list[ResumeVersion] = []
    for r in rounds:
        version = ResumeVersion(
            job_id=job.id,
            round=r.round_num,
            content_json=r.content.model_dump(mode="json"),
            review_score=r.verdict.aggregate_score,
            fact_check_passed=r.verdict.gate_passed,
            critique_json=[c.model_dump(mode="json") for c in r.verdict.critiques],
        )
        versions.append(save_resume_version(session, version))
    job.status = JobStatus.tailored.value
    save_job(session, job)
    return versions
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_tailor_service.py tests/test_repository.py -v
```

Expected: PASS (existing repository tests still green + the new service test).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/repository.py src/resume_agent/tailor/service.py tests/test_tailor_service.py
git commit -m "feat(tailor): persist resume versions + tailor_job service" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: CLI — `approve` and `tailor`

**Files:**

- Modify: `src/resume_agent/cli.py`
- Test: `tests/test_cli_tailor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_tailor.py`:

```python
from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.repository import get_job
from resume_agent.tracking.tables import Job, JobStatus

runner = CliRunner()


def _seed(db_url, status):
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        job = Job(source="manual", jd_text="jd", status=status, criteria_json={})
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id


def test_approve_sets_status_approved(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.shortlisted.value)

    result = runner.invoke(cli.app, ["approve", str(job_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output

    engine = make_engine(db_url)
    with get_session(engine) as s:
        assert get_job(s, job_id).status == JobStatus.approved.value


def test_tailor_processes_a_job(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.approved.value)

    monkeypatch.setattr(cli, "load_review_config", lambda path: object())
    monkeypatch.setattr(cli, "load_facts", lambda path: object())
    monkeypatch.setattr(cli, "build_tailor_agent", lambda: object())
    monkeypatch.setattr(cli, "build_reviser_agent", lambda: object())
    monkeypatch.setattr(cli, "build_reviewer_agents", lambda config: {})

    class _Version:
        fact_check_passed = True

    monkeypatch.setattr(
        cli,
        "tailor_job",
        lambda session, job, facts, config, tailor_agent, reviewer_agents, reviser_agent: [_Version()],
    )

    result = runner.invoke(cli.app, ["tailor", "--job-id", str(job_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "1 version" in result.output


def test_tailor_reports_missing_job(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    engine = make_engine(db_url)
    init_db(engine)

    result = runner.invoke(cli.app, ["tailor", "--job-id", "999", "--db-url", db_url])

    assert result.exit_code == 1
    assert "Job #999 not found" in result.output
```

- [ ] **Step 2: Run to verify it fails**

Run:

```bash
uv run pytest tests/test_cli_tailor.py -v
```

Expected: FAIL — the `approve`/`tailor` commands don't exist yet.

- [ ] **Step 3: Implement**

Add these imports near the other imports in `src/resume_agent/cli.py`:

```python
from resume_agent.discovery.search_config import load_search_config  # (already imported in Discovery task; do not duplicate)
from resume_agent.tracking.repository import get_job, jobs_by_status, save_job
from resume_agent.tracking.tables import JobStatus
from resume_agent.tailor.agents import build_reviewer_agent, build_reviser_agent, build_tailor_agent, model_for_tier
from resume_agent.tailor.review_config import load_review_config
from resume_agent.tailor.service import tailor_job
```

(If `load_search_config` / `jobs_by_status` are already imported from the Discovery task, do not add duplicate import lines.)

Add this helper + the two commands AFTER the `discover` command but BEFORE the trailing `if __name__ == "__main__":` block:

```python
DEFAULT_REVIEW = "config/review.yaml"


def build_reviewer_agents(config) -> dict:
    """Build one Agno reviewer agent per configured reviewer, at its model tier."""
    return {
        spec.name: build_reviewer_agent(spec.name, model_for_tier(spec.model_tier))
        for spec in config.reviewers
    }


@app.command("approve")
def approve(
    job_id: int = typer.Argument(..., help="Job id to approve for tailoring."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Mark a shortlisted job as approved (the human checkpoint before tailoring)."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        job = get_job(session, job_id)
        if job is None:
            typer.echo(f"Job #{job_id} not found.")
            raise typer.Exit(code=1)
        job.status = JobStatus.approved.value
        save_job(session, job)
    typer.echo(f"Approved job #{job_id}.")


@app.command("tailor")
def tailor_cmd(
    job_id: int = typer.Option(None, help="Tailor a single job by id."),
    approved: bool = typer.Option(False, "--approved", help="Tailor all approved jobs."),
    review: str = typer.Option(DEFAULT_REVIEW, help="Path to review.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the tailor + review loop over approved job(s)."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        if job_id is not None:
            job = get_job(session, job_id)
            if job is None:
                typer.echo(f"Job #{job_id} not found.")
                raise typer.Exit(code=1)
            targets = [job]
        elif approved:
            targets = jobs_by_status(session, JobStatus.approved.value)
        else:
            typer.echo("Specify --job-id <id> or --approved.")
            raise typer.Exit(code=1)

        config = load_review_config(review)
        profile_facts = load_facts(facts)
        tailor_agent = build_tailor_agent()
        reviser_agent = build_reviser_agent()
        reviewer_agents = build_reviewer_agents(config)

        for job in targets:
            versions = tailor_job(
                session, job, profile_facts, config, tailor_agent, reviewer_agents, reviser_agent
            )
            typer.echo(
                f"Job #{job.id}: {len(versions)} version(s); final fact_check_passed={versions[-1].fact_check_passed}"
            )
```

- [ ] **Step 4: Run to verify it passes**

Run:

```bash
uv run pytest tests/test_cli_tailor.py -v
```

Expected: PASS (3 tests). (The `tailor` test patches `cli.build_reviewer_agents`, `cli.tailor_job`, etc., so no real agents run.)

- [ ] **Step 5: Verify wiring**

Run:

```bash
uv run resume-agent approve --help
uv run resume-agent tailor --help
```

Expected: help text for each (exit 0).

- [ ] **Step 6: Run the full suite**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass (Discovery total + Tailor additions).

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_tailor.py
git commit -m "feat(tailor): approve + tailor CLI commands" -m "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (completed during plan authoring)

- **Spec coverage (§5.3):** Tailor agent → fact-locked `ResumeContent` with mandatory provenance (Task 2 instructions + reuse of Foundation models); parallel-role review panel — fact-check/ATS/recruiter/hiring-manager/concision (Tasks 2, 4); fact-check **hard gate** + weighted score aggregation (Task 5); revise loop until pass or `max_rounds` (Task 6); per-round persistence to `resume_versions` + job→`tailored` (Task 7); roster/weights/`max_rounds`/threshold from `config/review.yaml` (Task 1); `tailor` CLI + `approve` checkpoint (Task 8). **Documented decision:** Python-orchestrated loop driving Agno agents instead of the Agno `Loop` primitive (testability + deterministic gating).
- **Placeholder scan:** none — complete code + exact commands in every step.
- **Type consistency:** `tailor`/`revise`/`review_one` validate `ResumeContent`/`ReviewCritique`; `run_panel(input, config, reviewer_agents: dict[str,Runner]) -> list[ReviewCritique]`; `aggregate(critiques, config) -> PanelVerdict(passed, gate_passed, aggregate_score, critiques)`; `run_tailor_review(...) -> list[TailorRound(round_num, content, verdict)]`; `tailor_job(session, job, facts, config, tailor_agent, reviewer_agents, reviser_agent) -> list[ResumeVersion]` — argument order identical at the CLI call site and the test's monkeypatched stub. `ResumeVersion` fields (`round`, `content_json`, `review_score`, `fact_check_passed`, `critique_json`) match the Foundation table. CLI patches target module-level names (`build_reviewer_agents`, `tailor_job`, `load_facts`, `load_review_config`).

---

## Notes to carry into later plans

- **Render plan (next):** read the latest passing `ResumeVersion.content_json` → `ResumeContent` → Typst → PDF; store `pdf_path`; set job→`rendered`.
- **Tracking plan:** Streamlit shortlist page replaces the CLI `approve` gate; surface `fact_check_passed` + per-round critiques; extend repository for `applications`. Also the deferred Foundation items (`updated_at` onupdate; tz-aware datetimes).

## Execution Handoff

After this plan is executed and green, the next plan is **Render** (Typst → PDF), then **Tracking** (Streamlit dashboard), then the deferred **LinkedIn scraper**.
