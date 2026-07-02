from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.store import save_facts
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.tracking.tables import Job

runner = CliRunner()


def _seed_job(db_url, status, must_have):
    engine = make_engine(db_url)
    init_db(engine)
    with get_session(engine) as session:
        session.add(
            Job(
                source="manual",
                company="C",
                title="T",
                status=status,
                criteria_json={"must_have_skills": must_have},
            )
        )
        session.commit()


def test_match_gap_prints_aggregate(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed_job(db_url, "shortlisted", ["Kubernetes"])
    _seed_job(db_url, "approved", ["Kubernetes", "Go"])
    monkeypatch.setattr(
        cli,
        "load_facts",
        lambda path: ProfileFacts(contact=Contact(name="A"), skills={}),
    )

    result = runner.invoke(cli.app, ["match-gap", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "Kubernetes" in result.output
    assert "2/2" in result.output


def test_match_gap_no_target_jobs(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    init_db(make_engine(db_url))
    monkeypatch.setattr(
        cli,
        "load_facts",
        lambda path: ProfileFacts(contact=Contact(name="A"), skills={}),
    )

    result = runner.invoke(cli.app, ["match-gap", "--db-url", db_url])

    assert result.exit_code == 0
    assert "No jobs past discovery" in result.output


def test_match_gap_per_job(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed_job(db_url, "shortlisted", ["Kubernetes", "Python"])
    monkeypatch.setattr(
        cli,
        "load_facts",
        lambda path: ProfileFacts(
            contact=Contact(name="A"),
            skills={"lang": [Skill(name="Python")]},
        ),
    )

    result = runner.invoke(cli.app, ["match-gap", "--job-id", "1", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "Kubernetes" in result.output
    assert "Python" not in result.output


def test_match_gap_uses_effective_persisted_map_before_llm_fallback(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    _seed_job(db_url, "shortlisted", ["FastAPI"])
    profile_dir = tmp_path / "profile"
    facts_path = profile_dir / "facts.json"
    save_facts(
        ProfileFacts(
            contact=Contact(name="A"),
            skills={"Frameworks": [Skill(name="Flask")]},
        ),
        facts_path,
    )
    save_cluster_map(
        ClusterMap(theme_of={"flask": "web", "fastapi": "web"}),
        profile_dir / "cluster_map.json",
    )
    monkeypatch.setattr(
        cli,
        "build_skill_canonicalizer",
        lambda: (_ for _ in ()).throw(AssertionError("LLM fallback must not run")),
    )

    result = runner.invoke(
        cli.app,
        ["match-gap", "--facts", str(facts_path), "--llm", "--db-url", db_url],
    )

    assert result.exit_code == 0, result.output
    assert "FastAPI" in result.output
    assert "adjacent" in result.output
