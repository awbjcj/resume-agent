# Match/Gap Skill-Intelligence Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat read-only gap table with a skill-demand intelligence dashboard: a weighted demand graph sliceable by company/position, a word cloud + ranked list, skill→jobs drill-down, and LLM dedup+theming run off the read path.

**Architecture:** A new pure core `build_demand_graph()` returns the whole demand graph (jobs, deduped skills with coverage, weighted edges, themes) in one GET; the browser does all filtering/aggregation. LLM synonym-dedup + thematic clustering run in a background Run+SSE that persists a cluster map; the GET only reads it. The legacy `match_gap()` and CLI are left untouched.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, agno (LLM agents), Pydantic v2 (`CamelModel` camelCase wire). Frontend: React 19, TanStack Query, shadcn (sheet/select/switch/toggle-group), MSW + vitest, Playwright.

## Global Constraints

- **Test command (backend, offline):** `.venv/Scripts/python.exe -m pytest` — no API key, no network. All LLM agents and the browser are faked.
- **Test command (frontend):** `cd web && npm run test:run` (vitest).
- **Lint:** `ruff check` (backend), `cd web && npm run lint` (frontend).
- **Wire format is camelCase.** Python stays snake_case; `CamelModel` (`api/schemas/base.py`) sets `alias_generator=to_camel` + `from_attributes=True`, so `Schema.model_validate(dataclass_or_row)` projects snake_case attrs onto camelCase fields.
- **No business logic in routers.** Routers call `services/` / `tracking/` functions only.
- **Long ops = Run + SSE.** Any LLM/network work returns `202` + a run record via `mgr.submit(kind, work)`; the worker opens its OWN session bound to `request.app.state.engine` (never the request session).
- **OpenAPI is generated, drift-gated.** After any schema change run `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` must stay green.
- **Skill weights:** `must_have`=3, `nice_to_have`=2, `tech_stack`=1. Defined once in `aggregate.ts`; the backend emits raw source edges and has no weight constant.
- **Cluster map path:** `data/profile/cluster_map.json`.
- **Do NOT modify** `match_gap()`, `MatchGapReport`, `GapRow`, `cli.py`, or `tests/test_tracking_match_gap.py` / `tests/test_cli_match_gap.py` — the CLI depends on the legacy shape. New work is additive.

---

## Engineering-review corrections (authoritative)

The task order remains useful, but the following corrections supersede any later
snippet that conflicts with them:

1. **Edge uniqueness:** emit at most one edge per
   `(job_id, canonical_skill, source)`. Duplicate criteria values must not inflate
   scores. Make `source` a `Literal["must", "nice", "tech"]` in domain/API types.
2. **Cluster-map boundary:** validate loaded JSON and normalize strings. Missing or
   malformed files degrade to an empty/stale map; malformed LLM output fails the
   refresh without replacing the last good file. Theme output must be an exact
   partition of canonical skills. Use a unique temporary file and atomic replace,
   and serialize/coalesce concurrent refreshes.
3. **No pass-before-change tasks:** fold Task 3's cluster-application tests into
   the implementation task that first consumes `ClusterMap`; do not create an
   empty test-only commit. Likewise, land a route and its behavior test together.
4. **Thin projection:** `MatchGapOut.model_validate(graph)` is the projection.
   Do not manually reconstruct every nested DTO in the router.
5. **One aggregation primitive:** implement a pure `summarize(edges)` helper and
   use it for the main view and every facet bucket. Company/position rows must
   score only their own edges; the draft Task 10 implementation incorrectly
   reuses global `SkillRow.score` values.
6. **Both selection grains:** `DerivedView` exposes skill and theme job lookups.
   Selection state is a discriminated union (`skill` or `theme`), not a nullable
   skill string. A theme opens the union of jobs for its member skills and is the
   integration point required by Spec B.
7. **Production UI states:** explicitly handle request error, no target jobs, and
   no results under the current filters. Label both selects and the toggle group;
   expose gap/covered status with text for assistive technology; make the sheet
   scrollable and responsive. Refresh busy state resets in `finally` and launch
   failure is visible.
8. **Visual hierarchy:** follow the existing teal grid-backed analytical house
   style. Use one editorial analysis surface with dividers, with the ranked list
   primary and cloud secondary; avoid a generic grid of independently rounded
   cards. Respect reduced motion.

Add regression tests for every item above, including a facet-local score that
differs from the global score and an axe check of the populated dashboard.

---

## File Structure

| Path                                                                                                                                          | Responsibility                                                                                                                                                                                                           |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/resume_tailor_harness/tracking/match_gap.py`                                                                                                      | **Add** demand-graph dataclasses + `build_demand_graph()` + `collect_target_skill_tokens()` + `_skills_by_source()`. Reuse existing `_target_jobs`, `profile_skill_tokens`, `normalize_skill`. Legacy `match_gap` stays. |
| `src/resume_tailor_harness/taxonomy/clusters.py`                                                                                                       | **New.** `ClusterMap` dataclass + `load_cluster_map` / `save_cluster_map` / `merge_cluster_map`.                                                                                                                         |
| `src/resume_tailor_harness/tracking/canonicalize.py`                                                                                                   | **Add** `build_skill_themer()` (thematic-grouping agent) next to the existing `build_skill_canonicalizer()`.                                                                                                             |
| `src/resume_tailor_harness/services/match_gap.py`                                                                                                      | **New.** `refresh_clusters()` use-case: collect tokens → dedup → theme → persist.                                                                                                                                        |
| `src/resume_tailor_harness/api/schemas/match_gap.py`                                                                                                   | **Rewrite.** `JobLiteOut`, `SkillNodeOut`, `DemandEdgeOut`, `ThemeOut`, `MatchGapOut`.                                                                                                                                   |
| `src/resume_tailor_harness/api/routers/match_gap.py`                                                                                                   | **Rewrite GET** (rich projection) + **add POST** `/match-gap/refresh-clusters` Run endpoint.                                                                                                                             |
| `web/src/features/match-gap/aggregate.ts`                                                                                                     | **New.** Pure `deriveView(payload, filters)` — all weighting/filtering/rollups.                                                                                                                                          |
| `web/src/features/match-gap/use-match-gap.ts`                                                                                                 | **Rewrite.** Richer type + `useRefreshClusters()` hook.                                                                                                                                                                  |
| `web/src/features/match-gap/Filters.tsx`, `WordCloud.tsx`, `RankedList.tsx`, `SkillDrawer.tsx`, `StatTables.tsx`, `RefreshClustersButton.tsx` | **New** presentational components.                                                                                                                                                                                       |
| `web/src/features/match-gap/MatchGapContainer.tsx`                                                                                            | **Rewrite** to wire payload → `deriveView` → components.                                                                                                                                                                 |

---

## Task 1: Demand-graph core (`build_demand_graph`)

**Files:**

- Modify: `src/resume_tailor_harness/tracking/match_gap.py`
- Test: `tests/test_demand_graph.py` (new)

**Interfaces:**

- Consumes: existing `_target_jobs(session)`, `profile_skill_tokens(facts)`, `normalize_skill(str)`.
- Produces:
  - `@dataclass JobLite(id:int, company:str|None, title:str|None, seniority:str|None)`
  - `@dataclass DemandEdge(job_id:int, skill:str, source:str)`
  - `@dataclass SkillNode(skill:str, theme_id:str|None, covered:bool)`
  - `@dataclass ThemeNode(id:str, label:str)`
  - `@dataclass DemandGraph(target_total:int, clusters_stale:bool, jobs:list[JobLite], skills:list[SkillNode], edges:list[DemandEdge], themes:list[ThemeNode])`
  - `collect_target_skill_tokens(session) -> set[str]`
  - `build_demand_graph(session, facts, cluster_map=None) -> DemandGraph` (cluster_map applied in Task 3; here pass-through identity)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_demand_graph.py
from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.models.profile import Contact, ProfileFacts, Skill
from resume_tailor_harness.tracking.match_gap import (
    DemandGraph,
    build_demand_graph,
    collect_target_skill_tokens,
)
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _job(session, *, status=JobStatus.shortlisted.value, company="C", title="T",
         seniority=None, must=None, nice=None, tech=None):
    return save_job(session, Job(
        source="manual", company=company, title=title, status=status,
        criteria_json={
            "must_have_skills": must or [],
            "nice_to_have_skills": nice or [],
            "tech_stack": tech or [],
            "seniority": seniority,
        },
    ))


def _facts(skills):
    return ProfileFacts(contact=Contact(name="A"), skills=skills)


def test_demand_graph_builds_edges_per_source():
    with _session() as s:
        j = _job(s, must=["Kubernetes"], nice=["Go"], tech=["Linux"])
        graph = build_demand_graph(s, _facts({}))
        assert graph.target_total == 1
        sources = {(e.skill, e.source) for e in graph.edges}
        assert sources == {("Kubernetes", "must"), ("Go", "nice"), ("Linux", "tech")}
        assert j.id is not None
        assert {e.job_id for e in graph.edges} == {j.id}


def test_demand_graph_marks_covered_skills():
    with _session() as s:
        _job(s, must=["Kubernetes", "Python"])
        graph = build_demand_graph(s, _facts({"lang": [Skill(name="Python")]}))
        covered = {n.skill: n.covered for n in graph.skills}
        assert covered == {"Kubernetes": False, "Python": True}


def test_demand_graph_jobs_carry_facets():
    with _session() as s:
        _job(s, company="Stripe", title="Senior Backend", seniority="senior", must=["Go"])
        graph = build_demand_graph(s, _facts({}))
        job = graph.jobs[0]
        assert (job.company, job.title, job.seniority) == ("Stripe", "Senior Backend", "senior")


def test_demand_graph_dedupes_skill_nodes_across_jobs():
    with _session() as s:
        _job(s, must=["Kubernetes"])
        _job(s, must=["Kubernetes"], nice=["Kubernetes"])
        graph = build_demand_graph(s, _facts({}))
        assert [n.skill for n in graph.skills].count("Kubernetes") == 1
        # one edge per job*source
        k8s_edges = [e for e in graph.edges if e.skill == "Kubernetes"]
        assert len(k8s_edges) == 3


def test_demand_graph_dedupes_repeated_values_within_one_source():
    with _session() as s:
        _job(s, must=["Kubernetes", "kubernetes", "Kubernetes"])
        graph = build_demand_graph(s, _facts({}))
        assert [(e.skill, e.source) for e in graph.edges] == [("Kubernetes", "must")]


def test_demand_graph_empty_db():
    with _session() as s:
        graph = build_demand_graph(s, _facts({}))
        assert graph == DemandGraph(
            target_total=0, clusters_stale=False, jobs=[], skills=[], edges=[], themes=[]
        )


def test_collect_target_skill_tokens_unions_all_sources():
    with _session() as s:
        _job(s, must=["Kubernetes"], nice=["Go"], tech=["Linux"])
        assert collect_target_skill_tokens(s) == {"kubernetes", "go", "linux"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_demand_graph.py -v`
Expected: FAIL — `ImportError: cannot import name 'DemandGraph'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_tailor_harness/tracking/match_gap.py` (keep everything already there):

```python
_SOURCE_KEYS = (
    ("must", "must_have_skills"),
    ("nice", "nice_to_have_skills"),
    ("tech", "tech_stack"),
)


@dataclass
class JobLite:
    id: int
    company: str | None
    title: str | None
    seniority: str | None


@dataclass
class DemandEdge:
    job_id: int
    skill: str  # canonical display
    source: str  # "must" | "nice" | "tech"


@dataclass
class SkillNode:
    skill: str  # canonical display
    theme_id: str | None
    covered: bool


@dataclass
class ThemeNode:
    id: str
    label: str


@dataclass
class DemandGraph:
    target_total: int
    clusters_stale: bool
    jobs: list[JobLite]
    skills: list[SkillNode]
    edges: list[DemandEdge]
    themes: list[ThemeNode]


def _skill_list(job: Job, key: str) -> list[str]:
    raw = (job.criteria_json or {}).get(key) or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple, set)):
        return []
    return [str(s) for s in raw if str(s).strip()]


def _skills_by_source(job: Job) -> list[tuple[str, str, str]]:
    """(source, token, display) for every skill on a job, across all 3 lists."""
    out: list[tuple[str, str, str]] = []
    for source, key in _SOURCE_KEYS:
        for display in _skill_list(job, key):
            token = normalize_skill(display)
            if token:
                out.append((source, token, display))
    return out


def _job_seniority(job: Job) -> str | None:
    value = (job.criteria_json or {}).get("seniority")
    return str(value) if value else None


def collect_target_skill_tokens(session: Session) -> set[str]:
    """Normalized token union across all 3 skill lists of every target job."""
    tokens: set[str] = set()
    for job in _target_jobs(session):
        for _source, token, _display in _skills_by_source(job):
            tokens.add(token)
    return tokens


def build_demand_graph(
    session: Session,
    facts: ProfileFacts,
    cluster_map: "ClusterMap | None" = None,
) -> DemandGraph:
    """The full demand graph: jobs, deduped skills (with coverage + theme),
    weighted-source edges, and themes. cluster_map applies dedup/theming when
    present; otherwise every token is its own canonical skill with no theme."""
    aliases = cluster_map.aliases if cluster_map else {}
    theme_of = cluster_map.theme_of if cluster_map else {}
    theme_label = cluster_map.theme_label if cluster_map else {}

    profile_tokens = profile_skill_tokens(facts)
    profile_canonical = {aliases.get(t, t) for t in profile_tokens}

    jobs: list[JobLite] = []
    edges: list[DemandEdge] = []
    display_for: dict[str, str] = {}
    canon_seen: list[str] = []
    used_themes: set[str] = set()
    stale = False

    for job in _target_jobs(session):
        if job.id is None:
            continue
        jobs.append(JobLite(job.id, job.company, job.title, _job_seniority(job)))
        seen_edges: set[tuple[str, str]] = set()
        for source, token, display in _skills_by_source(job):
            canon = aliases.get(token, token)
            edge_key = (canon, source)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            if canon not in display_for:
                display_for[canon] = display
                canon_seen.append(canon)
            edges.append(DemandEdge(job.id, display_for[canon], source))

    skills: list[SkillNode] = []
    for canon in canon_seen:
        theme_id = theme_of.get(canon)
        if theme_id is None:
            stale = True
        else:
            used_themes.add(theme_id)
        skills.append(SkillNode(display_for[canon], theme_id, canon in profile_canonical))

    themes = [ThemeNode(tid, theme_label.get(tid, tid)) for tid in sorted(used_themes)]
    return DemandGraph(len(jobs), stale and bool(jobs), jobs, skills, edges, themes)
```

Add `from resume_tailor_harness.taxonomy.clusters import ClusterMap` under a `TYPE_CHECKING` guard at the top (the annotation is a forward ref):

```python
from typing import TYPE_CHECKING, Literal
if TYPE_CHECKING:
    from resume_tailor_harness.taxonomy.clusters import ClusterMap
```

Define `SkillSource = Literal["must", "nice", "tech"]` and use it for
`DemandEdge.source` and `_SOURCE_KEYS`; do not leave the source field as an
unchecked `str`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_demand_graph.py tests/test_tracking_match_gap.py -v`
Expected: PASS (new graph tests **and** the untouched legacy `match_gap` tests).

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/match_gap.py tests/test_demand_graph.py
git commit -m "feat: add demand-graph core for match-gap dashboard"
```

---

## Task 2: Cluster-map persistence (`taxonomy/clusters.py`)

**Files:**

- Create: `src/resume_tailor_harness/taxonomy/clusters.py`
- Test: `tests/test_taxonomy_clusters.py` (new)

**Interfaces:**

- Produces:
  - `@dataclass ClusterMap(aliases:dict[str,str], theme_of:dict[str,str], theme_label:dict[str,str])` with `@classmethod empty()`
  - `load_cluster_map(path) -> ClusterMap` (missing file → `empty()`)
  - `save_cluster_map(cmap, path) -> None` (atomic write, sorted keys)
  - `merge_cluster_map(existing, new) -> ClusterMap` (monotonic — existing wins, like `merge_aliases`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_taxonomy_clusters.py
from resume_tailor_harness.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    merge_cluster_map,
    save_cluster_map,
)


def test_load_missing_is_empty(tmp_path):
    cmap = load_cluster_map(tmp_path / "nope.json")
    assert cmap == ClusterMap.empty()


def test_load_malformed_is_empty(tmp_path):
    path = tmp_path / "cluster_map.json"
    path.write_text("{broken", encoding="utf-8")
    assert load_cluster_map(path) == ClusterMap.empty()


def test_save_then_load_roundtrips(tmp_path):
    path = tmp_path / "cluster_map.json"
    cmap = ClusterMap(
        aliases={"k8s": "kubernetes"},
        theme_of={"kubernetes": "t1"},
        theme_label={"t1": "Cloud/Infra"},
    )
    save_cluster_map(cmap, path)
    assert load_cluster_map(path) == cmap


def test_merge_is_monotonic_existing_wins():
    existing = ClusterMap(
        aliases={"k8s": "kubernetes"}, theme_of={"kubernetes": "t1"}, theme_label={"t1": "Infra"}
    )
    new = ClusterMap(
        aliases={"k8s": "k8s", "kube": "kubernetes"},
        theme_of={"kubernetes": "t2", "react": "t3"},
        theme_label={"t1": "RENAMED", "t3": "Frontend"},
    )
    merged = merge_cluster_map(existing, new)
    assert merged.aliases == {"k8s": "kubernetes", "kube": "kubernetes"}
    assert merged.theme_of == {"kubernetes": "t1", "react": "t3"}
    assert merged.theme_label == {"t1": "Infra", "t3": "Frontend"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_clusters.py -v`
Expected: FAIL — `ModuleNotFoundError: ...taxonomy.clusters`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/taxonomy/clusters.py
"""Persisted skill cluster map: synonym aliases + thematic grouping.

Extends the flat alias-map idea in taxonomy/skills.py. Merges are monotonic
(existing canonical/theme choices win) so the dashboard is stable across refreshes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


@dataclass
class ClusterMap:
    aliases: dict[str, str] = field(default_factory=dict)       # token -> canonical token
    theme_of: dict[str, str] = field(default_factory=dict)      # canonical token -> theme id
    theme_label: dict[str, str] = field(default_factory=dict)   # theme id -> display label

    @classmethod
    def empty(cls) -> "ClusterMap":
        return cls()


def load_cluster_map(path: str | Path) -> ClusterMap:
    p = Path(path)
    if not p.exists():
        return ClusterMap.empty()
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return ClusterMap.empty()
    if not isinstance(data, dict):
        return ClusterMap.empty()

    def string_map(value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            key.strip(): item.strip()
            for key, item in value.items()
            if isinstance(key, str) and isinstance(item, str) and key.strip() and item.strip()
        }

    return ClusterMap(
        aliases=string_map(data.get("aliases")),
        theme_of=string_map(data.get("theme_of")),
        theme_label=string_map(data.get("theme_label")),
    )


def save_cluster_map(cmap: ClusterMap, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "aliases": cmap.aliases,
        "theme_of": cmap.theme_of,
        "theme_label": cmap.theme_label,
    }
    tmp = p.with_name(f".{p.name}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(payload, sort_keys=True, indent=2), "utf-8")
        tmp.replace(p)
    finally:
        tmp.unlink(missing_ok=True)


def _merge(existing: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    merged = dict(new)
    merged.update(existing)  # existing wins
    return merged


def merge_cluster_map(existing: ClusterMap, new: ClusterMap) -> ClusterMap:
    return ClusterMap(
        aliases=_merge(existing.aliases, new.aliases),
        theme_of=_merge(existing.theme_of, new.theme_of),
        theme_label=_merge(existing.theme_label, new.theme_label),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_clusters.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/taxonomy/clusters.py tests/test_taxonomy_clusters.py
git commit -m "feat: add persisted skill cluster map"
```

---

## Task 3: Apply the cluster map in `build_demand_graph` (fold into Task 2)

**Files:**

- Modify: `src/resume_tailor_harness/tracking/match_gap.py` (only the forward-ref import; the body already reads `cluster_map`)
- Test: `tests/test_demand_graph.py` (add cases)

**Interfaces:**

- Consumes: `ClusterMap` (Task 2), `build_demand_graph` (Task 1).
- Produces: no new symbols — verifies dedup/theming/staleness behavior end-to-end.

- [ ] **Step 1: Add the regression tests before wiring `ClusterMap` into the graph**

Append to `tests/test_demand_graph.py`:

```python
from resume_tailor_harness.taxonomy.clusters import ClusterMap
from resume_tailor_harness.tracking.match_gap import ThemeNode


def test_demand_graph_dedupes_via_alias_map():
    with _session() as s:
        _job(s, must=["k8s"])
        _job(s, must=["Kubernetes"])
        cmap = ClusterMap(aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"})
        graph = build_demand_graph(s, _facts({}), cluster_map=cmap)
        # both jobs collapse onto one canonical skill node
        assert len(graph.skills) == 1
        assert len([e for e in graph.edges if e.source == "must"]) == 2


def test_demand_graph_alias_covers_profile():
    with _session() as s:
        _job(s, must=["k8s"])
        cmap = ClusterMap(aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"})
        graph = build_demand_graph(
            s, _facts({"infra": [Skill(name="Kubernetes")]}), cluster_map=cmap
        )
        assert graph.skills[0].covered is True


def test_demand_graph_assigns_themes_and_clears_stale():
    with _session() as s:
        _job(s, must=["Kubernetes"])
        cmap = ClusterMap(
            aliases={"kubernetes": "kubernetes"},
            theme_of={"kubernetes": "t1"},
            theme_label={"t1": "Cloud/Infra"},
        )
        graph = build_demand_graph(s, _facts({}), cluster_map=cmap)
        assert graph.skills[0].theme_id == "t1"
        assert graph.themes == [ThemeNode("t1", "Cloud/Infra")]
        assert graph.clusters_stale is False


def test_demand_graph_stale_when_skill_unthemed():
    with _session() as s:
        _job(s, must=["Kubernetes", "Rust"])
        cmap = ClusterMap(
            aliases={"kubernetes": "kubernetes", "rust": "rust"},
            theme_of={"kubernetes": "t1"},
            theme_label={"t1": "Cloud/Infra"},
        )
        graph = build_demand_graph(s, _facts({}), cluster_map=cmap)
        assert graph.clusters_stale is True  # Rust has no theme
```

- [ ] **Step 2: Run the tests against the pre-wiring implementation and verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_demand_graph.py -v -k "alias or theme or stale"`
Expected: FAIL before `ClusterMap` is wired. If Task 1 already included that wiring,
run these tests as part of Task 2 and omit a separate Task-3 commit.

- [ ] **Step 3: Confirm implementation**

The Task-1 body already consumes `cluster_map.aliases/theme_of/theme_label`. No code change expected. If a runtime `ClusterMap` reference is needed anywhere outside the annotation, import it normally at module top (no circular import: `clusters.py` imports nothing from `match_gap.py`). Verify with:

Run: `.venv/Scripts/python.exe -c "import resume_tailor_harness.tracking.match_gap"`
Expected: no error.

- [ ] **Step 4: Run full suite slice**

Run: `.venv/Scripts/python.exe -m pytest tests/test_demand_graph.py tests/test_tracking_match_gap.py -v`
Expected: PASS.

- [ ] **Step 5: Commit only if this contains production wiring; otherwise include the tests in Task 2's commit**

```bash
git add tests/test_demand_graph.py src/resume_tailor_harness/tracking/match_gap.py
git commit -m "test: cover cluster-map dedup/theming in demand graph"
```

---

## Task 4: Theming agent (`build_skill_themer`)

**Files:**

- Modify: `src/resume_tailor_harness/tracking/canonicalize.py`
- Test: `tests/test_skill_themer.py` (new)

**Interfaces:**

- Consumes: existing `AgentRunner`, `build_model`, `use_json_mode_for`, `ExtensibleModel`, `Runner`.
- Produces:
  - `Themer = Callable[[set[str]], list[tuple[str, list[str]]]]` (label, member canonical tokens)
  - `class SkillThemes(ExtensibleModel)` with `themes: list[ThemeGroup]`, `ThemeGroup(label:str, skills:list[str])`
  - `themes_to_pairs(themes, tokens) -> list[tuple[str, list[str]]]`
  - `build_skill_themer(agent: Runner | None = None) -> Themer`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_themer.py
import pytest

from resume_tailor_harness.tracking.canonicalize import (
    SkillThemes,
    ThemeGroup,
    build_skill_themer,
    themes_to_pairs,
)


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeRunner:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _FakeResult(self._content)


def test_themes_to_pairs_rejects_unknown_and_missing_members():
    themes = [
        ThemeGroup(label="Cloud/Infra", skills=["kubernetes", "terraform", "ghost"]),
        ThemeGroup(label="", skills=["x"]),
    ]
    with pytest.raises(ValueError):
        themes_to_pairs(themes, {"kubernetes", "terraform"})


def test_themes_to_pairs_requires_exact_partition():
    themes = [ThemeGroup(label="Cloud/Infra", skills=["kubernetes", "terraform"])]
    assert themes_to_pairs(themes, {"kubernetes", "terraform"}) == [
        ("Cloud/Infra", ["kubernetes", "terraform"])
    ]


def test_build_skill_themer_returns_pairs():
    content = SkillThemes(themes=[ThemeGroup(label="Frontend", skills=["react", "vue"])])
    themer = build_skill_themer(_FakeRunner(content))
    assert themer({"react", "vue"}) == [("Frontend", ["react", "vue"])]


def test_build_skill_themer_empty_tokens_skips_call():
    themer = build_skill_themer(_FakeRunner(SkillThemes(themes=[])))
    assert themer(set()) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_themer.py -v`
Expected: FAIL — `ImportError: cannot import name 'SkillThemes'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_tailor_harness/tracking/canonicalize.py`:

```python
from typing import Callable as _Callable  # already have Callable; reuse existing import

_THEME_INSTRUCTIONS = [
    "You group technical skills into broad themes.",
    "Given a JSON array of canonical skill tokens, assign each to a short theme.",
    "Themes are broad families, e.g. 'Cloud/Infra', 'Frontend frameworks', 'Data/ML'.",
    "Every input token must appear in exactly one theme's skills list.",
    "Use 3-8 themes total; prefer fewer, well-known families.",
]


class ThemeGroup(ExtensibleModel):
    label: str = ""
    skills: list[str] = Field(default_factory=list)


class SkillThemes(ExtensibleModel):
    themes: list[ThemeGroup] = Field(default_factory=list)


Themer = Callable[[set[str]], list[tuple[str, list[str]]]]


def themes_to_pairs(
    themes: list[ThemeGroup], tokens: set[str]
) -> list[tuple[str, list[str]]]:
    pairs: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for group in themes:
        label = group.label.strip()
        members = list(dict.fromkeys(group.skills))
        if not label or not members:
            raise ValueError("every theme needs a label and at least one skill")
        unknown = set(members) - tokens
        duplicate = set(members) & seen
        if unknown or duplicate:
            raise ValueError(f"invalid theme partition: unknown={unknown}, duplicate={duplicate}")
        seen.update(members)
        pairs.append((label, members))
    missing = tokens - seen
    if missing:
        raise ValueError(f"themer omitted skills: {sorted(missing)}")
    return pairs


def _default_themer_agent() -> Runner:
    settings = get_settings()
    model = build_model(settings.cheap_model)
    return AgentRunner(
        Agent(
            model=model,
            description="You group skills into broad themes.",
            instructions=_THEME_INSTRUCTIONS,
            output_schema=SkillThemes,
            use_json_mode=use_json_mode_for(model),
        )
    )


def build_skill_themer(agent: Runner | None = None) -> Themer:
    runner = agent or _default_themer_agent()

    def assign(tokens: set[str]) -> list[tuple[str, list[str]]]:
        if not tokens:
            return []
        result = runner.run(json.dumps(sorted(tokens)))
        content = result.content
        themes = content.themes if isinstance(content, SkillThemes) else []
        return themes_to_pairs(themes, tokens)

    return assign
```

(Remove the unused `_Callable` alias line if `Callable` is already imported — it is.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_themer.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/canonicalize.py tests/test_skill_themer.py
git commit -m "feat: add skill theming agent"
```

---

## Task 5: Refresh service (`services/match_gap.py`)

**Files:**

- Create: `src/resume_tailor_harness/services/match_gap.py`
- Test: `tests/test_services_match_gap.py` (new)

**Interfaces:**

- Consumes: `collect_target_skill_tokens` (Task 1), `ClusterMap`/`load_cluster_map`/`save_cluster_map`/`merge_cluster_map` (Task 2), `Canonicalizer` (existing in `tracking/match_gap.py`), `Themer` (Task 4).
- Produces:
  - `slugify_theme(label:str) -> str`
  - `refresh_clusters(session, *, dedup, themer, path, reporter=None) -> dict` returning `{"skills": int, "themes": int}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_match_gap.py
import pytest

from sqlmodel import Session, SQLModel, create_engine

from resume_tailor_harness.services.match_gap import refresh_clusters, slugify_theme
from resume_tailor_harness.taxonomy.clusters import load_cluster_map
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _job(session, must):
    return save_job(session, Job(
        source="manual", company="C", title="T", status=JobStatus.shortlisted.value,
        criteria_json={"must_have_skills": must},
    ))


def test_slugify_theme():
    assert slugify_theme("Cloud / Infra") == "cloud-infra"


def test_refresh_rejects_colliding_theme_ids(tmp_path):
    path = tmp_path / "cluster_map.json"
    with _session() as s:
        _job(s, ["C++", "C#"])
        with pytest.raises(ValueError):
            refresh_clusters(
                s,
                dedup=lambda toks: {t: t for t in toks},
                themer=lambda toks: [("C++", ["c++"]), ("C#", ["c#"])],
                path=path,
            )


def test_refresh_clusters_persists_aliases_and_themes(tmp_path):
    path = tmp_path / "cluster_map.json"
    with _session() as s:
        _job(s, ["k8s", "Kubernetes", "React"])

        def dedup(tokens):
            return {t: ("kubernetes" if t in {"k8s", "kubernetes"} else t) for t in tokens}

        def themer(tokens):
            return [("Cloud/Infra", ["kubernetes"]), ("Frontend", ["react"])]

        result = refresh_clusters(s, dedup=dedup, themer=themer, path=path)

    cmap = load_cluster_map(path)
    assert cmap.aliases["k8s"] == "kubernetes"
    assert cmap.theme_of["kubernetes"] == "cloud-infra"
    assert cmap.theme_label["cloud-infra"] == "Cloud/Infra"
    assert result == {"skills": 2, "themes": 2}


def test_refresh_clusters_merge_is_monotonic(tmp_path):
    path = tmp_path / "cluster_map.json"
    with _session() as s:
        _job(s, ["Kubernetes"])
        refresh_clusters(
            s,
            dedup=lambda toks: {t: t for t in toks},
            themer=lambda toks: [("Infra", ["kubernetes"])],
            path=path,
        )
        # second run proposes a different label; existing must win
        refresh_clusters(
            s,
            dedup=lambda toks: {t: t for t in toks},
            themer=lambda toks: [("RENAMED", ["kubernetes"])],
            path=path,
        )
    cmap = load_cluster_map(path)
    assert cmap.theme_label["infra"] == "Infra"


def test_refresh_rejects_canonicalizer_tokens_outside_input(tmp_path):
    with _session() as s:
        _job(s, ["Kubernetes"])
        with pytest.raises(ValueError, match="outside its input"):
            refresh_clusters(
                s,
                dedup=lambda toks: {"kubernetes": "invented"},
                themer=lambda toks: [("Infra", sorted(toks))],
                path=tmp_path / "cluster_map.json",
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_match_gap.py -v`
Expected: FAIL — `ModuleNotFoundError: ...services.match_gap`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/services/match_gap.py
"""Use-case: refresh the persisted skill cluster map (LLM dedup + theming).

Runs off the read path (a background Run). The dashboard GET only reads the map.
"""

from __future__ import annotations

import re
from pathlib import Path
from threading import Lock

from sqlmodel import Session

from resume_tailor_harness.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    merge_cluster_map,
    save_cluster_map,
)
from resume_tailor_harness.tracking.canonicalize import Themer
from resume_tailor_harness.tracking.match_gap import Canonicalizer, collect_target_skill_tokens

_SLUG = re.compile(r"[^a-z0-9]+")
_CLUSTER_WRITE_LOCK = Lock()


def slugify_theme(label: str) -> str:
    return _SLUG.sub("-", label.lower()).strip("-")


def refresh_clusters(
    session: Session,
    *,
    dedup: Canonicalizer,
    themer: Themer,
    path: str | Path,
    reporter=None,
) -> dict:
    tokens = collect_target_skill_tokens(session)
    proposed = dedup(tokens) if tokens else {}
    aliases = {token: proposed.get(token, token) for token in tokens}
    invalid = {
        token: canonical
        for token, canonical in aliases.items()
        if not isinstance(canonical, str) or canonical not in tokens
    }
    if invalid:
        raise ValueError(f"canonicalizer returned tokens outside its input: {invalid}")
    canonical = sorted({aliases.get(t, t) for t in tokens})

    theme_of: dict[str, str] = {}
    theme_label: dict[str, str] = {}
    for label, members in themer(set(canonical)):
        tid = slugify_theme(label)
        if not tid:
            raise ValueError(f"theme label cannot produce an id: {label!r}")
        if tid in theme_label and theme_label[tid] != label:
            raise ValueError(f"theme id collision for {label!r}: {tid!r}")
        theme_label[tid] = label
        for token in members:
            theme_of.setdefault(token, tid)

    new_map = ClusterMap(aliases=aliases, theme_of=theme_of, theme_label=theme_label)
    with _CLUSTER_WRITE_LOCK:
        merged = merge_cluster_map(load_cluster_map(path), new_map)
        save_cluster_map(merged, path)
    return {"skills": len(canonical), "themes": len(merged.theme_label)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_match_gap.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/services/match_gap.py tests/test_services_match_gap.py
git commit -m "feat: add refresh_clusters service"
```

---

## Task 6: API schemas (rich `MatchGapOut`)

**Files:**

- Modify: `src/resume_tailor_harness/api/schemas/match_gap.py` (full rewrite)
- Test: `tests/api/test_schemas_match_gap.py` (rewrite)

**Interfaces:**

- Consumes: `CamelModel` (`api/schemas/base.py`); the Task-1 dataclasses for `model_validate` projection.
- Produces (all `CamelModel`):
  - `JobLiteOut(id:int, company:str|None, title:str|None, seniority:str|None)`
  - `SkillNodeOut(skill:str, theme_id:str|None, covered:bool)` → wire `themeId`
  - `DemandEdgeOut(job_id:int, skill:str, source:str)` → wire `jobId`
  - `ThemeOut(id:str, label:str)`
  - `MatchGapOut(target_total:int, clusters_stale:bool, jobs:list, skills:list, edges:list, themes:list)`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_schemas_match_gap.py
from resume_tailor_harness.api.schemas.match_gap import (
    DemandEdgeOut,
    MatchGapOut,
    SkillNodeOut,
)
from resume_tailor_harness.tracking.match_gap import DemandEdge, SkillNode


def test_skill_node_out_camelizes_theme_id():
    out = SkillNodeOut.model_validate(SkillNode("Kubernetes", "t1", False))
    assert out.model_dump(by_alias=True) == {
        "skill": "Kubernetes", "themeId": "t1", "covered": False
    }


def test_demand_edge_out_camelizes_job_id():
    out = DemandEdgeOut.model_validate(DemandEdge(7, "Go", "must"))
    assert out.model_dump(by_alias=True) == {"jobId": 7, "skill": "Go", "source": "must"}


def test_match_gap_out_shape():
    out = MatchGapOut(
        target_total=0, clusters_stale=False, jobs=[], skills=[], edges=[], themes=[]
    )
    dumped = out.model_dump(by_alias=True)
    assert set(dumped) == {"targetTotal", "clustersStale", "jobs", "skills", "edges", "themes"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_match_gap.py -v`
Expected: FAIL — `ImportError: cannot import name 'DemandEdgeOut'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_tailor_harness/api/schemas/match_gap.py
"""Match-gap API schemas: the full skill-demand graph for the dashboard."""

from __future__ import annotations

from typing import Literal

from resume_tailor_harness.api.schemas.base import CamelModel


class JobLiteOut(CamelModel):
    id: int
    company: str | None = None
    title: str | None = None
    seniority: str | None = None


class SkillNodeOut(CamelModel):
    skill: str
    theme_id: str | None = None
    covered: bool


class DemandEdgeOut(CamelModel):
    job_id: int
    skill: str
    source: Literal["must", "nice", "tech"]


class ThemeOut(CamelModel):
    id: str
    label: str


class MatchGapOut(CamelModel):
    target_total: int
    clusters_stale: bool
    jobs: list[JobLiteOut]
    skills: list[SkillNodeOut]
    edges: list[DemandEdgeOut]
    themes: list[ThemeOut]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_match_gap.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/schemas/match_gap.py tests/api/test_schemas_match_gap.py
git commit -m "feat: rich match-gap demand-graph schemas"
```

---

## Task 7: GET `/match-gap` rich projection

**Files:**

- Modify: `src/resume_tailor_harness/api/routers/match_gap.py` (rewrite the GET)
- Test: `tests/api/test_match_gap.py` (rewrite the existing assertion + add a populated case)

**Interfaces:**

- Consumes: `build_demand_graph` (Task 1), `load_cluster_map` (Task 2), the Task-6 schemas, `load_facts` (existing).
- Produces: GET returns `MatchGapOut`; helper `_facts_or_empty()` and module constants `_FACTS_PATH`, `_CLUSTER_PATH`.

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/api/test_match_gap.py`:

```python
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_match_gap_empty_db_returns_empty_graph():
    client = _client()
    with client:
        resp = client.get("/api/match-gap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["targetTotal"] == 0
    assert body["jobs"] == []
    assert body["skills"] == []
    assert body["edges"] == []
    assert body["themes"] == []
    assert body["clustersStale"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_match_gap.py -v`
Expected: FAIL — old code returns `{"targetTotal":0,"gaps":[]}` (KeyError on `jobs`).

- [ ] **Step 3: Write minimal implementation**

Rewrite `src/resume_tailor_harness/api/routers/match_gap.py`:

```python
"""Read-only match-gap demand graph + a background cluster-refresh Run."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_run_manager, get_session
from resume_tailor_harness.api.runs.manager import RunManager
from resume_tailor_harness.api.runs.sse import record_to_run
from resume_tailor_harness.api.schemas.match_gap import MatchGapOut
from resume_tailor_harness.api.schemas.runs import RunOut
from resume_tailor_harness.db import get_session as open_session
from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.profile.store import load_facts
from resume_tailor_harness.taxonomy.clusters import load_cluster_map
from resume_tailor_harness.tracking.match_gap import build_demand_graph

router = APIRouter()

_FACTS_PATH = "data/profile/facts.json"
_CLUSTER_PATH = "data/profile/cluster_map.json"


def _facts_or_empty() -> ProfileFacts:
    if Path(_FACTS_PATH).exists():
        return load_facts(_FACTS_PATH)
    return ProfileFacts(contact=Contact(name=""))


@router.get("/match-gap", response_model=MatchGapOut)
def get_match_gap(session: Session = Depends(get_session)):
    graph = build_demand_graph(
        session, _facts_or_empty(), cluster_map=load_cluster_map(_CLUSTER_PATH)
    )
    return MatchGapOut.model_validate(graph)


@router.post("/match-gap/refresh-clusters", response_model=RunOut, status_code=202)
def refresh_match_gap_clusters(
    request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = request.app.state.engine

    def work(reporter):
        from resume_tailor_harness.services.match_gap import refresh_clusters
        from resume_tailor_harness.tracking.canonicalize import (
            build_skill_canonicalizer,
            build_skill_themer,
        )

        reporter.begin(1, "Clustering skills")
        dedup = build_skill_canonicalizer()
        themer = build_skill_themer()
        with open_session(engine) as session:
            result = refresh_clusters(
                session, dedup=dedup, themer=themer, path=_CLUSTER_PATH, reporter=reporter
            )
        reporter.step(1)
        return result

    run_id = mgr.submit("refreshClusters", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)
```

(Task 8 tests the POST; this step makes GET pass and lands the POST in one cohesive router rewrite.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_match_gap.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/match_gap.py tests/api/test_match_gap.py
git commit -m "feat: rich match-gap GET + refresh-clusters route"
```

---

## Task 8: Refresh-clusters Run endpoint test

**Files:**

- Test: `tests/api/test_match_gap_refresh.py` (new)
- Modify: none (endpoint landed in Task 7)

**Interfaces:**

- Consumes: the POST route from Task 7; monkeypatches `build_skill_canonicalizer` / `build_skill_themer` on `resume_tailor_harness.tracking.canonicalize` to fakes (the route imports them inside `work`, so patch the source module).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_match_gap_refresh.py
import time

from fastapi.testclient import TestClient

import resume_tailor_harness.tracking.canonicalize as canon
from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus


def _seed(engine):
    from resume_tailor_harness.db import get_session
    with get_session(engine) as s:
        save_job(s, Job(
            source="manual", company="C", title="T", status=JobStatus.shortlisted.value,
            criteria_json={"must_have_skills": ["k8s", "React"]},
        ))


def test_refresh_clusters_run_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        canon, "build_skill_canonicalizer",
        lambda: (lambda toks: {t: ("kubernetes" if t == "k8s" else t) for t in toks}),
    )
    monkeypatch.setattr(
        canon, "build_skill_themer",
        lambda: (lambda toks: [("Cloud/Infra", ["kubernetes"]), ("Frontend", ["react"])]),
    )
    # redirect the cluster-map path into tmp so the test is hermetic
    import resume_tailor_harness.api.routers.match_gap as router_mod
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(tmp_path / "cluster_map.json"))

    app = create_app(db_url="sqlite://")
    _seed(app.state.engine)
    client = TestClient(app)
    with client:
        resp = client.post("/api/match-gap/refresh-clusters")
        assert resp.status_code == 202
        run_id = resp.json()["runId"]

        for _ in range(50):
            rec = client.get(f"/api/runs/{run_id}").json()
            if rec["state"] in ("done", "error"):
                break
            time.sleep(0.02)
        assert rec["state"] == "done"
        assert rec["result"] == {"skills": 2, "themes": 2}
```

- [ ] **Step 2: Run test to verify it fails (then passes)**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_match_gap_refresh.py -v`
Expected: PASS if the production `RunManager` executor completes the inline-submitted work. If the app's executor is a real ThreadPool, the poll loop covers it. If a test conftest swaps an inline executor (see `tests/api/conftest.py`), it still passes.

> Note: if `tests/api/conftest.py` provides an inline-executor fixture for the app, prefer using it here for determinism. Inspect that file; if such a fixture exists, build the app through it instead of `create_app` directly, keeping the rest identical.

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_match_gap_refresh.py
git commit -m "test: refresh-clusters run endpoint end-to-end"
```

---

## Task 9: Regenerate OpenAPI + TS contract

**Files:**

- Modify (generated): `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts`
- Test: `tests/api/test_openapi_contract.py` (existing drift gate)

- [ ] **Step 1: Run the contract gate to confirm it now fails (drift)**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: FAIL — committed contract no longer matches the app schema (new MatchGapOut + route).

- [ ] **Step 2: Regenerate the contract + TS client**

Run: `bash scripts/gen_ts_client.sh`
Expected: writes `contracts/openapi.json`, `contracts/ts/api.ts`, copies to `web/src/lib/api/schema.ts`.

- [ ] **Step 3: Run the gate to confirm it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "chore: regenerate contract for match-gap demand graph"
```

---

## Task 10: Frontend pure aggregation (`aggregate.ts`)

**Files:**

- Create: `web/src/features/match-gap/aggregate.ts`
- Test: `web/src/features/match-gap/aggregate.test.ts` (new)

**Interfaces:**

- Consumes: `components["schemas"]["MatchGapOut"]` from `@/lib/api/schema`.
- Produces:
  - `interface Filters { company: string | null; seniority: string | null; gapsOnly: boolean; weighting: "essential" | "popular" }`
  - `interface SkillRow { skill; themeId: string|null; covered: boolean; score: number; jobCount: number; must: number; nice: number; tech: number }`
  - `interface ThemeGroup { id: string; label: string; score: number; skills: SkillRow[] }`
  - `interface StatRow { key: string; topSkills: { skill: string; score: number }[]; gapCount: number }`
  - `interface DerivedView { skills: SkillRow[]; themes: ThemeGroup[]; byCompany: StatRow[]; byPosition: StatRow[]; jobsForSkill: (skill: string) => JobLite[]; companies: string[]; seniorities: string[] }`
  - `const SOURCE_WEIGHT = { must: 3, nice: 2, tech: 1 }`
  - `deriveView(payload, filters): DerivedView`

- [ ] **Step 1: Write the failing test**

```ts
// web/src/features/match-gap/aggregate.test.ts
import { describe, expect, it } from "vitest";
import { deriveView, type Filters } from "./aggregate";
import type { components } from "@/lib/api/schema";

type Payload = components["schemas"]["MatchGapOut"];

const base: Filters = {
  company: null,
  seniority: null,
  gapsOnly: false,
  weighting: "essential",
};

const payload: Payload = {
  targetTotal: 2,
  clustersStale: false,
  jobs: [
    { id: 1, company: "Stripe", title: "Backend", seniority: "senior" },
    { id: 2, company: "Datadog", title: "Platform", seniority: "mid" },
  ],
  skills: [
    { skill: "Kubernetes", themeId: "infra", covered: false },
    { skill: "Python", themeId: "lang", covered: true },
  ],
  edges: [
    { jobId: 1, skill: "Kubernetes", source: "must" },
    { jobId: 2, skill: "Kubernetes", source: "tech" },
    { jobId: 1, skill: "Python", source: "must" },
  ],
  themes: [
    { id: "infra", label: "Cloud/Infra" },
    { id: "lang", label: "Languages" },
  ],
};

describe("deriveView", () => {
  it("scores by essential weighting (must=3,tech=1)", () => {
    const v = deriveView(payload, base);
    const k8s = v.skills.find((s) => s.skill === "Kubernetes")!;
    expect(k8s.score).toBe(4); // 3 + 1
    expect(k8s.jobCount).toBe(2);
    expect(k8s.must).toBe(1);
    expect(k8s.tech).toBe(1);
  });

  it("scores by popular weighting (distinct job count)", () => {
    const v = deriveView(payload, { ...base, weighting: "popular" });
    expect(v.skills.find((s) => s.skill === "Kubernetes")!.score).toBe(2);
    expect(v.skills.find((s) => s.skill === "Python")!.score).toBe(1);
  });

  it("gapsOnly hides covered skills", () => {
    const v = deriveView(payload, { ...base, gapsOnly: true });
    expect(v.skills.map((s) => s.skill)).toEqual(["Kubernetes"]);
  });

  it("filters by company and recomputes scores", () => {
    const v = deriveView(payload, { ...base, company: "Datadog" });
    // only job 2 survives -> Kubernetes via tech only
    expect(v.skills.map((s) => s.skill)).toEqual(["Kubernetes"]);
    expect(v.skills[0].score).toBe(1);
  });

  it("sorts skills by score desc", () => {
    const v = deriveView(payload, base);
    expect(v.skills[0].skill).toBe("Kubernetes"); // 4 > 3
  });

  it("jobsForSkill returns the demanding jobs", () => {
    const v = deriveView(payload, base);
    expect(
      v
        .jobsForSkill("Kubernetes")
        .map((j) => j.company)
        .sort(),
    ).toEqual(["Datadog", "Stripe"]);
  });

  it("byCompany rollup carries gap counts", () => {
    const v = deriveView(payload, base);
    const stripe = v.byCompany.find((r) => r.key === "Stripe")!;
    expect(stripe.gapCount).toBe(1); // Kubernetes is a gap, Python covered
  });

  it("recomputes facet scores from each facet's edges", () => {
    const v = deriveView(payload, base);
    const stripe = v.byCompany.find((r) => r.key === "Stripe")!;
    const datadog = v.byCompany.find((r) => r.key === "Datadog")!;
    expect(stripe.topSkills.find((s) => s.skill === "Kubernetes")!.score).toBe(
      3,
    );
    expect(datadog.topSkills.find((s) => s.skill === "Kubernetes")!.score).toBe(
      1,
    );
  });

  it("exposes filter facets", () => {
    const v = deriveView(payload, base);
    expect(v.companies).toEqual(["Datadog", "Stripe"]);
    expect(v.seniorities).toEqual(["mid", "senior"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/aggregate.test.ts`
Expected: FAIL — cannot resolve `./aggregate`.

- [ ] **Step 3: Write minimal implementation**

```ts
// web/src/features/match-gap/aggregate.ts
import type { components } from "@/lib/api/schema";

type Payload = components["schemas"]["MatchGapOut"];
type JobLite = Payload["jobs"][number];
type Edge = Payload["edges"][number];

export const SOURCE_WEIGHT = { must: 3, nice: 2, tech: 1 } as const;

export interface Filters {
  company: string | null;
  seniority: string | null;
  gapsOnly: boolean;
  weighting: "essential" | "popular";
}

export interface SkillRow {
  skill: string;
  themeId: string | null;
  covered: boolean;
  score: number;
  jobCount: number;
  must: number;
  nice: number;
  tech: number;
}

export interface ThemeGroup {
  id: string;
  label: string;
  score: number;
  skills: SkillRow[];
}

export interface StatRow {
  key: string;
  topSkills: { skill: string; score: number }[];
  gapCount: number;
}

export interface DerivedView {
  skills: SkillRow[];
  themes: ThemeGroup[];
  byCompany: StatRow[];
  byPosition: StatRow[];
  jobsForSkill: (skill: string) => JobLite[];
  jobsForTheme: (themeId: string) => JobLite[];
  companies: string[];
  seniorities: string[];
}

function uniqueSorted(values: (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((v): v is string => !!v))].sort();
}

function summarize(
  edges: Edge[],
  coveredOf: Map<string, boolean>,
  themeOf: Map<string, string | null>,
  filters: Filters,
): SkillRow[] {
  type Acc = { must: number; nice: number; tech: number; jobs: Set<number> };
  const acc = new Map<string, Acc>();
  for (const edge of edges) {
    if (
      edge.source !== "must" &&
      edge.source !== "nice" &&
      edge.source !== "tech"
    )
      continue;
    const row = acc.get(edge.skill) ?? {
      must: 0,
      nice: 0,
      tech: 0,
      jobs: new Set(),
    };
    row[edge.source] += 1;
    row.jobs.add(edge.jobId);
    acc.set(edge.skill, row);
  }

  const rows = [...acc.entries()].map(([skill, row]) => ({
    skill,
    themeId: themeOf.get(skill) ?? null,
    covered: coveredOf.get(skill) ?? false,
    score:
      filters.weighting === "popular"
        ? row.jobs.size
        : row.must * SOURCE_WEIGHT.must +
          row.nice * SOURCE_WEIGHT.nice +
          row.tech * SOURCE_WEIGHT.tech,
    jobCount: row.jobs.size,
    must: row.must,
    nice: row.nice,
    tech: row.tech,
  }));
  return rows
    .filter((row) => !filters.gapsOnly || !row.covered)
    .sort((a, b) => b.score - a.score || a.skill.localeCompare(b.skill));
}

export function deriveView(payload: Payload, filters: Filters): DerivedView {
  const jobById = new Map(payload.jobs.map((j) => [j.id, j]));
  const coveredOf = new Map(payload.skills.map((s) => [s.skill, s.covered]));
  const themeOf = new Map(payload.skills.map((s) => [s.skill, s.themeId]));
  const themeLabel = new Map(payload.themes.map((t) => [t.id, t.label]));

  const keep = (e: Edge): boolean => {
    const job = jobById.get(e.jobId);
    if (!job) return false;
    if (filters.company && job.company !== filters.company) return false;
    if (filters.seniority && job.seniority !== filters.seniority) return false;
    return true;
  };
  const edges = payload.edges.filter(keep);

  const skills = summarize(edges, coveredOf, themeOf, filters);

  const themeMap = new Map<string, ThemeGroup>();
  for (const s of skills) {
    const id = s.themeId ?? "__none__";
    const label = s.themeId
      ? (themeLabel.get(s.themeId) ?? s.themeId)
      : "Unthemed";
    const g = themeMap.get(id) ?? { id, label, score: 0, skills: [] };
    g.skills.push(s);
    g.score += s.score;
    themeMap.set(id, g);
  }
  const themes = [...themeMap.values()].sort((a, b) => b.score - a.score);

  const skillJobs = new Map<string, Set<number>>();
  for (const e of edges) {
    const set = skillJobs.get(e.skill) ?? new Set<number>();
    set.add(e.jobId);
    skillJobs.set(e.skill, set);
  }
  const jobsForSkill = (skill: string): JobLite[] =>
    [...(skillJobs.get(skill) ?? new Set<number>())]
      .map((id) => jobById.get(id))
      .filter((j): j is JobLite => !!j);

  const rollup = (
    facet: (j: JobLite) => string | null | undefined,
  ): StatRow[] => {
    const byKey = new Map<string, Edge[]>();
    for (const e of edges) {
      const job = jobById.get(e.jobId);
      const key = facet(job!);
      if (!key) continue;
      const bucket = byKey.get(key) ?? [];
      bucket.push(e);
      byKey.set(key, bucket);
    }
    return [...byKey.entries()]
      .map(([key, facetEdges]) => {
        // `summarize` is the same pure helper used to create the main `skills`
        // array. It applies weighting, distinct-job counting, coverage, and
        // gapsOnly to this facet's edges only.
        const rows = summarize(facetEdges, coveredOf, themeOf, filters);
        return {
          key,
          topSkills: rows
            .slice(0, 5)
            .map((r) => ({ skill: r.skill, score: r.score })),
          gapCount: rows.filter((r) => !r.covered).length,
        };
      })
      .sort((a, b) => a.key.localeCompare(b.key));
  };

  const jobsForTheme = (themeId: string): JobLite[] => {
    const memberSkills = new Set(
      payload.skills
        .filter((skill) => skill.themeId === themeId)
        .map((skill) => skill.skill),
    );
    const ids = new Set(
      edges
        .filter((edge) => memberSkills.has(edge.skill))
        .map((edge) => edge.jobId),
    );
    return [...ids]
      .map((id) => jobById.get(id))
      .filter((job): job is JobLite => !!job);
  };

  return {
    skills,
    themes,
    byCompany: rollup((j) => j.company),
    byPosition: rollup((j) => j.title),
    jobsForSkill,
    jobsForTheme,
    companies: uniqueSorted(payload.jobs.map((j) => j.company)),
    seniorities: uniqueSorted(payload.jobs.map((j) => j.seniority)),
  };
}
```

The excerpt above intentionally calls `summarize(...)`: extract the existing
accumulator/score/sort block into that helper instead of duplicating it. This is
the simplification that prevents global and facet logic from drifting.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/match-gap/aggregate.test.ts`
Expected: PASS (all 8 cases).

- [ ] **Step 5: Commit**

```bash
git add web/src/features/match-gap/aggregate.ts web/src/features/match-gap/aggregate.test.ts
git commit -m "feat: pure demand-graph aggregation for match-gap"
```

---

## Task 11: Data hook + refresh hook (`use-match-gap.ts`)

**Files:**

- Modify: `web/src/features/match-gap/use-match-gap.ts`
- Test: none new (covered by container test in Task 13; this is thin glue over existing tested infra)

**Interfaces:**

- Consumes: `api`/`unwrap` (`@/lib/api/client`), `useLaunchRun` (`@/features/runs/use-launch-run`).
- Produces: `useMatchGap()` (typed to new `MatchGapOut`), `useRefreshClusters()` returning `{ refresh: () => Promise<boolean> }`.

- [ ] **Step 1: Write the implementation**

```ts
// web/src/features/match-gap/use-match-gap.ts
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { useLaunchRun } from "@/features/runs/use-launch-run";
import type { components } from "@/lib/api/schema";

export type MatchGap = components["schemas"]["MatchGapOut"];

export function useMatchGap() {
  return useQuery({
    queryKey: ["match-gap"],
    queryFn: (): Promise<MatchGap> =>
      unwrap(api.GET("/api/match-gap", {})) as Promise<MatchGap>,
  });
}

export function useRefreshClusters() {
  const { launch } = useLaunchRun();
  const refresh = () =>
    launch(
      "refreshClusters",
      () => unwrap(api.POST("/api/match-gap/refresh-clusters", { body: {} })),
      ["match-gap"],
    );
  return { refresh };
}
```

- [ ] **Step 2: Type-check**

Run: `cd web && npx tsc -b --noEmit`
Expected: no errors (the POST path + body type come from the regenerated schema in Task 9).

- [ ] **Step 3: Commit**

```bash
git add web/src/features/match-gap/use-match-gap.ts
git commit -m "feat: match-gap data + refresh-clusters hooks"
```

---

## Task 12: Presentational components

**Files:**

- Create: `web/src/features/match-gap/Filters.tsx`, `WordCloud.tsx`, `RankedList.tsx`, `SkillDrawer.tsx`, `StatTables.tsx`, `RefreshClustersButton.tsx`
- Test: `web/src/features/match-gap/WordCloud.test.tsx`, `web/src/features/match-gap/SkillDrawer.test.tsx` (new)

**Interfaces:**

- Consumes: `SkillRow`, `ThemeGroup`, `StatRow`, `Filters` from `./aggregate`; `JobLite` shape from schema; shadcn `select`/`switch`/`toggle-group`/`sheet`/`button`/`table`.
- Produces:
  - `WordCloud({ skills, onSelect })` — buttons sized by score bucket, colored by coverage.
  - `RankedList({ skills, onSelect })`.
  - `Filters({ value, onChange, companies, seniorities })`.
  - `SkillDrawer({ skill, jobs, onClose })`.
  - `StatTables({ byCompany, byPosition })`.
  - `RefreshClustersButton({ stale, onRefresh })`.

- [ ] **Step 1: Write the failing tests**

```tsx
// web/src/features/match-gap/WordCloud.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WordCloud } from "./WordCloud";
import type { SkillRow } from "./aggregate";

const rows: SkillRow[] = [
  {
    skill: "Kubernetes",
    themeId: "infra",
    covered: false,
    score: 9,
    jobCount: 9,
    must: 3,
    nice: 0,
    tech: 0,
  },
  {
    skill: "Python",
    themeId: "lang",
    covered: true,
    score: 2,
    jobCount: 2,
    must: 0,
    nice: 1,
    tech: 0,
  },
];

describe("WordCloud", () => {
  it("renders a button per skill and fires onSelect", async () => {
    const onSelect = vi.fn();
    render(<WordCloud skills={rows} onSelect={onSelect} />);
    const btn = screen.getByRole("button", { name: /Kubernetes/ });
    await userEvent.click(btn);
    expect(onSelect).toHaveBeenCalledWith("Kubernetes");
  });

  it("marks gap vs covered via data attribute", () => {
    render(<WordCloud skills={rows} onSelect={() => {}} />);
    expect(screen.getByRole("button", { name: /Kubernetes/ })).toHaveAttribute(
      "data-covered",
      "false",
    );
    expect(screen.getByRole("button", { name: /Python/ })).toHaveAttribute(
      "data-covered",
      "true",
    );
  });
});
```

```tsx
// web/src/features/match-gap/SkillDrawer.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SkillDrawer } from "./SkillDrawer";

describe("SkillDrawer", () => {
  it("lists the companies + titles demanding the skill", () => {
    render(
      <SkillDrawer
        skill="Kubernetes"
        jobs={[
          { id: 1, company: "Stripe", title: "Backend", seniority: "senior" },
          { id: 2, company: "Datadog", title: "Platform", seniority: "mid" },
        ]}
        onClose={() => {}}
      />,
    );
    expect(screen.getByText("Stripe")).toBeInTheDocument();
    expect(screen.getByText("Platform")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/features/match-gap/WordCloud.test.tsx src/features/match-gap/SkillDrawer.test.tsx`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Write minimal implementations**

```tsx
// web/src/features/match-gap/WordCloud.tsx
import type { SkillRow } from "./aggregate";

// Five font-size buckets by score quantile-ish (max-relative).
function sizeClass(score: number, max: number): string {
  const r = max ? score / max : 0;
  if (r > 0.8) return "text-3xl";
  if (r > 0.6) return "text-2xl";
  if (r > 0.4) return "text-xl";
  if (r > 0.2) return "text-lg";
  return "text-sm";
}

export function WordCloud({
  skills,
  onSelect,
}: {
  skills: SkillRow[];
  onSelect: (skill: string) => void;
}) {
  const max = skills.reduce((m, s) => Math.max(m, s.score), 0);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border bg-card p-4">
      {skills.map((s) => (
        <button
          key={s.skill}
          type="button"
          data-covered={s.covered}
          onClick={() => onSelect(s.skill)}
          aria-label={`${s.skill}, ${s.covered ? "covered" : "gap"}, score ${s.score}, ${s.jobCount} jobs`}
          title={`${s.skill} · score ${s.score} · ${s.jobCount} jobs`}
          className={`${sizeClass(s.score, max)} font-semibold leading-tight transition hover:underline ${
            s.covered ? "text-muted-foreground" : "text-primary"
          }`}
        >
          {s.skill}
        </button>
      ))}
    </div>
  );
}
```

```tsx
// web/src/features/match-gap/RankedList.tsx
import type { SkillRow } from "./aggregate";

export function RankedList({
  skills,
  onSelect,
}: {
  skills: SkillRow[];
  onSelect: (skill: string) => void;
}) {
  const max = skills.reduce((m, s) => Math.max(m, s.score), 0) || 1;
  return (
    <div className="rounded-lg border bg-card p-2">
      <ul className="space-y-1">
        {skills.map((s) => (
          <li key={s.skill}>
            <button
              type="button"
              onClick={() => onSelect(s.skill)}
              aria-label={`${s.skill}, ${s.covered ? "covered" : "gap"}, score ${s.score}`}
              className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-sm hover:bg-muted"
            >
              <span className="w-40 truncate">{s.skill}</span>
              <span className="relative h-2 flex-1 overflow-hidden rounded bg-muted">
                <span
                  className={`absolute inset-y-0 left-0 ${s.covered ? "bg-muted-foreground/40" : "bg-primary"}`}
                  style={{ width: `${(s.score / max) * 100}%` }}
                />
              </span>
              <span className="w-12 text-right tabular-nums">{s.score}</span>
              <span aria-hidden>{s.covered ? "✓" : "⚠"}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

```tsx
// web/src/features/match-gap/Filters.tsx
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Label } from "@/components/ui/label";
import type { Filters as FiltersValue } from "./aggregate";

const ALL = "__all__";

export function Filters({
  value,
  onChange,
  companies,
  seniorities,
}: {
  value: FiltersValue;
  onChange: (next: FiltersValue) => void;
  companies: string[];
  seniorities: string[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Select
        value={value.company ?? ALL}
        onValueChange={(v) =>
          onChange({ ...value, company: v === ALL ? null : v })
        }
      >
        <SelectTrigger aria-label="Filter by company" className="w-44">
          <SelectValue placeholder="Company" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All companies</SelectItem>
          {companies.map((c) => (
            <SelectItem key={c} value={c}>
              {c}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={value.seniority ?? ALL}
        onValueChange={(v) =>
          onChange({ ...value, seniority: v === ALL ? null : v })
        }
      >
        <SelectTrigger aria-label="Filter by seniority" className="w-40">
          <SelectValue placeholder="Seniority" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>All levels</SelectItem>
          {seniorities.map((s) => (
            <SelectItem key={s} value={s}>
              {s}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <div className="flex items-center gap-2">
        <Switch
          id="gaps-only"
          checked={value.gapsOnly}
          onCheckedChange={(c) => onChange({ ...value, gapsOnly: c })}
        />
        <Label htmlFor="gaps-only">Gaps only</Label>
      </div>

      <ToggleGroup
        type="single"
        aria-label="Demand weighting"
        value={value.weighting}
        onValueChange={(v) =>
          v && onChange({ ...value, weighting: v as FiltersValue["weighting"] })
        }
      >
        <ToggleGroupItem value="essential">Essential</ToggleGroupItem>
        <ToggleGroupItem value="popular">Popular</ToggleGroupItem>
      </ToggleGroup>
    </div>
  );
}
```

```tsx
// web/src/features/match-gap/SkillDrawer.tsx
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

type Job = {
  id: number;
  company: string | null;
  title: string | null;
  seniority: string | null;
};

export function SkillDrawer({
  skill,
  jobs,
  onClose,
}: {
  skill: string | null;
  jobs: Job[];
  onClose: () => void;
}) {
  return (
    <Sheet open={skill !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{skill}</SheetTitle>
          <SheetDescription>
            {jobs.length} target job(s) demand this skill
          </SheetDescription>
        </SheetHeader>
        {jobs.length === 0 ? (
          <p role="status" className="mt-4 text-sm text-muted-foreground">
            No target jobs match the current filters.
          </p>
        ) : (
          <ul className="mt-4 space-y-2">
            {jobs.map((j) => (
              <li key={j.id} className="rounded border p-2 text-sm">
                <div className="font-medium">{j.company}</div>
                <div className="text-muted-foreground">
                  {j.title}
                  {j.seniority ? ` · ${j.seniority}` : ""}
                </div>
              </li>
            ))}
          </ul>
        )}
      </SheetContent>
    </Sheet>
  );
}
```

```tsx
// web/src/features/match-gap/StatTables.tsx
import type { StatRow } from "./aggregate";

function Table({ title, rows }: { title: string; rows: StatRow[] }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        {title}
      </h3>
      <ul className="space-y-1 text-sm">
        {rows.map((r) => (
          <li key={r.key} className="flex items-baseline justify-between gap-2">
            <span className="truncate font-medium">{r.key}</span>
            <span className="truncate text-muted-foreground">
              {r.topSkills.map((s) => s.skill).join(", ")}
            </span>
            <span className="shrink-0 tabular-nums text-xs">
              {r.gapCount} gaps
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function StatTables({
  byCompany,
  byPosition,
}: {
  byCompany: StatRow[];
  byPosition: StatRow[];
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Table title="By company" rows={byCompany} />
      <Table title="By position" rows={byPosition} />
    </div>
  );
}
```

```tsx
// web/src/features/match-gap/RefreshClustersButton.tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";

export function RefreshClustersButton({
  stale,
  onRefresh,
}: {
  stale: boolean;
  onRefresh: () => Promise<boolean>;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant={stale ? "default" : "outline"}
      size="sm"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await onRefresh();
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy
        ? "Clustering…"
        : stale
          ? "Refresh clusters (stale)"
          : "Refresh clusters"}
    </Button>
  );
}
```

> If `toggle-group.tsx` or `switch.tsx` exports differ, match the existing named exports in `web/src/components/ui/`. They are present per the component inventory.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/match-gap/WordCloud.test.tsx src/features/match-gap/SkillDrawer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/match-gap/Filters.tsx web/src/features/match-gap/WordCloud.tsx web/src/features/match-gap/RankedList.tsx web/src/features/match-gap/SkillDrawer.tsx web/src/features/match-gap/StatTables.tsx web/src/features/match-gap/RefreshClustersButton.tsx web/src/features/match-gap/WordCloud.test.tsx web/src/features/match-gap/SkillDrawer.test.tsx
git commit -m "feat: match-gap dashboard presentational components"
```

---

## Task 13: Container wiring + integration test

**Files:**

- Modify: `web/src/features/match-gap/MatchGapContainer.tsx` (full rewrite)
- Test: `web/src/features/match-gap/MatchGapContainer.test.tsx` (rewrite)

**Interfaces:**

- Consumes: `useMatchGap` (Task 11), `deriveView`/`Filters` type (Task 10), all Task-12 components, existing `PageHeader`, `MetricRow`, `EmptyState`, `BoardSkeleton`.
- Produces: the wired dashboard. Local React state holds `Filters` + a discriminated skill/theme selection.

Replace the draft nullable-skill selection with:

```ts
type DrawerSelection =
  | { kind: "skill"; key: string; label: string }
  | { kind: "theme"; key: string; label: string }
  | null;
```

Render a keyboard-accessible action for every derived theme. Skill selection uses
`jobsForSkill`; theme selection uses `jobsForTheme`. Pass `kind`, stable `key`, and
display `label` separately to the drawer so Spec B can query by theme id while the
sheet title remains human-readable. Add an integration test for theme selection.

- [ ] **Step 1: Write the failing test**

Rewrite `web/src/features/match-gap/MatchGapContainer.test.tsx`:

```tsx
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { MatchGapContainer } from "./MatchGapContainer";

const wrap = (ui: ReactNode) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
};

const populated = {
  targetTotal: 2,
  clustersStale: false,
  jobs: [
    { id: 1, company: "Stripe", title: "Backend", seniority: "senior" },
    { id: 2, company: "Datadog", title: "Platform", seniority: "mid" },
  ],
  skills: [{ skill: "Kubernetes", themeId: "infra", covered: false }],
  edges: [
    { jobId: 1, skill: "Kubernetes", source: "must" },
    { jobId: 2, skill: "Kubernetes", source: "tech" },
  ],
  themes: [{ id: "infra", label: "Cloud/Infra" }],
};

describe("MatchGapContainer", () => {
  it("renders the word cloud and opens the jobs drawer on click", async () => {
    server.use(http.get("/api/match-gap", () => HttpResponse.json(populated)));
    wrap(<MatchGapContainer />);
    const word = await screen.findByRole("button", { name: /Kubernetes/ });
    await userEvent.click(word);
    await waitFor(() => expect(screen.getByText("Stripe")).toBeInTheDocument());
    expect(screen.getByText("Datadog")).toBeInTheDocument();
  });

  it("shows the empty state when there are no target jobs", async () => {
    server.use(
      http.get("/api/match-gap", () =>
        HttpResponse.json({
          targetTotal: 0,
          clustersStale: false,
          jobs: [],
          skills: [],
          edges: [],
          themes: [],
        }),
      ),
    );
    wrap(<MatchGapContainer />);
    await waitFor(() =>
      expect(screen.getByText(/no target jobs yet/i)).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/MatchGapContainer.test.tsx`
Expected: FAIL — container still renders the old table (no role button named Kubernetes / no drawer).

- [ ] **Step 3: Write minimal implementation**

```tsx
// web/src/features/match-gap/MatchGapContainer.tsx
import { useMemo, useState } from "react";

import { BoardSkeleton } from "@/components/skeletons";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { MetricRow } from "@/components/MetricRow";
import { PageHeader } from "@/components/PageHeader";
import { deriveView, type Filters as FiltersValue } from "./aggregate";
import { Filters } from "./Filters";
import { WordCloud } from "./WordCloud";
import { RankedList } from "./RankedList";
import { SkillDrawer } from "./SkillDrawer";
import { StatTables } from "./StatTables";
import { RefreshClustersButton } from "./RefreshClustersButton";
import { useMatchGap, useRefreshClusters } from "./use-match-gap";

const DEFAULT_FILTERS: FiltersValue = {
  company: null,
  seniority: null,
  gapsOnly: false,
  weighting: "essential",
};

export function MatchGapContainer() {
  const { data, isLoading, isError, refetch } = useMatchGap();
  const { refresh } = useRefreshClusters();
  const [filters, setFilters] = useState<FiltersValue>(DEFAULT_FILTERS);
  const [selected, setSelected] = useState<string | null>(null);

  const view = useMemo(
    () => (data ? deriveView(data, filters) : null),
    [data, filters],
  );

  if (isLoading) return <BoardSkeleton />;

  if (isError) {
    return (
      <div role="alert" className="space-y-3">
        <EmptyState
          title="Couldn't load skill demand"
          body="The dashboard request failed. Retry after checking the API connection."
        />
        <Button type="button" variant="outline" onClick={() => void refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <>
      <PageHeader
        kicker="Closed loop"
        title="Match / Gap"
        sub="Skills your target jobs demand, clustered and weighted. Click any skill to see the roles behind it."
      />

      {!data || data.targetTotal === 0 || !view ? (
        <EmptyState
          title="No target jobs yet"
          body="Shortlist or approve jobs to populate the demand graph."
        />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Filters
              value={filters}
              onChange={setFilters}
              companies={view.companies}
              seniorities={view.seniorities}
            />
            <RefreshClustersButton
              stale={data.clustersStale}
              onRefresh={refresh}
            />
          </div>

          <MetricRow
            items={[
              ["Target jobs", String(data.targetTotal)],
              ["Distinct skills", String(view.skills.length)],
              ["Gaps", String(view.skills.filter((s) => !s.covered).length)],
            ]}
          />

          {view.skills.length === 0 ? (
            <EmptyState
              title="No skills match these filters"
              body="Clear a filter or show covered skills to restore results."
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <WordCloud skills={view.skills} onSelect={setSelected} />
              <RankedList skills={view.skills} onSelect={setSelected} />
            </div>
          )}

          <StatTables byCompany={view.byCompany} byPosition={view.byPosition} />

          <SkillDrawer
            skill={selected}
            jobs={selected ? view.jobsForSkill(selected) : []}
            onClose={() => setSelected(null)}
          />
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/match-gap/MatchGapContainer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Full frontend gate + commit**

Run: `cd web && npm run test:run && npm run lint`
Expected: PASS.

```bash
git add web/src/features/match-gap/MatchGapContainer.tsx web/src/features/match-gap/MatchGapContainer.test.tsx
git commit -m "feat: wire match-gap skill-intelligence dashboard"
```

---

## Final verification

- [ ] **Backend suite + lint**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all green (including untouched `test_tracking_match_gap.py`, `test_cli_match_gap.py`, and the OpenAPI contract gate).

- [ ] **Frontend suite + lint + typecheck**

Run: `cd web && npm run test:run && npm run lint && npx tsc -b --noEmit`
Expected: all green.

---

## Self-Review

**Spec coverage:**

- §2.1 demand graph GET → Tasks 1, 6, 7. ✔
- §2.2 all-three-sources weighted (3/2/1, client-applied) → Task 1 (edges by source), Task 10 (`SOURCE_WEIGHT`, Essential/Popular). ✔
- §2.3 cluster-map persistence (aliases + themeOf + themeLabel, monotonic) → Task 2. ✔
- §2.4 refresh Run (dedup + theming, own session, off read path) → Tasks 4, 5, 7 (POST), 8. ✔
- §2.5 schemas + contract regen → Tasks 6, 9. ✔
- §3.1 pure `aggregate.ts` → Task 10. ✔
- §3.2 Filters / WordCloud (CSS flex) / RankedList / SkillDrawer / StatTables / RefreshClustersButton → Task 12. ✔
- §3.3 data hook + refresh hook → Task 11. ✔
- §4 testing (backend offline, frontend vitest/MSW, contract gate) → every task + Final verification. ✔
- §5 out-of-scope advisor → not built; `SkillDrawer` is its mount point (noted). ✔
- Coverage flag deterministic in read path (no LLM) → Task 1 (`covered` from `profile_skill_tokens`), Task 7 GET. ✔
- Legacy `match_gap`/CLI untouched → enforced in Global Constraints; Task 1 is additive; Task 4 step verifies legacy tests still pass. ✔

**Review status:** The engineering-review corrections are part of every task's
acceptance criteria. In particular, do not copy the original aggregation or
component snippets without the shared `summarize` helper, theme selection,
boundary validation, and production UI states described above.

**Type consistency:** `DemandGraph`/`SkillNode`/`DemandEdge`/`JobLite`/`ThemeNode` names match across Tasks 1/6/10. `SOURCE_WEIGHT` exists only in Task 10 because weighting is a client concern. `refresh_clusters(session, *, dedup, themer, path, reporter)` matches between service, route, and fakes. `useRefreshClusters().refresh` returns `Promise<boolean>` consumed by the button and container. Cluster-map path `data/profile/cluster_map.json` is consistent.

One known seam to verify during execution (flagged in Task 8): whether `tests/api/conftest.py` swaps an inline executor for the RunManager — use it if present for deterministic run completion.

---

## Future Follow-up: Multi-theme skills (not yet built)

**Motivation.** Theming is a _many-to-one classification_, not a clean partition.
Plenty of tokens legitimately belong to more than one theme — a vector DB like
`weaviate` is both _Data_ and _AI/ML_, `python` is _Backend_ and _Data_, `docker`
is _DevOps_ and _Cloud_. The current contract forces exactly one theme per skill.
When the cheap themer model (correctly) puts such a token in two themes, the
refresh used to abort with `ValueError: skill token appears in multiple themes`.
That crash is now patched with a **keep-first repair** in `themes_to_pairs`
(`canonicalize.py`) — the first theme to claim a token wins and later repeats are
dropped — which keeps refresh robust but _discards a real signal_: the second
(and further) theme membership is silently thrown away.

This follow-up turns that discarded signal into a feature: let a skill belong to
**several** themes.

**Current state (single-theme):**

- `ClusterMap.theme_of: dict[str, str]` — each terminal canonical token → one `theme_id` (`taxonomy/clusters.py`).
- `themes_to_pairs` (`canonicalize.py`) and `_validated_themes` (`services/match_gap.py`) enforce an exact partition; `themes_to_pairs` now keep-first repairs duplicates instead of raising.
- Read path `build_demand_graph` assigns each `SkillNode` to a single `ThemeNode`; `aggregate.ts` and the components render one theme per skill.

**Proposed change (multi-theme):**

- **Data model.** `ClusterMap.theme_of: dict[str, list[str]]` — terminal token → ordered list of `theme_id`s (primary first). Keep `theme_label` as-is.
- **Validation contract.** Drop the "exactly one theme" rule in `themes_to_pairs`/`_validated_themes`: a token may appear in ≥1 theme. Still require full **coverage** (every canonical token in at least one theme), nonblank labels/members, and known tokens. Consider capping themes-per-skill (e.g. ≤2–3) to keep the dashboard legible, and dropping the keep-first skip in favour of recording each membership.
- **Themer prompt** (`_THEME_INSTRUCTIONS`). Replace "include every input token exactly once" with "assign each skill to every theme where it is a _primary_ fit — usually one, occasionally two; never list a theme where the skill is only tangentially related."
- **Persistence.** `theme_of` values become arrays. Update `_canonicalize_theme_keys` and `merge_cluster_map` to **union** lists rather than overwrite, preserving the monotonic guarantee (a refresh must never _remove_ an existing theme assignment a user has seen). `load_cluster_map` must accept the **legacy scalar form** and coerce `str → [str]` for backward compatibility with existing `data/profile/cluster_map.json`.
- **Read path.** `build_demand_graph` emits a skill under each of its themes; `ThemeNode` skill-counts sum per theme, but any "total unique skills" metric must **dedupe** so a two-theme skill isn't double-counted. Decide whether source weighting (3/2/1) is counted fully in each theme or split across them — recommend counted fully in each (a skill genuinely _is_ demand in both areas) with dedupe only on unique-skill totals.
- **Schemas + contract.** `MatchGapOut.themeOf` (or equivalent) becomes `string[]` per skill; regenerate `contracts/openapi.json` + `contracts/ts/api.ts` via `bash scripts/gen_ts_client.sh` and update the drift gate.
- **Frontend.** `aggregate.ts` groups a skill into each of its themes; components render it in each theme section; unique-skill counters dedupe.

**Acceptance criteria:**

- A token the themer places in two themes **persists both**; the refresh is monotonic (re-running never drops a previously assigned theme).
- The dashboard shows such a skill under each of its themes; unique-skill totals are unchanged (no double-count).
- `load_cluster_map` reads an existing single-theme `cluster_map.json` without error (scalar coerced to singleton list).
- Backend offline suite + frontend vitest/MSW + OpenAPI contract gate all green.

**Open decisions to settle before building:** themes-per-skill cap; weighting split vs. full-count-per-theme; whether to keep `themes_to_pairs`' keep-first path as a safety net for the cap, or remove it entirely once multi-theme is the contract.
