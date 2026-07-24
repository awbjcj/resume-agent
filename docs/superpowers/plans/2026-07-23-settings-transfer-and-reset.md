# Settings Transfer and Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a settings-only export/import bundle and a reset-to-default control for every user-customizable setting, both reading one declared table.

**Architecture:** A new `settings_sections.py` declares the twelve customizable sections once (id, label, canonical relative file paths). `services/settings_bundle.py` reads that table to build and apply a tar.gz containing only those files. A new `api/routers/settings.py` exposes list/export/preview/import/reset. The web app gains a `Settings > Backup` page whose section table is the canonical surface, plus a shared `ResetSectionButton` reused on individual settings pages.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLModel, pytest. React 19, TanStack Query, openapi-fetch, Base UI, Tailwind, Vitest + Testing Library.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-23-settings-transfer-and-reset-design.md`. Read it before starting.
- Backend tests run **offline**: no API key, no network, no live browser. Run with `.venv/Scripts/python.exe -m pytest`.
- Lint with `ruff check`. It must pass before every commit.
- Web tests: `cd web && npm test`. Typecheck: `cd web && npm run typecheck`.
- **Wire format is camelCase.** Every API schema subclasses `CamelModel` from `resume_agent.api.schemas.base`. Python stays snake_case.
- After any API schema or route change, regenerate the contract with `bash scripts/gen_ts_client.sh`. `tests/api/test_openapi_contract.py` is a drift gate and will fail otherwise.
- Errors use the single envelope `{"error": {code, message, details?}}` via `ApiException(status, code, message)` from `resume_agent.api.errors`.
- **The section table is an allowlist.** Never add a denylist, glob-the-whole-directory shortcut, or "copy everything except" logic anywhere in this feature. `secrets.env`, `gmail_token.json`, `resume_agent.db`, and `config/gmail_credentials.json` live alongside the bundled files.
- Never weaken `NON_EDITABLE_KEYS` in `prompts/guidance.py`. `reviewer-fact-check` is an integrity gate.
- Commit after every task. Branch off `dev`, not `main`.

---

## File Structure

**Create:**

| Path | Responsibility |
| --- | --- |
| `src/resume_agent/settings_sections.py` | The twelve-row table, path resolution, `is_customized`, `reset_section` |
| `src/resume_agent/services/settings_bundle.py` | Export, manifest read, strict validation, section-level apply with rollback |
| `src/resume_agent/api/schemas/settings.py` | `CamelModel` DTOs for the five routes |
| `src/resume_agent/api/routers/settings.py` | `router` + `link_router` |
| `tests/test_settings_sections.py` | Registry, customized detection, reset |
| `tests/test_settings_bundle.py` | Round-trip, credential exclusion, strict validation, rollback |
| `tests/api/test_settings_api.py` | Routes, guards, confirm, 409 |
| `web/src/features/settings/use-settings-sections.ts` | Query + mutations |
| `web/src/features/settings/ResetSectionButton.tsx` | Shared confirm-dialog reset control |
| `web/src/features/settings/ResetSectionButton.test.tsx` | Its test |
| `web/src/features/settings/pages/BackupSettingsPage.tsx` | Export, import, section table |
| `web/src/features/settings/pages/BackupSettingsPage.test.tsx` | Its test |

**Modify:**

| Path | Change |
| --- | --- |
| `src/resume_agent/tenancy/workspace.py` | `provision_workspace` seeds from the registry |
| `src/resume_agent/api/app.py` | Register `settings.router` (guarded) and `settings.link_router` (download-guarded) |
| `web/src/features/settings/SettingsLayout.tsx` | Add `Backup` to the `System` nav group |
| `web/src/app/router.tsx` | Add the `backup` route |
| `web/src/features/settings/pages/*.tsx` | Add `ResetSectionButton` to six pages |
| `web/src/features/settings/pages/AgentPromptsPage.tsx` | Per-agent reset |
| `CLAUDE.md` | Document the registry as the single enumeration |

---

### Task 1: The section registry

**Files:**
- Create: `src/resume_agent/settings_sections.py`
- Test: `tests/test_settings_sections.py`

**Interfaces:**
- Consumes: `resume_agent.tenancy.paths.resolve_tenant_path`
- Produces:
  - `SettingsSection` frozen dataclass with `id: str`, `label: str`, `files: tuple[str, ...]`
  - `SETTINGS_SECTIONS: tuple[SettingsSection, ...]` (12 entries)
  - `SECTIONS_BY_ID: dict[str, SettingsSection]`
  - `section_for(section_id: str) -> SettingsSection | None`
  - `live_paths(entry: str) -> list[Path]`
  - `default_path(entry: str) -> Path | None`
  - `arcname_for(entry: str, path: Path) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_sections.py`:

```python
from pathlib import Path

import pytest

from resume_agent.config import Settings
from resume_agent.settings_sections import (
    SECTIONS_BY_ID,
    SETTINGS_SECTIONS,
    arcname_for,
    default_path,
    live_paths,
    section_for,
)
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import WorkspacePaths


def _context(paths: WorkspacePaths) -> UserContext:
    """UserContext has eight required fields and is_admin is a property, not
    one of them. This mirrors the helper in tests/tenancy/test_workspace.py."""
    return UserContext(
        user_id="u1",
        username="u1",
        role="user",
        paths=paths,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )


EXPECTED_IDS = (
    "sources",
    "search",
    "review",
    "agent_guidance",
    "style_guide",
    "render",
    "templates",
    "prune",
    "profile_sources",
    "skill_overrides",
    "skill_groups",
    "taxonomy",
)


def test_registry_declares_twelve_sections_in_order():
    assert tuple(section.id for section in SETTINGS_SECTIONS) == EXPECTED_IDS


def test_registry_never_names_a_credential():
    forbidden = {
        "secrets.env",
        "gmail_token.json",
        "resume_agent.db",
        "config/gmail_credentials.json",
    }
    named = {entry for section in SETTINGS_SECTIONS for entry in section.files}
    assert named.isdisjoint(forbidden)


def test_section_for_returns_none_for_unknown_id():
    assert section_for("nope") is None
    assert section_for("sources") is SECTIONS_BY_ID["sources"]


def test_live_paths_resolves_into_the_active_workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    target = paths.config_dir / "connectors.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("companies: []\n", encoding="utf-8")
    with use_context(_context(paths)):
        assert live_paths("config/connectors.yaml") == [target]


def test_live_paths_is_empty_when_the_file_is_absent(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    with use_context(_context(paths)):
        assert live_paths("config/connectors.yaml") == []


def test_live_paths_expands_a_glob_entry(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    directory = paths.config_dir / "templates"
    directory.mkdir(parents=True)
    (directory / "b.typ").write_text("#b", encoding="utf-8")
    (directory / "a.typ").write_text("#a", encoding="utf-8")
    (directory / "notes.txt").write_text("ignored", encoding="utf-8")
    with use_context(_context(paths)):
        found = live_paths("config/templates/*.typ")
    assert [path.name for path in found] == ["a.typ", "b.typ"]


def test_default_path_finds_the_shipped_example():
    found = default_path("config/connectors.yaml")
    assert found is not None
    assert found.name == "connectors.yaml.example"
    assert found.is_file()


def test_default_path_is_none_for_sections_that_ship_no_example():
    assert default_path("config/agent_guidance.yaml") is None
    assert default_path("data/profile/overrides.yaml") is None
    assert default_path("data/profile/group_corrections.json") is None
    assert default_path("data/taxonomy/taxonomy_corrections.json") is None
    assert default_path("config/templates/*.typ") is None


@pytest.mark.parametrize(
    ("entry", "filename", "expected"),
    [
        ("config/connectors.yaml", "connectors.yaml", "config/connectors.yaml"),
        ("config/templates/*.typ", "mine.typ", "config/templates/mine.typ"),
    ],
)
def test_arcname_for_is_posix_and_glob_aware(entry, filename, expected):
    assert arcname_for(entry, Path("/anywhere") / filename) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_sections.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.settings_sections'`

Note: if `use_context` is not the exported context manager in `tenancy/context.py`, open that file and use whatever the existing tests use (grep `tests/tenancy` for how a `UserContext` is entered) — match it exactly rather than inventing a helper.

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/settings_sections.py`:

```python
"""The single enumeration of user-customizable settings.

Every surface that needs to answer "what can a user customize" reads this
table: the settings bundle (export and import), the reset-to-default controls,
and workspace provisioning. Adding a setting is one row here and it appears in
all three for free.

This table is an ALLOWLIST, and that is load-bearing. It spans the workspace
root, whose other occupants include secrets.env, gmail_token.json,
resume_agent.db, and config/gmail_credentials.json (an OAuth client secret). A
file not named here can never leave a workspace inside a bundle, nor enter one
from an imported bundle.

Paths are written in the canonical relative form tenancy/paths.py already
speaks -- "config/connectors.yaml", "data/profile/overrides.yaml". One string
serves as the live-file key (via resolve_tenant_path), the archive arcname, and
the lookup for a shipped default.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from resume_agent.tenancy.paths import resolve_tenant_path

# src/resume_agent/settings_sections.py -> resume_agent -> src -> repository
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SettingsSection:
    """One resettable, transferable unit of user customization."""

    id: str
    label: str
    files: tuple[str, ...]


SETTINGS_SECTIONS: tuple[SettingsSection, ...] = (
    SettingsSection("sources", "Company sources", ("config/connectors.yaml",)),
    SettingsSection("search", "Search", ("config/search.yaml",)),
    SettingsSection(
        "review",
        "Review panel",
        ("config/review.yaml", "config/review_deep.yaml"),
    ),
    SettingsSection(
        "agent_guidance", "Agent prompts", ("config/agent_guidance.yaml",)
    ),
    SettingsSection("style_guide", "Style guide", ("config/style_guide.md",)),
    SettingsSection("render", "Rendering", ("config/render.yaml",)),
    SettingsSection(
        "templates", "Custom resume templates", ("config/templates/*.typ",)
    ),
    SettingsSection("prune", "Pruning", ("config/prune.yaml",)),
    SettingsSection(
        "profile_sources", "Profile sources", ("config/profile_sources.yaml",)
    ),
    SettingsSection(
        "skill_overrides", "Skill overrides", ("data/profile/overrides.yaml",)
    ),
    SettingsSection(
        "skill_groups",
        "Skill group corrections",
        ("data/profile/group_corrections.json",),
    ),
    SettingsSection(
        "taxonomy",
        "Taxonomy corrections",
        ("data/taxonomy/taxonomy_corrections.json",),
    ),
)

SECTIONS_BY_ID: dict[str, SettingsSection] = {
    section.id: section for section in SETTINGS_SECTIONS
}


def section_for(section_id: str) -> SettingsSection | None:
    return SECTIONS_BY_ID.get(section_id)


def live_paths(entry: str) -> list[Path]:
    """Existing workspace files this entry names, sorted by name."""
    resolved = resolve_tenant_path(entry)
    if "*" in entry:
        return sorted(
            (path for path in resolved.parent.glob(resolved.name) if path.is_file()),
            key=lambda path: path.name,
        )
    return [resolved] if resolved.is_file() else []


def default_path(entry: str) -> Path | None:
    """The shipped `.example` for an entry, when the repository ships one.

    Globs never have a default: a directory of user uploads resets by being
    emptied, not by being repopulated.
    """
    if "*" in entry:
        return None
    candidate = _REPOSITORY_ROOT / f"{entry}.example"
    return candidate if candidate.is_file() else None


def arcname_for(entry: str, path: Path) -> str:
    """Archive member name for a live file matched by `entry`."""
    return str(PurePosixPath(entry).parent / path.name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_sections.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/settings_sections.py tests/test_settings_sections.py
git commit -m "feat: declare the customizable settings surface once"
```

---

### Task 2: Customized detection and reset

**Files:**
- Modify: `src/resume_agent/settings_sections.py` (append)
- Test: `tests/test_settings_sections.py` (append)

**Interfaces:**
- Consumes: `live_paths`, `default_path`, `SettingsSection` from Task 1
- Produces:
  - `is_customized(section: SettingsSection) -> bool`
  - `reset_section(section: SettingsSection) -> None`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings_sections.py`:

```python
from resume_agent.settings_sections import is_customized, reset_section


def _workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    paths.config_dir.mkdir(parents=True)
    return paths, _context(paths)


def test_absent_defaulted_file_is_not_customized(tmp_path):
    _, context = _workspace(tmp_path)
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["sources"]) is False


def test_file_matching_the_example_is_not_customized(tmp_path):
    paths, context = _workspace(tmp_path)
    example = default_path("config/connectors.yaml")
    assert example is not None
    (paths.config_dir / "connectors.yaml").write_bytes(example.read_bytes())
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["sources"]) is False


def test_file_differing_from_the_example_is_customized(tmp_path):
    paths, context = _workspace(tmp_path)
    (paths.config_dir / "connectors.yaml").write_text("companies: []\n", "utf-8")
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["sources"]) is True


def test_section_with_no_example_is_customized_when_the_file_exists(tmp_path):
    paths, context = _workspace(tmp_path)
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["agent_guidance"]) is False
    (paths.config_dir / "agent_guidance.yaml").write_text("writer: hi\n", "utf-8")
    with use_context(context):
        assert is_customized(SECTIONS_BY_ID["agent_guidance"]) is True


def test_reset_restores_the_shipped_example(tmp_path):
    paths, context = _workspace(tmp_path)
    target = paths.config_dir / "connectors.yaml"
    target.write_text("companies: []\n", encoding="utf-8")
    example = default_path("config/connectors.yaml")
    assert example is not None
    with use_context(context):
        reset_section(SECTIONS_BY_ID["sources"])
    assert target.read_bytes() == example.read_bytes()


def test_reset_deletes_when_no_example_ships(tmp_path):
    paths, context = _workspace(tmp_path)
    target = paths.config_dir / "agent_guidance.yaml"
    target.write_text("writer: hi\n", encoding="utf-8")
    with use_context(context):
        reset_section(SECTIONS_BY_ID["agent_guidance"])
    assert not target.exists()


def test_reset_clears_the_templates_directory(tmp_path):
    paths, context = _workspace(tmp_path)
    directory = paths.config_dir / "templates"
    directory.mkdir()
    (directory / "mine.typ").write_text("#mine", encoding="utf-8")
    (directory / "keep.txt").write_text("not a template", encoding="utf-8")
    with use_context(context):
        reset_section(SECTIONS_BY_ID["templates"])
    assert not (directory / "mine.typ").exists()
    assert (directory / "keep.txt").exists()


def test_reset_of_an_absent_section_is_a_noop(tmp_path):
    _, context = _workspace(tmp_path)
    with use_context(context):
        reset_section(SECTIONS_BY_ID["taxonomy"])  # must not raise


def test_every_section_resets_without_error(tmp_path):
    _, context = _workspace(tmp_path)
    with use_context(context):
        for section in SETTINGS_SECTIONS:
            reset_section(section)
            assert is_customized(section) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_sections.py -v -k "customized or reset"`
Expected: FAIL — `ImportError: cannot import name 'is_customized'`

- [ ] **Step 3: Write the implementation**

Append to `src/resume_agent/settings_sections.py`:

```python
def is_customized(section: SettingsSection) -> bool:
    """True when the user has content here they would not want silently lost.

    An absent file that has a shipped default counts as NOT customized: there
    is nothing to lose, and reset would only put the default back. The badge
    answers "do you have changes worth exporting", not "does this byte-match a
    pristine install".
    """
    for entry in section.files:
        default = default_path(entry)
        paths = live_paths(entry)
        if default is None:
            if paths:
                return True
            continue
        if paths and paths[0].read_bytes() != default.read_bytes():
            return True
    return False


def reset_section(section: SettingsSection) -> None:
    """Restore one section to defaults.

    The rule is policy-free and identical to fresh provisioning: copy the
    shipped `.example` when the repository ships one, otherwise delete the
    file. The five sections that ship no example -- agent guidance, custom
    templates, and the three correction ledgers -- all land on their true
    defaults by being removed.
    """
    for entry in section.files:
        for path in live_paths(entry):
            path.unlink(missing_ok=True)
        default = default_path(entry)
        if default is None:
            continue
        target = resolve_tenant_path(entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(default, target)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_sections.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/settings_sections.py tests/test_settings_sections.py
git commit -m "feat: reset one settings section to its shipped default"
```

---

### Task 3: Provisioning seeds from the registry

**Files:**
- Modify: `src/resume_agent/tenancy/workspace.py:92-115`
- Test: `tests/tenancy/test_workspace.py` (append — the file exists and already defines a `_context(tmp_path)` helper at line 13; reuse it)

**Interfaces:**
- Consumes: `SETTINGS_SECTIONS`, `default_path` from Task 1
- Produces: `seedable_entries() -> tuple[str, ...]` in `settings_sections.py`

**Why this is delicate:** `provision_workspace(template_dir=...)` is threaded from `app.state.template_config_dir` through six call sites (`api/app.py:126`, `api/deps.py:168`, `api/routers/admin.py:127`, `api/routers/auth.py:186`, `api/routers/gmail.py:148`, `gmail/scheduler.py:88`), and `tests/api/conftest.py` points it at a temp dir. **The `template_dir` parameter and its semantics must not change.** Only the *list* of files to seed moves into the registry; the *anchor* stays `template_dir`.

- [ ] **Step 1: Write the failing test**

Append to `tests/tenancy/test_workspace.py`:

```python
from resume_agent.settings_sections import seedable_entries
from resume_agent.tenancy.workspace import provision_workspace


def test_seedable_entries_are_config_files_that_ship_an_example():
    entries = seedable_entries()
    assert "config/connectors.yaml" in entries
    assert "config/search.yaml" in entries
    assert "config/agent_guidance.yaml" not in entries
    assert "data/profile/overrides.yaml" not in entries
    assert "config/templates/*.typ" not in entries


def test_provisioning_seeds_every_registry_default(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "connectors.yaml.example").write_text("companies: []\n", "utf-8")
    (templates / "search.yaml.example").write_text("titles: []\n", "utf-8")
    (templates / "unlisted.yaml.example").write_text("nope: true\n", "utf-8")

    paths = provision_workspace(tmp_path / "data", "u1", template_dir=templates)

    assert (paths.config_dir / "connectors.yaml").read_text("utf-8") == "companies: []\n"
    assert (paths.config_dir / "search.yaml").read_text("utf-8") == "titles: []\n"
    # Not in the registry, so provisioning no longer copies it.
    assert not (paths.config_dir / "unlisted.yaml").exists()


def test_provisioning_never_overwrites_an_existing_file(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "search.yaml.example").write_text("titles: []\n", "utf-8")
    paths = provision_workspace(tmp_path / "data", "u1", template_dir=templates)
    (paths.config_dir / "search.yaml").write_text("titles: [dev]\n", "utf-8")

    provision_workspace(tmp_path / "data", "u1", template_dir=templates)

    assert (paths.config_dir / "search.yaml").read_text("utf-8") == "titles: [dev]\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_workspace.py -v`
Expected: FAIL — `ImportError: cannot import name 'seedable_entries'`

- [ ] **Step 3: Add `seedable_entries` to the registry**

Append to `src/resume_agent/settings_sections.py`:

```python
def seedable_entries() -> tuple[str, ...]:
    """Entries a fresh workspace is provisioned with.

    Exactly the entries that ship a `.example`. Provisioning and resetting
    therefore cannot drift: both mean "put the shipped default here".
    """
    return tuple(
        entry
        for section in SETTINGS_SECTIONS
        for entry in section.files
        if default_path(entry) is not None
    )
```

- [ ] **Step 4: Rewrite the seeding loop**

In `src/resume_agent/tenancy/workspace.py`, add the import at the top:

```python
from resume_agent.settings_sections import seedable_entries
```

Replace the seeding block (currently the `templates.glob("*.example")` loop at the end of `provision_workspace`) with:

```python
    templates = Path(template_dir)
    if templates.is_dir():
        for entry in seedable_entries():
            name = PurePosixPath(entry).name
            example = templates / f"{name}.example"
            target = paths.config_dir / name
            if example.is_file() and not target.exists():
                shutil.copyfile(example, target)
    return paths
```

Add `PurePosixPath` to the existing `from pathlib import Path` import:

```python
from pathlib import Path, PurePosixPath
```

- [ ] **Step 5: Run the full tenancy and API suites**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy tests/api -q`
Expected: PASS. If anything fails, a caller depended on an `.example` that is not in the registry — add it as a section rather than restoring the glob.

- [ ] **Step 6: Lint and commit**

```bash
ruff check
git add src/resume_agent/settings_sections.py src/resume_agent/tenancy/workspace.py tests/tenancy/test_workspace.py
git commit -m "refactor: provision workspaces from the settings registry"
```

---

### Task 4: Bundle export

**Files:**
- Create: `src/resume_agent/services/settings_bundle.py`
- Test: `tests/test_settings_bundle.py`

**Interfaces:**
- Consumes: `SETTINGS_SECTIONS`, `live_paths`, `arcname_for` from Task 1
- Produces:
  - `BUNDLE_VERSION: int = 1`
  - `MANIFEST_NAME: str = "manifest.json"`
  - `InvalidBundleError(ValueError)`
  - `UnsupportedBundleVersionError(InvalidBundleError)`
  - `export_settings_bundle(out_dir: Path) -> Path`

- [ ] **Step 1: Write the failing test**

Create `tests/test_settings_bundle.py`:

```python
import io
import json
import tarfile
from pathlib import Path

from resume_agent.config import Settings
from resume_agent.services.settings_bundle import (
    BUNDLE_VERSION,
    MANIFEST_NAME,
    export_settings_bundle,
)
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import WorkspacePaths


def workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "u1")
    paths.config_dir.mkdir(parents=True)
    context = UserContext(
        user_id="u1",
        username="u1",
        role="user",
        paths=paths,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )
    return paths, context


def members(archive: Path) -> set[str]:
    with tarfile.open(archive, "r:gz") as tar:
        return {member.name for member in tar.getmembers() if member.isfile()}


def manifest(archive: Path) -> dict:
    with tarfile.open(archive, "r:gz") as tar:
        handle = tar.extractfile(MANIFEST_NAME)
        assert handle is not None
        return json.loads(handle.read().decode("utf-8"))


def test_export_contains_only_populated_sections(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.config_dir / "connectors.yaml").write_text("companies: []\n", "utf-8")
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")

    assert members(archive) == {MANIFEST_NAME, "config/connectors.yaml"}
    parsed = manifest(archive)
    assert parsed["version"] == BUNDLE_VERSION
    assert parsed["sections"] == ["sources"]
    assert parsed["exportedAt"]


def test_export_carries_the_correction_ledgers(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.root / "profile").mkdir(parents=True)
    (paths.root / "taxonomy").mkdir(parents=True)
    (paths.root / "profile" / "overrides.yaml").write_text("ban: [x]\n", "utf-8")
    (paths.root / "profile" / "group_corrections.json").write_text(
        '{"corrections": {}}', "utf-8"
    )
    (paths.root / "taxonomy" / "taxonomy_corrections.json").write_text(
        '{"aliases": {}}', "utf-8"
    )
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")

    assert "data/profile/overrides.yaml" in members(archive)
    assert "data/profile/group_corrections.json" in members(archive)
    assert "data/taxonomy/taxonomy_corrections.json" in members(archive)
    assert set(manifest(archive)["sections"]) == {
        "skill_overrides",
        "skill_groups",
        "taxonomy",
    }


def test_export_never_carries_a_credential(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.config_dir / "connectors.yaml").write_text("companies: []\n", "utf-8")
    (paths.config_dir / "gmail_credentials.json").write_text('{"web":{}}', "utf-8")
    paths.secrets_env.write_text("ANTHROPIC_API_KEY=sk-secret\n", encoding="utf-8")
    paths.gmail_token.write_text('{"token": "secret"}', encoding="utf-8")
    paths.db_file.write_bytes(b"SQLite format 3\x00")
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")

    found = members(archive)
    assert found == {MANIFEST_NAME, "config/connectors.yaml"}
    blob = Path(archive).read_bytes()
    assert b"sk-secret" not in blob


def test_export_of_an_untouched_workspace_lists_no_sections(tmp_path):
    _, context = workspace(tmp_path)
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")
    assert manifest(archive)["sections"] == []
    assert members(archive) == {MANIFEST_NAME}


def test_export_names_glob_members_by_their_real_filename(tmp_path):
    paths, context = workspace(tmp_path)
    directory = paths.config_dir / "templates"
    directory.mkdir()
    (directory / "mine.typ").write_text("#mine", encoding="utf-8")
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")
    assert "config/templates/mine.typ" in members(archive)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_bundle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.services.settings_bundle'`

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/services/settings_bundle.py`:

```python
"""Settings-only bundle: export, preview, and section-level import.

A bundle carries exactly the sections declared in settings_sections.py --
never the database, the derived profile corpus, or any credential. Import
replaces the sections a bundle names and leaves every other section untouched,
so a bundle can add or replace settings but never clear them. Clearing is what
reset is for.
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from resume_agent.settings_sections import (
    SETTINGS_SECTIONS,
    arcname_for,
    live_paths,
)

BUNDLE_VERSION = 1
MANIFEST_NAME = "manifest.json"


class InvalidBundleError(ValueError):
    """The upload is not a readable settings bundle."""


class UnsupportedBundleVersionError(InvalidBundleError):
    """The bundle was written by a version this build does not understand."""


def export_settings_bundle(out_dir: Path) -> Path:
    """Write a tar.gz of every populated section into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    archive = out_dir / f"resume-agent-settings-{stamp.date().isoformat()}.tar.gz"

    sections: list[str] = []
    members: list[tuple[str, Path]] = []
    for section in SETTINGS_SECTIONS:
        found = [
            (arcname_for(entry, path), path)
            for entry in section.files
            for path in live_paths(entry)
        ]
        if found:
            sections.append(section.id)
            members.extend(found)

    manifest = json.dumps(
        {
            "version": BUNDLE_VERSION,
            "exportedAt": stamp.isoformat(),
            "sections": sections,
        },
        indent=2,
    ).encode("utf-8")

    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(manifest)
        info.mtime = int(stamp.timestamp())
        tar.addfile(info, io.BytesIO(manifest))
        for arcname, path in members:
            tar.add(path, arcname=arcname)
    return archive
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_bundle.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/services/settings_bundle.py tests/test_settings_bundle.py
git commit -m "feat: export a settings-only bundle"
```

---

### Task 5: Manifest reading and strict validation

**Files:**
- Modify: `src/resume_agent/services/settings_bundle.py` (append)
- Test: `tests/test_settings_bundle.py` (append)

**Interfaces:**
- Consumes: `_extract_validated`, `UnsafeArchiveError` from `resume_agent.services.backup`; `SECTIONS_BY_ID`, `live_paths` from Task 1
- Produces:
  - `BundleManifest` frozen dataclass: `version: int`, `exported_at: str`, `sections: tuple[str, ...]`, `unknown_sections: tuple[str, ...]`
  - `read_bundle_manifest(archive: Path) -> BundleManifest`
  - `validate_member(arcname: str, path: Path) -> None`

**Critical context:** the read-time ledger loaders are deliberately tolerant and **must not** be used for validation. `load_group_corrections` catches `(OSError, ValueError)` and `load_taxonomy_corrections` catches `(OSError, UnicodeError, json.JSONDecodeError)`, both returning an *empty* ledger. Using them here would let a truncated bundle validate clean and then silently replace real corrections with nothing. Validate against the **models** with errors propagating.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings_bundle.py`:

```python
import pytest

from resume_agent.services.settings_bundle import (
    InvalidBundleError,
    UnsupportedBundleVersionError,
    read_bundle_manifest,
    validate_member,
)


def write_bundle(tmp_path: Path, manifest_body: object, files: dict[str, str]) -> Path:
    archive = tmp_path / "bundle.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        if manifest_body is not None:
            blob = json.dumps(manifest_body).encode("utf-8")
            info = tarfile.TarInfo(MANIFEST_NAME)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
        for name, text in files.items():
            blob = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
    return archive


def test_read_manifest_separates_known_from_unknown_sections(tmp_path):
    archive = write_bundle(
        tmp_path,
        {
            "version": 1,
            "exportedAt": "2026-07-23T00:00:00+00:00",
            "sections": ["sources", "from_the_future"],
        },
        {"config/connectors.yaml": "companies: []\n"},
    )
    parsed = read_bundle_manifest(archive)
    assert parsed.sections == ("sources",)
    assert parsed.unknown_sections == ("from_the_future",)


def test_read_manifest_rejects_a_missing_manifest(tmp_path):
    archive = write_bundle(tmp_path, None, {"config/connectors.yaml": "x: 1\n"})
    with pytest.raises(InvalidBundleError):
        read_bundle_manifest(archive)


def test_read_manifest_rejects_an_unknown_version(tmp_path):
    archive = write_bundle(
        tmp_path, {"version": 99, "exportedAt": "", "sections": []}, {}
    )
    with pytest.raises(UnsupportedBundleVersionError):
        read_bundle_manifest(archive)


def test_read_manifest_rejects_a_non_tar_upload(tmp_path):
    archive = tmp_path / "not-a-bundle.tar.gz"
    archive.write_bytes(b"this is not gzip")
    with pytest.raises(InvalidBundleError):
        read_bundle_manifest(archive)


@pytest.mark.parametrize(
    ("arcname", "body"),
    [
        ("config/connectors.yaml", "companies: [\n"),
        ("config/search.yaml", ": : :\n"),
        ("data/profile/overrides.yaml", "ban: {oops\n"),
        ("data/profile/group_corrections.json", "{not json"),
        ("data/taxonomy/taxonomy_corrections.json", "{not json"),
    ],
)
def test_validate_member_rejects_corruption(tmp_path, arcname, body):
    staged = tmp_path / "staged"
    staged.write_text(body, encoding="utf-8")
    with pytest.raises(InvalidBundleError):
        validate_member(arcname, staged)


def test_validate_member_rejects_a_traversing_template_stem(tmp_path):
    staged = tmp_path / "staged.typ"
    staged.write_text("#let x = 1", encoding="utf-8")
    with pytest.raises(InvalidBundleError):
        validate_member("config/templates/../evil.typ", staged)


def test_validate_member_accepts_a_ledger_naming_unknown_clusters(tmp_path):
    staged = tmp_path / "staged.json"
    staged.write_text(
        json.dumps({"domain_renames": {"cluster-i-do-not-have": "whatever"}}),
        encoding="utf-8",
    )
    validate_member("data/taxonomy/taxonomy_corrections.json", staged)


def test_validate_member_accepts_valid_documents(tmp_path):
    staged = tmp_path / "staged.yaml"
    staged.write_text("titles: [engineer]\n", encoding="utf-8")
    validate_member("config/search.yaml", staged)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_bundle.py -v -k "manifest or validate_member"`
Expected: FAIL — `ImportError: cannot import name 'read_bundle_manifest'`

- [ ] **Step 3: Write the implementation**

Append to `src/resume_agent/services/settings_bundle.py`. Add these imports at the top of the file:

```python
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

import yaml

from resume_agent.api.schemas.config import (
    ProfileConfigDoc,
    PruneConfigDoc,
    RenderConfigDoc,
    ReviewConfigDoc,
    SearchConfigDoc,
)
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.profile.group_corrections import GroupCorrections
from resume_agent.profile.matrix import load_overrides
from resume_agent.prompts.guidance import MAX_GUIDANCE_CHARS
from resume_agent.render.templates import validate_custom_stem
from resume_agent.services.backup import UnsafeArchiveError, _extract_validated
from resume_agent.settings_sections import SECTIONS_BY_ID
from resume_agent.taxonomy.corrections import TaxonomyCorrections
```

Then append:

```python
@dataclass(frozen=True)
class BundleManifest:
    version: int
    exported_at: str
    sections: tuple[str, ...]
    unknown_sections: tuple[str, ...]


def _yaml_doc(model: type) -> Callable[[Path], None]:
    def check(path: Path) -> None:
        model.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    return check


def _check_guidance(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("agent guidance must be a mapping")
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("agent guidance entries must be strings")
        if len(value.strip()) > MAX_GUIDANCE_CHARS:
            raise ValueError(f"guidance for {key!r} exceeds {MAX_GUIDANCE_CHARS}")


def _check_text(path: Path) -> None:
    path.read_text(encoding="utf-8")


def _check_group_corrections(path: Path) -> None:
    # NOT load_group_corrections: it swallows ValueError and returns an empty
    # ledger, which would let a truncated file import as "no corrections".
    GroupCorrections.model_validate_json(path.read_text(encoding="utf-8"))


def _check_taxonomy_corrections(path: Path) -> None:
    # NOT load_taxonomy_corrections, for the same reason. Semantic
    # unfamiliarity is fine -- dangling references are inert by design and are
    # dropped at read time by sanitize_taxonomy_corrections.
    TaxonomyCorrections.model_validate(json.loads(path.read_text(encoding="utf-8")))


_VALIDATORS: dict[str, Callable[[Path], None]] = {
    "config/connectors.yaml": _yaml_doc(ConnectorsConfig),
    "config/search.yaml": _yaml_doc(SearchConfigDoc),
    "config/review.yaml": _yaml_doc(ReviewConfigDoc),
    "config/review_deep.yaml": _yaml_doc(ReviewConfigDoc),
    "config/render.yaml": _yaml_doc(RenderConfigDoc),
    "config/prune.yaml": _yaml_doc(PruneConfigDoc),
    "config/profile_sources.yaml": _yaml_doc(ProfileConfigDoc),
    "config/agent_guidance.yaml": _check_guidance,
    "config/style_guide.md": _check_text,
    "data/profile/overrides.yaml": lambda path: load_overrides(path),
    "data/profile/group_corrections.json": _check_group_corrections,
    "data/taxonomy/taxonomy_corrections.json": _check_taxonomy_corrections,
}


def validate_member(arcname: str, path: Path) -> None:
    """Parse a staged member strictly; raise InvalidBundleError on corruption."""
    try:
        if arcname.startswith("config/templates/"):
            validate_custom_stem(Path(arcname).stem)
            _check_text(path)
            return
        checker = _VALIDATORS.get(arcname)
        if checker is None:
            return
        checker(path)
    except InvalidBundleError:
        raise
    except Exception as error:
        raise InvalidBundleError(f"{arcname} is not valid: {error}") from error


def read_bundle_manifest(archive: Path) -> BundleManifest:
    """Extract only the manifest, so a preview never touches live files."""
    with tempfile.TemporaryDirectory(prefix="ra-settings-preview-") as temporary:
        stage = Path(temporary)
        try:
            _extract_validated(archive, stage)
        except UnsafeArchiveError:
            raise
        except Exception as error:
            raise InvalidBundleError("upload is not a readable bundle") from error
        return _manifest_from_stage(stage)


def _manifest_from_stage(stage: Path) -> BundleManifest:
    source = stage / MANIFEST_NAME
    if not source.is_file():
        raise InvalidBundleError("bundle is missing manifest.json")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InvalidBundleError("manifest.json is not readable JSON") from error
    if not isinstance(data, dict):
        raise InvalidBundleError("manifest.json must be an object")
    if data.get("version") != BUNDLE_VERSION:
        raise UnsupportedBundleVersionError(
            f"bundle version {data.get('version')!r} is not supported"
        )
    raw = data.get("sections")
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise InvalidBundleError("manifest sections must be a list of strings")
    known = tuple(item for item in raw if item in SECTIONS_BY_ID)
    unknown = tuple(item for item in raw if item not in SECTIONS_BY_ID)
    exported = data.get("exportedAt")
    return BundleManifest(
        version=BUNDLE_VERSION,
        exported_at=exported if isinstance(exported, str) else "",
        sections=known,
        unknown_sections=unknown,
    )
```

Note on `_extract_validated`: it is a private helper in `services/backup.py`. Importing it across modules is intentional — it is the project's one hardened tar extractor, and duplicating it would mean two places to fix tar bugs. Do not copy it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_bundle.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/services/settings_bundle.py tests/test_settings_bundle.py
git commit -m "feat: read and strictly validate a settings bundle"
```

---

### Task 6: Bundle import with rollback

**Files:**
- Modify: `src/resume_agent/services/settings_bundle.py` (append)
- Test: `tests/test_settings_bundle.py` (append)

**Interfaces:**
- Consumes: `read_bundle_manifest`, `validate_member`, `_manifest_from_stage` from Task 5
- Produces: `import_settings_bundle(archive: Path) -> tuple[str, ...]` returning applied section ids

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings_bundle.py`:

```python
from resume_agent.services.settings_bundle import import_settings_bundle


def test_import_replaces_named_sections_and_leaves_the_rest(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.config_dir / "connectors.yaml").write_text("companies: [old]\n", "utf-8")
    (paths.config_dir / "search.yaml").write_text("titles: [mine]\n", "utf-8")
    archive = write_bundle(
        tmp_path,
        {"version": 1, "exportedAt": "", "sections": ["sources"]},
        {"config/connectors.yaml": "companies: []\n"},
    )

    with use_context(context):
        applied = import_settings_bundle(archive)

    assert applied == ("sources",)
    assert (paths.config_dir / "connectors.yaml").read_text("utf-8") == "companies: []\n"
    assert (paths.config_dir / "search.yaml").read_text("utf-8") == "titles: [mine]\n"


def test_import_round_trips_an_export(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.root / "profile").mkdir(parents=True)
    (paths.config_dir / "connectors.yaml").write_text("companies: []\n", "utf-8")
    (paths.root / "profile" / "overrides.yaml").write_text("ban: [x]\n", "utf-8")
    with use_context(context):
        archive = export_settings_bundle(tmp_path / "out")

    (paths.config_dir / "connectors.yaml").write_text("companies: [drift]\n", "utf-8")
    (paths.root / "profile" / "overrides.yaml").write_text("ban: [y]\n", "utf-8")

    with use_context(context):
        import_settings_bundle(archive)

    assert (paths.config_dir / "connectors.yaml").read_text("utf-8") == "companies: []\n"
    assert (paths.root / "profile" / "overrides.yaml").read_text("utf-8") == "ban: [x]\n"


def test_import_ignores_a_credential_hidden_in_the_bundle(tmp_path):
    paths, context = workspace(tmp_path)
    archive = write_bundle(
        tmp_path,
        {"version": 1, "exportedAt": "", "sections": ["sources"]},
        {
            "config/connectors.yaml": "companies: []\n",
            "config/gmail_credentials.json": '{"web": {"client_secret": "stolen"}}',
            "secrets.env": "ANTHROPIC_API_KEY=sk-evil\n",
        },
    )

    with use_context(context):
        import_settings_bundle(archive)

    assert not (paths.config_dir / "gmail_credentials.json").exists()
    assert not paths.secrets_env.exists()


def test_import_ignores_files_a_section_does_not_claim(tmp_path):
    paths, context = workspace(tmp_path)
    archive = write_bundle(
        tmp_path,
        {"version": 1, "exportedAt": "", "sections": ["sources"]},
        {
            "config/connectors.yaml": "companies: []\n",
            "config/search.yaml": "titles: [smuggled]\n",
        },
    )

    with use_context(context):
        import_settings_bundle(archive)

    assert not (paths.config_dir / "search.yaml").exists()


def test_a_corrupt_ledger_leaves_every_live_file_byte_identical(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.root / "profile").mkdir(parents=True)
    original_groups = '{"corrections": {"python": {"group": "languages"}}}'
    (paths.root / "profile" / "group_corrections.json").write_text(
        original_groups, "utf-8"
    )
    (paths.config_dir / "connectors.yaml").write_text("companies: [keep]\n", "utf-8")
    archive = write_bundle(
        tmp_path,
        {"version": 1, "exportedAt": "", "sections": ["sources", "skill_groups"]},
        {
            "config/connectors.yaml": "companies: [new]\n",
            "data/profile/group_corrections.json": "{truncated",
        },
    )

    with use_context(context), pytest.raises(InvalidBundleError):
        import_settings_bundle(archive)

    assert (
        paths.root / "profile" / "group_corrections.json"
    ).read_text("utf-8") == original_groups
    assert (paths.config_dir / "connectors.yaml").read_text("utf-8") == "companies: [keep]\n"


def test_import_replaces_the_whole_templates_set(tmp_path):
    paths, context = workspace(tmp_path)
    directory = paths.config_dir / "templates"
    directory.mkdir()
    (directory / "old.typ").write_text("#old", encoding="utf-8")
    archive = write_bundle(
        tmp_path,
        {"version": 1, "exportedAt": "", "sections": ["templates"]},
        {"config/templates/new.typ": "#new"},
    )

    with use_context(context):
        import_settings_bundle(archive)

    assert not (directory / "old.typ").exists()
    assert (directory / "new.typ").read_text("utf-8") == "#new"


def test_a_section_claiming_no_files_is_skipped_not_cleared(tmp_path):
    paths, context = workspace(tmp_path)
    (paths.config_dir / "connectors.yaml").write_text("companies: [keep]\n", "utf-8")
    archive = write_bundle(
        tmp_path,
        {"version": 1, "exportedAt": "", "sections": ["sources"]},
        {"config/unrelated.yaml": "nothing: true\n"},
    )

    with use_context(context):
        applied = import_settings_bundle(archive)

    assert applied == ()
    assert (paths.config_dir / "connectors.yaml").read_text("utf-8") == "companies: [keep]\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_bundle.py -v -k import_`
Expected: FAIL — `ImportError: cannot import name 'import_settings_bundle'`

- [ ] **Step 3: Write the implementation**

Append to `src/resume_agent/services/settings_bundle.py`. `live_paths` is already imported by Task 4; add only these two:

```python
import shutil

from resume_agent.tenancy.paths import resolve_tenant_path
```

Then append:

```python
def _claim(stage: Path, section_ids: tuple[str, ...]) -> dict[str, list[tuple[str, Path]]]:
    """Map each section to the staged files it actually owns.

    Anything the allowlist does not claim is dropped here -- a crafted bundle
    cannot plant a credential, and a bundle from a newer build stays importable.
    """
    claimed: dict[str, list[tuple[str, Path]]] = {}
    for section_id in section_ids:
        section = SECTIONS_BY_ID[section_id]
        found: list[tuple[str, Path]] = []
        for entry in section.files:
            if "*" in entry:
                parent = stage / PurePosixPath(entry).parent
                pattern = PurePosixPath(entry).name
                if parent.is_dir():
                    for path in sorted(parent.glob(pattern)):
                        if path.is_file():
                            found.append((f"{PurePosixPath(entry).parent}/{path.name}", path))
                continue
            staged = stage / entry
            if staged.is_file():
                found.append((entry, staged))
        if found:
            claimed[section_id] = found
    return claimed


def import_settings_bundle(archive: Path) -> tuple[str, ...]:
    """Replace the sections a bundle names; leave every other section alone."""
    with tempfile.TemporaryDirectory(prefix="ra-settings-import-") as temporary:
        stage = Path(temporary) / "stage"
        try:
            _extract_validated(archive, stage)
        except UnsafeArchiveError:
            raise
        except Exception as error:
            raise InvalidBundleError("upload is not a readable bundle") from error

        manifest = _manifest_from_stage(stage)
        claimed = _claim(stage, manifest.sections)

        for members in claimed.values():
            for arcname, path in members:
                validate_member(arcname, path)

        return _apply(claimed)


def _apply(claimed: dict[str, list[tuple[str, Path]]]) -> tuple[str, ...]:
    """Stash, write, and roll back on any failure."""
    rollback = Path(tempfile.mkdtemp(prefix="ra-settings-rollback-"))
    stashed: list[tuple[Path, Path]] = []
    written: list[Path] = []
    try:
        for section_id in claimed:
            for entry in SECTIONS_BY_ID[section_id].files:
                for live in live_paths(entry):
                    stash = rollback / f"{len(stashed)}-{live.name}"
                    shutil.move(live, stash)
                    stashed.append((live, stash))
        for members in claimed.values():
            for arcname, staged in members:
                target = resolve_tenant_path(arcname)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(staged, target)
                written.append(target)
    except BaseException:
        for target in written:
            target.unlink(missing_ok=True)
        for live, stash in stashed:
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(stash, live)
        raise
    finally:
        shutil.rmtree(rollback, ignore_errors=True)
    return tuple(claimed)
```

Add `PurePosixPath` to the `pathlib` import at the top of the file:

```python
from pathlib import Path, PurePosixPath
```

- [ ] **Step 4: Run the whole bundle suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_settings_bundle.py -v`
Expected: PASS, 25 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check
git add src/resume_agent/services/settings_bundle.py tests/test_settings_bundle.py
git commit -m "feat: apply a settings bundle section by section with rollback"
```

---

### Task 7: API schemas, routes, and contract

**Files:**
- Create: `src/resume_agent/api/schemas/settings.py`
- Create: `src/resume_agent/api/routers/settings.py`
- Modify: `src/resume_agent/api/app.py`
- Test: `tests/api/test_settings_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6
- Produces: five routes; `SettingsSectionOut`, `SettingsSectionList`, `BundlePreview`, `BundleApplied`

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_settings_api.py`:

```python
import io
import json
import tarfile


def _login(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "owner-password"},
    )
    assert response.status_code == 200


def _bundle(sections: list[str], files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        blob = json.dumps(
            {"version": 1, "exportedAt": "", "sections": sections}
        ).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(blob)
        tar.addfile(info, io.BytesIO(blob))
        for name, text in files.items():
            payload = text.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


def test_sections_lists_every_section(mu_client):
    _login(mu_client)
    response = mu_client.get("/api/settings/sections")
    assert response.status_code == 200
    body = response.json()
    ids = [section["id"] for section in body["sections"]]
    assert len(ids) == 12
    assert "sources" in ids
    assert all("customized" in section for section in body["sections"])


def test_sections_requires_authentication(mu_client):
    assert mu_client.get("/api/settings/sections").status_code == 401


def test_export_returns_a_gzip_archive(mu_client):
    _login(mu_client)
    response = mu_client.get("/api/settings/bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"


def test_preview_reports_sections_without_writing(mu_client):
    _login(mu_client)
    response = mu_client.post(
        "/api/settings/bundle/preview",
        files={"file": ("b.tar.gz", _bundle(["sources"], {
            "config/connectors.yaml": "companies: []\n"
        }), "application/gzip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert [section["id"] for section in body["sections"]] == ["sources"]
    assert body["unknownSections"] == []


def test_import_requires_the_confirm_token(mu_client):
    _login(mu_client)
    response = mu_client.post(
        "/api/settings/bundle",
        files={"file": ("b.tar.gz", _bundle([], {}), "application/gzip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_import_applies_the_bundle(mu_client):
    _login(mu_client)
    response = mu_client.post(
        "/api/settings/bundle?confirm=APPLY",
        files={"file": ("b.tar.gz", _bundle(["sources"], {
            "config/connectors.yaml": "companies: []\n"
        }), "application/gzip")},
    )
    assert response.status_code == 200
    assert response.json()["applied"] == ["sources"]


def test_import_rejects_a_corrupt_bundle(mu_client):
    _login(mu_client)
    response = mu_client.post(
        "/api/settings/bundle?confirm=APPLY",
        files={"file": ("b.tar.gz", b"not gzip", "application/gzip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_BUNDLE"


def test_reset_of_an_unknown_section_is_404(mu_client):
    _login(mu_client)
    response = mu_client.post("/api/settings/sections/nope/reset")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_reset_returns_the_section_uncustomized(mu_client):
    _login(mu_client)
    mu_client.post(
        "/api/settings/bundle?confirm=APPLY",
        files={"file": ("b.tar.gz", _bundle(["sources"], {
            "config/connectors.yaml": "companies: [mine]\n"
        }), "application/gzip")},
    )
    response = mu_client.post("/api/settings/sections/sources/reset")
    assert response.status_code == 200
    assert response.json() == {
        "id": "sources",
        "label": "Company sources",
        "customized": False,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_settings_api.py -v`
Expected: FAIL — all 404, routes do not exist

- [ ] **Step 3: Write the schemas**

Create `src/resume_agent/api/schemas/settings.py`:

```python
"""Wire DTOs for the settings bundle and reset controls."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class SettingsSectionOut(CamelModel):
    id: str
    label: str
    customized: bool


class SettingsSectionList(CamelModel):
    sections: list[SettingsSectionOut]


class BundlePreview(CamelModel):
    version: int
    exported_at: str
    sections: list[SettingsSectionOut]
    unknown_sections: list[str]


class BundleApplied(CamelModel):
    applied: list[str]
```

- [ ] **Step 4: Write the router**

Create `src/resume_agent/api/routers/settings.py`:

```python
"""Settings transfer and reset. Storage lives behind settings_sections."""

from __future__ import annotations

import shutil
import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.settings import (
    BundleApplied,
    BundlePreview,
    SettingsSectionList,
    SettingsSectionOut,
)
from resume_agent.api.uploads import UploadTooLargeError, copy_upload
from resume_agent.services.backup import UnsafeArchiveError
from resume_agent.services.settings_bundle import (
    InvalidBundleError,
    UnsupportedBundleVersionError,
    export_settings_bundle,
    import_settings_bundle,
    read_bundle_manifest,
)
from resume_agent.settings_sections import (
    SECTIONS_BY_ID,
    SETTINGS_SECTIONS,
    SettingsSection,
    is_customized,
    reset_section,
    section_for,
)
from resume_agent.tenancy.context import current_context

router = APIRouter(prefix="/settings", tags=["settings"])
link_router = APIRouter(prefix="/settings", tags=["settings"])

_MAX_BUNDLE_BYTES = 8 * 1024 * 1024


def _out(section: SettingsSection) -> SettingsSectionOut:
    return SettingsSectionOut(
        id=section.id, label=section.label, customized=is_customized(section)
    )


def _staged_upload(file: UploadFile, temporary: str) -> Path:
    archive = Path(temporary) / "bundle.tar.gz"
    try:
        copy_upload(file, archive, max_bytes=_MAX_BUNDLE_BYTES)
    except UploadTooLargeError as exc:
        raise ApiException(413, "UPLOAD_TOO_LARGE", str(exc)) from exc
    return archive


def _bundle_error(exc: Exception) -> ApiException:
    if isinstance(exc, UnsupportedBundleVersionError):
        return ApiException(400, "UNSUPPORTED_VERSION", str(exc))
    if isinstance(exc, UnsafeArchiveError):
        return ApiException(400, "UNSAFE_ARCHIVE", str(exc))
    return ApiException(400, "INVALID_BUNDLE", str(exc))


@router.get("/sections", response_model=SettingsSectionList)
def list_sections() -> SettingsSectionList:
    return SettingsSectionList(sections=[_out(s) for s in SETTINGS_SECTIONS])


@link_router.get("/bundle")
def export_bundle() -> FileResponse:
    temporary = Path(tempfile.mkdtemp(prefix="ra-settings-export-"))
    try:
        archive = export_settings_bundle(temporary)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return FileResponse(
        archive,
        media_type="application/gzip",
        filename=f"resume-agent-settings-{date.today().isoformat()}.tar.gz",
        background=BackgroundTask(shutil.rmtree, temporary, ignore_errors=True),
    )


@router.post("/bundle/preview", response_model=BundlePreview)
def preview_bundle(file: UploadFile) -> BundlePreview:
    with tempfile.TemporaryDirectory(prefix="ra-settings-preview-") as temporary:
        archive = _staged_upload(file, temporary)
        try:
            manifest = read_bundle_manifest(archive)
        except (InvalidBundleError, UnsafeArchiveError) as exc:
            raise _bundle_error(exc) from exc
    return BundlePreview(
        version=manifest.version,
        exported_at=manifest.exported_at,
        sections=[_out(SECTIONS_BY_ID[i]) for i in manifest.sections],
        unknown_sections=list(manifest.unknown_sections),
    )


@router.post("/bundle", response_model=BundleApplied)
def apply_bundle(
    request: Request, file: UploadFile, confirm: str = ""
) -> BundleApplied:
    if confirm != "APPLY":
        raise ApiException(
            400,
            "CONFIRM_REQUIRED",
            "Importing replaces the settings a bundle names; pass ?confirm=APPLY",
        )
    context = current_context()
    user_id = context.user_id if context is not None else None
    if request.app.state.run_manager.list_active(user_id=user_id):
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while your runs are active")
    with tempfile.TemporaryDirectory(prefix="ra-settings-import-") as temporary:
        archive = _staged_upload(file, temporary)
        try:
            applied = import_settings_bundle(archive)
        except (InvalidBundleError, UnsafeArchiveError) as exc:
            raise _bundle_error(exc) from exc
    return BundleApplied(applied=list(applied))


@router.post("/sections/{section_id}/reset", response_model=SettingsSectionOut)
def reset(section_id: str) -> SettingsSectionOut:
    section = section_for(section_id)
    if section is None:
        raise ApiException(404, "NOT_FOUND", f"No settings section {section_id!r}")
    reset_section(section)
    return _out(section)
```

- [ ] **Step 5: Register the routers**

In `src/resume_agent/api/app.py`, add the import beside the other router imports (around line 30):

```python
from resume_agent.api.routers import settings as settings_router
```

Add the link router beside the other `download_guarded` registrations (after line 262):

```python
    app.include_router(
        settings_router.link_router, prefix="/api", dependencies=download_guarded
    )
```

Add the guarded router beside `config_router` (line 292):

```python
    app.include_router(settings_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_settings_api.py -v`
Expected: PASS, 9 tests

- [ ] **Step 7: Regenerate the contract**

Run: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS

- [ ] **Step 8: Run the whole backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS

- [ ] **Step 9: Lint and commit**

```bash
ruff check
git add src/resume_agent/api tests/api/test_settings_api.py contracts/
git commit -m "feat: expose settings bundle and reset over the API"
```

---

### Task 8: Web data layer and reset button

**Files:**
- Create: `web/src/features/settings/use-settings-sections.ts`
- Create: `web/src/features/settings/ResetSectionButton.tsx`
- Test: `web/src/features/settings/ResetSectionButton.test.tsx`

**Interfaces:**
- Consumes: `/api/settings/sections`, `/api/settings/sections/{sectionId}/reset` from Task 7
- Produces:
  - `useSettingsSections()` — TanStack query returning `SettingsSection[]`
  - `useResetSection()` — mutation taking `{ sectionId: string }`
  - `SETTINGS_SECTIONS_KEY` query key
  - `<ResetSectionButton sectionId label />`

- [ ] **Step 1: Write the failing test**

Create `web/src/features/settings/ResetSectionButton.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, test, vi } from "vitest";

import { ResetSectionButton } from "./ResetSectionButton";

const reset = vi.fn();
const server = setupServer(
  http.post("*/api/settings/sections/:id/reset", ({ params }) => {
    reset(params.id);
    return HttpResponse.json({
      id: params.id,
      label: "Company sources",
      customized: false,
    });
  }),
);

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  reset.mockClear();
});
afterAll(() => server.close());

function renderButton() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ResetSectionButton sectionId="sources" label="Company sources" />
    </QueryClientProvider>,
  );
}

test("does not reset until the dialog is confirmed", async () => {
  const user = userEvent.setup();
  renderButton();

  await user.click(screen.getByRole("button", { name: /reset to defaults/i }));
  expect(reset).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: /^reset$/i }));
  await waitFor(() => expect(reset).toHaveBeenCalledWith("sources"));
});

test("names the section it will reset", async () => {
  const user = userEvent.setup();
  renderButton();

  await user.click(screen.getByRole("button", { name: /reset to defaults/i }));
  expect(
    screen.getByText(/reset company sources to defaults/i),
  ).toBeInTheDocument();
});

test("cancelling leaves the section untouched", async () => {
  const user = userEvent.setup();
  renderButton();

  await user.click(screen.getByRole("button", { name: /reset to defaults/i }));
  await user.click(screen.getByRole("button", { name: /cancel/i }));
  expect(reset).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- ResetSectionButton`
Expected: FAIL — cannot resolve `./ResetSectionButton`

- [ ] **Step 3: Write the hook**

Create `web/src/features/settings/use-settings-sections.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { paths } from "@/lib/api/schema";

export type SettingsSection =
  paths["/api/settings/sections"]["get"]["responses"][200]["content"]["application/json"]["sections"][number];

export const SETTINGS_SECTIONS_KEY = ["settings-sections"] as const;

export function useSettingsSections() {
  return useQuery({
    queryKey: SETTINGS_SECTIONS_KEY,
    queryFn: async () => {
      const body = await unwrap(api.GET("/api/settings/sections"));
      return (body as { sections: SettingsSection[] }).sections;
    },
  });
}

export function useResetSection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sectionId }: { sectionId: string }) =>
      unwrap(
        api.POST("/api/settings/sections/{section_id}/reset", {
          params: { path: { section_id: sectionId } },
        }),
      ) as Promise<SettingsSection>,
    onSuccess: (section) => {
      // A reset rewrites files other settings pages read, so drop everything
      // rather than trying to name each affected query key.
      queryClient.invalidateQueries();
      toast.success(`${section.label} reset to defaults`);
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
```

If the generated path parameter in `contracts/ts/api.ts` is named differently from `section_id`, use the generated name — openapi-typescript mirrors the FastAPI parameter exactly.

- [ ] **Step 4: Write the button**

Create `web/src/features/settings/ResetSectionButton.tsx`:

```tsx
import { RotateCcw } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

import { useResetSection } from "./use-settings-sections";

/** Restores one settings section to the value a fresh workspace would have.
 *  Used both in the Backup page's section table and on individual settings
 *  pages, so the confirm copy stays identical wherever a reset is offered. */
export function ResetSectionButton({
  sectionId,
  label,
  note,
}: {
  sectionId: string;
  label: string;
  note?: string;
}) {
  const reset = useResetSection();
  return (
    <AlertDialog>
      <AlertDialogTrigger render={<Button variant="outline" size="sm" />}>
        <RotateCcw data-icon="inline-start" />
        Reset to defaults
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogMedia>
            <RotateCcw aria-hidden="true" />
          </AlertDialogMedia>
          <AlertDialogTitle>Reset {label} to defaults?</AlertDialogTitle>
          <AlertDialogDescription>
            This replaces your {label.toLowerCase()} with the shipped default.
            Your current values are lost — export a settings bundle first if you
            want them back.
            {note ? ` ${note}` : ""}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={reset.isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={reset.isPending}
            onClick={(event) => {
              event.preventDefault();
              reset.mutate({ sectionId });
            }}
          >
            {reset.isPending ? <Spinner data-icon="inline-start" /> : null}
            Reset
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd web && npm test -- ResetSectionButton`
Expected: PASS, 3 tests

- [ ] **Step 6: Typecheck and commit**

```bash
cd web && npm run typecheck && cd ..
git add web/src/features/settings/use-settings-sections.ts web/src/features/settings/ResetSectionButton.tsx web/src/features/settings/ResetSectionButton.test.tsx
git commit -m "feat(web): shared reset-to-defaults control"
```

---

### Task 9: The Backup page

**Files:**
- Create: `web/src/features/settings/pages/BackupSettingsPage.tsx`
- Create: `web/src/features/settings/pages/BackupSettingsPage.test.tsx`
- Modify: `web/src/features/settings/SettingsLayout.tsx:51-54`
- Modify: `web/src/app/router.tsx`

**Interfaces:**
- Consumes: `useSettingsSections`, `ResetSectionButton` from Task 8; `openDownload`, `getToken` from `@/lib/api/client`
- Produces: `<BackupSettingsPage />` at route `/settings/backup`

- [ ] **Step 1: Write the failing test**

Create `web/src/features/settings/pages/BackupSettingsPage.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, expect, test, vi } from "vitest";

import { BackupSettingsPage } from "./BackupSettingsPage";

const applied = vi.fn();
const server = setupServer(
  http.get("*/api/settings/sections", () =>
    HttpResponse.json({
      sections: [
        { id: "sources", label: "Company sources", customized: true },
        { id: "prune", label: "Pruning", customized: false },
      ],
    }),
  ),
  http.post("*/api/settings/bundle/preview", () =>
    HttpResponse.json({
      version: 1,
      exportedAt: "2026-07-23T00:00:00+00:00",
      sections: [{ id: "sources", label: "Company sources", customized: true }],
      unknownSections: [],
    }),
  ),
  http.post("*/api/settings/bundle", () => {
    applied();
    return HttpResponse.json({ applied: ["sources"] });
  }),
);

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  applied.mockClear();
});
afterAll(() => server.close());

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BackupSettingsPage />
    </QueryClientProvider>,
  );
}

test("lists every section with its customized state", async () => {
  renderPage();
  expect(await screen.findByText("Company sources")).toBeInTheDocument();
  expect(screen.getByText("Pruning")).toBeInTheDocument();
  expect(screen.getByText("Customized")).toBeInTheDocument();
  expect(screen.getByText("Default")).toBeInTheDocument();
});

test("offers a reset control per section", async () => {
  renderPage();
  await screen.findByText("Company sources");
  expect(
    screen.getAllByRole("button", { name: /reset to defaults/i }),
  ).toHaveLength(2);
});

test("previews a chosen bundle before applying it", async () => {
  const user = userEvent.setup();
  renderPage();
  await screen.findByText("Company sources");

  const file = new File(["x"], "bundle.tar.gz", { type: "application/gzip" });
  await user.upload(screen.getByLabelText(/bundle file/i), file);

  expect(
    await screen.findByText(/this bundle will replace/i),
  ).toBeInTheDocument();
  expect(applied).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: /apply bundle/i }));
  await waitFor(() => expect(applied).toHaveBeenCalled());
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- BackupSettingsPage`
Expected: FAIL — cannot resolve `./BackupSettingsPage`

- [ ] **Step 3: Write the page**

Create `web/src/features/settings/pages/BackupSettingsPage.tsx`:

```tsx
import { useId, useState } from "react";
import { Archive, Download, Upload } from "lucide-react";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { authHeaders, apiUrl, openDownload } from "@/lib/api/client";

import { ResetSectionButton } from "../ResetSectionButton";
import {
  type SettingsSection,
  useSettingsSections,
} from "../use-settings-sections";

type Preview = {
  sections: SettingsSection[];
  unknownSections: string[];
};

async function post(path: string, file: File): Promise<unknown> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  const body = await response.json();
  if (!response.ok) {
    throw new Error(body?.error?.message ?? "Request failed");
  }
  return body;
}

export function BackupSettingsPage() {
  const fileId = useId();
  const queryClient = useQueryClient();
  const { data: sections = [], isLoading } = useSettingsSections();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);

  async function choose(chosen: File | null) {
    setFile(chosen);
    setPreview(null);
    if (!chosen) return;
    setBusy(true);
    try {
      setPreview((await post("/api/settings/bundle/preview", chosen)) as Preview);
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!file) return;
    setBusy(true);
    try {
      await post("/api/settings/bundle?confirm=APPLY", file);
      toast.success("Settings bundle applied");
      setFile(null);
      setPreview(null);
      await queryClient.invalidateQueries();
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader className="border-b">
          <CardTitle>
            <h3>Settings bundle</h3>
          </CardTitle>
          <CardDescription>
            Move your customizations between installs. A bundle carries only the
            settings below — never your jobs, your profile, or your API keys.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="outline"
              onClick={() => void openDownload("/api/settings/bundle")}
            >
              <Download data-icon="inline-start" />
              Export settings
            </Button>
          </div>
          <Field>
            <FieldLabel htmlFor={fileId}>Bundle file</FieldLabel>
            <Input
              id={fileId}
              type="file"
              accept=".tar.gz,.tgz,application/gzip"
              onChange={(event) =>
                void choose(event.target.files?.[0] ?? null)
              }
            />
          </Field>
          {preview ? (
            <div className="rounded-lg border p-4 text-sm">
              <p>
                <strong>This bundle will replace:</strong>{" "}
                {preview.sections.map((section) => section.label).join(", ") ||
                  "nothing"}
                . Your other settings are untouched.
              </p>
              {preview.unknownSections.length > 0 ? (
                <p className="mt-2 text-muted-foreground">
                  Ignoring {preview.unknownSections.length} section(s) this
                  version does not recognize.
                </p>
              ) : null}
              <Button
                className="mt-3"
                disabled={busy || preview.sections.length === 0}
                onClick={() => void apply()}
              >
                {busy ? <Spinner data-icon="inline-start" /> : null}
                Apply bundle
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="border-b">
          <div className="flex items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
              <Archive aria-hidden="true" />
            </div>
            <div className="flex flex-col gap-1">
              <CardTitle>
                <h3>Customizable settings</h3>
              </CardTitle>
              <CardDescription>
                Everything a bundle can carry, and everything you can reset.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col divide-y">
          {isLoading ? <Spinner /> : null}
          {sections.map((section) => (
            <div
              key={section.id}
              className="flex flex-wrap items-center gap-3 py-3"
            >
              <span className="font-medium">{section.label}</span>
              <Badge variant={section.customized ? "default" : "outline"}>
                {section.customized ? "Customized" : "Default"}
              </Badge>
              <div className="ml-auto">
                <ResetSectionButton
                  sectionId={section.id}
                  label={section.label}
                  note={
                    section.id === "skill_overrides"
                      ? "Takes effect on your next profile build."
                      : undefined
                  }
                />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
```

The `Upload` import is unused in this version — remove it if `ruff`'s JS counterpart (`npm run lint`) complains.

- [ ] **Step 4: Add the nav item**

In `web/src/features/settings/SettingsLayout.tsx`, add `Archive` to the `lucide-react` import list, then replace the `System` group:

```tsx
  {
    label: "System",
    items: [
      { to: "/settings/keys", label: "API keys", icon: FileKey2 },
      { to: "/settings/backup", label: "Backup", icon: Archive },
    ],
  },
```

- [ ] **Step 5: Add the route**

In `web/src/app/router.tsx`, add the lazy import beside the other settings pages:

```tsx
const BackupSettingsPage = lazy(() =>
  import("@/features/settings/pages/BackupSettingsPage").then((m) => ({
    default: m.BackupSettingsPage,
  })),
);
```

And the child route after `style-guide`:

```tsx
          { path: "backup", element: page(<BackupSettingsPage />) },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && npm test -- BackupSettingsPage SettingsLayout`
Expected: PASS. `SettingsLayout.test.tsx` may assert a nav-item count — update that expectation to include Backup.

- [ ] **Step 7: Typecheck and commit**

```bash
cd web && npm run typecheck && cd ..
git add web/src/features/settings/pages/BackupSettingsPage.tsx web/src/features/settings/pages/BackupSettingsPage.test.tsx web/src/features/settings/SettingsLayout.tsx web/src/app/router.tsx web/src/features/settings/SettingsLayout.test.tsx
git commit -m "feat(web): settings backup page with bundle transfer and reset table"
```

---

### Task 10: Per-page and per-agent reset controls

**Files:**
- Modify: `web/src/features/settings/pages/SearchSettingsPage.tsx`
- Modify: `web/src/features/settings/pages/ReviewSettingsPage.tsx`
- Modify: `web/src/features/settings/pages/RenderingSettingsPage.tsx`
- Modify: `web/src/features/settings/pages/PruningSettingsPage.tsx`
- Modify: `web/src/features/settings/pages/StyleGuideSettingsPage.tsx`
- Modify: `web/src/features/settings/pages/AgentPromptsPage.tsx`
- Modify: `web/src/features/sources/` sources page (find it via the `/settings/sources` route in `router.tsx`)
- Test: `web/src/features/settings/pages/AgentPromptsPage.test.tsx` (append)

**Interfaces:**
- Consumes: `ResetSectionButton` from Task 8, `useSaveGuidance` from `use-prompts.ts`
- Produces: no new exports

- [ ] **Step 1: Write the failing test**

Append to `web/src/features/settings/pages/AgentPromptsPage.test.tsx` (match the existing file's imports and server setup — read it first):

```tsx
test("resetting one agent clears just its guidance", async () => {
  const user = userEvent.setup();
  renderPage(); // reuse the helper already in this file

  await screen.findByText(/writer/i);
  const resets = screen.getAllByRole("button", { name: /reset this agent/i });
  await user.click(resets[0]);

  await waitFor(() =>
    expect(savedGuidance).toHaveBeenCalledWith(
      expect.objectContaining({ guidance: "" }),
    ),
  );
});
```

Add a `savedGuidance` spy to the existing `msw` handler for `PUT /api/agents/prompts/:key` in that file, recording the request body.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- AgentPromptsPage`
Expected: FAIL — no button named "Reset this agent"

- [ ] **Step 3: Add the per-agent reset**

In `AgentPromptsPage.tsx`, on each **editable** prompt card (`item.editable === true`), add beside the save control:

```tsx
<Button
  variant="ghost"
  size="sm"
  disabled={!item.guidance || save.isPending}
  onClick={() => save.mutate({ key: item.key, guidance: "" })}
>
  Reset this agent
</Button>
```

`save` is the existing `useSaveGuidance()` mutation. Saving empty guidance deletes the key — see `save_guidance` in `prompts/guidance.py`. Do **not** render this on non-editable prompts; `reviewer-fact-check` is an integrity gate.

- [ ] **Step 4: Add section resets to each page heading**

On each page, place the control in the heading row. Example for `SearchSettingsPage.tsx`:

```tsx
import { ResetSectionButton } from "../ResetSectionButton";

// inside the header row, after the title:
<ResetSectionButton sectionId="search" label="Search" />
```

Section ids per page:

| File | `sectionId` / `label` |
| --- | --- |
| `SearchSettingsPage.tsx` | `search` / "Search" |
| `ReviewSettingsPage.tsx` | `review` / "Review panel" |
| `RenderingSettingsPage.tsx` | `render` / "Rendering" **and** `templates` / "Custom resume templates" |
| `PruningSettingsPage.tsx` | `prune` / "Pruning" |
| `StyleGuideSettingsPage.tsx` | `style_guide` / "Style guide" |
| sources page | `sources` / "Company sources" |
| `AgentPromptsPage.tsx` | `agent_guidance` / "Agent prompts" (page level, alongside the per-agent buttons) |

- [ ] **Step 5: Run the whole web suite**

Run: `cd web && npm test`
Expected: PASS

- [ ] **Step 6: Typecheck, lint, and commit**

```bash
cd web && npm run typecheck && npm run lint && cd ..
git add web/src
git commit -m "feat(web): reset controls on settings pages and agent prompts"
```

---

### Task 11: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the registry to the design notes**

In `CLAUDE.md`, under **Known design notes**, add:

```markdown
- **The customizable settings surface is declared once.** `settings_sections.py`
  holds `SETTINGS_SECTIONS`: twelve rows naming each transferable, resettable
  unit and the canonical relative paths it owns (`config/connectors.yaml`,
  `data/profile/overrides.yaml`). It is an **allowlist** — it spans the
  workspace root alongside `secrets.env`, `gmail_token.json`,
  `resume_agent.db`, and `config/gmail_credentials.json`, so a file not named
  there can neither leave a workspace in a settings bundle nor enter one from
  an imported bundle. `services/settings_bundle.py` exports and imports that
  set as a tar.gz (`GET/POST /api/settings/bundle`), replacing the sections a
  bundle names and leaving the rest untouched — a bundle can add or replace
  settings but never clear them. Reset (`POST
  /api/settings/sections/{id}/reset`) copies the shipped `.example` when one
  exists and deletes the file otherwise, which is the same rule
  `provision_workspace` uses to seed a fresh workspace. Import validation uses
  the artifacts' **models** but not their read-time loaders:
  `load_group_corrections` and `load_taxonomy_corrections` return an empty
  ledger on corruption, which is right for reading and catastrophic for
  importing.
```

- [ ] **Step 2: Add the hot path**

In the **Hot paths** table, add:

```markdown
| `src/resume_agent/settings_sections.py`              | Single enumeration of customizable settings: bundle scope + reset targets                                                 |
```

- [ ] **Step 3: Full verification**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Then: `cd web && npm test && npm run typecheck && cd ..`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the settings registry as the single enumeration"
```

---

## Self-Review Notes

**Spec coverage:** section registry (T1), reset semantics incl. the five delete-defaults (T1-2), provisioning as reader (T3), export + manifest + credential exclusion (T4), strict validation incl. the tolerant-loader trap (T5), section-level replace + rollback + zero-claim guard (T6), five endpoints + error codes + runs-active guard + contract (T7), shared reset control (T8), Backup page as canonical surface (T9), per-page and per-agent resets (T10), docs (T11).

**Known deviations from the spec, both deliberate:**

1. The spec lists `UNSUPPORTED_VERSION` and `UNSAFE_ARCHIVE` as separate codes; `UnsupportedBundleVersionError` subclasses `InvalidBundleError`, so `_bundle_error` must check it **first**. It does.
2. `is_customized` treats an absent file with a shipped default as *not* customized. The spec says "differs from the shipped `.example`", which would literally mark a fresh workspace as customized. The badge answers "do you have changes worth exporting", so absent means nothing to lose.

**Caught during self-review:** the first draft built `UserContext(user_id=..., username=..., is_admin=..., paths=...)` in every test. `UserContext` actually has **eight** required fields (`user_id`, `username`, `role`, `paths`, `settings`, `engine`, `system_engine`, `own_key_providers`) and `is_admin` is a read-only property derived from `role`. Every test would have died with `TypeError` on the first line. The plan now mirrors the existing helper at `tests/tenancy/test_workspace.py:13`.

**Open risk:** Task 3 changes `provision_workspace`, whose `template_dir` is threaded through six call sites and pinned by `tests/api/conftest.py`. The task preserves the parameter and only moves the *file list* into the registry. If `tests/api` fails after Task 3, the cause is an `.example` that ships but is not in the registry — add a section for it rather than restoring the glob.
