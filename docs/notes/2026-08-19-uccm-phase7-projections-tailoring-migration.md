# UCCM Phase 7 projection and tailoring migration

Phase 7 is additive and does not require a database migration.

- `/api/match-gap` keeps every legacy field and may additionally emit the UCCM profile projection, typed requirements, shadow matches, and pinned revision metadata.
- Generated clients treat the new scalar metadata as optional so older fixtures and consumers remain valid.
- The match-gap page keeps the legacy constellation and adds a backend-driven career capability matrix when coherent UCCM artifacts are available.
- Each new UCCM tailoring attempt stores its complete frozen context under `taxonomy_manifest_json.uccm_tailoring_context`; resume versions written before this phase continue to load without that key.
- Tailoring derives `SkillMatchContext` from the frozen v2 context. Transferable and partial results use the candidate capability's actual name and never project the job's target term as a candidate claim.

Rollback is configuration-only: switch `CAREER_CAPABILITY_MODE` to `shadow` or `legacy`. Existing resume versions and legacy match-gap fields remain readable; the additive context is ignored by older readers.
