# 13. has_progress requires real investment, not a bare Application row

Date: 2026-08-29

## Status

Accepted

## Context

`has_progress` returned True if any `Application` row existed for a job.
`services/board.py::upsert_application` creates that row unconditionally, so
saving status `ready` with no notes — a no-op by any reasonable reading —
permanently tripped the `delete_job` gate.

The application timeline (ADR-0012) makes this fire constantly rather than
occasionally: recording a single date would lock a job forever, including one
logged against the wrong company.

## Decision

An `Application` counts as progress only when it carries investment:

    status != "ready"
      OR notes is non-blank
      OR any ApplicationEvent exists
      OR resume_version_id / cover_letter_id is set

`ResumeVersion` and `CoverLetter` existence checks are unchanged, as is
`job.status in {approved, tailored, rendered}`.

The predicate is a single SQLAlchemy expression,
`repository.py::_application_investment_clause`, shared verbatim by
`has_progress` and `progressed_job_ids`. They are the same rule expressed
twice — `progressed_job_ids` exists only to batch it for board reads and prune
scans — and a silent divergence would mean the batched path deletes what the
single path refuses. Sharing the expression also keeps `progressed_job_ids`
to one query per child table; a Python-side filter would have reintroduced the
N+1 that function was written to remove.

## Consequences

- This **loosens a destructive gate**. Tests pin both directions: an empty
  `ready` row deletes; a row with one event refuses
  (`tests/test_has_progress_investment.py`), including a case asserting the
  batched and single predicates agree over a mixed fixture set.
- Jobs already stuck in existing databases become deletable. This is the
  intended repair, not a side effect.
- Two existing tests asserted the old behaviour and were updated to assert
  protection through *real* investment instead:
  `test_repository.py::test_has_progress_true_for_advanced_status_and_children`
  and `test_prune_run.py::test_prune_run_archives_junk_expires_old_and_skips_progress`.
- The gate's meaning is now "investment", matching its docstring, rather than
  "a row exists".
- Any future child table of `Application` must be added to
  `_application_investment_clause` — which updates both call sites at once.
