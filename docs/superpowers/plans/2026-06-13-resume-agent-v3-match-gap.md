# Match-Gap Report Implementation Plan (v3 Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report which skills your *target* jobs (those that survived discovery) demand that your profile doesn't show — aggregated by frequency, with a per-job view — surfaced in both the CLI and the dashboard, read-only.

**Architecture:** A new pure module `tracking/match_gap.py` (sibling of `analytics.py`) holds `normalize_skill`, `profile_skill_tokens`, the `GapRow`/`MatchGapReport` dataclasses, and `match_gap(session, facts, canonicalizer=None)`. It reads `Job.criteria_json["must_have_skills"]` for jobs in `{shortlisted, approved, tailored, rendered}` and set-subtracts the profile's skill names+aliases. An optional cheap-LLM `canonicalizer` (in `tracking/canonicalize.py`) collapses synonyms like `k8s`≈`kubernetes`; it is off by default and injected as a plain callable so tests stay offline. `cli.py` gains a `match-gap` command; `dashboard/app.py` gains a Match-gap page. Zero DB changes.

**Tech Stack:** Python 3.13, SQLModel/SQLAlchemy, Pydantic, Typer, Streamlit, Agno (optional LLM pass), pytest. Follows the spec `docs/superpowers/specs/2026-06-13-resume-agent-v3-design.md` §5.2.

---

## File Structure

- **Create** `src/resume_agent/tracking/match_gap.py` — normalization, profile token set, gap dataclasses, and the pure `match_gap()`. One responsibility: compute the gap, no presentation, no LLM construction.
- **Create** `src/resume_agent/tracking/canonicalize.py` — the optional cheap-LLM synonym canonicalizer (`SkillClusters`, `clusters_to_mapping`, `build_skill_canonicalizer`). Isolated so `match_gap` never depends on Agno.
- **Modify** `src/resume_agent/cli.py` — add the `match-gap` command.
- **Modify** `src/resume_agent/dashboard/app.py` — `match_gap_table_rows` helper, `render_match_gap_page`, and a sidebar entry.
- **Tests:** `tests/test_tracking_match_gap.py`, `tests/test_tracking_canonicalize.py`, `tests/test_cli_match_gap.py`, `tests/test_dashboard_match_gap.py` (all new).

Order matters: Tasks 1→2→3 build the pure core; Task 4 adds the optional LLM pass; Tasks 5–6 add the two surfaces (independent of each other once 3 is done).

---

### Task 1: `normalize_skill` — deterministic comparison key

**Files:**
- Create: `src/resume_agent/tracking/match_gap.py`
- Test: `tests/test_tracking_match_gap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracking_match_gap.py
from resume_agent.tracking.match_gap import normalize_skill


def test_normalize_lowercases_and_collapses_whitespace():
    assert normalize_skill("  Kubernetes  ") == "kubernetes"
    assert normalize_skill("Amazon  Web   Services") == "amazon web services"


def test_normalize_keeps_plus_hash_dot_drops_other_punct():
    assert normalize_skill("C++") == "c++"
    assert normalize_skill("C#") == "c#"
    assert normalize_skill("Node.js") == "node.js"
    assert normalize_skill("CI/CD") == "ci cd"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tracking_match_gap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.tracking.match_gap'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/tracking/match_gap.py
import re

_PUNCT = re.compile(r"[^a-z0-9+#. ]+")
_WS = re.compile(r"\s+")


def normalize_skill(skill: str) -> str:
    """Lowercase, drop punctuation (keep + # . for c++/c#/node.js), collapse whitespace."""
    s = skill.lower()
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tracking_match_gap.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/match_gap.py tests/test_tracking_match_gap.py
git commit -m "feat(match-gap): normalize_skill comparison key"
```

---

### Task 2: `profile_skill_tokens` — the profile's known-skill set

**Files:**
- Modify: `src/resume_agent/tracking/match_gap.py`
- Test: `tests/test_tracking_match_gap.py`

- [ ] **Step 1: Write the failing test** (append)

```python
# tests/test_tracking_match_gap.py  (add)
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.tracking.match_gap import profile_skill_tokens


def test_profile_skill_tokens_includes_names_and_aliases():
    facts = ProfileFacts(
        contact=Contact(name="A"),
        skills={
            "languages": [Skill(name="Python"), Skill(name="Go")],
            "infra": [Skill(name="Kubernetes", aliases=["k8s", "K8S"])],
        },
    )
    assert profile_skill_tokens(facts) == {"python", "go", "kubernetes", "k8s"}


def test_profile_skill_tokens_empty_profile():
    assert profile_skill_tokens(ProfileFacts(contact=Contact(name="A"))) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tracking_match_gap.py::test_profile_skill_tokens_includes_names_and_aliases -v`
Expected: FAIL with `ImportError: cannot import name 'profile_skill_tokens'`

- [ ] **Step 3: Write minimal implementation** (add to `match_gap.py`; add the import)

```python
# src/resume_agent/tracking/match_gap.py — add to imports
from resume_agent.models.profile import ProfileFacts
```

```python
# src/resume_agent/tracking/match_gap.py — add
def profile_skill_tokens(facts: ProfileFacts) -> set[str]:
    """Every profile skill name + alias, normalized, as a lookup set."""
    tokens: set[str] = set()
    for skill_list in facts.skills.values():
        for skill in skill_list:
            tokens.add(normalize_skill(skill.name))
            for alias in skill.aliases:
                tokens.add(normalize_skill(alias))
    tokens.discard("")
    return tokens
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tracking_match_gap.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/match_gap.py tests/test_tracking_match_gap.py
git commit -m "feat(match-gap): profile_skill_tokens (names + aliases, normalized)"
```

---

### Task 3: `match_gap` — the pure core (aggregate + per-job)

**Files:**
- Modify: `src/resume_agent/tracking/match_gap.py`
- Test: `tests/test_tracking_match_gap.py`

- [ ] **Step 1: Write the failing test** (append)

```python
# tests/test_tracking_match_gap.py  (add)
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.tracking.match_gap import GapRow, MatchGapReport, match_gap
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _job(session, status, must_have):
    return save_job(
        session,
        Job(source="manual", company="C", title="T", status=status,
            criteria_json={"must_have_skills": must_have}),
    )


def _facts(skills):
    return ProfileFacts(contact=Contact(name="A"), skills=skills)


def test_match_gap_aggregates_by_frequency():
    with _session() as session:
        _job(session, "shortlisted", ["Kubernetes", "Python"])
        _job(session, "approved", ["Kubernetes", "Go"])
        report = match_gap(session, _facts({"lang": [Skill(name="Python")]}))
        assert report.target_total == 2
        pairs = [(g.skill, g.demand_count) for g in report.gaps]
        assert pairs[0] == ("Kubernetes", 2)        # most-demanded gap first
        assert ("Go", 1) in pairs
        assert all(g.skill != "Python" for g in report.gaps)  # Python is covered


def test_match_gap_excludes_pre_shortlist_jobs():
    with _session() as session:
        _job(session, "filtered", ["Rust"])
        _job(session, "rejected", ["Scala"])
        _job(session, "shortlisted", ["Kubernetes"])
        report = match_gap(session, _facts({}))
        assert report.target_total == 1
        assert {g.skill for g in report.gaps} == {"Kubernetes"}


def test_match_gap_alias_is_not_a_gap():
    with _session() as session:
        job = _job(session, "shortlisted", ["k8s"])
        report = match_gap(session, _facts({"infra": [Skill(name="Kubernetes", aliases=["k8s"])]}))
        assert report.gaps == []
        assert report.per_job[job.id] == []


def test_match_gap_per_job_lists_missing():
    with _session() as session:
        job = _job(session, "shortlisted", ["Kubernetes", "Python"])
        report = match_gap(session, _facts({"lang": [Skill(name="Python")]}))
        assert report.per_job[job.id] == ["Kubernetes"]


def test_match_gap_honors_canonicalizer():
    with _session() as session:
        _job(session, "shortlisted", ["k8s"])

        def canon(tokens):
            return {t: ("kubernetes" if t in {"k8s", "kubernetes"} else t) for t in tokens}

        report = match_gap(session, _facts({"infra": [Skill(name="Kubernetes")]}), canonicalizer=canon)
        assert report.gaps == []  # k8s collapses onto kubernetes via the canonicalizer


def test_match_gap_empty_db():
    with _session() as session:
        report = match_gap(session, _facts({}))
        assert report == MatchGapReport(target_total=0, gaps=[], per_job={})


def test_gap_row_demand_share():
    assert GapRow(skill="X", demand_count=2, target_total=3).demand_share == 67
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tracking_match_gap.py::test_match_gap_aggregates_by_frequency -v`
Expected: FAIL with `ImportError: cannot import name 'match_gap'`

- [ ] **Step 3: Write minimal implementation** (add to `match_gap.py`)

```python
# src/resume_agent/tracking/match_gap.py — add to imports
from dataclasses import dataclass
from typing import Any, Callable, cast

from sqlmodel import Session, select

from resume_agent.tracking.tables import Job, JobStatus

TARGET_STATUSES = (
    JobStatus.shortlisted.value,
    JobStatus.approved.value,
    JobStatus.tailored.value,
    JobStatus.rendered.value,
)

Canonicalizer = Callable[[set[str]], dict[str, str]]
```

```python
# src/resume_agent/tracking/match_gap.py — add
@dataclass
class GapRow:
    """One missing skill, aggregated across target jobs."""

    skill: str          # display form (first JD spelling seen)
    demand_count: int   # how many target jobs demand it (and the profile lacks it)
    target_total: int   # number of target jobs considered

    @property
    def demand_share(self) -> int:
        return round(100 * self.demand_count / self.target_total) if self.target_total else 0


@dataclass
class MatchGapReport:
    target_total: int
    gaps: list[GapRow]                # aggregated, ranked by demand_count desc then skill asc
    per_job: dict[int, list[str]]     # job_id -> missing skills (display form)


def _target_jobs(session: Session) -> list[Job]:
    status_col = cast(Any, Job.status)
    return list(session.exec(select(Job).where(status_col.in_(TARGET_STATUSES))).all())


def match_gap(
    session: Session,
    facts: ProfileFacts,
    canonicalizer: Canonicalizer | None = None,
) -> MatchGapReport:
    """Skills demanded by target jobs that the profile doesn't cover. Pure read; no writes."""
    jobs = _target_jobs(session)

    # (job_id, [(normalized_token, display)]) for each target job
    job_reqs: list[tuple[int, list[tuple[str, str]]]] = []
    all_tokens: set[str] = set()
    for job in jobs:
        if job.id is None:
            continue
        raw = (job.criteria_json or {}).get("must_have_skills") or []
        pairs: list[tuple[str, str]] = []
        for skill in raw:
            token = normalize_skill(str(skill))
            if not token:
                continue
            pairs.append((token, str(skill)))
            all_tokens.add(token)
        job_reqs.append((job.id, pairs))

    profile_tokens = profile_skill_tokens(facts)
    all_tokens |= profile_tokens

    canon = canonicalizer(all_tokens) if canonicalizer else {t: t for t in all_tokens}
    profile_canon = {canon.get(t, t) for t in profile_tokens}

    target_total = len(job_reqs)
    per_job: dict[int, list[str]] = {}
    demand: dict[str, int] = {}
    display_for: dict[str, str] = {}
    for job_id, pairs in job_reqs:
        req_canon: dict[str, str] = {}  # canonical -> display (first spelling wins)
        for token, display in pairs:
            req_canon.setdefault(canon.get(token, token), display)
        missing = [display for c, display in req_canon.items() if c not in profile_canon]
        per_job[job_id] = missing
        for c, display in req_canon.items():
            if c not in profile_canon:
                demand[c] = demand.get(c, 0) + 1
                display_for.setdefault(c, display)

    gaps = [GapRow(display_for[c], n, target_total) for c, n in demand.items()]
    gaps.sort(key=lambda g: (-g.demand_count, g.skill.lower()))
    return MatchGapReport(target_total=target_total, gaps=gaps, per_job=per_job)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tracking_match_gap.py -v`
Expected: PASS (all, including the 7 new)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/match_gap.py tests/test_tracking_match_gap.py
git commit -m "feat(match-gap): pure match_gap() — frequency-ranked gaps + per-job, optional canonicalizer"
```

---

### Task 4: Optional cheap-LLM synonym canonicalizer

**Files:**
- Create: `src/resume_agent/tracking/canonicalize.py`
- Test: `tests/test_tracking_canonicalize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracking_canonicalize.py
from resume_agent.tracking.canonicalize import (
    SkillClusters,
    build_skill_canonicalizer,
    clusters_to_mapping,
)


def test_clusters_to_mapping_uses_first_member_as_canonical():
    m = clusters_to_mapping([["kubernetes", "k8s"]], {"kubernetes", "k8s", "python"})
    assert m == {"kubernetes": "kubernetes", "k8s": "kubernetes", "python": "python"}


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeRunner:
    def __init__(self, clusters):
        self._clusters = clusters

    def run(self, prompt):
        return _FakeResult(SkillClusters(clusters=self._clusters))


def test_canonicalizer_collapses_synonyms_with_a_fake_agent():
    canon = build_skill_canonicalizer(agent=_FakeRunner([["kubernetes", "k8s"]]))
    assert canon({"kubernetes", "k8s", "python"}) == {
        "kubernetes": "kubernetes",
        "k8s": "kubernetes",
        "python": "python",
    }


def test_canonicalizer_short_circuits_on_empty():
    canon = build_skill_canonicalizer(agent=_FakeRunner([]))
    assert canon(set()) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tracking_canonicalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.tracking.canonicalize'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/tracking/canonicalize.py
import json
from typing import Callable

from agno.agent import Agent
from agno.models.anthropic import Claude
from pydantic import Field

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner
from resume_agent.models.base import ExtensibleModel

_INSTRUCTIONS = [
    "You canonicalize technical skill names.",
    "Given a JSON array of lowercased skill tokens, group tokens that refer to the SAME skill.",
    "Return clusters as lists; put the most canonical/standard token FIRST in each cluster.",
    "Only group true synonyms (kubernetes/k8s; ci cd/continuous integration). Never merge distinct skills.",
]


class SkillClusters(ExtensibleModel):
    """Groups of skill tokens meaning the same thing; the first token is canonical."""

    clusters: list[list[str]] = Field(default_factory=list)


def clusters_to_mapping(clusters: list[list[str]], tokens: set[str]) -> dict[str, str]:
    """Map each token to its cluster's first (canonical) member; unknown tokens map to themselves."""
    mapping: dict[str, str] = {}
    for cluster in clusters:
        if not cluster:
            continue
        canonical = cluster[0]
        for token in cluster:
            mapping[token] = canonical
    return {t: mapping.get(t, t) for t in tokens}


def _default_agent() -> Runner:
    s = get_settings()
    return AgentRunner(
        Agent(
            model=Claude(id=s.cheap_model),
            description="You canonicalize skill names into synonym clusters.",
            instructions=_INSTRUCTIONS,
            output_schema=SkillClusters,
        )
    )


def build_skill_canonicalizer(agent: Runner | None = None) -> Callable[[set[str]], dict[str, str]]:
    """Return a canonicalizer(tokens)->mapping. Injects a cheap LLM unless an agent is supplied."""
    runner = agent or _default_agent()

    def canonicalize(tokens: set[str]) -> dict[str, str]:
        if not tokens:
            return {}
        result = runner.run(json.dumps(sorted(tokens)))
        content = result.content
        clusters = content.clusters if isinstance(content, SkillClusters) else []
        return clusters_to_mapping(clusters, tokens)

    return canonicalize
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tracking_canonicalize.py -v`
Expected: PASS (3 passed). No API key needed — the fake `Runner` is injected.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/canonicalize.py tests/test_tracking_canonicalize.py
git commit -m "feat(match-gap): optional cheap-LLM skill canonicalizer (synonym clustering)"
```

---

### Task 5: `match-gap` CLI command

**Files:**
- Modify: `src/resume_agent/cli.py` (imports near line 34-36; new command after `sources_cmd`, ~line 184)
- Test: `tests/test_cli_match_gap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_match_gap.py
from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.tracking.tables import Job

runner = CliRunner()


def _seed_job(db_url, status, must_have):
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as s:
        s.add(Job(source="manual", company="C", title="T", status=status,
                  criteria_json={"must_have_skills": must_have}))
        s.commit()


def test_match_gap_prints_aggregate(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed_job(db_url, "shortlisted", ["Kubernetes"])
    _seed_job(db_url, "approved", ["Kubernetes", "Go"])
    monkeypatch.setattr(
        cli, "load_facts", lambda path: ProfileFacts(contact=Contact(name="A"), skills={})
    )

    result = runner.invoke(cli.app, ["match-gap", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "Kubernetes" in result.output
    assert "2/2" in result.output


def test_match_gap_no_target_jobs(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    init_db(make_engine(db_url))
    monkeypatch.setattr(
        cli, "load_facts", lambda path: ProfileFacts(contact=Contact(name="A"), skills={})
    )

    result = runner.invoke(cli.app, ["match-gap", "--db-url", db_url])
    assert result.exit_code == 0
    assert "No jobs past discovery" in result.output


def test_match_gap_per_job(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed_job(db_url, "shortlisted", ["Kubernetes", "Python"])
    monkeypatch.setattr(
        cli,
        "load_facts",
        lambda path: ProfileFacts(contact=Contact(name="A"), skills={"lang": [Skill(name="Python")]}),
    )

    result = runner.invoke(cli.app, ["match-gap", "--job-id", "1", "--db-url", db_url])
    assert result.exit_code == 0, result.output
    assert "Kubernetes" in result.output
    assert "Python" not in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_match_gap.py -v`
Expected: FAIL — `match-gap` is not a registered command (Typer exits non-zero with "No such command").

- [ ] **Step 3: Write minimal implementation**

Add imports (group with the other `tracking`/`discovery` imports near the top of `cli.py`):

```python
# src/resume_agent/cli.py
from resume_agent.tracking.match_gap import match_gap
from resume_agent.tracking.canonicalize import build_skill_canonicalizer
```

Add the command (place it after `sources_cmd`, before `DEFAULT_REVIEW`):

```python
# src/resume_agent/cli.py
@app.command("match-gap")
def match_gap_cmd(
    job_id: int = typer.Option(None, help="Show gaps for one job instead of the aggregate."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    llm: bool = typer.Option(
        False, "--llm", help="Add a cheap-LLM canonicalization pass (e.g. k8s≈Kubernetes)."
    ),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Report skills your target jobs demand that your profile doesn't show."""
    profile_facts = load_facts(facts)
    canonicalizer = build_skill_canonicalizer() if llm else None
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = match_gap(session, profile_facts, canonicalizer=canonicalizer)

    if report.target_total == 0:
        typer.echo("No jobs past discovery yet. Run `discover` and shortlist/approve some first.")
        raise typer.Exit(code=0)

    if job_id is not None:
        missing = report.per_job.get(job_id)
        if missing is None:
            typer.echo(f"Job #{job_id} is not among your {report.target_total} target jobs.")
            raise typer.Exit(code=1)
        if not missing:
            typer.echo(f"Job #{job_id}: no skill gaps.")
            raise typer.Exit(code=0)
        typer.echo(f"Job #{job_id} missing skills:")
        for skill in missing:
            typer.echo(f"  {skill}")
        raise typer.Exit(code=0)

    if not report.gaps:
        typer.echo(f"No gaps across your {report.target_total} target jobs.")
        raise typer.Exit(code=0)
    typer.echo(f"Skill gaps across {report.target_total} target jobs:")
    for gap in report.gaps:
        typer.echo(f"  {gap.skill:<28} demanded by {gap.demand_count}/{gap.target_total}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_match_gap.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/cli.py tests/test_cli_match_gap.py
git commit -m "feat(cli): match-gap command (aggregate + --job-id + --llm)"
```

---

### Task 6: Dashboard Match-gap page

**Files:**
- Modify: `src/resume_agent/dashboard/app.py` (imports near line 9-24; new helpers + page after `render_analytics_page` ~line 434; sidebar/dispatch in `main` ~line 446-462)
- Test: `tests/test_dashboard_match_gap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dashboard_match_gap.py
from resume_agent.dashboard.app import match_gap_table_rows, render_match_gap_page
from resume_agent.tracking.match_gap import GapRow, MatchGapReport


def test_render_match_gap_page_is_importable_and_callable():
    assert callable(render_match_gap_page)


def test_match_gap_table_rows_formats_counts_and_share():
    report = MatchGapReport(
        target_total=3,
        gaps=[
            GapRow(skill="Kubernetes", demand_count=2, target_total=3),
            GapRow(skill="Go", demand_count=1, target_total=3),
        ],
        per_job={},
    )
    assert match_gap_table_rows(report) == [
        {"Skill": "Kubernetes", "Demanded by": "2/3", "Share %": 67},
        {"Skill": "Go", "Demanded by": "1/3", "Share %": 33},
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dashboard_match_gap.py -v`
Expected: FAIL with `ImportError: cannot import name 'match_gap_table_rows'`

- [ ] **Step 3: Write minimal implementation**

Add imports to `dashboard/app.py` (next to the existing `from resume_agent.tracking...` imports):

```python
# src/resume_agent/dashboard/app.py
from resume_agent.profile.store import load_facts
from resume_agent.tracking.match_gap import MatchGapReport, match_gap

_FACTS_PATH = "data/profile/facts.json"
```

Add the pure helper + page (place after `render_analytics_page`):

```python
# src/resume_agent/dashboard/app.py
def match_gap_table_rows(report: MatchGapReport) -> list[dict]:
    """Pure table rows for the match-gap page."""
    return [
        {
            "Skill": gap.skill,
            "Demanded by": f"{gap.demand_count}/{gap.target_total}",
            "Share %": gap.demand_share,
        }
        for gap in report.gaps
    ]


def render_match_gap_page(session) -> None:
    _masthead(
        "Closed loop",
        'Match <span class="dot">/</span> Gap',
        "Skills your target jobs demand that your profile doesn't show yet. Read-only — act on facts.json yourself.",
    )

    if not Path(_FACTS_PATH).exists():
        _empty_state(
            "◇",
            "No profile yet",
            "Run <code>resume-agent profile build</code> to create your fact-lock profile first.",
        )
        return

    report = match_gap(session, load_facts(_FACTS_PATH))
    _metric_row(
        [("Target jobs", str(report.target_total)), ("Distinct gaps", str(len(report.gaps)))]
    )

    if report.target_total == 0:
        _empty_state(
            "◇",
            "No target jobs yet",
            "Shortlist or approve jobs (they survive discovery) to populate the gap report.",
        )
        return
    if not report.gaps:
        _empty_state(
            "◆",
            "No gaps",
            "Your profile covers every required skill across your target jobs.",
        )
        return

    st.markdown('<div class="rail-head">Most-demanded missing skills</div>', unsafe_allow_html=True)
    st.table(match_gap_table_rows(report))
```

Wire it into the sidebar + dispatch in `main()` — replace the radio line and the if/elif block:

```python
# src/resume_agent/dashboard/app.py — inside main(), replace the radio line
        page = st.radio(
            "View",
            ["Shortlist", "Pipeline board", "Analytics", "Match-gap"],
            label_visibility="collapsed",
        )
```

```python
# src/resume_agent/dashboard/app.py — replace the dispatch block in main()
    engine = _engine()
    with get_session(engine) as session:
        if page == "Shortlist":
            render_shortlist_page(session)
        elif page == "Pipeline board":
            render_pipeline_page(session)
        elif page == "Analytics":
            render_analytics_page(session)
        else:
            render_match_gap_page(session)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dashboard_match_gap.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/dashboard/app.py tests/test_dashboard_match_gap.py
git commit -m "feat(dashboard): Match-gap page (most-demanded missing skills)"
```

---

### Task 7: Document the command + dashboard page

**Files:**
- Modify: `README.md` (command reference section, and the dashboard page list ~line 246-253)

- [ ] **Step 1: Add a command-reference entry** (after the `sources` section)

```markdown
### `match-gap` — what skills your target jobs want that you lack
Compares the `must_have_skills` of every job that survived discovery
(`shortlisted`/`approved`/`tailored`/`rendered`) against your profile's skills
(names + aliases) and reports the gaps, ranked by how many target jobs demand
each. Read-only — it never edits `facts.json`; you decide what to add or learn.

```bash
uv run resume-agent match-gap                 # aggregate, most-demanded first
uv run resume-agent match-gap --job-id 7      # gaps for one job
uv run resume-agent match-gap --llm           # add cheap-LLM synonym matching (k8s≈Kubernetes)
```
```

- [ ] **Step 2: Add the page to the dashboard description** — in the `dashboard` section's bullet list, add:

```markdown
- **Match-gap** — skills your target jobs demand that your profile doesn't
  show, ranked by frequency. The closed-loop read on what to add or learn.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(match-gap): document match-gap command and dashboard page"
```

---

## Full-suite gate

- [ ] **Run the entire suite**

Run: `uv run pytest -q`
Expected: all green, no network, no API key. Confirms the optional LLM pass stays faked and `match_gap` is a pure read (no new tables created — `SQLModel.metadata` is unchanged).

---

## Self-Review

**1. Spec coverage** (against spec §2 decisions 6–10, §5.2, §9):
- Decision 6 (input = survived-discovery, aggregate + per-job, no employer-rejection lens) → Task 3 `TARGET_STATUSES` + `test_match_gap_excludes_pre_shortlist_jobs` + `per_job`; no `Application` join anywhere. ✓
- Decision 7 (deterministic + opt-in LLM canonicalization, faked in tests) → Task 1/2/3 deterministic; Task 4 canonicalizer injected as a callable, faked; `test_match_gap_honors_canonicalizer`. ✓
- Decision 8 (both surfaces over one pure core) → Task 3 core; Task 5 CLI; Task 6 dashboard — both call `match_gap`. ✓
- Decision 9 (read-only) → no `save_*` calls in `match_gap`, the CLI command, or the page; page copy says "act on facts.json yourself." ✓
- Decision 10 (frequency ranking) → `gaps.sort(key=lambda g: (-g.demand_count, g.skill.lower()))` + `test_match_gap_aggregates_by_frequency`. ✓
- §6 (zero DB changes) → no new SQLModel table; full-suite gate notes `metadata` unchanged. ✓
- §9 headline test ("skill demanded by N of M, alias not a gap, filtered excluded") → Tasks 3 tests cover all three. ✓

**2. Placeholder scan:** No TBD/TODO; every code step is complete; every run step has an exact command + expected outcome. ✓

**3. Type consistency:** `match_gap(session, facts, canonicalizer=None) -> MatchGapReport` used identically in Tasks 5 and 6. `GapRow(skill, demand_count, target_total)` and its `demand_share` property are constructed/used consistently across Tasks 3 and 6. `Canonicalizer = Callable[[set[str]], dict[str, str]]` matches `build_skill_canonicalizer`'s return type and the stub in `test_match_gap_honors_canonicalizer`. `clusters_to_mapping(clusters, tokens)` and `SkillClusters(clusters=...)` are spelled identically in Task 4 source and tests. `_FACTS_PATH` defined once in Task 6. ✓

---

## Execution Handoff

Both plans (A: house-style, B: match-gap) are independent — no dependency edge — so either order or in parallel. Choose an execution approach (subagent-driven recommended).
