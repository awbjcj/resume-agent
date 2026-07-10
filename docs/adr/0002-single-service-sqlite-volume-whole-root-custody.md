# 2. Cloud deploy is one service, SQLite on a volume, whole-root data custody

Date: 2026-07-10

## Status

Accepted

## Context

Deploying to Railway (single-tenant: the owner is the only user). The app's
state is not just database rows — the Data root spans the SQLite DB, profile
corpus, runs, mutable config (Source Manager writes `config/`), renders, and
the operational-secrets `.env`. Railway containers are ephemeral; volumes are
one-per-service and pin the service to one replica. Several connectors
(Tesla, Adzuna enrichment, LinkedIn, scrape recipes) require a visible local
browser that cannot exist in a cloud container.

## Decision

One Railway service serves both API and built SPA. The DB stays SQLite on a
single volume holding the entire Data root; no Postgres. Custody is
whole-root: `GET /api/admin/export` and `POST /api/admin/import` move the root
as one tarball (full replace, never a merge), and the cloud instance is the
single authoritative owner. Browser-requiring connectors are disabled in cloud
via `browser_enabled` and served by the Round-trip pull (export → local
browser pull → import) instead of a merge-sync endpoint.

Postgres was rejected because the file artifacts need the volume regardless,
so a managed DB removes little risk while adding a second service, a driver,
and a migration. Merge-sync was rejected as premature: whole-root moves need
no wire format for jobs, and ingest dedupe already makes re-pulls no-ops
inside a snapshot.

## Consequences

- One replica, no HA. Backups are the owner's job via the export endpoint;
  exports contain Operational secrets and are themselves secret material.
- Export/import must treat the WAL-mode DB specially (snapshot via SQLite
  backup, not a file copy) and refuse while runs are active.
- Do not mutate the cloud instance between an export and its re-import — the
  import clobbers everything since the export.
- Growing beyond one user (or wanting concurrent local+cloud use) reopens
  this: that is the trigger for Postgres and/or a merge-ingest endpoint, not
  an incremental patch on whole-root custody.
