from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from resume_agent.config import Settings
from resume_agent.db import init_db, make_engine
from resume_agent.h1b.models import HISTORICAL_ONLY_CAVEAT, H1BSponsorshipEvidence
from resume_agent.h1b.service import enrich_companies


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
    from contextlib import asynccontextmanager
    import asyncio
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
