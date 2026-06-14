# House-Style Layer Implementation Plan (v3 Plan A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user inject their own prose resume-writing guidance into the *system message* of every resume tailor-loop agent (writer, reviser, reviewers), appended beneath the non-removable fact-lock core.

**Architecture:** A new pure module `tailor/style_guide.py` owns two functions — `load_style_guide(path)` (reads an opt-in prose file; missing/empty ⇒ `None`) and `compose_instructions(base, style_guide)` (appends a labeled block beneath fixed instructions, or returns the base unchanged). The three agent builders in `tailor/agents.py` gain an optional `style_guide` param and route their hardcoded instruction lists through `compose_instructions`. `review.yaml` gains a `style_guide_path` key; `cli.py`'s `tailor_cmd` loads the guide once and threads it into all loop agents. Zero DB changes.

**Tech Stack:** Python 3.13, Pydantic, Typer, Agno (`Agent`), pytest. Follows the spec `docs/superpowers/specs/2026-06-13-resume-agent-v3-design.md` §5.1.

---

## File Structure

- **Create** `src/resume_agent/tailor/style_guide.py` — `STYLE_GUIDE_HEADER`, `compose_instructions()`, `load_style_guide()`. One responsibility: assemble/load the house-style layer. Pure (no Agno, no I/O beyond reading one file).
- **Modify** `src/resume_agent/tailor/agents.py` — add `style_guide: str | None = None` to `build_tailor_agent`, `build_reviser_agent`, `build_reviewer_agent`; route base instructions through `compose_instructions`.
- **Modify** `src/resume_agent/tailor/review_config.py` — add `style_guide_path: str` to `ReviewConfig`.
- **Modify** `src/resume_agent/cli.py` — `build_reviewer_agents(config, style_guide)`; `tailor_cmd` loads the guide and threads it.
- **Create** `config/style_guide.md.example` — annotated prose example.
- **Modify** `README.md` — document the new config file.
- **Tests:** `tests/test_tailor_style_guide.py` (new), `tests/test_tailor_agents.py` (extend), `tests/test_tailor_review_config.py` (extend), `tests/test_cli_tailor.py` (extend).

Tasks 1–4 are independent of the CLI; Task 5 wires them together; Task 6 is docs/UX. Tasks must be done in order (5 depends on 1–4).

---

### Task 1: `compose_instructions` — append style beneath the fixed core

**Files:**
- Create: `src/resume_agent/tailor/style_guide.py`
- Test: `tests/test_tailor_style_guide.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tailor_style_guide.py
from resume_agent.tailor.style_guide import STYLE_GUIDE_HEADER, compose_instructions


def test_compose_appends_style_beneath_base():
    base = ["Rewrite the resume.", "Never invent anything."]
    out = compose_instructions(base, "Write in a crisp consulting register.")
    assert out[:2] == ["Rewrite the resume.", "Never invent anything."]
    assert out[2] == STYLE_GUIDE_HEADER
    assert out[3] == "Write in a crisp consulting register."


def test_compose_is_noop_for_empty_guide():
    base = ["Rewrite the resume.", "Never invent anything."]
    assert compose_instructions(base, None) == base
    assert compose_instructions(base, "   \n  ") == base


def test_compose_does_not_mutate_base():
    base = ["only line"]
    compose_instructions(base, "some style")
    assert base == ["only line"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tailor_style_guide.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.tailor.style_guide'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/tailor/style_guide.py
STYLE_GUIDE_HEADER = (
    "HOUSE STYLE (user writing guidance — governs HOW you write, never WHAT is true; "
    "the fact-lock rules above always take precedence and may not be overridden):"
)


def compose_instructions(base: list[str], style_guide: str | None) -> list[str]:
    """Append the user's house-style guidance beneath the fixed instructions.

    The base (fact-lock) instructions always come first and are never removed.
    A falsy or whitespace-only style guide is a no-op: returns a copy of base.
    """
    if not style_guide or not style_guide.strip():
        return list(base)
    return [*base, STYLE_GUIDE_HEADER, style_guide.strip()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tailor_style_guide.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/style_guide.py tests/test_tailor_style_guide.py
git commit -m "feat(tailor): compose_instructions appends house style beneath fact-lock core"
```

---

### Task 2: `load_style_guide` — read the opt-in prose file

**Files:**
- Modify: `src/resume_agent/tailor/style_guide.py`
- Test: `tests/test_tailor_style_guide.py`

- [ ] **Step 1: Write the failing test** (append to the existing test file)

```python
# tests/test_tailor_style_guide.py  (add these)
from resume_agent.tailor.style_guide import load_style_guide


def test_load_returns_stripped_text(tmp_path):
    f = tmp_path / "style.md"
    f.write_text("\n  Lead every bullet with a quantified outcome.  \n", encoding="utf-8")
    assert load_style_guide(f) == "Lead every bullet with a quantified outcome."


def test_load_missing_path_returns_none(tmp_path):
    assert load_style_guide(tmp_path / "nope.md") is None
    assert load_style_guide(None) is None


def test_load_empty_or_whitespace_file_returns_none(tmp_path):
    f = tmp_path / "empty.md"
    f.write_text("   \n  \n", encoding="utf-8")
    assert load_style_guide(f) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tailor_style_guide.py::test_load_returns_stripped_text -v`
Expected: FAIL with `ImportError: cannot import name 'load_style_guide'`

- [ ] **Step 3: Write minimal implementation** (add to `style_guide.py`; add the import at top)

```python
# src/resume_agent/tailor/style_guide.py  — add at the very top
from pathlib import Path
```

```python
# src/resume_agent/tailor/style_guide.py  — add at the bottom
def load_style_guide(path: "str | Path | None") -> str | None:
    """Read the prose house-style file. Missing or empty file => None (opt-in no-op)."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8").strip()
    return text or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tailor_style_guide.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/style_guide.py tests/test_tailor_style_guide.py
git commit -m "feat(tailor): load_style_guide reads opt-in prose file (missing/empty => None)"
```

---

### Task 3: `ReviewConfig.style_guide_path` — where the guide lives

**Files:**
- Modify: `src/resume_agent/tailor/review_config.py:24-28`
- Test: `tests/test_tailor_review_config.py`

- [ ] **Step 1: Write the failing test** (append to the existing test file)

```python
# tests/test_tailor_review_config.py  (add these)
def test_style_guide_path_default():
    assert ReviewConfig().style_guide_path == "config/style_guide.md"


def test_style_guide_path_from_yaml(tmp_path):
    f = tmp_path / "review.yaml"
    f.write_text("style_guide_path: config/custom_style.md\n", encoding="utf-8")
    assert load_review_config(f).style_guide_path == "config/custom_style.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tailor_review_config.py::test_style_guide_path_default -v`
Expected: FAIL with `AttributeError: 'ReviewConfig' object has no attribute 'style_guide_path'`

- [ ] **Step 3: Write minimal implementation** — add one field to `ReviewConfig`

```python
# src/resume_agent/tailor/review_config.py — class ReviewConfig now reads:
class ReviewConfig(ExtensibleModel):
    max_rounds: int = Field(default=3, ge=1)
    score_threshold: int = 85
    reviewers: list[ReviewerSpec] = Field(default_factory=list)
    length_budget: LengthBudget = Field(default_factory=LengthBudget)
    style_guide_path: str = "config/style_guide.md"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tailor_review_config.py -v`
Expected: PASS (all, including the 2 new)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/review_config.py tests/test_tailor_review_config.py
git commit -m "feat(tailor): add style_guide_path to ReviewConfig (default config/style_guide.md)"
```

---

### Task 4: Thread `style_guide` through the three agent builders

**Files:**
- Modify: `src/resume_agent/tailor/agents.py:57-87`
- Test: `tests/test_tailor_agents.py`

- [ ] **Step 1: Write the failing test** (append to the existing test file)

```python
# tests/test_tailor_agents.py  (add these)
from resume_agent.tailor.agents import _TAILOR_INSTRUCTIONS  # noqa: E402


def test_tailor_agent_includes_style_and_keeps_factlock(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = build_tailor_agent(model_id="claude-haiku-4-5-20251001", style_guide="Use British spelling.")
    rendered = str(agent._agent.instructions)
    assert "Use British spelling." in rendered            # style present
    assert _TAILOR_INSTRUCTIONS[1] in rendered            # fact-lock line still present


def test_reviewer_agent_includes_style(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = build_reviewer_agent("recruiter", model_id="claude-haiku-4-5-20251001", style_guide="Prefer STAR phrasing.")
    assert "Prefer STAR phrasing." in str(agent._agent.instructions)


def test_reviser_agent_without_style_is_unchanged(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = build_reviser_agent(model_id="claude-haiku-4-5-20251001")
    assert "HOUSE STYLE" not in str(agent._agent.instructions)
```

Note: `_TAILOR_INSTRUCTIONS[1]` is the line `"Use ONLY facts present in the candidate profile. Never invent anything."`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tailor_agents.py::test_tailor_agent_includes_style_and_keeps_factlock -v`
Expected: FAIL with `TypeError: build_tailor_agent() got an unexpected keyword argument 'style_guide'`

- [ ] **Step 3: Write minimal implementation** — add the import and the `style_guide` param to all three builders

```python
# src/resume_agent/tailor/agents.py — add near the other imports
from resume_agent.tailor.style_guide import compose_instructions
```

```python
# src/resume_agent/tailor/agents.py — replace the three builder functions
def build_tailor_agent(model_id: str | None = None, style_guide: str | None = None) -> Runner:
    return AgentRunner(
        Agent(
            model=Claude(id=model_id or model_for_tier("premium")),
            description="You are an expert resume writer who never fabricates.",
            instructions=compose_instructions(_TAILOR_INSTRUCTIONS, style_guide),
            output_schema=ResumeContent,
        )
    )


def build_reviser_agent(model_id: str | None = None, style_guide: str | None = None) -> Runner:
    return AgentRunner(
        Agent(
            model=Claude(id=model_id or model_for_tier("premium")),
            description="You revise resume content while keeping it strictly fact-locked.",
            instructions=compose_instructions(_REVISER_INSTRUCTIONS, style_guide),
            output_schema=ResumeContent,
        )
    )


def build_reviewer_agent(
    name: str, model_id: str | None = None, style_guide: str | None = None
) -> Runner:
    return AgentRunner(
        Agent(
            model=Claude(id=model_id or model_for_tier("mid")),
            description=f"You are the '{name}' resume reviewer.",
            instructions=compose_instructions(
                REVIEWER_INSTRUCTIONS.get(name, _DEFAULT_REVIEWER_INSTRUCTIONS), style_guide
            ),
            output_schema=ReviewCritique,
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tailor_agents.py -v`
Expected: PASS (all, including the 3 new). If `agent._agent.instructions` is not a plain list in your Agno version, the `str(...)` containment assertions still hold because Agno stores the provided instructions verbatim.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tailor/agents.py tests/test_tailor_agents.py
git commit -m "feat(tailor): thread optional style_guide through writer/reviser/reviewer builders"
```

---

### Task 5: Wire the guide into the tailor command (whole loop)

**Files:**
- Modify: `src/resume_agent/cli.py:20-37` (imports), `src/resume_agent/cli.py:189-194` (`build_reviewer_agents`), `src/resume_agent/cli.py:214-249` (`tailor_cmd`)
- Test: `tests/test_cli_tailor.py`

- [ ] **Step 1: Write the failing test** — replace `test_tailor_processes_a_job` and add a threading test

```python
# tests/test_cli_tailor.py — add this import at the top
from resume_agent.tailor.review_config import ReviewConfig
```

```python
# tests/test_cli_tailor.py — REPLACE test_tailor_processes_a_job with the two tests below
def test_tailor_processes_a_job(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.approved.value)

    monkeypatch.setattr(cli, "load_review_config", lambda path: ReviewConfig())
    monkeypatch.setattr(cli, "load_facts", lambda path: object())
    monkeypatch.setattr(cli, "load_style_guide", lambda path: None)
    monkeypatch.setattr(cli, "build_tailor_agent", lambda style_guide=None: object())
    monkeypatch.setattr(cli, "build_reviser_agent", lambda style_guide=None: object())
    monkeypatch.setattr(cli, "build_reviewer_agents", lambda config, style_guide=None: {})

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


def test_tailor_threads_style_guide_into_all_loop_agents(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    job_id = _seed(db_url, JobStatus.approved.value)

    monkeypatch.setattr(cli, "load_review_config", lambda path: ReviewConfig())
    monkeypatch.setattr(cli, "load_facts", lambda path: object())
    monkeypatch.setattr(cli, "load_style_guide", lambda path: "HOUSE STYLE TEXT")

    seen: dict[str, object] = {}

    def fake_tailor(style_guide=None):
        seen["tailor"] = style_guide
        return object()

    def fake_reviser(style_guide=None):
        seen["reviser"] = style_guide
        return object()

    def fake_reviewers(config, style_guide=None):
        seen["reviewers"] = style_guide
        return {}

    monkeypatch.setattr(cli, "build_tailor_agent", fake_tailor)
    monkeypatch.setattr(cli, "build_reviser_agent", fake_reviser)
    monkeypatch.setattr(cli, "build_reviewer_agents", fake_reviewers)

    class _Version:
        fact_check_passed = True

    monkeypatch.setattr(cli, "tailor_job", lambda *a, **k: [_Version()])

    result = runner.invoke(cli.app, ["tailor", "--job-id", str(job_id), "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert seen == {
        "tailor": "HOUSE STYLE TEXT",
        "reviser": "HOUSE STYLE TEXT",
        "reviewers": "HOUSE STYLE TEXT",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_tailor.py::test_tailor_threads_style_guide_into_all_loop_agents -v`
Expected: FAIL — `AttributeError: <module 'resume_agent.cli'> does not have the attribute 'load_style_guide'`

- [ ] **Step 3: Write minimal implementation**

Add the import (group it with the other tailor imports near `cli.py:29`):

```python
# src/resume_agent/cli.py
from resume_agent.tailor.style_guide import load_style_guide
```

Update the `build_reviewer_agents` helper to forward the style guide:

```python
# src/resume_agent/cli.py — replace build_reviewer_agents
def build_reviewer_agents(config, style_guide: str | None = None) -> dict:
    """Build one Agno reviewer agent per configured reviewer, at its model tier."""
    return {
        spec.name: build_reviewer_agent(
            spec.name, model_for_tier(spec.model_tier), style_guide=style_guide
        )
        for spec in config.reviewers
    }
```

In `tailor_cmd`, load the guide right after the config and thread it into all three builders. Replace the block that currently reads:

```python
        config = load_review_config(review)
        profile_facts = load_facts(facts)
        tailor_agent = build_tailor_agent()
        reviser_agent = build_reviser_agent()
        reviewer_agents = build_reviewer_agents(config)
```

with:

```python
        config = load_review_config(review)
        profile_facts = load_facts(facts)
        style_guide = load_style_guide(config.style_guide_path)
        tailor_agent = build_tailor_agent(style_guide=style_guide)
        reviser_agent = build_reviser_agent(style_guide=style_guide)
        reviewer_agents = build_reviewer_agents(config, style_guide=style_guide)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_tailor.py -v`
Expected: PASS (all 4 tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_tailor.py
git commit -m "feat(cli): load style guide once and thread it into the whole tailor loop"
```

---

### Task 6: Ship the example file + docs

**Files:**
- Create: `config/style_guide.md.example`
- Modify: `README.md` (the `config/*.yaml` table around line 294-303, and the `templates/` note around line 305-308)

- [ ] **Step 1: Create the annotated example**

```markdown
# config/style_guide.md.example
<!--
House style — optional, opt-in resume-writing guidance.

Copy this file to `config/style_guide.md` (drop the .example) to activate it.
Its prose is appended to the SYSTEM MESSAGE of every resume tailor-loop agent
(writer, reviser, and reviewers), BENEATH the fixed fact-lock rules.

It governs HOW your resume is written — tone, emphasis, ordering, structure,
industry conventions. It can NOT introduce facts: every claim still has to
trace to data/profile/facts.json (the fact-check gate is unaffected). If a
guide implies a new fact about you, add it to facts.json, not here.

Delete this comment and write freely below. Missing/empty file = no change.
-->

Write in a crisp, results-first register suitable for senior software roles.

- Lead every experience bullet with a quantified outcome, then the action.
- Prefer strong verbs (built, shipped, scaled) over "responsible for".
- Foreground systems/infra work for backend roles; foreground product impact
  for full-stack roles.
- Keep it to one page; cut hobby projects unless they show a required skill.
- Use American spelling and the Oxford comma.
```

- [ ] **Step 2: Verify it does NOT activate by accident**

Run: `uv run pytest tests/test_tailor_style_guide.py tests/test_cli_tailor.py -v`
Expected: PASS. (The real `config/style_guide.md` does not exist, so `load_style_guide` returns `None` and behavior is unchanged. The `.example` suffix means it is never read.)

- [ ] **Step 3: Document the file in the README config table**

In `README.md`, add a row to the `config/*.yaml` table (it currently ends with the `render.yaml` row):

```markdown
| `style_guide.md` | *Optional.* Prose house-style guidance appended to the system message of the resume tailor loop (writer, reviser, reviewers). Governs *how* resumes are written, never *what* is claimed — fact-lock is unaffected. Absent ⇒ no change. Copy from `style_guide.md.example`. Path overridable via `review.yaml`'s `style_guide_path`. |
```

Also add `cp config/style_guide.md.example config/style_guide.md   # optional: house writing style` to the setup copy-block in README (the block around line 74-80), as an optional line.

- [ ] **Step 4: Commit**

```bash
git add config/style_guide.md.example README.md
git commit -m "docs(tailor): document opt-in config/style_guide.md house-style layer"
```

---

## Full-suite gate

- [ ] **Run the entire suite to prove nothing regressed**

Run: `uv run pytest -q`
Expected: all green. Pay special attention to `test_tailor_agents.py`, `test_tailor_review_config.py`, `test_cli_tailor.py`, and the existing fact-check adversarial test (`tests/test_tailor_provenance.py` / `test_tailor_panel.py`) — the fact-lock core must still block fabrication regardless of the new layer.

---

## Self-Review

**1. Spec coverage** (against spec §2 decisions 2–5, §5.1, §9):
- Decision 2 (additive, fact-lock fixed) → Task 1 (`compose_instructions` appends beneath base; base never removed) + Task 4 test asserts the fact-lock line survives.
- Decision 3 (whole loop) → Task 4 (all three builders) + Task 5 (`build_reviewer_agents` forwards style; `tailor_cmd` threads to writer+reviser+reviewers) + Task 5 test asserts all three receive it.
- Decision 4 (resumes only, cover letters out) → no change to `cover_letter/agents.py`; nothing in this plan touches it. ✓
- Decision 5 (single prose file, `review.yaml` key, verbatim labeled block, opt-in) → Task 2 (loader), Task 3 (`style_guide_path`), Task 1 (`STYLE_GUIDE_HEADER` label), Tasks 2/6 (missing/empty ⇒ no-op).
- §9 testing (reach, ordering, no-op, fact-lock survives) → Tasks 1, 4, 5 tests cover all four; the full-suite gate re-runs the adversarial fact-check test.

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; every run step shows the exact command + expected result. ✓

**3. Type consistency:** `compose_instructions(base: list[str], style_guide: str | None) -> list[str]` and `load_style_guide(path) -> str | None` are used with those exact signatures in Tasks 4 and 5. The `style_guide` keyword is spelled identically across `build_tailor_agent`, `build_reviser_agent`, `build_reviewer_agent`, `build_reviewer_agents`, and the `tailor_cmd` call sites. `STYLE_GUIDE_HEADER` is defined in Task 1 and only referenced in tests. ✓

---

## Execution Handoff

Plan complete. After Plan B, choose an execution approach (subagent-driven recommended).
