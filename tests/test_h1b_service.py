import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlmodel import Session

from resume_agent.config import Settings
from resume_agent.db import init_db, make_engine
from resume_agent.h1b.models import (
    H1BCompanyResolution,
    H1B_MCP_UNAVAILABLE_REASON,
    HISTORICAL_ONLY_CAVEAT,
    H1BSponsorshipEvidence,
)
from resume_agent.h1b.service import check_job_sponsorship, enrich_companies
from resume_agent.tracking.tables import Job


def _evidence(company: str) -> H1BSponsorshipEvidence:
    now = datetime.now(timezone.utc)
    return H1BSponsorshipEvidence(
        status="matched",
        normalized_company=company,
        display_company=company,
        fiscal_periods=["2024"],
        filing_count=2,
        certified_count=1,
        wage_summary={"median": 150000.0},
        source_url="https://example.com/data",
        data_version="fixture-v1",
        retrieved_at=now,
        expires_at=now + timedelta(days=1),
        confidence=0.8,
        caveat=HISTORICAL_ONLY_CAVEAT,
    )


class FakeRunner:
    def __init__(self):
        self.calls: list[str] = []

    def run(self, prompt: str) -> SimpleNamespace:
        raise NotImplementedError

    async def arun(self, prompt: str) -> SimpleNamespace:
        self.calls.append(prompt)
        company = "acme"
        return SimpleNamespace(content=_evidence(company))


class ClosingRunner(FakeRunner):
    def __init__(self, events: list[str]):
        super().__init__()
        self.events = events
        self.closed = False

    async def aclose(self) -> None:
        self.events.append("runner_close")
        self.closed = True


class NamedCompanyRunner(FakeRunner):
    def __init__(self, company: str):
        super().__init__()
        self.company = company

    async def arun(self, prompt: str) -> SimpleNamespace:
        self.calls.append(prompt)
        return SimpleNamespace(content=_evidence(self.company))


class ResolutionRunner:
    def __init__(self, resolution: H1BCompanyResolution):
        self.resolution = resolution
        self.calls: list[str] = []

    def run(self, prompt: str) -> SimpleNamespace:
        raise NotImplementedError

    async def arun(self, prompt: str) -> SimpleNamespace:
        self.calls.append(prompt)
        return SimpleNamespace(content=self.resolution)


class NameResolverFactory:
    def __init__(self, runner: ResolutionRunner):
        self.runner = runner

    def build(self) -> ResolutionRunner:
        return self.runner


class Factory:
    def __init__(self, runner):
        self.runner = runner

    def build(self, tools: object) -> FakeRunner:
        return self.runner


def test_disabled_enrichment_is_unavailable_without_building_agent():
    engine = make_engine("sqlite://")
    init_db(engine)
    runner = FakeRunner()
    report = __import__("asyncio").run(
        enrich_companies(
            engine,
            ["Acme, Inc."],
            settings=Settings(
                _env_file=None,  # type: ignore[call-arg]
                h1b_mcp_enabled=False,
            ),
            agent_factory=Factory(runner),
        )
    )
    assert report.by_company["acme"].status == "unavailable"
    assert runner.calls == []


def test_duplicate_company_spellings_are_researched_once_and_then_cached(monkeypatch):
    import resume_agent.h1b.service as service

    @asynccontextmanager
    async def fake_tools(settings):
        yield object()

    monkeypatch.setattr(service, "h1b_tools", fake_tools)
    engine = make_engine("sqlite://")
    init_db(engine)
    runner = FakeRunner()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )
    first = asyncio.run(
        enrich_companies(
            engine,
            ["Acme, Inc.", "ACME"],
            settings=settings,
            agent_factory=Factory(runner),
        )
    )
    second = asyncio.run(
        enrich_companies(
            engine,
            ["acme"],
            settings=settings,
            agent_factory=Factory(runner),
        )
    )
    assert first.researched == 1
    assert len(runner.calls) == 1
    assert second.cache_hits == 1
    assert second.researched == 0

    refreshed = asyncio.run(
        enrich_companies(
            engine,
            ["acme"],
            settings=settings,
            agent_factory=Factory(runner),
            force_refresh=True,
        )
    )
    assert refreshed.researched == 1
    assert len(runner.calls) == 2


def test_equivalent_legal_company_name_is_canonicalized_to_the_cache_key(monkeypatch):
    import resume_agent.h1b.service as service

    @asynccontextmanager
    async def fake_tools(_settings):
        yield object()

    monkeypatch.setattr(service, "h1b_tools", fake_tools)
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )

    report = asyncio.run(
        enrich_companies(
            engine,
            ["Google"],
            settings=settings,
            agent_factory=Factory(NamedCompanyRunner("Google LLC")),
        )
    )

    assert report.by_company["google"].status == "matched"
    assert report.by_company["google"].normalized_company == "google"


def test_company_name_resolver_rewrites_the_query_before_h1b_research(monkeypatch):
    import resume_agent.h1b.service as service

    @asynccontextmanager
    async def fake_tools(_settings):
        yield object()

    monkeypatch.setattr(service, "h1b_tools", fake_tools)
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
        cheap_model="cheap-company-resolver",
    )
    resolver = ResolutionRunner(
        H1BCompanyResolution(
            status="resolved",
            legal_name="Acme, Inc.",
            confidence=0.98,
        )
    )
    sponsor = FakeRunner()

    report = asyncio.run(
        enrich_companies(
            engine,
            ["ACME"],
            settings=settings,
            agent_factory=Factory(sponsor),
            company_resolver_factory=NameResolverFactory(resolver),
        )
    )

    assert report.by_company["acme"].status == "matched"
    assert resolver.calls
    assert "H-1B/LCA/green-card sponsorship records" in resolver.calls[0]
    assert sponsor.calls
    assert "Acme, Inc." in sponsor.calls[0]


def test_company_name_resolver_rejects_a_different_company_identity():
    import resume_agent.h1b.service as service

    runner = ResolutionRunner(
        H1BCompanyResolution(
            status="resolved",
            legal_name="Toyota Motor Corporation",
            confidence=0.99,
        )
    )

    resolved = asyncio.run(service._resolve_company_name(runner, "ACME"))

    assert resolved == "ACME"


def test_manual_job_check_records_cache_pointer_without_snapshot(monkeypatch):
    import resume_agent.h1b.service as service

    @asynccontextmanager
    async def fake_tools(_settings):
        yield object()

    monkeypatch.setattr(service, "h1b_tools", fake_tools)
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )

    with Session(engine) as session:
        job = Job(source="manual", company="Acme", jd_text="x")
        session.add(job)
        session.commit()
        session.refresh(job)

        evidence = asyncio.run(
            check_job_sponsorship(
                session,
                job,
                settings=settings,
                agent_factory=Factory(FakeRunner()),
            )
        )

        assert evidence is not None
        assert evidence.status == "matched"
        meta = job.analysis_meta_json or {}
        assert meta.get("h1b_evidence_id") is not None
        assert meta.get("h1b_evidence_snapshot") is None


def test_manual_check_records_the_cache_pointer_but_no_snapshot():
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )

    @asynccontextmanager
    async def fake_tools(_settings, **_kwargs):
        yield object()

    with Session(engine) as session:
        job = Job(source="manual", company="Acme, Inc.", title="Engineer", jd_text="x")
        session.add(job)
        session.commit()
        session.refresh(job)

        import resume_agent.h1b.service as service

        original = service.h1b_tools
        service.h1b_tools = fake_tools
        try:
            asyncio.run(
                check_job_sponsorship(
                    session,
                    job,
                    settings=settings,
                    agent_factory=Factory(FakeRunner()),
                )
            )
        finally:
            service.h1b_tools = original

        meta = job.analysis_meta_json or {}
        assert meta.get("h1b_evidence_id") is not None
        assert meta.get("h1b_evidence_snapshot") is None


def test_unavailable_results_use_the_short_retry_expiry(monkeypatch):
    import resume_agent.h1b.service as service

    @asynccontextmanager
    async def failing_tools(_settings):
        raise RuntimeError("MCP is down")
        yield

    monkeypatch.setattr(service, "h1b_tools", failing_tools)
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
        h1b_cache_ttl_days=30,
    )

    report = asyncio.run(
        enrich_companies(
            engine,
            ["Acme"],
            settings=settings,
            agent_factory=Factory(FakeRunner()),
        )
    )

    evidence = report.by_company["acme"]
    assert evidence.status == "unavailable"
    assert evidence.unavailable_reason == H1B_MCP_UNAVAILABLE_REASON
    assert evidence.expires_at is not None
    assert evidence.retrieved_at is not None
    assert evidence.expires_at <= evidence.retrieved_at + timedelta(minutes=5)


def test_enrichment_closes_runner_before_mcp_context(monkeypatch):
    import resume_agent.h1b.service as service

    events: list[str] = []

    @asynccontextmanager
    async def fake_tools(_settings):
        events.append("tools_enter")
        try:
            yield object()
        finally:
            events.append("tools_close")

    monkeypatch.setattr(service, "h1b_tools", fake_tools)
    engine = make_engine("sqlite://")
    init_db(engine)
    runner = ClosingRunner(events)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )

    report = asyncio.run(
        enrich_companies(
            engine,
            ["Acme"],
            settings=settings,
            agent_factory=Factory(runner),
        )
    )

    assert report.by_company["acme"].status == "matched"
    assert runner.closed is True
    assert events == ["tools_enter", "runner_close", "tools_close"]


def test_sponsorship_agent_is_instructed_to_collect_three_years():
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        anthropic_api_key="test-key",
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )
    from resume_agent.h1b.service import DefaultSponsorshipAgentFactory

    runner = DefaultSponsorshipAgentFactory(settings).build(tools=None)
    # AgentRunner intentionally narrows the public runner API; tests in this
    # repository inspect its wrapped agent for prompt-contract assertions.
    instructions = " ".join(runner._agent.instructions)
    assert "get_company_stats" in instructions
    assert "get_company_sponsorship_trend" in instructions
    assert "three-year" in instructions
    assert "twelve periods" in instructions
    assert "periods" in instructions
    assert runner.run_meta is not None
    assert runner.run_meta.prompt_policy_version == "h1b-sponsorship-research-v3"


def test_persisted_rows_are_written_at_schema_version_two():
    from resume_agent.tracking.tables import H1BCompanyEvidence
    from sqlmodel import select as model_select

    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )

    @asynccontextmanager
    async def fake_tools(_settings, **_kwargs):
        yield object()

    import resume_agent.h1b.service as service

    original = service.h1b_tools
    service.h1b_tools = fake_tools
    try:
        asyncio.run(
            enrich_companies(
                engine,
                ["Acme, Inc."],
                settings=settings,
                agent_factory=Factory(FakeRunner()),
            )
        )
    finally:
        service.h1b_tools = original

    with Session(engine) as session:
        row = session.exec(
            model_select(H1BCompanyEvidence).where(
                H1BCompanyEvidence.normalized_company == "acme"
            )
        ).first()
    assert row is not None
    assert row.schema_version == 2


class UnparsedRunner(FakeRunner):
    """An agent whose provider truncated, refused, or 400'd.

    agno leaves ``RunOutput.content`` as the raw ``str`` it could not parse, so
    this is what every one of those failures looks like from the call site.
    """

    def __init__(self, body: str = "Error: max_tokens reached before completion"):
        super().__init__()
        self.body = body

    async def arun(self, prompt: str) -> SimpleNamespace:
        self.calls.append(prompt)
        return SimpleNamespace(
            content=self.body,
            model="claude-sonnet-5",
            status=SimpleNamespace(value="error"),
            metrics=SimpleNamespace(
                input_tokens=1200, output_tokens=4096, reasoning_tokens=0
            ),
        )


def test_unparsed_agent_output_is_diagnosed_not_swallowed(monkeypatch, caplog):
    """A systematic provider failure must be distinguishable from "no filings"."""
    import logging

    import resume_agent.h1b.service as service

    @asynccontextmanager
    async def fake_tools(_settings):
        yield object()

    monkeypatch.setattr(service, "h1b_tools", fake_tools)
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )

    with caplog.at_level(logging.ERROR, logger="resume_agent.h1b.service"):
        report = asyncio.run(
            enrich_companies(
                engine,
                ["Acme, Inc."],
                settings=settings,
                agent_factory=Factory(UnparsedRunner()),
            )
        )

    # Degrades, never raises: the row is still written and still displayable.
    assert report.by_company["acme"].status == "unavailable"

    records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert records, "unparsed provider output must not be logged at warning"
    message = records[0].getMessage()
    assert "claude-sonnet-5" in message
    assert "in=1200" in message and "out=4096" in message
    # The tail is what shows a response was cut off.
    assert "max_tokens reached" in message


def test_enrichment_reads_and_writes_the_cache_in_batches(monkeypatch):
    """2N queries for N companies is the display path's mistake, made twice."""
    import resume_agent.h1b.service as service
    from scripts.perf_harness import count_queries

    @asynccontextmanager
    async def fake_tools(_settings):
        yield object()

    monkeypatch.setattr(service, "h1b_tools", fake_tools)
    engine = make_engine("sqlite://")
    init_db(engine)
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        h1b_mcp_enabled=True,
        h1b_mcp_transport="stdio",
        h1b_mcp_command="server",
    )
    companies = [f"Company {index}" for index in range(12)]

    class _PerCompanyRunner(FakeRunner):
        async def arun(self, prompt: str) -> SimpleNamespace:
            self.calls.append(prompt)
            key = prompt.split("\n")[1].strip()
            return SimpleNamespace(content=_evidence(key))

    with count_queries(engine) as counts:
        report = asyncio.run(
            enrich_companies(
                engine,
                companies,
                settings=settings,
                agent_factory=Factory(_PerCompanyRunner()),
            )
        )

    assert len(report.by_company) == 12
    # One batched read before the fan-out, one batched read before the writes.
    assert counts.by_kind["SELECT"] == 2, str(counts)
