# 4. Company renames recompute dedup_key and skip on collision

Date: 2026-07-13

## Status

Accepted

## Context

Jobs pulled from token-addressed ATS boards stored the raw account token
(`acmecorp`, a Workday tenant) as `company`. Connectors now resolve real
organization names from ATS payloads, and existing rows can be healed on
re-pull or by a backfill command.

`compute_dedup_key` is `normalize(company)|normalize_title(title)`
(ADR-0001), so renaming a company silently changes a row's dedup
identity. A cosmetic display-time mapping was rejected: the token would
survive in the DB, exports, and dedup keys, and every read surface would
need the mapping.

A rename can also collide: a properly-named row for the same posting may
already exist (e.g. manually added), so the renamed row's recomputed key
plus a compatible location would duplicate it.

## Decision

- Any path that rewrites `company` (the `RefreshCompany` merge action or
  the `fix-company-names` backfill) recomputes `dedup_key` atomically
  with the rename. `content_fingerprint` is JD-only and is untouched.
- The rename knowledge travels on the job: `IncomingJob.stale_company`
  carries the superseded fallback name; the merge decision stays pure.
- On collision — another non-archived row already holds the target key
  with a compatible location — the rename is skipped, never merged. The
  organic heal downgrades to Skip silently in the DB-bound layer
  (`save_or_upgrade`, which owns DB-bound checks per ADR-0001); the
  backfill reports each conflicting pair for human resolution.

## Consequences

- A renamed row keeps its id, status, applications, versions, and
  frozen `jd_text`; only `company` and `dedup_key` change.
- Duplicate rows created before resolution existed are surfaced, not
  auto-merged; progress is never moved between rows automatically.
- Rows whose rename was skipped keep the token name until the human
  resolves the duplicate — visible staleness is preferred over a wrong
  merge.
