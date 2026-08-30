# Company intelligence v2 — phased implementation plan

**Goal:** Turn the grounded company dossier into versioned, decision-ready
evidence and explicit job-search actions while preserving current compatibility,
cost controls, and trust boundaries.

**Design:** `docs/superpowers/specs/2026-08-30-company-intelligence-v2-design.md`

## Global constraints

- Branch from `main`; land each phase as an independently tested commit.
- GET operations are read-only and never launch a provider or model.
- Current evidence remains visible on failed refresh.
- Research text, JDs, resumes, event notes, and public pages are untrusted data.
- Company-wide evidence and job/candidate-specific preparation remain separate.
- Generated clients are committed only after backend contracts are stable.
- Tests inject fake runners and never require network access.

## Phase 0 — design and executable plan

- Write the approved design and this phased plan.
- Confirm compatibility, persistence, API, and UI boundaries against the current
  implementation.
- Commit documentation before behavioral code.

**Gate:** Markdown diff check and clean staged scope.

## Phase 1 — evidence quality, depth, and immutable history

### Backend

- Extend company source and insight models with compatibility-safe quality fields.
- Add deterministic server-side verification-state normalization.
- Add `CompanyIntelligenceVersionRow` and append a version on every successful
  explicit refresh.
- Snapshot a legacy current row before its first v2 refresh.
- Compute deterministic added/removed/changed axes and source URLs.
- Accept `quick | standard | deep` on the canonical refresh endpoint and adapt
  the research prompt without changing GET behavior.
- Add a version-list endpoint.

### Tests

- Old payload compatibility.
- Verification-state downgrade/corroboration rules.
- Version numbering, legacy baseline, diff, and failed-refresh preservation.
- Refresh depth propagation and version API response.

**Gate:** focused model/service/API tests, Ruff, diff check, atomic commit.

## Phase 2 — role-specific preparation and feedback reuse

### Backend

- Add typed role-preparation models, formatter agent, and one current job-scoped
  persistence row.
- Freeze company version, JD, resume version, application status, and existing
  interview-event signals at generation time.
- Revalidate every company citation against the frozen dossier.
- Add read and explicit-refresh endpoints through the existing Run/SSE system.
- Include frozen role brief metadata in newly opened mock-interview context while
  keeping old session JSON valid.

### Tests

- Selected/latest resume resolution.
- Earlier-round reflection and interviewer reuse.
- Citation filtering and immutable input references.
- Empty/ready API states, singleton identity, and frozen interview snapshot.

**Gate:** focused service/API/interview tests, Ruff, diff check, atomic commit.

## Phase 3 — evidence and preparation UI

- Regenerate OpenAPI and both TypeScript clients.
- Add depth controls with clear time/cost descriptions.
- Render source tier/date, insight verification state, and deterministic changes.
- Add version-history disclosure without replacing the current overview.
- Add role-preparation generation and readable result sections.
- Preserve shared Research-panel geometry, keyboard access, responsive stacking,
  reduced-motion behavior, and safe external links.

**Gate:** focused Vitest, TypeScript, ESLint, component review, atomic commit.

## Phase 4 — public hiring-contact intelligence

### Backend

- Add separate contact models, public-web researcher/formatter, grounding service,
  and job-scoped persistence.
- Persist only contacts whose source URL occurred in research; never guess a name.
- Generate copy-only email and short-message drafts; expose no send endpoint.
- Add read and explicit-refresh API resources.

### UI

- Add an aligned Hiring contacts section with contact confidence, public source,
  copy actions, empty/generic states, and a permanent draft-only notice.

**Gate:** grounding/service/API/component tests, generated contracts, lint/type
checks, atomic backend and UI commits where practical.

## Phase 5 — deterministic role comparison

- Add a two-or-three-job comparison request/response using stored evidence,
  sponsorship, application, fit, and latest structured offer data.
- Add comparison selection and a dense accessible table to Applications.
- Keep unavailable values explicit and perform no model call.

**Gate:** projection/API/UI tests, TypeScript, ESLint, atomic commit.

## Final verification and review

1. Run all focused backend and frontend suites changed by the phases.
2. Run the broad backend suite and the frontend test suite.
3. Run whole-tree Ruff, frontend lint, and TypeScript checks.
4. Regenerate contracts once more and prove no drift.
5. Run `git diff --check`, inspect branch status, and review every commit against
   the design's non-goals and compatibility rules.
