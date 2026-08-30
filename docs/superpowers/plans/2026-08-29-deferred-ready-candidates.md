# Deferred Ready Candidates — Implementation Plan

**Goal:** Complete the deferred product work whose dependencies and interfaces are already settled: reflection-informed mock interviews, named board views, durable run-completion history, and dashboard practice/source-health insights.

**Architecture:** Each candidate remains an independent vertical slice. Interview reflections are copied into the immutable session context. Board views persist the existing URL filter representation without creating a second filter model. Run completions use a dedicated durable table and the existing run terminal lifecycle. Dashboard insights are projections over ended interview sessions and open source errors, with no new background work.

## Global constraints

- Preserve the company-intelligence implementation and reuse its interview context and run-label extensions.
- Keep mock interviews practice-only: reflections are untrusted coaching context and never resume evidence or profile writes.
- Keep saved views workspace-scoped through the existing per-workspace database boundary.
- Keep Gmail application notifications and generic run history as separate durable concepts.
- Use `CamelModel` at API boundaries and regenerate OpenAPI and TypeScript contracts after schema changes.
- Deliver and verify one thin slice at a time before broad repository checks.

## Slice 1 — Reflection-informed mock interviews

- Add a bounded typed reflection snapshot to `InterviewContext`.
- Load only non-empty reflections from interview-kind application events for the selected job.
- Render the frozen reflections in an explicitly untrusted coaching block.
- Preserve compatibility with session JSON written before the field existed.

## Slice 2 — Saved and named board views

- Persist a unique view name, board identity, and canonical query string.
- Add workspace-scoped CRUD endpoints with duplicate-name conflict handling.
- Add an accessible board control that saves the current filters, applies a saved view, and deletes a view.
- Reuse the existing filter URL serializer as the canonical representation.

## Slice 3 — Durable run-completion history

- Persist one terminal record per run for succeeded, failed, and cancelled outcomes.
- Add list and read-state endpoints without coupling records to an application.
- Extend the notifications surface with unread run history while retaining existing application actions.
- Make terminal callback failures non-fatal to run execution.

## Slice 4 — Dashboard practice and source health

- Derive completed/scored interview counts, average/latest score, and score change from ended sessions.
- Derive current source health from open source error records.
- Add a compact responsive dashboard card with clear empty and healthy states.

## Verification

1. Focused backend tests for each service, router, and run lifecycle extension.
2. Focused frontend tests for saved views, notifications, and dashboard insights.
3. Regenerate API contracts after all backend schemas settle.
4. Run backend lint/type checks and frontend lint/type checks.
5. Run broad backend and frontend suites where the local environment permits.
6. Review `git diff --check`, worktree status, and the final diff for unrelated changes.
