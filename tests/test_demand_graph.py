from sqlmodel import Session, SQLModel, create_engine

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.taxonomy.clusters import ClusterMap, merge_cluster_map
from resume_agent.tracking.match_gap import (
    DemandEdge,
    DemandGraph,
    JobLite,
    SkillNode,
    ThemeNode,
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
                "nice_to_have_skills": [" Kubernetes ", "Go"],
                "tech_stack": ["Linux"],
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
            SkillNode("Go", None, False, "go", {"Go": 1}, nice=1, job_count=1),
            SkillNode(
                "Kubernetes",
                None,
                False,
                "kubernetes",
                {"Kubernetes": 1},
                nice=1,
                job_count=1,
            ),
            SkillNode("Linux", None, False, "linux", {"Linux": 1}, tech=1, job_count=1),
            SkillNode("Python", None, True, "python", {"Python": 1}, must=1, job_count=1),
        ]
        assert graph.edges == [
            DemandEdge(job.id, "Python", "must", "python"),
            DemandEdge(job.id, "Go", "nice", "go"),
            DemandEdge(job.id, "Kubernetes", "nice", "kubernetes"),
            DemandEdge(job.id, "Linux", "tech", "linux"),
        ]
        assert graph.themes == []
        assert graph.clusters_stale is True


def test_build_demand_graph_dedupes_skill_nodes_and_each_job_source_edge():
    with _session() as session:
        first = _job(
            session,
            criteria={
                "must_have_skills": [" Python ", "PYTHON", " python "],
                "nice_to_have_skills": ["Python"],
            },
        )
        second = _job(session, criteria={"tech_stack": "PYTHON"})

        graph = build_demand_graph(session, _facts())

        assert first.id is not None
        assert second.id is not None
        assert graph.skills == [
            SkillNode(
                "PYTHON",
                None,
                False,
                "python",
                {"PYTHON": 2, "Python": 1, "python": 1},
                must=1,
                nice=1,
                tech=1,
                job_count=2,
            )
        ]
        assert graph.edges == [
            DemandEdge(first.id, "PYTHON", "must", "python"),
            DemandEdge(first.id, "PYTHON", "nice", "python"),
            DemandEdge(second.id, "PYTHON", "tech", "python"),
        ]


def test_build_demand_graph_aliases_dedupe_edges_and_cover_canonical_skill():
    with _session() as session:
        job = _job(
            session,
            criteria={
                "must_have_skills": ["K8s", "Kubernetes", " k8s "],
                "nice_to_have_skills": ["KUBERNETES"],
            },
        )
        cmap = ClusterMap(aliases={"k8s": "kubernetes"})

        graph = build_demand_graph(
            session,
            _facts({"infra": [Skill(name="Kubernetes")]}),
            cmap,
        )

        assert job.id is not None
        assert graph.skills == [
            SkillNode(
                "K8s",
                None,
                True,
                "kubernetes",
                {"K8s": 1, "k8s": 1, "KUBERNETES": 1, "Kubernetes": 1},
                must=1,
                nice=1,
                job_count=1,
            )
        ]
        assert graph.edges == [
            DemandEdge(job.id, "K8s", "must", "kubernetes"),
            DemandEdge(job.id, "K8s", "nice", "kubernetes"),
        ]


def test_build_demand_graph_applies_aliases_to_profile_skill_coverage():
    with _session() as session:
        _job(
            session,
            criteria={"must_have_skills": ["Kubernetes"]},
        )
        cmap = ClusterMap(
            aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"}
        )

        graph = build_demand_graph(
            session,
            _facts({"infra": [Skill(name="K8s")]}),
            cmap,
        )

        assert graph.skills == [
            SkillNode(
                "Kubernetes",
                None,
                True,
                "kubernetes",
                {"Kubernetes": 1},
                must=1,
                job_count=1,
            )
        ]


def test_build_demand_graph_dedupes_flattened_alias_chain_with_coverage():
    with _session() as session:
        job = _job(
            session,
            criteria={"must_have_skills": ["A", "B", "C"]},
        )
        cmap = merge_cluster_map(
            ClusterMap.empty(),
            ClusterMap(
                aliases={"a": "b", "b": "c"},
                theme_of={"b": "terminal-theme"},
                theme_label={"terminal-theme": "Terminal"},
            ),
        )

        graph = build_demand_graph(
            session,
            _facts({"category": [Skill(name="B")]}),
            cmap,
        )

        assert job.id is not None
        assert graph.skills == [
            SkillNode(
                "A",
                "terminal-theme",
                True,
                "c",
                {"A": 1, "B": 1, "C": 1},
                must=1,
                job_count=1,
            )
        ]
        assert graph.edges == [DemandEdge(job.id, "A", "must", "c")]


def test_build_demand_graph_emits_only_used_sorted_themes_with_label_fallback():
    with _session() as session:
        _job(
            session,
            criteria={"must_have_skills": ["React", "Kubernetes"]},
        )
        cmap = ClusterMap(
            theme_of={
                "react": "z-frontend",
                "kubernetes": "a-infra",
                "unused": "unused-theme",
            },
            theme_label={
                "a-infra": "Cloud/Infra",
                "unused-theme": "Unused",
            },
        )

        graph = build_demand_graph(session, _facts(), cmap)

        assert graph.skills == [
            SkillNode(
                "Kubernetes",
                "a-infra",
                False,
                "kubernetes",
                {"Kubernetes": 1},
                must=1,
                job_count=1,
            ),
            SkillNode(
                "React",
                "z-frontend",
                False,
                "react",
                {"React": 1},
                must=1,
                job_count=1,
            ),
        ]
        assert graph.themes == [
            ThemeNode("a-infra", "Cloud/Infra", 3, 1, 1, 1, 1),
            ThemeNode("z-frontend", "z-frontend", 3, 1, 1, 1, 1),
        ]
        assert graph.clusters_stale is False


def test_build_demand_graph_is_stale_when_any_canonical_skill_is_unthemed():
    with _session() as session:
        _job(
            session,
            criteria={"must_have_skills": ["Kubernetes", "Rust"]},
        )
        cmap = ClusterMap(
            theme_of={"kubernetes": "infra"},
            theme_label={"infra": "Infrastructure"},
        )

        graph = build_demand_graph(session, _facts(), cmap)

        assert graph.themes == [ThemeNode("infra", "Infrastructure", 3, 1, 1, 1, 1)]
        assert graph.clusters_stale is True


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


def test_build_demand_graph_uses_stable_keys_and_distinct_job_counts():
    with _session() as session:
        first = _job(
            session,
            criteria={
                "must_have_skills": ["Python", "Python"],
                "nice_to_have_skills": ["Python"],
            },
        )
        second = _job(session, criteria={"must_have_skills": ["python3"]})
        cmap = ClusterMap(
            aliases={"python": "python", "python3": "python"},
            theme_of={"python": "backend"},
            theme_label={"backend": "Backend"},
        )

        graph = build_demand_graph(session, _facts(), cmap)

        assert first.id is not None
        assert second.id is not None
        assert graph.skills == [
            SkillNode(
                skill="Python",
                theme_id="backend",
                covered=False,
                key="python",
                members={"Python": 1, "python3": 1},
                must=2,
                nice=1,
                tech=0,
                job_count=2,
            )
        ]
        assert {(edge.job_id, edge.skill_key, edge.source) for edge in graph.edges} == {
            (first.id, "python", "must"),
            (first.id, "python", "nice"),
            (second.id, "python", "must"),
        }


def test_build_demand_graph_theme_aggregates_have_named_weightings():
    with _session() as session:
        _job(
            session,
            criteria={
                "must_have_skills": ["Python", "SQL"],
                "tech_stack": ["Python"],
            },
        )
        _job(session, criteria={"nice_to_have_skills": ["Python"]})
        cmap = ClusterMap(
            theme_of={"python": "backend", "sql": "backend"},
            theme_label={"backend": "Backend"},
        )

        graph = build_demand_graph(
            session,
            _facts({"data": [Skill(name="SQL")]}),
            cmap,
        )

        assert graph.themes == [
            ThemeNode(
                id="backend",
                label="Backend",
                essential_score=9,
                popular_score=3,
                job_count=2,
                skill_count=2,
                gap_count=0,
                adjacent_count=1,
            )
        ]


def test_build_demand_graph_output_does_not_depend_on_skill_input_order():
    def snapshot(raw_skills):
        with _session() as session:
            _job(session, criteria={"must_have_skills": raw_skills})
            cmap = ClusterMap(aliases={"python": "python", "python3": "python"})
            graph = build_demand_graph(session, _facts(), cmap)
            return (
                [(node.key, node.skill, node.members) for node in graph.skills],
                [(edge.skill_key, edge.skill, edge.source) for edge in graph.edges],
            )

    assert snapshot(["python3", "Python", "Go"]) == snapshot(
        ["Go", "Python", "python3"]
    )
