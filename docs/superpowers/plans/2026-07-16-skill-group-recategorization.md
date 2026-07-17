# Skill-Group Re-categorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user re-assign a skill's display group from the web UI, pinned durably in a corrections ledger so no rebuild or taxonomy reset ever re-applies the LLM's wrong guess.

**Architecture:** A new user-truth ledger (`data/profile/group_corrections.json`) sits above `overrides.yaml`'s `group:` map and the LLM taxonomy in `apply_skill_groups` precedence. A shared `decorate_matrix_groups` helper makes all three matrix-decorating call sites load the ledger. A `services/profile_groups.py` service mutates the ledger under the existing profile lock and rebuilds `matrix.json`; `PUT`/`DELETE /api/profile/skills/{key}/group` expose it; the Settings → Skill groups panel gets a per-badge dropdown.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic (`ExtensibleModel`), React 19 + TanStack Query + shadcn (base-ui) dropdown-menu, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-07-16-skill-group-recategorization-design.md`

## Global Constraints

- All tests run offline — no API key, no network: `.venv/Scripts/python.exe -m pytest`, lint with `ruff check`.
- Frontend tests: `cd web && npx vitest run <file>`; lint with `cd web && npm run lint`.
- Group slugs are the fixed 13-slug vocabulary `SKILL_GROUPS` in `src/resume_agent/taxonomy/groups.py`; never invent slugs.
- Wire format is camelCase (`CamelModel`); Python stays snake_case. After any schema change regenerate contracts with `bash scripts/gen_ts_client.sh` — `tests/api/test_openapi_contract.py` gates drift.
- Precedence (spec §2): **correction ledger > `overrides.yaml` `group:` map > LLM taxonomy**. Corrections never alter `facts.json`, categories, or fact-lock.
- "Profile not built" maps to HTTP 400 `SETUP_INCOMPLETE` (matches every manual-skills endpoint); unknown slug → 422; unknown skill / missing correction → 404.
- Atomic file writes only (tempfile + `os.fsync` + `os.replace`), matching `save_manual_skills`.
- Commit after every task; do not batch tasks into one commit.

---

### Task 1: Corrections ledger module

**Files:**
- Create: `src/resume_agent/profile/group_corrections.py`
- Test: `tests/test_group_corrections.py`

**Interfaces:**
- Consumes: `SKILL_GROUPS` (`taxonomy/groups.py`), `normalize_skill` (`tracking/match_gap.py`), `ExtensibleModel` (`models/base.py`).
- Produces (used by Tasks 2–3):
  - `corrections_path(profile_dir: str | Path) -> Path`
  - `class GroupCorrection(ExtensibleModel)` — fields `group: str`, `corrected_at: str = ""`
  - `class GroupCorrections(ExtensibleModel)` — field `corrections: dict[str, GroupCorrection]`, method `as_map() -> dict[str, str]`
  - `load_group_corrections(path) -> GroupCorrections` (missing/corrupt → empty; normalizes tokens, drops unknown slugs)
  - `save_group_corrections(ledger, path) -> None` (atomic)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_group_corrections.py`:

```python
from resume_agent.profile.group_corrections import (
    GroupCorrection,
    GroupCorrections,
    corrections_path,
    load_group_corrections,
    save_group_corrections,
)


def test_corrections_path_is_profile_scoped(tmp_path):
    assert corrections_path(tmp_path) == tmp_path / "group_corrections.json"


def test_missing_file_loads_empty(tmp_path):
    assert load_group_corrections(tmp_path / "group_corrections.json").corrections == {}


def test_corrupt_file_loads_empty(tmp_path):
    path = tmp_path / "group_corrections.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_group_corrections(path).corrections == {}


def test_round_trip_normalizes_tokens_and_drops_unknown_slugs(tmp_path):
    path = corrections_path(tmp_path)
    ledger = GroupCorrections(
        corrections={
            "  DBT  ": GroupCorrection(
                group="data-ml", corrected_at="2026-07-16T00:00:00+00:00"
            ),
            "mystery": GroupCorrection(group="not-a-real-group"),
        }
    )
    save_group_corrections(ledger, path)
    loaded = load_group_corrections(path)
    assert loaded.as_map() == {"dbt": "data-ml"}
    assert loaded.corrections["dbt"].corrected_at == "2026-07-16T00:00:00+00:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_group_corrections.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.group_corrections'`

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/profile/group_corrections.py`:

```python
"""Durable ledger of user skill-group corrections.

``data/taxonomy/skill_groups.json`` is a rebuildable LLM cache -- first-writer-
wins merges and missing-tokens-only classification mean a wrong guess there is
frozen, and a cache reset would lose any hand fix. This ledger is the user-truth
side of that split: corrections live beside the profile
(``data/profile/group_corrections.json``), are never written by the classifier,
and win over both the taxonomy and ``overrides.yaml``'s ``group:`` map when
matrix rows are decorated (``profile/matrix.py::apply_skill_groups``).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.groups import SKILL_GROUPS
from resume_agent.tracking.match_gap import normalize_skill


def corrections_path(profile_dir: str | Path) -> Path:
    return Path(profile_dir) / "group_corrections.json"


class GroupCorrection(ExtensibleModel):
    group: str
    corrected_at: str = ""


class GroupCorrections(ExtensibleModel):
    corrections: dict[str, GroupCorrection] = Field(default_factory=dict)

    def as_map(self) -> dict[str, str]:
        return {token: entry.group for token, entry in self.corrections.items()}


def load_group_corrections(path: str | Path) -> GroupCorrections:
    try:
        ledger = GroupCorrections.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return GroupCorrections()
    clean: dict[str, GroupCorrection] = {}
    for raw_token, entry in ledger.corrections.items():
        token = normalize_skill(raw_token)
        if token and entry.group in SKILL_GROUPS:
            clean.setdefault(token, entry)
    ledger.corrections = clean
    return ledger


def save_group_corrections(ledger: GroupCorrections, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(ledger.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_group_corrections.py -q && ruff check src/resume_agent/profile/group_corrections.py tests/test_group_corrections.py`
Expected: 4 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/profile/group_corrections.py tests/test_group_corrections.py
git commit -m "feat: add skill-group corrections ledger"
```

---

### Task 2: Precedence + `group_source` + shared decorate/rebuild helpers

**Files:**
- Modify: `src/resume_agent/profile/matrix.py` (`MatrixRow`, `apply_skill_groups`, new `decorate_matrix_groups` / `rebuild_saved_matrix`)
- Modify: `src/resume_agent/services/profile_build.py` (use `decorate_matrix_groups`)
- Modify: `src/resume_agent/services/profile_skills.py` (replace `_rebuild_matrix` with `rebuild_saved_matrix`)
- Modify: `src/resume_agent/api/routers/match_gap.py` (use `decorate_matrix_groups`)
- Test: `tests/test_profile_matrix.py` (append)

**Interfaces:**
- Consumes (Task 1): `corrections_path`, `load_group_corrections` (`.as_map()`).
- Produces (used by Tasks 3–4):
  - `MatrixRow.group_source: Literal["correction", "override", "taxonomy"] | None`
  - `apply_skill_groups(matrix, group_of, overrides, corrections: dict[str, str] | None = None) -> None`
  - `decorate_matrix_groups(matrix: SkillMatrix, profile_dir: str | Path, overrides: Overrides) -> None`
  - `rebuild_saved_matrix(profile_dir: str | Path, facts: ProfileFacts) -> SkillMatrix` — builds, decorates, saves `matrix.json`, returns the matrix.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_profile_matrix.py` (add any missing imports at the top; the file already imports `MatrixRow`, `SkillMatrix`, `Overrides`, `apply_skill_groups`, `load_matrix`):

```python
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.group_corrections import (
    GroupCorrection,
    GroupCorrections,
    corrections_path,
    save_group_corrections,
)
from resume_agent.profile.matrix import rebuild_saved_matrix


def test_apply_groups_correction_beats_override_and_taxonomy():
    matrix = SkillMatrix(rows=[MatrixRow(key="python", display="Python")])
    overrides = Overrides(group={"python": "frameworks"})
    apply_skill_groups(
        matrix,
        {"python": "languages"},
        overrides,
        corrections={"python": "data-ml"},
    )
    assert matrix.rows[0].group == "data-ml"
    assert matrix.rows[0].group_source == "correction"


def test_apply_groups_records_override_taxonomy_and_none_sources():
    matrix = SkillMatrix(
        rows=[
            MatrixRow(key="python", display="Python"),
            MatrixRow(key="sql", display="SQL"),
            MatrixRow(key="mystery", display="Mystery"),
        ]
    )
    apply_skill_groups(
        matrix, {"python": "languages"}, Overrides(group={"sql": "databases"})
    )
    by_key = {row.key: row for row in matrix.rows}
    assert (by_key["python"].group, by_key["python"].group_source) == (
        "languages",
        "taxonomy",
    )
    assert (by_key["sql"].group, by_key["sql"].group_source) == (
        "databases",
        "override",
    )
    assert (by_key["mystery"].group, by_key["mystery"].group_source) == (None, None)


def test_apply_groups_correction_lookup_is_alias_aware():
    matrix = SkillMatrix(
        rows=[MatrixRow(key="postgresql", display="PostgreSQL", aliases=["postgres"])]
    )
    apply_skill_groups(matrix, {}, Overrides(), corrections={"postgres": "databases"})
    assert matrix.rows[0].group == "databases"
    assert matrix.rows[0].group_source == "correction"


def test_matrix_row_without_group_source_still_loads():
    row = MatrixRow.model_validate({"key": "python", "display": "Python"})
    assert row.group_source is None
    row = MatrixRow.model_validate(
        {"key": "python", "display": "Python", "group_source": "bogus"}
    )
    assert row.group_source is None


def test_rebuild_saved_matrix_applies_correction_ledger(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python")]},
    )
    save_group_corrections(
        GroupCorrections(corrections={"python": GroupCorrection(group="data-ml")}),
        corrections_path(profile_dir),
    )
    matrix = rebuild_saved_matrix(profile_dir, facts)
    assert matrix.rows[0].group == "data-ml"
    assert matrix.rows[0].group_source == "correction"
    reloaded = load_matrix(profile_dir / "matrix.json")
    assert reloaded is not None
    assert reloaded.rows[0].group == "data-ml"
    assert reloaded.rows[0].group_source == "correction"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_matrix.py -q`
Expected: new tests FAIL (`group_source` unknown field / `TypeError: apply_skill_groups() got an unexpected keyword argument 'corrections'` / `ImportError: cannot import name 'rebuild_saved_matrix'`). Pre-existing tests still pass.

- [ ] **Step 3: Implement in `src/resume_agent/profile/matrix.py`**

3a. Update imports (top of file). Replace:

```python
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.groups import SKILL_GROUPS, sanitize_group_map
```

with:

```python
from resume_agent.profile.group_corrections import (
    corrections_path,
    load_group_corrections,
)
from resume_agent.taxonomy.clusters import ClusterMap, load_cluster_map
from resume_agent.taxonomy.groups import (
    SKILL_GROUPS,
    group_map_path,
    load_group_map,
    sanitize_group_map,
)
```

3b. Add to `MatrixRow` (after the `group` field and its validator):

```python
    group_source: Literal["correction", "override", "taxonomy"] | None = None

    @field_validator("group_source", mode="before")
    @classmethod
    def validate_group_source(cls, value: object) -> object | None:
        return value if value in ("correction", "override", "taxonomy") else None
```

3c. Replace the whole `apply_skill_groups` function with:

```python
def _lookup_group(mapping: dict[str, str], keys: list[str]) -> str | None:
    return next((mapping[key] for key in keys if key in mapping), None)


def apply_skill_groups(
    matrix: SkillMatrix,
    group_of: dict[str, str],
    overrides: Overrides,
    corrections: dict[str, str] | None = None,
) -> None:
    """Decorate rows with validated groups; corrections > overrides > taxonomy."""
    taxonomy = sanitize_group_map(group_of)
    override_groups = sanitize_group_map(overrides.group)
    correction_groups = sanitize_group_map(corrections or {})
    for row in matrix.rows:
        lookup_keys = [
            row.key,
            normalize_skill(row.display),
            *(normalize_skill(alias) for alias in row.aliases),
        ]
        correction = _lookup_group(correction_groups, lookup_keys)
        override = _lookup_group(override_groups, lookup_keys)
        taxonomy_group = taxonomy.get(row.key)
        if correction is not None:
            row.group, row.group_source = correction, "correction"
        elif override is not None:
            row.group, row.group_source = override, "override"
        elif taxonomy_group is not None:
            row.group, row.group_source = taxonomy_group, "taxonomy"
        else:
            row.group, row.group_source = None, None
```

3d. Add the two shared helpers (after `apply_skill_groups`, before `save_matrix`):

```python
def decorate_matrix_groups(
    matrix: SkillMatrix, profile_dir: str | Path, overrides: Overrides
) -> None:
    """Apply taxonomy + correction-ledger groups -- the one seam every consumer uses."""
    profile_dir = Path(profile_dir)
    group_map = load_group_map(group_map_path(profile_dir))
    corrections = load_group_corrections(corrections_path(profile_dir)).as_map()
    apply_skill_groups(matrix, group_map, overrides, corrections=corrections)


def rebuild_saved_matrix(profile_dir: str | Path, facts: ProfileFacts) -> SkillMatrix:
    """Rebuild and persist matrix.json from facts plus on-disk config artifacts."""
    profile_dir = Path(profile_dir)
    overrides = load_overrides(profile_dir / "overrides.yaml")
    matrix = build_matrix(
        facts, load_cluster_map(profile_dir / "cluster_map.json"), overrides
    )
    decorate_matrix_groups(matrix, profile_dir, overrides)
    save_matrix(matrix, profile_dir / "matrix.json")
    return matrix
```

- [ ] **Step 4: Switch the three call sites**

4a. `src/resume_agent/services/profile_build.py` — in `run_corpus_build`, replace:

```python
        taxonomy_path = skill_groups.group_map_path(profile_dir)
        group_map = skill_groups.load_group_map(taxonomy_path)
        missing = {row.key for row in matrix.rows} - set(group_map)
        if missing:
            additions = skill_groups.classify_missing_groups(
                missing,
                skill_groups.build_group_classifier_agent(),
            )
            if additions:
                skill_groups.save_group_map(additions, taxonomy_path)
                group_map = skill_groups.load_group_map(taxonomy_path)
        apply_skill_groups(matrix, group_map, overrides)
```

with:

```python
        taxonomy_path = skill_groups.group_map_path(profile_dir)
        group_map = skill_groups.load_group_map(taxonomy_path)
        missing = {row.key for row in matrix.rows} - set(group_map)
        if missing:
            additions = skill_groups.classify_missing_groups(
                missing,
                skill_groups.build_group_classifier_agent(),
            )
            if additions:
                skill_groups.save_group_map(additions, taxonomy_path)
        decorate_matrix_groups(matrix, profile_dir, overrides)
```

and in the same file's imports change `apply_skill_groups` to `decorate_matrix_groups` (keep the other `profile.matrix` imports the file already uses).

4b. `src/resume_agent/services/profile_skills.py` — delete the `_rebuild_matrix` function; replace its three call sites (`add_skill`, `add_alias`, `remove_manual_entry`) with `rebuild_saved_matrix(profile_dir, updated_facts)`, and replace the import line

```python
from resume_agent.profile.matrix import apply_skill_groups, build_matrix, load_overrides, save_matrix
```

with

```python
from resume_agent.profile.matrix import rebuild_saved_matrix
```

Also remove the now-unused imports `from resume_agent.taxonomy import groups as skill_groups` and `from resume_agent.taxonomy.clusters import load_cluster_map` (ruff will flag any leftovers).

4c. `src/resume_agent/api/routers/match_gap.py` — in the refresh worker, replace:

```python
        apply_skill_groups(
            matrix,
            load_group_map(group_map_path(facts_path.parent)),
            overrides,
        )
```

with:

```python
        decorate_matrix_groups(matrix, facts_path.parent, overrides)
```

Update the imports: in the `from resume_agent.profile.matrix import (...)` block replace `apply_skill_groups` with `decorate_matrix_groups`, and delete the line `from resume_agent.taxonomy.groups import group_map_path, load_group_map`.

- [ ] **Step 5: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: all pass (existing `test_apply_groups_uses_taxonomy_and_alias_aware_override_precedence` and profile-build/skills/match-gap tests must stay green), ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/profile/matrix.py src/resume_agent/services/profile_build.py src/resume_agent/services/profile_skills.py src/resume_agent/api/routers/match_gap.py tests/test_profile_matrix.py
git commit -m "feat: correction-aware group precedence with group_source provenance"
```

---

### Task 3: `services/profile_groups.py`

**Files:**
- Create: `src/resume_agent/services/profile_groups.py`
- Test: `tests/test_profile_groups_service.py`

**Interfaces:**
- Consumes (Tasks 1–2): `corrections_path`, `load_group_corrections`, `save_group_corrections`, `GroupCorrection`, `rebuild_saved_matrix`, `MatrixRow`; also `manual_skills_lock`, `load_facts`, `SKILL_GROUPS`, `normalize_skill`, and `ProfileNotBuiltError` / `SkillNotFoundError` from `services/profile_skills.py`.
- Produces (used by Task 4):
  - `set_group(profile_dir: str | Path, key: str, group: str) -> MatrixRow`
  - `clear_group(profile_dir: str | Path, key: str) -> None`
  - `class UnknownGroupError(ValueError)`, `class GroupCorrectionNotFoundError(ValueError)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_profile_groups_service.py`:

```python
import pytest

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.group_corrections import (
    corrections_path,
    load_group_corrections,
)
from resume_agent.profile.matrix import load_matrix, rebuild_saved_matrix
from resume_agent.profile.store import load_facts, save_facts
from resume_agent.services.profile_groups import (
    GroupCorrectionNotFoundError,
    UnknownGroupError,
    clear_group,
    set_group,
)
from resume_agent.services.profile_skills import (
    ProfileNotBuiltError,
    SkillNotFoundError,
)
from resume_agent.taxonomy.groups import group_map_path, save_group_map


@pytest.fixture()
def profile_dir(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir(parents=True)
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python", aliases=["py"])]},
    )
    save_facts(facts, profile / "facts.json")
    save_group_map({"python": "languages"}, group_map_path(profile))
    return profile


def test_set_group_raises_when_profile_not_built(tmp_path):
    with pytest.raises(ProfileNotBuiltError):
        set_group(tmp_path / "profile", "python", "data-ml")


def test_set_group_rejects_unknown_slug(profile_dir):
    with pytest.raises(UnknownGroupError):
        set_group(profile_dir, "python", "not-a-group")


def test_set_group_rejects_unknown_skill(profile_dir):
    with pytest.raises(SkillNotFoundError):
        set_group(profile_dir, "cobol", "languages")


def test_set_group_writes_ledger_and_matrix(profile_dir):
    row = set_group(profile_dir, "python", "data-ml")
    assert (row.group, row.group_source) == ("data-ml", "correction")

    ledger = load_group_corrections(corrections_path(profile_dir))
    assert ledger.as_map() == {"python": "data-ml"}
    assert ledger.corrections["python"].corrected_at

    saved = load_matrix(profile_dir / "matrix.json")
    assert saved is not None
    assert saved.rows[0].group == "data-ml"


def test_set_group_resolves_aliases_to_the_canonical_token(profile_dir):
    row = set_group(profile_dir, "py", "data-ml")
    assert row.key == "python"
    assert load_group_corrections(corrections_path(profile_dir)).as_map() == {
        "python": "data-ml"
    }


def test_correction_survives_taxonomy_reset_and_rebuild(profile_dir):
    set_group(profile_dir, "python", "data-ml")
    group_map_path(profile_dir).unlink()  # simulate LLM-cache reset

    facts = load_facts(profile_dir / "facts.json")
    matrix = rebuild_saved_matrix(profile_dir, facts)
    assert matrix.rows[0].group == "data-ml"
    assert matrix.rows[0].group_source == "correction"


def test_clear_group_reverts_to_taxonomy(profile_dir):
    set_group(profile_dir, "python", "data-ml")
    clear_group(profile_dir, "python")

    assert load_group_corrections(corrections_path(profile_dir)).corrections == {}
    saved = load_matrix(profile_dir / "matrix.json")
    assert saved is not None
    assert (saved.rows[0].group, saved.rows[0].group_source) == (
        "languages",
        "taxonomy",
    )


def test_clear_group_without_correction_raises(profile_dir):
    with pytest.raises(GroupCorrectionNotFoundError):
        clear_group(profile_dir, "python")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_groups_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.services.profile_groups'`

- [ ] **Step 3: Write the implementation**

Create `src/resume_agent/services/profile_groups.py`:

```python
"""Set or clear a durable skill-group correction and refresh matrix.json.

Mirrors ``services/profile_skills.py``: mutations run under the shared
profile-dir lock and end with a full derived-matrix rebuild so the change is
visible immediately. Corrections are keyed by the row's canonical token, so a
key passed as a display name or alias is resolved first.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.group_corrections import (
    GroupCorrection,
    corrections_path,
    load_group_corrections,
    save_group_corrections,
)
from resume_agent.profile.manual_skills import manual_skills_lock
from resume_agent.profile.matrix import MatrixRow, SkillMatrix, rebuild_saved_matrix
from resume_agent.profile.store import load_facts
from resume_agent.services.profile_skills import (
    ProfileNotBuiltError,
    SkillNotFoundError,
)
from resume_agent.taxonomy.groups import SKILL_GROUPS
from resume_agent.tracking.match_gap import normalize_skill


class UnknownGroupError(ValueError):
    """Raised when the requested group slug is not in the fixed vocabulary."""


class GroupCorrectionNotFoundError(ValueError):
    """Raised when clearing a correction that does not exist."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_facts_or_raise(profile_dir: str | Path) -> ProfileFacts:
    try:
        return load_facts(Path(profile_dir) / "facts.json")
    except FileNotFoundError as exc:
        raise ProfileNotBuiltError(
            "Build your profile before editing skill groups"
        ) from exc


def _resolve_row(matrix: SkillMatrix, key: str) -> MatrixRow:
    token = normalize_skill(key)
    for row in matrix.rows:
        needles = {
            row.key,
            normalize_skill(row.display),
            *(normalize_skill(alias) for alias in row.aliases),
        }
        if token in needles:
            return row
    raise SkillNotFoundError(f"No skill '{key}'")


def set_group(profile_dir: str | Path, key: str, group: str) -> MatrixRow:
    if group not in SKILL_GROUPS:
        raise UnknownGroupError(f"Unknown group '{group}'")
    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        row = _resolve_row(rebuild_saved_matrix(profile_dir, facts), key)
        path = corrections_path(profile_dir)
        ledger = load_group_corrections(path)
        ledger.corrections[row.key] = GroupCorrection(
            group=group, corrected_at=_utcnow()
        )
        save_group_corrections(ledger, path)
        return _resolve_row(rebuild_saved_matrix(profile_dir, facts), row.key)


def clear_group(profile_dir: str | Path, key: str) -> None:
    with manual_skills_lock(profile_dir):
        facts = _load_facts_or_raise(profile_dir)
        path = corrections_path(profile_dir)
        ledger = load_group_corrections(path)
        token = normalize_skill(key)
        if token not in ledger.corrections:
            token = _resolve_row(rebuild_saved_matrix(profile_dir, facts), key).key
        if token not in ledger.corrections:
            raise GroupCorrectionNotFoundError(f"No group correction for '{key}'")
        del ledger.corrections[token]
        save_group_corrections(ledger, path)
        rebuild_saved_matrix(profile_dir, facts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_groups_service.py -q && ruff check src/resume_agent/services/profile_groups.py tests/test_profile_groups_service.py`
Expected: 8 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/services/profile_groups.py tests/test_profile_groups_service.py
git commit -m "feat: profile_groups service for durable group corrections"
```

---

### Task 4: API endpoints + contract regeneration

**Files:**
- Modify: `src/resume_agent/api/schemas/profile.py` (`MatrixRowOut.group_source`, new `SetGroupIn`)
- Modify: `src/resume_agent/api/routers/profile.py` (two endpoints)
- Modify (generated): `contracts/openapi.json`, `contracts/ts/api.ts`
- Test: `tests/api/test_profile_groups_router.py`

**Interfaces:**
- Consumes (Task 3): `profile_groups.set_group` / `clear_group` / `UnknownGroupError` / `GroupCorrectionNotFoundError`; `profile_skills.ProfileNotBuiltError` / `SkillNotFoundError`.
- Produces (used by Task 5): wire routes `PUT /api/profile/skills/{key}/group` (body `{"group": "<slug>"}`, 200 → `MatrixRowOut` incl. `groupSource`) and `DELETE /api/profile/skills/{key}/group` (204); `MatrixOut` rows now carry `groupSource`.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_profile_groups_router.py`:

```python
import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.store import save_facts
from resume_agent.taxonomy.groups import group_map_path, save_group_map


@pytest.fixture()
def client(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(
        db_url="sqlite://",
        data_dir=data_dir,
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
    )
    with TestClient(app) as test_client:
        yield test_client, data_dir


def _seed(data_dir):
    profile = data_dir / "profile"
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python", aliases=["py"])]},
    )
    save_facts(facts, profile / "facts.json")
    save_group_map({"python": "languages"}, group_map_path(profile))


def test_put_group_requires_a_built_profile(client):
    test_client, _ = client
    resp = test_client.put(
        "/api/profile/skills/python/group", json={"group": "data-ml"}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SETUP_INCOMPLETE"


def test_put_group_rejects_unknown_slug(client):
    test_client, data_dir = client
    _seed(data_dir)
    resp = test_client.put(
        "/api/profile/skills/python/group", json={"group": "not-a-group"}
    )
    assert resp.status_code == 422


def test_put_group_rejects_unknown_skill(client):
    test_client, data_dir = client
    _seed(data_dir)
    resp = test_client.put(
        "/api/profile/skills/cobol/group", json={"group": "languages"}
    )
    assert resp.status_code == 404


def test_put_group_pins_and_matrix_reports_source(client):
    test_client, data_dir = client
    _seed(data_dir)
    resp = test_client.put(
        "/api/profile/skills/python/group", json={"group": "data-ml"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "python"
    assert body["group"] == "data-ml"
    assert body["groupSource"] == "correction"

    matrix = test_client.get("/api/profile/matrix").json()
    row = next(r for r in matrix["rows"] if r["key"] == "python")
    assert (row["group"], row["groupSource"]) == ("data-ml", "correction")


def test_delete_group_reverts_to_taxonomy(client):
    test_client, data_dir = client
    _seed(data_dir)
    test_client.put("/api/profile/skills/python/group", json={"group": "data-ml"})
    resp = test_client.delete("/api/profile/skills/python/group")
    assert resp.status_code == 204

    matrix = test_client.get("/api/profile/matrix").json()
    row = next(r for r in matrix["rows"] if r["key"] == "python")
    assert (row["group"], row["groupSource"]) == ("languages", "taxonomy")


def test_delete_group_without_correction_is_404(client):
    test_client, data_dir = client
    _seed(data_dir)
    resp = test_client.delete("/api/profile/skills/python/group")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_groups_router.py -q`
Expected: FAIL — 405/404 responses (routes don't exist yet).

- [ ] **Step 3: Implement schemas and routes**

3a. `src/resume_agent/api/schemas/profile.py` — add `group_source` to `MatrixRowOut` and a `SetGroupIn` model:

```python
class MatrixRowOut(CamelModel):
    key: str
    display: str
    category: str | None = None
    group: str | None = None
    group_source: Literal["correction", "override", "taxonomy"] | None = None
    inferred: bool = False
    strength: float = 0.0
    last_used: str | None = None


class SetGroupIn(CamelModel):
    group: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
    ]
```

3b. `src/resume_agent/api/routers/profile.py` — import `SetGroupIn` in the schemas import block, add `profile_groups` to the services import (`from resume_agent.services import profile_build, profile_groups, profile_skills`), and add after `delete_manual_skill`:

```python
@router.put("/profile/skills/{key}/group", response_model=MatrixRowOut)
def put_skill_group(key: str, payload: SetGroupIn, request: Request):
    try:
        row = profile_groups.set_group(_profile_dir(request), key, payload.group)
    except profile_groups.UnknownGroupError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    except profile_skills.ProfileNotBuiltError as exc:
        raise ApiException(400, "SETUP_INCOMPLETE", str(exc)) from exc
    except profile_skills.SkillNotFoundError as exc:
        raise ApiException(404, "NOT_FOUND", str(exc)) from exc
    return MatrixRowOut.model_validate(row)


@router.delete("/profile/skills/{key}/group", status_code=204)
def delete_skill_group(key: str, request: Request):
    try:
        profile_groups.clear_group(_profile_dir(request), key)
    except profile_skills.ProfileNotBuiltError as exc:
        raise ApiException(400, "SETUP_INCOMPLETE", str(exc)) from exc
    except (
        profile_groups.GroupCorrectionNotFoundError,
        profile_skills.SkillNotFoundError,
    ) as exc:
        raise ApiException(404, "NOT_FOUND", str(exc)) from exc
```

- [ ] **Step 4: Run the router tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_profile_groups_router.py tests/api/test_profile_matrix.py -q`
Expected: all pass.

- [ ] **Step 5: Regenerate contracts and run the drift gate**

Run: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q && .venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: contracts updated (`contracts/openapi.json`, `contracts/ts/api.ts` show the new paths + `groupSource`), full suite green.

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api/schemas/profile.py src/resume_agent/api/routers/profile.py tests/api/test_profile_groups_router.py contracts/openapi.json contracts/ts/api.ts
git commit -m "feat: PUT/DELETE skill-group correction endpoints with groupSource on matrix rows"
```

---

### Task 5: Editable SkillGroupsPanel

**Files:**
- Modify: `web/src/features/settings/use-matrix.ts` (two mutations)
- Modify: `web/src/features/settings/SkillGroupsPanel.tsx` (badge → dropdown, pin, reset)
- Test: `web/src/features/settings/SkillGroupsPanel.test.tsx` (extend)

**Interfaces:**
- Consumes (Task 4): generated schema paths `PUT/DELETE /api/profile/skills/{key}/group`; `MatrixRowOut.groupSource`.
- Produces: `useSetSkillGroup()` / `useClearSkillGroup()` TanStack mutations (both invalidate `["profile-matrix"]`).

- [ ] **Step 1: Write the failing tests**

In `web/src/features/settings/SkillGroupsPanel.test.tsx`, extend the hoisted state and mock, then add the interaction test. Replace the existing `vi.hoisted`/`vi.mock` block with:

```tsx
const state = vi.hoisted(() => ({
  value: {} as Record<string, unknown>,
  refetch: vi.fn(),
  setGroup: vi.fn(),
  clearGroup: vi.fn(),
}));

vi.mock("./use-matrix", () => ({
  useMatrix: () => ({ ...state.value, refetch: state.refetch }),
  useSetSkillGroup: () => ({ mutate: state.setGroup, isPending: false }),
  useClearSkillGroup: () => ({ mutate: state.clearGroup, isPending: false }),
}));
```

Reset the new mocks in `beforeEach` (`state.setGroup.mockReset(); state.clearGroup.mockReset();`) and append:

```tsx
  it("moves a skill to another group and resets a pinned one", async () => {
    state.value = {
      isPending: false,
      isError: false,
      data: {
        generatedAt: "2026-07-16T00:00:00Z",
        groups,
        rows: [
          { key: "python", display: "Python", category: "hard", group: "languages",
            groupSource: "taxonomy", inferred: false, strength: 3, lastUsed: "current" },
          { key: "dbt", display: "dbt", category: "hard", group: "languages",
            groupSource: "correction", inferred: false, strength: 1, lastUsed: null },
        ],
      },
    };
    render(<SkillGroupsPanel />);

    await userEvent.click(
      screen.getByRole("button", { name: /change group for python/i }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: /^other$/i }));
    expect(state.setGroup).toHaveBeenCalledWith({ key: "python", group: "other" });

    await userEvent.click(
      screen.getByRole("button", { name: /change group for dbt/i }),
    );
    await userEvent.click(
      await screen.findByRole("menuitem", { name: /reset to automatic/i }),
    );
    expect(state.clearGroup).toHaveBeenCalledWith("dbt");
  });

  it("does not offer reset for an automatic assignment", async () => {
    state.value = {
      isPending: false,
      isError: false,
      data: {
        generatedAt: "2026-07-16T00:00:00Z",
        groups,
        rows: [
          { key: "python", display: "Python", category: "hard", group: "languages",
            groupSource: "taxonomy", inferred: false, strength: 3, lastUsed: "current" },
        ],
      },
    };
    render(<SkillGroupsPanel />);
    await userEvent.click(
      screen.getByRole("button", { name: /change group for python/i }),
    );
    expect(await screen.findByRole("menuitem", { name: /^other$/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /reset to automatic/i })).toBeNull();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/features/settings/SkillGroupsPanel.test.tsx`
Expected: new tests FAIL (no button named "Change group for Python").

- [ ] **Step 3: Add the mutations to `use-matrix.ts`**

Replace the file's imports and append the mutations:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ProfileMatrix = components["schemas"]["MatrixOut"];

export function useMatrix() {
  return useQuery({
    queryKey: ["profile-matrix"],
    queryFn: () =>
      unwrap(api.GET("/api/profile/matrix", {} as never)) as Promise<ProfileMatrix>,
  });
}

export function useSetSkillGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { key: string; group: string }) =>
      unwrap(
        api.PUT("/api/profile/skills/{key}/group", {
          params: { path: { key: vars.key } },
          body: { group: vars.group },
        }),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-matrix"] });
      toast.success("Skill group updated");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}

export function useClearSkillGroup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      unwrap(
        api.DELETE("/api/profile/skills/{key}/group", {
          params: { path: { key } },
        }),
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["profile-matrix"] });
      toast.success("Reverted to automatic grouping");
    },
    onError: (error: Error) => toast.error(error.message),
  });
}
```

- [ ] **Step 4: Make the badges editable in `SkillGroupsPanel.tsx`**

Add imports:

```tsx
import { Check, CircleAlert, Layers3, Pin, Undo2 } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useClearSkillGroup, useMatrix, useSetSkillGroup } from "./use-matrix";
```

Inside the component (after `const matrix = useMatrix();`):

```tsx
  const setGroup = useSetSkillGroup();
  const clearGroup = useClearSkillGroup();
```

Replace the member badge rendering (`members.map((row) => (<Badge …>{row.display}</Badge>))`) with:

```tsx
                  {members.length > 0 ? members.map((row) => {
                    const current = row.group && known.has(row.group) ? row.group : "other";
                    return (
                      <DropdownMenu key={row.key}>
                        <DropdownMenuTrigger
                          aria-label={`Change group for ${row.display}`}
                          className="rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                        >
                          <Badge variant="outline" className="cursor-pointer gap-1">
                            {row.groupSource === "correction" ? (
                              <Pin aria-hidden className="size-3" />
                            ) : null}
                            {row.display}
                          </Badge>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          <DropdownMenuLabel>Move to…</DropdownMenuLabel>
                          {orderedGroups.map((target) => (
                            <DropdownMenuItem
                              key={target.slug}
                              disabled={setGroup.isPending || target.slug === current}
                              onClick={() =>
                                setGroup.mutate({ key: row.key, group: target.slug })
                              }
                            >
                              {target.label}
                              {target.slug === current ? (
                                <Check aria-hidden className="ml-auto size-3.5" />
                              ) : null}
                            </DropdownMenuItem>
                          ))}
                          {row.groupSource === "correction" ? (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                disabled={clearGroup.isPending}
                                onClick={() => clearGroup.mutate(row.key)}
                              >
                                <Undo2 aria-hidden className="size-3.5" />
                                Reset to automatic
                              </DropdownMenuItem>
                            </>
                          ) : null}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    );
                  }) : (
                    <span className="text-xs text-muted-foreground">No skills in this group.</span>
                  )}
```

Note: `orderedGroups` and `known` are computed before the accordion renders — move both computations above the `return` if they aren't already in scope where members render. Update the panel's description copy to: `Profile skills grouped by their primary professional use. Click a skill to move it; corrections are pinned and survive profile rebuilds.`

- [ ] **Step 5: Run tests, lint, and typecheck**

Run: `cd web && npx vitest run src/features/settings/SkillGroupsPanel.test.tsx && npx vitest run && npm run lint && npx tsc -b`
Expected: all Vitest suites pass, ESLint clean, tsc clean (the regenerated `contracts/ts/api.ts` from Task 4 provides the new paths and `groupSource`).

- [ ] **Step 6: Commit**

```bash
git add web/src/features/settings/use-matrix.ts web/src/features/settings/SkillGroupsPanel.tsx web/src/features/settings/SkillGroupsPanel.test.tsx
git commit -m "feat: editable skill groups with pinned corrections in settings panel"
```

---

### Task 6: Document the invariant

**Files:**
- Modify: `CLAUDE.md` (the "Skill groups are a derived display axis" bullet in Known design notes)

**Interfaces:** none (docs only).

- [ ] **Step 1: Amend the design note**

In `CLAUDE.md`, extend the "Skill groups are a derived display axis." bullet — after the sentence about `overrides.yaml`'s `group:` map, insert:

```
User re-categorizations from Settings > Skill groups live in
`data/profile/group_corrections.json` (`profile/group_corrections.py`), win over
both `overrides.yaml` and the taxonomy, and are replayed by
`decorate_matrix_groups` on every matrix rebuild — the LLM classifier never
writes or reads them. `MatrixRow.group_source` records which layer
(correction/override/taxonomy) assigned each row's group.
```

- [ ] **Step 2: Run the full suites one final time**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check && cd web && npx vitest run && npm run lint`
Expected: everything green.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record group-corrections ledger invariant"
```
