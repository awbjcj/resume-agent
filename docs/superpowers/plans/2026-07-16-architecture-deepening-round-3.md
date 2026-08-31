# Architecture Deepening Round 3 Implementation Plan

> **Execution mode:** Implement this plan task-by-task in one agent. Do not use
> subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Four deepenings surfaced by the 2026-07-16 architecture review: (A) the Connector registry owns source-unit addressing, (B) the Workspace layout gets a single author behind `resolve_tenant_path`, (C) one shared run-launch seam replaces seven routers' copied submit tails, (D) `JobDetailRow` stops hand-mirroring `ShortlistRow`.

**Architecture:** All four are behavior-preserving refactors that concentrate an existing, duplicated piece of knowledge behind one interface each. No wire-contract changes: `contracts/openapi.json` must be byte-identical after every phase. Vocabulary follows CONTEXT.md (Connector, Unit, Board seam, Workspace, UserContext) and the review's glossary (module, interface, seam, adapter, depth, locality, leverage).

**Tech Stack:** Python 3.12, FastAPI, SQLModel, pydantic v2, pytest (offline — every agent and the browser are faked).

## Global Constraints

> **Status 2026-07-19:** Phase A (Tasks 1–3) shipped in `72dc10c`. Phases B–D
> executed via `2026-07-19-architecture-deepening-round-4.md` Task 1.

- Test command: `.venv/Scripts/python.exe -m pytest` (offline; no API key, no network). Lint: `ruff check`.
- `contracts/openapi.json` must not change in any task (`tests/api/test_openapi_contract.py` is the drift gate). No schema, route, or wire-shape edits anywhere in this plan.
- Behavior-preserving: every existing test must pass unmodified unless a task explicitly says otherwise (no task in this plan modifies an existing test's assertions).
- ADR alignment: Phase B rides ADR-0003 (contextvar tenancy propagation); nothing here may add a second propagation mechanism — deleting the hand-threaded one is the point.
- Windows dev box: use `.venv/Scripts/python.exe -m pytest ...` exactly as written.
- Commit after every task (small, single-purpose commits).
- Keep intermediate verification narrow: run the task's focused tests and scoped
  lint only. Defer every task-local "full suite" instruction to Final verification;
  this plan's final gate is the one broad backend + web + browser pass.

## Correctness amendments (implementation audit)

The pre-implementation audit found and corrected four contract hazards in the
draft plan:

1. `ConnectorSpec.section` is a required field, not a default returning `None`.
   Every spec promises an enabled section, so an incomplete future registry row
   must fail at construction instead of failing later during Source Manager CRUD.
2. The tenancy RED tests change into `tmp_path` before exercising unresolved
   relative paths. The expected failure may create `data/connector_runs.json`,
   but it must never create that stray file in the repository checkout.
3. The layout migration includes `discovery/pipeline.py`'s
   `SKILL_ALIASES_PATH`; otherwise `data/skill_aliases.json` would still have two
   authors and the stated grep gate would be false.
4. Final verification includes the web test/lint/build gates and a headless
   Playwright smoke flow in addition to the Python/OpenAPI checks. The refactor
   crosses API launch and response boundaries even though it intentionally does
   not change the web wire contract.

---

## Background for implementers (read once)

**Key facts you'd otherwise have to rediscover:**

1. `resolve_tenant_path` (`src/resume_tailor_harness/tenancy/paths.py`) rebases relative paths whose first segment is `data`, `config`, or `output` into the active Workspace (from the `UserContext` contextvar). Absolute paths and unknown prefixes pass through unchanged. With no context set, everything passes through unchanged (legacy single-user mode).
2. The config loaders already resolve internally: `config.load_yaml` (used by `load_search_config` and `load_connectors_config`) and `profile.store.load_facts` all call `resolve_tenant_path`. Three leaf modules do **not** (that's Task 4): `discovery/connectors/telemetry.py`, `taxonomy/skills.load_aliases`, and `services/sources._save`.
3. `RunManager.submit` (`api/runs/manager.py:284`) already derives `user_id` and `max_concurrent` from the active context when they are not passed, and `tenancy.limits.active_limit` returns `None` when no context is set — so dropping the explicit `user_id=`/`max_concurrent=` arguments from `api/routers/runs.py::_submit` is behavior-identical.
4. `ConnectorUnit.payload` (in `registry.py`) is the live pydantic object from the loaded `ConnectorsConfig` — mutating it mutates the config that `_save` will write. Every board-like payload model (`GreenhouseBoard`, `LeverBoard`, `AshbyBoard`, `NativeUrlBoard`, `CompanyUrl`, `ScrapeTarget`) has `enabled: bool` and `limit: int | None`; every section model has `enabled: bool`; the three aggregator sections (`adzuna`, `remoteok`, `linkedin`) also have `limit`.
5. `list_source_views` (`discovery/connectors/sources.py`) is deliberately **out of scope**: its per-kind display logic is genuine variation, native-URL kinds already loop generically, and it has its own tests. Do not refactor it in this plan.
6. The sources router's `_config_paths` threading is also **out of scope**: it resolves through the config store, which is its own seam; leave it.

---

# Phase A — the Connector registry owns source-unit addressing

Today `CONNECTOR_SPECS` is documented as "the single enumeration of connector kinds", but `services/sources.py` re-enumerates the kinds by hand in `add_source`, `_apply_enabled`, `_apply_limit`, and `_remove` (~200 lines of parallel branches). These tasks give `ConnectorSpec` the mutation half of unit addressing and rewrite the four functions as table walks.

### Task 1: ConnectorSpec unit-addressing fields + `find_unit` / `spec_for`

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/registry.py`
- Test: `tests/test_connectors_registry.py` (append new tests)

**Interfaces:**

- Consumes: `ConnectorsConfig` and its section/board models (`discovery/connectors/config.py`), `AtsTarget` (`discovery/connectors/detect.py`), id helpers (`discovery/connectors/sources.py`).
- Produces (used by Tasks 2–3):
  - `ConnectorSpec.section: Callable[[ConnectorsConfig], Any]` — the config section object (always set; has `.enabled`).
  - `ConnectorSpec.unit_items: Callable[[ConnectorsConfig], list[Any]] | None` — the mutable payload list; `None` for singleton kinds (adzuna/remoteok/linkedin).
  - `ConnectorSpec.admits: Callable[[AtsTarget | None], bool]` — whether a detected target can become a unit of this kind (token kinds require a token).
  - `ConnectorSpec.new_unit: Callable[[AtsTarget | None, str, str | None], tuple[str, Any]] | None` — `(target, url, label) -> (source_id, payload)`; `None` for kinds that cannot be added.
  - `find_unit(config: ConnectorsConfig, source_id: str) -> tuple[ConnectorSpec, Any] | None` — payload is `None` for singleton kinds.
  - `spec_for(kind: str) -> ConnectorSpec | None`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_connectors_registry.py`:

```python
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.registry import (
    CONNECTOR_SPECS,
    find_unit,
    spec_for,
)


def _sample_config() -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(
        {
            "greenhouse": {"enabled": True, "boards": [{"token": "acme"}]},
            "lever": {"enabled": True, "boards": [{"token": "lev"}]},
            "ashby": {"enabled": True, "boards": [{"token": "ash"}]},
            "workday": {
                "enabled": True,
                "boards": [{"url": "https://acme.wd5.myworkdayjobs.com/External"}],
            },
            "companies": {"enabled": True, "urls": ["https://example.com/careers"]},
            "scrape": {"enabled": True, "targets": [{"url": "https://jobs.example.org/list"}]},
            "adzuna": {"enabled": True},
            "remoteok": {"enabled": True},
            "linkedin": {"enabled": True},
        }
    )


def test_find_unit_round_trips_every_unit():
    config = _sample_config()
    seen = 0
    for spec in CONNECTOR_SPECS:
        for unit in spec.units(config):
            found = find_unit(config, unit.source_id)
            assert found is not None, unit.source_id
            found_spec, payload = found
            assert found_spec.kind == spec.kind
            assert payload is unit.payload
            seen += 1
    assert seen >= 9  # one board-like unit per shape + the three singletons


def test_find_unit_unknown_id_returns_none():
    assert find_unit(_sample_config(), "greenhouse:nope") is None


def test_every_spec_addresses_a_section_with_enabled():
    config = ConnectorsConfig()
    for spec in CONNECTOR_SPECS:
        assert hasattr(spec.section(config), "enabled"), spec.kind


def test_new_unit_produces_addressable_units():
    config = ConnectorsConfig()
    cases = {
        "greenhouse": (AtsTarget(ats="greenhouse", token="acme"), "https://job-boards.greenhouse.io/acme"),
        "workday": (
            AtsTarget(ats="workday", tenant="acme", datacenter="wd5", site="Ext"),
            "https://acme.wd5.myworkdayjobs.com/Ext",
        ),
        "companies": (AtsTarget(ats="companies"), "https://example.com/careers"),
        "scrape": (None, "https://jobs.example.org/list"),
    }
    for kind, (target, url) in cases.items():
        spec = spec_for(kind)
        assert spec is not None and spec.new_unit is not None and spec.unit_items is not None
        source_id, payload = spec.new_unit(target, url, "Label")
        spec.unit_items(config).append(payload)
        assert any(unit.source_id == source_id for unit in spec.units(config)), kind


def test_token_kinds_admit_only_tokened_targets():
    spec = spec_for("greenhouse")
    assert spec is not None
    assert spec.admits(AtsTarget(ats="greenhouse", token="acme"))
    assert not spec.admits(AtsTarget(ats="greenhouse"))
```

(`ConnectorsConfig` is already imported at the top of this test file; `AtsTarget` and the registry names are the only new imports.)

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_registry.py -q`
Expected: FAIL with `ImportError: cannot import name 'find_unit'`.

- [x] **Step 3: Implement the registry additions**

In `src/resume_tailor_harness/discovery/connectors/registry.py`:

Add imports:

```python
from resume_tailor_harness.discovery.connectors.config import (
    AshbyBoard,
    CompanyUrl,
    ConnectorsConfig,
    GreenhouseBoard,
    LeverBoard,
    NativeUrlBoard,
    ScrapeTarget,
)
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
```

(`ConnectorsConfig` is already imported; merge into one import block.)

Extend `ConnectorSpec` (keep the existing fields and docstring; append these fields and doc line):

```python
@dataclass(frozen=True)
class ConnectorSpec:
    """Everything the registry knows about one connector kind.

    ``build`` receives the enabled payloads — all of them for the aggregate
    builder, exactly one for the per-source builder — so both public builders
    collapse to loops over this table. Table order is the canonical dedup order.

    The unit-addressing half (``section``, ``unit_items``, ``admits``,
    ``new_unit``) lets the Source Manager mutate config units through this
    table instead of re-enumerating the kinds by hand.
    """

    kind: str
    section_enabled: Callable[[ConnectorsConfig], bool]
    section: Callable[[ConnectorsConfig], Any]
    units: Callable[[ConnectorsConfig], list[ConnectorUnit]]
    build: Callable[[list[Any], ConnectorsConfig, Settings], Connector]
    pullable: Callable[[Settings], bool] = field(default=lambda settings: True)
    unit_items: Callable[[ConnectorsConfig], list[Any]] | None = None
    admits: Callable[[AtsTarget | None], bool] = field(default=lambda target: True)
    new_unit: Callable[[AtsTarget | None, str, str | None], tuple[str, Any]] | None = None
```

Place `section` with the other required fields before any field with a default
(`pullable`, `unit_items`, `admits`, `new_unit`) so dataclass field ordering stays
legal. Every spec below must set it explicitly.

Add the new fields to every entry in `CONNECTOR_SPECS`:

```python
def _token_admits(target: AtsTarget | None) -> bool:
    return target is not None and bool(target.token)
```

- `greenhouse` spec — add:

```python
        section=lambda c: c.greenhouse,
        unit_items=lambda c: c.greenhouse.boards,
        admits=_token_admits,
        new_unit=lambda target, url, label: (
            f"greenhouse:{target.token}",
            GreenhouseBoard(token=target.token, company=label),
        ),
```

- `lever` spec — add:

```python
        section=lambda c: c.lever,
        unit_items=lambda c: c.lever.boards,
        admits=_token_admits,
        new_unit=lambda target, url, label: (
            f"lever:{target.token}",
            LeverBoard(token=target.token, company=label),
        ),
```

- `ashby` spec — add:

```python
        section=lambda c: c.ashby,
        unit_items=lambda c: c.ashby.boards,
        admits=_token_admits,
        new_unit=lambda target, url, label: (
            f"ashby:{target.token}",
            AshbyBoard(token=target.token, company=label),
        ),
```

- `_native_url_spec(kind)` — add inside the returned `ConnectorSpec(...)`:

```python
        section=lambda c: getattr(c, kind),
        unit_items=lambda c: getattr(c, kind).boards,
        new_unit=lambda target, url, label: (
            native_url_id(kind, url),
            NativeUrlBoard(url=url, company=label),
        ),
```

- `companies` spec — add:

```python
        section=lambda c: c.companies,
        unit_items=lambda c: c.companies.urls,
        new_unit=lambda target, url, label: (
            company_url_id(url),
            CompanyUrl(url=url, label=label),
        ),
```

- `scrape` spec — add:

```python
        section=lambda c: c.scrape,
        unit_items=lambda c: c.scrape.targets,
        new_unit=lambda target, url, label: (
            scrape_target_id(url),
            ScrapeTarget(url=url, label=label),
        ),
```

- `remoteok` spec — add: `section=lambda c: c.remoteok,`
- `adzuna` spec — add: `section=lambda c: c.adzuna,`
- `linkedin` spec — add: `section=lambda c: c.linkedin,`

After `CONNECTOR_SPECS`, add the lookup helpers:

```python
_SPEC_BY_KIND = {spec.kind: spec for spec in CONNECTOR_SPECS}


def spec_for(kind: str) -> ConnectorSpec | None:
    return _SPEC_BY_KIND.get(kind)


def find_unit(config: ConnectorsConfig, source_id: str) -> tuple[ConnectorSpec, Any] | None:
    """Locate one source unit by stable id; payload is None for singleton kinds."""
    for spec in CONNECTOR_SPECS:
        for unit in spec.units(config):
            if unit.source_id == source_id:
                return spec, unit.payload
    return None
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_connectors_registry.py -q`
Expected: PASS (all, including pre-existing tests).

- [x] **Step 5: Lint and commit**

```bash
ruff check src/resume_tailor_harness/discovery/connectors/registry.py tests/test_connectors_registry.py
git add src/resume_tailor_harness/discovery/connectors/registry.py tests/test_connectors_registry.py
git commit -m "feat(registry): ConnectorSpec owns source-unit addressing (section/unit_items/admits/new_unit + find_unit)"
```

---

### Task 2: Rewrite `_apply_enabled` / `_apply_limit` / `_remove` as table walks

**Files:**

- Modify: `src/resume_tailor_harness/services/sources.py:476-616` (the three functions at the bottom of the file)
- Test: `tests/test_services_sources.py` (append new tests)

**Interfaces:**

- Consumes: `find_unit` from Task 1.
- Produces: same public behavior as today — `patch_source`, `set_source_enabled`, `set_source_limit`, `remove_source` are unchanged in signature and semantics. Behavior to preserve exactly:
  - Enabling a board also enables its section; disabling a board does **not** disable the section.
  - Singleton kinds (adzuna/remoteok/linkedin) toggle/limit the section itself and can never be removed (`_remove` returns `False` → `remove_source` raises `SourceError("Unknown source '...'")`).

- [x] **Step 1: Write the failing test**

Append to `tests/test_services_sources.py`. The file already has `import pytest` and `from resume_tailor_harness.services import sources as svc` at the top — the `svc.` references below match its existing style; only the two imports shown need adding:

```python
from resume_tailor_harness.discovery.connectors.config import ConnectorsConfig, load_connectors_config
from resume_tailor_harness.discovery.connectors.registry import CONNECTOR_SPECS


def _every_kind_config() -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(
        {
            "greenhouse": {"enabled": True, "boards": [{"token": "acme"}]},
            "lever": {"enabled": True, "boards": [{"token": "lev"}]},
            "ashby": {"enabled": True, "boards": [{"token": "ash"}]},
            "workday": {
                "enabled": True,
                "boards": [{"url": "https://acme.wd5.myworkdayjobs.com/External"}],
            },
            "companies": {"enabled": True, "urls": ["https://example.com/careers"]},
            "scrape": {"enabled": True, "targets": [{"url": "https://jobs.example.org/list"}]},
            "adzuna": {"enabled": True},
            "remoteok": {"enabled": True},
            "linkedin": {"enabled": True},
        }
    )


def test_patch_source_round_trips_every_unit(tmp_path):
    path = str(tmp_path / "connectors.yaml")
    svc._save(path, _every_kind_config())
    config = load_connectors_config(path)
    ids = [unit.source_id for spec in CONNECTOR_SPECS for unit in spec.units(config)]
    assert len(ids) >= 9
    for source_id in ids:
        view = svc.patch_source(source_id, enabled=False, connectors_path=path)
        assert view.enabled is False, source_id
        view = svc.patch_source(source_id, enabled=True, limit=7, connectors_path=path)
        assert view.enabled is True, source_id
        assert view.limit == 7, source_id


def test_remove_source_removes_boards_but_never_singletons(tmp_path):
    path = str(tmp_path / "connectors.yaml")
    svc._save(path, _every_kind_config())
    config = load_connectors_config(path)
    board_ids = [
        unit.source_id
        for spec in CONNECTOR_SPECS
        if spec.unit_items is not None
        for unit in spec.units(config)
    ]
    for source_id in board_ids:
        svc.remove_source(source_id, connectors_path=path)
        with pytest.raises(svc.SourceError, match="Unknown source"):
            svc.patch_source(source_id, enabled=True, connectors_path=path)
    for source_id in ("adzuna", "remoteok", "linkedin"):
        with pytest.raises(svc.SourceError, match="Unknown source"):
            svc.remove_source(source_id, connectors_path=path)
```

- [x] **Step 2: Run the new tests to verify current behavior (they should PASS against the old code)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_sources.py -q`
Expected: PASS. These are characterization tests — they pin today's behavior so the rewrite in Step 3 can't drift. (If either fails here, stop: the sample config or an assumption is wrong; fix the test before touching the implementation.)

- [x] **Step 3: Replace the three functions**

In `src/resume_tailor_harness/services/sources.py`, add to the imports:

```python
from resume_tailor_harness.discovery.connectors.registry import find_unit
```

Delete the bodies of `_apply_enabled` (lines ~476-525), `_apply_limit` (~528-563), and `_remove` (~566-616) and replace with:

```python
def _apply_enabled(config: ConnectorsConfig, source_id: str, enabled: bool) -> bool:
    found = find_unit(config, source_id)
    if found is None:
        return False
    spec, payload = found
    section = spec.section(config)
    if payload is None:
        section.enabled = enabled
        return True
    if enabled:
        section.enabled = True
    payload.enabled = enabled
    return True


def _apply_limit(config: ConnectorsConfig, source_id: str, limit: int | None) -> bool:
    found = find_unit(config, source_id)
    if found is None:
        return False
    spec, payload = found
    target = payload if payload is not None else spec.section(config)
    target.limit = limit
    return True


def _remove(config: ConnectorsConfig, source_id: str) -> bool:
    found = find_unit(config, source_id)
    if found is None:
        return False
    spec, payload = found
    if payload is None or spec.unit_items is None:
        return False
    spec.unit_items(config).remove(payload)
    return True
```

Then remove any imports that became unused (run `ruff check` — it will name them; `NATIVE_URL_KINDS`, `native_url_id`, `company_url_id`, `scrape_target_id` may still be used elsewhere in the file, so trust ruff, not this list).

- [x] **Step 4: Run the sources test files**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_sources.py tests/test_services_sources_preview.py tests/test_cli_sources.py tests/api/test_schemas_sources.py tests/test_connector_sources.py -q`
Expected: PASS.

- [x] **Step 5: Lint and commit**

```bash
ruff check src/resume_tailor_harness/services/sources.py tests/test_services_sources.py
git add src/resume_tailor_harness/services/sources.py tests/test_services_sources.py
git commit -m "refactor(sources): enable/limit/remove walk CONNECTOR_SPECS instead of hand-enumerating kinds"
```

---

### Task 3: Rewrite `add_source` over the spec table

**Files:**

- Modify: `src/resume_tailor_harness/services/sources.py:320-420` (`add_source`), plus two new private helpers above it
- Test: `tests/test_services_sources.py` (existing add-source tests must pass unmodified)

**Interfaces:**

- Consumes: `spec_for`, `find_unit` from Task 1; `ConnectorSpec.new_unit/admits/section/unit_items`.
- Produces: `add_source` unchanged in signature and semantics, including the exact duplicate error messages:
  - token kinds: `"Greenhouse board 'acme' is already a source."` (kind title-cased)
  - native-URL kinds: `"This Workday board is already a source."`
  - companies: `"This URL is already a source."`
  - scrape: `"This URL is already a scrape target."`

- [x] **Step 1: Add helpers and rewrite `add_source`**

Add above `add_source` (imports: extend the registry import to `from resume_tailor_harness.discovery.connectors.registry import find_unit, spec_for`, and make sure `ConnectorSpec` is imported for type hints: `from resume_tailor_harness.discovery.connectors.registry import ConnectorSpec, find_unit, spec_for`; `Any` from `typing`):

```python
def _duplicate_message(spec: ConnectorSpec, payload: Any) -> str:
    if spec.kind == "companies":
        return "This URL is already a source."
    if spec.kind == "scrape":
        return "This URL is already a scrape target."
    token = getattr(payload, "token", "")
    if token:
        return f"{spec.kind.title()} board '{token}' is already a source."
    return f"This {spec.kind.title()} board is already a source."


def _append_unit(
    config: ConnectorsConfig,
    spec: ConnectorSpec,
    *,
    target: AtsTarget | None,
    url: str,
    label: str | None,
) -> str:
    """Append one new unit through the spec table; returns its source id."""
    if spec.new_unit is None or spec.unit_items is None:
        raise SourceError(f"Sources of kind '{spec.kind}' cannot be added.")
    source_id, payload = spec.new_unit(target, url, label)
    if any(unit.source_id == source_id for unit in spec.units(config)):
        raise SourceError(_duplicate_message(spec, payload))
    spec.section(config).enabled = True
    spec.unit_items(config).append(payload)
    return source_id
```

Replace the body of `add_source` from the `if provider == "scrape":` block through the end of the function with:

```python
    if provider == "scrape":
        preview = preview_source(url, label=label, provider="scrape")
        if not preview.ok:
            raise SourceError(preview.error or "Could not validate this source.")
        config = (
            load_connectors_config(connectors_path)
            if Path(connectors_path).exists()
            else ConnectorsConfig()
        )
        scrape_spec = spec_for("scrape")
        assert scrape_spec is not None
        new_id = _append_unit(
            config, scrape_spec, target=None, url=preview.url, label=label
        )
        _save(connectors_path, config)
        return _view(config, new_id)

    if (
        provider == "auto"
        and search_path == DEFAULT_SEARCH
        and token is None
        and tenant is None
        and datacenter is None
        and site is None
        and country == "com"
    ):
        # Preserve the original service call shape for CLI/internal callers and
        # their test doubles. API requests pass their tenant-specific search path.
        preview = preview_source(url, label=label)
    else:
        preview = preview_source(
            url,
            label=label,
            search_path=search_path,
            provider=provider,
            token=token,
            tenant=tenant,
            datacenter=datacenter,
            site=site,
            country=country,
        )
    if not preview.ok:
        raise SourceError(preview.error or "Could not validate this source.")

    url = preview.url

    config = load_connectors_config(connectors_path)
    target = detect_ats(url)
    if target is None:
        raise SourceError("Could not detect a known ATS behind this URL.")

    spec = spec_for(target.ats)
    if spec is None or spec.new_unit is None or not spec.admits(target):
        spec = spec_for("companies")
        assert spec is not None

    new_id = _append_unit(config, spec, target=target, url=url, label=label)
    _save(connectors_path, config)
    return _view(config, new_id)
```

Then delete now-unused imports (`GreenhouseBoard`? — no: `_preview_connector` still uses `GreenhouseBoard`/`LeverBoard`; `AshbyBoard`, `NativeUrlBoard`, `CompanyUrl`, `ScrapeTarget` become unused — again trust `ruff check` to name the dead ones).

- [x] **Step 2: Run the sources tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_sources.py tests/test_services_sources_preview.py tests/test_cli_sources.py tests/api/test_schemas_sources.py -q`
Expected: PASS with zero test edits. If a duplicate-message assertion fails, fix `_duplicate_message` to match the asserted string — the old messages are the contract.

- [x] **Step 3: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS.

- [x] **Step 4: Lint and commit**

```bash
ruff check src/resume_tailor_harness/services/sources.py
git add src/resume_tailor_harness/services/sources.py
git commit -m "refactor(sources): add_source appends units through CONNECTOR_SPECS"
```

---

# Phase B — the Workspace layout gets one author

`resolve_tenant_path` is already the deep seam (config loaders and `load_facts` resolve through it), but three leaf modules bypass it — which is why `api/routers/runs.py` hand-threads absolute workspace paths — and the layout literals (`"data/profile/facts.json"` etc.) are declared in nine modules.

### Task 4: Leaf modules resolve tenant paths

**Files:**

- Modify: `src/resume_tailor_harness/discovery/connectors/telemetry.py`
- Modify: `src/resume_tailor_harness/taxonomy/skills.py:59-76` (`load_aliases`)
- Modify: `src/resume_tailor_harness/services/sources.py:77-88` (`_save`)
- Test: `tests/tenancy/test_workspace.py` (append)

**Interfaces:**

- Consumes: `resolve_tenant_path(path: Path | str) -> Path` (`tenancy/paths.py`).
- Produces: `read_runs` / `record_run` / `load_aliases` / `_save` accept the same arguments but rebase relative `data/` / `config/` paths into the active Workspace when a `UserContext` is set. With no context: byte-identical behavior (resolve is a pass-through).

- [x] **Step 1: Write the failing test**

Append to `tests/tenancy/test_workspace.py`:

```python
from resume_tailor_harness.config import Settings
from resume_tailor_harness.discovery.connectors.telemetry import read_runs, record_run
from resume_tailor_harness.taxonomy.skills import load_aliases
from resume_tailor_harness.tenancy.context import UserContext, use_context
from resume_tailor_harness.tenancy.workspace import WorkspacePaths


def _context(tmp_path):
    return UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "alice"),
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )


def test_record_run_lands_in_the_active_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = _context(tmp_path)
    with use_context(context):
        record_run("data/connector_runs.json", "greenhouse", added=3, error=None)
        assert read_runs("data/connector_runs.json")["greenhouse"]["added"] == 3
    telemetry_file = context.paths.root / "connector_runs.json"
    assert telemetry_file.exists()


def test_load_aliases_resolves_the_active_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    context = _context(tmp_path)
    aliases_file = context.paths.root / "skill_aliases.json"
    aliases_file.parent.mkdir(parents=True, exist_ok=True)
    aliases_file.write_text('{"reactjs": "react"}', encoding="utf-8")
    with use_context(context):
        assert load_aliases("data/skill_aliases.json") == {"reactjs": "react"}
```

Note: `resolve_tenant_path` maps the `data/` prefix to `context.paths.root`, so `data/connector_runs.json` → `<workspace>/connector_runs.json`. That matches what `api/routers/runs.py` threads today (`context.workspace / "connector_runs.json"`).

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_workspace.py -q`
Expected: the two new tests FAIL (file written to CWD-relative `data/`, not the workspace). If they accidentally write into the repo's `data/` directory, delete the stray file: `git status` must stay clean of `data/connector_runs.json`.

- [x] **Step 3: Implement**

`src/resume_tailor_harness/discovery/connectors/telemetry.py` — full new content:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from resume_tailor_harness.tenancy.paths import resolve_tenant_path


def read_runs(path: str | Path) -> dict[str, dict]:
    """Return the per-connector run record, or {} if the file does not exist."""
    p = resolve_tenant_path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def record_run(path: str | Path, name: str, added: int, error: str | None) -> None:
    """Upsert one connector's last run."""
    p = resolve_tenant_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    runs = read_runs(p)
    runs[name] = {
        "last_run": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "added": added,
        "error": error,
    }
    p.write_text(json.dumps(runs, indent=2), encoding="utf-8")
```

`src/resume_tailor_harness/taxonomy/skills.py` — in `load_aliases`, change only the first body line:

```python
    p = resolve_tenant_path(path)
```

with a lazy import at the top of the function (matches the pattern `config.load_yaml` uses):

```python
    from resume_tailor_harness.tenancy.paths import resolve_tenant_path
```

`src/resume_tailor_harness/services/sources.py` — in `_save`, change the first line:

```python
    target = resolve_tenant_path(path)
```

and add the import `from resume_tailor_harness.tenancy.paths import resolve_tenant_path`. Also in `add_source`'s scrape branch (written in Task 3), change `Path(connectors_path).exists()` to `resolve_tenant_path(connectors_path).exists()` so the load/save pair can never split across directories.

- [x] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy -q && .venv/Scripts/python.exe -m pytest -q`
Expected: PASS (full suite — these are leaf functions with many indirect callers).

- [x] **Step 5: Lint and commit**

```bash
ruff check src/resume_tailor_harness/discovery/connectors/telemetry.py src/resume_tailor_harness/taxonomy/skills.py src/resume_tailor_harness/services/sources.py tests/tenancy/test_workspace.py
git add -A
git commit -m "fix(tenancy): telemetry, skill aliases, and connectors save resolve the active workspace"
```

---

### Task 5: Layout constants in `tenancy/paths.py`; migrate every literal declaration

**Files:**

- Modify: `src/resume_tailor_harness/tenancy/paths.py`
- Modify: `src/resume_tailor_harness/services/discovery.py:55-58`, `src/resume_tailor_harness/services/tailoring.py:27-29`, `src/resume_tailor_harness/services/board.py:48`, `src/resume_tailor_harness/services/cover_letters.py:18`, `src/resume_tailor_harness/services/cover_letter_revision.py:16`, `src/resume_tailor_harness/services/revision.py:20-21`
- Modify: `src/resume_tailor_harness/cli.py:82,455-457`
- Modify: `src/resume_tailor_harness/api/routers/match_gap.py:32`, `src/resume_tailor_harness/api/routers/suggestions.py:44`
- Modify: `src/resume_tailor_harness/tracking/queries.py` (the two `aliases_path: str | Path = "data/skill_aliases.json"` defaults — actually three: `shortlist_rows`, `job_facets`, `job_detail_row`)
- Modify: `src/resume_tailor_harness/discovery/pipeline.py:50` (`SKILL_ALIASES_PATH`)
- Test: no new tests — this is a constant relocation; the full suite is the check.

**Interfaces:**

- Produces (used by Task 7 and future code): module constants in `resume_tailor_harness.tenancy.paths`:

```python
FACTS_PATH = "data/profile/facts.json"
SEARCH_PATH = "config/search.yaml"
CONNECTORS_PATH = "config/connectors.yaml"
REVIEW_PATH = "config/review.yaml"
REVIEW_DEEP_PATH = "config/review_deep.yaml"
TELEMETRY_PATH = "data/connector_runs.json"
SKILL_ALIASES_PATH = "data/skill_aliases.json"
```

- Existing public names (`DEFAULT_FACTS`, `DEFAULT_SEARCH`, `DEFAULT_CONNECTORS`, `CONNECTOR_RUNS_PATH`, `DEFAULT_REVIEW`, `DEFAULT_REVIEW_DEEP`) **stay importable from their current modules** — they become aliases so no caller or test breaks.

- [x] **Step 1: Add the constants block**

Append to `src/resume_tailor_harness/tenancy/paths.py` (below the imports, above `resolve_tenant_path`):

```python
# Canonical Workspace layout. Every artifact a service or adapter defaults to
# is named exactly once here, as the relative path resolve_tenant_path rebases
# into the active Workspace (or leaves CWD-relative in legacy single-user mode).
FACTS_PATH = "data/profile/facts.json"
SEARCH_PATH = "config/search.yaml"
CONNECTORS_PATH = "config/connectors.yaml"
REVIEW_PATH = "config/review.yaml"
REVIEW_DEEP_PATH = "config/review_deep.yaml"
TELEMETRY_PATH = "data/connector_runs.json"
SKILL_ALIASES_PATH = "data/skill_aliases.json"
```

- [x] **Step 2: Migrate each declaration site to an aliasing import**

`src/resume_tailor_harness/services/discovery.py` — replace lines 55-58:

```python
from resume_tailor_harness.tenancy.paths import (
    CONNECTORS_PATH as DEFAULT_CONNECTORS,
    FACTS_PATH as DEFAULT_FACTS,
    SEARCH_PATH as DEFAULT_SEARCH,
    TELEMETRY_PATH as CONNECTOR_RUNS_PATH,
)
```

(the module already imports `resolve_tenant_path` from the same place — merge into one import statement).

`src/resume_tailor_harness/services/tailoring.py` — replace lines 27-29:

```python
from resume_tailor_harness.tenancy.paths import (
    FACTS_PATH as DEFAULT_FACTS,
    REVIEW_DEEP_PATH as DEFAULT_REVIEW_DEEP,
    REVIEW_PATH as DEFAULT_REVIEW,
    resolve_tenant_path,
)
```

(delete the module's existing `from resume_tailor_harness.tenancy.paths import resolve_tenant_path` line so there is exactly one import from the module.)

`src/resume_tailor_harness/services/board.py:48`, `services/cover_letters.py:18`, `services/cover_letter_revision.py:16` — replace `DEFAULT_FACTS = "data/profile/facts.json"` with `from resume_tailor_harness.tenancy.paths import FACTS_PATH as DEFAULT_FACTS` (merged into existing tenancy.paths imports where present).

`src/resume_tailor_harness/services/revision.py:20-21` — replace both constants:

```python
from resume_tailor_harness.tenancy.paths import (
    FACTS_PATH as DEFAULT_FACTS,
    REVIEW_PATH as DEFAULT_REVIEW,
)
```

`src/resume_tailor_harness/cli.py` — replace line 82 (`DEFAULT_FACTS = ...`) and lines 455-457 (`DEFAULT_SEARCH`/`DEFAULT_CONNECTORS`/`CONNECTOR_RUNS_PATH`) with one import near the top:

```python
from resume_tailor_harness.tenancy.paths import (
    CONNECTORS_PATH as DEFAULT_CONNECTORS,
    FACTS_PATH as DEFAULT_FACTS,
    SEARCH_PATH as DEFAULT_SEARCH,
    TELEMETRY_PATH as CONNECTOR_RUNS_PATH,
)
```

`src/resume_tailor_harness/api/routers/match_gap.py:32` — replace `_FACTS_PATH = "data/profile/facts.json"` with `from resume_tailor_harness.tenancy.paths import FACTS_PATH as _FACTS_PATH` (merge with the existing `from resume_tailor_harness.tenancy.paths import resolve_tenant_path`).

`src/resume_tailor_harness/api/routers/suggestions.py:44` — same replacement for its `_FACTS_PATH`.

`src/resume_tailor_harness/tracking/queries.py` — change the three defaults `aliases_path: str | Path = "data/skill_aliases.json"` to `aliases_path: str | Path = SKILL_ALIASES_PATH` with `from resume_tailor_harness.tenancy.paths import SKILL_ALIASES_PATH` added to the imports.

`src/resume_tailor_harness/discovery/pipeline.py` — replace the local declaration with
`from resume_tailor_harness.tenancy.paths import SKILL_ALIASES_PATH`. The constant is a
string, which remains valid for the existing `Path | str` parameter and is
resolved by `load_aliases` at the leaf.

- [x] **Step 3: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS / clean. Grep-verify no stray declarations remain:

Run: `grep -rn "data/profile/facts.json\|config/search.yaml\|config/connectors.yaml\|data/connector_runs.json" src/resume_tailor_harness --include="*.py" | grep -v tenancy/paths.py | grep -v "\.example\|Copy config"`
Expected: only `tenancy/paths.py` declares the strings; remaining hits are user-facing help text in `cli.py`/`setup/screens.py` (leave those) and `search_config.py`'s docstring (leave it).

- [x] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(tenancy): workspace layout constants have one author in tenancy/paths"
```

---

# Phase C — one launch seam for background runs

Seven routers copy the submit → get → assert → `record_to_run` tail; `runs.py` additionally hand-threads workspace paths that Phase B made redundant, and hand-writes the "worker opens its OWN session" rule in every closure.

### Task 6: `api/runs/launch.py` — `launch()` + `session_work()`

**Files:**

- Create: `src/resume_tailor_harness/api/runs/launch.py`
- Test: `tests/api/test_launch_helper.py` (new)

**Interfaces:**

- Consumes: `RunManager.submit(kind, fn, *, singleton_key, singleton_conflict, meta)` (context-derived `user_id`/`max_concurrent` — see Background fact 3), `RunSingletonConflict`/`RunResetConflict`/`RunQuotaError` (`api/runs/manager.py`), `record_to_run` (`api/runs/sse.py`), `ApiException` (`api/errors.py`), `get_session` (`db.py`).
- Produces (used by Tasks 7–8):

```python
def launch(
    mgr: RunManager,
    kind: str,
    work,                       # fn(reporter) -> dict, run in the worker thread
    *,
    singleton_key: str | None = None,
    singleton_conflict: str = "join",
    meta: dict[str, object] | None = None,
    busy_code: str | None = None,
    busy_message: str = "A run is already active for this item",
) -> RunOut

def session_work(engine, fn):   # fn(session, reporter) -> dict
```

- [x] **Step 1: Write the failing tests**

Create `tests/api/test_launch_helper.py`:

```python
import pytest

from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.runs.launch import launch, session_work
from resume_tailor_harness.api.runs.manager import (
    RunQuotaError,
    RunResetConflict,
    RunSingletonConflict,
)


class _RecordStub:
    """Every attribute record_to_run reads off a RunSnapshot (api/runs/sse.py:13)."""

    kind = "pull"
    state = "running"
    label = None
    percent = None
    current = None
    total = None
    eta_text = None
    result = None
    error = None
    error_code = None
    meta = None

    def __init__(self, run_id: str):
        self.run_id = run_id


class _ManagerStub:
    def __init__(self, error: Exception | None = None):
        self._error = error
        self.submitted: dict | None = None

    def submit(self, kind, fn, *, singleton_key=None, singleton_conflict="join", meta=None):
        if self._error is not None:
            raise self._error
        self.submitted = {
            "kind": kind,
            "singleton_key": singleton_key,
            "singleton_conflict": singleton_conflict,
            "meta": meta,
        }
        return "run-1"

    def get(self, run_id):
        return _RecordStub(run_id)


def test_launch_submits_and_returns_runout():
    mgr = _ManagerStub()
    out = launch(mgr, "pull", lambda reporter: {}, singleton_key="pull", meta={"a": 1})
    assert out.run_id == "run-1"
    assert mgr.submitted == {
        "kind": "pull",
        "singleton_key": "pull",
        "singleton_conflict": "join",
        "meta": {"a": 1},
    }


def test_launch_maps_singleton_conflict_to_409():
    mgr = _ManagerStub(error=RunSingletonConflict("run-9"))
    with pytest.raises(ApiException) as excinfo:
        launch(mgr, "pull", lambda reporter: {}, singleton_key="pull",
               singleton_conflict="raise")
    assert excinfo.value.status_code == 409
    assert excinfo.value.details == {"runId": "run-9"}


def test_launch_busy_code_overrides_default():
    mgr = _ManagerStub(error=RunSingletonConflict("run-9"))
    with pytest.raises(ApiException) as excinfo:
        launch(mgr, "coach", lambda reporter: {}, busy_code="COACH_BUSY",
               busy_message="A coach turn is already running")
    assert excinfo.value.code == "COACH_BUSY"
    assert excinfo.value.message == "A coach turn is already running"


def test_launch_maps_quota_to_429_and_reset_to_409():
    with pytest.raises(ApiException) as excinfo:
        launch(_ManagerStub(error=RunQuotaError("too many")), "pull", lambda r: {})
    assert excinfo.value.status_code == 429
    with pytest.raises(ApiException) as excinfo:
        launch(_ManagerStub(error=RunResetConflict("reset underway")), "pull", lambda r: {})
    assert excinfo.value.status_code == 409


def test_session_work_opens_its_own_session(tmp_path):
    from resume_tailor_harness.db import init_db, make_engine

    engine = make_engine(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    init_db(engine)
    seen = {}

    def fn(session, reporter):
        seen["session"] = session
        seen["reporter"] = reporter
        return {"ok": True}

    work = session_work(engine, fn)
    assert work("REPORTER") == {"ok": True}
    assert seen["reporter"] == "REPORTER"
    assert seen["session"] is not None
```

Attribute names verified against `api/errors.py:28`: the constructor is `ApiException(status_code, code, message, details=None)` and stores each under the same name — the test's `excinfo.value.status_code` / `.code` / `.message` / `.details` are correct as written.

- [x] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_launch_helper.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'resume_tailor_harness.api.runs.launch'`.

- [x] **Step 3: Implement `src/resume_tailor_harness/api/runs/launch.py`**

```python
"""The run-launch seam shared by every router that starts a background run.

Owns the whole launch tail: submit through RunManager (which derives user_id
and max_concurrent from the active UserContext), map the three launch-time
errors onto the API error envelope, and convert the created record to RunOut.

``session_work`` owns the one threading invariant every worker must honor:
the worker opens its OWN session bound to the app engine — never the request
session, which is not safe to share across threads.
"""

from __future__ import annotations

from typing import Any, Callable

from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.runs.manager import (
    RunManager,
    RunQuotaError,
    RunResetConflict,
    RunSingletonConflict,
)
from resume_tailor_harness.api.runs.sse import record_to_run
from resume_tailor_harness.api.schemas.runs import RunOut
from resume_tailor_harness.db import get_session


def launch(
    mgr: RunManager,
    kind: str,
    work: Callable[[Any], dict],
    *,
    singleton_key: str | None = None,
    singleton_conflict: str = "join",
    meta: dict[str, object] | None = None,
    busy_code: str | None = None,
    busy_message: str = "A run is already active for this item",
) -> RunOut:
    try:
        run_id = mgr.submit(
            kind,
            work,
            singleton_key=singleton_key,
            singleton_conflict=singleton_conflict,
            meta=meta,
        )
    except RunSingletonConflict as error:
        raise ApiException(
            409,
            busy_code or error.code,
            busy_message,
            details={"runId": error.run_id},
        ) from error
    except RunResetConflict as error:
        raise ApiException(409, error.code, str(error)) from error
    except RunQuotaError as error:
        raise ApiException(429, error.code, str(error)) from error
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


def session_work(engine, fn: Callable[[Any, Any], dict]) -> Callable[[Any], dict]:
    """Wrap ``fn(session, reporter)`` in a worker-owned session."""

    def work(reporter):
        with get_session(engine) as session:
            return fn(session, reporter)

    return work
```

(Verified: `make_engine`, `init_db`, and `get_session` are all defined in `src/resume_tailor_harness/db.py`.)

- [x] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_launch_helper.py -q`
Expected: PASS.

- [x] **Step 5: Lint and commit**

```bash
ruff check src/resume_tailor_harness/api/runs/launch.py tests/api/test_launch_helper.py
git add src/resume_tailor_harness/api/runs/launch.py tests/api/test_launch_helper.py
git commit -m "feat(api): shared launch() + session_work() run-launch seam"
```

---

### Task 7: Rewrite the runs router over `launch`/`session_work`, dropping path threading

**Files:**

- Modify: `src/resume_tailor_harness/api/routers/runs.py` (whole launch section)
- Test: existing `tests/api/test_runs_launch.py`, `tests/api/test_runs_list.py`, `tests/api/test_runs_sse.py`, `tests/api/test_run_tenancy_quota.py` — must pass unmodified.

**Interfaces:**

- Consumes: `launch` / `session_work` (Task 6); services with their default paths, which now resolve into the workspace by Tasks 4–5 (`pull_jobs`, `discover_jobs`, `refresh_jobs`, `reprocess_jobs`, `scrape_linkedin_jobs`, `tailor`, `write_cover_letters`, `revise_resume_version`, `revise_cover_letter_version`, `add_job_from_url`).
- Produces: identical HTTP behavior. The only intentional deltas: (a) `RunResetConflict` now maps to 409 instead of an unhandled 500, (b) the generic singleton-conflict message applies to join-mode kinds (unreachable in practice — only `raise`-mode kinds can surface it).

**Why dropping the path kwargs is safe:** `_workspace_args()` and the inline ternaries compute exactly the absolute paths that `resolve_tenant_path` now produces from the services' own relative defaults (Background facts 1–2 + Task 4). The RunManager worker restores the caller's `UserContext` (ADR-0003), so resolution inside the worker sees the same workspace.

- [x] **Step 1: Delete the shallow helpers**

In `src/resume_tailor_harness/api/routers/runs.py` delete:

- `_WorkspaceArgs` and `_workspace_args()` (lines 63-78)
- `_submit(...)` (lines 81-111)

and their now-unused imports (`TypedDict`, `active_limit`, `DEFAULT_MAX_CONCURRENT_RUNS`, `RunQuotaError`, `RunSingletonConflict`). Keep `current_context` (still used by `_owned_record` and `list_runs`). Add:

```python
from resume_tailor_harness.api.runs.launch import launch, session_work
```

- [x] **Step 2: Rewrite each endpoint**

The twelve launch endpoints become (complete replacements — signatures and decorators unchanged unless shown):

```python
@router.post("/resume-versions/{version_id}/revise", response_model=RunOut, status_code=202)
def launch_resume_revise(
    version_id: int,
    body: ReviseRequest,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    with get_session(engine) as session:
        parent = get_resume_version(session, version_id)
        if parent is None:
            raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
        job_id = parent.job_id

    def do_revise(session, reporter):
        reporter.begin(1, f"Revising resume version #{version_id}")
        child = revise_resume_version(
            session, version_id, body.instruction, re_review=body.re_review
        )
        reporter.step(1)
        return {"versionId": child.id if child else None, "jobId": child.job_id if child else job_id}

    meta = {"versionId": version_id, "jobId": job_id, "instruction": body.instruction, "reReview": body.re_review}
    return launch(
        mgr, "revise", session_work(engine, do_revise),
        singleton_key=f"revise:{version_id}", singleton_conflict="raise", meta=meta,
        busy_message="A revision is already running for this item",
    )


@router.post("/cover-letters/{cover_letter_id}/revise", response_model=RunOut, status_code=202)
def launch_cover_letter_revise(
    cover_letter_id: int,
    body: ReviseRequest,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    with get_session(engine) as session:
        parent = get_cover_letter(session, cover_letter_id)
        if parent is None:
            raise ApiException(404, "NOT_FOUND", f"Cover letter #{cover_letter_id} not found")
        job_id = parent.job_id

    def do_revise(session, reporter):
        reporter.begin(1, f"Revising cover letter #{cover_letter_id}")
        child = revise_cover_letter_version(session, cover_letter_id, body.instruction)
        reporter.step(1)
        return {"coverLetterId": child.id if child else None, "jobId": child.job_id if child else job_id}

    meta = {"coverLetterId": cover_letter_id, "jobId": job_id, "instruction": body.instruction}
    return launch(
        mgr, "coverLetterRevise", session_work(engine, do_revise),
        singleton_key=f"cover-letter-revise:{cover_letter_id}", singleton_conflict="raise", meta=meta,
        busy_message="A revision is already running for this item",
    )
```

`launch_import_urls`: keep its body through the `allow_browser = ...` line and its custom multi-session `work(reporter)` closure exactly as today, then replace the three-line tail with:

```python
    return launch(mgr, "importUrls", work)
```

```python
@router.post("/discover", response_model=RunOut, status_code=202)
def launch_discover(
    request: Request,
    params: DiscoverParams | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def do_discover(session, reporter):
        return {"statusCounts": discover_jobs(session, reporter=reporter)}

    return launch(mgr, "discover", session_work(engine, do_discover))


@router.post("/reprocess", response_model=RunOut, status_code=202)
def launch_reprocess(
    request: Request,
    params: ReprocessParams | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    scopes = params.scopes if params is not None and params.scopes else ["shortlisted"]

    def do_reprocess(session, reporter):
        return {"statusCounts": reprocess_jobs(session, scopes=scopes, reporter=reporter)}

    return launch(mgr, "reprocess", session_work(engine, do_reprocess))


@router.post("/refresh", response_model=RunOut, status_code=202)
def launch_refresh(
    request: Request,
    params: RefreshParams | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)
    limit = params.limit if params is not None else None

    def do_refresh(session, reporter):
        report = refresh_jobs(session, limit=limit, reporter=reporter)
        return {
            "pulled": report.pulled,
            "totals": report.totals,
            "statusCounts": report.status_counts,
            "failures": report.failures,
        }

    return launch(mgr, "refresh", session_work(engine, do_refresh), singleton_key="refresh")


@router.post("/pull", response_model=RunOut, status_code=202)
def launch_pull(
    params: PullParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def do_pull(session, reporter):
        report = pull_jobs(
            session,
            limit=params.limit,
            source_ids=params.source_ids,
            reporter=reporter,
            skip_known=not bool(params.refresh),
        )
        return {
            "totals": report.totals,
            "upgraded": report.upgraded,
            "skipped": report.skipped,
            "failures": report.failures,
        }

    return launch(mgr, "pull", session_work(engine, do_pull), singleton_key="pull")


@router.post("/tailor", response_model=RunOut, status_code=202)
def launch_tailor(
    params: TailorParams, request: Request, mgr: RunManager = Depends(get_run_manager)
):
    engine = _engine(request)

    def do_tailor(session, reporter):
        results = tailor(
            session,
            job_ids=params.job_ids,
            approved=params.approved,
            review_path=DEFAULT_REVIEW_DEEP if params.deep else DEFAULT_REVIEW,
            reporter=reporter,
            fail_on_partial=True,
        )
        return {
            "jobs": [
                {
                    "jobId": jid,
                    "versionCount": len(v),
                    "factCheckPassed": v[-1].fact_check_passed if v else False,
                }
                for jid, v in results.items()
            ]
        }

    return launch(mgr, "tailor", session_work(engine, do_tailor))


@router.post("/cover-letters", response_model=RunOut, status_code=202)
def launch_cover_letters(
    params: CoverLetterParams,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def do_write(session, reporter):
        results = write_cover_letters(
            session, job_ids=params.job_ids, approved=params.approved, reporter=reporter
        )
        return {
            "coverLetters": [
                {
                    "jobId": r.job_id,
                    "coverLetterId": r.cover_letter_id,
                    "factCheckPassed": r.fact_check_passed,
                }
                for r in results
            ]
        }

    return launch(mgr, "coverLetter", session_work(engine, do_write))
```

`launch_gmail_sync`: keep its custom `work(reporter)` closure (it builds the Gmail service before opening a session); replace the tail with `return launch(mgr, "gmailSync", work, singleton_key="gmailSync")`.

```python
@router.post("/sources/linkedin/scrape", response_model=RunOut, status_code=202)
def launch_linkedin_scrape(
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    """Scrape LinkedIn; the worker opens a visible browser on the server host."""
    if not _linkedin_ready():
        raise ApiException(
            409,
            "LINKEDIN_NOT_CONFIGURED",
            "LinkedIn needs a saved browser profile or configured email and password. "
            "Run `resume-tailor-harness scrape` locally once to create the profile.",
        )
    engine = _engine(request)

    def do_scrape(session, reporter):
        return scrape_linkedin_jobs(session, reporter=reporter)

    return launch(mgr, "linkedinScrape", session_work(engine, do_scrape), singleton_key="linkedinScrape")


@router.post("/jobs/from-url", response_model=RunOut, status_code=202)
def launch_add_from_url(
    params: AddJobUrlParams,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = _engine(request)

    def do_add(session, reporter):
        reporter.begin(1, f"Fetching {params.url}")
        job = add_job_from_url(
            session,
            url=params.url,
            company=params.company,
            title=params.title,
            location=params.location,
            allow_browser=params.allow_browser,
        )
        reporter.step(1)
        return {"jobId": job.id if job else None, "duplicate": job is None}

    return launch(mgr, "addJobUrl", session_work(engine, do_add))
```

Leave `list_runs`, `get_run`, `cancel_run`, `stream_run`, `_owned_record`, `_engine`, `_linkedin_ready` untouched. Update the module docstring's session note to point at `session_work` as the owner of the rule.

- [x] **Step 3: Run the runs and tenancy API tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_runs_launch.py tests/api/test_runs_list.py tests/api/test_runs_sse.py tests/api/test_run_tenancy_quota.py -q`
Expected: PASS unmodified.
Run: `.venv/Scripts/python.exe -m pytest -q && ruff check src/resume_tailor_harness/api/routers/runs.py`
Expected: PASS / clean.

- [x] **Step 4: Commit**

```bash
git add src/resume_tailor_harness/api/routers/runs.py
git commit -m "refactor(api): runs router launches through the shared seam; workspace paths resolve at the leaves"
```

---

### Task 8: Migrate the other five routers to `launch`

**Files:**

- Modify: `src/resume_tailor_harness/api/routers/coach.py:75-97` (its `_submit`)
- Modify: `src/resume_tailor_harness/api/routers/profile.py:149-157, 271-274`
- Modify: `src/resume_tailor_harness/api/routers/sources.py:124-127`
- Modify: `src/resume_tailor_harness/api/routers/match_gap.py:117-120`
- Test: `tests/api/test_coach_router.py`, `tests/api/test_profile_build_run.py`, `tests/api/test_match_gap_refresh.py`, plus whichever files cover sources discovery — all unmodified.

**Interfaces:**

- Consumes: `launch` from Task 6 (exact signature in Task 6's Produces block).
- Produces: no router-level interface changes. Intentional delta: routers that previously called `mgr.submit` bare now surface `RunSingletonConflict`/`RunQuotaError`/`RunResetConflict` as 409/429 envelopes instead of 500s.

- [x] **Step 1: coach.py — reimplement `_submit` as a delegate**

Replace the whole `_submit` function body (keep the name and the three call sites unchanged):

```python
def _submit(manager: RunManager, kind: str, work) -> RunOut:
    return launch(
        manager,
        kind,
        work,
        singleton_key=_SINGLETON,
        singleton_conflict="raise",
        busy_code="COACH_BUSY",
        busy_message="A coach turn is already running",
    )
```

Add `from resume_tailor_harness.api.runs.launch import launch`; delete the now-unused imports (`RunSingletonConflict`, `RunResetConflict`, `RunQuotaError`, `record_to_run` — keep any still used elsewhere in the file; trust ruff).

- [x] **Step 2: profile.py, sources.py, match_gap.py — replace the tails**

In each, add `from resume_tailor_harness.api.runs.launch import launch` and replace the four-line tail pattern:

`profile.py` build endpoint (line ~149):

```python
    return launch(
        mgr,
        "profile-build",
        work,
        singleton_key="profile-build",
        singleton_conflict=singleton_conflict,
    )
```

`profile.py` github-sync endpoint (line ~271):

```python
    return launch(mgr, "github-sync", work, singleton_key="github-sync")
```

`sources.py` (line ~124):

```python
    return launch(mgr, "source-discovery", work, singleton_key="source-discovery")
```

`match_gap.py` (line ~117):

```python
    return launch(mgr, "refreshClusters", work, singleton_key="refreshClusters")
```

`suggestions.py`: leave it **unchanged**. Its submit rides a service seam (`submit_suggestion_run` in `services/suggestion_runs.py` returns a run id), not a bare `mgr.submit`; converting it would mean threading `launch` semantics through that service. Out of scope for this plan.

Delete each file's now-unused `record_to_run` import where the tail was removed (ruff will flag).

- [x] **Step 3: Run the affected API tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/api -q`
Expected: PASS unmodified.
Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: PASS / clean.

- [x] **Step 4: Commit**

```bash
git add src/resume_tailor_harness/api/routers
git commit -m "refactor(api): coach/profile/sources/match_gap routers launch through the shared seam"
```

---

# Phase D — JobDetailRow stops hand-mirroring ShortlistRow

### Task 9: `JobDetailRow` inherits the facet half from `ShortlistRow`

**Files:**

- Modify: `src/resume_tailor_harness/tracking/queries.py:67-105` (the `JobDetailRow` dataclass) and `:247-303` (`job_detail_row`)
- Test: `tests/test_job_detail_row.py`, `tests/api/test_job_detail.py`, `tests/api/test_openapi_contract.py` — all unmodified.

**Interfaces:**

- Consumes: `ShortlistRow` (same module), `_shortlist_row(job, tokens, aliases) -> ShortlistRow`.
- Produces: `JobDetailRow` keeps every attribute it has today (the API projects it with `JobDetail.model_validate(row)` via `from_attributes`), plus the inherited `job_id` and `is_us` (extra attributes; pydantic ignores them). Construction becomes keyword-only.

**Design note:** the wire shape is flat and contract-pinned, so composition-with-flattening at the mapper would move the hand-mapping, not delete it. Inheritance deletes it: the facet fields are declared once in `ShortlistRow`, and `job_detail_row` splats `vars(facets)` instead of copying twenty fields by name.

- [x] **Step 1: Replace the dataclass**

```python
@dataclass(kw_only=True)
class JobDetailRow(ShortlistRow):
    """Flat read-model for one job's detail view.

    Inherits the facet half from ShortlistRow (declared once, projected by
    _shortlist_row) and adds the detail-only columns, named to match the
    JobDetail schema: id, not job_id.
    """

    id: int
    jd_text: str
    status: str
    criteria_json: dict[str, Any] | None
    archived_at: datetime | None
    created_at: datetime
    has_progress: bool
    application: Application | None
    resume_versions: list[ResumeVersion]
    cover_letters: list[CoverLetter]
    best_resume_version_id: int | None = None
    needs_attention: bool = False
    regressed: bool = False
    reject_reason: str | None = None
```

(`source` and `url` disappear from the child — they are inherited, and `_shortlist_row` already fills them from the same `Job` columns.)

- [x] **Step 2: Replace the construction in `job_detail_row`**

```python
def job_detail_row(
    session: Session,
    job_id: int,
    facts: ProfileFacts | None = None,
    aliases_path: str | Path = SKILL_ALIASES_PATH,
) -> JobDetailRow | None:
    """Assemble the full detail read-model for one job."""
    job = session.get(Job, job_id)
    if job is None:
        return None
    tokens = profile_skill_tokens(facts) if facts is not None else set()
    aliases = load_aliases(aliases_path)
    facets = _shortlist_row(job, tokens, aliases)
    jid = _require_job_id(job)
    versions = resume_versions_for_job(session, jid)
    best = pick_best(versions)
    return JobDetailRow(
        **vars(facets),
        id=jid,
        jd_text=clean_job_description_text(job.jd_text),
        status=job.status,
        criteria_json=(
            {key: value for key, value in job.criteria_json.items() if key != "_industry_candidate"}
            if job.criteria_json is not None
            else None
        ),
        archived_at=job.archived_at,
        created_at=job.created_at,
        has_progress=has_progress(session, jid),
        application=application_for_job(session, jid),
        resume_versions=versions,
        cover_letters=cover_letters_for_job(session, jid),
        best_resume_version_id=best.version.id if best.version else None,
        needs_attention=best.no_clean_round,
        regressed=best.regressed,
        reject_reason=job.reject_reason,
    )
```

(Keep the `aliases_path` default as whatever Task 5 set — `SKILL_ALIASES_PATH`. If Phase B was skipped or reordered, keep the current literal; this task does not depend on Phase B.)

- [x] **Step 3: Run the detail tests and the contract gate**

Run: `.venv/Scripts/python.exe -m pytest tests/test_job_detail_row.py tests/test_tracking_queries.py tests/api/test_job_detail.py tests/api/test_openapi_contract.py -q`
Expected: PASS unmodified — the schema and OpenAPI output are untouched because every attribute the schema reads still exists on the row.

- [x] **Step 4: Run the full suite, lint, commit**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check src/resume_tailor_harness/tracking/queries.py`
Expected: PASS / clean.

```bash
git add src/resume_tailor_harness/tracking/queries.py
git commit -m "refactor(tracking): JobDetailRow inherits the facet half from ShortlistRow"
```

---

## Final verification (after all tasks)

- [x] Full suite: `.venv/Scripts/python.exe -m pytest -q` → PASS
- [x] Lint: `ruff check` → clean
- [x] Web unit suite: `npm run test:run --prefix web` → PASS
- [x] Web lint: `npm run lint --prefix web` → clean
- [x] Web production build: `npm run build --prefix web` → PASS
- [x] Browser smoke: start the local API and Vite app with the webapp-testing
      server helper, then use headless Playwright to load the board, exercise a
      representative run-launch action available in the offline fixture state,
      and confirm the rendered response plus a clean browser console. If the
      fixture has no safe launch action, verify board render + `/api/health` and
      record that bounded scope explicitly.
- [x] Contract drift: `git diff --stat contracts/` → empty (no OpenAPI/TS regeneration was needed or performed)
- [x] Patch hygiene: `git diff --check` → clean
- [x] Grep gates:
  - `grep -rn "for board in config.greenhouse.boards" src/resume_tailor_harness/services/sources.py` → no hits
  - `grep -rn "_workspace_args" src/resume_tailor_harness` → no hits
  - `grep -rn "record = mgr.get(run_id)" src/resume_tailor_harness/api/routers | grep -v suggestions` → no hits (suggestions.py keeps its service-seam tail by design)
- [x] Update `CLAUDE.md`: in the Companies-connector section, the sentence "adding an ATS appends one `ConnectorSpec`" now also covers Source Manager CRUD; add one line to the API-layer section naming `api/runs/launch.py` as the launch seam; add one line under Core invariants → Tenancy noting the layout constants in `tenancy/paths.py`. Commit as `docs: record round-3 deepenings in CLAUDE.md`.
