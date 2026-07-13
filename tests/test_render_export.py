import json
from pathlib import Path

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.config import Settings
from resume_agent.render.export import (
    build_manifest,
    cover_letter_pdf_name,
    export_job_artifacts,
    job_dir,
    job_slug,
    resume_json_name,
    resume_pdf_name,
)
from resume_agent.tracking.repository import (
    save_application,
    save_cover_letter,
    save_job,
    save_resume_version,
)
from resume_agent.tracking.tables import Application, CoverLetter, Job, ResumeVersion
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import WorkspacePaths


def test_job_slug_and_version_filenames():
    job = Job(id=42, source="manual", company="Acme Corp", title="Senior Engineer")
    version = ResumeVersion(id=7, job_id=42, round=1, origin="revision")
    cover = CoverLetter(id=3, job_id=42, origin="draft")

    assert job_slug(job) == "acme_corp-senior_engineer-42"
    assert job_dir("output", job) == Path("output") / "acme_corp-senior_engineer-42"
    assert resume_pdf_name(version) == "resume-v7-revision.pdf"
    assert resume_json_name(version) == "resume-v7-revision.content.json"
    assert cover_letter_pdf_name(cover) == "cover-letter-v3-draft.pdf"


def test_job_dir_rebases_default_output_into_active_workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / "users" / "alice")
    context = UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=paths,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )
    job = Job(id=42, source="manual", company="Acme", title="Engineer")

    with use_context(context):
        assert job_dir("output", job).is_relative_to(paths.output_dir)


def test_build_manifest_shape():
    job = Job(id=42, source="manual", company="Acme", title="Eng")
    version = ResumeVersion(
        id=7,
        job_id=42,
        round=1,
        origin="revision",
        instruction="be concise",
        parent_version_id=5,
        fact_check_passed=True,
    )
    cover = CoverLetter(id=3, job_id=42, origin="draft", fact_check_passed=True)
    app = Application(id=1, job_id=42, resume_version_id=7, cover_letter_id=3)

    manifest = build_manifest(job, [version], [cover], app)

    assert manifest["job"]["id"] == 42
    assert manifest["resumeVersions"][0]["instruction"] == "be concise"
    assert manifest["resumeVersions"][0]["file"] == "resume-v7-revision.pdf"
    assert manifest["applied"] == {"resumeVersionId": 7, "coverLetterId": 3}


def test_export_writes_manifest_and_content_idempotently(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        version = save_resume_version(
            session,
            ResumeVersion(
                job_id=job.id,
                round=1,
                origin="tailor",
                content_json={"contact": {"name": "Ada"}},
                fact_check_passed=True,
            ),
        )
        cover = save_cover_letter(
            session,
            CoverLetter(
                job_id=job.id,
                origin="draft",
                content_json={"contact": {"name": "Ada"}},
                fact_check_passed=True,
            ),
        )
        save_application(
            session,
            Application(job_id=job.id, resume_version_id=version.id, cover_letter_id=cover.id),
        )

        out = export_job_artifacts(session, job.id, base=tmp_path)
        assert out is not None
        first_manifest = (out / "manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(first_manifest)

        assert manifest["resumeVersions"][0]["id"] == version.id
        assert manifest["coverLetters"][0]["id"] == cover.id
        assert (out / f"resume-v{version.id}-tailor.content.json").exists()
        assert (out / f"cover-letter-v{cover.id}-draft.content.json").exists()

        export_job_artifacts(session, job.id, base=tmp_path)
        assert (out / "manifest.json").read_text(encoding="utf-8") == first_manifest
