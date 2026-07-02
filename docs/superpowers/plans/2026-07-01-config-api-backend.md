# Config API Backend (Phase 1 of dashboard/wizard/config) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Storage-agnostic config/secrets/documents/setup-status/profile-build/dashboard-summary HTTP contract over the existing YAML files, so the web app can manage every config.

**Architecture:** A `ConfigStore` seam (`services/config_store.py`) maps config _domains_ to YAML/text files behind typed `CamelModel` schemas; routers depend on the seam, never on paths. Secrets and model ids ride the existing `setup/env_writer` merge logic with a settings-refresh hook. Documents get a manifest-backed store under `data/profile/documents/`. Profile build becomes a Run via the existing `RunManager`.

**Tech Stack:** FastAPI, Pydantic v2 (`CamelModel`), SQLModel, pytest (offline), existing `RunManager`/`ProgressReporter`.

**Spec:** `docs/superpowers/specs/2026-07-01-dashboard-wizard-config-design.md`

## Global Constraints

- Wire format is camelCase via `CamelModel` (`api/schemas/base.py`); Python and YAML stay snake_case.
- Errors use the `ApiException` envelope (`api/errors.py`); validation failures are 422, user-fixable input 400.
- No file paths on the wire (render's `template_path`/`output_dir` are config _values_ — allowed).
- Secrets never round-trip: GET returns `{key, isSet, hint}` only (hint = last 4 chars, `null` when shorter than 8).
- All writes atomic: tmp file + `os.replace` (pattern of `services/sources._save`).
- Tests run offline: no network, no API key; run with `.venv/Scripts/python.exe -m pytest`.
- Lint gate: `ruff check` must stay clean.
- `connectors.yaml` stays behind `/api/sources` — this plan must NOT add a config domain for it.
- After all routers land, regenerate the TS contract: `bash scripts/gen_ts_client.sh` (Task 9).

---

### Task 1: Config document schemas + ConfigStore seam

**Files:**

- Create: `src/resume_agent/api/schemas/config.py`
- Create: `src/resume_agent/services/config_store.py`
- Test: `tests/api/test_config_store.py`

**Interfaces:**

- Consumes: `CamelModel` (`resume_agent.api.schemas.base`), `SearchConfig` (`resume_agent.discovery.search_config`) for the parity test.
- Produces: `ConfigStore` protocol with `get(domain: str) -> CamelModel` and `put(domain: str, model: CamelModel) -> CamelModel`; `YamlConfigStore(config_dir: Path | str = "config")`; `DOMAIN_SCHEMAS: dict[str, type[CamelModel]]` with keys `search`, `review`, `prune`, `render`, `style_guide`, `profile`. Schema classes: `SearchConfigDoc`, `ReviewConfigDoc` (with `ReviewerEntry`, `LengthBudget`), `PruneConfigDoc`, `RenderConfigDoc`, `StyleGuideDoc`, `ProfileConfigDoc`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_config_store.py
"""ConfigStore seam: YAML round-trip, defaults on missing file, domain registry."""

import pytest

from resume_agent.api.schemas.config import (
    DOMAIN_SCHEMAS,
    PruneConfigDoc,
    SearchConfigDoc,
    StyleGuideDoc,
)
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.services.config_store import YamlConfigStore


@pytest.fixture()
def store(tmp_path):
    return YamlConfigStore(config_dir=tmp_path)


def test_get_missing_file_returns_defaults(store):
    doc = store.get("prune")
    assert isinstance(doc, PruneConfigDoc)
    assert doc.fit_threshold == 40
    assert doc.enable_rejected is True


def test_put_then_get_round_trips(store, tmp_path):
    doc = PruneConfigDoc(fit_threshold=55, stale_days=30, retention_days=7,
                         enable_rejected=False, enable_low_fit=True, enable_stale=True)
    store.put("prune", doc)
    assert (tmp_path / "prune.yaml").exists()
    again = store.get("prune")
    assert again.fit_threshold == 55
    assert again.enable_rejected is False


def test_yaml_on_disk_is_snake_case(store, tmp_path):
    store.put("prune", PruneConfigDoc())
    text = (tmp_path / "prune.yaml").read_text(encoding="utf-8")
    assert "fit_threshold" in text
    assert "fitThreshold" not in text


def test_style_guide_is_plain_text(store, tmp_path):
    store.put("style_guide", StyleGuideDoc(content="# Voice\nBe terse."))
    assert (tmp_path / "style_guide.md").read_text(encoding="utf-8") == "# Voice\nBe terse."
    assert store.get("style_guide").content == "# Voice\nBe terse."


def test_unknown_domain_raises_key_error(store):
    with pytest.raises(KeyError):
        store.get("connectors")  # connectors stays behind /api/sources


def test_search_doc_covers_search_config_fields():
    """Drift gate: every declared SearchConfig field exists on SearchConfigDoc."""
    assert set(SearchConfig.model_fields) <= set(SearchConfigDoc.model_fields)


def test_domain_registry_contents():
    assert set(DOMAIN_SCHEMAS) == {"search", "review", "prune", "render", "style_guide", "profile"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_config_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_agent.api.schemas.config'`

- [ ] **Step 3: Implement the schemas**

```python
# src/resume_agent/api/schemas/config.py
"""Typed config documents — the wire contract for /api/config/{domain}.

Each Doc mirrors one YAML file's shape (snake_case on disk, camelCase on the
wire via CamelModel). Field defaults ARE the file defaults: a missing file
serves these values, and the TUI/CLI keep reading the same YAML.
"""

from __future__ import annotations

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel


class SearchConfigDoc(CamelModel):
    keywords: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_policy: str | None = None
    min_salary: int | None = None
    yoe_min: int | None = None
    yoe_max: int | None = None
    sponsorship_required: bool = False
    role_anchors: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    target_role: str | None = None
    distance: int | None = None
    max_days_old: int | None = None
    experience_levels: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)


class ReviewerEntry(CamelModel):
    name: str
    gate: bool = False
    weight: int = 1
    model_tier: str = "mid"


class LengthBudget(CamelModel):
    max_experiences: int = 4
    max_bullets_per_role: int = 5
    target_total_bullets: int = 20


def _default_reviewers() -> list[ReviewerEntry]:
    return [
        ReviewerEntry(name="fact-check", gate=True, weight=0, model_tier="premium"),
        ReviewerEntry(name="ats-keyword", gate=False, weight=1, model_tier="mid"),
        ReviewerEntry(name="recruiter", gate=False, weight=1, model_tier="mid"),
        ReviewerEntry(name="hiring-manager", gate=False, weight=1, model_tier="premium"),
        ReviewerEntry(name="concision", gate=False, weight=1, model_tier="mid"),
    ]


class ReviewConfigDoc(CamelModel):
    max_rounds: int = 3
    score_threshold: int = 85
    reviewers: list[ReviewerEntry] = Field(default_factory=_default_reviewers)
    length_budget: LengthBudget | None = None


class PruneConfigDoc(CamelModel):
    fit_threshold: int = 40
    stale_days: int = 60
    retention_days: int = 30
    enable_rejected: bool = True
    enable_low_fit: bool = True
    enable_stale: bool = True


class RenderConfigDoc(CamelModel):
    template_path: str = "templates/resume.typ"
    output_dir: str = "output"


class StyleGuideDoc(CamelModel):
    content: str = ""


class ProfileConfigDoc(CamelModel):
    github_username: str | None = None


DOMAIN_SCHEMAS: dict[str, type[CamelModel]] = {
    "search": SearchConfigDoc,
    "review": ReviewConfigDoc,
    "prune": PruneConfigDoc,
    "render": RenderConfigDoc,
    "style_guide": StyleGuideDoc,
    "profile": ProfileConfigDoc,
}
```

- [ ] **Step 4: Implement the store**

```python
# src/resume_agent/services/config_store.py
"""ConfigStore seam: domain name -> typed document, storage behind a protocol.

YamlConfigStore is the only implementation today (YAML/markdown files under
config/). A future DbConfigStore implements the same protocol; routers depend
only on get/put, so the HTTP contract never learns about storage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import yaml

from resume_agent.api.schemas.base import CamelModel
from resume_agent.api.schemas.config import DOMAIN_SCHEMAS, StyleGuideDoc


class ConfigStore(Protocol):
    def get(self, domain: str) -> CamelModel: ...
    def put(self, domain: str, model: CamelModel) -> CamelModel: ...


# domain -> filename; style_guide is plain markdown, everything else YAML.
_FILES: dict[str, str] = {
    "search": "search.yaml",
    "review": "review.yaml",
    "prune": "prune.yaml",
    "render": "render.yaml",
    "style_guide": "style_guide.md",
    "profile": "profile_sources.yaml",
}


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


class YamlConfigStore:
    def __init__(self, config_dir: Path | str = "config") -> None:
        self.config_dir = Path(config_dir)

    def _path(self, domain: str) -> Path:
        return self.config_dir / _FILES[domain]  # KeyError for unknown domains

    def get(self, domain: str) -> CamelModel:
        schema = DOMAIN_SCHEMAS[domain]
        path = self._path(domain)
        if schema is StyleGuideDoc:
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            return StyleGuideDoc(content=content)
        if not path.exists():
            return schema()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return schema.model_validate(data)

    def put(self, domain: str, model: CamelModel) -> CamelModel:
        schema = DOMAIN_SCHEMAS[domain]
        doc = schema.model_validate(model.model_dump())
        path = self._path(domain)
        if schema is StyleGuideDoc:
            _atomic_write(path, doc.content)  # type: ignore[attr-defined]
            return doc
        text = yaml.safe_dump(
            doc.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        )
        _atomic_write(path, text)
        return doc
```

Note: `profile_sources.yaml` may contain a legacy `resume_path` key; `ProfileConfigDoc`
ignores it on read (CamelModel is not extra-forbidding) and drops it on write —
acceptable, the document store supersedes it (spec §3.3).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_config_store.py -v`
Expected: 7 passed

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/resume_agent/api/schemas/config.py src/resume_agent/services/config_store.py tests/api/test_config_store.py
git add src/resume_agent/api/schemas/config.py src/resume_agent/services/config_store.py tests/api/test_config_store.py
git commit -m "feat(api): ConfigStore seam with typed per-domain config documents"
```

---

### Task 2: Config router (`/api/config/{domain}` GET/PUT for YAML domains)

**Files:**

- Create: `src/resume_agent/api/routers/config.py`
- Modify: `src/resume_agent/api/app.py` (register router; add `config_dir` state)
- Test: `tests/api/test_config_router.py`

**Interfaces:**

- Consumes: `YamlConfigStore`, `DOMAIN_SCHEMAS`, doc schemas from Task 1; `require_token` guard pattern from `app.py`.
- Produces: routes `GET/PUT /api/config/search|review|prune|render|style-guide|profile` (URL uses hyphen for `style-guide`; domain key stays `style_guide`). Dependency `get_config_store(request) -> ConfigStore` reading `request.app.state.config_store`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_config_router.py
"""GET serves defaults/current file; PUT validates, persists, and echoes."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config")
    with TestClient(app) as c:
        yield c


def test_get_search_defaults(client):
    resp = client.get("/api/config/search")
    assert resp.status_code == 200
    body = resp.json()
    assert body["keywords"] == []
    assert body["sponsorshipRequired"] is False  # camelCase wire


def test_put_search_round_trip(client):
    resp = client.put("/api/config/search", json={
        "keywords": ["python"], "titles": ["ML Engineer"], "locations": ["Remote"],
        "remotePolicy": "remote_only", "sponsorshipRequired": True,
    })
    assert resp.status_code == 200
    assert client.get("/api/config/search").json()["keywords"] == ["python"]


def test_put_invalid_types_is_422(client):
    resp = client.put("/api/config/prune", json={"fitThreshold": "not-a-number"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_style_guide_get_put(client):
    assert client.get("/api/config/style-guide").json() == {"content": ""}
    put = client.put("/api/config/style-guide", json={"content": "# Style"})
    assert put.status_code == 200
    assert client.get("/api/config/style-guide").json()["content"] == "# Style"


def test_review_reviewers_default_roster(client):
    body = client.get("/api/config/review").json()
    names = [r["name"] for r in body["reviewers"]]
    assert names[0] == "fact-check"
    assert body["reviewers"][0]["gate"] is True
```

Note: FastAPI request-body validation already yields the envelope 422 through
`install_error_handlers` — check `api/errors.py`; if the handler names the code
differently (e.g. `VALIDATION_ERROR` vs another string), match the existing
code in the assertion rather than changing the handler.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_config_router.py -v`
Expected: FAIL — `create_app() got an unexpected keyword argument 'config_dir'`

- [ ] **Step 3: Implement router + app wiring**

```python
# src/resume_agent/api/routers/config.py
"""Typed per-domain config resources. Storage lives behind ConfigStore."""

from __future__ import annotations

from fastapi import APIRouter, Request

from resume_agent.api.schemas.config import (
    ProfileConfigDoc,
    PruneConfigDoc,
    RenderConfigDoc,
    ReviewConfigDoc,
    SearchConfigDoc,
    StyleGuideDoc,
)
from resume_agent.services.config_store import ConfigStore

router = APIRouter()


def _store(request: Request) -> ConfigStore:
    return request.app.state.config_store


@router.get("/config/search", response_model=SearchConfigDoc)
def get_search(request: Request):
    return _store(request).get("search")


@router.put("/config/search", response_model=SearchConfigDoc)
def put_search(body: SearchConfigDoc, request: Request):
    return _store(request).put("search", body)


@router.get("/config/review", response_model=ReviewConfigDoc)
def get_review(request: Request):
    return _store(request).get("review")


@router.put("/config/review", response_model=ReviewConfigDoc)
def put_review(body: ReviewConfigDoc, request: Request):
    return _store(request).put("review", body)


@router.get("/config/prune", response_model=PruneConfigDoc)
def get_prune(request: Request):
    return _store(request).get("prune")


@router.put("/config/prune", response_model=PruneConfigDoc)
def put_prune(body: PruneConfigDoc, request: Request):
    return _store(request).put("prune", body)


@router.get("/config/render", response_model=RenderConfigDoc)
def get_render(request: Request):
    return _store(request).get("render")


@router.put("/config/render", response_model=RenderConfigDoc)
def put_render(body: RenderConfigDoc, request: Request):
    return _store(request).put("render", body)


@router.get("/config/style-guide", response_model=StyleGuideDoc)
def get_style_guide(request: Request):
    return _store(request).get("style_guide")


@router.put("/config/style-guide", response_model=StyleGuideDoc)
def put_style_guide(body: StyleGuideDoc, request: Request):
    return _store(request).put("style_guide", body)


@router.get("/config/profile", response_model=ProfileConfigDoc)
def get_profile_config(request: Request):
    return _store(request).get("profile")


@router.put("/config/profile", response_model=ProfileConfigDoc)
def put_profile_config(body: ProfileConfigDoc, request: Request):
    return _store(request).put("profile", body)
```

In `src/resume_agent/api/app.py`:

1. Add parameter `config_dir: Path | str | None = None` to `create_app`.
2. After `app.state.db_url = resolved_db`, add:

```python
from resume_agent.services.config_store import YamlConfigStore  # top of file

app.state.config_store = YamlConfigStore(config_dir=config_dir or "config")
```

1. Register (with the other guarded routers):

```python
from resume_agent.api.routers import config as config_router  # top of file

app.include_router(config_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_config_router.py -v`
Expected: 5 passed

- [ ] **Step 5: Full suite, lint, commit**

Run: `.venv/Scripts/python.exe -m pytest` — expected: all green (the OpenAPI
contract test WILL fail if it snapshots routes; if `tests/api/test_openapi_contract.py`
fails, regenerate per its instructions — read that test file; it documents the
regen command — and include the updated `contracts/openapi.json` in the commit).

```bash
ruff check
git add -A src/resume_agent/api tests/api/test_config_router.py contracts
git commit -m "feat(api): typed GET/PUT /api/config/{domain} resources"
```

---

### Task 3: Env-backed config: secrets (write-only) + models domain

**Files:**

- Create: `src/resume_agent/services/env_config.py`
- Create: `src/resume_agent/api/schemas/secrets.py`
- Create: `src/resume_agent/api/routers/secrets.py`
- Modify: `src/resume_agent/api/app.py` (settings override reads `app.state.settings`; register router; add `env_path` param)
- Test: `tests/api/test_secrets_router.py`

**Interfaces:**

- Consumes: `parse_env`, `merge_env`, `format_env` (`resume_agent.setup.env_writer`); `get_settings` cache.
- Produces: `read_env(env_path) -> dict[str, str]`; `write_env_updates(updates: dict[str, str], env_path) -> None` (atomic merge-write + `get_settings.cache_clear()`); routes `GET /api/secrets`, `PUT /api/secrets`, `GET/PUT /api/config/models`. `SECRET_FIELDS: dict[str, str]` (schema field -> env var). Schemas: `SecretStatus {key, is_set, hint}`, `SecretsUpdate` (all-optional str-or-null fields), `ModelsConfigDoc {cheap_model, mid_model, premium_model}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_secrets_router.py
"""Secrets are write-only: GET exposes status+hint, never values."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text('ANTHROPIC_API_KEY=sk-ant-test-abcd1234\nUNMANAGED=keepme\n', encoding="utf-8")
    return p


@pytest.fixture()
def client(tmp_path, env_file):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config", env_path=env_file)
    with TestClient(app) as c:
        yield c


def test_get_secrets_returns_status_not_values(client):
    body = client.get("/api/secrets").json()
    by_key = {row["key"]: row for row in body}
    assert by_key["anthropicApiKey"]["isSet"] is True
    assert by_key["anthropicApiKey"]["hint"] == "1234"
    assert by_key["openaiApiKey"]["isSet"] is False
    assert by_key["openaiApiKey"]["hint"] is None
    dumped = str(body)
    assert "sk-ant-test-abcd1234" not in dumped


def test_put_writes_only_provided_keys(client, env_file):
    resp = client.put("/api/secrets", json={"openaiApiKey": "sk-oai-xyz98765"})
    assert resp.status_code == 200
    text = env_file.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-oai-xyz98765" in text
    assert "ANTHROPIC_API_KEY=sk-ant-test-abcd1234" in text  # untouched
    assert "UNMANAGED=keepme" in text  # unmanaged keys survive


def test_put_null_clears_key(client, env_file):
    client.put("/api/secrets", json={"anthropicApiKey": None})
    body = client.get("/api/secrets").json()
    by_key = {row["key"]: row for row in body}
    assert by_key["anthropicApiKey"]["isSet"] is False


def test_models_config_readable_round_trip(client):
    body = client.get("/api/config/models").json()
    assert "cheapModel" in body and body["cheapModel"]  # defaults visible
    put = client.put("/api/config/models", json={
        "cheapModel": "claude-haiku-4-5-20251001",
        "midModel": "claude-sonnet-5",
        "premiumModel": "claude-opus-4-8",
    })
    assert put.status_code == 200
    assert client.get("/api/config/models").json()["midModel"] == "claude-sonnet-5"


def test_put_secret_refreshes_app_settings(client):
    client.put("/api/secrets", json={"anthropicApiKey": "sk-ant-new-key-5678"})
    # settings served to routes must see the new value without an app restart
    from resume_agent.api.deps import get_settings_dep  # noqa: PLC0415
    app = client.app
    assert app.dependency_overrides[get_settings_dep]().anthropic_api_key == "sk-ant-new-key-5678"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_secrets_router.py -v`
Expected: FAIL — `create_app() got an unexpected keyword argument 'env_path'`

- [ ] **Step 3: Implement env service + schemas + router**

```python
# src/resume_agent/services/env_config.py
"""Read/merge-write .env through the TUI wizard's pure helpers.

The one write path for web-managed env values. After a write, the cached
Settings singleton is cleared so run workers (which call get_settings() at
call time) see fresh values; the router additionally refreshes
app.state.settings for request-scoped dependencies.
"""

from __future__ import annotations

import os
from pathlib import Path

from resume_agent.config import Settings, get_settings
from resume_agent.setup.env_writer import format_env, merge_env, parse_env

DEFAULT_ENV_PATH = Path(".env")


def read_env(env_path: Path | str = DEFAULT_ENV_PATH) -> dict[str, str]:
    p = Path(env_path)
    if not p.exists():
        return {}
    return parse_env(p.read_text(encoding="utf-8"))


def write_env_updates(
    updates: dict[str, str], env_path: Path | str = DEFAULT_ENV_PATH
) -> Settings:
    """Merge-write managed keys (empty string = clear) and return fresh Settings."""
    p = Path(env_path)
    merged = merge_env(read_env(p), updates)
    merged = {k: v for k, v in merged.items() if v != ""}
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(format_env(merged), encoding="utf-8")
    os.replace(tmp, p)
    get_settings.cache_clear()
    return Settings(_env_file=p)  # type: ignore[call-arg]
```

```python
# src/resume_agent/api/schemas/secrets.py
"""Write-only secrets contract + readable model-tier config."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel

# schema field name -> .env variable. One place; GET, PUT, and setup-status use it.
SECRET_FIELDS: dict[str, str] = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "github_token": "GITHUB_TOKEN",
    "adzuna_app_id": "ADZUNA_APP_ID",
    "adzuna_app_key": "ADZUNA_APP_KEY",
    "linkedin_email": "LINKEDIN_EMAIL",
    "linkedin_password": "LINKEDIN_PASSWORD",
}


class SecretStatus(CamelModel):
    key: str  # camelCase field name, e.g. "anthropicApiKey"
    is_set: bool
    hint: str | None = None  # last 4 chars, only when len(value) >= 8


class SecretsUpdate(CamelModel):
    """All-optional; only fields present in the request body are written.
    An explicit null clears the key."""

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    deepseek_api_key: str | None = None
    github_token: str | None = None
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    linkedin_email: str | None = None
    linkedin_password: str | None = None


class ModelsConfigDoc(CamelModel):
    cheap_model: str = "claude-haiku-4-5-20251001"
    mid_model: str = "claude-sonnet-4-6"
    premium_model: str = "claude-opus-4-8"
```

```python
# src/resume_agent/api/routers/secrets.py
"""Write-only secrets + readable model tiers, both backed by .env."""

from __future__ import annotations

from pydantic.alias_generators import to_camel
from fastapi import APIRouter, Request

from resume_agent.api.schemas.secrets import (
    SECRET_FIELDS,
    ModelsConfigDoc,
    SecretStatus,
    SecretsUpdate,
)
from resume_agent.services.env_config import read_env, write_env_updates

router = APIRouter()

_MODEL_ENV = {"cheap_model": "CHEAP_MODEL", "mid_model": "MID_MODEL",
              "premium_model": "PREMIUM_MODEL"}


def _statuses(env_path) -> list[SecretStatus]:
    env = read_env(env_path)
    out = []
    for field, var in SECRET_FIELDS.items():
        value = env.get(var, "")
        hint = value[-4:] if len(value) >= 8 else None
        out.append(SecretStatus(key=to_camel(field), is_set=bool(value), hint=hint))
    return out


@router.get("/secrets", response_model=list[SecretStatus])
def get_secrets(request: Request):
    return _statuses(request.app.state.env_path)


@router.put("/secrets", response_model=list[SecretStatus])
def put_secrets(body: SecretsUpdate, request: Request):
    provided = body.model_dump(exclude_unset=True)
    updates = {SECRET_FIELDS[f]: (v or "") for f, v in provided.items()}
    request.app.state.settings = write_env_updates(updates, request.app.state.env_path)
    return _statuses(request.app.state.env_path)


@router.get("/config/models", response_model=ModelsConfigDoc)
def get_models(request: Request):
    env = read_env(request.app.state.env_path)
    defaults = ModelsConfigDoc()
    return ModelsConfigDoc(**{
        f: env.get(var) or getattr(defaults, f) for f, var in _MODEL_ENV.items()
    })


@router.put("/config/models", response_model=ModelsConfigDoc)
def put_models(body: ModelsConfigDoc, request: Request):
    updates = {var: getattr(body, f) for f, var in _MODEL_ENV.items()}
    request.app.state.settings = write_env_updates(updates, request.app.state.env_path)
    return body
```

In `src/resume_agent/api/app.py`:

1. Add `env_path: Path | str | None = None` parameter; set `app.state.env_path = Path(env_path) if env_path is not None else Path(".env")`.
2. Change the settings override so refreshes propagate (was a frozen closure):

```python
# before:
app.dependency_overrides[get_settings_dep] = lambda: resolved_settings
# after:
app.state.settings = resolved_settings
app.dependency_overrides[get_settings_dep] = lambda: app.state.settings
```

(Keep the `app.state.settings = resolved_settings` assignment that already
exists near the top of `create_app` — just make sure it happens before the
override line and delete any duplicate.)

1. When refreshing settings after an env write, the db_url/api_token resolved at
   startup must survive. In `put_secrets`/`put_models` this is handled by
   re-applying the app's resolved values — add this helper to `app.py` and use it
   in the router instead of assigning raw:

```python
def refresh_app_settings(app, fresh):
    """Env-derived settings changed; keep startup-resolved db_url/api_token."""
    app.state.settings = fresh.model_copy(update={
        "db_url": app.state.db_url,
        "api_token": app.state.settings.api_token,
    })
```

In `secrets.py`, replace both `request.app.state.settings = write_env_updates(...)`
lines with:

```python
from resume_agent.api.app import refresh_app_settings  # NO — circular import.
```

That import would be circular (`app.py` imports the router). Put
`refresh_app_settings(app, fresh)` in `src/resume_agent/api/deps.py` instead,
and import it from there in the router:

```python
# in api/deps.py
def refresh_app_settings(app, fresh):
    """Env-derived settings changed; keep startup-resolved db_url/api_token."""
    app.state.settings = fresh.model_copy(update={
        "db_url": app.state.db_url,
        "api_token": app.state.settings.api_token,
    })
```

```python
# in routers/secrets.py
from resume_agent.api.deps import refresh_app_settings
...
    fresh = write_env_updates(updates, request.app.state.env_path)
    refresh_app_settings(request.app, fresh)
```

1. Register the router: `app.include_router(secrets_router.router, prefix="/api", dependencies=guarded)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_secrets_router.py -v`
Expected: 5 passed

- [ ] **Step 5: Full suite, lint, commit**

Run: `.venv/Scripts/python.exe -m pytest` and `ruff check`

```bash
git add -A src/resume_agent tests/api/test_secrets_router.py contracts
git commit -m "feat(api): write-only /api/secrets + env-backed /api/config/models"
```

---

### Task 4: Profile document store + upload endpoints

**Files:**

- Create: `src/resume_agent/services/profile_documents.py`
- Create: `src/resume_agent/api/schemas/profile.py`
- Create: `src/resume_agent/api/routers/profile.py` (documents part; build lands in Task 5)
- Modify: `src/resume_agent/api/app.py` (register router; add `data_dir` param defaulting to `"data"`)
- Modify: `pyproject.toml` (add `python-multipart` if absent — required by FastAPI `UploadFile`)
- Test: `tests/api/test_profile_documents.py`

**Interfaces:**

- Produces: `DocumentStore(root: Path)` with `add(filename: str, content: bytes, doc_type: str) -> DocumentRecord`, `list() -> list[DocumentRecord]`, `delete(doc_id: str) -> bool`, `latest_resume_path() -> Path | None`; `DocumentRecord` dataclass `(id, filename, doc_type, size_bytes, uploaded_at)`; `DocumentError(str)` for user-fixable rejects. Routes `GET/POST /api/profile/documents`, `DELETE /api/profile/documents/{doc_id}`. `ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}`, `MAX_SIZE_BYTES = 15 * 1024 * 1024`. Store lives at `request.app.state.document_store`, root `data/profile/documents`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_profile_documents.py
"""Upload validation, manifest atomicity, list/delete, resume resolution."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.services.profile_documents import DocumentStore


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=tmp_path / ".env", data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c


def _upload(client, name="resume.pdf", doc_type="resume", content=b"%PDF-1.4 fake"):
    return client.post(
        "/api/profile/documents",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
        data={"docType": doc_type},
    )


def test_upload_and_list(client):
    resp = _upload(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == "resume.pdf"
    assert body["docType"] == "resume"
    listed = client.get("/api/profile/documents").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_reject_bad_extension(client):
    resp = _upload(client, name="malware.exe")
    assert resp.status_code == 422
    assert client.get("/api/profile/documents").json() == []  # nothing registered


def test_reject_bad_doc_type(client):
    resp = _upload(client, doc_type="mixtape")
    assert resp.status_code == 422


def test_reject_oversize(client):
    resp = _upload(client, content=b"x" * (15 * 1024 * 1024 + 1))
    assert resp.status_code == 422


def test_delete(client):
    doc_id = _upload(client).json()["id"]
    assert client.delete(f"/api/profile/documents/{doc_id}").status_code == 204
    assert client.get("/api/profile/documents").json() == []
    assert client.delete(f"/api/profile/documents/{doc_id}").status_code == 404


def test_latest_resume_path(tmp_path):
    store = DocumentStore(tmp_path / "docs")
    assert store.latest_resume_path() is None
    store.add("old.pdf", b"a", "resume")
    rec = store.add("new.pdf", b"b", "resume")
    store.add("notes.md", b"c", "other")
    path = store.latest_resume_path()
    assert path is not None and path.name == "new.pdf" and rec.id in str(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_documents.py -v`
Expected: FAIL — no module `resume_agent.services.profile_documents`

- [ ] **Step 3: Implement store, schemas, router**

First check the multipart dependency: `Grep "python-multipart" pyproject.toml`.
If absent, add `"python-multipart>=0.0.9",` to the main dependencies list and
run `.venv/Scripts/python.exe -m pip install python-multipart`.

```python
# src/resume_agent/services/profile_documents.py
"""Manifest-backed profile document store (data/profile/documents/).

File first, manifest last: a crashed upload leaves an orphan directory but
never a manifest entry, so readers only ever see complete documents.
Designed for the profile-corpus spec's multi-doc ingestion; today only the
resume-typed document feeds profile build.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
ALLOWED_DOC_TYPES = {"resume", "transcript", "portfolio", "other"}
MAX_SIZE_BYTES = 15 * 1024 * 1024


class DocumentError(Exception):
    """User-fixable upload problem: bad type, bad extension, too large."""


@dataclass(frozen=True)
class DocumentRecord:
    id: str
    filename: str
    doc_type: str
    size_bytes: int
    uploaded_at: str


def _safe_name(filename: str) -> str:
    name = Path(filename).name  # strip any client path
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "upload"


class DocumentStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    @property
    def _manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def _read_manifest(self) -> list[dict]:
        if not self._manifest_path.exists():
            return []
        return json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def _write_manifest(self, rows: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        os.replace(tmp, self._manifest_path)

    def add(self, filename: str, content: bytes, doc_type: str) -> DocumentRecord:
        if doc_type not in ALLOWED_DOC_TYPES:
            raise DocumentError(f"docType must be one of {sorted(ALLOWED_DOC_TYPES)}")
        name = _safe_name(filename)
        if Path(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise DocumentError(f"File type must be one of {sorted(ALLOWED_SUFFIXES)}")
        if len(content) > MAX_SIZE_BYTES:
            raise DocumentError("File exceeds the 15 MB limit")
        doc_id = uuid.uuid4().hex[:12]
        target_dir = self.root / doc_id
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / name).write_bytes(content)  # file first…
        record = DocumentRecord(
            id=doc_id, filename=name, doc_type=doc_type, size_bytes=len(content),
            uploaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        rows = self._read_manifest()
        rows.append(asdict(record))
        self._write_manifest(rows)  # …manifest last
        return record

    def list(self) -> list[DocumentRecord]:
        return [DocumentRecord(**row) for row in self._read_manifest()]

    def delete(self, doc_id: str) -> bool:
        rows = self._read_manifest()
        kept = [r for r in rows if r["id"] != doc_id]
        if len(kept) == len(rows):
            return False
        self._write_manifest(kept)
        target = self.root / doc_id
        if target.is_dir():
            for child in target.iterdir():
                child.unlink(missing_ok=True)
            target.rmdir()
        return True

    def latest_resume_path(self) -> Path | None:
        resumes = [r for r in self._read_manifest() if r["doc_type"] == "resume"]
        if not resumes:
            return None
        newest = max(resumes, key=lambda r: r["uploaded_at"])
        return self.root / newest["id"] / newest["filename"]
```

```python
# src/resume_agent/api/schemas/profile.py
"""Profile document + build wire schemas."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class DocumentOut(CamelModel):
    id: str
    filename: str
    doc_type: str
    size_bytes: int
    uploaded_at: str
```

```python
# src/resume_agent/api/routers/profile.py
"""Profile documents CRUD (+ profile build run, added in a later task)."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile

from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.profile import DocumentOut
from resume_agent.services.profile_documents import DocumentError, DocumentStore

router = APIRouter()


def _docs(request: Request) -> DocumentStore:
    return request.app.state.document_store


@router.get("/profile/documents", response_model=list[DocumentOut])
def list_documents(request: Request):
    return [DocumentOut.model_validate(rec) for rec in _docs(request).list()]


@router.post("/profile/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(..., alias="docType"),
):
    content = await file.read()
    try:
        record = _docs(request).add(file.filename or "upload", content, doc_type)
    except DocumentError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    return DocumentOut.model_validate(record)


@router.delete("/profile/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, request: Request):
    if not _docs(request).delete(doc_id):
        raise ApiException(404, "NOT_FOUND", f"No document '{doc_id}'")
```

In `app.py`: add `data_dir: Path | str | None = None` param;
`app.state.document_store = DocumentStore(Path(data_dir or "data") / "profile" / "documents")`;
register `profile_router.router` with the guarded routers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_documents.py -v`
Expected: 7 passed

- [ ] **Step 5: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest && ruff check
git add -A src/resume_agent tests/api/test_profile_documents.py pyproject.toml contracts
git commit -m "feat(api): profile document store with typed multipart upload"
```

---

### Task 5: Profile build as a Run

**Files:**

- Create: `src/resume_agent/services/profile_build.py`
- Modify: `src/resume_agent/api/routers/profile.py` (add `POST /profile/build`)
- Modify: `CLAUDE.md` (API layer section: remove "profile build" from the deferred list)
- Test: `tests/api/test_profile_build_run.py`

**Interfaces:**

- Consumes: `build_profile(resume_path, github_username, extractor_agent=None, github_client=None)` (`resume_agent.profile.build`), `save_facts` / `validate_profile` (`resume_agent.profile.store` / `.validate`), `DocumentStore.latest_resume_path()`, `ConfigStore.get("profile")`, `RunManager.submit` pattern from `api/routers/runs.py`, `RunOut` + `record_to_run`.
- Produces: `run_profile_build(reporter, *, document_store, config_store, settings, facts_out="data/profile/facts.json") -> dict` and route `POST /api/profile/build` (202, `RunOut`, singleton_key `"profile-build"`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_profile_build_run.py
"""Profile build launches as a run; preconditions fail fast with 400."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-test-abcd1234\n", encoding="utf-8")
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=env, data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c


def test_build_without_resume_is_400(client):
    resp = client.post("/api/profile/build")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SETUP_INCOMPLETE"


def test_build_without_key_is_400(tmp_path):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=tmp_path / ".env", data_dir=tmp_path / "data")
    with TestClient(app) as client:
        client.post(
            "/api/profile/documents",
            files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
            data={"docType": "resume"},
        )
        resp = client.post("/api/profile/build")
        assert resp.status_code == 400


def test_build_launches_run(client, monkeypatch):
    client.post(
        "/api/profile/documents",
        files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
        data={"docType": "resume"},
    )

    from resume_agent.services import profile_build

    def fake_run(reporter, **kwargs):
        return {"experiences": 2, "projects": 1, "warnings": []}

    monkeypatch.setattr(profile_build, "run_profile_build", fake_run)
    resp = client.post("/api/profile/build")
    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "profile-build"
    assert body["runId"]
```

Note on the monkeypatch: the router must call `profile_build.run_profile_build`
through the module (`from resume_agent.services import profile_build` then
`profile_build.run_profile_build(...)`), NOT `from ... import run_profile_build`,
or the patch will not take. Mirror how the test patches it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_build_run.py -v`
Expected: FAIL — 404 on `/api/profile/build` / missing module

- [ ] **Step 3: Implement service + route**

```python
# src/resume_agent/services/profile_build.py
"""Profile build use-case: documents + GitHub -> facts.json, with progress."""

from __future__ import annotations

from pathlib import Path

from resume_agent.profile.build import build_profile
from resume_agent.profile.store import save_facts
from resume_agent.profile.validate import validate_profile


def run_profile_build(
    reporter,
    *,
    resume_path: Path,
    github_username: str | None,
    facts_out: str | Path = "data/profile/facts.json",
) -> dict:
    reporter.begin(2, "Extracting facts from resume")
    facts, raw_text = build_profile(
        resume_path=resume_path, github_username=github_username
    )
    reporter.step(1, label="Validating profile")
    report = validate_profile(facts, raw_text)
    save_facts(facts, str(facts_out))
    reporter.step(2, label="Saved facts.json")
    return {
        "experiences": len(facts.experience),
        "projects": len(facts.projects),
        "warnings": list(report.warnings),
    }
```

Add to `src/resume_agent/api/routers/profile.py`:

```python
from resume_agent.api.deps import get_run_manager
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.runs import RunOut
from resume_agent.services import profile_build
from fastapi import Depends


@router.post("/profile/build", response_model=RunOut, status_code=202)
def launch_profile_build(request: Request, mgr: RunManager = Depends(get_run_manager)):
    settings = request.app.state.settings
    if not settings.anthropic_api_key:
        raise ApiException(400, "SETUP_INCOMPLETE",
                           "ANTHROPIC_API_KEY is not set — add it in Settings > API Keys")
    resume_path = _docs(request).latest_resume_path()
    if resume_path is None:
        raise ApiException(400, "SETUP_INCOMPLETE",
                           "Upload a resume document before building the profile")
    profile_cfg = request.app.state.config_store.get("profile")
    github_username = profile_cfg.github_username
    facts_out = request.app.state.data_dir / "profile" / "facts.json"

    def work(reporter):
        return profile_build.run_profile_build(
            reporter, resume_path=resume_path,
            github_username=github_username, facts_out=facts_out,
        )

    run_id = mgr.submit("profile-build", work, singleton_key="profile-build")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)
```

In `app.py`, alongside the document store: `app.state.data_dir = Path(data_dir or "data")`.

In `CLAUDE.md`, change the API-layer bullet
`**Deferred (not exposed over HTTP):** Gmail sync, profile build, LinkedIn scrape.`
to `**Deferred (not exposed over HTTP):** Gmail sync, LinkedIn scrape.`

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_build_run.py -v`
Expected: 3 passed

- [ ] **Step 5: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest && ruff check
git add -A src/resume_agent tests/api/test_profile_build_run.py CLAUDE.md contracts
git commit -m "feat(api): profile build exposed as a run (202 + SSE)"
```

---

### Task 6: Setup status endpoint

**Files:**

- Create: `src/resume_agent/api/schemas/setup.py`
- Create: `src/resume_agent/api/routers/setup.py`
- Modify: `src/resume_agent/api/app.py` (register)
- Test: `tests/api/test_setup_status.py`

**Interfaces:**

- Consumes: `read_env` + `SECRET_FIELDS` (Task 3), `DocumentStore` (Task 4), `ConfigStore` (Task 1), `list_sources` (`resume_agent.services.sources`), `app.state.data_dir`.
- Produces: `GET /api/setup/status` returning `SetupStatusOut`:

```
{ secrets: {anthropicKey: bool, anyLlmKey: bool},
  profile: {documentCount: int, hasResume: bool, factsBuiltAt: str|null, githubUsername: str|null},
  search: {configured: bool},
  sources: {enabledCount: int},
  complete: bool }
```

`complete` = `anyLlmKey and hasResume and factsBuiltAt is not None and search.configured and enabledCount > 0`.
`search.configured` = any of `keywords`/`titles`/`role_anchors` non-empty.
`factsBuiltAt` = mtime (UTC isoformat) of `{data_dir}/profile/facts.json`, null when missing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_setup_status.py
"""setup/status aggregates per-area readiness and an overall complete flag."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def make_client(tmp_path):
    def _make(env_text=""):
        env = tmp_path / ".env"
        env.write_text(env_text, encoding="utf-8")
        app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                         env_path=env, data_dir=tmp_path / "data")
        return TestClient(app)
    return _make


def test_fresh_install_incomplete(make_client):
    with make_client() as client:
        body = client.get("/api/setup/status").json()
        assert body["complete"] is False
        assert body["secrets"]["anthropicKey"] is False
        assert body["profile"]["documentCount"] == 0
        assert body["profile"]["factsBuiltAt"] is None
        assert body["search"]["configured"] is False


def test_areas_flip_as_setup_progresses(make_client, tmp_path):
    with make_client("ANTHROPIC_API_KEY=sk-ant-test-abcd1234\n") as client:
        client.post(
            "/api/profile/documents",
            files={"file": ("resume.txt", io.BytesIO(b"exp"), "text/plain")},
            data={"docType": "resume"},
        )
        client.put("/api/config/search", json={"keywords": ["python"]})
        facts = tmp_path / "data" / "profile" / "facts.json"
        facts.parent.mkdir(parents=True, exist_ok=True)
        facts.write_text("{}", encoding="utf-8")

        body = client.get("/api/setup/status").json()
        assert body["secrets"]["anthropicKey"] is True
        assert body["profile"]["hasResume"] is True
        assert body["profile"]["factsBuiltAt"] is not None
        assert body["search"]["configured"] is True
        # no sources enabled yet -> still incomplete
        assert body["sources"]["enabledCount"] == 0
        assert body["complete"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_setup_status.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Implement**

```python
# src/resume_agent/api/schemas/setup.py
"""Setup readiness projection for the first-run gate + dashboard health card."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class SecretsStatus(CamelModel):
    anthropic_key: bool
    any_llm_key: bool


class ProfileStatus(CamelModel):
    document_count: int
    has_resume: bool
    facts_built_at: str | None = None
    github_username: str | None = None


class SearchStatus(CamelModel):
    configured: bool


class SourcesStatus(CamelModel):
    enabled_count: int


class SetupStatusOut(CamelModel):
    secrets: SecretsStatus
    profile: ProfileStatus
    search: SearchStatus
    sources: SourcesStatus
    complete: bool
```

```python
# src/resume_agent/api/routers/setup.py
"""GET /setup/status — one aggregate the gate, wizard, and dashboard all read."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from resume_agent.api.schemas.setup import (
    ProfileStatus,
    SearchStatus,
    SecretsStatus,
    SetupStatusOut,
    SourcesStatus,
)
from resume_agent.services.env_config import read_env
from resume_agent.services.sources import list_sources

router = APIRouter()

_LLM_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY")


@router.get("/setup/status", response_model=SetupStatusOut)
def get_setup_status(request: Request):
    env = read_env(request.app.state.env_path)
    secrets = SecretsStatus(
        anthropic_key=bool(env.get("ANTHROPIC_API_KEY")),
        any_llm_key=any(env.get(k) for k in _LLM_KEYS),
    )

    docs = request.app.state.document_store.list()
    facts_path = request.app.state.data_dir / "profile" / "facts.json"
    facts_built_at = (
        datetime.fromtimestamp(facts_path.stat().st_mtime, tz=timezone.utc)
        .isoformat(timespec="seconds")
        if facts_path.exists() else None
    )
    profile_cfg = request.app.state.config_store.get("profile")
    profile = ProfileStatus(
        document_count=len(docs),
        has_resume=any(d.doc_type == "resume" for d in docs),
        facts_built_at=facts_built_at,
        github_username=profile_cfg.github_username,
    )

    search_cfg = request.app.state.config_store.get("search")
    search = SearchStatus(
        configured=bool(search_cfg.keywords or search_cfg.titles or search_cfg.role_anchors)
    )

    try:
        enabled = sum(1 for v in list_sources(settings=request.app.state.settings) if v.enabled)
    except Exception:  # missing/broken connectors.yaml must not 500 the gate
        enabled = 0
    sources = SourcesStatus(enabled_count=enabled)

    complete = (
        secrets.any_llm_key and profile.has_resume
        and profile.facts_built_at is not None
        and search.configured and sources.enabled_count > 0
    )
    return SetupStatusOut(secrets=secrets, profile=profile, search=search,
                          sources=sources, complete=complete)
```

Check `SourceView`'s enabled attribute name before relying on `v.enabled`
(`Grep "class SourceView" src/resume_agent/discovery/connectors/sources.py -A 15`)
and adjust if the field is named differently.

Register in `app.py` with the guarded routers. Note `list_sources` reads
`config/connectors.yaml` via its default parameter — pass
`connectors_path=str(request.app.state.config_store.config_dir / "connectors.yaml")`
so tests with a temp `config_dir` don't read the developer's real file:
`list_sources(connectors_path=..., settings=request.app.state.settings)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_setup_status.py -v`
Expected: 2 passed

- [ ] **Step 5: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest && ruff check
git add -A src/resume_agent tests/api/test_setup_status.py contracts
git commit -m "feat(api): GET /api/setup/status readiness aggregate"
```

---

### Task 7: Dashboard summary endpoint

**Files:**

- Create: `src/resume_agent/services/dashboard.py`
- Create: `src/resume_agent/api/schemas/dashboard.py`
- Create: `src/resume_agent/api/routers/dashboard.py`
- Modify: `src/resume_agent/api/app.py` (register)
- Test: `tests/api/test_dashboard_summary.py`

**Interfaces:**

- Consumes: `Job`, `JobStatus`, `Application` (`resume_agent.tracking.tables`); `get_session` dep.
- Produces: `GET /api/dashboard/summary` returning `DashboardSummaryOut`:

```
{ statusCounts: {raw: int, extracted: int, filtered: int, rejected: int,
                 shortlisted: int, approved: int, tailored: int, rendered: int},
  queues: {triage: int, approve: int, tailor: int, apply: int},
  applied: int }
```

Service: `summarize_dashboard(session) -> DashboardSummary` (plain dataclass mirror).
Queue mapping: `triage=filtered`, `approve=shortlisted`, `tailor=approved`, `apply=rendered`;
`applied` = count of `Application` rows with status != `"ready"`. All job counts
exclude archived rows (`archived_at IS NULL`). **Verify the triage mapping**
against `_TRIAGE_STATUSES` in `src/resume_agent/tracking/queries.py:352` — if
triage includes more statuses than `filtered`, use that tuple instead.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_dashboard_summary.py
"""Status counts + action queues over a seeded DB; archived rows excluded."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_agent.api.app import create_app
from resume_agent.tracking.tables import Application, Job


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=tmp_path / ".env", data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c


def _seed(engine):
    with Session(engine) as session:
        def job(status, archived=False, **kw):
            j = Job(source="manual", company="Acme", title=f"{status}-role",
                    status=status, dedup_key=f"acme|{status}{archived}", **kw)
            if archived:
                j.archived_at = datetime.now(timezone.utc)
            session.add(j)
            return j

        job("filtered")
        job("filtered", archived=True)  # must not count
        job("shortlisted")
        job("approved")
        rendered = job("rendered")
        session.commit()
        session.add(Application(job_id=rendered.id, status="submitted"))
        session.commit()


def test_summary_counts_and_queues(client):
    _seed(client.app.state.engine)
    body = client.get("/api/dashboard/summary").json()
    assert body["statusCounts"]["filtered"] == 1  # archived excluded
    assert body["queues"] == {"triage": 1, "approve": 1, "tailor": 1, "apply": 1}
    assert body["applied"] == 1
```

Check `Job`'s required fields before finalizing the seed helper (`Read
src/resume_agent/tracking/tables.py:37-80`) — add any non-nullable columns the
constructor requires (e.g. `jd_text`), and match `Application`'s actual column
names.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_dashboard_summary.py -v`
Expected: FAIL — 404

- [ ] **Step 3: Implement**

```python
# src/resume_agent/services/dashboard.py
"""Read-only dashboard projection: one query pass, no business logic."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, func, select

from resume_agent.tracking.tables import Application, Job, JobStatus

# Pipeline stages that are literally "waiting on the user", keyed by queue name.
QUEUE_STATUSES: dict[str, tuple[str, ...]] = {
    "triage": (JobStatus.filtered.value,),
    "approve": (JobStatus.shortlisted.value,),
    "tailor": (JobStatus.approved.value,),
    "apply": (JobStatus.rendered.value,),
}


@dataclass(frozen=True)
class DashboardSummary:
    status_counts: dict[str, int] = field(default_factory=dict)
    queues: dict[str, int] = field(default_factory=dict)
    applied: int = 0


def summarize_dashboard(session: Session) -> DashboardSummary:
    rows = session.exec(
        select(Job.status, func.count())
        .where(Job.archived_at == None)  # noqa: E711 — SQL IS NULL
        .group_by(Job.status)
    ).all()
    counts = {status.value: 0 for status in JobStatus}
    for status, count in rows:
        counts[status] = count
    queues = {
        name: sum(counts.get(s, 0) for s in statuses)
        for name, statuses in QUEUE_STATUSES.items()
    }
    applied = session.exec(
        select(func.count()).select_from(Application).where(Application.status != "ready")
    ).one()
    return DashboardSummary(status_counts=counts, queues=queues, applied=applied)
```

```python
# src/resume_agent/api/schemas/dashboard.py
from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class DashboardSummaryOut(CamelModel):
    status_counts: dict[str, int]
    queues: dict[str, int]
    applied: int
```

```python
# src/resume_agent/api/routers/dashboard.py
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.schemas.dashboard import DashboardSummaryOut
from resume_agent.services.dashboard import summarize_dashboard

router = APIRouter()


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(session: Session = Depends(get_session)):
    return DashboardSummaryOut.model_validate(summarize_dashboard(session))
```

Register in `app.py` with the guarded routers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_dashboard_summary.py -v`
Expected: 1 passed

- [ ] **Step 5: Full suite, lint, commit**

```bash
.venv/Scripts/python.exe -m pytest && ruff check
git add -A src/resume_agent tests/api/test_dashboard_summary.py contracts
git commit -m "feat(api): GET /api/dashboard/summary funnel + queue counts"
```

---

### Task 8: CLI/TUI compatibility check for temp-path plumbing

**Files:**

- Modify: `tests/api/conftest.py` (only if needed — see step 1)
- Test: existing suite

The new `create_app` params (`config_dir`, `env_path`, `data_dir`) default to
the production paths, so `resume-agent serve` behaves unchanged. This task
verifies no existing test now touches real files.

- [ ] **Step 1: Audit existing API tests for real-path leakage**

Run: `.venv/Scripts/python.exe -m pytest tests/api -v`
Then check: `git status --short config data .env` — expected: no modifications.
If any pre-existing test writes `config/` or `data/profile/documents/` through
the new state, add an autouse fixture next to `_isolate_runs_root` in
`tests/api/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _isolate_new_state(tmp_path, monkeypatch):
    """Keep config/env/data writes inside tmp for tests that use create_app()
    without pinning the new path params."""
    import resume_agent.api.app as app_module
    original = app_module.create_app

    def wrapped(*args, **kwargs):
        kwargs.setdefault("config_dir", tmp_path / "config")
        kwargs.setdefault("env_path", tmp_path / ".env")
        kwargs.setdefault("data_dir", tmp_path / "data")
        return original(*args, **kwargs)

    monkeypatch.setattr(app_module, "create_app", wrapped)
```

Caution: tests import `create_app` directly (`from resume_agent.api.app import
create_app`), so monkeypatching the module attribute does NOT affect them —
only add this fixture if audit shows leakage, and in that case prefer fixing
the individual tests to pass the params explicitly.

- [ ] **Step 2: Commit (only if changes were needed)**

```bash
git add tests/api
git commit -m "test(api): isolate config/env/data paths in API tests"
```

---

### Task 9: OpenAPI contract + generated TS client refresh

**Files:**

- Modify: `contracts/openapi.json`, `contracts/ts/api.ts` (generated)
- Test: `tests/api/test_openapi_contract.py` (existing drift gate)

- [ ] **Step 1: Regenerate the contract**

Run: `bash scripts/gen_ts_client.sh`
Expected: `contracts/openapi.json` and `contracts/ts/api.ts` updated with the
new routes (`/api/config/*`, `/api/secrets`, `/api/profile/documents`,
`/api/profile/build`, `/api/setup/status`, `/api/dashboard/summary`).

- [ ] **Step 2: Run the drift gate + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v` then the full suite.
Expected: PASS.

Also sync the web app's copy if it vendors the schema: check whether
`web/src/lib/api/schema.ts` is generated from `contracts/ts/api.ts` (Read the
header of `web/src/lib/api/schema.ts`; if it says generated, re-run the same
generator or copy per its header instructions).

- [ ] **Step 3: Commit**

```bash
git add contracts web/src/lib/api/schema.ts
git commit -m "chore(contracts): regenerate OpenAPI + TS client for config/setup/profile/dashboard routes"
```

---

## Self-review notes (already applied)

- Spec coverage: §3.1 → Task 1; §3.2 rows → Tasks 2–7 + 9; §3.3 → Task 4/5; §3.4 → Task 3 (env_writer reuse); §7 error rows → Tasks 2–5 tests; CLAUDE.md deferred-list update → Task 5.
- The `refresh_app_settings` helper lives in `deps.py` (not `app.py`) to avoid the router→app circular import.
- `connectors` is deliberately absent from `DOMAIN_SCHEMAS` and covered by a test.
