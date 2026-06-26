# Gap-Closing Advisor Implementation Plan (Spec B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an on-demand, cached advisor that tells the user how to close a skill/theme gap — verified GitHub repos, courses/docs, a project to build, and a profile-bridge framing — grounded in web search.

**Architecture:** A search seam in `llm_runner.py` picks provider-native web search (Anthropic/OpenAI/Gemini) or a model-agnostic agno tool (DeepSeek + fallback) from a pure `plan_search` decision. Two-stage synthesis (search agent → schema formatter) decouples search from structured output. A `generate_suggestion` service verifies repos via the GitHub API and upserts a `SkillSuggestion` row; generation runs as a Run+SSE. The dashboard reads the cached row and renders it inside Spec A's `SkillDrawer`.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, agno (provider-native search + one DDGS-backed fallback tool), httpx (GitHub API), Pydantic v2 `CamelModel`. Frontend: React 19, TanStack Query, shadcn, MSW + vitest.

## Global Constraints

- **PREREQUISITE: Spec A must be implemented first.** This plan's frontend (Task 12) modifies `web/src/features/match-gap/SkillDrawer.tsx` and the backend reuses Spec A's `_target_jobs`, `build_demand_graph`, `profile_skill_tokens`, and cluster map. Do not start Task 12 until Spec A's `SkillDrawer` exists.
- **Test command (backend, offline):** `.venv/Scripts/python.exe -m pytest` — no API key, no network. LLM agents, the search tool, and httpx are faked.
- **Test command (frontend):** `cd web && npm run test:run`.
- **Lint:** `ruff check`; `cd web && npm run lint`.
- **Wire format is camelCase** via `CamelModel` (`alias_generator=to_camel`, `from_attributes=True`).
- **No business logic in routers.** Routers call `services/` only.
- **Long ops = Run + SSE.** Generation returns `202` + a run record via `mgr.submit(kind, work)`; the worker opens its OWN session bound to `request.app.state.engine`.
- **`build_model`/`llm_runner.py` is the only module that knows provider SDKs.** All native-search provider specifics live there, imported lazily per branch.
- **Suggestions are advisory.** They never become resume content; **fact-lock does not apply**.
- **Search defaults:** `search_mode="auto"`; unsupported native providers use one keyless DDGS fallback. `advisor_model` blank → `premium_model`.
- **A new table needs no ALTER migration** — `init_db` (`db.py`) calls `SQLModel.metadata.create_all`, which creates any table whose model is imported into metadata (`tables` is imported in `db.py`). Only column adds use `tracking/migrate.py`.
- **OpenAPI is generated, drift-gated.** After schema changes run `bash scripts/gen_ts_client.sh`; `tests/api/test_openapi_contract.py` must stay green.

---

## Engineering-review corrections (authoritative)

The following corrections supersede any later snippet that conflicts with them:

1. **Keep the search seam narrow.** V1 supports provider-native search plus one
   DDGS-backed Agno tool fallback. Remove `search_provider`, Tavily/Exa keys, and
   their speculative factory branches. Add the optional `ddgs` runtime dependency
   explicitly. Validate `search_mode` as a literal; `native` fails for unsupported
   providers, while `auto` falls back. `off` makes generation unavailable rather
   than silently producing ungrounded advice.
2. **Server owns context.** POST accepts only `{kind, key}`. Resolve the canonical
   skill/theme, members, demanding jobs, display label, and profile context from
   Spec A's demand graph on the server. Reject unknown keys. Never accept member
   skills or job context from the browser.
3. **One context and fingerprint path.** Introduce a pure
   `resolve_suggestion_context(...)` used by generation and cached GET. Fingerprint
   `(schema_version, kind, key, coverage, members, demanding_job_ids)`. This fixes
   the draft plan's always-stale theme rows and stale skill advice after target
   jobs change.
4. **Ground links at the boundary.** Parse URLs with `urllib.parse`; allow only
   `http`/`https`. Keep a resource only when its normalized URL occurs in the
   stage-1 evidence. Require a useful formatter result instead of persisting an
   empty draft. Parse GitHub URLs using an exact `github.com` host and validated
   path segments; dedupe repos.
5. **Preserve last good cache on infrastructure failure.** GitHub 404 means a dead
   repo and is dropped. Network, auth, rate-limit, 5xx, malformed JSON, or formatter
   failures fail the Run and leave the cached row unchanged.
6. **Enforce uniqueness in the database.** Add a composite unique constraint on
   `(kind, key)` and perform an update-in-place upsert. `kind` is a closed
   `"skill" | "theme"` literal in service and API models.
7. **Use a cache key that can actually be invalidated.** The existing
   `useLaunchRun` accepts string key segments and invalidates `[segment]`.
   Therefore `suggestionQueryKey(kind, key)` returns one string and both `useQuery`
   and `launch(..., invalidate)` wrap that same string once. Do not join an array
   after using the unjoined array as the query key.
8. **Expose run and request states.** The drawer must render loading skeleton,
   query error/retry, generating/disabled, cached, stale, and empty states. Render
   citations. Theme learning-path entry must be wired from Spec A's theme
   selection, not merely mentioned in a comment. Add keyboard and axe coverage.

Tasks 1–9 depend on Spec A's demand-graph/context resolver contracts; only the
provider-search and generic agent primitives can land independently.

---

## File Structure

| Path | Responsibility |
|------|----------------|
| `src/resume_agent/config.py` | **Add** validated `search_mode` and `advisor_model` to `Settings`. (`github_token` already exists.) |
| `pyproject.toml`, `uv.lock` | **Add** the DDGS search-tool runtime dependency. |
| `src/resume_agent/llm_runner.py` | **Add** `plan_search` (pure decision) + `build_search_equipped` (model+tools) + native-search constants. |
| `src/resume_agent/suggestions/agents.py` | **New.** `SuggestionDraft` + nested models; `build_search_agent`, `build_formatter_agent`. |
| `src/resume_agent/github/repos.py` | **New.** `RepoMeta`, `parse_github_url`, `verify_repo`. |
| `src/resume_agent/services/suggestions.py` | **New.** `generate_suggestion`, `suggestion_fingerprint`, context-prompt helpers, upsert. |
| `src/resume_agent/tracking/tables.py` | **Add** `SkillSuggestion` table. |
| `src/resume_agent/api/schemas/suggestions.py` | **New.** camelCase `SuggestionOut` + envelope. |
| `src/resume_agent/api/routers/suggestions.py` | **New.** `POST /suggestions/generate` (Run) + `GET /suggestions`. |
| `src/resume_agent/api/app.py` | **Add** router registration. |
| `web/src/features/match-gap/use-suggestion.ts` | **New.** query + generate hooks. |
| `web/src/features/match-gap/SuggestionPanel.tsx` | **New.** rendered suggestion. |
| `web/src/features/match-gap/SkillDrawer.tsx` | **Modify** (Spec A's file) to host the suggestion section + theme learning-path. |

---

## Task 1: Settings additions

**Files:**
- Modify: `src/resume_agent/config.py`
- Modify: `pyproject.toml`, `uv.lock`
- Test: `tests/test_config_search.py` (new)

**Interfaces:**
- Produces on `Settings`: `search_mode:Literal["auto","native","tool","off"]="auto"`, `advisor_model:str=""`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config_search.py
import pytest
from pydantic import ValidationError

from resume_agent.config import Settings


def test_search_settings_defaults():
    s = Settings()
    assert s.search_mode == "auto"
    assert s.advisor_model == ""


def test_search_mode_rejects_unknown_value():
    with pytest.raises(ValidationError):
        Settings(search_mode="typo")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config_search.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'search_mode'`.

- [ ] **Step 3: Write minimal implementation**

In `src/resume_agent/config.py`, add inside `Settings` (after `llm_retry_delay`):

```python
    # Gap-closing advisor (Spec B).
    search_mode: Literal["auto", "native", "tool", "off"] = "auto"
    advisor_model: str = ""  # blank -> premium_model
```

Add the required `Literal`, `pytest`, and `ValidationError` imports in their
respective production/test files. Add `ddgs` through the project's dependency
workflow and commit the lockfile in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config_search.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/config.py tests/test_config_search.py
git commit -m "feat: add advisor search settings"
```

---

## Task 2: Search seam (`plan_search` + `build_search_equipped`)

**Files:**
- Modify: `src/resume_agent/llm_runner.py`
- Test: `tests/test_search_seam.py` (new)

**Interfaces:**
- Consumes: existing `split_provider`, `build_model`, `resolve_api_key`, `get_settings`.
- Produces:
  - `ANTHROPIC_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}`
  - `OPENAI_WEB_SEARCH_TOOL = {"type": "web_search_preview"}`
  - `@dataclass(frozen=True) SearchPlan(provider:str, strategy:SearchStrategy)`
  - `plan_search(model_id:str, mode:SearchMode) -> SearchPlan` (pure)
  - `build_search_equipped(model_id:str, mode:str|None=None) -> tuple[Any, list]` (model, tools)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search_seam.py
import pytest

from resume_agent.llm_runner import (
    ANTHROPIC_WEB_SEARCH_TOOL,
    OPENAI_WEB_SEARCH_TOOL,
    build_search_equipped,
    plan_search,
)


def test_plan_auto_anthropic_native_server_tool():
    p = plan_search("claude-opus-4-8", "auto")
    assert p.strategy == "native_anthropic"


def test_plan_auto_gemini_sets_search_kwarg():
    p = plan_search("gemini:gemini-2.0-flash", "auto")
    assert p.strategy == "native_gemini"


def test_plan_auto_openai_uses_responses_variant():
    p = plan_search("openai:gpt-4o", "auto")
    assert p.strategy == "native_openai"


def test_plan_auto_deepseek_falls_back_to_tool():
    p = plan_search("deepseek:deepseek-chat", "auto")
    assert p.strategy == "tool"


def test_plan_tool_mode_forces_tool_for_anthropic():
    p = plan_search("claude-opus-4-8", "tool")
    assert p.strategy == "tool"


def test_plan_native_mode_unsupported_provider_raises():
    with pytest.raises(ValueError):
        plan_search("deepseek:deepseek-chat", "native")


def test_plan_off_mode_no_search():
    p = plan_search("claude-opus-4-8", "off")
    assert p.strategy == "none"


def test_build_off_mode_disables_advisor():
    with pytest.raises(ValueError, match="disabled"):
        build_search_equipped("claude-opus-4-8", "off")


def test_build_search_equipped_anthropic_returns_server_tool():
    model, tools = build_search_equipped("claude-opus-4-8", "auto")
    assert ANTHROPIC_WEB_SEARCH_TOOL in tools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_search_seam.py -v`
Expected: FAIL — `ImportError: cannot import name 'plan_search'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/llm_runner.py`:

```python
from dataclasses import dataclass
from typing import Literal

ANTHROPIC_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
OPENAI_WEB_SEARCH_TOOL = {"type": "web_search_preview"}

SearchMode = Literal["auto", "native", "tool", "off"]
SearchStrategy = Literal[
    "none", "tool", "native_anthropic", "native_openai", "native_gemini"
]
_NATIVE_PROVIDERS = {"anthropic", "openai", "gemini"}


@dataclass(frozen=True)
class SearchPlan:
    provider: str
    strategy: SearchStrategy


def plan_search(model_id: str, mode: SearchMode) -> SearchPlan:
    """Pure decision: how to give ``model_id`` web search under ``mode``."""
    provider, _ = split_provider(model_id)
    if mode == "off":
        return SearchPlan(provider, "none")
    if mode == "tool":
        return SearchPlan(provider, "tool")

    native_ok = provider in _NATIVE_PROVIDERS
    if mode == "native" and not native_ok:
        raise ValueError(f"search_mode=native but provider {provider!r} has no native web search")
    if not native_ok:
        return SearchPlan(provider, "tool")
    strategy: dict[str, SearchStrategy] = {
        "anthropic": "native_anthropic",
        "openai": "native_openai",
        "gemini": "native_gemini",
    }
    return SearchPlan(provider, strategy[provider])


def build_search_equipped(model_id: str, mode: SearchMode | None = None):
    """Return ``(model, tools)`` for the configured search strategy."""
    settings = get_settings()
    plan = plan_search(model_id, mode or settings.search_mode)
    _provider, model_name = split_provider(model_id)
    key = resolve_api_key(model_id) or None

    if plan.strategy == "native_openai":
        from agno.models.openai import OpenAIResponses

        return OpenAIResponses(id=model_name, api_key=key), [OPENAI_WEB_SEARCH_TOOL]
    if plan.strategy == "native_gemini":
        from agno.models.google import Gemini

        return Gemini(id=model_name, api_key=key, search=True), []
    model = build_model(model_id)
    if plan.strategy == "native_anthropic":
        return model, [ANTHROPIC_WEB_SEARCH_TOOL]
    if plan.strategy == "tool":
        from agno.tools.duckduckgo import DuckDuckGoTools

        return model, [DuckDuckGoTools()]
    raise ValueError("advisor web search is disabled by search_mode=off")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_search_seam.py -v`
Expected: PASS. (The anthropic `build_search_equipped` case only constructs a `Claude` model object — no network.)

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/llm_runner.py tests/test_search_seam.py
git commit -m "feat: native/tool web-search seam"
```

---

## Task 3: `SkillSuggestion` table

**Files:**
- Modify: `src/resume_agent/tracking/tables.py`
- Test: `tests/test_skill_suggestion_table.py` (new)

**Interfaces:**
- Produces: `SkillSuggestion(SQLModel, table=True)` with `id, kind, key, payload_json(JSON), fingerprint, generated_at`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_suggestion_table.py
from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.tables import SkillSuggestion


def test_skill_suggestion_table_created_by_init_db():
    engine = make_engine("sqlite://")
    init_db(engine)  # create_all must create the new table
    with Session(engine) as s:
        row = SkillSuggestion(
            kind="skill", key="Kubernetes",
            payload_json={"repos": [], "resources": [], "project": None, "bridge": "", "citations": []},
            fingerprint="abc123",
        )
        s.add(row)
        s.commit()
        got = s.exec(select(SkillSuggestion).where(SkillSuggestion.key == "Kubernetes")).one()
        assert got.kind == "skill"
        assert got.payload_json["bridge"] == ""
        assert got.generated_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_suggestion_table.py -v`
Expected: FAIL — `ImportError: cannot import name 'SkillSuggestion'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/resume_agent/tracking/tables.py`:

```python
class SkillSuggestion(SQLModel, table=True):
    __tablename__ = cast(Any, "skill_suggestions")
    __table_args__ = (UniqueConstraint("kind", "key", name="uq_skill_suggestion_kind_key"),)

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)  # "skill" | "theme"
    key: str = Field(index=True)   # canonical skill display, or theme id
    payload_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    fingerprint: str = ""
    generated_at: datetime = Field(default_factory=utcnow)
    schema_version: int = 1
```

Import `UniqueConstraint` from SQLAlchemy. Add a test that two concurrent or
sequential inserts with the same `(kind, key)` raise `IntegrityError`; querying by
`key` alone is insufficient because a skill display and theme id may coincide.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skill_suggestion_table.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tracking/tables.py tests/test_skill_suggestion_table.py
git commit -m "feat: add skill_suggestions table"
```

---

## Task 4: Suggestion agents + `SuggestionDraft`

**Files:**
- Create: `src/resume_agent/suggestions/__init__.py` (empty), `src/resume_agent/suggestions/agents.py`
- Test: `tests/test_suggestion_agents.py` (new)

**Interfaces:**
- Consumes: `build_search_equipped` (Task 2), existing `AgentRunner`, `build_model`, `use_json_mode_for`, `retry_kwargs`, `get_settings`, `ExtensibleModel`, `Runner`.
- Produces:
  - `RepoRef{name:str, url:str, why:str}`, `ResourceRef{title:str, url:str, kind:str}`, `ProjectIdea{title:str, summary:str, skills_demonstrated:list[str]}`
  - `SuggestionDraft{repos:list[RepoRef], resources:list[ResourceRef], project:ProjectIdea|None, bridge:str, citations:list[str]}`
  - `build_search_agent() -> Runner` (search-equipped, no schema)
  - `build_formatter_agent() -> Runner` (schema-only → `SuggestionDraft`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_suggestion_agents.py
from resume_agent.suggestions.agents import (
    ProjectIdea,
    RepoRef,
    SuggestionDraft,
    build_formatter_agent,
    build_search_agent,
)


def test_suggestion_draft_defaults():
    d = SuggestionDraft()
    assert d.repos == [] and d.resources == [] and d.project is None
    assert d.bridge == "" and d.citations == []


def test_suggestion_draft_roundtrips_nested():
    d = SuggestionDraft(
        repos=[RepoRef(name="kubernetes/kubernetes", url="https://github.com/kubernetes/kubernetes", why="ref")],
        project=ProjectIdea(title="Mini k8s", summary="build a scheduler", skills_demonstrated=["Go"]),
        bridge="You know Docker, so...",
        citations=["https://kubernetes.io"],
    )
    assert d.repos[0].name == "kubernetes/kubernetes"
    assert d.project.skills_demonstrated == ["Go"]


def test_builders_return_runners(monkeypatch):
    # Avoid constructing real provider models: stub build_search_equipped + build_model.
    import resume_agent.suggestions.agents as agents_mod

    monkeypatch.setattr(agents_mod, "build_search_equipped", lambda *a, **k: (object(), []))
    monkeypatch.setattr(agents_mod, "build_model", lambda *a, **k: object())
    search = build_search_agent()
    fmt = build_formatter_agent()
    assert hasattr(search, "run") and hasattr(fmt, "run")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_suggestion_agents.py -v`
Expected: FAIL — `ModuleNotFoundError: ...suggestions.agents`.

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/suggestions/__init__.py` (empty file). Then:

```python
# src/resume_agent/suggestions/agents.py
"""Two-stage advisor agents: a search-equipped researcher + a schema formatter."""

from typing import Literal

from agno.agent import Agent
from pydantic import Field

from resume_agent.config import get_settings
from resume_agent.llm_runner import (
    AgentRunner,
    Runner,
    build_model,
    build_search_equipped,
    retry_kwargs,
    use_json_mode_for,
)
from resume_agent.models.base import ExtensibleModel


class RepoRef(ExtensibleModel):
    name: str = ""
    url: str = ""
    why: str = ""


class ResourceRef(ExtensibleModel):
    title: str = ""
    url: str = ""
    kind: Literal["course", "doc", "tutorial"] = "doc"


class ProjectIdea(ExtensibleModel):
    title: str = ""
    summary: str = ""
    skills_demonstrated: list[str] = Field(default_factory=list)


class SuggestionDraft(ExtensibleModel):
    repos: list[RepoRef] = Field(default_factory=list)
    resources: list[ResourceRef] = Field(default_factory=list)
    project: ProjectIdea | None = None
    bridge: str = ""
    citations: list[str] = Field(default_factory=list)


_SEARCH_INSTRUCTIONS = [
    "You research how a job-seeker can close a specific skill gap.",
    "Use web search to find real, currently-existing GitHub repositories and learning resources.",
    "Prefer well-known reference implementations, awesome-lists, and official docs/courses.",
    "Report each resource with its real URL. Do not invent URLs.",
    "End with a short list of the source URLs you used.",
]

_FORMAT_INSTRUCTIONS = [
    "You convert a research write-up into the structured suggestion schema.",
    "Put GitHub links in repos; courses/docs/tutorials in resources with a kind.",
    "Propose one concrete portfolio project. Write the profile-bridge framing in bridge.",
    "Copy source URLs into citations. Use only URLs present in the input.",
]


def _advisor_model_id() -> str:
    s = get_settings()
    return s.advisor_model or s.premium_model


def build_search_agent() -> Runner:
    model, tools = build_search_equipped(_advisor_model_id())
    return AgentRunner(
        Agent(
            model=model,
            tools=tools,
            description="You research gap-closing resources with web search.",
            instructions=_SEARCH_INSTRUCTIONS,
            **retry_kwargs(),
        )
    )


def build_formatter_agent() -> Runner:
    s = get_settings()
    model = build_model(s.cheap_model)
    return AgentRunner(
        Agent(
            model=model,
            description="You format research into the suggestion schema.",
            instructions=_FORMAT_INSTRUCTIONS,
            output_schema=SuggestionDraft,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_suggestion_agents.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/suggestions/ tests/test_suggestion_agents.py
git commit -m "feat: two-stage advisor agents"
```

---

## Task 5: GitHub verification (`github/repos.py`)

**Files:**
- Create: `src/resume_agent/github/__init__.py` (empty), `src/resume_agent/github/repos.py`
- Test: `tests/test_github_repos.py` (new)

**Interfaces:**
- Produces:
  - `@dataclass RepoMeta(full_name:str, url:str, stars:int, description:str|None)`
  - `parse_github_url(url:str) -> tuple[str,str] | None` (owner, name)
  - `verify_repo(owner:str, name:str, *, token:str="") -> RepoMeta | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_github_repos.py
import httpx
import pytest

from resume_agent.github.repos import RepoMeta, parse_github_url, verify_repo


def test_parse_github_url_variants():
    assert parse_github_url("https://github.com/kubernetes/kubernetes") == ("kubernetes", "kubernetes")
    assert parse_github_url("http://github.com/foo/bar/") == ("foo", "bar")
    assert parse_github_url("https://github.com/foo/bar/tree/main") == ("foo", "bar")
    assert parse_github_url("https://example.com/foo/bar") is None
    assert parse_github_url("https://github.com/foo") is None


def test_verify_repo_ok(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(
            200,
            json={"full_name": "foo/bar", "html_url": "https://github.com/foo/bar",
                  "stargazers_count": 42, "description": "a repo"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    meta = verify_repo("foo", "bar")
    assert meta == RepoMeta("foo/bar", "https://github.com/foo/bar", 42, "a repo")


def test_verify_repo_404(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(404, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)
    assert verify_repo("foo", "ghost") is None


def test_verify_repo_network_error_fails_generation(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPError):
        verify_repo("foo", "bar")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_github_repos.py -v`
Expected: FAIL — `ModuleNotFoundError: ...github.repos`.

- [ ] **Step 3: Write minimal implementation**

Create `src/resume_agent/github/__init__.py` (empty). Then:

```python
# src/resume_agent/github/repos.py
"""Verify + enrich GitHub repos via the public API. Faked offline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import httpx

_GH_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass
class RepoMeta:
    full_name: str
    url: str
    stars: int
    description: str | None


def parse_github_url(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "github.com":
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, name = parts[:2]
    if name.endswith(".git"):
        name = name[:-4]
    if not _GH_PART.fullmatch(owner) or not _GH_PART.fullmatch(name):
        return None
    return owner, name


def verify_repo(owner: str, name: str, *, token: str = "") -> RepoMeta | None:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.get(
        f"https://api.github.com/repos/{owner}/{name}", headers=headers, timeout=10.0
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("GitHub repository response must be an object")
    return RepoMeta(
        full_name=data.get("full_name", f"{owner}/{name}"),
        url=data.get("html_url", f"https://github.com/{owner}/{name}"),
        stars=int(data.get("stargazers_count", 0)),
        description=data.get("description"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_github_repos.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/github/ tests/test_github_repos.py
git commit -m "feat: github repo verification"
```

---

## Task 6: Generation service (`services/suggestions.py`)

**Files:**
- Create: `src/resume_agent/services/suggestions.py`
- Test: `tests/test_services_suggestions.py` (new)

**Interfaces:**
- Consumes: `SuggestionDraft`/`RepoRef` (Task 4), `parse_github_url`/`RepoMeta` (Task 5), `profile_skill_tokens` (existing in `tracking/match_gap.py`), `SkillSuggestion` (Task 3).
- Produces:
  - `SuggestionContext(kind, key, label, members, demanding_job_ids, jobs_context)`
  - `resolve_suggestion_context(graph, *, kind, key) -> SuggestionContext`
  - `suggestion_fingerprint(context, coverage, schema_version=1) -> str`
  - `RepoVerifier = Callable[[str, str], RepoMeta | None]`
  - `generate_suggestion(session, *, context, search_agent, formatter, verify, facts, reporter=None) -> SkillSuggestion`

`resolve_suggestion_context` is mandatory pure service code, not router logic. For
a skill it matches the canonical display key in the demand graph and collects its
edge job IDs. For a theme it resolves the theme id, member skills, and the union
of their edge job IDs. It sorts all members/job IDs for deterministic prompts and
fingerprints and raises a domain not-found error for unknown keys. Both POST and
GET call this same function.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_suggestions.py
from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.github.repos import RepoMeta
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.suggestions.agents import ProjectIdea, RepoRef, SuggestionDraft
from resume_agent.services.suggestions import (
    SuggestionContext,
    generate_suggestion,
    suggestion_fingerprint,
)
from resume_agent.tracking.tables import SkillSuggestion


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self._c = content

    def run(self, prompt):
        return _Result(self._c)


def _facts():
    return ProfileFacts(contact=Contact(name="A"), skills={"infra": [Skill(name="Docker")]})


def _engine():
    e = make_engine("sqlite://")
    init_db(e)
    return e


def test_fingerprint_changes_with_coverage():
    context = SuggestionContext(
        kind="skill", key="Kubernetes", label="Kubernetes",
        members=("Kubernetes",), demanding_job_ids=(1,), jobs_context="C — T",
    )
    a = suggestion_fingerprint(context, {"docker"})
    b = suggestion_fingerprint(context, {"docker", "kubernetes"})
    assert a != b


def test_generate_verifies_repos_and_persists():
    draft = SuggestionDraft(
        repos=[
            RepoRef(name="ok", url="https://github.com/foo/bar", why="ref"),
            RepoRef(name="dead", url="https://github.com/foo/ghost", why="x"),
            RepoRef(name="notgh", url="https://example.com/x", why="x"),
        ],
        project=ProjectIdea(title="P", summary="s", skills_demonstrated=["Go"]),
        bridge="You know Docker...",
        citations=["https://k8s.io"],
    )

    def verify(owner, name):
        return RepoMeta("foo/bar", "https://github.com/foo/bar", 9, "d") if name == "bar" else None

    engine = _engine()
    with Session(engine) as s:
        row = generate_suggestion(
            s, context=SuggestionContext(
                kind="skill", key="Kubernetes", label="Kubernetes",
                members=("Kubernetes",), demanding_job_ids=(1,), jobs_context="C — T",
            ),
            search_agent=_Agent("Research: https://github.com/foo/bar https://k8s.io"),
            formatter=_Agent(draft),
            verify=verify, facts=_facts(),
        )
        assert [r["url"] for r in row.payload_json["repos"]] == ["https://github.com/foo/bar"]
        assert row.payload_json["repos"][0]["stars"] == 9
        assert row.payload_json["project"]["title"] == "P"
        assert row.kind == "skill" and row.key == "Kubernetes"

        # upsert: a second run replaces, not duplicates
        generate_suggestion(
            s, context=SuggestionContext(
                kind="skill", key="Kubernetes", label="Kubernetes",
                members=("Kubernetes",), demanding_job_ids=(1,), jobs_context="C — T",
            ),
            search_agent=_Agent("prose2"), formatter=_Agent(SuggestionDraft(bridge="v2")),
            verify=verify, facts=_facts(),
        )
        rows = s.exec(select(SkillSuggestion).where(SkillSuggestion.key == "Kubernetes")).all()
        assert len(rows) == 1
        assert rows[0].payload_json["bridge"] == "v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_suggestions.py -v`
Expected: FAIL — `ModuleNotFoundError: ...services.suggestions`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/services/suggestions.py
"""Use-case: generate + cache a gap-closing suggestion (search -> format -> verify)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import urlsplit, urlunsplit

from sqlmodel import Session, select

from resume_agent.github.repos import RepoMeta
from resume_agent.github.repos import parse_github_url
from resume_agent.models.profile import ProfileFacts
from resume_agent.suggestions.agents import SuggestionDraft
from resume_agent.tracking.match_gap import DemandGraph, profile_skill_tokens
from resume_agent.tracking.tables import SkillSuggestion, utcnow

RepoVerifier = Callable[[str, str], RepoMeta | None]


class SuggestionTargetNotFound(ValueError):
    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"unknown {kind} suggestion target: {key}")


@dataclass(frozen=True)
class SuggestionContext:
    kind: Literal["skill", "theme"]
    key: str
    label: str
    members: tuple[str, ...]
    demanding_job_ids: tuple[int, ...]
    jobs_context: str


def resolve_suggestion_context(
    graph: DemandGraph,
    *,
    kind: Literal["skill", "theme"],
    key: str,
) -> SuggestionContext:
    if kind == "skill":
        node = next((skill for skill in graph.skills if skill.skill == key), None)
        if node is None:
            raise SuggestionTargetNotFound(kind, key)
        label = node.skill
        members = (node.skill,)
    else:
        theme = next((theme for theme in graph.themes if theme.id == key), None)
        if theme is None:
            raise SuggestionTargetNotFound(kind, key)
        label = theme.label
        members = tuple(sorted(skill.skill for skill in graph.skills if skill.theme_id == key))

    member_set = set(members)
    job_ids = tuple(sorted({edge.job_id for edge in graph.edges if edge.skill in member_set}))
    jobs = {job.id: job for job in graph.jobs}
    jobs_context = "; ".join(
        f"{jobs[job_id].company or 'Unknown company'} — {jobs[job_id].title or 'Untitled role'}"
        for job_id in job_ids
        if job_id in jobs
    )
    return SuggestionContext(kind, key, label, members, job_ids, jobs_context)


def suggestion_fingerprint(
    context: SuggestionContext,
    coverage: set[str],
    schema_version: int = 1,
) -> str:
    payload = json.dumps(
        {
            "v": schema_version,
            "kind": context.kind,
            "key": context.key,
            "cov": sorted(coverage),
            "mem": sorted(context.members),
            "jobs": sorted(context.demanding_job_ids),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


_URL = re.compile(r"https?://[^\s<>\]\[()]+")


def _normalized_http_url(value: str) -> str | None:
    parsed = urlsplit(value.rstrip(".,;:"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


def _verified_repos(
    draft: SuggestionDraft,
    verify: RepoVerifier,
    evidence_urls: set[str],
) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for ref in draft.repos:
        normalized = _normalized_http_url(ref.url)
        if normalized is None or normalized not in evidence_urls:
            continue
        parsed = parse_github_url(ref.url)
        if not parsed:
            continue
        meta = verify(*parsed)
        if meta is None:
            continue
        if meta.full_name in seen:
            continue
        seen.add(meta.full_name)
        out.append({
            "name": meta.full_name, "url": meta.url, "why": ref.why,
            "stars": meta.stars, "description": meta.description,
        })
    return out


def _payload_from_evidence(
    draft: SuggestionDraft,
    prose: str,
    verify: RepoVerifier,
) -> dict[str, Any]:
    evidence_urls = {
        normalized
        for raw in _URL.findall(prose)
        if (normalized := _normalized_http_url(raw)) is not None
    }
    project = (
        {
            "title": draft.project.title,
            "summary": draft.project.summary,
            "skills_demonstrated": draft.project.skills_demonstrated,
        }
        if draft.project is not None
        else None
    )
    return {
        "repos": _verified_repos(draft, verify, evidence_urls),
        "resources": [
            {"title": r.title, "url": normalized, "kind": r.kind}
            for r in draft.resources
            if (normalized := _normalized_http_url(r.url)) in evidence_urls
        ],
        "project": project,
        "bridge": draft.bridge,
        "citations": sorted(evidence_urls),
    }


def _search_prompt(kind: str, key: str, members: list[str], jobs_context: str) -> str:
    if kind == "theme":
        return (
            f"Theme: {key}. Member skills: {', '.join(members)}.\n"
            f"Jobs demanding these: {jobs_context}\n"
            "Research a learning path that closes this whole skill-set gap."
        )
    return (
        f"Skill gap: {key}.\nJobs demanding it: {jobs_context}\n"
        "Research how to learn it: real GitHub repos, courses/docs, and a project."
    )


def _format_prompt(prose: str, bridge_ctx: str) -> str:
    return f"Research:\n{prose}\n\nProfile context for the bridge framing:\n{bridge_ctx}"


def generate_suggestion(
    session: Session,
    *,
    context: SuggestionContext,
    search_agent,
    formatter,
    verify: RepoVerifier,
    facts: ProfileFacts,
    reporter=None,
) -> SkillSuggestion:
    coverage = profile_skill_tokens(facts)
    bridge_ctx = ", ".join(sorted(coverage)) or "(no profile skills on file)"

    prose = search_agent.run(
        _search_prompt(context.kind, context.label, context.members, context.jobs_context)
    ).content
    drafted = formatter.run(_format_prompt(str(prose), bridge_ctx)).content
    if not isinstance(drafted, SuggestionDraft):
        raise ValueError("advisor formatter did not return SuggestionDraft")
    draft = drafted
    if not (draft.repos or draft.resources or draft.project or draft.bridge.strip()):
        raise ValueError("advisor formatter returned an empty suggestion")

    payload = _payload_from_evidence(draft, str(prose), verify)
    fingerprint = suggestion_fingerprint(context, coverage)

    row = session.exec(
        select(SkillSuggestion).where(
            SkillSuggestion.kind == context.kind, SkillSuggestion.key == context.key
        )
    ).first()
    if row is None:
        row = SkillSuggestion(kind=context.kind, key=context.key)
        session.add(row)
    row.payload_json = payload
    row.fingerprint = fingerprint
    row.generated_at = utcnow()
    session.commit()
    session.refresh(row)
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_suggestions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/suggestions.py tests/test_services_suggestions.py
git commit -m "feat: generate_suggestion service"
```

---

## Task 7: API schemas (`api/schemas/suggestions.py`)

**Files:**
- Create: `src/resume_agent/api/schemas/suggestions.py`
- Test: `tests/api/test_schemas_suggestions.py` (new)

**Interfaces:**
- Consumes: `CamelModel`.
- Produces (all `CamelModel`): `RepoOut`, `ResourceOut`, `ProjectOut`, `SuggestionOut`, `SuggestionEnvelope`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_schemas_suggestions.py
from datetime import datetime, timezone

from resume_agent.api.schemas.suggestions import SuggestionEnvelope, SuggestionOut


def test_suggestion_out_camelizes_nested():
    out = SuggestionOut(
        kind="skill", key="Kubernetes",
        repos=[{"name": "foo/bar", "url": "u", "why": "w", "stars": 3, "description": "d"}],
        resources=[{"title": "t", "url": "u", "kind": "doc"}],
        project={"title": "P", "summary": "s", "skills_demonstrated": ["Go"]},
        bridge="b", citations=["c"],
        generated_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    dumped = out.model_dump(by_alias=True)
    assert dumped["project"]["skillsDemonstrated"] == ["Go"]
    assert "generatedAt" in dumped


def test_envelope_allows_null():
    env = SuggestionEnvelope(suggestion=None, stale=False)
    assert env.model_dump(by_alias=True) == {"suggestion": None, "stale": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_suggestions.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/api/schemas/suggestions.py
"""Gap-closing advisor API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl

from resume_agent.api.schemas.base import CamelModel


class RepoOut(CamelModel):
    name: str
    url: AnyHttpUrl
    why: str
    stars: int | None = None
    description: str | None = None


class ResourceOut(CamelModel):
    title: str
    url: AnyHttpUrl
    kind: Literal["course", "doc", "tutorial"]


class ProjectOut(CamelModel):
    title: str
    summary: str
    skills_demonstrated: list[str]


class SuggestionOut(CamelModel):
    kind: Literal["skill", "theme"]
    key: str
    repos: list[RepoOut]
    resources: list[ResourceOut]
    project: ProjectOut | None = None
    bridge: str
    citations: list[AnyHttpUrl]
    generated_at: datetime


class SuggestionEnvelope(CamelModel):
    suggestion: SuggestionOut | None = None
    stale: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_schemas_suggestions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/schemas/suggestions.py tests/api/test_schemas_suggestions.py
git commit -m "feat: advisor api schemas"
```

---

## Task 8: Router (`POST generate` Run + `GET` cached) + registration

**Files:**
- Create: `src/resume_agent/api/routers/suggestions.py`
- Modify: `src/resume_agent/api/app.py`
- Test: `tests/api/test_suggestions.py` (new)

**Interfaces:**
- Consumes: `generate_suggestion`/`suggestion_fingerprint` (Task 6), `build_search_agent`/`build_formatter_agent` (Task 4), `verify_repo` (Task 5), Task-7 schemas, `record_to_run`, `RunManager`, `load_facts`, `profile_skill_tokens`.
- Produces: `GET /api/suggestions?kind=&key=` → `SuggestionEnvelope`; `POST /api/suggestions/generate` → `RunOut` (202).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_suggestions.py
import time

from fastapi.testclient import TestClient

import resume_agent.api.routers.suggestions as router_mod
from resume_agent.api.app import create_app
from resume_agent.github.repos import RepoMeta
from resume_agent.suggestions.agents import RepoRef, SuggestionDraft
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self._c = content

    def run(self, prompt):
        return _Result(self._c)


def _seed_skill(engine):
    from resume_agent.db import get_session

    with get_session(engine) as session:
        save_job(session, Job(
            source="manual", company="C", title="T",
            status=JobStatus.shortlisted.value,
            criteria_json={"must_have_skills": ["Kubernetes"]},
        ))


def test_get_empty_when_none(monkeypatch):
    app = create_app(db_url="sqlite://")
    _seed_skill(app.state.engine)
    client = TestClient(app)
    with client:
        resp = client.get("/api/suggestions", params={"kind": "skill", "key": "Kubernetes"})
    assert resp.status_code == 200
    assert resp.json() == {"suggestion": None, "stale": False}


def test_generate_then_get(monkeypatch):
    draft = SuggestionDraft(
        repos=[RepoRef(name="ok", url="https://github.com/foo/bar", why="ref")],
        bridge="bridge", citations=["https://k8s.io"],
    )
    monkeypatch.setattr(
        router_mod,
        "build_search_agent",
        lambda: _Agent("Research: https://github.com/foo/bar"),
    )
    monkeypatch.setattr(router_mod, "build_formatter_agent", lambda: _Agent(draft))
    monkeypatch.setattr(
        router_mod, "verify_repo",
        lambda owner, name, token="": RepoMeta("foo/bar", "https://github.com/foo/bar", 5, "d"),
    )

    app = create_app(db_url="sqlite://")
    _seed_skill(app.state.engine)
    client = TestClient(app)
    with client:
        resp = client.post("/api/suggestions/generate", json={"kind": "skill", "key": "Kubernetes"})
        assert resp.status_code == 202
        run_id = resp.json()["runId"]
        for _ in range(50):
            rec = client.get(f"/api/runs/{run_id}").json()
            if rec["state"] in ("done", "error"):
                break
            time.sleep(0.02)
        assert rec["state"] == "done"

        got = client.get("/api/suggestions", params={"kind": "skill", "key": "Kubernetes"}).json()
        assert got["suggestion"]["repos"][0]["url"] == "https://github.com/foo/bar"
        assert got["suggestion"]["repos"][0]["stars"] == 5
        assert got["stale"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_suggestions.py -v`
Expected: FAIL — `ModuleNotFoundError: ...routers.suggestions`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/resume_agent/api/routers/suggestions.py
"""Gap-closing advisor: cached GET + generation Run."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from resume_agent.api.deps import get_run_manager, get_session
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.runs import RunOut
from resume_agent.api.schemas.suggestions import SuggestionEnvelope, SuggestionOut
from resume_agent.db import get_session as open_session
from resume_agent.github.repos import verify_repo
from resume_agent.config import get_settings
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.store import load_facts
from resume_agent.services.suggestions import generate_suggestion, suggestion_fingerprint
from resume_agent.suggestions.agents import build_formatter_agent, build_search_agent
from resume_agent.tracking.match_gap import profile_skill_tokens
from resume_agent.tracking.tables import SkillSuggestion

router = APIRouter()

_FACTS_PATH = "data/profile/facts.json"
_CLUSTER_PATH = "data/profile/cluster_map.json"


class GenerateParams(BaseModel):
    kind: Literal["skill", "theme"]
    key: str = Field(min_length=1, max_length=200)


def _facts_or_empty() -> ProfileFacts:
    if Path(_FACTS_PATH).exists():
        return load_facts(_FACTS_PATH)
    return ProfileFacts(contact=Contact(name=""))


@router.get("/suggestions", response_model=SuggestionEnvelope)
def get_suggestion(
    kind: Literal["skill", "theme"],
    key: Annotated[str, Query(min_length=1, max_length=200)],
    session: Session = Depends(get_session),
):
    facts = _facts_or_empty()
    cluster_map = load_cluster_map(_CLUSTER_PATH)
    graph = build_demand_graph(session, facts, cluster_map)
    context = resolve_suggestion_context(
        graph,
        kind=kind,
        key=key,
    )
    row = session.exec(
        select(SkillSuggestion).where(
            SkillSuggestion.kind == kind, SkillSuggestion.key == key
        )
    ).first()
    if row is None:
        return SuggestionEnvelope(suggestion=None, stale=False)
    current = suggestion_fingerprint(context, profile_skill_tokens(facts))
    suggestion = SuggestionOut(
        kind=row.kind, key=row.key, generated_at=row.generated_at, **(row.payload_json or {})
    )
    return SuggestionEnvelope(suggestion=suggestion, stale=row.fingerprint != current)


@router.post("/suggestions/generate", response_model=RunOut, status_code=202)
def launch_generate(
    params: GenerateParams,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = request.app.state.engine
    s = get_settings()

    def work(reporter):
        reporter.begin(1, f"Researching {params.key}")
        search_agent = build_search_agent()
        formatter = build_formatter_agent()
        with open_session(engine) as session:
            facts = _facts_or_empty()
            cluster_map = load_cluster_map(_CLUSTER_PATH)
            graph = build_demand_graph(session, facts, cluster_map)
            context = resolve_suggestion_context(
                graph,
                kind=params.kind,
                key=params.key,
            )
            row = generate_suggestion(
                session,
                context=context,
                search_agent=search_agent,
                formatter=formatter,
                verify=lambda owner, name: verify_repo(owner, name, token=s.github_token),
                facts=facts,
                reporter=reporter,
            )
            result = {"kind": row.kind, "key": row.key}
        reporter.step(1)
        return result

    run_id = mgr.submit("suggestion", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)
```

In `src/resume_agent/api/app.py`, add the import (near the other router imports) and registration (near the others):

```python
from resume_agent.api.routers import suggestions as suggestions_router
```
```python
    app.include_router(suggestions_router.router, prefix="/api", dependencies=guarded)
```

Import `Annotated`/`Literal`, `Field`/`Query`, `_CLUSTER_PATH`, `load_cluster_map`,
`build_demand_graph`, and `resolve_suggestion_context`. Map the resolver's domain not-found error to the
project's normal API error envelope. Do not accept `members` in the request model.
Add populated skill and theme endpoint tests that seed target jobs and a cluster
map; the earlier draft test generated an arbitrary `Kubernetes` key against an
empty graph and must be updated to prove server-side validation.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_suggestions.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/routers/suggestions.py src/resume_agent/api/app.py tests/api/test_suggestions.py
git commit -m "feat: advisor generate + cached suggestion endpoints"
```

---

## Task 9: Regenerate OpenAPI + TS contract

**Files:**
- Modify (generated): `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts`
- Test: `tests/api/test_openapi_contract.py`

- [ ] **Step 1: Confirm drift**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: FAIL (new endpoints/schemas not in committed contract).

- [ ] **Step 2: Regenerate**

Run: `bash scripts/gen_ts_client.sh`
Expected: rewrites `contracts/openapi.json`, `contracts/ts/api.ts`, copies to `web/src/lib/api/schema.ts`.

- [ ] **Step 3: Confirm gate passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "chore: regenerate contract for advisor endpoints"
```

---

## Task 10: Frontend hooks (`use-suggestion.ts`)

**Files:**
- Create: `web/src/features/match-gap/use-suggestion.ts`
- Test: none new (thin glue; exercised by Task 11/12 tests).

**Interfaces:**
- Consumes: `api`/`unwrap` (`@/lib/api/client`), `useLaunchRun` (`@/features/runs/use-launch-run`), `useQuery`.
- Produces:
  - `useSuggestion(kind, key, enabled)` → query of `SuggestionEnvelope`
  - `useGenerateSuggestion()` → `{ generate(kind, key), generating }`

- [ ] **Step 1: Write the implementation**

```ts
// web/src/features/match-gap/use-suggestion.ts
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { useLaunchRun } from "@/features/runs/use-launch-run";
import { useRunStore } from "@/lib/runs/store";
import type { components } from "@/lib/api/schema";

export type SuggestionEnvelope = components["schemas"]["SuggestionEnvelope"];

type SuggestionKind = "skill" | "theme";

export function suggestionQueryKey(kind: SuggestionKind, key: string) {
  return `suggestion:${kind}:${key}`;
}

export function useSuggestion(kind: SuggestionKind, key: string | null, enabled: boolean) {
  const cacheKey = suggestionQueryKey(kind, key ?? "");
  return useQuery({
    queryKey: [cacheKey],
    enabled: enabled && !!key,
    queryFn: (): Promise<SuggestionEnvelope> =>
      unwrap(
        api.GET("/api/suggestions", { params: { query: { kind, key: key ?? "" } } }),
      ) as Promise<SuggestionEnvelope>,
  });
}

export function useGenerateSuggestion() {
  const { launch } = useLaunchRun();
  const generating = useRunStore((state) =>
    Object.values(state.runs).some(
      (run) => run.kind === "suggestion" && (run.status === "running" || run.status === "cancelling"),
    ),
  );
  const generate = (kind: SuggestionKind, key: string) =>
    launch(
      "suggestion",
      () => unwrap(api.POST("/api/suggestions/generate", { body: { kind, key } })),
      [suggestionQueryKey(kind, key)],
    );
  return { generate, generating };
}
```

The single-string key is intentional: the current `useLaunchRun` invalidates each
string as `[key]`, which now exactly matches the query. Add a hook test that starts
a completed fake Run and proves the cached envelope refetches.

- [ ] **Step 2: Type-check**

Run: `cd web && npx tsc -b --noEmit`
Expected: no errors (types come from the regenerated schema).

- [ ] **Step 3: Commit**

```bash
git add web/src/features/match-gap/use-suggestion.ts
git commit -m "feat: suggestion hooks"
```

---

## Task 11: `SuggestionPanel.tsx`

**Files:**
- Create: `web/src/features/match-gap/SuggestionPanel.tsx`
- Test: `web/src/features/match-gap/SuggestionPanel.test.tsx` (new)

**Interfaces:**
- Consumes: `SuggestionEnvelope` type (Task 10).
- Produces: `SuggestionPanel({ envelope, isLoading, isError, onRetry, onGenerate, generating })`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/features/match-gap/SuggestionPanel.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SuggestionPanel } from "./SuggestionPanel";

const envelope = {
  stale: false,
  suggestion: {
    kind: "skill", key: "Kubernetes",
    repos: [{ name: "foo/bar", url: "https://github.com/foo/bar", why: "ref", stars: 42, description: "d" }],
    resources: [{ title: "K8s docs", url: "https://k8s.io", kind: "doc" }],
    project: { title: "Mini scheduler", summary: "build it", skillsDemonstrated: ["Go"] },
    bridge: "You know Docker, so Kubernetes is a short jump.",
    citations: ["https://k8s.io"],
    generatedAt: "2026-06-26T00:00:00Z",
  },
};

describe("SuggestionPanel", () => {
  it("renders repos, resources, project, and bridge", () => {
    render(<SuggestionPanel envelope={envelope} isLoading={false} onGenerate={() => {}} generating={false} />);
    expect(screen.getByText("foo/bar")).toBeInTheDocument();
    expect(screen.getByText(/42/)).toBeInTheDocument();
    expect(screen.getByText("K8s docs")).toBeInTheDocument();
    expect(screen.getByText("Mini scheduler")).toBeInTheDocument();
    expect(screen.getByText(/short jump/)).toBeInTheDocument();
  });

  it("shows a generate button when there is no suggestion", async () => {
    const onGenerate = vi.fn();
    render(
      <SuggestionPanel
        envelope={{ suggestion: null, stale: false }}
        isLoading={false}
        onGenerate={onGenerate}
        generating={false}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /how to close this gap/i }));
    expect(onGenerate).toHaveBeenCalled();
  });

  it("shows a stale badge + regenerate when stale", () => {
    render(
      <SuggestionPanel
        envelope={{ ...envelope, stale: true }}
        isLoading={false}
        onGenerate={() => {}}
        generating={false}
      />,
    );
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /regenerate/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/SuggestionPanel.test.tsx`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```tsx
// web/src/features/match-gap/SuggestionPanel.tsx
import { Button } from "@/components/ui/button";
import type { SuggestionEnvelope } from "./use-suggestion";

export function SuggestionPanel({
  envelope,
  isLoading,
  isError = false,
  onRetry = () => {},
  onGenerate,
  generating,
}: {
  envelope: SuggestionEnvelope | undefined;
  isLoading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  onGenerate: () => void;
  generating: boolean;
}) {
  const s = envelope?.suggestion;

  if (isLoading) {
    return (
      <div aria-busy="true" aria-label="Loading gap-closing advice" className="space-y-2">
        <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
        <div className="h-4 w-full animate-pulse rounded bg-muted" />
        <div className="h-4 w-5/6 animate-pulse rounded bg-muted" />
      </div>
    );
  }

  if (isError) {
    return (
      <div role="alert" className="space-y-2 text-sm">
        <p>Couldn't load cached advice.</p>
        <Button size="sm" variant="outline" onClick={onRetry}>Retry</Button>
      </div>
    );
  }

  if (!s) {
    return (
      <Button size="sm" disabled={generating} onClick={onGenerate}>
        {generating ? "Researching…" : "How to close this gap"}
      </Button>
    );
  }

  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-center gap-2">
        <h4 className="font-semibold">How to close this gap</h4>
        {envelope?.stale && (
          <span className="rounded border bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
            stale
          </span>
        )}
        <Button size="sm" variant="outline" disabled={generating} onClick={onGenerate}>
          {generating ? "Researching…" : "Regenerate"}
        </Button>
      </div>

      {s.bridge && <p className="text-muted-foreground">{s.bridge}</p>}

      {s.repos.length > 0 && (
        <div>
          <p className="font-medium">Repos to learn from</p>
          <ul className="space-y-1">
            {s.repos.map((r) => (
              <li key={r.url}>
                <a className="text-primary hover:underline" href={r.url} target="_blank" rel="noreferrer">
                  {r.name}
                </a>
                {typeof r.stars === "number" && <span className="text-muted-foreground"> · ★ {r.stars}</span>}
                {r.description && <span className="text-muted-foreground"> — {r.description}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {s.resources.length > 0 && (
        <div>
          <p className="font-medium">Resources</p>
          <ul className="space-y-1">
            {s.resources.map((r) => (
              <li key={r.url}>
                <a className="text-primary hover:underline" href={r.url} target="_blank" rel="noreferrer">
                  {r.title}
                </a>
                <span className="text-muted-foreground"> · {r.kind}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {s.project && (
        <div>
          <p className="font-medium">Build this</p>
          <p>{s.project.title}</p>
          <p className="text-muted-foreground">{s.project.summary}</p>
        </div>
      )}

      {s.citations.length > 0 && (
        <details>
          <summary className="cursor-pointer font-medium">Sources</summary>
          <ul className="mt-1 space-y-1 break-all text-xs">
            {s.citations.map((url) => (
              <li key={url}>
                <a className="text-primary underline" href={url} target="_blank" rel="noreferrer">
                  {url}
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/match-gap/SuggestionPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/match-gap/SuggestionPanel.tsx web/src/features/match-gap/SuggestionPanel.test.tsx
git commit -m "feat: suggestion panel"
```

---

## Task 12: Wire into `SkillDrawer` (Spec A's component)

**Files:**
- Modify: `web/src/features/match-gap/SkillDrawer.tsx` (created in Spec A)
- Test: `web/src/features/match-gap/SkillDrawer.test.tsx` (extend Spec A's test)

**Interfaces:**
- Consumes: `useSuggestion`/`useGenerateSuggestion` (Task 10), `SuggestionPanel` (Task 11).
- Produces: the drawer renders a `SuggestionPanel` for the open skill. (Theme learning-path entry is wired the same way with `kind="theme"`; the per-theme button in the dashboard sets the drawer's `kind`. For v1, the drawer accepts a `kind` prop defaulting to `"skill"`.)

> PREREQUISITE: Spec A Task 12 (`SkillDrawer.tsx`) must exist. If implementing B before A, stop here until A lands.

Spec A's container must already pass a discriminated selection with separate
`kind`, stable `key`, and display `label`. Add a theme-path integration test: click
a theme action, assert the drawer shows its label and union of demanding jobs,
then assert the advisor GET/POST use `kind=theme` and the theme id key. A defaulted
`kind` prop without a theme entry point does not satisfy this task.

- [ ] **Step 1: Write the failing test**

Add to `web/src/features/match-gap/SkillDrawer.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";

it("shows the generate button when no suggestion is cached", async () => {
  server.use(
    http.get("/api/suggestions", () => HttpResponse.json({ suggestion: null, stale: false })),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <SkillDrawer
        skill="Kubernetes"
        jobs={[{ id: 1, company: "Stripe", title: "Backend", seniority: "senior" }]}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("button", { name: /how to close this gap/i })).toBeInTheDocument();
});
```

> If Spec A's `SkillDrawer.test.tsx` does not already wrap in a `QueryClientProvider`, add the wrapper as shown (the drawer now issues a query).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/match-gap/SkillDrawer.test.tsx`
Expected: FAIL — no such button (drawer doesn't render `SuggestionPanel` yet).

- [ ] **Step 3: Write minimal implementation**

In `web/src/features/match-gap/SkillDrawer.tsx`, add the suggestion section. Add a `kind` prop (default `"skill"`), and render the panel below the jobs list:

```tsx
import { SuggestionPanel } from "./SuggestionPanel";
import { useGenerateSuggestion, useSuggestion } from "./use-suggestion";

// ...inside the component signature, add `kind = "skill"`:
export function SkillDrawer({
  skill,
  jobs,
  onClose,
  kind = "skill",
}: {
  skill: string | null;
  jobs: Job[];
  onClose: () => void;
  kind?: "skill" | "theme";
}) {
  const { data: envelope, isLoading, isError, refetch } = useSuggestion(
    kind, skill, skill !== null
  );
  const { generate, generating } = useGenerateSuggestion();

  // ...within <SheetContent>, after the <ul> of jobs:
  // <div className="mt-6 border-t pt-4">
  //   <SuggestionPanel
  //     envelope={envelope}
  //     isLoading={isLoading}
  //     generating={false}
  //     onGenerate={() => skill && generate(kind, skill)}
  //   />
  // </div>
}
```

Concretely, splice this block in immediately before `</SheetContent>` and add `kind = "skill"` to the destructured props plus the two hooks at the top of the component:

```tsx
        <div className="mt-6 border-t pt-4">
          <SuggestionPanel
            envelope={envelope}
            isLoading={isLoading}
            generating={generating}
            isError={isError}
            onRetry={() => void refetch()}
            onGenerate={() => skill && generate(kind, skill)}
          />
        </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/match-gap/SkillDrawer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Full frontend gate + commit**

Run: `cd web && npm run test:run && npm run lint && npx tsc -b --noEmit`
Expected: PASS.

```bash
git add web/src/features/match-gap/SkillDrawer.tsx web/src/features/match-gap/SkillDrawer.test.tsx
git commit -m "feat: advisor panel in skill drawer"
```

---

## Final verification

- [ ] **Backend suite + lint**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all green (including the OpenAPI contract gate).

- [ ] **Frontend suite + lint + typecheck**

Run: `cd web && npm run test:run && npm run lint && npx tsc -b --noEmit`
Expected: all green.

---

## Self-Review

**Spec coverage:**
- §2.1/§2.2 native-vs-tool per provider, `auto` default → Task 2 (`plan_search` covers anthropic/openai/gemini/deepseek + native/tool/off). ✔
- §2.3 new Settings (`github_token` already existed) → Task 1. ✔
- §3 two-stage synthesis (search agent no-schema → formatter schema) → Task 4 + Task 6 (`generate_suggestion` calls both). ✔
- §3.1 `SuggestionDraft` shape → Task 4. ✔
- §4 service + context assembly + Run endpoints → Tasks 6, 8. ✔
- §5 `SkillSuggestion` table + fingerprint staleness (no ALTER needed; `create_all`) → Tasks 3, 6, 8 (GET recomputes fingerprint). ✔
- §6 GitHub verify (enrich ★/desc, drop dead) → Task 5 + Task 6 `_verified_repos`. ✔
- §7 camelCase schemas + contract regen → Tasks 7, 9. ✔
- §8 frontend hooks + `SuggestionPanel` + `SkillDrawer` wiring + theme learning-path (via `kind` prop) → Tasks 10, 11, 12. ✔
- §9 offline tests (faked agents/github/httpx) → every backend task. ✔
- §10 out-of-scope advisory/fact-lock → no resume mutation anywhere. ✔

**Review status:** The previous theme-staleness and query-invalidation
"simplifications" were correctness bugs and are now mandatory fixes. Treat code
blocks as implementation scaffolding together with the authoritative review
corrections; do not copy a block that omits the shared context resolver, evidence
validation, or error handling.

**Type consistency:** `SuggestionDraft`/`RepoRef`/`ResourceRef`/`ProjectIdea` names are identical across Tasks 4/6. `generate_suggestion` accepts one server-resolved `SuggestionContext`; POST and GET both call the same resolver. `SuggestionEnvelope`/`SuggestionOut` fields match between Python and generated TypeScript. `kind` is the same closed `"skill"|"theme"` literal across service, router, and drawer.

**Dependency note:** Search planning and generic agent/GitHub primitives can land
before Spec A. Context resolution, generation, endpoints, staleness, and all
frontend work depend on Spec A's demand graph, cluster map, and skill/theme
selection contracts.
