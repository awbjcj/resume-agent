# Effective Taxonomy Read Contract Implementation Plan (UCCM Phase 0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every consumer read one immutable, corrections-aware effective taxonomy through a single seam, so a user's taxonomy correction can never be visible to one code path and invisible to another.

**Architecture:** A frozen `EffectiveTaxonomy` dataclass in `taxonomy/snapshot.py` holds the fully-resolved cluster map plus two hashes — `semantic_revision` (the freshness key, computed over the _effective projection_) and `projection_revision` (display-only) — with per-component hashes kept in a `TaxonomyManifest` for traceability but never compared. A pure `from_parts()` classmethod is the single implementation of precedence (generated → corrections → overrides → `forbid_alias` last); an I/O shell `build_effective_taxonomy()` in `profile/effective.py` reads the files. Eleven consumers stop composing the taxonomy themselves and instead receive the frozen object.

**Tech Stack:** Python 3.13, Pydantic v2 (`ExtensibleModel`, `extra="allow"`), SQLModel + hand-rolled idempotent SQLite migrations (no Alembic), pytest, FastAPI, ruff.

## Global Constraints

- **Scope is Phase 0 only.** No graph concepts or edges, no concept typing, no capability assertions, no typed job requirements, no Match Engine v2, no shadow mode, no UCCM six-layer projections, no frontend changes, no gold set, no evaluation gates.
- **No feature flag.** Rollback is `git revert`. Do not add a settings boolean or a mode enum.
- **No import-boundary enforcement test.** Explicitly declined.
- **Additive persistence only.** Every new persisted or API field is new and optional. `SkillMatrix.canonical_map_sha256` keeps being written but is no longer consulted.
- **Precedence is exactly:** generated ClusterMap → `TaxonomyCorrections` → `Overrides.alias` → `Overrides.forbid_alias` applied last and terminal. This inverts today's router order.
- **Semantic vs projection vs manifest:** `ban`, `alias`, `forbid_alias`, the effective ClusterMap, and `retired_skills` **keys only** are semantic. `category` and `group` are projection. `grouping_status` timestamps, `maintenance_due`, `history`, and retirement `reason`/`retired_at` are manifest-only and must never invalidate an artifact.
- **Unknown revision splits by artifact kind:** `matrix.json` is a cache and rebuilds; a `ResumeVersion` row is a record and is kept with `revisionUnknown`.
- **Test command:** `.venv/Scripts/python.exe -m pytest` (offline; no API key, no network). Lint: `ruff check`.
- **Branch:** work on `codex/universal-career-capability-matrix-spec` or a branch from it. `main` is protected.

## File Structure

| File                                                                                             | Responsibility                                                                                                                                                 |
| ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/resume_agent/taxonomy/snapshot.py`                                                          | **Create.** `TaxonomyManifest`, `OverrideConflict`, `OverrideView` protocol, `EffectiveTaxonomy` + pure `from_parts()`. No `profile/` imports.                 |
| `src/resume_agent/taxonomy/custody.py`                                                           | **Modify.** Add per-component hashes to `TaxonomySnapshot`; keep `revision` untouched.                                                                         |
| `src/resume_agent/profile/effective.py`                                                          | **Create.** `build_effective_taxonomy()` — the I/O shell. Only file that knows where the four artifacts live.                                                  |
| `src/resume_agent/profile/matrix.py`                                                             | **Modify.** `build_matrix` / `load_matrix` / `decorate_matrix_groups` take `EffectiveTaxonomy`. `SkillMatrix` gains `taxonomy_revision` + `taxonomy_manifest`. |
| `src/resume_agent/services/profile_build.py`                                                     | **Modify.** Two snapshots (pre- and post-classification), not three raw loads.                                                                                 |
| `src/resume_agent/api/routers/match_gap.py`                                                      | **Modify.** Both `build_match_gap_payload` and `_regenerate_bound_matrix` use one snapshot.                                                                    |
| `src/resume_agent/api/schemas/match_gap.py`                                                      | **Modify.** Additive `taxonomyRevision`, `taxonomyManifest`, `overrideConflicts`.                                                                              |
| `src/resume_agent/services/tailoring.py`, `services/discovery.py`, `services/suggestion_runs.py` | **Modify.** Adopt the snapshot.                                                                                                                                |
| `src/resume_agent/cli.py`, `src/resume_agent/profile/coach.py`                                   | **Modify.** Adopt the snapshot; `is_populated` replaces the local `use_cluster_map` heuristic.                                                                 |
| `src/resume_agent/tracking/tables.py`, `tracking/migrate.py`                                     | **Modify.** `resume_versions` gains two nullable taxonomy columns.                                                                                             |
| `src/resume_agent/api/schemas/jobs.py`                                                           | **Modify.** `ResumeVersionOut.revisionUnknown`.                                                                                                                |
| `tests/test_effective_taxonomy_seam.py`                                                          | **Create.** The cross-path acceptance test.                                                                                                                    |
| `tests/test_taxonomy_snapshot.py`                                                                | **Create.** Precedence, hashing, conflicts.                                                                                                                    |
| `tests/test_profile_effective.py`                                                                | **Create.** I/O shell.                                                                                                                                         |

---

### Task 1: Cross-path acceptance test (xfail, drives the whole phase)

**Files:**

- Test: `tests/test_effective_taxonomy_seam.py` (create)

**Interfaces:**

- Consumes: nothing yet.
- Produces: the executable definition of done. Task 12 removes the `xfail` marker.

**Why this shape:** `TaxonomyCustody.read()` was built for this exact purpose, unit-tested in `tests/test_taxonomy_custody.py:14`, and then bypassed by every consumer including ones written afterward. A passing unit test on the seam proves nothing about adoption — only a cross-path test does. All imports go **inside the test body**: a module-level import of a not-yet-existing symbol is a collection error, which `xfail` cannot catch.

- [ ] **Step 1: Write the failing acceptance test**

```python
"""One fixture, two paths, one answer.

The Phase 0 defect: `build_match_gap_payload` applies taxonomy corrections
(routers/match_gap.py:61) and `_regenerate_bound_matrix` does not (line 108).
Coverage is a join across demand-graph keys and matrix row keys, so a user's
alias correction moves one side of the join and not the other.
"""

from __future__ import annotations

import pytest

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)


def _seed(tmp_path):
    """Facts naming 'js'; a correction aliasing js -> javascript."""
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    save_cluster_map(
        ClusterMap(
            domain_of={"javascript": "web"},
            domain_label={"web": "Web"},
            category_of={"web": "languages"},
        ),
        profile_dir / "cluster_map.json",
    )
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_taxonomy_corrections(
        TaxonomyCorrections(aliases={"js": "javascript"}), corrections_path
    )
    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="js")]})
    return profile_dir, corrections_path, facts


@pytest.mark.xfail(
    strict=True,
    reason="Phase 0 not yet adopted: consumers still compose the taxonomy themselves",
)
def test_matrix_and_match_gap_agree_on_one_correction(tmp_path):
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.profile.matrix import build_matrix

    profile_dir, corrections_path, facts = _seed(tmp_path)
    taxonomy = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)
    matrix = build_matrix(facts, taxonomy)

    # The correction must reach the matrix row key, not only the demand graph.
    assert [row.key for row in matrix.rows] == ["javascript"]
    # Both artifacts pin the same revision.
    assert matrix.taxonomy_revision == taxonomy.semantic_revision
    assert len(taxonomy.semantic_revision) == 64


@pytest.mark.xfail(
    strict=True,
    reason="Phase 0 not yet adopted: timestamps still participate in the hash",
)
def test_regroup_timestamp_does_not_invalidate_the_matrix(tmp_path):
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.taxonomy.state import (
        GroupingStatus,
        TaxonomyState,
        save_taxonomy_state,
    )

    profile_dir, corrections_path, _ = _seed(tmp_path)
    cluster_path = profile_dir / "cluster_map.json"
    before = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)

    save_taxonomy_state(
        TaxonomyState(
            maintenance_due=True,
            grouping_status={
                "rust": GroupingStatus(reason="uncertain", last_attempted_at="2030-01-01T00:00:00+00:00")
            },
        ),
        cluster_path,
    )
    after = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)

    assert after.semantic_revision == before.semantic_revision
    assert after.manifest.state != before.manifest.state
```

- [ ] **Step 2: Run to verify both xfail (not error)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_effective_taxonomy_seam.py -v`
Expected: `2 xfailed`. If you see `errors` instead, an import escaped to module level — move it into the test body.

- [ ] **Step 3: Run the full suite to confirm it stays green**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS, with 2 xfailed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_effective_taxonomy_seam.py
git commit -m "test: add xfail cross-path acceptance test for effective taxonomy seam"
```

---

### Task 2: `EffectiveTaxonomy.from_parts` — precedence, implemented once

**Files:**

- Create: `src/resume_agent/taxonomy/snapshot.py`
- Test: `tests/test_taxonomy_snapshot.py` (create)

**Interfaces:**

- Consumes: `ClusterMap`, `TaxonomyCorrections`, `TaxonomyState` from `taxonomy/`.
- Produces: `EffectiveTaxonomy.from_parts(cluster_map, *, corrections=None, overrides=None, state=None) -> EffectiveTaxonomy`; attributes `cluster_map`, `banned_keys`, `retired_keys`, `category_overrides`, `group_overrides`, `state`, `conflicts`; property `is_populated`. Hashes arrive in Task 3, conflicts in Task 4 — leave `semantic_revision=""`, `projection_revision=""`, `conflicts=()` for now.

**Why a protocol for overrides:** `Overrides` lives in `profile/matrix.py`. The snapshot must not import from `profile/` or the layering inverts. A structural `Protocol` lets `taxonomy/` accept it without depending on it.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

import pytest

from resume_agent.profile.matrix import Overrides
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.corrections import TaxonomyCorrections
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy
from resume_agent.taxonomy.state import RetiredSkill, TaxonomyState


def test_correction_alias_reaches_the_effective_map():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(domain_of={"javascript": "web"}),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
    )
    assert snap.cluster_map.aliases["js"] == "javascript"


def test_override_alias_beats_a_correction_alias():
    """Spec precedence: generated -> corrections -> overrides."""
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "typescript"}),
    )
    assert snap.cluster_map.aliases["js"] == "typescript"


def test_forbid_alias_is_terminal_and_cannot_be_re_merged():
    """The bug this ordering closes: today apply_taxonomy_corrections runs
    AFTER effective_cluster_map and its `combined_aliases.update(...)`
    (corrections.py:184) silently re-merges a pair the profile forbade."""
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(aliases={"js": "javascript"}),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(forbid_alias=[["js", "javascript"]]),
    )
    assert snap.cluster_map.aliases.get("js") != "javascript"


def test_ban_and_retirement_are_exposed_as_semantic_sets():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        overrides=Overrides(ban=["cobol"]),
        state=TaxonomyState(retired_skills={"8 years of ml": RetiredSkill()}),
    )
    assert snap.banned_keys == frozenset({"cobol"})
    assert snap.retired_keys == frozenset({"8 years of ml"})


def test_category_and_group_are_projections_not_identity():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(), overrides=Overrides(category={"rust": "hard"}, group={"rust": "languages"})
    )
    assert snap.category_overrides == {"rust": "hard"}
    assert snap.group_overrides == {"rust": "languages"}


def test_is_populated_replaces_the_use_cluster_map_heuristic():
    assert not EffectiveTaxonomy.from_parts(ClusterMap()).is_populated
    assert EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"})).is_populated


def test_alias_cycle_raises_rather_than_picking_a_winner():
    with pytest.raises(ValueError):
        EffectiveTaxonomy.from_parts(ClusterMap(aliases={"a": "b", "b": "a"}))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.taxonomy.snapshot'`

- [ ] **Step 3: Write the implementation**

```python
"""One immutable, fully-resolved read of a profile's effective taxonomy.

Holds only taxonomy-layer types plus plain collections so it never imports
from ``profile/``.  Precedence lives here and nowhere else.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    apply_taxonomy_corrections,
)
from resume_agent.taxonomy.state import TaxonomyState
from resume_agent.tracking.match_gap import normalize_skill


@runtime_checkable
class OverrideView(Protocol):
    """Structural view of ``profile.matrix.Overrides``.

    Declared here so the taxonomy package can consume profile overrides
    without importing the profile package and inverting the layering.
    """

    alias: dict[str, str]
    forbid_alias: list[list[str]]
    ban: list[str]
    category: dict[str, str]
    group: dict[str, str]


@dataclass(frozen=True)
class TaxonomyManifest:
    """Component hashes for traceability.  NEVER compared for freshness."""

    generated: str = ""
    corrections: str = ""
    state: str = ""
    overrides: str = ""
    semantic: str = ""


@dataclass(frozen=True)
class OverrideConflict:
    """A token where a workspace correction and a profile override disagree."""

    token: str
    correction_head: str
    override_head: str
    resolution: Literal["override", "forbid_alias"]


def _flatten(aliases: dict[str, str]) -> dict[str, str]:
    """Resolve each alias to a terminal token; a cycle is corrupt input."""
    flattened: dict[str, str] = {}
    for start in set(aliases) | set(aliases.values()):
        token, seen = start, set()
        while token in aliases and aliases[token] != token:
            if token in seen:
                raise ValueError(f"alias cycle detected at {token!r}")
            seen.add(token)
            token = aliases[token]
        if start != token:
            flattened[start] = token
    return flattened


@dataclass(frozen=True)
class EffectiveTaxonomy:
    cluster_map: ClusterMap
    banned_keys: frozenset[str] = frozenset()
    retired_keys: frozenset[str] = frozenset()
    category_overrides: Mapping[str, str] = field(default_factory=dict)
    group_overrides: Mapping[str, str] = field(default_factory=dict)
    state: TaxonomyState = field(default_factory=TaxonomyState)
    conflicts: tuple[OverrideConflict, ...] = ()
    semantic_revision: str = ""
    projection_revision: str = ""
    manifest: TaxonomyManifest = field(default_factory=TaxonomyManifest)

    @property
    def is_populated(self) -> bool:
        """Whether a usable taxonomy exists.

        Replaces the ``use_cluster_map`` heuristic that cli.py and coach.py
        each re-derived, so every surface answers the question identically.
        """
        return bool(self.cluster_map.aliases or self.cluster_map.domain_of)

    @classmethod
    def from_parts(
        cls,
        cluster_map: ClusterMap,
        *,
        corrections: TaxonomyCorrections | None = None,
        overrides: OverrideView | None = None,
        state: TaxonomyState | None = None,
    ) -> "EffectiveTaxonomy":
        """Resolve generated -> corrections -> overrides -> forbid_alias.

        Pure: no I/O.  ``profile.effective.build_effective_taxonomy`` is the
        only I/O shell around it.
        """
        corrections = corrections or TaxonomyCorrections()
        state = state or TaxonomyState()

        resolved = apply_taxonomy_corrections(cluster_map, corrections)
        aliases = dict(resolved.aliases)

        if overrides is not None:
            for token, head in overrides.alias.items():
                key, target = normalize_skill(token), normalize_skill(head)
                if key and target:
                    aliases[key] = target

        aliases = _flatten(aliases)

        if overrides is not None:
            for pair in overrides.forbid_alias:
                if len(pair) != 2:
                    continue
                first, second = (normalize_skill(token) for token in pair)
                if not first or not second or first == second:
                    continue
                # Terminal: split in both directions, whatever produced the merge.
                if aliases.get(first) == second:
                    aliases.pop(first, None)
                if aliases.get(second) == first:
                    aliases.pop(second, None)

        domain_of = {
            aliases.get(token, token): domain
            for token, domain in resolved.domain_of.items()
        }
        effective = ClusterMap(
            aliases=aliases,
            domain_of=domain_of,
            domain_label=dict(resolved.domain_label),
            category_of=dict(resolved.category_of),
        )

        banned = frozenset(
            aliases.get(token, token)
            for raw in (overrides.ban if overrides is not None else [])
            if (token := normalize_skill(raw))
        )
        return cls(
            cluster_map=effective,
            banned_keys=banned,
            retired_keys=frozenset(state.retired_skills),
            category_overrides=dict(overrides.category) if overrides else {},
            group_overrides=dict(overrides.group) if overrides else {},
            state=state,
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_snapshot.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/taxonomy/snapshot.py
git add src/resume_agent/taxonomy/snapshot.py tests/test_taxonomy_snapshot.py
git commit -m "feat(taxonomy): add EffectiveTaxonomy with single-source precedence"
```

---

### Task 3: Semantic and projection revisions

**Files:**

- Modify: `src/resume_agent/taxonomy/snapshot.py`
- Test: `tests/test_taxonomy_snapshot.py`

**Interfaces:**

- Consumes: `EffectiveTaxonomy.from_parts` from Task 2.
- Produces: populated `semantic_revision`, `projection_revision`, and `manifest.semantic`. Both are 64-char sha256 hex.

**Why hash the effective projection, not the inputs:** two different correction ledgers that resolve to the same taxonomy produce the same hash, which makes "reordering equivalent serialized input must not change the effective hash" true by construction. It also means an idempotent correction replay does not churn every derived artifact.

- [ ] **Step 1: Write the failing tests**

```python
def test_semantic_revision_ignores_grouping_timestamps_and_history():
    """The live taxonomy_state.json carries 453 grouping_status entries, each
    with a last_attempted_at timestamp.  Clicking Regroup on one skill must
    not invalidate every derived artifact."""
    from resume_agent.taxonomy.state import GroupingStatus, TaxonomyGeneration

    base = ClusterMap(domain_of={"python": "backend"})
    quiet = EffectiveTaxonomy.from_parts(base, state=TaxonomyState())
    noisy = EffectiveTaxonomy.from_parts(
        base,
        state=TaxonomyState(
            maintenance_due=True,
            grouping_status={"rust": GroupingStatus(reason="uncertain")},
            history=[TaxonomyGeneration(id="g1", created_at="2030-01-01", snapshot="s")],
        ),
    )
    assert quiet.semantic_revision == noisy.semantic_revision


def test_retirement_reason_is_manifest_only_but_the_key_is_semantic():
    from resume_agent.taxonomy.state import RetiredSkill

    first = EffectiveTaxonomy.from_parts(
        ClusterMap(), state=TaxonomyState(retired_skills={"x": RetiredSkill(reason="a")})
    )
    reworded = EffectiveTaxonomy.from_parts(
        ClusterMap(), state=TaxonomyState(retired_skills={"x": RetiredSkill(reason="b")})
    )
    added = EffectiveTaxonomy.from_parts(
        ClusterMap(), state=TaxonomyState(retired_skills={"y": RetiredSkill()})
    )
    assert first.semantic_revision == reworded.semantic_revision
    assert first.semantic_revision != added.semantic_revision


def test_ban_is_semantic_because_it_deletes_rows():
    """matrix.py:305 skips row creation for a banned key."""
    plain = EffectiveTaxonomy.from_parts(ClusterMap(domain_of={"cobol": "legacy"}))
    banned = EffectiveTaxonomy.from_parts(
        ClusterMap(domain_of={"cobol": "legacy"}), overrides=Overrides(ban=["cobol"])
    )
    assert plain.semantic_revision != banned.semantic_revision


def test_category_and_group_move_projection_not_semantic():
    """MatrixRow.category is assigned at matrix.py:324/378 and never read
    anywhere in src/ - it exists only to be serialized out."""
    plain = EffectiveTaxonomy.from_parts(ClusterMap(domain_of={"rust": "systems"}))
    styled = EffectiveTaxonomy.from_parts(
        ClusterMap(domain_of={"rust": "systems"}),
        overrides=Overrides(category={"rust": "hard"}, group={"rust": "languages"}),
    )
    assert plain.semantic_revision == styled.semantic_revision
    assert plain.projection_revision != styled.projection_revision


def test_equivalent_inputs_in_different_order_hash_identically():
    a = EffectiveTaxonomy.from_parts(
        ClusterMap(aliases={"py": "python", "js": "javascript"})
    )
    b = EffectiveTaxonomy.from_parts(
        ClusterMap(aliases={"js": "javascript", "py": "python"})
    )
    assert a.semantic_revision == b.semantic_revision


def test_two_ledgers_resolving_to_the_same_taxonomy_hash_identically():
    """Hashing the effective projection, not the inputs, makes idempotent
    correction replay free of artifact churn."""
    direct = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"js": "javascript"}))
    via_correction = EffectiveTaxonomy.from_parts(
        ClusterMap(), corrections=TaxonomyCorrections(aliases={"js": "javascript"})
    )
    assert direct.semantic_revision == via_correction.semantic_revision


def test_revisions_are_sha256_hex_and_echoed_into_the_manifest():
    snap = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"}))
    assert len(snap.semantic_revision) == 64
    assert len(snap.projection_revision) == 64
    assert snap.manifest.semantic == snap.semantic_revision
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_snapshot.py -v`
Expected: FAIL — assertions on empty-string revisions

- [ ] **Step 3: Add the hashing to `snapshot.py`**

Add these imports at the top: `import hashlib`, `import json`, and `from dataclasses import asdict`.

```python
def _digest(payload: object) -> str:
    """Deterministic sha256 over canonical JSON, key order normalized."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _semantic_digest(
    effective: ClusterMap, banned: frozenset[str], retired: frozenset[str]
) -> str:
    """Hash what changes the derived artifact's content.

    Deliberately excludes every timestamp, ``maintenance_due``, ``history``,
    and retirement ``reason``: those are metadata, and letting them
    participate would make one Regroup click invalidate every artifact.
    """
    return _digest(
        {
            "effective": asdict(effective),
            "banned": sorted(banned),
            "retired": sorted(retired),
        }
    )
```

Then, at the end of `from_parts`, replace the bare `return cls(...)` with a version that computes both hashes before constructing:

```python
        semantic = _semantic_digest(effective, banned, frozenset(state.retired_skills))
        projection = _digest(
            {
                "category": dict(overrides.category) if overrides else {},
                "group": dict(overrides.group) if overrides else {},
                "semantic": semantic,
            }
        )
        return cls(
            cluster_map=effective,
            banned_keys=banned,
            retired_keys=frozenset(state.retired_skills),
            category_overrides=dict(overrides.category) if overrides else {},
            group_overrides=dict(overrides.group) if overrides else {},
            state=state,
            semantic_revision=semantic,
            projection_revision=projection,
            manifest=TaxonomyManifest(semantic=semantic),
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_snapshot.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/taxonomy/snapshot.py
git add src/resume_agent/taxonomy/snapshot.py tests/test_taxonomy_snapshot.py
git commit -m "feat(taxonomy): split semantic revision from projection and manifest"
```

---

### Task 4: Override/correction conflict detection

**Files:**

- Modify: `src/resume_agent/taxonomy/snapshot.py`
- Test: `tests/test_taxonomy_snapshot.py`

**Interfaces:**

- Consumes: `from_parts` from Tasks 2–3.
- Produces: populated `EffectiveTaxonomy.conflicts: tuple[OverrideConflict, ...]`, sorted by `token`.

**Why:** overrides now beat corrections, and `overrides.yaml` is hand-authored with no UI while corrections come from the Settings screen. Without surfacing, a stale YAML line silently defeats a correction the user just made and nothing explains why. The parent spec calls for exposing "correction conflicts and obsolete targets as actionable maintenance states."

- [ ] **Step 1: Write the failing tests**

```python
def test_disagreeing_override_and_correction_records_a_conflict():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "typescript"}),
    )
    assert snap.conflicts == (
        OverrideConflict(
            token="js",
            correction_head="javascript",
            override_head="typescript",
            resolution="override",
        ),
    )


def test_agreeing_override_and_correction_is_not_a_conflict():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "javascript"}),
    )
    assert snap.conflicts == ()


def test_forbid_alias_defeating_a_correction_is_recorded_as_such():
    snap = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(forbid_alias=[["js", "javascript"]]),
    )
    assert snap.conflicts == (
        OverrideConflict(
            token="js",
            correction_head="javascript",
            override_head="",
            resolution="forbid_alias",
        ),
    )


def test_conflicts_do_not_participate_in_the_semantic_revision():
    """A conflict is a diagnostic about how the result was reached; the
    result itself is already fully captured by the effective projection."""
    conflicted = EffectiveTaxonomy.from_parts(
        ClusterMap(),
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "typescript"}),
    )
    clean = EffectiveTaxonomy.from_parts(
        ClusterMap(), overrides=Overrides(alias={"js": "typescript"})
    )
    assert conflicted.semantic_revision == clean.semantic_revision
    assert conflicted.conflicts and not clean.conflicts
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_snapshot.py -k conflict -v`
Expected: FAIL — `conflicts` is `()`

- [ ] **Step 3: Add conflict detection to `from_parts`**

Insert after `aliases` has been flattened and `forbid_alias` applied, before building `effective`:

```python
        conflicts: list[OverrideConflict] = []
        if overrides is not None:
            for raw_token, raw_head in corrections.aliases.items():
                token, correction_head = (
                    normalize_skill(raw_token),
                    normalize_skill(raw_head),
                )
                if not token or not correction_head:
                    continue
                override_head = normalize_skill(overrides.alias.get(token, ""))
                if override_head and override_head != correction_head:
                    conflicts.append(
                        OverrideConflict(
                            token=token,
                            correction_head=correction_head,
                            override_head=override_head,
                            resolution="override",
                        )
                    )
                elif aliases.get(token) != correction_head:
                    # The correction was defeated by a forbidden pair.
                    conflicts.append(
                        OverrideConflict(
                            token=token,
                            correction_head=correction_head,
                            override_head="",
                            resolution="forbid_alias",
                        )
                    )
```

Pass `conflicts=tuple(sorted(conflicts, key=lambda item: item.token))` into the `cls(...)` call.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_taxonomy_snapshot.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/taxonomy/snapshot.py
git add src/resume_agent/taxonomy/snapshot.py tests/test_taxonomy_snapshot.py
git commit -m "feat(taxonomy): surface override/correction conflicts on the snapshot"
```

---

### Task 5: `build_effective_taxonomy` — the I/O shell

**Files:**

- Create: `src/resume_agent/profile/effective.py`
- Modify: `src/resume_agent/taxonomy/custody.py`
- Test: `tests/test_profile_effective.py` (create), `tests/test_taxonomy_custody.py`

**Interfaces:**

- Consumes: `EffectiveTaxonomy.from_parts` (Tasks 2–4), `TaxonomyCustody`.
- Produces: `build_effective_taxonomy(profile_dir: str | Path, *, corrections_path: str | Path | None = None) -> EffectiveTaxonomy`, with `manifest.generated/corrections/state/overrides` populated. Also adds `generated_sha256`, `corrections_sha256`, `state_sha256` to `TaxonomySnapshot` (its existing `revision` field is left untouched — `test_taxonomy_custody.py:37` asserts on it).

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from resume_agent.profile.effective import build_effective_taxonomy
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)


def _write(tmp_path, *, aliases=None, corrections=None, overrides_yaml=None):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    save_cluster_map(
        ClusterMap(aliases=aliases or {}, domain_of={"python": "backend"}),
        profile_dir / "cluster_map.json",
    )
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_taxonomy_corrections(corrections or TaxonomyCorrections(), corrections_path)
    if overrides_yaml is not None:
        (profile_dir / "overrides.yaml").write_text(overrides_yaml, encoding="utf-8")
    return profile_dir, corrections_path


def test_reads_all_four_artifacts_into_one_snapshot(tmp_path):
    profile_dir, corrections_path = _write(
        tmp_path,
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides_yaml="ban:\n  - cobol\n",
    )
    snap = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)
    assert snap.cluster_map.aliases["js"] == "javascript"
    assert snap.banned_keys == frozenset({"cobol"})
    assert snap.is_populated


def test_missing_artifacts_degrade_to_an_empty_snapshot(tmp_path):
    empty = tmp_path / "profile"
    empty.mkdir()
    snap = build_effective_taxonomy(empty, corrections_path=tmp_path / "nope.json")
    assert not snap.is_populated
    assert len(snap.semantic_revision) == 64


def test_manifest_records_every_component_hash(tmp_path):
    profile_dir, corrections_path = _write(tmp_path, overrides_yaml="ban:\n  - cobol\n")
    snap = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)
    for component in (
        snap.manifest.generated,
        snap.manifest.corrections,
        snap.manifest.state,
        snap.manifest.overrides,
    ):
        assert len(component) == 64


def test_repeated_builds_are_deterministic(tmp_path):
    profile_dir, corrections_path = _write(tmp_path)
    first = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)
    second = build_effective_taxonomy(profile_dir, corrections_path=corrections_path)
    assert first.semantic_revision == second.semantic_revision
    assert first.manifest == second.manifest
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_effective.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.profile.effective'`

- [ ] **Step 3: Add component hashes to `custody.py`**

Add three fields to `TaxonomySnapshot` (after `revision`), and populate them in `read()`:

```python
    generated_sha256: str = ""
    corrections_sha256: str = ""
    state_sha256: str = ""
```

```python
def _component(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
```

In `read()`, pass:

```python
                generated_sha256=_component(asdict(generated)),
                corrections_sha256=_component(corrections.model_dump(mode="json")),
                state_sha256=_component(state.model_dump(mode="json")),
```

- [ ] **Step 4: Write `profile/effective.py`**

```python
"""The single I/O shell that resolves one profile's effective taxonomy.

Only this module knows where the four inputs live.  Everything downstream
receives the frozen ``EffectiveTaxonomy`` and never re-reads a file, so two
steps in one operation physically cannot see different taxonomies.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from resume_agent.profile.matrix import load_overrides
from resume_agent.taxonomy.corrections import corrections_file_path
from resume_agent.taxonomy.custody import TaxonomyCustody
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy, TaxonomyManifest
from resume_agent.tenancy.storage import resolve_tenant_path


def build_effective_taxonomy(
    profile_dir: str | Path,
    *,
    corrections_path: str | Path | None = None,
) -> EffectiveTaxonomy:
    """Read every taxonomy input for one profile and resolve it exactly once.

    Costs roughly 100 ms on a 7,700-alias map.  Deliberately uncached: build
    once per operation and pass the frozen result down.
    """
    profile_dir = Path(profile_dir)
    cluster_path = profile_dir / "cluster_map.json"
    if corrections_path is None:
        corrections_path = resolve_tenant_path(corrections_file_path())

    snapshot = TaxonomyCustody(cluster_path, corrections_path).read()
    overrides = load_overrides(profile_dir / "overrides.yaml")

    resolved = EffectiveTaxonomy.from_parts(
        snapshot.generated,
        corrections=snapshot.corrections,
        overrides=overrides,
        state=snapshot.state,
    )
    payload = json.dumps(
        overrides.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return replace(
        resolved,
        manifest=TaxonomyManifest(
            generated=snapshot.generated_sha256,
            corrections=snapshot.corrections_sha256,
            state=snapshot.state_sha256,
            overrides=hashlib.sha256(payload).hexdigest(),
            semantic=resolved.semantic_revision,
        ),
    )
```

Add `from dataclasses import replace` to the imports.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_effective.py tests/test_taxonomy_custody.py -v`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/resume_agent/profile/effective.py src/resume_agent/taxonomy/custody.py
git add src/resume_agent/profile/effective.py src/resume_agent/taxonomy/custody.py tests/test_profile_effective.py
git commit -m "feat(profile): add build_effective_taxonomy I/O shell over custody"
```

---

### Task 6: `matrix.py` consumes the snapshot; unknown revision rebuilds

**Files:**

- Modify: `src/resume_agent/profile/matrix.py`
- Test: `tests/test_profile_matrix.py`

**Interfaces:**

- Consumes: `EffectiveTaxonomy`, `build_effective_taxonomy`.
- Produces: `build_matrix(facts, taxonomy: EffectiveTaxonomy, *, today=None)`, `load_matrix(path, facts=None, taxonomy: EffectiveTaxonomy | None = None)`, `decorate_matrix_groups(matrix, profile_dir, taxonomy)`. `SkillMatrix` gains `taxonomy_revision: str = ""` and `taxonomy_manifest: TaxonomyManifestModel | None = None`.

**Migration note for existing call sites:** every `build_matrix(facts, cluster_map, overrides)` becomes `build_matrix(facts, EffectiveTaxonomy.from_parts(cluster_map, overrides=overrides))`. There are 16 call sites across 6 files; tests migrate with that one-line change and need no filesystem fixture.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_matrix_pins_the_semantic_revision():
    from resume_agent.taxonomy.snapshot import EffectiveTaxonomy

    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    taxonomy = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"}))
    matrix = build_matrix(facts, taxonomy)
    assert matrix.taxonomy_revision == taxonomy.semantic_revision
    assert matrix.taxonomy_manifest is not None
    assert [row.key for row in matrix.rows] == ["python"]


def test_load_matrix_rebuilds_a_legacy_matrix_with_no_revision(tmp_path):
    """A cache written before this field existed carries corrections-free
    keys, and its old canonical_map_sha256 reports fresh.  It must not be
    accepted."""
    from resume_agent.taxonomy.snapshot import EffectiveTaxonomy

    path = tmp_path / "matrix.json"
    save_matrix(SkillMatrix(rows=[MatrixRow(key="python", display="Python")]), path)
    taxonomy = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"}))
    assert load_matrix(path, taxonomy=taxonomy) is None


def test_load_matrix_accepts_a_matching_revision(tmp_path):
    from resume_agent.taxonomy.snapshot import EffectiveTaxonomy

    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    taxonomy = EffectiveTaxonomy.from_parts(ClusterMap(aliases={"py": "python"}))
    path = tmp_path / "matrix.json"
    save_matrix(build_matrix(facts, taxonomy), path)
    assert load_matrix(path, taxonomy=taxonomy) is not None


def test_a_regroup_timestamp_does_not_invalidate_a_saved_matrix(tmp_path):
    from resume_agent.taxonomy.snapshot import EffectiveTaxonomy
    from resume_agent.taxonomy.state import GroupingStatus, TaxonomyState

    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    cmap = ClusterMap(aliases={"py": "python"})
    before = EffectiveTaxonomy.from_parts(cmap)
    path = tmp_path / "matrix.json"
    save_matrix(build_matrix(facts, before), path)

    after = EffectiveTaxonomy.from_parts(
        cmap, state=TaxonomyState(grouping_status={"rust": GroupingStatus(reason="uncertain")})
    )
    assert load_matrix(path, taxonomy=after) is not None


def test_a_ban_does_invalidate_a_saved_matrix(tmp_path):
    from resume_agent.taxonomy.snapshot import EffectiveTaxonomy

    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    cmap = ClusterMap(aliases={"py": "python"})
    path = tmp_path / "matrix.json"
    save_matrix(build_matrix(facts, EffectiveTaxonomy.from_parts(cmap)), path)

    banned = EffectiveTaxonomy.from_parts(cmap, overrides=Overrides(ban=["python"]))
    assert load_matrix(path, taxonomy=banned) is None


def test_canonical_map_sha256_is_still_written_for_old_readers():
    from resume_agent.taxonomy.snapshot import EffectiveTaxonomy

    facts = ProfileFacts(contact=Contact(name="A"), skills={"hard": [Skill(name="py")]})
    matrix = build_matrix(facts, EffectiveTaxonomy.from_parts(ClusterMap()))
    assert matrix.canonical_map_sha256
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_matrix.py -v`
Expected: FAIL — `build_matrix()` signature mismatch / `taxonomy_revision` missing

- [ ] **Step 3: Update `matrix.py`**

Add the persisted fields to `SkillMatrix`:

```python
class TaxonomyManifestModel(ExtensibleModel):
    generated: str = ""
    corrections: str = ""
    state: str = ""
    overrides: str = ""
    semantic: str = ""


class SkillMatrix(ExtensibleModel):
    generated_at: str = ""
    facts_sha256: str = ""
    canonical_map_sha256: str = ""
    # "" means a matrix written before this field existed - unknown, not
    # empty.  A cache is regenerable, so unknown means rebuild (a record
    # such as ResumeVersion is kept and flagged instead).
    taxonomy_revision: str = ""
    taxonomy_manifest: TaxonomyManifestModel | None = None
    rows: list[MatrixRow] = Field(default_factory=list)
```

Change `build_matrix` to take the snapshot. Replace its first lines:

```python
def build_matrix(
    facts: ProfileFacts,
    taxonomy: EffectiveTaxonomy,
    *,
    today: date | None = None,
) -> SkillMatrix:
    today = today or datetime.now(timezone.utc).date()
    effective = taxonomy.cluster_map
    aliases = effective.aliases
    banned = taxonomy.banned_keys
    category_overrides = {
        aliases.get(token, token): category
        for value, category in taxonomy.category_overrides.items()
        if (token := normalize_skill(value))
    }
```

Delete the now-dead local `effective = effective_cluster_map(cluster_map, overrides)` and `banned = {...}` blocks. `effective_cluster_map` stays exported — `from_parts` no longer uses it, but removing a public helper is a separate concern and out of scope here.

In the return, add the two new fields:

```python
    return SkillMatrix(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        facts_sha256=facts_sha256(facts),
        canonical_map_sha256=canonical_map_sha256(effective),
        taxonomy_revision=taxonomy.semantic_revision,
        taxonomy_manifest=TaxonomyManifestModel(**asdict(taxonomy.manifest)),
        rows=sorted(rows.values(), key=lambda row: (-row.strength, row.key)),
    )
```

Change `load_matrix` to compare the semantic revision:

```python
def load_matrix(
    path: str | Path,
    facts: ProfileFacts | None = None,
    taxonomy: EffectiveTaxonomy | None = None,
) -> SkillMatrix | None:
    try:
        matrix = SkillMatrix.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if facts is not None and matrix.facts_sha256 != facts_sha256(facts):
        return None
    if taxonomy is not None and matrix.taxonomy_revision != taxonomy.semantic_revision:
        # Covers the legacy "" case: a matrix with no recorded revision is
        # unknown, not current, and a cache is cheap to rebuild.
        return None
    return matrix
```

Change `decorate_matrix_groups` to take the snapshot instead of re-reading:

```python
def decorate_matrix_groups(
    matrix: SkillMatrix, profile_dir: str | Path, taxonomy: EffectiveTaxonomy
) -> None:
    """Apply every skill-group layer through one shared seam."""
    profile_dir = Path(profile_dir)
    group_map = groups_from_cluster_map(taxonomy.cluster_map)
    if not group_map and taxonomy.state.legacy_group_map_sha256 is None:
        group_map = load_group_map(group_map_path(profile_dir))
    corrections = load_group_corrections(corrections_path(profile_dir)).as_map()
    apply_skill_groups(
        matrix, group_map, taxonomy.group_overrides, corrections=corrections
    )
```

`apply_skill_groups` currently takes an `Overrides`; change its third parameter to a `Mapping[str, str]` of group overrides and update its body to use the mapping directly. Update `build_decorated_matrix` and `rebuild_saved_matrix` to build one snapshot via `build_effective_taxonomy(profile_dir)` and thread it through both calls.

- [ ] **Step 4: Migrate the remaining call sites in this file and its tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_profile_matrix.py -v`
Fix each failure by wrapping with `EffectiveTaxonomy.from_parts(cluster_map, overrides=overrides)`.
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/profile/matrix.py
git add src/resume_agent/profile/matrix.py tests/test_profile_matrix.py
git commit -m "feat(profile): build and validate the matrix against one effective taxonomy"
```

---

### Task 7: `profile_build` adopts the snapshot

**Files:**

- Modify: `src/resume_agent/services/profile_build.py:83-118`
- Test: `tests/test_services_profile_build.py`

**Interfaces:**

- Consumes: `build_effective_taxonomy`, the new `build_matrix`/`decorate_matrix_groups`.
- Produces: no new public API. The saved `matrix.json` now carries `taxonomy_revision`.

**Important:** this path needs **two** snapshots, not one. `refresh_clusters` mutates `cluster_map.json` between the preliminary build (line 86) and the final build (line 117). Lines 86 and 100 both run _before_ the mutation and share one snapshot; line 117 runs _after_ and requires a fresh one. Collapsing all three into a single snapshot would silently discard the classification that just ran.

- [ ] **Step 1: Write the failing test**

```python
def test_profile_build_rebinds_the_taxonomy_after_classification(tmp_path, monkeypatch):
    """The final matrix must reflect the cluster map as it exists AFTER
    refresh_clusters mutates it, not the pre-classification snapshot."""
    # ... existing profile-build fixture setup for tmp_path ...
    result = build_profile(...)  # use the harness already in this file
    saved = load_matrix(tmp_path / "profile" / "matrix.json")
    fresh = build_effective_taxonomy(tmp_path / "profile")
    assert saved.taxonomy_revision == fresh.semantic_revision
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_profile_build.py -v`
Expected: FAIL — `taxonomy_revision` is `""`

- [ ] **Step 3: Rewrite the taxonomy section of `build_profile`**

```python
        overrides = load_overrides(Path(profile_dir) / "overrides.yaml")
        cluster_path = Path(profile_dir) / "cluster_map.json"
        # One snapshot for everything before classification.
        pre = build_effective_taxonomy(profile_dir)
        preliminary = build_matrix(facts, pre)

        taxonomy_path = skill_groups.group_map_path(profile_dir)
        legacy_hints = (
            skill_groups.load_group_map(taxonomy_path)
            if pre.state.legacy_group_map_sha256 is None
            else {}
        )
        missing = {
            row.key
            for row in preliminary.rows
            if pre.cluster_map.domain_of.get(
                pre.cluster_map.aliases.get(row.key, row.key)
            )
            is None
        }
        if missing:
            refresh_clusters(
                None,
                canonicalizer=build_incremental_canonicalizer_agent(),
                themer=build_incremental_themer_agent(),
                path=cluster_path,
                demanded_tokens=missing,
                category_hints=legacy_hints,
            )
        mark_legacy_group_map_imported(cluster_path, taxonomy_path)
        # refresh_clusters mutated the map; rebind to a fresh snapshot.
        post = build_effective_taxonomy(profile_dir)
        matrix = build_matrix(facts, post)
        decorate_matrix_groups(matrix, profile_dir, post)
        save_matrix(matrix, Path(facts_out).with_name("matrix.json"))
```

Remove the now-unused `load_cluster_map` and `load_taxonomy_state` imports at line 47-50.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_profile_build.py tests/test_profile_build.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/services/profile_build.py
git add src/resume_agent/services/profile_build.py tests/test_services_profile_build.py
git commit -m "feat(profile-build): bind the build to pre- and post-classification snapshots"
```

---

### Task 8: `match_gap` router — both functions, one snapshot

**Files:**

- Modify: `src/resume_agent/api/routers/match_gap.py:54-115`, `src/resume_agent/api/schemas/match_gap.py`
- Test: `tests/api/test_match_gap_router.py` (or the existing match-gap API test module)

**Interfaces:**

- Consumes: `build_effective_taxonomy`, new `build_matrix`.
- Produces: `MatchGapOut.taxonomyRevision: str`, `MatchGapOut.taxonomyManifest: TaxonomyManifestOut | None`, `MatchGapOut.overrideConflicts: list[OverrideConflictOut]`.

**This is the task that closes the headline defect** — lines 61 and 108 currently disagree.

- [ ] **Step 1: Write the failing test**

```python
def test_payload_and_bound_matrix_share_one_revision(tmp_path, client):
    """routers/match_gap.py:61 applied corrections; line 108 did not."""
    payload = client.get("/api/match-gap").json()
    assert len(payload["taxonomyRevision"]) == 64
    assert payload["taxonomyManifest"]["semantic"] == payload["taxonomyRevision"]

    saved = load_matrix(tmp_path / "profile" / "matrix.json")
    assert saved.taxonomy_revision == payload["taxonomyRevision"]


def test_override_conflicts_are_reported(tmp_path, client):
    # Seed a correction aliasing js -> javascript and an override
    # aliasing js -> typescript, then:
    payload = client.get("/api/match-gap").json()
    assert payload["overrideConflicts"] == [
        {
            "token": "js",
            "correctionHead": "javascript",
            "overrideHead": "typescript",
            "resolution": "override",
        }
    ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api -k match_gap -v`
Expected: FAIL — `KeyError: 'taxonomyRevision'`

- [ ] **Step 3: Add the schema fields**

```python
class TaxonomyManifestOut(CamelModel):
    generated: str = ""
    corrections: str = ""
    state: str = ""
    overrides: str = ""
    semantic: str = ""


class OverrideConflictOut(CamelModel):
    token: str
    correction_head: str
    override_head: str
    resolution: Literal["override", "forbid_alias"]
```

Append to `MatchGapOut`:

```python
    taxonomy_revision: str = ""
    taxonomy_manifest: TaxonomyManifestOut | None = None
    override_conflicts: list[OverrideConflictOut] = Field(default_factory=list)
```

- [ ] **Step 4: Rewrite both router functions to share one snapshot**

```python
def build_match_gap_payload(session: Session) -> MatchGapOut:
    facts = _facts_or_empty()
    facts_path = resolve_tenant_path(_FACTS_PATH)
    profile_dir = facts_path.parent
    taxonomy = build_effective_taxonomy(profile_dir)
    graph = build_demand_graph(
        session,
        facts,
        cluster_map=taxonomy.cluster_map,
        ...  # remaining existing arguments unchanged
    )
    # ... existing payload assembly, then:
    payload.taxonomy_revision = taxonomy.semantic_revision
    payload.taxonomy_manifest = TaxonomyManifestOut(**asdict(taxonomy.manifest))
    payload.override_conflicts = [
        OverrideConflictOut(**asdict(conflict)) for conflict in taxonomy.conflicts
    ]
    return payload


def _regenerate_bound_matrix(facts: ProfileFacts | None, facts_path: Path) -> bool:
    if facts is None:
        return False
    profile_dir = facts_path.parent
    taxonomy = build_effective_taxonomy(profile_dir)
    matrix = build_matrix(facts, taxonomy)
    decorate_matrix_groups(matrix, profile_dir, taxonomy)
    save_matrix(matrix, facts_path.with_name("matrix.json"))
    return True
```

Existing uses of `taxonomy_state` in this function become `taxonomy.state`. Remove the now-unused `load_cluster_map`, `load_taxonomy_corrections`, `load_taxonomy_state`, `apply_taxonomy_corrections`, `effective_cluster_map`, and `load_overrides` imports.

- [ ] **Step 5: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/api -k match_gap -v`
Expected: PASS

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/resume_agent/api/routers/match_gap.py src/resume_agent/api/schemas/match_gap.py
git add src/resume_agent/api/routers/match_gap.py src/resume_agent/api/schemas/match_gap.py tests/api
git commit -m "fix(match-gap): payload and bound matrix now share one effective taxonomy"
```

---

### Task 9: `tailoring`, `discovery`, and `suggestion_runs` adopt the snapshot

**Files:**

- Modify: `src/resume_agent/services/tailoring.py:66-73`, `src/resume_agent/services/discovery.py:244-254`, `src/resume_agent/services/suggestion_runs.py:42-53`
- Test: `tests/test_services_tailoring.py`, `tests/test_services_match_gap.py`

**Interfaces:**

- Consumes: `build_effective_taxonomy`, new `load_matrix(path, facts=..., taxonomy=...)`.
- Produces: no new public API.

**Why these three together:** `tailoring` and `discovery` apply overrides but never load `taxonomy_corrections.json` at all, so a correction is invisible to both today. `suggestion_runs` applies corrections but not overrides. All three are the same one-line fix and share a review.

- [ ] **Step 1: Write the failing test**

```python
def test_tailoring_sees_a_taxonomy_correction(tmp_path):
    """services/tailoring.py:68 never loaded the correction ledger."""
    save_taxonomy_corrections(
        TaxonomyCorrections(aliases={"js": "javascript"}),
        tmp_path / "taxonomy" / "taxonomy_corrections.json",
    )
    taxonomy = build_effective_taxonomy(tmp_path / "profile")
    assert taxonomy.cluster_map.aliases["js"] == "javascript"
    # And the matrix bound by the tailoring path agrees:
    matrix = build_matrix(facts, taxonomy)
    assert "js" not in [row.key for row in matrix.rows]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_tailoring.py -v`
Expected: FAIL

- [ ] **Step 3: Replace the composition in all three files**

In `services/tailoring.py`:

```python
    profile_dir = resolve_tenant_path(facts_path).parent
    taxonomy = build_effective_taxonomy(profile_dir)
    matrix_facts = facts if isinstance(facts, ProfileFacts) else None
    skill_matrix = load_matrix(
        profile_dir / "matrix.json", facts=matrix_facts, taxonomy=taxonomy
    )
```

In `services/discovery.py`:

```python
def _skill_artifacts(
    facts_path: str, facts: ProfileFacts
) -> tuple[SkillMatrix | None, ClusterMap]:
    profile_dir = resolve_tenant_path(facts_path).parent
    taxonomy = build_effective_taxonomy(profile_dir)
    matrix = load_matrix(profile_dir / "matrix.json", facts=facts, taxonomy=taxonomy)
    return matrix, taxonomy.cluster_map
```

In `services/suggestion_runs.py`, replace the inline `apply_taxonomy_corrections(load_cluster_map(cluster_path), corrections)` with `build_effective_taxonomy(cluster_path.parent).cluster_map`, keeping the separate `corrections=corrections` argument to `build_demand_graph` as-is.

Remove now-unused imports from all three files.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_tailoring.py tests/test_services_match_gap.py tests/test_tailoring.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/services/tailoring.py src/resume_agent/services/discovery.py src/resume_agent/services/suggestion_runs.py
git add src/resume_agent/services tests/test_services_tailoring.py tests/test_services_match_gap.py
git commit -m "fix(services): tailoring, discovery, and suggestions read corrections"
```

---

### Task 10: `cli.py` and `coach.py` adopt the snapshot and drop the local heuristic

**Files:**

- Modify: `src/resume_agent/cli.py:1182-1195`, `src/resume_agent/profile/coach.py:266-282`
- Test: `tests/test_cli_match_gap.py`

**Interfaces:**

- Consumes: `build_effective_taxonomy`, `EffectiveTaxonomy.is_populated`.
- Produces: no new public API.

**Why:** both call `tracking.match_gap()` with a corrections-free map while the API calls `build_demand_graph()` with a corrections-applied one — three surfaces, three answers, one question. Both also re-derive `bool(cluster_map.aliases or cluster_map.domain_of)` locally; that becomes `taxonomy.is_populated` so every surface answers identically.

- [ ] **Step 1: Write the failing test**

```python
def test_cli_match_gap_honours_a_taxonomy_correction(tmp_path, capsys):
    """cli.py:1188 never loaded the correction ledger, so the CLI and the
    API disagreed about the same report."""
    save_taxonomy_corrections(
        TaxonomyCorrections(aliases={"js": "javascript"}),
        tmp_path / "taxonomy" / "taxonomy_corrections.json",
    )
    # ... invoke the CLI match-gap command against tmp_path ...
    assert "js" not in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_match_gap.py -v`
Expected: FAIL

- [ ] **Step 3: Replace both compositions**

In `cli.py` (keep the import inside the function — it is deferred for startup cost, and `profile/effective.py` is cheap to import):

```python
    from resume_agent.profile.effective import build_effective_taxonomy

    profile_facts = load_facts(facts)
    profile_dir = _tenant_cli_path(facts).parent
    taxonomy = build_effective_taxonomy(profile_dir)
    use_cluster_map = taxonomy.is_populated
    cluster_map = taxonomy.cluster_map
    canonicalizer = build_skill_canonicalizer() if llm and not use_cluster_map else None
```

In `coach.py::_market_gaps_report`:

```python
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.tracking.match_gap import match_gap

    facts_path = profile_dir / "facts.json"
    if not facts_path.exists():
        return None
    taxonomy = build_effective_taxonomy(profile_dir)
    use_map = taxonomy.is_populated
    return match_gap(session, load_facts(facts_path), ...)  # pass taxonomy.cluster_map
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_match_gap.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/cli.py src/resume_agent/profile/coach.py
git add src/resume_agent/cli.py src/resume_agent/profile/coach.py tests/test_cli_match_gap.py
git commit -m "fix(cli,coach): read the shared effective taxonomy for match-gap reports"
```

---

### Task 11: `resume_versions` taxonomy provenance

**Files:**

- Modify: `src/resume_agent/tracking/tables.py:69-103`, `src/resume_agent/tracking/migrate.py`, `src/resume_agent/api/schemas/jobs.py:116-136`, the tailoring write site
- Test: `tests/test_tracking_migrate.py`, `tests/test_tailor_service.py`

**Interfaces:**

- Consumes: `EffectiveTaxonomy.semantic_revision` and `.manifest`.
- Produces: `ResumeVersion.taxonomy_revision: str | None`, `ResumeVersion.taxonomy_manifest_json: dict | None`, `ensure_resume_version_taxonomy_columns(engine)`, `ResumeVersionOut.revision_unknown: bool`.

**Naming:** `ensure_resume_version_revision_columns` already exists at `migrate.py:221` and means _resume lineage_ (`origin`, `instruction`, `parent_version_id`). The new migration must be named `ensure_resume_version_taxonomy_columns` or the next reader will conflate them.

**A record, not a cache:** old rows keep `None` and are reported `revisionUnknown: true`. They are never backfilled — the parent spec lists rewriting history as out of scope, and the taxonomy that produced them no longer exists.

- [ ] **Step 1: Write the failing tests**

```python
def test_migration_is_idempotent(engine):
    ensure_resume_version_taxonomy_columns(engine)
    ensure_resume_version_taxonomy_columns(engine)
    cols = _table_columns(engine, "resume_versions")
    assert "taxonomy_revision" in cols
    assert "taxonomy_manifest_json" in cols


def test_a_new_resume_version_records_the_revision(session, tmp_path):
    taxonomy = build_effective_taxonomy(tmp_path / "profile")
    version = tailor_one_job(...)  # existing harness
    assert version.taxonomy_revision == taxonomy.semantic_revision


def test_a_pre_existing_row_is_reported_revision_unknown():
    out = ResumeVersionOut.model_validate(
        {"id": 1, "jobId": 1, "round": 0, "reviewScore": None,
         "factCheckPassed": False, "pdfPath": None, "critiqueJson": None,
         "createdAt": "2026-01-01T00:00:00Z", "taxonomyRevision": None}
    )
    assert out.revision_unknown is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_migrate.py -v`
Expected: FAIL — `ensure_resume_version_taxonomy_columns` not defined

- [ ] **Step 3: Add the columns, migration, and schema field**

In `tables.py`, on `ResumeVersion`:

```python
    # None means "written before this column existed" - unknown, not empty.
    # A resume version is a record of an attempt, so it is never backfilled:
    # the taxonomy that produced it has moved on and cannot be reconstructed.
    taxonomy_revision: str | None = None
    taxonomy_manifest_json: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
```

In `migrate.py`:

```python
def ensure_resume_version_taxonomy_columns(engine: Engine) -> None:
    """Idempotently add taxonomy provenance columns to ``resume_versions``.

    Distinct from ``ensure_resume_version_revision_columns`` above, which adds
    *resume lineage* (origin/instruction/parent), not taxonomy provenance.
    """
    cols = _table_columns(engine, "resume_versions")
    if not cols:
        return
    with engine.begin() as conn:
        if "taxonomy_revision" not in cols:
            conn.execute(
                text("ALTER TABLE resume_versions ADD COLUMN taxonomy_revision VARCHAR")
            )
        if "taxonomy_manifest_json" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE resume_versions "
                    "ADD COLUMN taxonomy_manifest_json JSON"
                )
            )
```

Register the call wherever the other `ensure_*` functions run at startup.

In `api/schemas/jobs.py`, on `ResumeVersionOut`:

```python
    taxonomy_revision: str | None = Field(default=None, exclude=True)
    revision_unknown: bool = True

    @model_validator(mode="after")
    def _derive_revision_unknown(self) -> "ResumeVersionOut":
        self.revision_unknown = self.taxonomy_revision is None
        return self
```

At the tailoring write site, set `taxonomy_revision=taxonomy.semantic_revision` and `taxonomy_manifest_json=asdict(taxonomy.manifest)` on the new `ResumeVersion`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_migrate.py tests/test_tailor_service.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

```bash
ruff check src/resume_agent/tracking src/resume_agent/api/schemas/jobs.py
git add src/resume_agent/tracking src/resume_agent/api/schemas/jobs.py tests/test_tracking_migrate.py
git commit -m "feat(tracking): record taxonomy provenance on new resume versions"
```

---

### Task 12: Regenerate contracts and retire the xfail

**Files:**

- Modify: `tests/test_effective_taxonomy_seam.py`, generated OpenAPI + TypeScript contract files
- Test: the whole suite

**Interfaces:**

- Consumes: everything from Tasks 2–11.
- Produces: a green acceptance test and regenerated frontend contracts.

- [ ] **Step 1: Regenerate the contracts**

Run the repo's existing contract regeneration command (the OpenAPI drift test names it on failure). Confirm the diff is purely additive: `taxonomyRevision`, `taxonomyManifest`, `overrideConflicts`, `revisionUnknown` — and that no existing field changed name, type, or optionality.

- [ ] **Step 2: Remove the xfail markers**

Delete both `@pytest.mark.xfail(...)` decorators in `tests/test_effective_taxonomy_seam.py`.

- [ ] **Step 3: Run the acceptance test**

Run: `.venv/Scripts/python.exe -m pytest tests/test_effective_taxonomy_seam.py -v`
Expected: PASS (2 tests). If either still fails, a consumer was missed — do not re-add the marker.

- [ ] **Step 4: Run the full suite and lint**

Run: `.venv/Scripts/python.exe -m pytest -q` then `ruff check`
Expected: PASS, zero xfailed, zero xpassed.

- [ ] **Step 5: Verify the frontend suite**

Run the web test command from `web/`.
Expected: PASS — the added fields are optional and no existing field changed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(taxonomy): adopt the effective read contract across all consumers"
```

---

## Self-Review

**Spec coverage.** Each of the twelve grilled decisions maps to a task: scope (global constraints), revision split (Task 3), two-layer compose (Tasks 2 + 5), `ban` semantic (Task 3), accepted behavior change (Tasks 8–10), precedence (Task 2), all eleven sites (Tasks 6–10), no cache (Task 5), unknown-revision split (Tasks 6 + 11), `resume_versions` columns (Task 11), xfail-first (Tasks 1 + 12), no flag (global constraints).

**Known gaps the implementer must resolve locally, not guess at.** Three test bodies reference existing fixtures by shape rather than by exact code, because the harnesses live in files this plan does not reproduce: Task 7's `build_profile` fixture, Task 8's `client` fixture, and Task 11's `tailor_one_job` harness. Use the existing setup in each named test module; do not invent a new fixture. Task 12's contract regeneration command is likewise named by the repo's own drift test rather than hard-coded here, since pinning a possibly-stale command would be worse than reading the live one.

**Type consistency.** `EffectiveTaxonomy`, `TaxonomyManifest`, `OverrideConflict`, `OverrideView`, `build_effective_taxonomy`, `from_parts`, `is_populated`, `semantic_revision`, `projection_revision`, `taxonomy_revision`, `taxonomy_manifest`, `ensure_resume_version_taxonomy_columns`, `revision_unknown` are used identically in every task that references them.

**Ordering.** Tasks 2–5 build the seam with no consumer changes, so the suite stays green. Tasks 6–11 adopt it one area at a time, each independently reviewable and independently green. Task 1's acceptance test is `xfail(strict=True)` throughout, so if adoption completes early the suite _fails_

- [ ] **Step 5: Verify the frontend suite**

Run the web test command from `web/`.
Expected: PASS — the added fields are optional and no existing field changed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(taxonomy): adopt the effective read contract across all consumers"
```

---

## Self-Review

**Spec coverage.** Each of the twelve grilled decisions maps to a task: scope (global constraints), revision split (Task 3), two-layer compose (Tasks 2 + 5), `ban` semantic (Task 3), accepted behavior change (Tasks 8–10), precedence (Task 2), all eleven sites (Tasks 6–10), no cache (Task 5), unknown-revision split (Tasks 6 + 11), `resume_versions` columns (Task 11), xfail-first (Tasks 1 + 12), no flag (global constraints).

**Known gaps the implementer must resolve locally, not guess at.** Three test bodies reference existing fixtures by shape rather than by exact code, because the harnesses live in files this plan does not reproduce: Task 7's `build_profile` fixture, Task 8's `client` fixture, and Task 11's `tailor_one_job` harness. Use the existing setup in each named test module; do not invent a new fixture. Task 12's contract regeneration command is likewise named by the repo's own drift test rather than hard-coded here, since pinning a possibly-stale command would be worse than reading the live one.

**Type consistency.** `EffectiveTaxonomy`, `TaxonomyManifest`, `OverrideConflict`, `OverrideView`, `build_effective_taxonomy`, `from_parts`, `is_populated`, `semantic_revision`, `projection_revision`, `taxonomy_revision`, `taxonomy_manifest`, `ensure_resume_version_taxonomy_columns`, `revision_unknown` are used identically in every task that references them.

**Ordering.** Tasks 2–5 build the seam with no consumer changes, so the suite stays green. Tasks 6–11 adopt it one area at a time, each independently reviewable and independently green. Task 1's acceptance test is `xfail(strict=True)` throughout, so if adoption completes early the suite *fails* on an unexpected pass rather than hiding a stale marker.
