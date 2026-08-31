# Rendered PDF Download Filenames Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single-file resume/cover-letter PDF downloads save with a friendly,
company/title-bearing filename instead of the internal `resume-v{id}-{origin}.pdf`
storage name, so users can tell downloaded PDFs apart.

**Architecture:** Two new pure functions in `render/export.py` compute a
case-preserving, filesystem-safe `{Company}-{Title}-Resume-v{id}.pdf` /
`{Company}-{Title}-CoverLetter-v{id}.pdf` name from a `Job` plus a
`ResumeVersion`/`CoverLetter`. The two existing single-file download routes
(`resumes.py::download_pdf`, `cover_letters.py::download_cover_letter_pdf`)
look up the parent `Job` and pass that name as `FileResponse(..., filename=...)`.
On-disk storage paths, `manifest.json`, and bulk export are untouched.

**Tech Stack:** Python 3.13, FastAPI, SQLModel, pytest.

## Global Constraints

- Only the download `filename=` changes — on-disk storage names/paths in
  `render/export.py` (`resume_pdf_name`, `cover_letter_pdf_name`, `job_dir`,
  `build_manifest`) are not modified.
- Format: `{Company}-{Title}-Resume-v{versionId}.pdf` and
  `{Company}-{Title}-CoverLetter-v{coverLetterId}.pdf`, e.g.
  `Acme_Corp-Software_Engineer-Resume-v3.pdf`.
- Sanitizing preserves original casing (unlike the existing lowercase `_slug`):
  strip characters that aren't letters/digits/underscore/whitespace/hyphen,
  collapse runs of whitespace/hyphens into a single underscore, strip
  leading/trailing underscores.
- Missing/blank company or title fall back to `"Company"` / `"Role"`.
- If the parent `Job` can't be found (defensive only), fall back to today's
  `Path(pdf_path).name` behavior — the endpoint must never 404 or crash over a
  naming concern.

---

### Task 1: Friendly filename helpers in `render/export.py`

**Files:**
- Modify: `src/resume_tailor_harness/render/export.py`
- Test: `tests/test_render_export.py`

**Interfaces:**
- Produces: `resume_download_name(job: Job, version: ResumeVersion) -> str` and
  `cover_letter_download_name(job: Job, cover_letter: CoverLetter) -> str`, both
  importable from `resume_tailor_harness.render.export`. Later tasks call these with a
  `Job` (has `.company: str | None`, `.title: str | None`) and the matching
  `ResumeVersion`/`CoverLetter` (has `.id: int | None`).

- [x] **Step 1: Write the failing tests**

Add to `tests/test_render_export.py` (near `test_job_slug_and_version_filenames`,
using the same imports already in that file — add `cover_letter_download_name`
and `resume_download_name` to the existing `from resume_tailor_harness.render.export
import (...)` block):

```python
def test_resume_download_name_uses_company_and_title():
    job = Job(id=42, source="manual", company="Acme Corp", title="Senior Engineer")
    version = ResumeVersion(id=7, job_id=42, round=1, origin="revision")

    assert resume_download_name(job, version) == "Acme_Corp-Senior_Engineer-Resume-v7.pdf"


def test_cover_letter_download_name_uses_company_and_title():
    job = Job(id=42, source="manual", company="Acme Corp", title="Senior Engineer")
    cover = CoverLetter(id=3, job_id=42, origin="draft")

    assert (
        cover_letter_download_name(job, cover)
        == "Acme_Corp-Senior_Engineer-CoverLetter-v3.pdf"
    )


def test_download_name_falls_back_when_company_or_title_missing():
    job = Job(id=42, source="manual", company=None, title="")
    version = ResumeVersion(id=7, job_id=42, round=1, origin="tailor")

    assert resume_download_name(job, version) == "Company-Role-Resume-v7.pdf"


def test_download_name_strips_special_characters_and_collapses_whitespace():
    job = Job(
        id=42,
        source="manual",
        company="Acme, Inc.  (Remote)",
        title="C++  Engineer -- Backend",
    )
    version = ResumeVersion(id=9, job_id=42, round=1, origin="tailor")

    assert (
        resume_download_name(job, version)
        == "Acme_Inc_Remote-C_Engineer_Backend-Resume-v9.pdf"
    )
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_export.py -v`
Expected: FAIL — `ImportError: cannot import name 'resume_download_name'`
(or `cover_letter_download_name`) from the new test's import line.

- [x] **Step 3: Implement the helpers**

In `src/resume_tailor_harness/render/export.py`, add after the existing `_origin` helper
(the module already `import re`s indirectly via `render/renderer.py`'s `_slug`,
so add an explicit `import re` at the top of the file if not already present —
check first; currently the file has no top-level `re` import, only via the
`_slug` re-export):

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

Add `import re` near the top of `src/resume_tailor_harness/render/export.py` (alongside
the existing `import json`) if it isn't already imported at module level.

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_export.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones).

- [x] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/render/export.py tests/test_render_export.py
git commit -m "feat(render): add friendly resume/cover-letter download filename helpers"
```

---

### Task 2: Use the friendly name in the resume PDF download route

**Files:**
- Modify: `src/resume_tailor_harness/api/routers/resumes.py`
- Test: `tests/api/test_job_detail.py`

**Interfaces:**
- Consumes: `resume_download_name(job, version) -> str` from Task 1
  (`resume_tailor_harness.render.export`); `get_job(session, job_id) -> Job | None` from
  `resume_tailor_harness.tracking.repository` (already imported project-wide, not yet in
  this file).

- [x] **Step 1: Write the failing test**

Add to `tests/api/test_job_detail.py`:

```python
def test_pdf_download_filename_is_friendly(tmp_path):
    client = _client()
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with client:
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(source="manual", jd_text="x", company="Acme Corp", title="Senior Engineer")
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
            v = ResumeVersion(job_id=job.id, round=0, pdf_path=str(pdf))
            s.add(v)
            s.commit()
            s.refresh(v)
            vid = v.id
        resp = client.get(f"/api/resume-versions/{vid}/pdf")
    assert resp.status_code == 200
    assert (
        f'filename="Acme_Corp-Senior_Engineer-Resume-v{vid}.pdf"'
        in resp.headers["content-disposition"]
    )
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_detail.py::test_pdf_download_filename_is_friendly -v`
Expected: FAIL — assertion error, `content-disposition` still names
`ok.pdf` (the old `Path(pdf_path).name` behavior).

- [x] **Step 3: Implement the route change**

In `src/resume_tailor_harness/api/routers/resumes.py`, add the import and change
`download_pdf`:

```python
from resume_tailor_harness.render.export import resume_download_name
from resume_tailor_harness.tracking.repository import get_job, get_resume_version
```

(replace the existing `from resume_tailor_harness.tracking.repository import
get_resume_version` line with the combined import above, keeping alphabetical
order alongside any other names already imported from that module in the
file).

```python
@link_router.get("/resume-versions/{version_id}/pdf")
def download_pdf(
    version_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    version = get_resume_version(session, version_id)
    if version is None:
        raise ApiException(404, "NOT_FOUND", f"Resume version #{version_id} not found")
    if not version.pdf_path or not Path(version.pdf_path).exists():
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this version")
    job = get_job(session, version.job_id)
    filename = (
        resume_download_name(job, version) if job is not None else Path(version.pdf_path).name
    )
    return FileResponse(
        version.pdf_path,
        media_type="application/pdf",
        filename=filename,
    )
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_job_detail.py -v`
Expected: PASS (including the two pre-existing download tests, which don't
assert on filename and remain unaffected).

- [x] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/api/routers/resumes.py tests/api/test_job_detail.py
git commit -m "feat(api): friendly filename for resume PDF single-file download"
```

---

### Task 3: Use the friendly name in the cover-letter PDF download route

**Files:**
- Modify: `src/resume_tailor_harness/api/routers/cover_letters.py`
- Create: `tests/api/test_cover_letters_download.py`

**Interfaces:**
- Consumes: `cover_letter_download_name(job, cover_letter) -> str` from Task 1
  (`resume_tailor_harness.render.export`); `get_job(session, job_id) -> Job | None` from
  `resume_tailor_harness.tracking.repository`.

- [x] **Step 1: Write the failing tests**

Create `tests/api/test_cover_letters_download.py`:

```python
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.db import get_session
from resume_tailor_harness.tracking.tables import CoverLetter, Job


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_cover_letter_pdf_download_404_when_no_file(tmp_path):
    client = _client()
    with client:
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(source="manual", jd_text="x")
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
            cl = CoverLetter(job_id=job.id, pdf_path=str(tmp_path / "missing.pdf"))
            s.add(cl)
            s.commit()
            s.refresh(cl)
            clid = cl.id
        resp = client.get(f"/api/cover-letters/{clid}/pdf")
    assert resp.status_code == 404


def test_cover_letter_pdf_download_uses_friendly_filename(tmp_path):
    client = _client()
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    with client:
        with get_session(client.app.state.engine) as s:  # type: ignore[union-attr]
            job = Job(source="manual", jd_text="x", company="Acme Corp", title="Senior Engineer")
            s.add(job)
            s.commit()
            s.refresh(job)
            assert job.id is not None
            cl = CoverLetter(job_id=job.id, pdf_path=str(pdf))
            s.add(cl)
            s.commit()
            s.refresh(cl)
            clid = cl.id
        resp = client.get(f"/api/cover-letters/{clid}/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 test"
    assert (
        f'filename="Acme_Corp-Senior_Engineer-CoverLetter-v{clid}.pdf"'
        in resp.headers["content-disposition"]
    )
```

- [x] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_cover_letters_download.py -v`
Expected: the 404 test passes already (unrelated to this change); the friendly-filename
test FAILS on the `content-disposition` assertion (still names `ok.pdf`).

- [x] **Step 3: Implement the route change**

In `src/resume_tailor_harness/api/routers/cover_letters.py`, add the import and change
`download_cover_letter_pdf`:

```python
from resume_tailor_harness.render.export import cover_letter_download_name
from resume_tailor_harness.tracking.repository import get_cover_letter, get_job
```

(replace the existing `from resume_tailor_harness.tracking.repository import
get_cover_letter` line with the combined import above).

```python
@link_router.get("/cover-letters/{cover_letter_id}/pdf")
def download_cover_letter_pdf(
    cover_letter_id: int, session: Session = Depends(get_session)
) -> FileResponse:
    cover_letter = get_cover_letter(session, cover_letter_id)
    if cover_letter is None:
        raise ApiException(
            404, "NOT_FOUND", f"Cover letter #{cover_letter_id} not found"
        )
    if not cover_letter.pdf_path or not Path(cover_letter.pdf_path).exists():
        raise ApiException(404, "NOT_FOUND", "No rendered PDF for this cover letter")
    job = get_job(session, cover_letter.job_id)
    filename = (
        cover_letter_download_name(job, cover_letter)
        if job is not None
        else Path(cover_letter.pdf_path).name
    )
    return FileResponse(
        cover_letter.pdf_path,
        media_type="application/pdf",
        filename=filename,
    )
```

- [x] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_cover_letters_download.py -v`
Expected: PASS (both tests).

- [x] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: PASS (no regressions elsewhere).

- [x] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/api/routers/cover_letters.py tests/api/test_cover_letters_download.py
git commit -m "feat(api): friendly filename for cover-letter PDF single-file download"
```
