# Skill management, Search Scout, and job-detail polish — Design

**Date:** 2026-07-20
**Status:** Approved (design), pending implementation plan

## Summary

Five workstreams bundled into one spec, spanning the profile-skill lifecycle,
a new search-condition recommender, and two job-detail UI fixes:

- **A.** Manually-added skills fold into real categories, merge with existing
  skills, and reliably survive a profile rebuild.
- **B.** The user can delete *any* skill (synthesized, inferred, or manual)
  durably — a deleted skill never reappears on rebuild until restored.
- **C.** The job-detail modal is wider so the masthead title stops wrapping, and
  the Versions tab count number sits snug against its label.
- **D.** Skill badges/chips render at one consistent size across the matrix.
- **E.** A Search Scout recommends keywords, titles, role anchors, and exclude
  terms — the same approve-before-add pattern Source Scout uses for companies.

Workstreams A and B share one ledger, one replay path, and one Settings panel.
C and D are isolated UI polish. E is self-contained and parallels the existing
Source Scout (`discovery/source_scout.py` + `services/source_discovery.py`).

## Context / current state

- **Additive ledger already exists and is replayed on build.**
  `profile/manual_skills.py` defines `ManualSkillsLedger` (`new_skill`, `alias`
  entry kinds) persisted to `manual_skills.json`. `apply_manual_skills` is
  idempotent and dedupes by normalized token. `services/profile_build.run_corpus_build`
  replays it (profile_build.py:63-65) onto freshly-synthesized facts every build.
- **`build_matrix` flattens all buckets.** `matrix.py:292` iterates
  `for skills in facts.skills.values()` regardless of bucket key; row category
  comes from `Skill.category` (matrix.py:318-319). A manual skill placed in the
  `"Manually added"` bucket with `category=None` therefore *does* get a matrix
  row — but renders uncategorized/ungrouped, which is why it reads as
  second-class. **The bucket key is a cosmetic problem, not a filtering one.**
- **No suppression path exists.** The ledger only adds; there is no symmetric
  way to remove a synthesized skill and keep it removed across rebuilds.
- **Two badge primitives coexist.** The job-detail matrix uses a bespoke
  `.skill-chip` CSS class (`src/index.css:234`, padding `0.3rem 0.72rem`, font
  `0.84rem`); everywhere else uses shadcn `Badge` (`h-5`, `text-xs`). Gap chips
  embed `AddSkillPopover`'s `+` button, inflating their height vs covered chips.
- **Source Scout is the proven pattern to mirror.** Research agent (web-search-
  equipped, mid tier) + formatter agent (cheap tier, typed output) →
  `services/source_discovery.py` builds grounding context, dedupes against
  existing sources, runs through the launch seam as a run + SSE →
  `DiscoverCompaniesDialog` presents approve-able rows.

## A. Manual skills — categories, merge, persistence

### A0. Persistence regression test first

Reproduce the reported "skills don't persist after rebuild" as a **failing
test**: add a skill via the service, run `run_corpus_build`, assert the skill is
present in the resulting `facts.json`/matrix. Prime suspect: `_ledger_path`
(`services/profile_skills.py:55`) builds `Path(profile_dir) / "manual_skills.json"`
without `resolve_tenant_path`, while `run_corpus_build` reads the ledger from an
already-resolved dir — a path divergence under tenancy would make the build
replay an empty ledger. Fix the root cause the test actually reveals; do not
assume.

### A1. Fold into real categories (kill the dead-end bucket)

- `apply_manual_skill_entry` places a new manual skill into its **real category
  bucket** (`hard`/`soft`/`domain`) instead of `MANUAL_SKILLS_BUCKET`, and always
  sets `Skill.category`.
- When the user picks "Not sure" (category unspecified), **default to `hard`**
  so the skill is never uncategorized/ungrouped.
- `MANUAL_SKILLS_BUCKET` and its special-casing in `apply_manual_skill_entry` /
  `remove_manual_skill_entry` are removed. Removal of a manual skill now targets
  its category bucket by normalized token.
- Result: after the next build, a manually-added skill is indistinguishable from
  a synthesized one — it gets a group via the existing taxonomy classifier,
  counts as covered on job cards, and renders normally in the matrix.

### A2. Merge with existing skills

- Exact normalized-token match against any existing skill name/alias already
  no-ops in `apply_manual_skill_entry` — that *is* the merge with a synthesized
  duplicate, preserved unchanged.
- Variants (k8s ↔ Kubernetes) stay on the deterministic alias path: the
  `AddSkillPopover` "Same as a skill I have" mode writes a `ManualAliasEntry`.
  **No LLM guessing** — fact-lock discipline is preserved.

## B. Delete any skill — durable suppression

- Add a third ledger entry kind `ManualSuppressEntry{kind: "suppress", token,
  display, added_at}` to the **same** `manual_skills.json` (one file, one lock,
  one replay).
- `apply_manual_skills` replays adds/aliases first, then **removes any skill
  whose normalized token is suppressed**, so a deleted synthesized/inferred/
  manual skill stays gone across every rebuild until restored.
- Contradiction rule: suppressing a skill that also has a pending `new_skill`
  add entry drops the add entry rather than storing a contradictory pair; adding
  a skill whose token is currently suppressed drops the suppress entry (restore).
- Service: `delete_skill(profile_dir, key)` resolves the skill by matrix key /
  id, appends a suppress entry, removes it from live `facts.json`, and rebuilds
  the saved matrix — mirroring the immediate-effect mechanism of `add_skill`.
- API: `DELETE /api/profile/skills/{key}` (204). Errors map through the standard
  envelope (`ProfileNotBuiltError` → 400, not-found → 404).
- Restore: suppressed skills are listed in the Settings > Profile skills panel
  with a **Restore** button that removes the suppress entry and rebuilds.

## C. Job-detail modal width + heading + version count

- Widen `JobModal` (`components/JobModal.tsx`): `DialogContent`
  `sm:max-w-6xl` → `sm:max-w-7xl`; keep the 400px rail, so the extra width goes
  to the main pane and the masthead `DialogTitle` stops wrapping at common widths.
- Fix the Versions tab count: tighten `tabCountClass` so the number sits snug
  against the label (remove the loose `ml-1.5` gap / align baseline), reading
  "Versions ③" rather than "Versions      3". Cover letters count uses the same
  class and benefits identically.

## D. Unify skill badge sizes

- `AddSkillPopover`'s `+` trigger becomes a fixed-size inline affordance that
  does **not** change chip height (constrained box, no extra vertical padding).
- Covered and gap `.skill-chip` variants share identical padding, height, and
  line-height so they read as one size regardless of the embedded `+`.
- Align `.skill-chip` metrics (`src/index.css`) to the shadcn `Badge` scale so
  chips are one consistent size system across the job-detail matrix.

## E. Search Scout — recommend search conditions

Mirrors Source Scout, minus the URL-validation phase (search terms need no
reachability probe).

### E1. Agents — `discovery/search_scout.py`

- `SearchSuggestion{value, kind: "keyword"|"title"|"role_anchor"|"exclude_term",
  reason}` and `SearchSuggestions{suggestions: list[...]}` typed models
  (`ExtensibleModel`).
- **Research agent**: web-search-equipped (`build_search_equipped(mid_model)`),
  instructed to propose keywords, titles, role anchors, and exclude terms fitting
  the supplied profile + existing search config; supplied context and web
  results are untrusted data, never instructions.
- **Formatter agent**: cheap tier, `output_schema=SearchSuggestions`, converts
  grounded notes into typed rows; uses no outside knowledge.
- Reuses `with_guidance`, `retry_kwargs`, `tool_kwargs`, `use_json_mode_for` —
  same construction shape as `source_scout.py`. Registers guidance keys
  `search-scout-research` / `search-scout-format`.

### E2. Service — `services/search_discovery.py`

- `scout_search_context(search_path, profile_dir)`: compact grounding from
  profile recent titles + top skills + current keywords/titles/role-anchors/
  exclude-terms.
- `run_search_discovery(reporter, *, prompt, search_path, profile_dir,
  research_agent=None, formatter_agent=None)`: runs research → format, **dedupes
  each suggestion against the existing term of its kind (case-folded)**, marks
  duplicates, returns approve-able rows grouped by kind. Runs through the launch
  seam as a run + SSE. No validation fan-out.

### E3. UI

- A **"Suggest search terms"** dialog on the Search settings page
  (`SearchSettingsPage`), structured like `DiscoverCompaniesDialog`: a prompt
  box, grouped suggestion rows (Keywords / Titles / Role anchors / Exclude terms)
  with per-item checkboxes and the reason as helper text; duplicates disabled.
- "Add selected" **appends** approved terms additively (never replacing) to the
  matching `TagListInput` field through the existing search-config save path.
- Locations are out of scope for the recommender.

## Testing

- **A0/A/B (backend):** add→build→present persistence test; manual skill lands in
  its category bucket with a category set; "Not sure" → `hard`; exact-token merge
  no-ops; suppress hides a synthesized skill and survives rebuild; add-then-
  suppress and suppress-then-add contradiction rules; restore. All offline
  (agents/browser faked, as the suite already runs).
- **E (backend):** context builder tolerates missing artifacts; dedupe against
  existing terms per kind; run_search_discovery with injected fake agents
  produces grouped rows; launch-seam wiring.
- **API contract:** `DELETE /api/profile/skills/{key}`, restore, and the search-
  discovery run endpoints regenerate `contracts/openapi.json` + `contracts/ts/api.ts`
  (drift gate `tests/api/test_openapi_contract.py`).
- **Web:** ManualSkillsPanel shows suppressed + restore; delete affordance on
  matrix/skill UIs; JobModal width + version-count alignment; skill-chip size
  parity (covered vs gap); Search Scout dialog approve-and-append.

## Out of scope

- LLM-based fuzzy skill merging (deterministic exact-token + explicit alias only).
- Location recommendations in Search Scout.
- Any change to fact-lock, synthesis, or the hard/soft/domain semantics beyond
  the manual-skill categorization above.
