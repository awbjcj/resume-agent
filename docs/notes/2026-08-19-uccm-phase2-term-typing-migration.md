# UCCM Phase 2 term-typing migration

Phase 2 adds a source-preserving type-decision service and tenant-scoped correction ledger. It does not rewrite the approved capability graph, profile facts, job criteria, or legacy taxonomy artifacts.

## Compatibility

- Existing profile and job data remain unchanged until their Phase 3 and Phase 4 builders opt into typed decisions.
- Ambiguous terms and invalid provider output remain `unknown`; they are not coerced to `skill`.
- The API additions are additive. Existing taxonomy routes and generated client operations keep their contracts.
- Corrections are stored at `data/taxonomy/term_type_corrections.json` within the active tenant workspace. The server records the authenticated user identifier, or `local-user` in local mode.

## Revisions and rollback

Every decision records `term-typing-v1`. A correction targets that policy revision and is rejected if replay would cross a revision boundary or an unexpected prior type.

Rollback requires no data migration: switch consumers back to their legacy projections or remove the Phase 2 callers. Retain the correction ledger so reviewed intent can be replayed after re-enabling the phase. The ledger never mutates the global graph.
