# Effective Taxonomy Read Contract — Interface Design (UCCM Phase 0)

**Date:** 2026-08-19
**Status:** Designed, ready for implementation
**Parent spec:** `2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md` (Phase 0 only)
**Scope:** The single effective-taxonomy read seam. No graph, no typed concepts, no assertions, no Match Engine v2, no UCCM layers.

---

## 1. The defect this seam removes

Eleven read sites compose the taxonomy four different ways:

| Composition                   | Sites                                                                                           |
| ----------------------------- | ----------------------------------------------------------------------------------------------- |
| raw only                      | `profile/matrix.py:465`, `services/profile_build.py:86/100/117`, `api/routers/match_gap.py:110` |
| raw + overrides               | `services/tailoring.py:68`, `services/discovery.py:249`, `profile/coach.py:276`, `cli.py:1188`  |
| raw + corrections             | `profile/matrix.py:443` (group axis only), `services/suggestion_runs.py:49`                     |
| raw + overrides + corrections | `api/routers/match_gap.py:63`                                                                   |

Two of them are in the same router file and feed the same screen. `build_match_gap_payload` applies corrections; `_regenerate_bound_matrix` does not. Coverage is a join across demand-graph keys and matrix row keys, so a user alias correction moves one side of the join and not the other, and a covered skill renders as a gap.

The freshness gate cannot catch it: `build_matrix` writes `canonical_map_sha256` over a corrections-free map (`matrix.py:395`), and `load_matrix` compares corrections-free against corrections-free (`matrix.py:515`). The stale artifact reports fresh.

`TaxonomyCustody.read()` was built for exactly this, is unit-tested (`test_taxonomy_custody.py:14`), and has zero production callers.

---

## 2. Contract

### 2.1 `EffectiveTaxonomy` — the frozen snapshot

Lives in `src/resume_agent/taxonomy/snapshot.py`. Holds only taxonomy-layer types plus plain collections, so it never imports from `profile/`.

```python
@dataclass(frozen=True)
class TaxonomyManifest:
    """Component hashes recorded for traceability. NEVER compared for freshness."""

    generated: str        # sha256 of the raw ClusterMap
    corrections: str      # sha256 of the TaxonomyCorrections ledger
    state: str            # sha256 of TaxonomyState, timestamps included
    overrides: str        # sha256 of the profile Overrides document
    semantic: str         # echo of EffectiveTaxonomy.semantic_revision


@dataclass(frozen=True)
class OverrideConflict:
    """A token where a workspace correction and a profile override disagree."""

    token: str
    correction_head: str
    override_head: str
    resolution: Literal["override", "forbid_alias"]


@dataclass(frozen=True)
class EffectiveTaxonomy:
    # Fully resolved: generated -> corrections -> overrides -> forbid_alias last
    cluster_map: ClusterMap

    # Semantic projections (participate in semantic_revision)
    banned_keys: frozenset[str]
    retired_keys: frozenset[str]

    # Display projections (participate in projection_revision only)
    category_overrides: Mapping[str, str]
    group_overrides: Mapping[str, str]

    state: TaxonomyState
    conflicts: tuple[OverrideConflict, ...]

    semantic_revision: str      # freshness key
    projection_revision: str    # display-layer key
    manifest: TaxonomyManifest

    @property
    def is_populated(self) -> bool:
        """Replaces the hand-rolled `use_cluster_map` heuristic in cli.py/coach.py."""
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
        """Pure construction. No I/O. The only place precedence is implemented."""
```

`OverrideView` is a small structural protocol (`alias`, `forbid_alias`, `ban`, `category`, `group`) that `profile.matrix.Overrides` satisfies without the taxonomy package importing it.

**Why `from_parts` is public:** it keeps the precedence rule in exactly one place while letting tests build a snapshot without touching the filesystem. Pure core, I/O shell.

### 2.2 `build_effective_taxonomy` — the I/O shell

Lives in `src/resume_agent/profile/effective.py`. Layering stays `profile → taxonomy`.

```python
def build_effective_taxonomy(
    profile_dir: str | Path,
    *,
    corrections_path: str | Path | None = None,
) -> EffectiveTaxonomy:
    """Read every taxonomy input for one profile and resolve it once.

    Reads cluster_map.json + taxonomy_state.json under the custody lock, then
    folds in the profile's overrides.yaml. `corrections_path` defaults to the
    tenant-resolved `corrections_file_path()`.
    """
```

Measured cost on the live 7,723-alias map: ~100 ms. No cache — callers build once per operation and pass the frozen object down. Two steps in one build physically cannot see different taxonomies if they hold the same object.

### 2.3 Precedence — implemented once, in `from_parts`

```
generated ClusterMap
  -> apply TaxonomyCorrections   (workspace scope; corrections.aliases update generated)
  -> apply Overrides.alias        (profile scope; wins over corrections)
  -> apply Overrides.forbid_alias (terminal; splits any pair, wins over everything)
```

This inverts today's router order, where `apply_taxonomy_corrections` runs _after_ `effective_cluster_map` and its `combined_aliases.update(corrections.aliases)` (`corrections.py:184`) can silently re-merge a pair the profile forbade. Under the new order a forbidden pair can never be re-merged.

Where an override and a correction name the same token with different heads, the override wins **and** an `OverrideConflict` is recorded. Conflicts are surfaced, never silently resolved.

### 2.4 Revision split

| Input                                                      | Semantic | Projection | Manifest only |
| ---------------------------------------------------------- | -------- | ---------- | ------------- |
| Effective `ClusterMap` (post-precedence)                   | yes      |            |               |
| `Overrides.alias`, `forbid_alias`                          | yes      |            |               |
| `Overrides.ban`                                            | yes      |            |               |
| `TaxonomyState.retired_skills` **keys only**               | yes      |            |               |
| `Overrides.category`, `Overrides.group`                    |          | yes        |               |
| `grouping_status` timestamps, `maintenance_due`, `history` |          |            | yes           |
| `retired_skills` `reason` / `retired_at`                   |          |            | yes           |

`semantic_revision` is computed over the **effective projection**, not over the inputs. Two different correction ledgers that resolve to the same taxonomy therefore produce the same hash, which makes "reordering equivalent serialized input must not change the effective hash" true by construction rather than by hand-engineering.

`retired_skills` hashed by key set only: an edited retirement reason is display text and must not invalidate every derived artifact.

**Rule:** content-changing inputs are semantic; display-only inputs are projection; timestamps and history are manifest. `ban` is semantic because it deletes rows (`matrix.py:305`). `category` is projection because it is write-only in the backend — assigned at `matrix.py:324`/`378` and never read anywhere in `src/`.

### 2.5 Freshness — unknown revision splits by artifact kind

| Artifact            | Kind                                      | On absent `taxonomy_revision`    |
| ------------------- | ----------------------------------------- | -------------------------------- |
| `matrix.json`       | cache — regenerable from facts + taxonomy | **rebuild**                      |
| `ResumeVersion` row | record — a historical attempt             | **keep, flag `revisionUnknown`** |

Rewriting a historical resume version would fabricate a revision that was never used; the parent spec lists that as out of scope. Rebuilding a cache costs nothing and is the only way Phase 0's key change actually lands, since the stale hash reports fresh.

This also delivers the one-time forced invalidation by an explicit rule rather than by hash-mismatch coincidence.

### 2.6 Changed signatures

```python
# profile/matrix.py — receives a snapshot, never builds one
def build_matrix(facts: ProfileFacts, taxonomy: EffectiveTaxonomy, *, today=None) -> SkillMatrix
def load_matrix(path, facts=None, taxonomy: EffectiveTaxonomy | None = None) -> SkillMatrix | None
def decorate_matrix_groups(matrix: SkillMatrix, profile_dir, taxonomy: EffectiveTaxonomy) -> None
```

16 `build_matrix(` call sites across 6 files. Test call sites migrate with `EffectiveTaxonomy.from_parts(cluster_map, overrides=overrides)` — a one-line change, no filesystem fixture.

`canonical_map_sha256` keeps being written on `SkillMatrix` for compatibility with any old reader, but is no longer consulted by `load_matrix`.

### 2.7 Persisted fields — additive only

`SkillMatrix` (`ExtensibleModel`, `extra="allow"`, so both directions round-trip without loss):

```python
taxonomy_revision: str = ""                        # semantic; "" means legacy -> rebuild
taxonomy_manifest: TaxonomyManifestModel | None = None
```

`resume_versions` table — one `PRAGMA`-guarded idempotent migration named `ensure_resume_version_taxonomy_columns`, deliberately distinct from the existing `ensure_resume_version_revision_columns` (`migrate.py:221`), which means _resume lineage_, not taxonomy:

```python
taxonomy_revision: str | None = None                    # None = written before the column existed
taxonomy_manifest_json: dict | None = Column(JSON)
```

Written on new rows only. Never backfilled — provenance cannot be reconstructed once the taxonomy moves on, which is the whole reason it lands in Phase 0 rather than later.

### 2.8 API surface — additive, no new endpoints

`MatchGapOut` gains:

```python
taxonomy_revision: str = ""
taxonomy_manifest: TaxonomyManifestOut | None = None
override_conflicts: list[OverrideConflictOut] = Field(default_factory=list)
```

`ResumeVersionOut` gains:

```python
revision_unknown: bool = True   # derived from taxonomy_revision is None
```

Every existing field keeps its name, type, and meaning. No endpoint is added, removed, or renamed. OpenAPI + TypeScript contracts regenerate; the existing drift gate covers it.

### 2.9 Error semantics

The seam does not introduce new failure modes. A missing or unparseable input degrades exactly as today — `load_cluster_map`, `load_taxonomy_corrections`, and `load_overrides` each already return an empty document on `OSError`/parse failure. A snapshot built from empty inputs is valid, has `is_populated == False`, and carries the hash of the empty projection.

The one new invariant: `from_parts` raises `ValueError` on an alias cycle, matching `_flatten_aliases`' existing behaviour (`matrix.py:116`). A cycle is a corrupt input, not a degraded one, and must not be resolved by picking an arbitrary winner.

---

## 3. Design rules this follows

- **Contract first.** `EffectiveTaxonomy` is defined before any consumer is touched; the eleven adoptions are mechanical once it exists.
- **Prefer addition over modification.** Every persisted and API field is new and optional. `canonical_map_sha256` is retained though unused.
- **Validate at boundaries.** No new validation inside the seam; the loaders already own it.
- **One version.** No flag, no second read path. The parent spec explicitly warns against creating a second taxonomy read path, and a flag would preserve the divergence this phase removes.
- **Don't leak implementation detail.** Consumers see a resolved `ClusterMap` and two opaque revision strings. They never see the precedence order, which is what lets it change in a later phase without touching eleven call sites.

## 4. Out of scope

Graph concepts and edges, concept typing, capability assertions, typed job requirements, Match Engine v2 and shadow mode, UCCM six-layer projections, frontend changes, the cross-industry gold set and evaluation gates, external framework imports, `manual_skills.json` (facts-side, unrelated), and any import-boundary enforcement test.
