# UCCM Phase 4 typed-job-requirement migration

Discovery now binds the existing lean `JobCriteriaExtract` result into source-grounded typed requirements before persisting `criteria_json`. No SQL migration is required because job criteria are already stored as extensible JSON.

## Compatibility

- `must_have_skills`, `nice_to_have_skills`, and `tech_stack` remain populated and are reproduced by the typed records. A mismatch is stored as a reconciliation issue.
- New extractions retain exact source text and `[start,end)` offsets whenever the extracted phrase is present in the JD. An unlocated phrase is retained with `unlocated_extraction` provenance and an explicit issue; offsets are never fabricated.
- Old list-only jobs adapt with `legacy_list_item` provenance and unknown offsets.
- The lean provider-facing extraction schema is unchanged. Requirement binding runs after structured extraction so provider grammar complexity does not increase.
- Ambiguous terms remain unknown. In shadow/UCCM modes an optional schema-validated model assistant may classify them; invalid output or provider failure remains an observable unknown.

## Revisions and rollback

Every typed record stores `job-requirements-v1`, the effective taxonomy revision supplied by the profile artifact, and its source-bound term-decision ID. The job-level extraction revision hashes the complete typed record set and policy inputs.

Rollback requires no rewrite: legacy consumers continue reading the three existing lists and older jobs remain valid. Retain additive typed fields during rollback so exact source spans and reviewable provenance are not lost.
