from pathlib import Path

import pytest

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.matrix import Overrides, build_matrix, save_matrix
from resume_agent.profile.store import save_facts
from resume_agent.services import rendering, tailoring
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.tracking.tables import Job, JobStatus, ResumeVersion


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
    ):
        captured["targets"] = [j.id for j in targets]
        captured["match_plan"] = match_plan_agent
        captured["skill_matrix"] = skill_matrix
        return {targets[0].id: ["v1"]}

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


def test_tailor_can_fail_loudly_when_a_target_produces_no_resume(monkeypatch):
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
        monkeypatch.setattr(
            tailoring,
            "tailor_jobs",
            lambda *args, **kwargs: {jobs[0].id: ["v1"]},
        )
        monkeypatch.setattr(tailoring, "export_job_artifacts", lambda *args, **kwargs: None)

        with pytest.raises(RuntimeError, match="failed for 1 of 2 jobs"):
            tailoring.tailor(
                session,
                job_ids=[job.id for job in jobs if job.id is not None],
                fail_on_partial=True,
            )


def test_tailor_loads_bound_skill_artifacts_once(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    facts_path = profile_dir / "facts.json"
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Platforms": [Skill(name="Kubernetes")]},
    )
    cluster_map = ClusterMap(aliases={"k8s": "kubernetes"})
    save_facts(facts, facts_path)
    save_cluster_map(cluster_map, profile_dir / "cluster_map.json")
    save_matrix(
        build_matrix(facts, cluster_map, Overrides()), profile_dir / "matrix.json"
    )
    captured = {}

    def fake_tailor_jobs(*args, **kwargs):
        captured.update(kwargs)
        return {args[1][0].id: ["v1"]}

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
    assert captured["cluster_map"].aliases["k8s"] == "kubernetes"


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
