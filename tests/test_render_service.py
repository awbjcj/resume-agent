from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from resume_agent.models.resume import ResumeContent
from resume_agent.models.profile import Contact
from resume_agent.render.render_config import RenderConfig
from resume_agent.render.service import render_version
from resume_agent.tracking.repository import (
    get_resume_version,
    save_job,
    save_resume_version,
)
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def test_render_version_sets_path_and_marks_rendered(tmp_path):
    calls = {}

    def fake_render(content, output_path, template_path, *, fit_pages=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-fake")
        calls["content"] = content
        calls["template_path"] = template_path
        calls["fit_pages"] = fit_pages
        return Path(output_path)

    config = RenderConfig(
        template_path="templates/resume.typ", output_dir=str(tmp_path / "out")
    )
    with _session() as s:
        job = save_job(
            s,
            Job(
                source="manual",
                jd_text="jd",
                company="Acme",
                title="Engineer",
                status=JobStatus.tailored.value,
            ),
        )
        version = save_resume_version(
            s,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=1,
                content_json=ResumeContent(contact=Contact(name="Ada")).model_dump(
                    mode="json"
                ),
            ),
        )

        path = render_version(s, _require_id(version.id), config, render_fn=fake_render)

        assert path is not None
        assert path.exists()
        assert path.suffix == ".pdf"
        assert isinstance(calls["content"], ResumeContent)
        assert calls["fit_pages"] == 1
        refreshed = get_resume_version(s, _require_id(version.id))
        assert refreshed is not None
        assert refreshed.pdf_path == str(path)
        assert job.status == JobStatus.rendered.value


def test_render_version_uses_distinct_paths_for_versions_same_job_same_day(tmp_path):
    def fake_render(content, output_path, template_path, *, fit_pages=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-fake")
        return Path(output_path)

    config = RenderConfig(
        template_path="templates/resume.typ", output_dir=str(tmp_path / "out")
    )
    with _session() as s:
        job = save_job(
            s,
            Job(
                source="manual",
                jd_text="jd",
                company="Acme",
                title="Engineer",
                status=JobStatus.tailored.value,
            ),
        )
        first = save_resume_version(
            s,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=1,
                content_json=ResumeContent(contact=Contact(name="Ada")).model_dump(
                    mode="json"
                ),
            ),
        )
        second = save_resume_version(
            s,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=2,
                content_json=ResumeContent(contact=Contact(name="Ada")).model_dump(
                    mode="json"
                ),
            ),
        )

        first_path = render_version(
            s, _require_id(first.id), config, render_fn=fake_render
        )
        second_path = render_version(
            s, _require_id(second.id), config, render_fn=fake_render
        )

        assert first_path is not None
        assert second_path is not None
        assert first_path != second_path
        assert f"v{_require_id(first.id)}" in first_path.stem
        assert f"v{_require_id(second.id)}" in second_path.stem


def test_render_version_missing_returns_none(tmp_path):
    config = RenderConfig(output_dir=str(tmp_path))

    def fake_render(content, output_path, template_path, *, fit_pages=None):
        return Path(output_path)

    with _session() as s:
        assert render_version(s, 4242, config, render_fn=fake_render) is None


def test_render_version_can_disable_one_page_fit(tmp_path):
    calls = {}

    def fake_render(content, output_path, template_path, *, fit_pages=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-fake")
        calls["fit_pages"] = fit_pages
        return Path(output_path)

    config = RenderConfig(
        template="classic",
        fit_one_page=False,
        output_dir=str(tmp_path / "out"),
    )
    with _session() as session:
        job = save_job(
            session,
            Job(source="manual", jd_text="jd", company="Acme", title="Engineer"),
        )
        version = save_resume_version(
            session,
            ResumeVersion(
                job_id=_require_id(job.id),
                round=1,
                content_json=ResumeContent(contact=Contact(name="Ada")).model_dump(
                    mode="json"
                ),
            ),
        )
        render_version(session, _require_id(version.id), config, render_fn=fake_render)
    assert calls["fit_pages"] is None


class _FakeConfigStore:
    """Minimal store honoring the get/put contract clear_custom_render_template needs."""

    def __init__(self, doc: RenderConfig) -> None:
        self.doc = doc

    def get(self, key: str) -> RenderConfig:
        assert key == "render"
        return self.doc

    def put(self, key: str, doc: RenderConfig) -> None:
        assert key == "render"
        self.doc = doc


def test_clear_custom_render_template_falls_back_to_classic():
    from resume_agent.services.render_templates import clear_custom_render_template

    store = _FakeConfigStore(RenderConfig(template="custom:mine"))
    clear_custom_render_template(store)
    assert store.doc.template == "classic"


def test_clear_custom_render_template_leaves_bundled_and_empty_alone():
    from resume_agent.services.render_templates import clear_custom_render_template

    for template in ("classic", None):
        store = _FakeConfigStore(RenderConfig(template=template))
        clear_custom_render_template(store)
        assert store.doc.template == template
