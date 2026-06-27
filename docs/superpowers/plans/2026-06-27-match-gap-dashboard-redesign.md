# Match / Gap Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Match/Gap dashboard into a tabbed Map+List workspace over a three-tier skill taxonomy, with a d3-force theme constellation, a job-modal-style skill detail, suggestion status tracking, and async multi-select batch suggestion generation.

**Architecture:** Additive backend changes expose per-skill member phrasings + frequencies + source mix and per-theme aggregates on the existing demand graph; two new suggestion endpoints (status list, batch generate). The React feature is rewritten into a tabbed shell (Map | Ranked list) sharing filter + selection state, a d3-force constellation, a theme-row ranked list, a `Dialog` skill modal, and a selection tray that fires per-item suggestion runs.

**Tech Stack:** Python 3.13 / FastAPI / SQLModel / Pydantic (CamelModel) backend; React + TypeScript + TanStack Query + Zustand + shadcn/ui + Tailwind frontend; `d3-force` + `d3-zoom` for the graph. Backend tests: pytest (fully offline, agents/browser faked). Frontend tests: vitest + Testing Library.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-06-27-match-gap-dashboard-redesign-design.md`.
- **Wire format is camelCase, Python is snake_case.** All API schemas extend `CamelModel` (`api/schemas/base.py`); `to_camel` maps `job_count`→`jobCount`, `skill_count`→`skillCount`, `gap_count`→`gapCount`, `generated_at`→`generatedAt`, `not_found`→`notFound`, `run_id`→`runId`.
- **Contracts are generated, never hand-edited.** After any schema change run `bash scripts/gen_ts_client.sh` to regenerate `contracts/openapi.json` + `contracts/ts/api.ts`; `tests/api/test_openapi_contract.py` is a drift gate that MUST pass.
- **Backend changes are additive.** Do NOT touch the legacy `match_gap()` report, `match_gap` CLI, fact-lock, or source-priority logic. The demand graph is read-only analytics over `Job.criteria_json`.
- **Every backend worker opens its OWN DB session** bound to `app.state.engine` (request sessions are not thread-safe).
- **Tests are offline.** No network, no real LLM, no real browser. Fake agents with a `.run()` stub returning `.content`; never call live endpoints.
- **Backend test command:** `.venv/Scripts/python.exe -m pytest <path>`. **Lint:** `ruff check`.
- **Frontend test command:** `cd web && npx vitest run <path>`. Type/lint as the repo configures (`cd web && npx tsc --noEmit`).
- **Suggestion tiers:** generalized **skill** is the default target; **theme** target is kept but never auto-selected.
- **New runtime deps (Phase 3 only):** `d3-force`, `d3-zoom`, `@types/d3-force`, `@types/d3-zoom`.

---

## File Structure

**Phase 1 — backend & contract**
- Modify: `src/resume_agent/tracking/match_gap.py` — `SkillNode`/`ThemeNode`/`build_demand_graph` retain members, frequencies, source mix, theme aggregates.
- Modify: `src/resume_agent/api/schemas/match_gap.py` — extend `SkillNodeOut`, `ThemeOut`.
- Modify: `src/resume_agent/api/schemas/suggestions.py` — add `SuggestionStatusOut`, batch DTOs.
- Modify: `src/resume_agent/api/routers/suggestions.py` — `GET /suggestions/status`, `POST /suggestions/generate-batch`.
- Modify: `src/resume_agent/config.py` — `suggestion_batch_concurrency`.
- Modify: `src/resume_agent/api/app.py` — size the run executor from the setting.
- Tests: `tests/test_tracking_match_gap.py`, `tests/api/test_schemas_match_gap.py`, `tests/api/test_suggestions.py`, `tests/api/test_match_gap.py`, `tests/test_config.py` (new if absent).

**Phase 2 — frontend shell + ranked list**
- Modify: `web/src/features/match-gap/aggregate.ts` — theme rows w/ members, status, within-group sort.
- Create: `web/src/features/match-gap/use-suggestion-status.ts` — status query + `effectiveState` derivation.
- Rewrite: `web/src/features/match-gap/RankedList.tsx` — theme rows → expandable skills + badges + compaction.
- Rewrite: `web/src/features/match-gap/MatchGapContainer.tsx` — tabbed shell.
- Delete: `web/src/features/match-gap/WordCloud.tsx` (+ test), `web/src/features/match-gap/StatTables.tsx`.
- Tests: `aggregate.test.ts`, `use-suggestion-status.test.tsx`, `RankedList.test.tsx`, `MatchGapContainer.test.tsx`.

**Phase 3 — constellation Map**
- Modify: `web/package.json` — add d3 deps.
- Create: `web/src/features/match-gap/skill-map-layout.ts` — pure layout (deterministic, tested).
- Create: `web/src/features/match-gap/SkillMap.tsx` — SVG + simulation + zoom + interactions.
- Tests: `skill-map-layout.test.ts`, `SkillMap.test.tsx`.

**Phase 4 — modal + selection tray + batch**
- Create: `web/src/features/match-gap/SkillModal.tsx` — `Dialog`, evidence rail + tabbed main.
- Delete: `web/src/features/match-gap/SkillDrawer.tsx` (+ test) once `SkillModal` replaces it.
- Create: `web/src/features/match-gap/use-batch-suggestions.ts` — basket batch launcher.
- Create: `web/src/features/match-gap/SelectionTray.tsx` — basket panel w/ per-item status.
- Modify: `web/src/features/match-gap/MatchGapContainer.tsx` — wire modal, tray, basket state.
- Tests: `SkillModal.test.tsx`, `use-batch-suggestions.test.tsx`, `SelectionTray.test.tsx`, `MatchGapContainer.test.tsx`.

---

## Phase 1 — Backend & contract

### Task 1: Demand graph retains members, frequencies, source mix, theme aggregates

**Files:**
- Modify: `src/resume_agent/tracking/match_gap.py` (dataclasses `SkillNode`, `ThemeNode`, `DemandGraph`; function `build_demand_graph`)
- Test: `tests/test_tracking_match_gap.py`

**Interfaces:**
- Produces:
  - `SkillNode(skill: str, theme_id: str | None, covered: bool, members: dict[str, int], must: int, nice: int, tech: int, job_count: int)`
  - `ThemeNode(id: str, label: str, score: int, skill_count: int, gap_count: int)`
  - `build_demand_graph(session, facts, cluster_map=None) -> DemandGraph` (unchanged signature; richer nodes)
  - Weighting for `ThemeNode.score`: `must*3 + nice*2 + tech*1` summed over member skills (the essential weighting; the client re-derives `popular`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tracking_match_gap.py`:

```python
from resume_agent.tracking.match_gap import build_demand_graph
from resume_agent.taxonomy.clusters import ClusterMap


def _job_criteria(session, status, *, must=None, nice=None, tech=None):
    return save_job(
        session,
        Job(
            source="manual", company="C", title="T", status=status,
            criteria_json={
                "must_have_skills": must or [],
                "nice_to_have_skills": nice or [],
                "tech_stack": tech or [],
            },
        ),
    )


def test_demand_graph_collects_members_frequencies_and_source_mix():
    cmap = ClusterMap(
        aliases={"python": "python", "python3": "python", "py": "python"},
        theme_of={"python": "backend"},
        theme_label={"backend": "Backend"},
    )
    with _session() as session:
        _job_criteria(session, JobStatus.shortlisted.value, must=["Python"], tech=["python3"])
        _job_criteria(session, JobStatus.approved.value, must=["py"])

        graph = build_demand_graph(session, _facts({}), cluster_map=cmap)

        node = next(n for n in graph.skills if n.skill == "Python")
        # display = highest-frequency member phrasing
        assert node.skill == "Python"
        assert node.members == {"Python": 1, "python3": 1, "py": 1}
        assert node.job_count == 2
        assert node.must == 2  # job1 must + job2 must
        assert node.tech == 1
        assert node.covered is False
        theme = next(t for t in graph.themes if t.id == "backend")
        assert theme.skill_count == 1
        assert theme.gap_count == 1
        assert theme.score == 2 * 3 + 0 * 2 + 1 * 1  # must=2, nice=0, tech=1


def test_demand_graph_theme_aggregates_count_only_gaps():
    cmap = ClusterMap(
        aliases={"python": "python", "sql": "sql"},
        theme_of={"python": "backend", "sql": "backend"},
        theme_label={"backend": "Backend"},
    )
    facts = _facts({"db": [Skill(name="SQL")]})
    with _session() as session:
        _job_criteria(session, JobStatus.shortlisted.value, must=["Python", "SQL"])
        graph = build_demand_graph(session, facts, cluster_map=cmap)
        theme = next(t for t in graph.themes if t.id == "backend")
        assert theme.skill_count == 2
        assert theme.gap_count == 1  # SQL covered, Python is the only gap
```

(Reuse the existing `_session`, `_facts`, `save_job`, `Job`, `JobStatus`, `Skill` imports already in the file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_match_gap.py -k "members_frequencies or theme_aggregates" -v`
Expected: FAIL (`SkillNode` has no `members` / `TypeError` on dataclass fields).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/tracking/match_gap.py` replace the `SkillNode` and `ThemeNode` dataclasses and the body of `build_demand_graph`:

```python
@dataclass
class SkillNode:
    skill: str
    theme_id: str | None
    covered: bool
    members: dict[str, int]
    must: int
    nice: int
    tech: int
    job_count: int


@dataclass
class ThemeNode:
    id: str
    label: str
    score: int
    skill_count: int
    gap_count: int
```

Rewrite `build_demand_graph` to accumulate per-canonical aggregates. Replace the loop body and the trailing theme/return block:

```python
def build_demand_graph(
    session: Session,
    facts: ProfileFacts,
    cluster_map: "ClusterMap | None" = None,
) -> DemandGraph:
    """Build normalized target-job skill demand for dashboard consumers."""
    target_jobs = _target_jobs(session)
    profile_tokens = profile_skill_tokens(facts)
    aliases = cluster_map.aliases if cluster_map else {}
    theme_of = cluster_map.theme_of if cluster_map else {}
    theme_label = cluster_map.theme_label if cluster_map else {}
    profile_canonical = {aliases.get(token, token) for token in profile_tokens}

    @dataclass
    class _Acc:
        members: dict[str, int]
        jobs: set[int]
        must: int
        nice: int
        tech: int

    jobs: list[JobLite] = []
    acc: dict[str, _Acc] = {}
    edges: list[DemandEdge] = []

    for job in target_jobs:
        if job.id is None:
            continue
        criteria = job.criteria_json or {}
        seniority = criteria.get("seniority")
        jobs.append(
            JobLite(
                id=job.id,
                company=job.company,
                title=job.title,
                seniority=seniority if isinstance(seniority, str) else None,
            )
        )
        emitted: set[tuple[str, SkillSource]] = set()
        member_seen: set[tuple[str, str]] = set()
        for key, source in _SKILL_SOURCES:
            for raw_skill in _criteria_skill_values(job, key):
                token = normalize_skill(raw_skill)
                canonical = aliases.get(token, token)
                if not canonical:
                    continue
                phrasing = raw_skill.strip()
                entry = acc.setdefault(
                    canonical, _Acc(members={}, jobs=set(), must=0, nice=0, tech=0)
                )
                if (canonical, phrasing) not in member_seen:
                    member_seen.add((canonical, phrasing))
                    entry.members[phrasing] = entry.members.get(phrasing, 0) + 1
                entry.jobs.add(job.id)
                edge_key = (canonical, source)
                if edge_key in emitted:
                    continue
                emitted.add(edge_key)
                setattr(entry, source, getattr(entry, source) + 1)

    skill_nodes: list[SkillNode] = []
    edges = []  # rebuild edges keyed by display below
    display_of: dict[str, str] = {}
    for canonical, entry in acc.items():
        display = max(entry.members.items(), key=lambda kv: (kv[1], kv[0]))[0]
        display_of[canonical] = display

    for job in target_jobs:
        if job.id is None:
            continue
        emitted_edges: set[tuple[str, SkillSource]] = set()
        for key, source in _SKILL_SOURCES:
            for raw_skill in _criteria_skill_values(job, key):
                canonical = aliases.get(normalize_skill(raw_skill), normalize_skill(raw_skill))
                if not canonical or canonical not in display_of:
                    continue
                display = display_of[canonical]
                if (display, source) in emitted_edges:
                    continue
                emitted_edges.add((display, source))
                edges.append(DemandEdge(job_id=job.id, skill=display, source=source))

    for canonical, entry in acc.items():
        display = display_of[canonical]
        members = {
            (display if phrasing == display else phrasing): count
            for phrasing, count in entry.members.items()
        }
        skill_nodes.append(
            SkillNode(
                skill=display,
                theme_id=theme_of.get(canonical),
                covered=canonical in profile_canonical,
                members=entry.members,
                must=entry.must,
                nice=entry.nice,
                tech=entry.tech,
                job_count=len(entry.jobs),
            )
        )

    by_theme: dict[str, list[SkillNode]] = {}
    for node in skill_nodes:
        if node.theme_id is not None:
            by_theme.setdefault(node.theme_id, []).append(node)
    themes = [
        ThemeNode(
            id=theme_id,
            label=theme_label.get(theme_id, theme_id),
            score=sum(n.must * 3 + n.nice * 2 + n.tech * 1 for n in members_),
            skill_count=len(members_),
            gap_count=sum(1 for n in members_ if not n.covered),
        )
        for theme_id, members_ in sorted(by_theme.items())
    ]
    return DemandGraph(
        target_total=len(jobs),
        clusters_stale=any(node.theme_id is None for node in skill_nodes),
        jobs=jobs,
        skills=skill_nodes,
        edges=edges,
        themes=themes,
    )
```

(Keep the `display` key in `members` as the chosen display string — the test asserts `{"Python": 1, "python3": 1, "py": 1}`, i.e. the display phrasing replaces the raw `"Python"` only when they are identical; raw phrasings are preserved verbatim.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_match_gap.py -v`
Expected: PASS (all existing + 2 new). Then `ruff check src/resume_agent/tracking/match_gap.py`.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/match_gap.py tests/test_tracking_match_gap.py
git commit -m "feat(match-gap): retain skill members, frequencies, source mix, theme aggregates"
```

---

### Task 2: Extend match-gap API schemas + regenerate contract

**Files:**
- Modify: `src/resume_agent/api/schemas/match_gap.py`
- Test: `tests/api/test_schemas_match_gap.py`, `tests/api/test_match_gap.py`
- Generated: `contracts/openapi.json`, `contracts/ts/api.ts`

**Interfaces:**
- Consumes: `SkillNode`, `ThemeNode` from Task 1.
- Produces (camelCase wire): `SkillNodeOut{skill, themeId, covered, members: dict[str,int], must, nice, tech, jobCount}`, `ThemeOut{id, label, score, skillCount, gapCount}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_schemas_match_gap.py`:

```python
from resume_agent.api.schemas.match_gap import SkillNodeOut, ThemeOut
from resume_agent.tracking.match_gap import SkillNode, ThemeNode


def test_skill_node_out_projects_members_and_source_mix():
    node = SkillNode(
        skill="Python", theme_id="backend", covered=False,
        members={"Python": 2, "py": 1}, must=2, nice=1, tech=0, job_count=3,
    )
    out = SkillNodeOut.model_validate(node)
    dumped = out.model_dump(by_alias=True)
    assert dumped["members"] == {"Python": 2, "py": 1}
    assert dumped["jobCount"] == 3
    assert dumped["must"] == 2 and dumped["nice"] == 1 and dumped["tech"] == 0


def test_theme_out_projects_aggregates():
    theme = ThemeNode(id="backend", label="Backend", score=18, skill_count=4, gap_count=2)
    dumped = ThemeOut.model_validate(theme).model_dump(by_alias=True)
    assert dumped == {"id": "backend", "label": "Backend", "score": 18, "skillCount": 4, "gapCount": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_match_gap.py -k "members_and_source_mix or aggregates" -v`
Expected: FAIL (`SkillNodeOut` has no `members`/`jobCount`).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/api/schemas/match_gap.py` extend the two models:

```python
class SkillNodeOut(CamelModel):
    skill: str
    theme_id: str | None = None
    covered: bool
    members: dict[str, int] = {}
    must: int = 0
    nice: int = 0
    tech: int = 0
    job_count: int = 0


class ThemeOut(CamelModel):
    id: str
    label: str
    score: int = 0
    skill_count: int = 0
    gap_count: int = 0
```

- [ ] **Step 4: Verify tests pass + regenerate contract**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_match_gap.py tests/api/test_match_gap.py -v`
Expected: PASS.
Then regenerate and confirm the drift gate:
Run: `bash scripts/gen_ts_client.sh && .venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS (and `contracts/ts/api.ts` now carries `members`, `jobCount`, `skillCount`, `gapCount`).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/schemas/match_gap.py tests/api/test_schemas_match_gap.py contracts/
git commit -m "feat(api): expose skill members + theme aggregates in match-gap contract"
```

---

### Task 3: `GET /api/suggestions/status` — which targets have suggestions

**Files:**
- Modify: `src/resume_agent/api/schemas/suggestions.py` (add `SuggestionStatusOut`)
- Modify: `src/resume_agent/api/routers/suggestions.py` (add route)
- Test: `tests/api/test_suggestions.py`
- Generated: `contracts/openapi.json`, `contracts/ts/api.ts`

**Interfaces:**
- Produces: `GET /api/suggestions/status -> list[SuggestionStatusOut]` where `SuggestionStatusOut{kind: "skill"|"theme", key: str, state: "ready"|"stale", generatedAt: datetime}`. `stale` computed exactly as `get_suggestion` does (current fingerprint vs stored).

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_suggestions.py` (reuse `_configure`, `_seed_job`, `_wait_for_run`, `_Agent`, fakes):

```python
def test_status_lists_ready_and_stale(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(router_module, "build_search_agent", lambda: _Agent("Research"))
    monkeypatch.setattr(
        router_module, "build_formatter_agent",
        lambda: _Agent(SuggestionDraft(bridge="Bridge")),
    )
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        _seed_job(app.state.engine)  # Kubernetes, Terraform
        launched = client.post("/api/suggestions/generate", json={"kind": "skill", "key": "Kubernetes"})
        assert _wait_for_run(client, launched.json()["runId"])["state"] == "done"

        before = client.get("/api/suggestions/status").json()
        assert before == [{"kind": "skill", "key": "Kubernetes", "state": "ready",
                           "generatedAt": before[0]["generatedAt"]}]

        _seed_job(app.state.engine, company="D", skills=["Kubernetes", "Helm"])  # demand changes
        after = client.get("/api/suggestions/status").json()
        assert after[0]["state"] == "stale"


def test_status_empty_when_none_generated(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        _seed_job(app.state.engine)
        assert client.get("/api/suggestions/status").json() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_suggestions.py -k "status_lists or status_empty" -v`
Expected: FAIL (404 — route missing).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/api/schemas/suggestions.py` add:

```python
class SuggestionStatusOut(CamelModel):
    kind: Literal["skill", "theme"]
    key: str
    state: Literal["ready", "stale"]
    generated_at: datetime
```

In `src/resume_agent/api/routers/suggestions.py` add the route (above `launch_generate`), reusing existing imports (`build_demand_graph`, `profile_skill_tokens`, `suggestion_fingerprint`, `resolve_suggestion_context`, `SkillSuggestion`, `load_cluster_map`):

```python
@router.get("/suggestions/status", response_model=list[SuggestionStatusOut])
def list_suggestion_status(session: Session = Depends(get_session)):
    facts = _facts_or_empty()
    graph = build_demand_graph(session, facts, cluster_map=load_cluster_map(_CLUSTER_PATH))
    coverage = profile_skill_tokens(facts)
    out: list[SuggestionStatusOut] = []
    for row in session.exec(select(SkillSuggestion)).all():
        try:
            context = resolve_suggestion_context(graph, kind=row.kind, key=row.key)
        except SuggestionTargetNotFound:
            continue  # target no longer demanded; omit from the dashboard
        current = suggestion_fingerprint(context, coverage)
        out.append(
            SuggestionStatusOut(
                kind=row.kind, key=row.key,
                state="stale" if row.fingerprint != current else "ready",
                generated_at=row.generated_at,
            )
        )
    return out
```

Add `SuggestionStatusOut` to the existing `from resume_agent.api.schemas.suggestions import (...)` block.

- [ ] **Step 4: Verify + regenerate contract**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_suggestions.py -v`
Expected: PASS.
Run: `bash scripts/gen_ts_client.sh && .venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/schemas/suggestions.py src/resume_agent/api/routers/suggestions.py tests/api/test_suggestions.py contracts/
git commit -m "feat(api): GET /suggestions/status for ready/stale tracking"
```

---

### Task 4: Batch generation endpoint + concurrency setting

**Files:**
- Modify: `src/resume_agent/config.py` (`suggestion_batch_concurrency`)
- Modify: `src/resume_agent/api/app.py` (size run executor)
- Modify: `src/resume_agent/api/schemas/suggestions.py` (batch DTOs)
- Modify: `src/resume_agent/api/routers/suggestions.py` (`POST /suggestions/generate-batch`)
- Test: `tests/api/test_suggestions.py`, `tests/test_config.py`
- Generated: `contracts/`

**Interfaces:**
- Consumes: `RunManager.submit("suggestion", work)`, the existing `generate_suggestion` worker.
- Produces:
  - `Settings.suggestion_batch_concurrency: int` (default 3, `ge=1`).
  - `POST /api/suggestions/generate-batch` body `{ items: [{kind, key}, …] }` → `BatchGenerateOut{runs: [{kind, key, runId}], notFound: [{kind, key}]}` (status 202). Duplicate items collapse; unknown targets land in `notFound`, never abort.
  - In `create_app`, when `run_executor is None`, the `RunManager` executor is `ThreadPoolExecutor(max_workers=settings.suggestion_batch_concurrency)` so concurrent suggestion runs are bounded by the setting.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` (create the file if absent — mirror existing config import style):

```python
from resume_agent.config import Settings


def test_suggestion_batch_concurrency_default_and_floor():
    assert Settings().suggestion_batch_concurrency == 3
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(suggestion_batch_concurrency=0)
```

Add to `tests/api/test_suggestions.py`:

```python
def test_generate_batch_launches_one_run_per_item_and_reports_not_found(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(router_module, "build_search_agent", lambda: _Agent("Research"))
    monkeypatch.setattr(
        router_module, "build_formatter_agent",
        lambda: _Agent(SuggestionDraft(bridge="Bridge")),
    )
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        _seed_job(app.state.engine)  # Kubernetes, Terraform
        resp = client.post(
            "/api/suggestions/generate-batch",
            json={"items": [
                {"kind": "skill", "key": "Kubernetes"},
                {"kind": "skill", "key": "Terraform"},
                {"kind": "skill", "key": "Kubernetes"},   # dup collapses
                {"kind": "skill", "key": "Nonexistent"},  # not found
            ]},
        )
        assert resp.status_code == 202
        body = resp.json()
        keys = sorted(r["key"] for r in body["runs"])
        assert keys == ["Kubernetes", "Terraform"]
        assert body["notFound"] == [{"kind": "skill", "key": "Nonexistent"}]
        for run in body["runs"]:
            assert _wait_for_run(client, run["runId"])["state"] == "done"
        status = {s["key"] for s in client.get("/api/suggestions/status").json()}
        assert status == {"Kubernetes", "Terraform"}


def test_generate_batch_concurrency_never_exceeds_cap(monkeypatch, tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    _configure(monkeypatch, tmp_path)
    cap = 2
    monkeypatch.setattr(Settings_for_test := router_module, "build_search_agent", lambda: _Agent("Research"), raising=False)
    # instrument the worker: count concurrent generations
    live = {"n": 0, "max": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(cap)

    def fake_generate(*args, **kwargs):
        with lock:
            live["n"] += 1
            live["max"] = max(live["max"], live["n"])
        barrier.wait(timeout=2)  # force `cap` to overlap, prove parallelism
        with lock:
            live["n"] -= 1
        class _Row:
            kind, key = "skill", kwargs.get("context").key
        return _Row()

    monkeypatch.setattr(router_module, "generate_suggestion", fake_generate)
    app = create_app(db_url="sqlite://", run_executor=ThreadPoolExecutor(max_workers=cap))
    with TestClient(app) as client:
        _seed_job(app.state.engine, skills=["Kubernetes", "Terraform", "Helm", "Argo"])
        resp = client.post("/api/suggestions/generate-batch", json={"items": [
            {"kind": "skill", "key": k} for k in ["Kubernetes", "Terraform", "Helm", "Argo"]
        ]})
        for run in resp.json()["runs"]:
            _wait_for_run(client, run["runId"])
    assert live["max"] == cap
```

(If a `tests/test_config.py` already exists, append the test there instead of recreating.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/api/test_suggestions.py -k "batch or concurrency" -v`
Expected: FAIL (no setting / 404 route).

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/config.py`, after `llm_retry_delay`:

```python
    suggestion_batch_concurrency: int = Field(default=3, ge=1)
```

In `src/resume_agent/api/app.py`, replace the `run_manager` assignment block:

```python
    from concurrent.futures import ThreadPoolExecutor

    executor = run_executor or ThreadPoolExecutor(
        max_workers=resolved_settings.suggestion_batch_concurrency
    )
    app.state.run_manager = (
        RunManager(root=runs_root, executor=executor)
        if runs_root is not None
        else RunManager(executor=executor)
    )
```

(The injected-executor test path is unchanged; only the default path is sized.)

In `src/resume_agent/api/schemas/suggestions.py` add:

```python
class SuggestionTarget(CamelModel):
    kind: Literal["skill", "theme"]
    key: str


class BatchRunOut(CamelModel):
    kind: Literal["skill", "theme"]
    key: str
    run_id: str


class BatchGenerateOut(CamelModel):
    runs: list[BatchRunOut]
    not_found: list[SuggestionTarget]
```

In `src/resume_agent/api/routers/suggestions.py` add the batch route (after `launch_generate`), reusing the `work`-closure shape from `launch_generate`:

```python
class BatchGenerateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[GenerateParams] = Field(min_length=1, max_length=100)


@router.post("/suggestions/generate-batch", response_model=BatchGenerateOut, status_code=202)
def launch_generate_batch(
    params: BatchGenerateParams,
    request: Request,
    session: Session = Depends(get_session),
    mgr: RunManager = Depends(get_run_manager),
):
    engine = request.app.state.engine
    github_token = request.app.state.settings.github_token
    facts = _facts_or_empty()

    seen: set[tuple[str, str]] = set()
    runs: list[BatchRunOut] = []
    not_found: list[SuggestionTarget] = []
    for item in params.items:
        ident = (item.kind, item.key)
        if ident in seen:
            continue
        seen.add(ident)
        try:
            _resolve_context(session, facts, kind=item.kind, key=item.key)
        except ApiException:
            not_found.append(SuggestionTarget(kind=item.kind, key=item.key))
            continue

        def work(reporter, _item=item):
            reporter.begin(1, f"Researching {_item.key}")
            with open_session(engine) as worker_session:
                worker_facts = _facts_or_empty()
                context = _resolve_context(
                    worker_session, worker_facts, kind=_item.kind, key=_item.key
                )
                row = generate_suggestion(
                    worker_session, context=context,
                    search_agent=build_search_agent(), formatter=build_formatter_agent(),
                    verify=lambda owner, name: verify_repo(owner, name, token=github_token),
                    facts=worker_facts, reporter=reporter,
                )
            reporter.step(1)
            return {"kind": row.kind, "key": row.key}

        run_id = mgr.submit("suggestion", work)
        runs.append(BatchRunOut(kind=item.kind, key=item.key, run_id=run_id))

    return BatchGenerateOut(runs=runs, not_found=not_found)
```

Add `BatchGenerateOut`, `BatchRunOut`, `SuggestionTarget` to the schemas import block.

- [ ] **Step 4: Verify + regenerate**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/api/test_suggestions.py -v`
Expected: PASS.
Run: `bash scripts/gen_ts_client.sh && .venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v && ruff check src/resume_agent`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/config.py src/resume_agent/api/app.py src/resume_agent/api/schemas/suggestions.py src/resume_agent/api/routers/suggestions.py tests/test_config.py tests/api/test_suggestions.py contracts/
git commit -m "feat(api): batch suggestion generation bounded by suggestion_batch_concurrency"
```

---

## Phase 2 — Frontend shell + ranked list

### Task 5: `aggregate.ts` — theme rows with members, status, within-group sort

**Files:**
- Modify: `web/src/features/match-gap/aggregate.ts`
- Test: `web/src/features/match-gap/aggregate.test.ts`

**Interfaces:**
- Consumes: extended `MatchGapOut` (Task 2) — `skills[].members/must/nice/tech/jobCount`, `themes[].score/skillCount/gapCount`.
- Produces additions to `aggregate.ts`:
  - `SkillRow` gains `members: Record<string, number>`.
  - `interface ThemeRow { id: string; label: string; score: number; gapCount: number; skills: SkillRow[]; }`
  - `DerivedView` gains `themeRows: ThemeRow[]`.
  - `type SuggestionState = "none" | "ready" | "stale" | "researching" | "queued" | "failed"`.
  - `function sortSkillsWithin(skills: SkillRow[], stateOf: (skill: string) => SuggestionState): SkillRow[]` — ready/researching float above demand order; stable otherwise.

- [ ] **Step 1: Write the failing test**

Add to `web/src/features/match-gap/aggregate.test.ts`:

```ts
import { sortSkillsWithin, type SkillRow } from "./aggregate";

const row = (skill: string, score: number): SkillRow => ({
  skill, themeId: "t", covered: false, score, jobCount: 1,
  must: 0, nice: 0, tech: 0, members: {},
});

it("floats ready-suggestion skills above pure demand order", () => {
  const skills = [row("A", 90), row("B", 80), row("C", 70)];
  const sorted = sortSkillsWithin(skills, (s) => (s === "C" ? "ready" : "none"));
  expect(sorted.map((s) => s.skill)).toEqual(["C", "A", "B"]);
});

it("keeps demand order when no statuses differ", () => {
  const skills = [row("A", 90), row("B", 80)];
  const sorted = sortSkillsWithin(skills, () => "none");
  expect(sorted.map((s) => s.skill)).toEqual(["A", "B"]);
});
```

Also extend the existing `deriveView` test to assert `view.themeRows[0].skills` carries `members`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/aggregate.test.ts`
Expected: FAIL (`sortSkillsWithin`/`members`/`themeRows` undefined).

- [ ] **Step 3: Write minimal implementation**

In `aggregate.ts`: add `members: Record<string, number>` to `SkillRow`; populate it in `summarize` from `edge`-independent node data (read members off `payload.skills`). Add the `SuggestionState` type, `ThemeRow`, `themeRows` in `DerivedView`, and:

```ts
export type SuggestionState =
  | "none" | "ready" | "stale" | "researching" | "queued" | "failed";

const STATE_RANK: Record<SuggestionState, number> = {
  ready: 0, researching: 1, queued: 2, stale: 3, failed: 4, none: 5,
};

export function sortSkillsWithin(
  skills: SkillRow[],
  stateOf: (skill: string) => SuggestionState,
): SkillRow[] {
  return [...skills].sort(
    (a, b) =>
      STATE_RANK[stateOf(a.skill)] - STATE_RANK[stateOf(b.skill)] ||
      b.score - a.score ||
      a.skill.localeCompare(b.skill),
  );
}
```

In `summarize`, attach members: build a `membersBySkill = new Map(payload.skills.map((s) => [s.skill, s.members ?? {}]))` in `deriveView` and pass through so each `SkillRow` gets `members: membersBySkill.get(skill) ?? {}`. Build `themeRows` from the existing `themeGroups` plus `payload.themes` (`score`, `gapCount` from server baseline; `skills` from the filtered groups). Keep the existing `themes` field for back-compat until Task 8 removes its only consumer.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/match-gap/aggregate.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/match-gap/aggregate.ts web/src/features/match-gap/aggregate.test.ts
git commit -m "feat(match-gap): theme rows, member frequencies, status-aware skill sort"
```

---

### Task 6: `useSuggestionStatus` — query + effective-state derivation

**Files:**
- Create: `web/src/features/match-gap/use-suggestion-status.ts`
- Test: `web/src/features/match-gap/use-suggestion-status.test.tsx`

**Interfaces:**
- Consumes: `GET /api/suggestions/status` (Task 3), `useRunStore` (per-run `kind: "suggestion"`, `status`), the run `result` `{kind, key}` to map a run → target.
- Produces:
  - `useSuggestionStatus() -> { stateOf: (kind: SuggestionKind, key: string) => SuggestionState }`.
  - Precedence: in-flight run (`failed`/`researching`/`queued`) > `ready`/`stale` from endpoint > `none`.

- [ ] **Step 1: Write the failing test**

Create `use-suggestion-status.test.tsx`:

```tsx
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { deriveState } from "./use-suggestion-status";

describe("deriveState", () => {
  it("prefers in-flight run status over endpoint", () => {
    expect(deriveState({ endpoint: "ready", run: "running" })).toBe("researching");
    expect(deriveState({ endpoint: "ready", run: "failed" })).toBe("failed");
  });
  it("falls back to endpoint then none", () => {
    expect(deriveState({ endpoint: "stale", run: undefined })).toBe("stale");
    expect(deriveState({ endpoint: undefined, run: undefined })).toBe("none");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/use-suggestion-status.test.tsx`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

Create `use-suggestion-status.ts`:

```ts
import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { useRunStore } from "@/lib/runs/store";
import type { SuggestionState } from "./aggregate";
import type { SuggestionKind } from "./use-suggestion";

type StatusRow = components["schemas"]["SuggestionStatusOut"];

export function deriveState(input: {
  endpoint: "ready" | "stale" | undefined;
  run: "running" | "cancelling" | "failed" | "succeeded" | "cancelled" | undefined;
}): SuggestionState {
  if (input.run === "running" || input.run === "cancelling") return "researching";
  if (input.run === "failed") return "failed";
  return input.endpoint ?? "none";
}

export function useSuggestionStatus() {
  const { data } = useQuery({
    queryKey: ["suggestion-status"],
    queryFn: (): Promise<StatusRow[]> =>
      unwrap(api.GET("/api/suggestions/status", {})) as Promise<StatusRow[]>,
  });
  const runs = useRunStore((s) => s.runs);
  const endpointByKey = new Map((data ?? []).map((r) => [`${r.kind}:${r.key}`, r.state]));
  const runByKey = new Map(
    Object.values(runs)
      .filter((r) => r.kind === "suggestion" && r.result)
      .map((r) => [
        `${(r.result as { kind?: string }).kind}:${(r.result as { key?: string }).key}`,
        r.status,
      ]),
  );
  const stateOf = (kind: SuggestionKind, key: string): SuggestionState =>
    deriveState({
      endpoint: endpointByKey.get(`${kind}:${key}`),
      run: runByKey.get(`${kind}:${key}`),
    });
  return { stateOf };
}
```

(If the run store does not carry `result` for in-flight runs, `runByKey` simply yields `undefined` and precedence falls through — acceptable; live `researching` is also surfaced by the tray via the launched run ids in Task 12.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/match-gap/use-suggestion-status.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/match-gap/use-suggestion-status.ts web/src/features/match-gap/use-suggestion-status.test.tsx
git commit -m "feat(match-gap): suggestion status hook with run-precedence state"
```

---

### Task 7: Rewrite `RankedList` — theme rows → expandable skills + badges + compaction

**Files:**
- Rewrite: `web/src/features/match-gap/RankedList.tsx`
- Test: `web/src/features/match-gap/RankedList.tsx` → `RankedList.test.tsx` (create)

**Interfaces:**
- Consumes: `ThemeRow`/`SkillRow` (Task 5), `SuggestionState` + `stateOf` (Task 6).
- Produces: `RankedList({ themeRows, stateOf, selected, onToggleSelect, onOpenSkill })` where `selected: Set<string>` keyed `skill:<name>`, `onToggleSelect(kind, key)`, `onOpenSkill(skill: SkillRow)`.

- [ ] **Step 1: Write the failing test**

Create `RankedList.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RankedList } from "./RankedList";
import type { ThemeRow } from "./aggregate";

const theme: ThemeRow = {
  id: "backend", label: "Backend", score: 18, gapCount: 1,
  skills: [{ skill: "Python", themeId: "backend", covered: false, score: 12,
    jobCount: 3, must: 2, nice: 1, tech: 0, members: { Python: 2 } }],
};

it("collapses skills until a theme row is expanded, then opens a skill", () => {
  const onOpenSkill = vi.fn();
  render(
    <RankedList themeRows={[theme]} stateOf={() => "ready"}
      selected={new Set()} onToggleSelect={vi.fn()} onOpenSkill={onOpenSkill} />,
  );
  expect(screen.queryByText("Python")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Backend/ }));
  fireEvent.click(screen.getByText("Python"));
  expect(onOpenSkill).toHaveBeenCalledWith(theme.skills[0]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/RankedList.test.tsx`
Expected: FAIL (RankedList signature mismatch / Python rendered).

- [ ] **Step 3: Write minimal implementation**

Rewrite `RankedList.tsx`: render `themeRows` as collapsible rows (demand bar from `score`, `gapCount`, skill count). Local `expanded: Set<string>` of theme ids. When expanded, render `sortSkillsWithin(theme.skills, (s) => stateOf("skill", s))` with: a select checkbox (`onToggleSelect("skill", skill)`, checked from `selected.has("skill:"+name)`), the skill label as a button (`onOpenSkill`), a status badge derived from `stateOf`, frequency (`jobCount`), and covered/gap marker. Compact the tail: show first 12 skills, the rest behind a "Show N more" button; show first 30 themes, rest behind "Show N more themes". Use existing icon set (`lucide-react`: `Check`, `AlertTriangle`, `ChevronRight`, `Star`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/match-gap/RankedList.test.tsx`
Expected: PASS. Then `cd web && npx tsc --noEmit`.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/match-gap/RankedList.tsx web/src/features/match-gap/RankedList.test.tsx
git commit -m "feat(match-gap): theme-row ranked list with status badges and compaction"
```

---

### Task 8: Tabbed workspace shell; delete WordCloud + StatTables

**Files:**
- Rewrite: `web/src/features/match-gap/MatchGapContainer.tsx`
- Delete: `web/src/features/match-gap/WordCloud.tsx`, `web/src/features/match-gap/WordCloud.test.tsx`, `web/src/features/match-gap/StatTables.tsx`
- Test: `web/src/features/match-gap/MatchGapContainer.test.tsx`

**Interfaces:**
- Consumes: `useMatchGap`, `deriveView` (`themeRows`), `useSuggestionStatus`, `RankedList`, `Filters`, `RefreshClustersButton`, shadcn `Tabs`.
- Produces: container holds `filters`, `selected: Set<string>`, `activeTab` state; renders `Tabs` `Map`|`Ranked list` with `RankedList` under the list tab and a `Map` placeholder until Task 9. (Modal/tray wired in Phase 4 — until then `onOpenSkill` is a no-op stub and selection is inert.)

- [ ] **Step 1: Write the failing test**

Rewrite `MatchGapContainer.test.tsx` to mock `useMatchGap`/`useSuggestionStatus` and assert: both tabs render, the "Ranked list" tab shows theme rows, and **no** "By company"/"By position"/word-cloud text appears.

```tsx
it("renders tabbed workspace without by-company/by-position tables", async () => {
  // mock useMatchGap → payload with one theme; render container
  expect(screen.getByRole("tab", { name: /Ranked list/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /Map/ })).toBeInTheDocument();
  expect(screen.queryByText("By company")).not.toBeInTheDocument();
  expect(screen.queryByText("Demand landscape")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/MatchGapContainer.test.tsx`
Expected: FAIL (tabs absent, StatTables present).

- [ ] **Step 3: Write minimal implementation**

Rewrite `MatchGapContainer.tsx`: keep loading/error/empty branches; replace the body with `MetricRow` + a `Tabs` (`defaultValue="list"`). Filter bar + `RefreshClustersButton` stay above the tabs. Tab `list` → `<RankedList themeRows={view.themeRows} stateOf={stateOf} selected={selected} onToggleSelect={...} onOpenSkill={() => {}} />`. Tab `map` → `<div data-testid="skill-map-placeholder" />`. Delete the `WordCloud`, `StatTables` imports/usages and the "Theme learning paths" section. Remove the files.

```bash
git rm web/src/features/match-gap/WordCloud.tsx web/src/features/match-gap/WordCloud.test.tsx web/src/features/match-gap/StatTables.tsx
```

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npx vitest run src/features/match-gap/ && npx tsc --noEmit`
Expected: PASS (no dangling imports of deleted files).

- [ ] **Step 5: Commit**

```bash
git add -A web/src/features/match-gap/
git commit -m "feat(match-gap): tabbed Map/List workspace; drop word cloud and stat tables"
```

---

## Phase 3 — Constellation Map

### Task 9: d3 deps + pure constellation layout

**Files:**
- Modify: `web/package.json`
- Create: `web/src/features/match-gap/skill-map-layout.ts`
- Test: `web/src/features/match-gap/skill-map-layout.test.ts`

**Interfaces:**
- Produces:
  - `interface MapNode { id: string; kind: "theme" | "skill"; label: string; radius: number; color: "gap" | "covered" | "hub"; x: number; y: number; }`
  - `interface MapLink { source: string; target: string; }`
  - `function buildGraph(themeRows: ThemeRow[], expanded: Set<string>, stateOf?): { nodes: MapNode[]; links: MapLink[] }` — hubs always; skills + hub→skill links only for expanded themes; radius from `sqrt(score)`.
  - `function runLayout(nodes: MapNode[], links: MapLink[], ticks = 120): MapNode[]` — runs a `d3-force` simulation **synchronously** (`simulation.stop()`, fixed `tick()` count, seeded by index) and returns nodes with final `x`/`y`. Deterministic given the same input.

- [ ] **Step 1: Write the failing test**

Create `skill-map-layout.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildGraph, runLayout } from "./skill-map-layout";
import type { ThemeRow } from "./aggregate";

const themeRows: ThemeRow[] = [
  { id: "backend", label: "Backend", score: 16, gapCount: 1, skills: [
    { skill: "Python", themeId: "backend", covered: false, score: 9, jobCount: 3, must: 3, nice: 0, tech: 0, members: {} },
  ] },
  { id: "cloud", label: "Cloud", score: 4, gapCount: 0, skills: [] },
];

it("shows only hubs when nothing is expanded", () => {
  const { nodes, links } = buildGraph(themeRows, new Set());
  expect(nodes.map((n) => n.id).sort()).toEqual(["cloud", "backend"].sort());
  expect(links).toEqual([]);
});

it("injects skill nodes + hub links for an expanded theme", () => {
  const { nodes, links } = buildGraph(themeRows, new Set(["backend"]));
  expect(nodes.find((n) => n.id === "skill:Python")?.color).toBe("gap");
  expect(links).toContainEqual({ source: "backend", target: "skill:Python" });
});

it("runLayout is deterministic and assigns finite coordinates", () => {
  const g = buildGraph(themeRows, new Set(["backend"]));
  const a = runLayout(g.nodes, g.links);
  const b = runLayout(g.nodes.map((n) => ({ ...n })), g.links);
  expect(a.every((n) => Number.isFinite(n.x) && Number.isFinite(n.y))).toBe(true);
  expect(a.map((n) => [Math.round(n.x), Math.round(n.y)]))
    .toEqual(b.map((n) => [Math.round(n.x), Math.round(n.y)]));
});
```

- [ ] **Step 2: Add deps, run test to verify it fails**

Run:
```bash
cd web && npm install d3-force d3-zoom && npm install -D @types/d3-force @types/d3-zoom
npx vitest run src/features/match-gap/skill-map-layout.test.ts
```
Expected: install succeeds; test FAILS (module missing).

- [ ] **Step 3: Write minimal implementation**

Create `skill-map-layout.ts` using `forceSimulation`, `forceLink`, `forceManyBody`, `forceCenter`, `forceCollide` from `d3-force`. Seed each node `x = cos(i)*30`, `y = sin(i)*30` (deterministic, no `Math.random`); `simulation.stop()`; loop `ticks` times calling `simulation.tick()`; return nodes. `buildGraph` maps `ThemeRow`→hub `MapNode` (`color:"hub"`, `radius = 6 + sqrt(score)`), and for each expanded theme appends skill nodes (`id: "skill:"+skill`, `color: covered ? "covered" : "gap"`, `radius = 4 + sqrt(score)`) + a `{source: themeId, target: "skill:"+skill}` link.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/match-gap/skill-map-layout.test.ts && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/package.json web/package-lock.json web/src/features/match-gap/skill-map-layout.ts web/src/features/match-gap/skill-map-layout.test.ts
git commit -m "feat(match-gap): deterministic d3-force constellation layout"
```

---

### Task 10: `SkillMap` — SVG render, zoom, expand/collapse, select/open

**Files:**
- Create: `web/src/features/match-gap/SkillMap.tsx`
- Test: `web/src/features/match-gap/SkillMap.test.tsx`
- Modify: `web/src/features/match-gap/MatchGapContainer.tsx` (swap the Map placeholder for `SkillMap`)

**Interfaces:**
- Consumes: `buildGraph`/`runLayout` (Task 9), `ThemeRow`, `stateOf`, the `selected`/`onToggleSelect`/`onOpenSkill` props from the container.
- Produces: `SkillMap({ themeRows, stateOf, selected, onToggleSelect, onOpenSkill })` — SVG of nodes/links; clicking a hub toggles its id in local `expanded`; clicking a skill node calls `onOpenSkill`; a small "select" affordance per skill node calls `onToggleSelect`. Gold ring class when `stateOf("skill", name) === "ready"`. `d3-zoom` on the `<svg>` updates a transform on the root `<g>`.

- [ ] **Step 1: Write the failing test**

Create `SkillMap.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SkillMap } from "./SkillMap";
import type { ThemeRow } from "./aggregate";

const themeRows: ThemeRow[] = [
  { id: "backend", label: "Backend", score: 16, gapCount: 1, skills: [
    { skill: "Python", themeId: "backend", covered: false, score: 9, jobCount: 3, must: 3, nice: 0, tech: 0, members: {} },
  ] },
];

it("expands a hub on click and opens a skill node", () => {
  const onOpenSkill = vi.fn();
  render(<SkillMap themeRows={themeRows} stateOf={() => "ready"}
    selected={new Set()} onToggleSelect={vi.fn()} onOpenSkill={onOpenSkill} />);
  expect(screen.queryByText("Python")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("Backend"));
  fireEvent.click(screen.getByText("Python"));
  expect(onOpenSkill).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/SkillMap.test.tsx`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

Create `SkillMap.tsx`. Local `expanded` state; `useMemo` over `buildGraph` + `runLayout` keyed on `themeRows`+`expanded`. Render `<svg>` with a `<g>` holding `<line>` per link and a `<g>` per node (`<circle>` + `<text>` label). Hub `<text>` click toggles `expanded`. Skill node `<text>`/`<circle>` click → `onOpenSkill(find the SkillRow)`. Add a tiny select dot (`<circle role="button" aria-label={"select "+name}>`) → `onToggleSelect("skill", name)`. Apply `className="ring"` (gold) when ready. Wire `d3-zoom`: `useEffect` attaches `zoom().on("zoom", (e) => setTransform(e.transform))` to the svg ref; apply `transform={String(transform)}` on the root `<g>`. Guard against zero nodes (empty/`clustersStale` → render a single "Unthemed" hub from any `themeId === null` skills, or an empty-state hint).

- [ ] **Step 4: Run tests + wire into container**

Replace the `skill-map-placeholder` div in `MatchGapContainer.tsx` with `<SkillMap ... />` (same props it already threads to `RankedList`).
Run: `cd web && npx vitest run src/features/match-gap/ && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/match-gap/SkillMap.tsx web/src/features/match-gap/SkillMap.test.tsx web/src/features/match-gap/MatchGapContainer.tsx
git commit -m "feat(match-gap): d3-force constellation Map with expand/collapse, zoom, select"
```

---

## Phase 4 — Modal + selection tray + batch

### Task 11: `SkillModal` — job-modal-style detail, replaces `SkillDrawer`

**Files:**
- Create: `web/src/features/match-gap/SkillModal.tsx`
- Modify: `web/src/features/match-gap/MatchGapContainer.tsx` (open `SkillModal` from `onOpenSkill`)
- Delete: `web/src/features/match-gap/SkillDrawer.tsx`, `web/src/features/match-gap/SkillDrawer.test.tsx`
- Test: `web/src/features/match-gap/SkillModal.test.tsx`

**Interfaces:**
- Consumes: `SkillRow`, `useSuggestion`/`useGenerateSuggestion` (existing), `SuggestionPanel` (reused), `Dialog`/`Tabs` (shadcn), `view.jobsForSkill` from `deriveView`.
- Produces: `SkillModal({ skill: SkillRow | null, jobs: Job[], onClose })` — `Dialog` (`max-w-6xl`) masthead (name, theme + gap/covered + status pills, demand/role counts), left evidence rail (member phrasings+freq from `skill.members`, source mix `must/nice/tech`), right `Tabs` `Suggestion`|`Roles`.

- [ ] **Step 1: Write the failing test**

Create `SkillModal.test.tsx`: render with a `SkillRow` carrying `members: { Python: 2, py: 1 }` and 1 job; assert masthead name, that member phrasings + counts render, and that the `Suggestion` tab renders the empty-advice "How to close this gap" CTA (mock `useSuggestion` → `{ data: { suggestion: null }, ... }`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/SkillModal.test.tsx`
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

Create `SkillModal.tsx` mirroring `JobModal.tsx`'s structure (masthead + two-pane + `Tabs`). Left rail lists `Object.entries(skill.members)` sorted by count desc with the frequency, plus the source mix. Right `Tabs`: `Suggestion` renders `<SuggestionPanel ...>` wired to `useSuggestion("skill", skill.skill, open)` + `useGenerateSuggestion` (lifted from the old `SkillDrawer`); `Roles` renders the demanding-jobs list (the markup from `SkillDrawer`'s "Demanding roles" section). Delete `SkillDrawer.tsx` + test:

```bash
git rm web/src/features/match-gap/SkillDrawer.tsx web/src/features/match-gap/SkillDrawer.test.tsx
```

In `MatchGapContainer.tsx`, add `const [openSkill, setOpenSkill] = useState<SkillRow | null>(null)`, pass `onOpenSkill={setOpenSkill}` to both `RankedList` and `SkillMap`, and render `<SkillModal skill={openSkill} jobs={openSkill ? view.jobsForSkill(openSkill.skill) : []} onClose={() => setOpenSkill(null)} />`.

- [ ] **Step 4: Run tests + typecheck**

Run: `cd web && npx vitest run src/features/match-gap/ && npx tsc --noEmit`
Expected: PASS (no dangling `SkillDrawer` imports).

- [ ] **Step 5: Commit**

```bash
git add -A web/src/features/match-gap/
git commit -m "feat(match-gap): large skill detail modal replacing the sheet drawer"
```

---

### Task 12: Selection tray + batch generation wiring

**Files:**
- Create: `web/src/features/match-gap/use-batch-suggestions.ts`
- Create: `web/src/features/match-gap/SelectionTray.tsx`
- Modify: `web/src/features/match-gap/MatchGapContainer.tsx` (render tray; basket already in `selected`)
- Test: `web/src/features/match-gap/use-batch-suggestions.test.tsx`, `web/src/features/match-gap/SelectionTray.test.tsx`

**Interfaces:**
- Consumes: `POST /api/suggestions/generate-batch` (Task 4), `useLaunchRun`/`watchRun` machinery, `useRunStore`, `useSuggestionStatus.stateOf`, `selected: Set<string>` from the container.
- Produces:
  - `useBatchSuggestions() -> { generateAll: (targets: {kind, key}[]) => Promise<void>, generating: boolean }` — POSTs the batch, registers each returned run in the run store + `watchRun`, invalidates `["suggestion-status"]` on completion.
  - `SelectionTray({ open, targets, stateOf, onClear, onRemove, onGenerateAll, generating })`.

- [ ] **Step 1: Write the failing test**

Create `use-batch-suggestions.test.tsx`: mock `api.POST("/api/suggestions/generate-batch")` → `{ runs: [{kind:"skill",key:"Python",runId:"r1"}], notFound: [] }` and `watchRun`; call `generateAll([{kind:"skill",key:"Python"}])`; assert the run store has `r1` with `kind:"suggestion"` and that `watchRun` was called with `"r1"`.

Create `SelectionTray.test.tsx`: render with two targets, `stateOf` returning `"researching"` for one; assert both labels + a "Generate all" button render; click it → `onGenerateAll` called with both targets; click a remove control → `onRemove` called.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/features/match-gap/use-batch-suggestions.test.tsx src/features/match-gap/SelectionTray.test.tsx`
Expected: FAIL (modules missing).

- [ ] **Step 3: Write minimal implementation**

Create `use-batch-suggestions.ts`:

```ts
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "@/lib/api/client";
import { watchRun } from "@/lib/runs/sse";
import { useRunStore } from "@/lib/runs/store";
import type { SuggestionKind } from "./use-suggestion";

type Target = { kind: SuggestionKind; key: string };
type BatchOut = { runs: { kind: string; key: string; runId: string }[]; notFound: Target[] };

export function useBatchSuggestions() {
  const qc = useQueryClient();
  const [generating, setGenerating] = useState(false);
  const generateAll = async (targets: Target[]) => {
    if (targets.length === 0) return;
    setGenerating(true);
    try {
      const out = (await unwrap(
        api.POST("/api/suggestions/generate-batch", { body: { items: targets } }),
      )) as BatchOut;
      for (const run of out.runs) {
        useRunStore.getState().upsert({
          runId: run.runId, kind: "suggestion", status: "running",
          percent: 0, phase: "", current: 0, total: 0, etaText: null,
          result: { kind: run.kind, key: run.key },
        });
        watchRun(run.runId, "suggestion", () => {
          qc.invalidateQueries({ queryKey: ["suggestion-status"] });
        });
      }
    } finally {
      setGenerating(false);
    }
  };
  return { generateAll, generating };
}
```

Create `SelectionTray.tsx`: a fixed right-side panel (visible when `open`), listing each target with its `stateOf` icon (○/⏱/◐/★/⚠), a remove button (`onRemove(target)`), a "Clear" and a primary "⚡ Generate all" (`onGenerateAll(targets)`, disabled when `generating`). Use existing `Button` + `lucide-react` icons.

In `MatchGapContainer.tsx`: derive `targets` from `selected` (`"skill:Python"` → `{kind:"skill", key:"Python"}`); render `<SelectionTray open={selected.size > 0} targets={targets} stateOf={stateOf} onRemove={...} onClear={() => setSelected(new Set())} onGenerateAll={(t) => generateAll(t)} generating={generating} />` using `useBatchSuggestions()`.

- [ ] **Step 4: Run tests + full suite + typecheck**

Run: `cd web && npx vitest run src/features/match-gap/ && npx tsc --noEmit`
Expected: PASS.
Run backend once more: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A web/src/features/match-gap/
git commit -m "feat(match-gap): multi-select tray with async batch suggestion generation"
```

---

## Self-Review

**Spec coverage:**
- Point 1 (interactive plot) → Tasks 9–10 (d3-force constellation, theme hubs → skill leaves, expand/collapse, zoom, click).
- Point 2 (big modal) → Task 11 (`SkillModal`, `max-w-6xl`, job-modal idiom, replaces `Sheet`).
- Point 3 (density, cluster-first, members+frequencies) → Task 1 (members/frequencies) + Task 7 (theme rows, expand, compaction).
- Point 4 (drop by-company/by-position; prioritize clusters) → Task 8 (delete `StatTables`/`WordCloud`; theme-first list + map).
- Point 5 (suggestion status tracking + prioritized layout) → Task 3 (`/status`) + Task 6 (`stateOf`) + Task 5 (`sortSkillsWithin`) + badges/ring in Tasks 7, 10.
- Point 6 (generalized-skill suggestions; skill+theme both) → Task 1 taxonomy; existing `kind` preserved; modal targets `kind="skill"`.
- Point 7 (multi-select async batch) → Task 4 (batch endpoint, concurrency cap) + Task 12 (tray + `useBatchSuggestions`).

**Placeholder scan:** No "TBD"/"handle edge cases"/"similar to". The `clustersStale` degenerate case is given concrete handling in Task 10 Step 3. The one judgement call left to the implementer (rail/tab markup reuse from `JobModal`/`SkillDrawer`) cites the exact source components.

**Type consistency:** `SkillRow.members: Record<string,number>` (Task 5) matches `SkillNodeOut.members: dict[str,int]` (Task 2) and the layout/modal consumers (Tasks 9–11). `SuggestionState` is defined once in `aggregate.ts` (Task 5) and consumed in Tasks 6/7/10/12. `stateOf(kind, key)` signature is identical across Tasks 6, 7, 10, 12. Batch response `runs[].runId` / `notFound[]` (Task 4) matches `useBatchSuggestions` (Task 12). `RunRecord.result` is used optionally and is already part of the store type.

---

## Execution Handoff

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.
