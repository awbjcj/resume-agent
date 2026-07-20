# Rendered PDF Download Filenames — Design

**Date:** 2026-07-20
**Status:** Approved

## Problem

`GET /resume-versions/{id}/pdf` and `GET /cover-letters/{id}/pdf` stream the file
back with `filename=Path(pdf_path).name`, i.e. the on-disk storage name:
`resume-v{id}-{origin}.pdf` / `cover-letter-v{id}-{origin}.pdf`. That name carries
no company or job title, so once a user downloads a handful of these into one
Downloads folder, they're indistinguishable and hard to manage.

## Decision

Only the **download filename** (`Content-Disposition`) changes — the on-disk
storage path/name inside `output/{company}-{title}-{jobId}/` is untouched, so
`render/export.py`'s manifest, bulk export, and re-render lookups are unaffected.

New format, built from the version's/cover letter's parent `Job`:

- Resume: `{Company}-{Title}-Resume-v{versionId}.pdf`
- Cover letter: `{Company}-{Title}-CoverLetter-v{coverLetterId}.pdf`

Example: `Acme_Corp-Software_Engineer-Resume-v3.pdf`.

- The version/cover-letter primary-key id is reused as `vN` — it's already
  globally unique (autoincrement PK across the whole table, not scoped per job),
  so two re-renders or two different jobs never collide, and no extra date
  suffix is needed for uniqueness.
- Company/title are sanitized **case-preserving** (unlike the existing lowercase
  `_slug` helper used for the internal folder name, which is meant for URLs/paths
  not human reading): strip characters that aren't letters, digits, underscore,
  whitespace, or hyphen, then collapse runs of whitespace/hyphens into a single
  underscore, then strip leading/trailing underscores.
- Missing/blank company or title fall back to `"Company"` / `"Role"` (mirrors the
  existing internal fallback words, just re-cased).

## Implementation sketch

`render/export.py` (alongside the existing `resume_pdf_name` / `cover_letter_pdf_name`):

```python
def _friendly_part(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE).strip()
    cleaned = re.sub(r"[\s-]+", "_", cleaned).strip("_")
    return cleaned or fallback


def resume_download_name(job: Job, version: ResumeVersion) -> str:
    company = _friendly_part(job.company or "", "Company")
    title = _friendly_part(job.title or "", "Role")
    return f"{company}-{title}-Resume-v{version.id}.pdf"


def cover_letter_download_name(job: Job, cover_letter: CoverLetter) -> str:
    company = _friendly_part(job.company or "", "Company")
    title = _friendly_part(job.title or "", "Role")
    return f"{company}-{title}-CoverLetter-v{cover_letter.id}.pdf"
```

`api/routers/resumes.py::download_pdf` and
`api/routers/cover_letters.py::download_cover_letter_pdf` fetch the parent `Job`
via `get_job(session, version.job_id)` (resume) / `get_job(session,
cover_letter.job_id)` (cover letter) and pass the friendly name as `filename=`.
If the job is unexpectedly missing (defensive only — `has_progress` already
blocks deleting a job with a rendered version/cover letter), fall back to
today's `Path(pdf_path).name` so the endpoint never 404s or crashes over a
naming concern.

## Testing

- Unit tests for `resume_download_name` / `cover_letter_download_name`: normal
  case, missing/blank company or title (fallback), special characters
  (punctuation, multiple spaces, unicode).
- Router tests for both download endpoints asserting the friendly filename
  appears in the response's `Content-Disposition` header.

## Out of scope

- On-disk storage filenames, `manifest.json` entries, and the bulk job-folder
  export — unchanged.
- Sequential per-job numbering, dates, or origin/round in the download name —
  the version id already disambiguates.
