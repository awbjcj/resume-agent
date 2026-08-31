# Closed-Loop Resume — Phase 2: Organized Versioned Local Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mirror every resume/cover-letter version to a well-organized per-job folder with self-describing `content.json` snapshots and a `manifest.json` table of contents, via an idempotent projection from the database.

**Architecture:** A pure `export.py` module computes folder paths, version-keyed filenames, and a manifest dict from DB rows. `export_job_artifacts(session, job_id, base)` is the idempotent projection that writes the folder. The render path writes PDFs straight into the per-job folder; the tailor/revise use-cases and a new `resume-tailor-harness export [--all]` CLI call the projection so the mirror stays in sync. The database remains the authoritative version store.

**Tech Stack:** Python 3 / SQLModel / SQLite, Typst rendering, Typer CLI; pytest (offline).

## Global Constraints

- **DB is authoritative.** The filesystem is a pure projection; `export_job_artifacts` must be idempotent — running it twice yields byte-identical output.
- **Immutable, version-keyed filenames.** Never overwrite a different version's file. Filenames embed the version id and origin.
- **Tests are offline.** Run: `.venv/Scripts/python.exe -m pytest`. Use `tmp_path` for filesystem assertions; never write into the repo's real `output/`.
- **Depends on Phase 1.** Requires `ResumeVersion.origin`/`parent_version_id`, `CoverLetter.origin`/`parent_id`, and `Application.cover_letter_id` (Phase 1 Tasks 1–2). Land Phase 1 first.
- **Lint clean:** `ruff check` must pass.

---

### Task 1: Slug, path, and filename helpers

**Files:**

- Create: `src/resume_tailor_harness/render/export.py`
- Test: `tests/test_render_export.py`

**Interfaces:**

- Consumes: `Job`, `ResumeVersion`, `CoverLetter` (`resume_tailor_harness.tracking.tables`), existing `_slug` idea from `renderer.py`.
- Produces: `job_slug(job: Job) -> str`; `job_dir(base: str | Path, job: Job) -> Path`; `resume_pdf_name(v: ResumeVersion) -> str`; `resume_json_name(v: ResumeVersion) -> str`; `cover_letter_pdf_name(cl: CoverLetter) -> str`; `cover_letter_json_name(cl: CoverLetter) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render_export.py
from pathlib import Path

from resume_tailor_harness.render.export import (
    cover_letter_pdf_name, job_dir, job_slug, resume_json_name, resume_pdf_name,
)
from resume_tailor_harness.tracking.tables import CoverLetter, Job, ResumeVersion


def test_job_slug_and_dir():
    job = Job(id=42, source="url", company="Acme Corp", title="Senior Engineer")
    assert job_slug(job) == "acme_corp-senior_engineer-42"
    assert job_dir("output", job) == Path("output") / "acme_corp-senior_engineer-42"


def test_version_filenames_are_version_keyed():
    v = ResumeVersion(id=7, job_id=42, round=2, origin="revision")
    assert resume_pdf_name(v) == "resume-v7-revision.pdf"
    assert resume_json_name(v) == "resume-v7-revision.content.json"


def test_cover_letter_filename():
    cl = CoverLetter(id=3, job_id=42, origin="draft")
    assert cover_letter_pdf_name(cl) == "cover-letter-v3-draft.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_export.py -v`
Expected: FAIL (`ModuleNotFoundError: resume_tailor_harness.render.export`).

- [ ] **Step 3: Implement the helpers**

```python
# src/resume_tailor_harness/render/export.py
"""Filesystem projection of a job's resume/cover-letter versions.

The database is authoritative; this module mirrors it into a per-job folder for
human lookup. Every function here is pure except export_job_artifacts (below).
"""

from __future__ import annotations

from pathlib import Path

from resume_tailor_harness.render.renderer import _slug
from resume_tailor_harness.tracking.tables import CoverLetter, Job, ResumeVersion


def job_slug(job: Job) -> str:
    company = _slug(job.company or "") or "company"
    title = _slug(job.title or "") or "role"
    return f"{company}-{title}-{job.id}"


def job_dir(base: str | Path, job: Job) -> Path:
    return Path(base) / job_slug(job)


def resume_pdf_name(v: ResumeVersion) -> str:
    return f"resume-v{v.id}-{v.origin}.pdf"


def resume_json_name(v: ResumeVersion) -> str:
    return f"resume-v{v.id}-{v.origin}.content.json"


def cover_letter_pdf_name(cl: CoverLetter) -> str:
    return f"cover-letter-v{cl.id}-{cl.origin}.pdf"


def cover_letter_json_name(cl: CoverLetter) -> str:
    return f"cover-letter-v{cl.id}-{cl.origin}.content.json"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/render/export.py tests/test_render_export.py
git commit -m "feat: per-job folder path and version-keyed filename helpers"
```

---

### Task 2: Manifest builder (pure)

**Files:**

- Modify: `src/resume_tailor_harness/render/export.py`
- Test: `tests/test_render_export.py`

**Interfaces:**

- Consumes: `Job`, `list[ResumeVersion]`, `list[CoverLetter]`, `Application | None`.
- Produces: `build_manifest(job, versions, cover_letters, application) -> dict` — a JSON-serializable dict with `job` meta, a `resumeVersions` list (id, round, origin, instruction, parentVersionId, factCheckPassed, reviewScore, createdAt, file), a `coverLetters` list, and `applied` `{resumeVersionId, coverLetterId}`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_render_export.py
from resume_tailor_harness.render.export import build_manifest
from resume_tailor_harness.tracking.tables import Application


def test_build_manifest_shape():
    job = Job(id=42, source="url", company="Acme", title="Eng")
    v = ResumeVersion(id=7, job_id=42, round=1, origin="revision",
                      instruction="be concise", parent_version_id=5, fact_check_passed=True)
    cl = CoverLetter(id=3, job_id=42, origin="draft", fact_check_passed=True)
    app = Application(id=1, job_id=42, resume_version_id=7, cover_letter_id=3, status="ready")
    m = build_manifest(job, [v], [cl], app)
    assert m["job"]["id"] == 42
    assert m["resumeVersions"][0]["instruction"] == "be concise"
    assert m["resumeVersions"][0]["file"] == "resume-v7-revision.pdf"
    assert m["applied"] == {"resumeVersionId": 7, "coverLetterId": 3}


def test_build_manifest_no_application():
    job = Job(id=42, source="url", company="Acme", title="Eng")
    m = build_manifest(job, [], [], None)
    assert m["applied"] == {"resumeVersionId": None, "coverLetterId": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_export.py::test_build_manifest_shape -v`
Expected: FAIL (`ImportError: cannot import name 'build_manifest'`).

- [ ] **Step 3: Implement `build_manifest`**

Append to `export.py`:

```python
def _version_entry(v: ResumeVersion) -> dict:
    return {
        "id": v.id, "round": v.round, "origin": v.origin,
        "instruction": v.instruction, "parentVersionId": v.parent_version_id,
        "factCheckPassed": v.fact_check_passed, "reviewScore": v.review_score,
        "createdAt": v.created_at.isoformat() if v.created_at else None,
        "file": resume_pdf_name(v),
    }


def _cover_letter_entry(cl: CoverLetter) -> dict:
    return {
        "id": cl.id, "origin": cl.origin, "instruction": cl.instruction,
        "parentId": cl.parent_id, "factCheckPassed": cl.fact_check_passed,
        "createdAt": cl.created_at.isoformat() if cl.created_at else None,
        "file": cover_letter_pdf_name(cl),
    }


def build_manifest(job, versions, cover_letters, application) -> dict:
    return {
        "job": {
            "id": job.id, "company": job.company, "title": job.title,
            "url": job.url, "status": job.status,
        },
        "resumeVersions": [_version_entry(v) for v in versions],
        "coverLetters": [_cover_letter_entry(cl) for cl in cover_letters],
        "applied": {
            "resumeVersionId": application.resume_version_id if application else None,
            "coverLetterId": application.cover_letter_id if application else None,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/render/export.py tests/test_render_export.py
git commit -m "feat: manifest builder for per-job export"
```

---

### Task 3: `cover_letters_for_job` repository helper

**Files:**

- Modify: `src/resume_tailor_harness/tracking/repository.py` (near `resume_versions_for_job:107`)
- Test: `tests/test_tracking_repository.py` (append; create if absent)

**Interfaces:**

- Produces: `cover_letters_for_job(session, job_id: int) -> list[CoverLetter]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tracking_repository.py
from sqlmodel import Session
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tracking.repository import (
    cover_letters_for_job, save_cover_letter, save_job,
)
from resume_tailor_harness.tracking.tables import CoverLetter, Job


def test_cover_letters_for_job():
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        job = save_job(s, Job(source="url", company="Acme", title="Eng"))
        save_cover_letter(s, CoverLetter(job_id=job.id, content_json={}))
        save_cover_letter(s, CoverLetter(job_id=job.id, content_json={}))
        assert len(cover_letters_for_job(s, job.id)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_repository.py::test_cover_letters_for_job -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Implement the helper**

After `resume_versions_for_job` in `repository.py`:

```python
def cover_letters_for_job(session: Session, job_id: int) -> list[CoverLetter]:
    return list(session.exec(select(CoverLetter).where(CoverLetter.job_id == job_id)).all())
```

(Ensure `CoverLetter` is imported in this module — it is already, used by `save_cover_letter`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tracking_repository.py::test_cover_letters_for_job -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/tracking/repository.py tests/test_tracking_repository.py
git commit -m "feat: cover_letters_for_job repository helper"
```

---

### Task 4: `export_job_artifacts` projection

**Files:**

- Modify: `src/resume_tailor_harness/render/export.py`
- Test: `tests/test_render_export.py`

**Interfaces:**

- Consumes: `get_job`, `resume_versions_for_job`, `cover_letters_for_job` (Task 3), `application_for_job`.
- Produces: `export_job_artifacts(session, job_id: int, base: str | Path = "output") -> Path | None` — writes `content.json` per version/cover-letter + `manifest.json` into `job_dir`, returns the dir (or `None` if job missing). Idempotent.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_render_export.py
import json
from sqlmodel import Session
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.render.export import export_job_artifacts
from resume_tailor_harness.tracking.repository import save_job, save_resume_version


def test_export_writes_manifest_and_content_idempotently(tmp_path):
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        job = save_job(s, Job(source="url", company="Acme", title="Eng"))
        v = save_resume_version(s, ResumeVersion(
            job_id=job.id, round=1, origin="tailor",
            content_json={"contact": {"name": "Jane"}}, fact_check_passed=True))
        out = export_job_artifacts(s, job.id, base=tmp_path)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["resumeVersions"][0]["id"] == v.id
        assert (out / f"resume-v{v.id}-tailor.content.json").exists()
        # Idempotent: second run produces identical manifest bytes.
        first = (out / "manifest.json").read_text(encoding="utf-8")
        export_job_artifacts(s, job.id, base=tmp_path)
        assert (out / "manifest.json").read_text(encoding="utf-8") == first


def test_export_missing_job_returns_none(tmp_path):
    engine = make_engine("sqlite://"); init_db(engine)
    with Session(engine) as s:
        assert export_job_artifacts(s, 999, base=tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_export.py -k export -v`
Expected: FAIL (`ImportError: cannot import name 'export_job_artifacts'`).

- [ ] **Step 3: Implement the projection**

Append to `export.py`:

```python
import json

from sqlmodel import Session

from resume_tailor_harness.tracking.repository import (
    application_for_job, cover_letters_for_job, get_job, resume_versions_for_job,
)


def export_job_artifacts(
    session: Session, job_id: int, base: str | Path = "output"
) -> Path | None:
    job = get_job(session, job_id)
    if job is None:
        return None
    versions = resume_versions_for_job(session, job_id)
    cover_letters = cover_letters_for_job(session, job_id)
    application = application_for_job(session, job_id)

    out = job_dir(base, job)
    out.mkdir(parents=True, exist_ok=True)

    for v in versions:
        (out / resume_json_name(v)).write_text(
            json.dumps(v.content_json or {}, indent=2, sort_keys=True), encoding="utf-8"
        )
    for cl in cover_letters:
        (out / cover_letter_json_name(cl)).write_text(
            json.dumps(cl.content_json or {}, indent=2, sort_keys=True), encoding="utf-8"
        )
    manifest = build_manifest(job, versions, cover_letters, application)
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return out
```

(Move the `import json` to the top of the file with the other imports.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/render/export.py tests/test_render_export.py
git commit -m "feat: idempotent export_job_artifacts projection"
```

---

### Task 5: Render PDFs into the per-job folder

**Files:**

- Modify: `src/resume_tailor_harness/render/service.py:15-40` (`render_version`)
- Modify: `src/resume_tailor_harness/cover_letter/render.py:32-56` (`render_cover_letter`)
- Test: `tests/test_render_service.py` (append; mirror existing render tests)

**Interfaces:**

- Consumes: `job_dir`, `resume_pdf_name`, `cover_letter_pdf_name`, `export_job_artifacts`.
- Produces: unchanged signatures; `render_version` now writes to `job_dir(config.output_dir, job)/resume_pdf_name(version)` and calls `export_job_artifacts` afterward. `render_cover_letter` writes to `job_dir(output_dir, job)/cover_letter_pdf_name(cover)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render_service.py  (append)
from sqlmodel import Session
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.render.render_config import RenderConfig
from resume_tailor_harness.render.service import render_version
from resume_tailor_harness.tracking.repository import save_job, save_resume_version
from resume_tailor_harness.tracking.tables import Job, ResumeVersion


def test_render_version_writes_into_per_job_folder(tmp_path):
    engine = make_engine("sqlite://"); init_db(engine)
    captured = {}
    def fake_render(content, output_path, template_path):
        from pathlib import Path
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-1.4")
        captured["path"] = str(output_path)
        return Path(output_path)
    with Session(engine) as s:
        job = save_job(s, Job(source="url", company="Acme Corp", title="Eng"))
        v = save_resume_version(s, ResumeVersion(
            job_id=job.id, round=1, origin="tailor",
            content_json={"contact": {"name": "Jane"}}))
        out = render_version(s, v.id, RenderConfig(output_dir=str(tmp_path)), render_fn=fake_render)
        assert f"acme_corp-eng-{job.id}" in captured["path"]
        assert captured["path"].endswith(f"resume-v{v.id}-tailor.pdf")
        # export ran: manifest is present alongside the PDF
        assert (out.parent / "manifest.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_service.py::test_render_version_writes_into_per_job_folder -v`
Expected: FAIL (PDF lands in flat `output_dir`, no manifest).

- [ ] **Step 3: Update `render_version`**

In `src/resume_tailor_harness/render/service.py`, replace the filename/out_path block (lines ~29-31) and add the export call before `return`:

```python
from resume_tailor_harness.render.export import export_job_artifacts, job_dir, resume_pdf_name
```

```python
    out_dir = job_dir(config.output_dir, job) if job else Path(config.output_dir)
    out_path = out_dir / resume_pdf_name(version)

    render_fn(content, out_path, config.template_path)

    version.pdf_path = str(out_path)
    save_resume_version(session, version)
    if job is not None:
        job.status = JobStatus.rendered.value
        save_job(session, job)
        export_job_artifacts(session, job.id, base=config.output_dir)
    return out_path
```

(Drop the now-unused `output_filename`/`utcnow` imports if they become unused.)

- [ ] **Step 4: Update `render_cover_letter`**

In `src/resume_tailor_harness/cover_letter/render.py`, replace the filename/out_path block (lines ~46-50) and add export:

```python
from resume_tailor_harness.render.export import cover_letter_pdf_name, export_job_artifacts, job_dir
```

```python
    out_dir = job_dir(output_dir, job) if job else Path(output_dir)
    out_path = out_dir / cover_letter_pdf_name(cover)

    render_fn(content, out_path, template_path)

    cover.pdf_path = str(out_path)
    save_cover_letter(session, cover)
    if job is not None:
        export_job_artifacts(session, job.id, base=output_dir)
    return out_path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_render_service.py -v`
Expected: PASS. Also run the existing cover-letter render test module to confirm no regression.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/render/service.py src/resume_tailor_harness/cover_letter/render.py tests/test_render_service.py
git commit -m "feat: render PDFs into per-job folders and export manifest"
```

---

### Task 6: Export after tailor and revise

**Files:**

- Modify: `src/resume_tailor_harness/services/tailoring.py:29-48` (`tailor`)
- Modify: `src/resume_tailor_harness/services/revision.py` (Phase 1) — call export after persisting
- Modify: `src/resume_tailor_harness/services/cover_letters.py` + `src/resume_tailor_harness/services/cover_letter_revision.py` (Phase 1) — call export
- Test: `tests/test_services_tailoring_export.py`

**Interfaces:**

- Consumes: `export_job_artifacts`.
- Produces: after `tailor`, `revise_resume_version`, `write_cover_letters`, and `revise_cover_letter_version` persist their rows, the affected job's folder is refreshed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_tailoring_export.py
from sqlmodel import Session
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.services import tailoring as T
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job


def test_tailor_exports_each_job(monkeypatch, tmp_path):
    engine = make_engine("sqlite://"); init_db(engine)
    calls = []
    monkeypatch.setattr(T, "export_job_artifacts", lambda s, jid, **k: calls.append(jid))
    # Fake tailor_jobs to persist nothing but return one job's versions.
    with Session(engine) as s:
        job = save_job(s, Job(source="url", company="Acme", title="Eng"))
        monkeypatch.setattr(T, "tailor_jobs", lambda *a, **k: {job.id: []})
        monkeypatch.setattr(T, "resolve_targets", lambda *a, **k: [job])
        monkeypatch.setattr(T, "load_review_config", lambda p: type("C", (), {"style_guide_path": None})())
        monkeypatch.setattr(T, "load_facts", lambda p: object())
        monkeypatch.setattr(T, "load_style_guide", lambda p: None)
        monkeypatch.setattr(T, "build_tailor_bundle", lambda c, style_guide=None: type(
            "B", (), {"tailor": None, "reviewers": {}, "reviser": None})())
        T.tailor(s, job_ids=[job.id])
        assert job.id in calls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_tailoring_export.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute 'export_job_artifacts'`).

- [ ] **Step 3: Call export in `tailor`**

In `src/resume_tailor_harness/services/tailoring.py`, import and call export over the result keys:

```python
from resume_tailor_harness.render.export import export_job_artifacts
```

At the end of `tailor`, replace `return tailor_jobs(...)` with:

```python
    results = tailor_jobs(
        session, targets, facts, config,
        bundle.tailor, bundle.reviewers, bundle.reviser, reporter=reporter,
    )
    for job_id in results:
        export_job_artifacts(session, job_id)
    return results
```

- [ ] **Step 4: Call export in the revision + cover-letter services**

In `services/revision.py` (Phase 1), before returning `child`:

```python
    saved = save_resume_version(session, child)
    from resume_tailor_harness.render.export import export_job_artifacts
    export_job_artifacts(session, saved.job_id)
    return saved
```

In `services/cover_letter_revision.py`, likewise after `save_cover_letter`. In `services/cover_letters.py` `write_cover_letters`, call `export_job_artifacts(session, job.id)` after each `render_cover_letter` (render already exports, so this is belt-and-suspenders for the no-render path — acceptable, idempotent).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_tailoring_export.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/resume_tailor_harness/services/ tests/test_services_tailoring_export.py
git commit -m "feat: refresh per-job export after tailor and revise"
```

---

### Task 7: `resume-tailor-harness export` CLI command

**Files:**

- Modify: `src/resume_tailor_harness/cli.py` (add `export` command near other commands)
- Test: `tests/test_cli_export.py`

**Interfaces:**

- Consumes: `export_job_artifacts`, `get_job`, a "list all job ids" query.
- Produces: `resume-tailor-harness export [JOB_ID] [--all] [--output DIR]` — exports one job, or every job with `--all`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_export.py
from typer.testing import CliRunner
from sqlmodel import Session
from resume_tailor_harness.cli import app
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job

runner = CliRunner()


def test_export_all(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    engine = make_engine(f"sqlite:///{db}"); init_db(engine)
    with Session(engine) as s:
        save_job(s, Job(source="url", company="Acme", title="Eng"))
    out = tmp_path / "out"
    result = runner.invoke(app, [
        "export", "--all", "--output", str(out), "--db-url", f"sqlite:///{db}"])
    assert result.exit_code == 0
    assert any(out.glob("*/manifest.json"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_export.py -v`
Expected: FAIL (`No such command 'export'`).

- [ ] **Step 3: Implement the command**

Add to `src/resume_tailor_harness/cli.py` (import `export_job_artifacts` and a job-listing helper; if none exists, use `select(Job)`):

```python
@app.command("export")
def export_cmd(
    job_id: int | None = typer.Argument(None, help="Job id to export."),
    all_jobs: bool = typer.Option(False, "--all", help="Export every job."),
    output: str = typer.Option("output", "--output", help="Base output directory."),
    db_url: str | None = typer.Option(None, "--db-url", help="Override the database URL."),
) -> None:
    """Write per-job folders (content.json + manifest.json) from the database."""
    from sqlmodel import select

    from resume_tailor_harness.render.export import export_job_artifacts
    from resume_tailor_harness.tracking.tables import Job

    engine = _engine(db_url)
    with get_session(engine) as session:
        if all_jobs:
            ids = [j.id for j in session.exec(select(Job)).all() if j.id is not None]
        elif job_id is not None:
            ids = [job_id]
        else:
            typer.echo("Pass a JOB_ID or --all."); raise typer.Exit(code=1)
        count = 0
        for jid in ids:
            if export_job_artifacts(session, jid, base=output) is not None:
                count += 1
    typer.echo(f"Exported {count} job folder(s) to {output}/")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/resume_tailor_harness/cli.py tests/test_cli_export.py
git commit -m "feat: resume-tailor-harness export CLI for per-job folder backfill"
```

---

### Task 8: Full verification pass

- [ ] **Step 1: Backend suite + lint**

Run: `.venv/Scripts/python.exe -m pytest` then `ruff check`
Expected: all PASS, lint clean.

- [ ] **Step 2: Manual smoke (optional)**

`resume-tailor-harness export --all` against a real dev DB → confirm `output/{company}-{title}-{id}/manifest.json` + `content.json` files appear and are stable on a second run.

- [ ] **Step 3: Commit (if cleanup)**

```bash
git add -A && git commit -m "chore: phase-2 export verification"
```

---

## Self-Review

**Spec coverage (Phase 2):**

- Per-job folder layout `output/{company}-{title}-{jobId}/` → Task 1 (`job_dir`/`job_slug`). ✓
- Version-keyed `resume-v{n}-{origin}.pdf` / `cover-letter-v{n}.pdf` + `content.json` snapshots → Tasks 1, 4. ✓
- `manifest.json` with instruction/fact-check/timestamp/origin + applied marker → Task 2. ✓
- Idempotent `export_job_artifacts` projection, DB authoritative → Task 4 (`test_export_writes_manifest_and_content_idempotently`). ✓
- Render writes straight into per-job folder → Task 5. ✓
- Export called after tailor/revise/render → Tasks 5 (render), 6 (tailor/revise). ✓
- `resume-tailor-harness export [--all]` backfill → Task 7. ✓

**Placeholder scan:** none. Test in Task 5/7 use fakes for the Typst renderer / real CliRunner — concrete, not placeholders.

**Type consistency:** `export_job_artifacts(session, job_id, base=...)` called identically in Tasks 5, 6, 7. `job_dir(base, job)`, `resume_pdf_name(v)`, `cover_letter_pdf_name(cl)` signatures defined in Task 1 and consumed unchanged in Tasks 4, 5. `build_manifest(job, versions, cover_letters, application)` defined Task 2, consumed Task 4. Manifest camelCase keys (`resumeVersions`, `parentVersionId`, `coverLetterId`) are internal JSON, intentionally matching the API wire convention.
