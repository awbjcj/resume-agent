from pathlib import Path
from typing import cast

import pytest
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.models.profile import Contact, ProfileFacts, Skill
import resume_agent.profile.effective as effective_module
from resume_agent.profile.effective import build_effective_taxonomy
from resume_agent.profile.matrix import build_matrix, save_matrix
from resume_agent.profile.store import save_facts
from resume_agent.services import rendering, tailoring
from resume_agent.services.errors import StageFailure
from resume_agent.tailor.service import TailorOutcome
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as database:
        yield database


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


class _RunnerStub:
    def __init__(self, result: str):
        self.result = result

    def run(self, prompt: str) -> str:
        return self.result

    async def arun(self, prompt: str) -> str:
        return self.result


def test_tailor_loads_config_and_calls_tailor_jobs(monkeypatch):
    captured = {}
    exports = []

    def fake_tailor_jobs(
        session, targets, facts, config, tailor, reviewers, reviser, reporter=None,
        match_plan_agent=None,
        skill_matrix=None,
        cluster_map=None,
        model=None,
    ):
        captured["targets"] = [j.id for j in targets]
        captured["match_plan"] = match_plan_agent
        captured["skill_matrix"] = skill_matrix
        return TailorOutcome(
            versions=cast(
                dict[int, list[ResumeVersion]], {targets[0].id: ["v1"]}
            ),
            failures={},
        )

    monkeypatch.setattr(tailoring, "tailor_jobs", fake_tailor_jobs)
    monkeypatch.setattr(
        tailoring, "load_review_config",
        lambda p: type("C", (), {"style_guide_path": None, "reviewers": []})(),
    )
    monkeypatch.setattr(tailoring, "load_facts", lambda p: object())
    monkeypatch.setattr(tailoring, "load_style_guide", lambda p: None)
    monkeypatch.setattr(
        tailoring, "build_tailor_bundle",
        lambda config, style_guide=None: tailoring.TailorBundle(
            tailor=_RunnerStub("t"),
            reviser=_RunnerStub("r"),
            reviewers={},
            revision=_RunnerStub("revise"),
            match_plan=_RunnerStub("plan"),
        ),
    )
    monkeypatch.setattr(
        tailoring,
        "export_job_artifacts",
        lambda session, job_id: exports.append(job_id),
    )
    with _session() as session:
        job = Job(source="manual", jd_text="x", status=JobStatus.approved.value)
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        result = tailoring.tailor(session, job_ids=[job.id])
    assert captured["targets"] == [job.id]
    assert captured["match_plan"] is not None
    assert result
    assert exports == [job.id]


def test_tailor_does_not_raise_when_only_some_targets_fail(monkeypatch):
    """fail_on_partial raises only on TOTAL failure -- a partial result is kept."""
    monkeypatch.setattr(
        tailoring, "load_review_config",
        lambda p: type("C", (), {"style_guide_path": None, "reviewers": []})(),
    )
    monkeypatch.setattr(tailoring, "load_facts", lambda p: object())
    monkeypatch.setattr(tailoring, "load_style_guide", lambda p: None)
    monkeypatch.setattr(
        tailoring,
        "build_tailor_bundle",
        lambda config, style_guide=None: tailoring.TailorBundle(
            tailor=_RunnerStub("t"), reviser=_RunnerStub("r"), reviewers={},
            revision=_RunnerStub("revise"),
        ),
    )

    with _session() as session:
        jobs = [
            Job(source="manual", jd_text=f"job {i}", status=JobStatus.approved.value)
            for i in range(2)
        ]
        session.add_all(jobs)
        session.commit()
        for job in jobs:
            session.refresh(job)
        failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")
        monkeypatch.setattr(
            tailoring,
            "tailor_jobs",
            lambda *args, **kwargs: TailorOutcome(
                versions=cast(dict[int, list[ResumeVersion]], {jobs[0].id: ["v1"]}),
                failures=cast(dict[int, StageFailure], {jobs[1].id: failure}),
            ),
        )
        monkeypatch.setattr(tailoring, "export_job_artifacts", lambda *args, **kwargs: None)

        outcome = tailoring.tailor(
            session,
            job_ids=[job.id for job in jobs if job.id is not None],
            fail_on_partial=True,
        )

        assert list(outcome.versions) == [jobs[0].id]
        assert list(outcome.failures) == [jobs[1].id]


def test_tailoring_sees_a_taxonomy_correction(tmp_path, monkeypatch):
    """Tailoring's matrix and cluster map must share the correction ledger."""
    profile_dir = tmp_path / "profile"
    facts_path = profile_dir / "facts.json"
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="JS")]},
    )
    cluster_map = ClusterMap(domain_of={"javascript": "web"})
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_taxonomy_corrections(
        TaxonomyCorrections(aliases={"js": "javascript"}), corrections_path
    )
    monkeypatch.setattr(
        effective_module, "corrections_file_path", lambda: str(corrections_path)
    )
    save_facts(facts, facts_path)
    save_cluster_map(cluster_map, profile_dir / "cluster_map.json")
    taxonomy = build_effective_taxonomy(profile_dir)
    save_matrix(
        build_matrix(facts, taxonomy), profile_dir / "matrix.json"
    )
    captured = {}

    def fake_tailor_jobs(*args, **kwargs):
        captured.update(kwargs)
        return TailorOutcome(
            versions=cast(
                dict[int, list[ResumeVersion]], {args[1][0].id: ["v1"]}
            ),
            failures={},
        )

    monkeypatch.setattr(tailoring, "tailor_jobs", fake_tailor_jobs)
    monkeypatch.setattr(
        tailoring,
        "load_review_config",
        lambda path: type("C", (), {"style_guide_path": None, "reviewers": []})(),
    )
    monkeypatch.setattr(tailoring, "load_style_guide", lambda path: None)
    monkeypatch.setattr(
        tailoring,
        "build_tailor_bundle",
        lambda config, style_guide=None: tailoring.TailorBundle(
            tailor=_RunnerStub("t"),
            reviser=_RunnerStub("r"),
            reviewers={},
            revision=_RunnerStub("revise"),
            match_plan=_RunnerStub("plan"),
        ),
    )
    monkeypatch.setattr(tailoring, "export_job_artifacts", lambda *args: None)

    with _session() as session:
        job = Job(source="manual", jd_text="x", status=JobStatus.approved.value)
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        tailoring.tailor(session, job_ids=[job.id], facts_path=str(facts_path))

    assert captured["skill_matrix"] is not None
    assert captured["cluster_map"].aliases["js"] == "javascript"
    assert [row.key for row in captured["skill_matrix"].rows] == ["javascript"]


def test_render_resume_version_returns_path(monkeypatch, tmp_path):
    def fake_render_version(session, version_id, config, render_fn=None):
        return tmp_path / "out.pdf"

    monkeypatch.setattr(rendering, "render_version", fake_render_version)
    monkeypatch.setattr(rendering, "_load_config", lambda p: object())
    with _session() as session:
        job = Job(source="manual", jd_text="x")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.id is not None
        v = ResumeVersion(job_id=job.id, round=0)
        session.add(v)
        session.commit()
        session.refresh(v)
        assert v.id is not None
        path = rendering.render_resume_version(session, v.id)
    assert path is not None
    assert Path(path).name == "out.pdf"


def test_fail_on_partial_raises_only_when_everything_failed(monkeypatch, session):
    job = Job(source="manual", jd_text="jd", status=JobStatus.approved.value)
    session.add(job)
    session.commit()
    session.refresh(job)
    assert job.id is not None
    job_id = job.id
    failure = StageFailure(
        error_type="ValueError",
        message="match_plan_enabled requires a match-plan agent",
        traceback_tail="",
    )
    monkeypatch.setattr(
        tailoring,
        "tailor_jobs",
        lambda *a, **k: TailorOutcome(versions={}, failures={job_id: failure}),
    )
    monkeypatch.setattr(tailoring, "enforce_active_budget", lambda: None)
    monkeypatch.setattr(tailoring, "load_facts", lambda p: object())
    monkeypatch.setattr(
        tailoring, "load_review_config",
        lambda p: type("C", (), {"style_guide_path": None, "reviewers": []})(),
    )
    monkeypatch.setattr(tailoring, "load_style_guide", lambda p: None)
    monkeypatch.setattr(
        tailoring, "build_tailor_bundle",
        lambda config, style_guide=None: tailoring.TailorBundle(
            tailor=_RunnerStub("t"), reviser=_RunnerStub("r"), reviewers={},
            revision=_RunnerStub("revise"),
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        tailoring.tailor(session, job_ids=[job_id], fail_on_partial=True)

    # The whole point: the cause is named, not just counted.
    assert "match_plan_enabled requires a match-plan agent" in str(excinfo.value)
    assert "ValueError" in str(excinfo.value)


def test_partial_failure_does_not_raise(monkeypatch, session):
    ok = Job(source="manual", jd_text="a", status=JobStatus.approved.value)
    bad = Job(source="manual", jd_text="b", status=JobStatus.approved.value)
    session.add(ok)
    session.add(bad)
    session.commit()
    session.refresh(ok)
    session.refresh(bad)
    assert ok.id is not None
    assert bad.id is not None
    ok_id, bad_id = ok.id, bad.id
    failure = StageFailure(error_type="RuntimeError", message="boom", traceback_tail="")
    monkeypatch.setattr(
        tailoring,
        "tailor_jobs",
        lambda *a, **k: TailorOutcome(versions={ok_id: []}, failures={bad_id: failure}),
    )
    monkeypatch.setattr(tailoring, "enforce_active_budget", lambda: None)
    monkeypatch.setattr(tailoring, "load_facts", lambda p: object())
    monkeypatch.setattr(
        tailoring, "load_review_config",
        lambda p: type("C", (), {"style_guide_path": None, "reviewers": []})(),
    )
    monkeypatch.setattr(tailoring, "load_style_guide", lambda p: None)
    monkeypatch.setattr(
        tailoring, "build_tailor_bundle",
        lambda config, style_guide=None: tailoring.TailorBundle(
            tailor=_RunnerStub("t"), reviser=_RunnerStub("r"), reviewers={},
            revision=_RunnerStub("revise"),
        ),
    )
    monkeypatch.setattr(tailoring, "export_job_artifacts", lambda *a, **k: None)

    outcome = tailoring.tailor(
        session, job_ids=[ok_id, bad_id], fail_on_partial=True
    )

    assert list(outcome.versions) == [ok.id]
    assert list(outcome.failures) == [bad.id]
