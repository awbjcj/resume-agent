# UCCM Phase 1 Graph Adapter Migration

## Persisted data

Phase 1 writes no graph artifact. Existing `cluster_map.json`, correction ledger,
taxonomy state, profile overrides, matrices, and resume versions remain readable.
New matrices and resume versions add a nested capability revision to the existing
taxonomy manifest.

## Modes

- `CAREER_CAPABILITY_MODE=legacy` (default): Phase 0 behavior; no graph build.
- `CAREER_CAPABILITY_MODE=shadow`: build and validate the graph, serve the Phase 0 map.
- `CAREER_CAPABILITY_MODE=uccm`: serve the graph-derived legacy projection after exact equality validation.

All three modes use the current exact/adjacent/gap matcher. Phase 1 does not change
ranking, suggestions, tailoring, or candidate claims.

## Rollback

Set `CAREER_CAPABILITY_MODE=legacy` and restart the API and workers. No data deletion,
backfill, or schema downgrade is required. Nested revision metadata remains historical
provenance and is safe for older readers because the surrounding models are additive.

## Failure behavior

Graph validation or projection mismatch returns the Phase 0 map, preserves the Phase 0
semantic revision, and records `capabilityStatus=fallback` plus a stable error code.
No fallback writes or rewrites taxonomy inputs.

## Data retained after rollback

Existing taxonomy files, correction events projected in historical snapshots, matrix
manifests, and resume-version manifests remain. No graph database or graph JSON file
exists to clean up.
