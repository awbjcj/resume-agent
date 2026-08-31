# Codex handoff: effective taxonomy read contract

You are implementing the first compatibility-first slice of the Universal Career Capability Matrix redesign in an existing resume/career application.

Read these two documents first:
1. skill-taxonomy-current-state-and-research-handoff.md
2. universal-career-capability-matrix-research-and-codex-handoff.md

Do not implement the full capability graph in this slice.

OBJECTIVE
Create one canonical effective-taxonomy read contract and propagate a complete taxonomy revision through profile matrix, match-gap, evidence planning, tailoring, and stored resume attempts.

CURRENT VERIFIED ISSUE
- Match-gap and taxonomy maintenance replay taxonomy_corrections.json through the effective taxonomy.
- The tailoring entry point currently reads profile/cluster_map.json directly and applies profile overrides, so correction-only aliases, moves, or merges may not be visible.
- The candidate truth/provenance gates must not change.
- Existing matching semantics remain exact / same-domain adjacent / gap for this slice.

REQUIRED INVESTIGATION
1. Inspect the repository and confirm the current read paths.
2. Add a regression fixture with a generated ClusterMap and candidate matrix.
3. Apply, only through taxonomy_corrections.json:
   - one alias;
   - one skill-to-domain move; and
   - one domain merge.
4. Run match-gap and tailoring's build_skill_match_context path.
5. Record the failing behavior before the fix.

IMPLEMENTATION REQUIREMENTS
- Prefer using or extending TaxonomyCustody's coherent snapshot rather than adding a second competing service.
- Expose one immutable EffectiveTaxonomySnapshot containing the effective ClusterMap and a complete revision over generated map, correction ledger, and lifecycle state.
- Route services/profile_build.py, services/match_gap.py, services/tailoring.py, and relevant downstream portfolio/tailoring calls through that snapshot or a single adapter.
- Persist the complete taxonomy revision in matrix metadata and stored resume-attempt metadata.
- Make freshness checks fail when any component of the effective taxonomy revision changes.
- Keep user correction precedence and idempotent replay.
- Keep current fact-lock, provenance, skill-naming, numeric-evidence, and adjacent-name rules unchanged.
- Do not materialize corrections back into cluster_map.json as the primary fix; consumers must read the effective state.
- Do not add O*NET, ESCO, new categories, proficiency, or graph matching in this slice.

LIKELY FILES
- src/resume_tailor_harness/taxonomy/custody.py
- src/resume_tailor_harness/taxonomy/clusters.py
- src/resume_tailor_harness/taxonomy/corrections.py
- src/resume_tailor_harness/taxonomy/state.py
- src/resume_tailor_harness/profile/matrix.py
- src/resume_tailor_harness/services/profile_build.py
- src/resume_tailor_harness/services/match_gap.py
- src/resume_tailor_harness/services/tailoring.py
- src/resume_tailor_harness/tailor/service.py
- relevant persistence/model files discovered during inspection

TESTS
Add or update tests proving:
- correction-only alias is identical in match-gap and tailoring;
- correction-only move is identical in match-gap and tailoring;
- correction-only merge is identical in match-gap and tailoring;
- matrix freshness changes for generated map, correction ledger, or lifecycle state changes;
- resume attempts retain complete taxonomy revision;
- correction replay and revision generation are deterministic and idempotent;
- existing exact/adjacent/gap, provenance, and fact-lock tests still pass.

DELIVERABLES
1. Code and tests.
2. A brief migration note describing the new read contract and rollback.
3. A before/after test showing the verified divergence is closed.
4. A list of remaining seams for the later typed capability graph, without implementing them.

QUALITY GATE
Do not claim completion until the focused tests and the repository's relevant full test suite pass. Include exact commands and outputs in the final implementation report.
