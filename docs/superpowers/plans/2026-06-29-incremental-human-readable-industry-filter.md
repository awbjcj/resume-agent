# Incremental Human-Readable Industry Filter — Implementation Plan

**Status:** Revised after requirements interview; awaiting final approval
**Design source:** `docs/superpowers/specs/2026-06-29-incremental-human-readable-industry-filter-design.md`

## Outcome

Industry values become stable human-readable strings. A monotonic taxonomy map and one incremental
classification call per non-warm discovery run deduplicate new labels against established canonicals.
Each normalized company has exactly one canonical industry. The SIC implementation is removed completely,
including its package data, generator, runtime projections, API fields, frontend lookup, and tests.

## Components and Dependencies

1. **Industry taxonomy state**
   - A pure `taxonomy/industries.py` module owns industry/company normalization, alias lookup,
     company-to-industry lookup, stable merges, and atomic JSON persistence.
   - It has no dependency on discovery, SQLModel, FastAPI, or React.

2. **Incremental classifier seam**
   - A focused `discovery/industry.py` module defines `{canonical, candidates}` groups and validates
     assignments against authoritative company/candidate pairs and supplied existing canonicals.
   - It depends on the taxonomy normalizer and the existing `Runner` abstraction.

3. **Discovery integration**
   - Extraction emits concise readable proposals.
   - After concurrent extraction, the pipeline resolves known company and alias mappings locally, then
     sends every unresolved candidate in one call together with all existing canonicals. It persists valid
     partial additions and updates matching jobs across all statuses.
   - The shared discovery bundle supplies the classifier runner.

4. **Read/filter/UI projection**
   - Board and detail read models project `criteria_json.industry` directly.
   - Existing filter behavior continues to compare exact canonical strings.
   - UI labels only replace underscore separators; there is no code lookup.

5. **SIC pruning**
   - Delete the SIC Python module, bundled code table, SEC sync script, generated TypeScript labels, and
     dedicated SIC tests.
   - Remove `sic_major`, `sic_label`, and `sic_division` from tracking/API models and regenerated
     contracts.
   - Remove SIC package-data configuration and all executable/test references.
   - On the first normalization pass, remove stale SIC keys from every `criteria_json` and clear
     numeric-only Industry values.
   - Delete the aborted uncommitted four-digit SIC specification and plan; preserve older historical
     design records.
   - Historical design documents remain as project history; the runtime source tree must have no SIC
     implementation.

## Implementation Order

1. Add failing taxonomy and classifier tests that pin stable incremental and same-company behavior.
2. Implement the pure taxonomy store and strict classifier projection.
3. Add failing extraction/pipeline tests for readable candidates, bootstrap consolidation, unseen-delta
   classification, retryable partial failures, company consistency, and persisted canonical names.
4. Wire the classifier through discovery services and reprocessing.
5. Remove SIC projections and update backend filter/read-model tests.
6. Remove frontend SIC labeling and update component/e2e tests for readable names.
7. Delete all SIC assets and regenerate OpenAPI/TypeScript contracts.
8. Run targeted verification, scan for residual SIC runtime references, then run full backend/frontend
   verification.

## Incremental Classification Rules

- Normalize industry case, surrounding/repeated whitespace, punctuation, hyphens, and underscores for
  lookup. Reject numeric-only values but allow readable alphanumeric values such as `Web3`.
- Normalize company case, punctuation, whitespace, and legal suffixes; keep named brands/subsidiaries
  distinct.
- Resolve company mappings first, aliases second, then compute the unresolved delta.
- Supply all unresolved company/candidate pairs together with sorted stable canonical values to at most
  one classification operation. A fully warm run makes zero calls.
- Each delta label must either reference one supplied canonical or propose one nonblank concise new label.
- Multiple delta labels may propose the same new label, which creates one canonical option.
- Existing mappings are immutable during merge; additions cannot redirect an established alias.
- Model-invented source labels, unknown existing canonicals, incomplete assignments, and ambiguous
  assignment modes are rejected.
- Canonical names are concise, recognizable employer business domains; they exclude job functions,
  company names, and marketing slogans.
- Save valid groups even when sibling groups are invalid. Missing labels remain absent so the next run
  retries them.
- Update a job's persisted Industry only when its candidate resolves successfully. Unresolved values use
  `industry: null` plus an internal retry-only candidate that never appears in the API or filter.
- Persist the first validated company-to-industry mapping and let it override future candidate/alias
  results. Corrections require removing the mapping and running Reprocess.
- Retain learned mappings even when no current job uses them; facets still expose only values present in
  current board results.

## Working-Tree Safety

The current tree contains unrelated in-progress changes for concurrent LLM calls, salary precision,
match-gap classification, and tailoring. Implementation will edit overlapping files surgically:

- Preserve non-SIC hunks in `models/job.py`, `discovery/pipeline.py`, `llm_runner.py`, services, and tests.
- Do not restore files wholesale from `HEAD`.
- Review the final diff by file and compare deleted SIC hunks against the pending SIC design.

## Risks and Mitigations

- **Classifier failure leaves jobs without Industry:** retain an internal candidate, keep mappings absent,
  and retry; do not persist identity fallbacks that pollute the filter.
- **Vocabulary drift:** existing mappings and canonical display names are immutable automatically.
- **Same-batch duplicate names:** the single call sees the complete unseen delta and may assign one shared
  new canonical; deterministic normalization collapses trivial variants before the call.
- **Conflicting jobs at one company:** the company mapping is authoritative; bootstrap sends all conflicts
  together and accepts only one canonical assignment for that company.
- **Bundle signature churn in tests/callers:** make the new classifier explicit in `DiscoveryBundle` and
  update all construction seams together; use fake runners in tests.
- **Contract break from SIC field removal:** regenerate checked-in contracts and update all API/frontend
  consumers in the same change.
- **Accidental loss of unrelated dirty changes:** patch individual hunks and inspect `git diff` before
  verification.

## Parallelism

The taxonomy/classifier core and the SIC reference scan are logically independent, but implementation
will remain sequential because the same dirty files and contracts overlap. Test suites may run in
parallel after code changes are complete.

## Verification Checkpoints

1. **Core checkpoint:** taxonomy/classifier unit tests pass with no network or API credentials.
2. **Pipeline checkpoint:** extraction and discovery tests prove only unseen labels are classified and
   canonical strings are persisted consistently per company; warm runs make zero classifier calls.
3. **Projection checkpoint:** backend filter, board, tracking, and API tests pass with no SIC fields.
4. **Frontend checkpoint:** readable labels pass unit/e2e fixtures and the production build.
5. **Pruning checkpoint:** `rg` finds no SIC implementation reference in runtime source, tests, scripts,
   package configuration, or generated contracts. Historical docs are excluded from this gate.
6. **Final checkpoint:** Ruff, the complete Python suite, frontend lint/tests, and frontend build pass.
