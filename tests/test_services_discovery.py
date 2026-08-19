import httpx
import pytest

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.connectors.base import RawJob
import resume_agent.profile.effective as effective_module
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.effective import build_effective_taxonomy
from resume_agent.profile.matrix import build_matrix, save_matrix
from resume_agent.profile.store import save_facts
from resume_agent.services import discovery
from resume_agent.services.agents import DiscoveryBundle
from resume_agent.services.discovery import UrlFetchError
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)


def _session():
    engine = make_engine("sqlite://")
    init_db(engine)
    return get_session(engine)


class _RunnerStub:
    """Minimal Runner protocol stand-in for tests that never invoke it."""

    def __init__(self, value=None):
        self.value = value

    def run(self, prompt: str):
        return self.value

    async def arun(self, prompt: str):
        return self.value


def test_add_job_from_text_inserts(tmp_path):
    with _session() as session:
        job = discovery.add_job_from_text(
            session, jd_text="We need a Python engineer.", company="Acme", title="SWE"
        )
    assert job is not None
    assert job.source == "manual"
    assert job.company == "Acme"


def test_skill_artifacts_uses_taxonomy_corrections(tmp_path, monkeypatch):
    profile_dir = tmp_path / "profile"
    facts_path = profile_dir / "facts.json"
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="JS")]},
    )
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_cluster_map(
        ClusterMap(domain_of={"javascript": "web"}),
        profile_dir / "cluster_map.json",
    )
    save_taxonomy_corrections(
        TaxonomyCorrections(aliases={"js": "javascript"}), corrections_path
    )
    save_facts(facts, facts_path)
    monkeypatch.setattr(
        effective_module, "corrections_file_path", lambda: str(corrections_path)
    )
    taxonomy = build_effective_taxonomy(profile_dir)
    save_matrix(build_matrix(facts, taxonomy), profile_dir / "matrix.json")

    matrix, cluster_map = discovery._skill_artifacts(str(facts_path), facts)

    assert matrix is not None
    assert [row.key for row in matrix.rows] == ["javascript"]
    assert cluster_map.aliases["js"] == "javascript"


def test_discover_jobs_delegates_and_forwards_bundle(monkeypatch, tmp_path):
    seen = {}

    def _canonicalizer(skills: set[str]) -> dict[str, str]:
        return {"value": "c"}

    bundle = DiscoveryBundle(
        extract=_RunnerStub("e"),
        fit=_RunnerStub("f"),
        relevance=_RunnerStub("r"),
        canonicalizer=_canonicalizer,
        industry_classifier=_RunnerStub("i"),
    )

    def fake_discover(
        session,
        config,
        facts,
        extract,
        fit,
        relevance,
        canonicalizer=None,
        industry_classifier=None,
        reporter=None,
        scope=None,
        matrix=None,
        cluster_map=None,
    ):
        seen["relevance"] = relevance
        seen["canonicalizer"] = canonicalizer
        seen["industry_classifier"] = industry_classifier
        return {"raw": 0, "shortlisted": 2}

    monkeypatch.setattr(discovery, "discover", fake_discover)
    monkeypatch.setattr(discovery, "load_search_config", lambda p: object())
    monkeypatch.setattr(discovery, "load_facts", lambda p: object())
    monkeypatch.setattr(discovery, "build_discovery_bundle", lambda: bundle)
    with _session() as session:
        counts = discovery.discover_jobs(session, search_path="x", facts_path="y")
    assert counts == {"raw": 0, "shortlisted": 2}
    assert seen == {
        "relevance": bundle.relevance,
        "canonicalizer": bundle.canonicalizer,
        "industry_classifier": bundle.industry_classifier,
    }


def test_discover_jobs_with_empty_job_ids_scopes_to_nothing_not_everything(
    monkeypatch, tmp_path
):
    """An explicit empty set means 'no jobs' -- refresh_jobs relies on this when
    a pull finds zero new/changed raw jobs. Falling back to the unscoped
    default here would silently re-run the funnel over the whole backlog."""
    seen = {}

    def fake_discover(session, config, facts, extract, fit, relevance, **kwargs):
        seen["scope"] = kwargs["scope"]
        return {}

    monkeypatch.setattr(discovery, "discover", fake_discover)
    monkeypatch.setattr(discovery, "load_search_config", lambda p: object())
    monkeypatch.setattr(discovery, "load_facts", lambda p: object())
    monkeypatch.setattr(
        discovery,
        "build_discovery_bundle",
        lambda: DiscoveryBundle(
            extract=_RunnerStub(), fit=_RunnerStub(), relevance=None,
            canonicalizer=None, industry_classifier=_RunnerStub(),
        ),
    )
    with _session() as session:
        discovery.discover_jobs(session, job_ids=set())

    assert seen["scope"].job_ids == frozenset()


def test_add_job_from_url_extracts_and_overrides(monkeypatch):
    monkeypatch.setattr(discovery, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(
        discovery, "job_from_url",
        lambda url, *, agent, allow_browser=True: RawJob(
            source="url", url=url, company="Acme", title="Engineer",
            location="Remote", jd_text="Build.",
        ),
    )
    with _session() as session:
        job = discovery.add_job_from_url(session, url="https://x/job", company="Globex")
    assert job is not None
    assert job.company == "Globex"  # explicit override wins
    assert job.title == "Engineer"  # extracted value kept


def test_add_job_from_url_raises_on_fetch_error(monkeypatch):
    monkeypatch.setattr(discovery, "build_url_extract_agent", lambda: object())

    def _raise(url, *, agent, allow_browser=True):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(discovery, "job_from_url", _raise)
    with _session() as session:
        with pytest.raises(UrlFetchError, match="Couldn't fetch"):
            discovery.add_job_from_url(session, url="https://x/job")


def test_add_job_from_url_raises_when_no_extraction(monkeypatch):
    monkeypatch.setattr(discovery, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(discovery, "job_from_url", lambda url, *, agent, allow_browser=True: None)
    with _session() as session:
        with pytest.raises(UrlFetchError, match="Couldn't extract"):
            discovery.add_job_from_url(session, url="https://x/job")


# ---------------------------------------------------------------------------
# Task-7 tests: reprocess_jobs + run_pull finish=False
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, content):
        self.content = content


class _ExtractRunner:
    def run(self, prompt: str):
        from resume_agent.models.job import JobCriteriaExtract, SponsorshipSignal

        return _FakeResult(JobCriteriaExtract.model_validate(dict(
            sponsorship_signal=SponsorshipSignal.offered, seniority=None,
            employment_type=None, tech_stack=[], industry=None, company_size=None,
            yoe_min=None, salary_range=None, remote_policy=None, location=None,
            must_have_skills=[], nice_to_have_skills=[],
        )))

    async def arun(self, prompt: str):
        return self.run(prompt)


class _FitRunner:
    def run(self, prompt: str):
        from resume_agent.discovery.fit import FitScore

        return _FakeResult(FitScore(score=77, rationale="ok"))

    async def arun(self, prompt: str):
        return self.run(prompt)


class _IndustryRunner:
    def run(self, prompt: str):
        from resume_agent.discovery.industry import IndustryClassification

        return _FakeResult(IndustryClassification(groups=[]))

    async def arun(self, prompt: str):
        return self.run(prompt)


def _bundle():
    from resume_agent.services.agents import DiscoveryBundle

    extract = _ExtractRunner()
    fit = _FitRunner()
    return DiscoveryBundle(
        extract=extract,
        fit=fit,
        relevance=None,
        canonicalizer=None,
        industry_classifier=_IndustryRunner(),
    )


def test_reprocess_jobs_rescores_shortlisted(tmp_path):
    from resume_agent.services.discovery import reprocess_jobs
    from resume_agent.tracking.repository import jobs_by_status, save_job
    from resume_agent.tracking.tables import Job, JobStatus

    facts = tmp_path / "facts.json"
    facts.write_text('{"contact": {"name": "Ada"}}', "utf-8")
    search = tmp_path / "search.yaml"
    search.write_text("titles: []\n", "utf-8")

    with _session() as s:
        save_job(s, Job(
            source="x", jd_text="jd", title="Eng",
            status=JobStatus.shortlisted.value, fit_score=10, criteria_json={},
        ))
        counts = reprocess_jobs(
            s, scopes=["shortlisted"],
            search_path=str(search), facts_path=str(facts),
            bundle=_bundle(),
        )
        assert jobs_by_status(s, JobStatus.shortlisted.value)[0].fit_score == 77
        assert counts[JobStatus.shortlisted.value] == 1


def test_run_pull_finish_false_does_not_emit_done(tmp_path):
    from resume_agent.discovery.connectors.runner import run_pull
    from resume_agent.discovery.search_config import SearchConfig
    from resume_agent.progress import ProgressReporter, read_progress

    with _session() as s:
        reporter = ProgressReporter("refresh", tmp_path)
        run_pull(s, [], SearchConfig(), tmp_path / "runs.json", reporter=reporter, finish=False)
    rec = read_progress("refresh", tmp_path)
    assert rec is not None and rec["state"] == "running"  # not "done"


def test_refresh_jobs_discovers_only_pull_changed_raw_jobs(monkeypatch):
    from resume_agent.discovery.connectors.runner import PullReport
    from resume_agent.services.discovery import RefreshReport, refresh_jobs

    seen = {}

    def fake_pull_jobs(session, **kwargs):
        report = PullReport()
        report.totals["manual"] = 1
        report.changed_raw_job_ids.append(42)
        return report

    def fake_discover_jobs(session, **kwargs):
        seen["job_ids"] = kwargs["job_ids"]
        return {"shortlisted": 1}

    monkeypatch.setattr(discovery, "pull_jobs", fake_pull_jobs)
    monkeypatch.setattr(discovery, "discover_jobs", fake_discover_jobs)

    with _session() as s:
        report = refresh_jobs(s)

    assert report == RefreshReport(
        pulled=1,
        totals={"manual": 1},
        status_counts={"shortlisted": 1},
        failures={},
    )
    assert seen["job_ids"] == {42}
