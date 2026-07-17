# Skill-Group Re-categorization — Design

**Date:** 2026-07-16
**Status:** Approved

## Problem

Skill-group assignments (the 13-slug display axis: Languages, Data & ML, …) are made
once by the cheap-tier LLM classifier and frozen in `data/taxonomy/skill_groups.json`.
`save_group_map` merges first-writer-wins and `classify_missing_groups` only classifies
tokens *missing* from the cache, so a wrong guess is permanent. The only correction path
today is hand-editing `data/profile/overrides.yaml`'s `group:` map on disk — no UI, no
API, no way to enumerate or revert corrections.

## Decisions (from brainstorming)

1. **Scope: groups only.** The hard/soft/domain `category` axis is untouched; fact-lock
   and match-plan behavior are unaffected.
2. **Surface: Web UI + API.** No CLI command.
3. **Reach: pin corrected tokens only.** A correction permanently fixes that exact
   canonical token across all future rebuilds. New, never-seen tokens are still
   classified fresh by the LLM; corrections are *not* injected as few-shot examples.
4. **Storage: a dedicated corrections ledger** (Approach A), not programmatic
   `overrides.yaml` writes (comment/format-destroying YAML round-trips) and not direct
   `skill_groups.json` mutation (corrections would vanish on cache reset and be
   indistinguishable from LLM guesses).

## Correctness amendments (implementation audit)

- Alias-aware precedence is symmetric: correction, override, and taxonomy maps are all
  checked against the canonical key, normalized display, and normalized aliases.
- Service validation is side-effect-free. Unknown groups/skills and missing corrections
  are rejected before either the ledger or `matrix.json` is written.
- API contract regeneration includes the SPA's committed
  `web/src/lib/api/schema.ts` copy in addition to the canonical OpenAPI and TypeScript
  artifacts.
- The installed shadcn stack uses Base UI, so editable badges use a `render` trigger,
  grouped menu items, component icon conventions, and keyboard-accessible menu behavior.
- Mutation success awaits matrix-query invalidation so a successful move/reset is not
  reported while stale grouping remains visible.
- `other` is the explicit Other group. It is not a null/ungroup operation; reset means
  deleting the correction and falling back to override/taxonomy.

## Design

### 1. Storage — corrections ledger

New file `data/profile/group_corrections.json` (profile-scoped, beside
`manual_skills.json`), managed by a new module
`src/resume_agent/profile/group_corrections.py`:

```json
{
  "corrections": {
    "dbt": { "group": "data-ml", "corrected_at": "2026-07-16T12:00:00+00:00" }
  }
}
```

- Keys are canonical tokens (`normalize_skill`-normalized). Values carry a group slug
  validated against the fixed `SKILL_GROUPS` vocabulary plus an ISO timestamp.
- Load/save follow the existing atomic-write pattern (`tempfile.NamedTemporaryFile` +
  `os.fsync` + `os.replace`, as in `save_group_map`). Missing or corrupt file loads as
  empty corrections, never an error. Entries with unknown slugs or empty tokens are
  dropped on load (same sanitize discipline as `sanitize_group_map`).
- The ledger is user truth: the LLM classifier and profile rebuilds never write it.
  Deleting `data/taxonomy/skill_groups.json` or re-running `profile build` cannot lose
  a correction.

### 2. Precedence — `apply_skill_groups` + shared decorate helper

`apply_skill_groups(matrix, group_of, overrides)` gains a `corrections` parameter.
Per-row lookup order, each layer checked against `row.key`, normalized `row.display`,
and normalized aliases (same lookup the override map uses today):

**correction ledger > `overrides.yaml` `group:` map > LLM taxonomy**

Rationale for corrections beating `overrides.yaml`: the UI action is the more recent,
more deliberate signal; a stale hand edit must not silently shadow a click the user
just made. (Approved during design review.)

`MatrixRow` gains an optional field
`group_source: Literal["correction", "override", "taxonomy"] | None` recording which
layer assigned the group (`None` when ungrouped). `ExtensibleModel` keeps old
`matrix.json` files loadable — the field simply reads as `None`.

The three existing call sites (`services/profile_build.py`, `services/profile_skills.py::_rebuild_matrix`,
`api/routers/match_gap.py` refresh worker) each compose load-map + apply by hand. Extract
one shared helper — `decorate_matrix_groups(matrix, profile_dir, overrides)` in
`profile/matrix.py` — that loads the taxonomy map and the corrections ledger and applies
both. All three call sites switch to it so future consumers cannot forget the ledger.
(`profile_build.py` keeps its classify-missing-tokens step before calling the helper.)

### 3. Service + API

New `services/profile_groups.py`, mirroring `services/profile_skills.py`:

- `set_group(profile_dir, key, group)` — validates slug ∈ `SKILL_GROUPS`, resolves the
  key to a matrix row (by key, display, or alias; `SkillNotFoundError` otherwise),
  writes the ledger under the same profile-dir lock the manual-skills ledger uses,
  rebuilds `matrix.json` immediately, and returns the updated row.
- `clear_group(profile_dir, key)` — removes the correction (`ManualEntryNotFoundError`-style
  error when absent) and rebuilds; the row falls back to override/taxonomy.

Endpoints in `api/routers/profile.py`, same error mapping as the manual-skills endpoints:

| Route | Body | Success | Errors |
| --- | --- | --- | --- |
| `PUT /api/profile/skills/{key}/group` | `{ "group": "data-ml" }` | 200 + updated row (key, display, group, groupSource) | 422 unknown slug, 404 unknown skill, 400 `SETUP_INCOMPLETE` profile not built |
| `DELETE /api/profile/skills/{key}/group` | — | 204 | 404 no correction for key, 400 `SETUP_INCOMPLETE` profile not built |

("Profile not built" maps to 400 `SETUP_INCOMPLETE`, not 409, matching every
existing manual-skills endpoint in `routers/profile.py`.)

Contract regeneration: `scripts/export_openapi.py` + `bash scripts/gen_ts_client.sh`;
`tests/api/test_openapi_contract.py` gates drift.

### 4. Web UI — SkillGroupsPanel becomes editable

In `web/src/features/settings/SkillGroupsPanel.tsx`, each skill badge gets a popover
(same interaction pattern as the SkillMatrix popover):

- A "Move to…" list of the 13 groups with the current group checked; selecting one
  calls the PUT endpoint.
- When `groupSource === "correction"`, the badge shows a pin indicator and the popover
  offers "Reset to automatic" (the DELETE endpoint).
- Mutations invalidate the matrix query (`use-matrix.ts`) so the skill jumps to its new
  accordion section immediately.

### 5. Error handling & edge cases

- A correction whose token later vanishes from the matrix (skill removed from the
  profile) stays in the ledger harmlessly and re-applies if the skill returns.
- Concurrent writes serialize on the existing profile-dir lock.
- `other` is a valid correction target (explicitly place the skill in Other).
- Correction lookup is by canonical token, so renaming a skill's display text does not
  orphan its correction as long as the canonical key is stable.

### 6. Testing (offline, no LLM)

- **Ledger:** round-trip, corrupt-file → empty, unknown-slug entries dropped, atomic write.
- **Precedence:** correction beats override beats taxonomy; alias/display lookup;
  `group_source` set per layer; old matrix.json without the field still loads.
- **Service:** `set_group` persists across a full `matrix.json` rebuild (the "never make
  the same mistake again" guarantee); `clear_group` reverts to the taxonomy value;
  error types for unknown slug/skill/missing profile.
- **API:** success paths plus the 400/404/422 mappings; OpenAPI contract test and all
  three generated artifacts kept in sync.
- **Web:** Vitest component tests for the popover move flow, pin indicator, and revert.

## Out of scope

- Correcting the hard/soft/domain `category` axis.
- Few-shot steering of the LLM classifier from corrections.
- CLI surface.
- Editing `overrides.yaml` from the UI.
