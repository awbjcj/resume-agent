from sqlmodel import Session, SQLModel, create_engine

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.tracking.match_gap import (
    DemandEdge,
    DemandGraph,
    JobLite,
    SkillNode,
    build_demand_graph,
    collect_target_skill_tokens,
)
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _job(session, *, criteria, company="C", title="T", status=None):
    return save_job(
        session,
        Job(
            source="manual",
            company=company,
            title=title,
            status=status or JobStatus.shortlisted.value,
            criteria_json=criteria,
        ),
    )


def _facts(skills=None):
    return ProfileFacts(contact=Contact(name="A"), skills=skills or {})


def test_build_demand_graph_reads_all_sources_coverage_and_job_facets():
    with _session() as session:
        job = _job(
            session,
            company="Acme",
            title="Platform Engineer",
            criteria={
                "seniority": "senior",
                "must_have_skills": "Python",
                "nice_to_have_skills": ["Kubernetes"],
                "tech_stack": ["Docker"],
            },
        )

        graph = build_demand_graph(
            session,
            _facts({"languages": [Skill(name="PYTHON")]}),
        )

        assert job.id is not None
        assert graph.target_total == 1
        assert graph.jobs == [
            JobLite(
                id=job.id,
                company="Acme",
                title="Platform Engineer",
                seniority="senior",
            )
        ]
        assert graph.skills == [
            SkillNode(skill="python", theme_id=None, covered=True),
            SkillNode(skill="kubernetes", theme_id=None, covered=False),
            SkillNode(skill="docker", theme_id=None, covered=False),
        ]
        assert graph.edges == [
            DemandEdge(job_id=job.id, skill="python", source="must"),
            DemandEdge(job_id=job.id, skill="kubernetes", source="nice"),
            DemandEdge(job_id=job.id, skill="docker", source="tech"),
        ]
        assert graph.themes == []
        assert graph.clusters_stale is True


def test_build_demand_graph_dedupes_skill_nodes_and_each_job_source_edge():
    with _session() as session:
        first = _job(
            session,
            criteria={
                "must_have_skills": ["Python", "PYTHON", " python "],
                "nice_to_have_skills": ["Python"],
            },
        )
        second = _job(session, criteria={"tech_stack": "PYTHON"})

        graph = build_demand_graph(session, _facts())

        assert first.id is not None
        assert second.id is not None
        assert graph.skills == [
            SkillNode(skill="python", theme_id=None, covered=False)
        ]
        assert graph.edges == [
            DemandEdge(job_id=first.id, skill="python", source="must"),
            DemandEdge(job_id=first.id, skill="python", source="nice"),
            DemandEdge(job_id=second.id, skill="python", source="tech"),
        ]


def test_build_demand_graph_empty_db_is_exact():
    with _session() as session:
        graph = build_demand_graph(session, _facts())

        assert graph == DemandGraph(
            target_total=0,
            clusters_stale=False,
            jobs=[],
            skills=[],
            edges=[],
            themes=[],
        )


def test_collect_target_skill_tokens_unions_sources_and_ignores_nontarget_jobs():
    with _session() as session:
        _job(
            session,
            criteria={
                "must_have_skills": " Rust ",
                "nice_to_have_skills": ["Go", ""],
                "tech_stack": {"unexpected": "mapping"},
            },
        )
        _job(
            session,
            status=JobStatus.filtered.value,
            criteria={"must_have_skills": ["Scala"]},
        )

        assert collect_target_skill_tokens(session) == {"rust", "go"}
