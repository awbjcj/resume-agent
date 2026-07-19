# Skill Constellation Three-Level Taxonomy — Design

**Date:** 2026-07-18
**Status:** Implemented
**Supersedes:** the two-level theme layer of the 2026-06-27 match-gap dashboard redesign (SkillMap portion only)

## Problem

The Skill constellation (`web/src/features/match-gap/SkillMap.tsx`) renders a two-level
graph: LLM-invented theme hubs → skill leaves. Theme creation is open-vocabulary
(`classify_incrementally` may always mint a new label), so themes proliferate: many
top-level nodes, each holding few skills. Separately, the profile skill matrix uses a
different fixed 13-slug group vocabulary (`taxonomy/groups.py`), and the constellation
has no editing affordances at all — existing skill-edit surfaces (Settings →
SkillGroupsPanel, ManualSkillsPanel) are invisible from the map.

## Decisions (user-approved)

1. **Fixed shared top level.** One curated vocabulary of 19 category slugs + `other`,
   defined in code, replaces both the 13 profile group slugs and the LLM's ability to
   invent top-level nodes. Shared by the constellation and the profile matrix group axis.
2. **LLM second level, capped.** Domains are LLM-clustered but each must parent to one
   fixed category; per-category cap (default 12, `Settings.domains_per_category_cap`)
   is enforced deterministically in projection code, never trusted to the model.
3. **Full edit suite:** move skill between domains, rename/merge/re-parent domains,
   add/remove skills, merge duplicate skills (aliases).
4. **Edits surfaced in the constellation** via per-node menus; Settings panels remain
   for bulk work.
5. **Leaves stay demanded skills only** (match-gap purpose unchanged); empty categories
   are hidden.
6. **Approach A:** evolve `ClusterMap` in place, keep aliases, discard the old theme
   layer, reclassify fresh on the first refresh after upgrade.

## Correctness amendments

The implementation review made the following contracts explicit:

- The per-category cap is a hard final invariant across all concurrent LLM batches.
  Model calls may fan out, but a deterministic post-projection admission pass prevents
  aggregate overshoot. Equal labels under different categories remain distinct domains.
- Correction files salvage valid entries when neighboring values are malformed or
  cyclic. Explicit terminal-token assignments win over alias-member assignments,
  independent of serialized map order.
- Each API mutation is one locked read-modify-write ledger transaction. Compound add
  and patch operations validate completely and persist once, so failures cannot leave a
  partial edit and concurrent requests cannot overwrite each other's intents.
- Skill aliases merge two existing visible skills. Unknown alias endpoints are rejected
  rather than creating dangling canonical tokens.
- `MatchGapOut.categories` is the authoritative full 20-entry vocabulary for both
  rendering metadata and edit pickers. Empty categories are hidden by the derived view,
  not omitted from the wire contract; the web app never mirrors the slug list.
- Constellation leaves are demanded skills plus explicit `added_skills` overrides.
  Explicit additions may have zero job counts; unrelated profile-only skills remain out
  of scope.
- Corrections-aware demand-graph imports must not create a `tracking.match_gap` ↔
  `taxonomy.corrections` module cycle.

## Category vocabulary (top level)

Defined in `taxonomy/vocabulary.py` and re-exported by `taxonomy/groups.py`. Display + parenting only —
fact-lock and the hard/soft/domain categories in `facts.json` are untouched.

Hard (14): `languages` Programming Languages, `frontend-web` Frontend & Web,
`backend-apis` Backend & APIs, `mobile-desktop` Mobile & Desktop,
`data-engineering` Data Engineering & Analytics, `ai-ml` AI & Machine Learning,
`databases-storage` Databases & Storage, `cloud-infra` Cloud & Infrastructure,
`devops-automation` DevOps & Automation, `testing-quality` Testing & Quality,
`security-compliance` Security & Compliance, `systems-embedded` Systems & Embedded,
`architecture-design` Architecture & Design, `tools-platforms` Tools & Platforms.

Soft (5): `leadership-management` Leadership & Management,
`collaboration-communication` Collaboration & Communication,
`product-business` Product & Business, `process-methodology` Process & Methodology,
`domain-knowledge` Domain Knowledge.

Fallback: `other` (mandatory, never removed; unassignable domains land there).

The vocabulary is a code constant, not user-editable — that is what guarantees a
bounded top level. Each category carries `kind: hard | soft` for the UI.

### group_corrections migration

One-time slug remap applied on load of `data/profile/group_corrections.json`:
unambiguous 1:1 renames map (`languages`, `cloud-infra`, `testing-quality`,
`security`→`security-compliance`, `leadership`→`leadership-management`,
`communication`→`collaboration-communication`, `domain-knowledge`, `other`);
corrections under `frameworks`, `practices`, `data-ml`, `databases`,
`devops-tooling` are dropped and those tokens reclassify on the next profile build.

## Data model (`taxonomy/clusters.py`)

```python
@dataclass
class ClusterMap:
    aliases: dict[str, str]        # unchanged: raw token -> canonical token
    domain_of: dict[str, str]      # canonical token -> domain_id   (was theme_of)
    domain_label: dict[str, str]   # domain_id -> display label      (was theme_label)
    category_of: dict[str, str]    # domain_id -> fixed category slug (NEW)
```

- Loading is tolerant: legacy `theme_of`/`theme_label` keys are ignored (aliases kept).
- New invariants sanitized on load: every `category_of` value must be in the fixed
  vocabulary; every domain referenced by `domain_of` must have a category. Violations
  sanitize to `other`; nothing crashes.
- `merge_cluster_map` / `prune_cluster_map` extend naturally: prune drops domains with
  zero demanded skills and categories follow implicitly (empty categories never render).

## Classification pipeline (`taxonomy/classification.py`)

Each themer batch prompt carries, per category: slug, label, current domains
(id, label, member skills), and a `full` flag (domain count ≥ cap). Per skill the LLM
outputs either `existing_domain_id` or `new_domain: {label, category}`.

Deterministic projection (successor of `_project_themes`) rejects: category slug not in
vocabulary; `new_domain` naming a full category; both/neither mode fields set. Rejected
tokens become `ClassificationFailure`s and retry next refresh. Canonicalize → reconcile
semantics are unchanged.

## Taxonomy corrections ledger

`data/taxonomy/taxonomy_corrections.json` — user-authored intents, replayed last,
always winning; the LLM never reads or writes it (mirrors `group_corrections`):

```json
{
  "skill_domain": { "<canonical token>": "<domain_id>" },
  "domain_renames": { "<domain_id>": "New Label" },
  "domain_merges": { "<loser_domain_id>": "<winner_domain_id>" },
  "domain_category": { "<domain_id>": "<category_slug>" },
  "added_skills": ["<token>"],
  "removed_skills": ["<token>"],
  "aliases": { "<token>": "<canonical token>" }
}
```

- Applied by one pure function `apply_taxonomy_corrections(cmap, corrections)` at every
  load point, after LLM refresh output merges. Precedence: corrections > LLM output.
- `domain_merges` reuses the `_flatten_aliases` cycle-rejection approach.
- `removed_skills` hides leaves from views but never blocks re-adding: `POST
/api/taxonomy/skills` for a removed token deletes it from `removed_skills` in the
  same ledger update.
- User aliases merge into the alias map with user entries winning.
- **User-created domain durability:** creating a domain via "Move → New domain…" writes
  `skill_domain` + `domain_renames` + `domain_category` in one atomic update, so replay
  reconstructs the domain from the ledger alone after any rebuild.
- **Dangling refs are inert:** a correction naming a domain that no longer exists and
  cannot be reconstructed from the ledger is skipped during replay, not an error.
- Writes hold a lock and use the atomic tempfile + `os.replace` pattern; loading
  sanitizes every boundary (bad types, unknown slugs, cycles → entry dropped).

Refresh flow (`services/match_gap.refresh_clusters`): canonicalize new tokens →
reconcile → classify into domains (category-aware) → merge → prune → **apply
corrections** → save.

## API and wire contract

`MatchGapOut` reshape (regenerate contracts via `scripts/gen_ts_client.sh`; the
OpenAPI drift gate covers it):

- `ThemeOut` → `DomainOut` (same aggregates + `category: str`).
- New `CategoryOut { slug, label, kind: "hard" | "soft" }`; payload carries all
  categories in authored order so the web app never hardcodes the vocabulary. The
  derived view omits empty categories from galaxy rendering.
- `SkillNodeOut.theme_id` → `domain_id`; the `covered` sync validator stays.
- Suggestion kinds rename `"theme"` → `"domain"` across the four suggestion schemas
  and `SuggestionStatusOut` in the match-gap schema.
  Stored suggestions with kind `theme` are deleted on first service load (their keys
  are orphaned by reclassification regardless). Categories get no suggestion/research
  support — research stays at skill and domain granularity.

New edit endpoints — thin `api/routers/taxonomy.py` over `services/taxonomy.py`,
all synchronous (no LLM, no Run/SSE), each validating against the current map,
appending to the ledger atomically, and returning the updated map:

| Endpoint                                                   | Ledger write                         |
| ---------------------------------------------------------- | ------------------------------------ |
| `PUT /api/taxonomy/skills/{token}/domain`                  | `skill_domain`                       |
| `PATCH /api/taxonomy/domains/{id}` (label and/or category) | `domain_renames` / `domain_category` |
| `POST /api/taxonomy/domains/{id}/merge`                    | `domain_merges`                      |
| `POST /api/taxonomy/skills` (token + target domain)        | `added_skills` + `skill_domain`      |
| `DELETE /api/taxonomy/skills/{token}`                      | `removed_skills`                     |
| `POST /api/taxonomy/aliases` (token → canonical)           | `aliases`                            |

No create-empty-domain endpoint: domains exist only when a skill lives there; moving a
skill to a new label + category creates the domain implicitly. Validation failures
(unknown domain id, invalid category slug, alias/merge cycle) use the standard
`ApiException` error envelope.

## Constellation UI

Progressive disclosure, three view states, reusing existing zoom/pan/focus mechanics
in `SkillMap.tsx` / `skill-map-layout.ts`:

1. **Galaxy (default):** category nodes only; hard vs soft visually distinct
   (filled vs outlined hubs), sized by skill count, badged with gap count.
2. **Category view:** click a category → its domains orbit it; other categories
   hidden; breadcrumb "All categories ›" returns.
3. **Domain view:** click a domain → skill leaves with today's gap/adjacent/covered
   borders, checkboxes, research-ready rings, and the existing skill-details sheet.

Research checkboxes appear on domains and skills, not categories. Footer legend and
counts adapt per level.

Editing is per-node kebab/context menus (no separate edit mode):

- **Skill leaf:** Move to domain… (picker grouped by category + "New domain…" with
  label + category), Merge into another skill… (alias), Remove skill, Open details.
- **Domain:** Rename…, Change category…, Merge into domain….
- **Category:** no edit menu (fixed vocabulary).
- **Map header:** Add skill (token + target domain) beside zoom controls.

Mutations flow through a new `use-taxonomy.ts` (TanStack mutations; endpoint responses
are written straight into the match-gap query cache). Destructive ops confirm inline in
their dialogs. Dialog components live in `web/src/features/match-gap/taxonomy-edit/`
(one per operation + the menu) to keep `SkillMap.tsx` focused on layout/rendering.

Settings → `SkillGroupsPanel` stays for bulk profile-matrix work and picks up the new
vocabulary automatically from the API's `groups` payload.

## Migration & rollout

- Legacy cluster file loads with themes ignored → `clusters_stale` computes true →
  the existing "Refresh clustering" prompt drives the one-time reclassification
  (~1 cheap-tier batch per 40 skills). No hidden background migration.
- `group_corrections.json` slug remap on load (see above); the dropped-slug caveat is
  accepted.
- Theme-kind stored suggestions deleted on first service load.

## Error handling summary

- Classification failures stay isolated per batch; cap-full rejection is one more
  failure reason; tokens retry next refresh. `ReconcileError` semantics unchanged.
- Ledger and cluster-map loading sanitize, never crash; writes are locked + atomic.
- Prune cannot strand a user-moved skill: a domain holding a demanded skill is never
  pruned; truly dangling corrections are inert.

## Testing (offline; agents faked)

- **Unit:** ClusterMap round-trip/sanitize/merge/prune with categories; projection cap
  enforcement (full category → new-domain rejected, reuse accepted);
  `apply_taxonomy_corrections` pure-function coverage (every intent, ordering, dangling
  refs, merge cycles); group-corrections slug remap; vocabulary integrity.
- **API:** per-endpoint router tests (happy path + each validation failure); OpenAPI
  contract drift gate regenerated.
- **Web:** `aggregate.ts` reshape; SkillMap drill-down navigation (jsdom, same pattern
  as current focus tests); one test per edit dialog; mutation-hook cache-write tests.

## Out of scope

- Editing the category vocabulary at runtime.
- Research/suggestions at category granularity.
- Any change to fact-lock, `facts.json` categories, or inferred-skill rules.
- Profile-skill leaves in the constellation (demanded skills only).
