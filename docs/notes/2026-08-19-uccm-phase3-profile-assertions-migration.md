# UCCM Phase 3 profile-assertion migration

Profile builds now persist evidence-backed capability assertions, independent proficiency dimensions, UCCM layer projections, and legacy matrix rows in one atomic `matrix.json` artifact.

## Compatibility

- Existing matrix fields and row ordering remain unchanged. Rows are generated from each assertion's explicit `legacy_projection` metadata.
- Stored matrices without assertions still load with empty assertion/projection fields. When current facts or taxonomy are supplied, the existing freshness rules rebuild stale legacy artifacts.
- Assertions cite profile fact identifiers. A missing cited fact rejects the build instead of emitting an untraceable candidate claim.
- Job titles, taxonomy membership, and learned-domain proximity do not create assertions or favorable levels.
- Proficiency, autonomy, complexity, responsibility scope, and influence scope remain unknown unless a later reviewed policy has behavioral evidence.

## Revisions and rollback

Assertions record `profile-assertions-v1`, `term-typing-v1`, the facts SHA-256, and the complete effective taxonomy revision. Changing any semantic input rebuilds the atomic artifact.

Rollback requires no rewrite: legacy readers continue consuming `rows`, and older matrix files remain valid. Retain the assertion fields during rollback so evidence and reviewed profile state are not discarded.
