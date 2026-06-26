# Closed-Loop Resume Interaction, Versioned Local Output, and Gmail Notifications

**Date:** 2026-06-26
**Status:** Approved (design); ready for implementation planning
**Branch context:** builds on `feat/source-manager`

## Summary

Three semi-independent enhancements that, together, make the resume-agent
workflow closed-loop:

1. **Prompt-driven revision** — the user gives a free-text instruction to revise
   a tailored resume or cover letter; the system produces a new, fact-locked
   version.
2. **Organized, versioned local output** — every version is mirrored to a
   well-structured per-job folder with a manifest, for human lookup.
3. **Gmail notifications** — the existing inbound Gmail pipeline is surfaced in
   the frontend as reviewable notifications that apply application-status
   transitions on accept.

The phases are independently shippable. Phase 1 delivers the headline value on
its own; Phases 2 and 3 build on the artifacts and data it produces.

---

## Phase 1 — Prompt-driven revision (closing the loop)

### Goal

Let the user type an instruction ("drop the volunteering section," "lead with
Python," "make the summary more concise") and get a new resume/cover-letter
version that honors it while preserving fact-lock.

### Interaction model

Single-shot **instructed revision** (not a multi-turn chat): one instruction →
one new version. This reuses the existing reviser seam conceptually but routes
through a purpose-built agent (below).

### Backend

- **New endpoints (synchronous, `200`):**
  - `POST /api/resume-versions/{id}/revise` body `{ instruction: str, reReview?: bool }`
    → returns the new `ResumeVersionOut`.
  - `POST /api/cover-letters/{id}/revise` body `{ instruction: str }`
    → returns the new cover-letter projection.
  - Synchronous by design: a single interactive edit is a request/response with
    a spinner, not a batch op. This is a deliberate exception to the "long ops =
    Run + SSE" convention, which earns its complexity only for multi-job batches.
- **Dedicated revision agents.** Add a resume-revision agent and a
  cover-letter-revision agent to the agent bundle, each system-prompted for
  *human instructions*: "apply the user's instruction, change only what is
  asked, keep everything else intact, preserve fact-lock (every bullet keeps a
  valid `provenance` id)." Output type stays `ResumeContent` /
  `CoverLetterContent`.
- **New composer.** `compose_user_revision_input(content, instruction, facts)`
  frames the instruction as a directive (distinct from
  `compose_revise_input`, which consumes reviewer critique lists).
- **Review depth.** Default: run only the cheap deterministic provenance /
  fact-check gate (the hard invariant). The `reReview: true` flag opts into the
  full scoring panel. A user-revised version that did not run the panel carries a
  null `review_score` (honest: "not panel-scored").
- **Fact-lock stays a hard gate.** A revision that introduces an unsupported
  claim is **persisted and flagged** `fact_check_passed = false` (surfaced red in
  the UI), never silently discarded. The user can rephrase, keep the prior
  version, or add a fact to `facts.json`.

### Data model

Extend `ResumeVersion` (nullable additive columns):

| Column | Type | Meaning |
| --- | --- | --- |
| `origin` | `str` (`"tailor"` \| `"revision"`) | how this version was produced |
| `instruction` | `str \| None` | the user instruction (revisions only) |
| `parent_version_id` | `int \| None` (self-FK) | lineage pointer |

- Revisions get `round = parent.round`; they are distinguished from auto-tailor
  rounds by `origin` and ordered by `created_at`. Lineage is a parent-pointer
  chain (a user may revise version 3, not just the latest).
- Every existing consumer (PDF download, `Application.resume_version_id`,
  frontend version list) keeps working unchanged — a revision is just another
  renderable snapshot row.

Mirror the same three columns onto `CoverLetter` (`origin`, `instruction`,
`parent_id`). Multiple `CoverLetter` rows per job become the cover-letter
"version list."

### Version selection (the "applied" link)

Today `Application.resume_version_id` is **never assigned** anywhere
(`upsert_application` writes only `status`/`notes`). Closing the loop requires
recording which artifacts the user is applying with.

- **Explicit selection.** A "Use for application" action in the Versions tab sets
  `Application.resume_version_id` (creating the `Application` if needed). Add a
  new `Application.cover_letter_id` column and a "Use this cover letter" action
  in the Cover Letters tab.
- **Default.** When the user has not chosen, the "current" artifact is the latest
  fact-check-passing version. The chosen ids drive the manifest's "applied"
  marker (Phase 2) and the frontend's "current" highlight.

### Frontend

- **Versions tab (`JobModal`)** — extend each row: show `origin` (tailor vs
  revision) and the `instruction` text, indicate lineage ("revised from round
  N"), add an instruction input + Revise button, a `reReview` toggle, and a "Use
  for application" control. Failed fact-check renders red.
- **New Cover Letters tab** — none exists today. Lists `CoverLetter` rows with
  the same revise + "use this cover letter" affordances.

---

## Phase 2 — Organized, versioned local output

### Goal

Mirror every version to a human-navigable folder structure; "version control"
here means immutable, version-keyed files plus a manifest — the **database stays
the authoritative version store**.

### Layout

```
output/{company}-{title}-{jobId}/
  resume-v{n}-{origin}.pdf
  resume-v{n}-{origin}.content.json
  cover-letter-v{n}.pdf
  cover-letter-v{n}.content.json
  manifest.json
```

- Filenames are immutable and version-keyed (never overwritten).
- `content.json` snapshots make a folder self-describing without the DB.
- `manifest.json` is the table of contents: every version with its instruction,
  fact-check status, timestamp, origin, and the **applied** marker (resolved from
  `Application.resume_version_id` / `cover_letter_id`).

### Mechanism

- **`export_job_artifacts(session, job_id)`** — an idempotent projection that
  rewrites the entire job folder + manifest from current DB state. Called after
  `tailor`, `revise`, and `render`. If the mirror ever drifts, re-running export
  makes it correct.
- **Render writes in place.** The render path writes its PDF straight into the
  per-job folder (one canonical location, no copies); `export` fills in
  `content.json` + `manifest.json` and organizes the tree.
- **CLI `resume-agent export [--all]`** — backfills `content.json`/`manifest.json`
  and reorganizes existing jobs in one shot.

All filesystem-layout logic lives in this one testable projection; the render
path owns only PDF generation.

---

## Phase 3 — Gmail notifications (inbound surfacing)

### Goal

Turn the existing deferred, CLI-only inbound Gmail pipeline (fetch → match →
classify → propose status transitions) into reviewable in-app notifications that
apply application-status changes on accept.

### Flow

- **Sync trigger** runs as a **Run + SSE** op (network fetch over Gmail, by the
  long-ops convention).
- The pipeline now **upserts `Notification` rows** instead of returning ephemeral
  proposals.
- The frontend **notifications surface** (badge + inbox) shows each pending
  proposal ("Interview at Acme — from email 'Next steps…'"). The user **accepts**
  (applies the `Application` status transition, flips to `accepted`) or
  **dismisses** (flips to `dismissed`, suppressed forever).

### Data model

New `Notification` table:

| Column | Type | Meaning |
| --- | --- | --- |
| `id` | `int` PK | |
| `application_id` | `int` FK | target application |
| `kind` | `str` | classification (rejection/interview/offer/…) |
| `proposed_status` | `str` | the forward transition |
| `evidence` | `str` | email subject/snippet shown to the user |
| `message_id` | `str` | Gmail message id (dedup key) |
| `state` | `str` | `pending` \| `accepted` \| `dismissed` |
| `created_at` | `datetime` | |

- **Idempotent upsert** keyed on `(application_id, message_id)` — re-syncing never
  duplicates a proposal or resurrects a dismissed one.
- **`EmailMessage` gains `message_id`** — currently the Gmail message id is
  fetched as `ref["id"]` in `fetch_recent_messages` but discarded; surface it.
  Keyed on the message id, not `thread_id`, because one thread can carry both an
  interview and a later offer email that must each surface.

The human-review gate is intentional: classification can misfire (e.g. "we'll
keep your resume on file"), so changes are proposed, not auto-applied.

---

## Cross-cutting concerns

- **Contracts.** New endpoints regenerate `contracts/openapi.json` +
  `contracts/ts/api.ts` via `scripts/gen_ts_client.sh`; the
  `test_openapi_contract.py` drift gate enforces it.
- **Migration.** New columns on `ResumeVersion`/`CoverLetter`/`Application` and
  the new `Notification` table need a real migration step (SQLite `create_all`
  does not alter existing tables). Backfill existing rows with `origin="tailor"`.
- **Testing.** Follows existing offline conventions — fake the revision agents,
  fixture the Gmail payloads. Assert: fact-gate flagging on unsupported-claim
  revisions, idempotent `Notification` upsert across re-syncs, and
  `export_job_artifacts` idempotency (running twice yields identical output).

## Out of scope (YAGNI)

- Multi-turn conversational chat with a resume (single-shot only).
- Literal `git` VCS over `output/` (DB is the version store).
- Outbound notification emails to the user (Gmail integration stays inbound).
- Auto-applying Gmail-derived status changes without review.
