"""Filesystem projection of a job's resume and cover-letter versions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlmodel import Session

from resume_agent.render.renderer import _slug
from resume_agent.tracking.repository import (
    application_for_job,
    cover_letters_for_job,
    get_job,
    resume_versions_for_job,
)
from resume_agent.tracking.tables import Application, CoverLetter, Job, ResumeVersion


def job_slug(job: Job) -> str:
    company = _slug(job.company or "") or "company"
    title = _slug(job.title or "") or "role"
    return f"{company}-{title}-{job.id}"


def job_dir(base: str | Path, job: Job) -> Path:
    return Path(base) / job_slug(job)


def _origin(value: str | None, fallback: str) -> str:
    return _slug(value or "") or fallback


def resume_pdf_name(version: ResumeVersion) -> str:
    return f"resume-v{version.id}-{_origin(version.origin, 'tailor')}.pdf"


def resume_json_name(version: ResumeVersion) -> str:
    return f"resume-v{version.id}-{_origin(version.origin, 'tailor')}.content.json"


def cover_letter_pdf_name(cover_letter: CoverLetter) -> str:
    return f"cover-letter-v{cover_letter.id}-{_origin(cover_letter.origin, 'draft')}.pdf"


def cover_letter_json_name(cover_letter: CoverLetter) -> str:
    return f"cover-letter-v{cover_letter.id}-{_origin(cover_letter.origin, 'draft')}.content.json"


def _version_entry(version: ResumeVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "round": version.round,
        "origin": version.origin,
        "instruction": version.instruction,
        "parentVersionId": version.parent_version_id,
        "factCheckPassed": version.fact_check_passed,
        "reviewScore": version.review_score,
        "createdAt": version.created_at.isoformat() if version.created_at else None,
        "file": resume_pdf_name(version),
        "contentFile": resume_json_name(version),
    }


def _cover_letter_entry(cover_letter: CoverLetter) -> dict[str, Any]:
    return {
        "id": cover_letter.id,
        "origin": cover_letter.origin,
        "instruction": cover_letter.instruction,
        "parentId": cover_letter.parent_id,
        "factCheckPassed": cover_letter.fact_check_passed,
        "createdAt": cover_letter.created_at.isoformat() if cover_letter.created_at else None,
        "file": cover_letter_pdf_name(cover_letter),
        "contentFile": cover_letter_json_name(cover_letter),
    }


def build_manifest(
    job: Job,
    versions: list[ResumeVersion],
    cover_letters: list[CoverLetter],
    application: Application | None,
) -> dict[str, Any]:
    return {
        "job": {
            "id": job.id,
            "company": job.company,
            "title": job.title,
            "url": job.url,
            "status": job.status,
        },
        "resumeVersions": [_version_entry(v) for v in sorted(versions, key=_row_id)],
        "coverLetters": [_cover_letter_entry(cl) for cl in sorted(cover_letters, key=_row_id)],
        "applied": {
            "resumeVersionId": application.resume_version_id if application else None,
            "coverLetterId": application.cover_letter_id if application else None,
        },
    }


def _row_id(row: ResumeVersion | CoverLetter) -> int:
    return row.id or 0


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def export_job_artifacts(
    session: Session, job_id: int, base: str | Path = "output"
) -> Path | None:
    job = get_job(session, job_id)
    if job is None:
        return None

    versions = sorted(resume_versions_for_job(session, job_id), key=_row_id)
    cover_letters = sorted(cover_letters_for_job(session, job_id), key=_row_id)
    application = application_for_job(session, job_id)

    out = job_dir(base, job)
    out.mkdir(parents=True, exist_ok=True)

    for version in versions:
        _write_json(out / resume_json_name(version), version.content_json or {})
    for cover_letter in cover_letters:
        _write_json(out / cover_letter_json_name(cover_letter), cover_letter.content_json or {})
    _write_json(out / "manifest.json", build_manifest(job, versions, cover_letters, application))
    return out
