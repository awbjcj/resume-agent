# Spec: Incremental Human-Readable Industry Filter

**Status:** Revised after requirements interview; awaiting final approval

## Assumptions

1. `industry` remains a nullable string in persisted criteria, API responses, and filter state.
2. Canonical values are concise, title-cased, human-readable domain names such as `Fintech`,
   `Autonomous Driving`, and `Healthcare`; SIC codes and SIC-derived labels are removed.
3. Similar labels are aliases of one stable canonical value (`Financial Technology` -> `Fintech`),
   while related but materially different domains remain separate.
4. Existing canonical names never change automatically. Each refresh makes at most one classification
   call containing all previously unseen candidates and all existing canonicals.
5. A normalized company has one stable canonical industry across every current and future job.
6. Runtime taxonomy state is stored under the existing gitignored `data/` directory; no database
   migration or new dependency is required.
7. Unknown industries remain `null` and keep the board's existing unknown-neutral filter semantics.

## Objective

Replace the pending four-digit SEC SIC implementation with a stable, incrementally learned vocabulary
of readable industry names. Users should see a small, useful Industry filter instead of codes or a
growing list of synonymous free-text variants.

The extraction model proposes the employer's primary business domain. One hidden batch classification
call inside the extraction phase canonicalizes all unseen proposals together, preferentially mapping
them to existing names. The resulting canonical name is persisted and used unchanged by filtering,
facets, active-filter chips, and job detail.

## Acceptance Criteria

- No SIC code, SIC lookup, generated SIC label map, or SEC synchronization script remains in the
  Industry extraction, persistence, filtering, or presentation path.
- `criteria_json.industry` is `null` or a concise human-readable canonical string, never a numeric code.
- Extraction requests the employer's primary business domain and explicitly rejects job functions as
  industries.
- Industry classification receives the stable existing canonical names and only raw labels not already
  covered by the alias map.
- The classifier receives normalized company/candidate pairs and existing canonical names, not full job
  descriptions.
- The first run bootstraps the taxonomy by treating all historical nonnumeric Industry strings as unseen
  candidates. Numeric-only values are cleared and never submitted as candidates.
- Every normalized company resolves to one canonical industry. A known company mapping overrides a new
  posting's proposal; bootstrap conflicts for one company are resolved to one value.
- Company identity normalizes case, punctuation, whitespace, and common legal suffixes while preserving
  separately named subsidiaries and brands.
- A new raw label may reuse one existing canonical or create one concise new canonical; aliases from the
  same batch may converge on the same new canonical.
- Existing alias and canonical choices win on later refreshes, preventing vocabulary churn.
- Exact/case/spacing/underscore variants deduplicate deterministically before any LLM classification.
- Failed or malformed classifier output does not corrupt existing taxonomy state. Valid groups persist;
  unresolved labels stay out of the canonical filter in an internal retry candidate and retry on the
  next refresh.
- The alias map is written atomically. Successful additions are monotonic and idempotent.
- Board facet counts, filtering, active chips, and job detail use the same canonical string, displayed
  without code-specific formatting.
- Learned mappings update matching jobs across all statuses. Numeric SIC values require normal
  Reprocess to regain a readable Industry; no SIC-to-name guessing is attempted.
- The first normalization pass removes legacy `sic_major` and other SIC-derived JSON keys from every
  stored job.
- Tests cover `Fintech`, `Autonomous Driving`, reuse of an existing canonical, same-batch synonym
  convergence, stable reruns, malformed output, filter matching, and UI display.

## Tech Stack

- Python 3.13, Pydantic 2, Agno structured-output agents, SQLModel
- FastAPI with generated OpenAPI/TypeScript contracts
- React 19, TypeScript 6, Vite 8, Vitest
- Atomic JSON runtime state under `data/industry_taxonomy.json`

No new runtime dependency is required.

## Commands

```bash
# Targeted backend verification
uv run pytest tests/test_taxonomy_industries.py tests/test_discovery_extract.py \
  tests/test_discovery_pipeline.py tests/test_tracking_queries.py \
  tests/test_services_board.py tests/test_shortlist_filtering.py -v

# Targeted frontend verification
npm --prefix web run test:run -- \
  src/lib/filters/industry-label.test.ts \
  src/components/FilterDesk.test.tsx \
  src/components/JobMeta.test.tsx

# Full verification
uv run ruff check src tests
uv run pytest
npm --prefix web run lint
npm --prefix web run test:run
npm --prefix web run build
```

## Project Structure

```text
src/resume_tailor_harness/taxonomy/industries.py
  Normalize labels/company identities; load, merge, and atomically save aliases and company mappings.
src/resume_tailor_harness/discovery/industry.py
  Structured incremental classifier schema, prompt, and validated output projection.
src/resume_tailor_harness/discovery/extract.py
  Extract a raw readable business-domain proposal.
src/resume_tailor_harness/discovery/pipeline.py
  Classify unseen proposals after extraction and persist canonical names.
src/resume_tailor_harness/services/agents.py
  Add the industry classifier to the shared discovery agent bundle.
src/resume_tailor_harness/models/job.py
  Keep `industry` as an unrestricted nullable string; remove SIC validation.
src/resume_tailor_harness/tracking/queries.py
  Project canonical industry strings directly into board/detail rows.
web/src/lib/filters/industry-label.ts
  Human-readable formatting only; no code-to-title lookup.
data/industry_taxonomy.json
  Gitignored runtime alias/company-to-canonical state, written atomically.
tests/, web/src/**/*.test.*
  Incremental taxonomy, pipeline, filtering, and display coverage.
```

## Code Style

Canonicalization is explicit at the boundary and stable afterward:

```python
def canonical_industry(raw: str | None, aliases: dict[str, str]) -> str | None:
    key = normalize_industry(raw)
    return aliases.get(key) if key else None


def merge_industry_aliases(
    existing: dict[str, str], additions: dict[str, str]
) -> dict[str, str]:
    return existing | {key: value for key, value in additions.items() if key not in existing}
```

- Python uses typed functions, snake_case, and small pure taxonomy helpers.
- TypeScript uses explicit types, camelCase, and pure formatting helpers.
- Classifier output is projected back onto authoritative input labels; invented source labels and unknown
  existing canonical names are rejected.
- Canonical output uses recognizable 1–4 word business domains without company names, job functions, or
  marketing slogans. Numeric-only values are rejected; readable names such as `3D Printing` remain valid.
- Persistence uses atomic replace and deterministic JSON ordering.

## Testing Strategy

- Pure taxonomy tests pin normalization, exact-variant deduplication, stable merge semantics, atomic
  persistence, and idempotence.
- Classifier tests use fake runners to prove existing-canonical reuse, same-batch convergence, and strict
  rejection of malformed or invented assignments.
- Pipeline tests prove only unseen labels are sent to classification, successful canonical values are
  persisted, and failures remain retryable without damaging existing aliases.
- Board and shared filter-contract tests prove exact string matching and unknown-neutral behavior.
- React tests prove filter options, active chips, and job details show readable names with no SIC labels.
- Full backend/frontend suites and a production frontend build guard unrelated working-tree changes.

## Boundaries

- Always:
  - Preserve unrelated active work in the dirty working tree.
  - Keep existing canonical choices stable and classify only unseen labels.
  - Normalize trivial textual variants before invoking the classifier.
  - Treat model output as untrusted and validate it against supplied inputs/context.
  - Enforce a single canonical industry for every normalized company.
  - Run targeted tests before full verification.
- Ask first:
  - Rename or merge an already-established canonical industry automatically.
  - Change unknown-neutral filter semantics.
  - Add a database table/migration or a new runtime dependency.
- Never:
  - Store or display SIC codes for Industry.
  - Use a job function, department, or customer project such as `Software Engineering` as the industry.
  - Reclassify the complete historical vocabulary on every run.
  - Persist fallback identity mappings after classifier failure, because that would prevent retry and
    permanently create redundant options.

## Success Criteria

Given an existing canonical `Fintech`, a later extracted `Financial Technology` is classified once and
persisted as `Fintech`; subsequent runs make no classification call for it. In the same new batch,
`Self-Driving Cars` and `Autonomous Vehicle Technology` may converge on one new canonical
`Autonomous Driving`. The Industry filter then contains only `Fintech` and `Autonomous Driving`, and the
same values appear in active chips and job detail. Every spelling variant of the same company receives
that company's one stored canonical Industry. No numeric SIC option appears anywhere.

## Open Questions

- None.
