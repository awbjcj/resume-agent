# Discovery Relevance Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop wildly off-target jobs ("Class A CDL Driver", "Creative Lead") from entering the raw list and burning two LLM calls each. Add a **tiered relevance gate** — a free deterministic title-anchored lexical gate at the connector edge, plus a cheap haiku relevance stage before extraction — and **tighten the Adzuna server-side query** so junk is narrowed at the source.

**Architecture:** Two new tiers slot in *before* the existing LLM stages. Tier 1 (lexical, title-anchored) replaces `filter_by_search` inside connectors so junk never reaches the DB. Tier 2 (`run_relevance`, haiku) is a new pipeline stage that marks off-target `raw` jobs `rejected` with a reason and lets survivors flow to `run_extract`. Everything fails open: empty config / no API key / LLM error ⇒ that gate is a no-op. No DB migration; config-only additions.

**Tech Stack:** Python 3.13, Pydantic v2 (`ExtensibleModel`, `extra="allow"`), SQLModel/SQLAlchemy (SQLite), Typer (CLI), Agno + Claude (LLM), httpx (connectors), pytest (offline; agents/HTTP faked).

**Spec:** `docs/superpowers/specs/2026-06-17-discovery-relevance-gate-design.md`

**Test command:** `cd D:/Fun/resume-agent && .venv/Scripts/python -m pytest tests/ -q`
**Lint:** `cd D:/Fun/resume-agent && .venv/Scripts/python -m ruff check`

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/resume_agent/discovery/search_config.py` | New `role_anchors`, `exclude_terms`, `target_role`, `adzuna_distance`, `adzuna_max_days_old` fields | Modify |
| `config/search.yaml.example` | Document the new fields with sensible defaults | Modify |
| `src/resume_agent/discovery/connectors/text.py` | `relevance_gate` (title-anchored, word-boundary); keep `filter_by_search` as fallback | Modify |
| `src/resume_agent/discovery/connectors/{greenhouse,lever,adzuna,remoteok}.py` | Call `relevance_gate`; record `self.filtered` | Modify |
| `src/resume_agent/discovery/connectors/adzuna.py` | Targeted server-side query | Modify |
| `src/resume_agent/discovery/connectors/runner.py` | Surface `filtered` count in telemetry note | Modify |
| `src/resume_agent/discovery/relevance.py` | `build_relevance_agent`, `judge_relevance` (haiku gate) | Create |
| `src/resume_agent/discovery/pipeline.py` | `run_relevance` stage; call it inside `discover` | Modify |
| `src/resume_agent/cli.py` | Build + thread the relevance agent into `discover` | Modify |
| `tests/fixtures/relevance/*.json` | Labeled golden corpus | Create |
| `tests/...` | One test file per module above | Create/Modify |

---

## Task 1: Add relevance config fields to `SearchConfig`

**Files:**
- Modify: `src/resume_agent/discovery/search_config.py`
- Modify: `config/search.yaml.example`
- Test: `tests/test_search_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_search_config.py` (match the file's existing load/validate helpers; if it loads from a temp YAML, mirror that):

```python
from resume_agent.discovery.search_config import SearchConfig


def test_relevance_fields_default_empty_and_optional():
    c = SearchConfig()
    assert c.role_anchors == []
    assert c.exclude_terms == []
    assert c.target_role is None
    assert c.adzuna_distance is None
    assert c.adzuna_max_days_old is None


def test_relevance_fields_roundtrip():
    c = SearchConfig.model_validate({
        "role_anchors": ["engineer", "ai"],
        "exclude_terms": ["driver", "creative"],
        "target_role": "Applied AI / LLM engineering roles.",
        "adzuna_distance": 40,
        "adzuna_max_days_old": 30,
    })
    assert c.role_anchors == ["engineer", "ai"]
    assert c.exclude_terms == ["driver", "creative"]
    assert "Applied AI" in (c.target_role or "")
    assert c.adzuna_distance == 40
    assert c.adzuna_max_days_old == 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_search_config.py -q`
Expected: FAIL — `SearchConfig` has no attribute `role_anchors`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/discovery/search_config.py`, extend the model:

```python
class SearchConfig(ExtensibleModel):
    """Discovery criteria + hard-filter thresholds (from config/search.yaml)."""

    keywords: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_policy: str | None = None
    min_salary: int | None = None
    yoe_min: int | None = None
    yoe_max: int | None = None
    sponsorship_required: bool = False
    # Relevance gate (all optional — empty/None => that gate is skipped).
    role_anchors: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    target_role: str | None = None
    adzuna_distance: int | None = None
    adzuna_max_days_old: int | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_search_config.py -q`
Expected: PASS.

- [ ] **Step 5: Document the fields in the example config**

Append to `config/search.yaml.example`:

```yaml
# --- Relevance gate (optional; omit any field to disable that part) ---
# Tier 1 (free, deterministic): the job TITLE must contain at least one
# role_anchor (whole word) and none of the exclude_terms.
role_anchors:
  - engineer
  - ai
  - ml
  - machine learning
  - applied scientist
  - llm
exclude_terms:
  - driver
  - cdl
  - nurse
  - sales
  - recruiter
  - creative
# Tier 2 (cheap LLM): a one-line description of the role you're hunting.
# Falls back to `titles` if unset. Needs ANTHROPIC_API_KEY; skipped if absent.
target_role: >
  Applied AI / LLM engineering roles, including forward-deployed,
  autonomy solutions, and ML platform engineering.
# Adzuna server-side narrowing (optional).
adzuna_distance: 40       # miles radius around locations[0]
adzuna_max_days_old: 30   # freshness window
```

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/discovery/search_config.py config/search.yaml.example tests/test_search_config.py
git commit -m "feat(discovery): add relevance-gate config fields to SearchConfig"
```

---

## Task 2: Title-anchored lexical gate (`relevance_gate`)

**Files:**
- Modify: `src/resume_agent/discovery/connectors/text.py`
- Test: `tests/test_connectors_text.py`

The gate keeps a job iff its **title** contains ≥1 `role_anchor` (whole word) AND no
`exclude_term` (whole word). Matching is word-boundary + case-insensitive, multi-word phrases
allowed. Body is never a gate. Empty `role_anchors` ⇒ skip the anchor requirement; both lists
empty ⇒ fall back to the legacy `filter_by_search`. A title-less job scans the whole document for
anchors so a data hiccup doesn't drop a real role.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_connectors_text.py`:

```python
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.text import relevance_gate
from resume_agent.discovery.search_config import SearchConfig


def _job(title, jd="some description"):
    return RawJob(source="t", url=None, company="C", title=title, location=None, jd_text=jd)


def _cfg(**kw):
    return SearchConfig(**kw)


def test_anchor_required_in_title():
    cfg = _cfg(role_anchors=["engineer", "ai"])
    out = relevance_gate([_job("AI Applications Engineer"), _job("Creative Lead")], cfg)
    assert [j.title for j in out] == ["AI Applications Engineer"]


def test_exclude_term_rejects_even_with_anchor_absent():
    cfg = _cfg(role_anchors=["engineer"], exclude_terms=["driver"])
    out = relevance_gate([_job("Class A CDL Driver")], cfg)
    assert out == []


def test_word_boundary_blocks_substring_false_positive():
    # 'rag' must NOT match 'garage' / 'storage' in the body, and title has no anchor.
    cfg = _cfg(role_anchors=["rag", "engineer"])
    junk = _job("Warehouse Associate", jd="maintain the garage and storage areas")
    assert relevance_gate([junk], cfg) == []


def test_exclude_matches_title_only_not_body():
    cfg = _cfg(role_anchors=["engineer"], exclude_terms=["creative", "sales"])
    keep = _job("AI Engineer", jd="partner with sales; creative problem solving")
    assert [j.title for j in relevance_gate([keep], cfg)] == ["AI Engineer"]


def test_empty_anchors_and_excludes_fall_back_to_legacy():
    cfg = _cfg(keywords=["python"])
    out = relevance_gate([_job("Anything", jd="we use python daily")], cfg)
    assert len(out) == 1  # legacy filter_by_search keeps a body keyword hit


def test_missing_title_scans_document_for_anchor():
    cfg = _cfg(role_anchors=["engineer"])
    out = relevance_gate([_job(None, jd="Senior Engineer wanted")], cfg)
    assert len(out) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_connectors_text.py -q`
Expected: FAIL — `cannot import name 'relevance_gate'`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/discovery/connectors/text.py`, add (keep `filter_by_search` intact):

```python
import re


def _matches_any(haystack: str, terms: list[str]) -> bool:
    """True if any term appears in haystack as a whole word/phrase (case-insensitive)."""
    return any(re.search(rf"\b{re.escape(t)}\b", haystack) for t in terms)


def relevance_gate(jobs: list[RawJob], search: SearchConfig) -> list[RawJob]:
    """Title-anchored relevance gate. Keep iff title has an anchor and no exclude term.

    Body text is never a gate. Empty anchors => skip the anchor check; both lists
    empty => fall back to the legacy keyword `filter_by_search`.
    """
    anchors = [t.strip().lower() for t in search.role_anchors if t.strip()]
    excludes = [t.strip().lower() for t in search.exclude_terms if t.strip()]
    if not anchors and not excludes:
        return filter_by_search(jobs, search)

    kept: list[RawJob] = []
    for job in jobs:
        title = (job.title or "").lower()
        if excludes and title and _matches_any(title, excludes):
            continue
        if anchors:
            haystack = title or f"{job.title or ''}\n{job.jd_text}".lower()
            if not _matches_any(haystack, anchors):
                continue
        kept.append(job)
    return kept
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_connectors_text.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/text.py tests/test_connectors_text.py
git commit -m "feat(discovery): add title-anchored relevance_gate with word-boundary matching"
```

---

## Task 3: Route connectors through `relevance_gate` + record filtered count

**Files:**
- Modify: `src/resume_agent/discovery/connectors/greenhouse.py`, `lever.py`, `adzuna.py`, `remoteok.py`
- Modify: `src/resume_agent/discovery/connectors/runner.py`
- Test: `tests/test_connector_greenhouse.py`, `tests/test_connectors_runner.py`

Each connector swaps `filter_by_search(...)` → `relevance_gate(...)` and records how many it
dropped on `self.filtered` (mirroring the existing `self.failures` pattern). The runner appends
that to its telemetry note.

- [ ] **Step 1: Write the failing test (connector drops + records)**

Add to `tests/test_connector_greenhouse.py`:

```python
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.config import GreenhouseBoard
from resume_agent.discovery.search_config import SearchConfig


def test_greenhouse_gate_drops_offtarget_and_records_count(monkeypatch):
    conn = GreenhouseConnector([GreenhouseBoard(token="acme", company="Acme")])
    payload = {"jobs": [
        {"title": "AI Engineer", "absolute_url": "u1", "content": "build llm systems"},
        {"title": "Class A CDL Driver", "absolute_url": "u2", "content": "drive a truck"},
    ]}
    monkeypatch.setattr(conn, "_get_board", lambda token: payload)
    cfg = SearchConfig(role_anchors=["engineer", "ai"], exclude_terms=["driver", "cdl"])
    out = conn.fetch(cfg)
    assert [j.title for j in out] == ["AI Engineer"]
    assert conn.filtered == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_connector_greenhouse.py::test_greenhouse_gate_drops_offtarget_and_records_count -q`
Expected: FAIL — `relevance_gate` not used / `conn.filtered` missing.

- [ ] **Step 3: Update each connector**

In `greenhouse.py` and `lever.py`: import `relevance_gate` (replace the `filter_by_search` import),
initialise `self.filtered = 0` in `__init__`, and in `fetch` replace the filter line:

```python
from resume_agent.discovery.connectors.text import relevance_gate, html_to_text
# __init__: self.filtered = 0
        before = len(jobs)
        jobs = relevance_gate(jobs, search)
        self.filtered = before - len(jobs)
        return jobs[:limit] if limit is not None else jobs
```

In `adzuna.py` and `remoteok.py` (which have no `failures` today): add a `self.filtered = 0`
attribute (give `RemoteOKConnector`/`AdzunaConnector` an `__init__` if needed — Adzuna already has
one) and the same before/after pattern wrapping `relevance_gate`.

- [ ] **Step 4: Surface the count in telemetry — failing runner test**

Add to `tests/test_connectors_runner.py`:

```python
def test_runner_note_includes_filtered_count(tmp_path, session_factory):
    class _Conn:
        name = "fake"
        filtered = 7
        def fetch(self, search, limit=None):
            return []  # nothing added
    tele = tmp_path / "runs.json"
    with session_factory() as s:
        run_pull(s, [_Conn()], SearchConfig(), tele)
    from resume_agent.discovery.connectors.telemetry import read_runs
    note = read_runs(tele)["fake"]["error"] or ""
    assert "filtered 7" in note
```

(Match the file's existing fixtures/imports; add `from resume_agent.discovery.search_config import SearchConfig` and `from resume_agent.discovery.connectors.runner import run_pull` if absent.)

- [ ] **Step 5: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_connectors_runner.py::test_runner_note_includes_filtered_count -q`
Expected: FAIL — note has no "filtered" text.

- [ ] **Step 6: Update the runner note**

In `src/resume_agent/discovery/connectors/runner.py`, fold the filtered count into the note:

```python
def _run_note(connector: Connector, count: int) -> str | None:
    """Non-fatal note: sub-sources skipped (dead boards) and off-target jobs filtered."""
    parts: list[str] = []
    filtered = int(getattr(connector, "filtered", 0) or 0)
    if filtered:
        parts.append(f"+{count} added; filtered {filtered} off-target")
    failures: dict[str, str] | None = getattr(connector, "failures", None)
    if failures:
        items = ", ".join(f"{name} ({reason})" for name, reason in failures.items())
        parts.append(f"skipped {len(failures)} source(s): {items}")
    return "; ".join(parts) or None
```

Replace the `_partial_failure_note(...)` call in `run_pull` with `_run_note(connector, count)`
(and remove the old helper, or keep it delegating).

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_connector_greenhouse.py tests/test_connector_lever.py tests/test_connector_adzuna.py tests/test_connector_remoteok.py tests/test_connectors_runner.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/discovery/connectors/ tests/test_connector_greenhouse.py tests/test_connector_lever.py tests/test_connector_adzuna.py tests/test_connector_remoteok.py tests/test_connectors_runner.py
git commit -m "feat(connectors): route fetch through relevance_gate and report filtered count"
```

---

## Task 4: Targeted Adzuna server-side query

**Files:**
- Modify: `src/resume_agent/discovery/connectors/adzuna.py`
- Test: `tests/test_connector_adzuna.py`

Replace the all-terms `what` blob with a narrowed query: `what_or` of role phrases
(`role_anchors` + `keywords`), `what_exclude` of `exclude_terms`, `category="it-jobs"`,
`where`+`distance`, `salary_min`, `max_days_old`. Avoid `title_only`/`what_and` (over-filter).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_connector_adzuna.py`:

```python
def test_adzuna_builds_targeted_params():
    conn = AdzunaConnector("id", "key", country="us")
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        class _R:
            def raise_for_status(self): ...
            def json(self): return {"results": []}
        return _R()

    import resume_agent.discovery.connectors.adzuna as mod
    orig = mod.httpx.get
    mod.httpx.get = fake_get
    try:
        cfg = SearchConfig(
            role_anchors=["ai engineer", "machine learning"],
            keywords=["llm", "rag"],
            exclude_terms=["driver", "cdl"],
            locations=["Detroit, MI"],
            min_salary=130000,
            adzuna_distance=40,
            adzuna_max_days_old=30,
        )
        conn.fetch(cfg)
    finally:
        mod.httpx.get = orig

    p = captured["params"]
    assert "ai engineer" in p["what_or"] and "machine learning" in p["what_or"]
    assert "driver" in p["what_exclude"] and "cdl" in p["what_exclude"]
    assert p["category"] == "it-jobs"
    assert p["where"] == "Detroit, MI" and p["distance"] == 40
    assert p["salary_min"] == 130000
    assert p["max_days_old"] == 30
    assert "what" not in p  # no blob
```

(Add `from resume_agent.discovery.search_config import SearchConfig` and `from resume_agent.discovery.connectors.adzuna import AdzunaConnector` if absent.)

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_connector_adzuna.py::test_adzuna_builds_targeted_params -q`
Expected: FAIL — params still use `what` blob.

- [ ] **Step 3: Rewrite `_get_results`**

```python
    def _get_results(self, search: SearchConfig) -> dict:
        role_terms = [t.strip() for t in [*search.role_anchors, *search.keywords] if t.strip()]
        params: dict[str, object] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "category": "it-jobs",
            "results_per_page": 50,
        }
        if role_terms:
            params["what_or"] = ", ".join(dict.fromkeys(role_terms))
        if search.exclude_terms:
            params["what_exclude"] = " ".join(t.strip() for t in search.exclude_terms if t.strip())
        if search.locations:
            params["where"] = search.locations[0]
            if search.adzuna_distance is not None:
                params["distance"] = search.adzuna_distance
        if search.min_salary is not None:
            params["salary_min"] = search.min_salary
        if search.adzuna_max_days_old is not None:
            params["max_days_old"] = search.adzuna_max_days_old
        resp = httpx.get(f"{_BASE}/{self.country}/search/1", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
```

Keep the local `relevance_gate` in `fetch` as the backstop (Task 3).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_connector_adzuna.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/connectors/adzuna.py tests/test_connector_adzuna.py
git commit -m "feat(adzuna): push a targeted server-side query instead of an all-terms blob"
```

---

## Task 5: Haiku relevance gate module (`relevance.py`)

**Files:**
- Create: `src/resume_agent/discovery/relevance.py`
- Test: `tests/test_discovery_relevance.py` (create)

Mirrors `extract.py`/`fit.py`: an Agno agent with a small output schema, plus a pure
`judge_relevance` that calls it and returns a decision. Fail-open lives in `run_relevance`
(Task 6), but `judge_relevance` accepts a pre-truncated snippet and a role description.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_discovery_relevance.py`:

```python
from resume_agent.discovery.relevance import RelevanceVerdict, compose_relevance_input, judge_relevance


class _Result:
    def __init__(self, content): self.content = content


class _Agent:
    def __init__(self, verdict): self._v = verdict
    def run(self, prompt): return _Result(self._v)


def test_compose_input_includes_role_title_and_truncated_snippet():
    text = compose_relevance_input("AI roles", "CDL Driver", "x" * 1000)
    assert "AI roles" in text and "CDL Driver" in text
    assert text.count("x") <= 500  # snippet truncated


def test_judge_relevance_returns_verdict():
    agent = _Agent(RelevanceVerdict(keep=False, reason="trucking role"))
    v = judge_relevance("AI roles", "CDL Driver", "drive a truck", agent)
    assert v.keep is False and "trucking" in v.reason


def test_judge_relevance_type_guard():
    import pytest
    with pytest.raises(TypeError):
        judge_relevance("AI roles", "T", "jd", _Agent("not a verdict"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_discovery_relevance.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the module**

Create `src/resume_agent/discovery/relevance.py`:

```python
from agno.agent import Agent
from agno.models.anthropic import Claude
from pydantic import ConfigDict
from pydantic import BaseModel

from resume_agent.config import get_settings
from resume_agent.llm_runner import AgentRunner, Runner

_SNIPPET_CHARS = 500

_INSTRUCTIONS = [
    "Decide whether a job posting plausibly matches the target role the user is hunting.",
    "Judge by the title and the snippet only; be lenient on adjacent roles, strict on unrelated ones.",
    "Reject clearly off-target roles (e.g. truck driver, nurse, creative/marketing) with a short reason.",
    "Answer keep=true to let it through, keep=false to reject; give a one-line reason.",
]


class RelevanceVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep: bool
    reason: str


def build_relevance_agent(model_id: str | None = None) -> Runner:
    s = get_settings()
    resolved = model_id or s.cheap_model
    return AgentRunner(
        Agent(
            model=Claude(id=resolved, api_key=s.anthropic_api_key or None),
            description="You decide whether a job posting matches a target role.",
            instructions=_INSTRUCTIONS,
            output_schema=RelevanceVerdict,
        )
    )


def compose_relevance_input(target_role: str, title: str | None, jd_text: str) -> str:
    snippet = (jd_text or "")[:_SNIPPET_CHARS]
    return (
        f"TARGET ROLE:\n{target_role}\n\n"
        f"JOB TITLE:\n{title or '(none)'}\n\n"
        f"JOB SNIPPET:\n{snippet}"
    )


def judge_relevance(target_role: str, title: str | None, jd_text: str, agent: Runner) -> RelevanceVerdict:
    result = agent.run(compose_relevance_input(target_role, title, jd_text))
    verdict = result.content
    if not isinstance(verdict, RelevanceVerdict):
        raise TypeError(f"Expected RelevanceVerdict from agent, got {type(verdict).__name__}")
    return verdict
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_discovery_relevance.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/relevance.py tests/test_discovery_relevance.py
git commit -m "feat(discovery): add haiku relevance-gate agent and judge_relevance"
```

---

## Task 6: `run_relevance` pipeline stage (fail-open) + wire into `discover`

**Files:**
- Modify: `src/resume_agent/discovery/pipeline.py`
- Test: `tests/test_discovery_pipeline.py`

`run_relevance` runs over `raw` jobs: keep ⇒ stay `raw`; reject ⇒ `status=rejected`,
`reject_reason="off-target role: <reason>"`. Fail-open: if `target_role` is empty **and** `titles`
is empty, or `agent is None`, the stage returns 0 and touches nothing. Per-job agent errors are
swallowed (the job is kept). It is inserted at the **front** of `discover`, before `run_extract`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_discovery_pipeline.py` (reuse the file's fake-agent + session helpers):

```python
from resume_agent.discovery.pipeline import run_relevance
from resume_agent.discovery.relevance import RelevanceVerdict
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.tracking.repository import save_job, jobs_by_status
from resume_agent.tracking.tables import Job, JobStatus


class _V:
    def __init__(self, content): self.content = content


class _Judge:
    """Keeps titles containing 'engineer'; rejects others."""
    def run(self, prompt):
        keep = "engineer" in prompt.lower()
        return _V(RelevanceVerdict(keep=keep, reason="ok" if keep else "off-target"))


def test_run_relevance_rejects_offtarget_keeps_match(session_factory):
    cfg = SearchConfig(target_role="AI engineering roles")
    with session_factory() as s:
        save_job(s, Job(source="x", jd_text="build systems", title="AI Engineer", status=JobStatus.raw.value))
        save_job(s, Job(source="x", jd_text="drive a truck", title="CDL Driver", status=JobStatus.raw.value))
        n = run_relevance(s, cfg, _Judge())
        assert n == 1  # one rejected
        raw = jobs_by_status(s, JobStatus.raw.value)
        rejected = jobs_by_status(s, JobStatus.rejected.value)
        assert [j.title for j in raw] == ["AI Engineer"]
        assert rejected[0].reject_reason.startswith("off-target role")


def test_run_relevance_noop_when_no_target_and_no_titles(session_factory):
    cfg = SearchConfig()  # no target_role, no titles
    with session_factory() as s:
        save_job(s, Job(source="x", jd_text="jd", title="Whatever", status=JobStatus.raw.value))
        assert run_relevance(s, cfg, _Judge()) == 0
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1


def test_run_relevance_noop_when_agent_none(session_factory):
    cfg = SearchConfig(target_role="AI roles")
    with session_factory() as s:
        save_job(s, Job(source="x", jd_text="jd", title="CDL Driver", status=JobStatus.raw.value))
        assert run_relevance(s, cfg, None) == 0
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1


def test_run_relevance_keeps_job_on_agent_error(session_factory):
    class _Boom:
        def run(self, prompt): raise RuntimeError("api down")
    cfg = SearchConfig(target_role="AI roles")
    with session_factory() as s:
        save_job(s, Job(source="x", jd_text="jd", title="CDL Driver", status=JobStatus.raw.value))
        assert run_relevance(s, cfg, _Boom()) == 0
        assert len(jobs_by_status(s, JobStatus.raw.value)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_discovery_pipeline.py -k run_relevance -q`
Expected: FAIL — `cannot import name 'run_relevance'`.

- [ ] **Step 3: Write the stage + wire into `discover`**

In `src/resume_agent/discovery/pipeline.py`:

```python
from resume_agent.discovery.relevance import judge_relevance


def _relevance_target(config: SearchConfig) -> str | None:
    if config.target_role and config.target_role.strip():
        return config.target_role.strip()
    if config.titles:
        return "Roles like: " + ", ".join(config.titles)
    return None


def run_relevance(session: Session, config: SearchConfig, agent: Runner | None) -> int:
    """Reject off-target raw jobs via the haiku gate. Returns the number rejected.

    Fail-open: no target (and no titles) or no agent => no-op; per-job agent
    errors keep the job (never silently drops a real role).
    """
    target = _relevance_target(config)
    if target is None or agent is None:
        return 0
    rejected = 0
    for job in jobs_by_status(session, JobStatus.raw.value):
        if not job.jd_text.strip():
            continue
        try:
            verdict = judge_relevance(target, job.title, job.jd_text, agent)
        except Exception:
            continue  # fail-open
        if not verdict.keep:
            job.status = JobStatus.rejected.value
            job.reject_reason = f"off-target role: {verdict.reason}"
            session.add(job)
            rejected += 1
    session.commit()
    return rejected
```

Update `discover` to accept an optional relevance agent and run the stage first:

```python
def discover(
    session: Session,
    config: SearchConfig,
    profile_facts: ProfileFacts,
    extract_agent: Runner,
    fit_agent: Runner,
    relevance_agent: Runner | None = None,
) -> dict[str, int]:
    """Run the full funnel over current rows and return final status counts."""
    run_relevance(session, config, relevance_agent)
    run_extract(session, extract_agent)
    run_filter(session, config)
    run_score(session, profile_facts, fit_agent)
    return status_counts(session)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_discovery_pipeline.py -q`
Expected: PASS (new + existing — `relevance_agent` defaults to `None`, so old calls are unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/discovery/pipeline.py tests/test_discovery_pipeline.py
git commit -m "feat(discovery): add fail-open run_relevance stage ahead of extraction"
```

---

## Task 7: CLI wiring + golden corpus + live before/after

**Files:**
- Modify: `src/resume_agent/cli.py`
- Create: `tests/fixtures/relevance/labeled.json`
- Create/Modify: `tests/test_relevance_corpus.py`, `tests/test_cli_discovery.py`

- [ ] **Step 1: Thread the relevance agent through the CLI — failing test**

Add to `tests/test_cli_discovery.py` (match the file's CliRunner + monkeypatch style):

```python
def test_discover_builds_and_passes_relevance_agent(monkeypatch, tmp_path):
    seen = {}

    def fake_discover(session, config, facts, extract_agent, fit_agent, relevance_agent=None):
        seen["relevance_agent"] = relevance_agent
        return {"shortlisted": 0}

    monkeypatch.setattr("resume_agent.cli.discover", fake_discover)
    monkeypatch.setattr("resume_agent.cli.build_relevance_agent", lambda: "RELV")
    # ... build search.yaml + facts.json via the file's existing helpers ...
    result = runner.invoke(app, ["discover", "--search", str(search_path),
                                 "--facts", str(facts_path), "--db-url", "sqlite://"])
    assert result.exit_code == 0
    assert seen["relevance_agent"] == "RELV"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_cli_discovery.py::test_discover_builds_and_passes_relevance_agent -q`
Expected: FAIL — `build_relevance_agent` not imported / not passed.

- [ ] **Step 3: Wire the CLI**

In `src/resume_agent/cli.py`, import the builder and pass it in `discover_cmd`:

```python
from resume_agent.discovery.relevance import build_relevance_agent
# ...
    extract_agent = build_extract_agent()
    fit_agent = build_fit_agent()
    relevance_agent = build_relevance_agent()
    engine = _engine(db_url)
    with get_session(engine) as session:
        counts = discover(session, config, profile_facts, extract_agent, fit_agent, relevance_agent)
```

- [ ] **Step 4: Build the golden corpus + test**

Create `tests/fixtures/relevance/labeled.json` with ~15–25 entries drawn from real postings,
each `{ "title": ..., "jd_text": ..., "tier1_keep": bool }`. Must include the regressions:
"Class A CDL Driver", "Creative Lead", a warehouse role whose body says "garage/storage" (the
`rag` trap), plus genuine keeps ("AI Applications Engineer", "Forward Deployed Engineer",
"Autonomy Solutions Engineer", "Machine Learning Engineer", "Applied Scientist").

Create `tests/test_relevance_corpus.py`:

```python
import json
from pathlib import Path

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.text import relevance_gate
from resume_agent.discovery.search_config import SearchConfig

_FIXTURE = Path(__file__).parent / "fixtures" / "relevance" / "labeled.json"
# The shipped defaults from search.yaml.example:
_ANCHORS = ["engineer", "ai", "ml", "machine learning", "applied scientist", "llm"]
_EXCLUDES = ["driver", "cdl", "nurse", "sales", "recruiter", "creative"]


def test_tier1_gate_matches_labels():
    cases = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    cfg = SearchConfig(role_anchors=_ANCHORS, exclude_terms=_EXCLUDES)
    misses = []
    for c in cases:
        job = RawJob(source="t", url=None, company=None, title=c["title"],
                     location=None, jd_text=c["jd_text"])
        kept = bool(relevance_gate([job], cfg))
        if kept != c["tier1_keep"]:
            misses.append((c["title"], kept, c["tier1_keep"]))
    assert not misses, f"gate disagreed with labels: {misses}"
```

- [ ] **Step 5: Run the corpus + CLI tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_relevance_corpus.py tests/test_cli_discovery.py -q`
Expected: PASS. (If a label is genuinely ambiguous, fix the *fixture* label or tune the default
anchor/exclude lists in `search.yaml.example` — not the gate logic.)

- [ ] **Step 6: Live before/after smoke (manual, recorded in PR)**

```bash
# On main (baseline)
git stash; git checkout main
.venv/Scripts/python -m resume_agent.cli pull --db-url sqlite:///before.db
.venv/Scripts/python -m resume_agent.cli discover --db-url sqlite:///before.db

# On this branch
git checkout feat/relevance-gate; git stash pop 2>/dev/null || true
.venv/Scripts/python -m resume_agent.cli pull --db-url sqlite:///after.db
.venv/Scripts/python -m resume_agent.cli discover --db-url sqlite:///after.db
```

Record in the PR: raw count before vs after, count of obviously off-target titles in each, and the
drop in `extracted`/`shortlisted` rows (≈ LLM calls saved). Acceptance: materially fewer junk raw
rows and fewer downstream LLM calls, with no genuine AI roles lost.

- [ ] **Step 7: Full suite + lint**

Run: `.venv/Scripts/python -m pytest tests/ -q && .venv/Scripts/python -m ruff check`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/resume_agent/cli.py tests/fixtures/relevance/ tests/test_relevance_corpus.py tests/test_cli_discovery.py
git commit -m "feat(discovery): wire relevance agent into CLI + golden-corpus regression guard"
```

---

## Definition of Done

- [ ] All 7 tasks committed; full suite green; ruff clean.
- [ ] Default `role_anchors`/`exclude_terms` reject "Class A CDL Driver" and "Creative Lead" at Tier 1; the `rag`→`garage` substring bug cannot recur.
- [ ] `run_relevance` rejects an off-target survivor with a reason and is a no-op when under-configured or the agent errors.
- [ ] Adzuna issues one narrowed request (asserted params), not the all-terms blob.
- [ ] Live before/after recorded in the PR shows lower junk-rate and fewer downstream LLM calls.
- [ ] No existing config or test required changes (additive, fail-open).
