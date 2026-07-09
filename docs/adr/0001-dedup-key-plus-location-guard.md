# 1. Job identity is dedup_key plus a location guard; dedup_key is not unique

Date: 2026-07-08

## Status

Accepted

## Context

`compute_dedup_key` is `normalize(company)|normalize_title(title)`. Multi-location
same-title requisitions collapsed into one `Job` row, including when they shared
byte-identical description text and differed only by URL and location.

Putting location in the key was rejected because sources spell the same location
differently. A location-bearing key would prevent source-priority upgrades from
matching postings such as `Austin, TX` and `Austin, Texas, United States`.

## Decision

Keep the key location-free. `find_existing` requires `locations_compatible` on
the identical-description, `dedup_key`, and keyless-fingerprint branches. A
blank location is a wildcard; otherwise the normalized city segments before the
first comma must be token-subset-related. The URL branch remains unguarded.

Incompatible candidates fall through, so multi-location requisitions insert as
sibling rows sharing a `dedup_key`.

## Consequences

- `dedup_key` is deliberately not unique. Do not add a unique index or treat
  `GROUP BY dedup_key` as one row per job.
- Row identity is `dedup_key` plus compatible location. The guard belongs in
  matching, not in the merge decision.
- Existing collapsed rows are not split retroactively.
