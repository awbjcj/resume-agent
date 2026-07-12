# 3. Tenancy context propagates via a contextvar, not parameter threading

Date: 2026-07-12

## Status

Accepted

## Context

Multi-user tenancy needs the per-user context (effective Settings, user id,
Workspace paths, engine) to reach code that today reads process-global state:
`get_settings()` is called in 36 files deep in the domain layer (agent
builders, connectors, profile extraction), and `llm_runner.acall` — the seam
that must record per-user token usage — receives no user identity at all.
Threading an explicit `UserContext` parameter through every call chain would
touch most of the domain layer, conflict with five pending unexecuted plans,
and add a ceremony parameter to every future function.

## Decision

A `contextvars.ContextVar` holds the active `UserContext`. Exactly three
places set it: the API auth dependency (per request), the RunManager worker
wrapper (per background run), and the CLI entrypoint (per invocation).
`get_settings()` returns the active context's effective Settings when one is
set, falling back to env-derived settings otherwise (tests, legacy local
mode); `acall` reads the active user id to record usage events. Crossing an
`asyncio.run` or threadpool boundary must capture and restore the context
explicitly — that capture is part of the seam's contract.

Explicit parameter threading was rejected for diff size and permanent
signature ceremony; a hybrid (explicit at service entrypoints, contextvar at
leaves) was rejected because two propagation mechanisms must be kept coherent
forever.

## Consequences

- Implicit state is now THE tenancy invariant: any new entrypoint that spawns
  work (thread, task, executor) must propagate the contextvar or requests
  will silently run against the wrong (or no) workspace. Tests must assert
  isolation under concurrent mixed-user requests.
- Code must never cache the result of `get_settings()` across requests.
- The escape hatch is deliberate: with no context set, behavior is identical
  to today's single-user mode, which keeps the offline test suite and legacy
  local CLI working unchanged.
