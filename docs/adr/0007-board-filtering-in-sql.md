# ADR 0007: Board filtering and paging live in SQL

## Status

Accepted — 2026-07-24

## Context

The board read path materialized every matching `Job`, projected child data, and
then filtered, sorted, and paged in Python. A 2,000-row pipeline benchmark took
about 262 ms in the original profile while SQL accounted for only about 6% of
the request. Later pages paid the same whole-board cost as page 1, and pipeline
responses included complete job descriptions.

## Decision

`tracking/board_query.py` is the single owner of board selection. It translates
`BoardFilter` into SQL predicates and stable ordering, pages job ids in SQL, and
computes leave-one-out facet counts with `GROUP BY`. Row projection runs only
for the returned jobs.

Board responses carry a cleaned `jdPreview` of at most 400 characters. Full job
description text remains available from job detail only. Facets are returned on
page 1 and are `null` on later pages.

## Consequences

- Later pages avoid whole-board projection and facet work.
- Filter, sort, and preset behavior has one server-side implementation.
- `company_size` and `skills` are computed facets, so their displayed values
  must be inverted to stored values at the filter boundary.
- Adding a facet means adding its SQL expression to `FACET_SPECS`, plus focused
  filter and leave-one-out count tests; it does not mean adding a Python
  predicate over materialized rows.
- The OpenAPI and generated TypeScript contracts must be regenerated whenever
  the board response changes.
