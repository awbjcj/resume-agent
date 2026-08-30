# Company intelligence v2 — evidence, role preparation, and action design

**Date:** 2026-08-30
**Status:** Approved for phased implementation

## Problem

The current company-intelligence feature is intentionally narrow and reliable. It
stores one company-wide dossier, rejects citations that did not occur in the
research transcript, keeps expired evidence visible, refreshes only on explicit
request, and freezes the current dossier into new mock-interview sessions.

That foundation has three limitations:

1. A cited claim does not explain whether it is corroborated, inferred, recent, or
   based on one source.
2. Refresh replaces the saved payload, so the user cannot see what changed or
   recover the evidence used before the latest refresh.
3. The dossier is displayed and injected into mock interviews, but it is not
   converted into a role-specific preparation artifact using the exact JD,
   submitted resume, interview stage, and earlier-round reflections.

Comparable job-search systems increasingly connect company research to staged
interview preparation, reusable stories, outcome learning, and approval-gated
contact research. This design adds those capabilities without weakening this
repository's stricter provenance and human-control boundaries.

## Goals

- Make evidence quality legible at claim and source level.
- Preserve every explicit research refresh as an immutable version and show a
  deterministic diff from the previous version.
- Offer explicit quick, standard, and deep research modes with clear cost/depth
  expectations.
- Generate a job-specific preparation brief from frozen inputs without polluting
  the company-wide dossier with candidate claims.
- Reuse existing application-event reflections and interviewer data as the
  approved feedback loop for later preparation.
- Add public-source hiring-contact research as a separate, draft-only artifact.
- Let users compare two or three active roles using existing evidence rather than
  asking another model to resummarize it.

## Non-goals and safety boundaries

- No provider or model call on any GET endpoint or job-detail read.
- No automatic refresh when evidence becomes stale.
- No automatic outreach, email send, profile mutation, or application submission.
- No guessed contact identity or private contact-data enrichment.
- No model-authored numeric confidence score. The server owns deterministic
  verification states; the UI explains them.
- No company-research claim may mutate a resume, cover letter, application event,
  or interview transcript.
- H-1B evidence remains a separate canonical resource.

## Canonical model

### Evidence source

The existing `source_type` compatibility field remains `official | independent`.
New fields add precision without breaking old payloads:

- `source_tier`: `company_official | government_or_regulatory |
  reputable_independent | employee_or_community | other`
- `published_at`: optional source publication timestamp
- `last_verified_at`: the refresh timestamp at which the URL was grounded

### Evidence insight

New fields:

- `verification_state`: `corroborated | single_source | inferred`
- `as_of`: optional date the claim describes
- `conflicting_evidence`: concise disagreement note, still citation-grounded

The server derives the strongest allowed state:

- `corroborated` requires citations from at least two distinct source authorities.
- `single_source` is the default for one authority.
- `inferred` is allowed only when the formatter explicitly marks the claim as an
  inference and at least one grounded citation remains.

Unknown or uncited claims continue to be discarded.

### Immutable version

`CompanyIntelligenceVersionRow` stores one row for every successful explicit
refresh. The existing `CompanyIntelligenceEvidenceRow` remains the fast current
projection and compatibility source.

Each evidence payload carries:

- `version_id`, `version_number`, `previous_version_id`
- `research_depth`
- a deterministic change set: added/removed/changed axes and sources

On the first v2 refresh of a legacy company, the service snapshots the existing
current row as version 1 before appending the new version. Failed refreshes create
no version and leave the current projection unchanged.

## Role-preparation brief

The role brief is job-scoped and persisted separately from company evidence. Its
frozen input references are:

- job id and exact JD text
- current company-intelligence version
- selected resume version when one exists; otherwise the latest job resume
- current application status
- relevant application-event kind, interviewer, result, notes, and reflection

The output contains:

- role and company positioning summary
- prioritized competencies
- likely questions with question type and rationale
- candidate story prompts grounded only in the frozen resume
- concerns and preparation actions
- questions to ask the interviewer
- recruiter-verification questions
- earlier-round signals used in the brief

Generation is explicit and asynchronous. Company citations are revalidated
against the frozen dossier. Existing briefs remain readable after company,
resume, or event data changes and show that their inputs are older.

## Hiring-contact intelligence

Contact research is a separate job-scoped resource because it contains personal
names and roles. It searches public company pages, team pages, talks, and news;
professional-network login scraping is out of scope.

Each result stores name, public role/title, contact type, source URL, verification
state, why the person may be relevant, and copy-only message drafts. Exact source
URLs must occur in the search transcript. If no person is verified, the artifact
contains generic role-addressed drafts and says that no contact was confirmed.

## Deterministic role comparison

A comparison accepts two or three job ids and projects already stored data:

- role/company and fit score
- application stage
- company-evidence freshness, depth, source count, and strongest verification
- H-1B status when available
- latest structured offer total when present

No model call is required. Missing data remains missing instead of being guessed.

## API shape

- Existing current resource remains:
  `GET /api/jobs/{job_id}/company-intelligence`
- Version collection:
  `GET /api/jobs/{job_id}/company-intelligence/versions`
- Explicit refresh accepts optional `{ depth }`:
  `POST /api/jobs/{job_id}/company-intelligence/refreshes`
- Role-preparation resource and refresh collection:
  `GET /api/jobs/{job_id}/role-preparation-brief`
  `POST /api/jobs/{job_id}/role-preparation-brief/refreshes`
- Hiring-contact resource and refresh collection:
  `GET /api/jobs/{job_id}/hiring-contact-intelligence`
  `POST /api/jobs/{job_id}/hiring-contact-intelligence/refreshes`
- Deterministic comparison:
  `POST /api/jobs/company-intelligence-comparisons`

All optional generated resources use state-discriminated `unavailable | empty |
ready` responses. Background runs keep job correlation metadata while singleton
keys use the actual artifact identity.

## UI

The Research tab remains the home for company evidence and gains three aligned
sections:

1. Company dossier — depth selector, explicit refresh, quality badges, source
   dates, and a compact "what changed" block.
2. Role preparation — explicit generation, frozen-input metadata, competencies,
   likely questions, story prompts, concerns, and questions to ask.
3. Hiring contacts — explicit public-source search, verified contact cards, and
   copy-only drafts with a permanent no-send notice.

Comparison lives in the Applications workspace because selection spans jobs.

## Compatibility

- Old evidence JSON validates through defaults.
- Existing GET responses retain current fields and add new optional fields.
- The undocumented legacy refresh alias remains accepted.
- Existing interview-session JSON remains valid.
- No existing table or API route is removed.
