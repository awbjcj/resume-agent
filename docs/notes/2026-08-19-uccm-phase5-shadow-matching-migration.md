# UCCM Phase 5 shadow-matching migration

Match Engine v2 now evaluates one typed requirement at a time against evidence-backed assertions and explicit requirement-lane facts. Shadow records persist the actual legacy coverage beside the precise v2 result.

## Compatibility and safety

- Legacy exact/adjacent/gap matching is still executed by `build_skill_match_context`; it is never reconstructed from a v2 status.
- Requirements with no legacy lane use `not_evaluated`, not a fabricated legacy gap.
- Hard credential checks use verified requirement-lane facts only. Exact-product checks cannot be bypassed by graph transfer.
- Traversal is bounded to approved, active, scope-visible edges, an allowlist of predicates, a confidence floor, and a maximum depth.
- Category, learned-domain, embedding, lexical, and co-occurrence similarity remain zero/non-covering features unless a later retrieval stage uses them only to shortlist candidates.
- Transfer and partial results retain the candidate label and never count as strict coverage.
- A profile matrix or typed requirement whose taxonomy revision differs from the effective snapshot is rejected as stale instead of blended.

## Evaluation and activation

The offline evaluator implements every release threshold in the design spec and rejects missing denominators, incomplete career/level coverage, unreviewed records, or absent reviewers. The committed JSONL record is explicitly `unreviewed`; it is a schema template and cannot authorize UCCM mode.

Rollback is configuration-only. Legacy results remain present, and the v2 records can be ignored without rewriting profile, job, or resume artifacts.
