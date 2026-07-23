from dataclasses import dataclass

from resume_agent.discovery.source_scout import ScoutCandidate, ScoutReport
from resume_agent.services import source_discovery as svc
from resume_agent.services.sources import SourcePreview


class FakeReporter:
    def begin(self, total, label, **extra):
        pass

    def step(self, current, *, label=None, **extra):
        pass

    def checkpoint(self):
        pass


@dataclass
class FakeResult:
    content: object


class FakeAgent:
    def __init__(self, content: object):
        self.content = content

    def run(self, prompt: str) -> FakeResult:
        return FakeResult(self.content)

    async def arun(self, prompt: str) -> FakeResult:
        return self.run(prompt)


def run_worker(monkeypatch, tmp_path, candidates, previews, *, browser_enabled=True):
    monkeypatch.setattr(svc, "preview_source", lambda url, **kwargs: previews[url])
    return svc.run_source_discovery(
        FakeReporter(),
        prompt="AI infrastructure startups",
        connectors_path=str(tmp_path / "connectors.yaml"),
        search_path=str(tmp_path / "search.yaml"),
        profile_dir=tmp_path,
        browser_enabled=browser_enabled,
        research_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(ScoutReport(candidates=candidates)),
    )


def test_worker_classifies_structured_validation_results(monkeypatch, tmp_path):
    previews = {
        "https://job-boards.greenhouse.io/acme": SourcePreview(
            ok=True,
            url="https://job-boards.greenhouse.io/acme",
            kind="greenhouse",
            token="acme",
            role_count=4,
        ),
        "https://plain.example/careers": SourcePreview(
            ok=False,
            url="https://plain.example/careers",
            error="No supported ATS",
            error_code="ATS_NOT_DETECTED",
        ),
        "https://broken.example/jobs": SourcePreview(
            ok=False,
            url="https://broken.example/jobs",
            error="Could not reach this source.",
            error_code="UNREACHABLE",
        ),
    }
    candidates = [
        ScoutCandidate(company="Acme", careers_url=url)
        for url in previews
    ]
    candidates[1].company = "Plain"
    candidates[2].company = "Broken"

    result = run_worker(monkeypatch, tmp_path, candidates, previews)

    assert [row["status"] for row in result["candidates"]] == [
        "validated",
        "unverified",
        "failed",
    ]
    assert result["candidates"][0]["roleCount"] == 4
    assert result["scrapeAvailable"] is True


def test_worker_dedupes_config_and_preserves_order_within_status(monkeypatch, tmp_path):
    (tmp_path / "connectors.yaml").write_text(
        "greenhouse: {enabled: true, boards: [{token: existing}]}\n",
        encoding="utf-8",
    )
    candidates = [
        ScoutCandidate(
            company="Existing",
            careers_url="https://job-boards.greenhouse.io/existing/",
        ),
        ScoutCandidate(company="Acme", careers_url="https://jobs.lever.co/acme/"),
        ScoutCandidate(company="Acme again", careers_url="https://jobs.lever.co/acme"),
    ]
    previews = {
        "https://jobs.lever.co/acme/": SourcePreview(
            ok=True, url="https://jobs.lever.co/acme", kind="lever", token="acme"
        )
    }

    result = run_worker(monkeypatch, tmp_path, candidates, previews)

    assert [row["company"] for row in result["candidates"]] == [
        "Acme",
        "Existing",
        "Acme again",
    ]
    assert [row["status"] for row in result["candidates"]] == [
        "validated",
        "duplicate",
        "duplicate",
    ]


def test_worker_exposes_browserless_scrape_capability(monkeypatch, tmp_path):
    candidates = [
        ScoutCandidate(company="Plain", careers_url="https://plain.example/careers")
    ]
    previews = {
        candidates[0].careers_url: SourcePreview(
            ok=False,
            url=candidates[0].careers_url,
            error="No ATS",
            error_code="ATS_NOT_DETECTED",
        )
    }

    result = run_worker(
        monkeypatch, tmp_path, candidates, previews, browser_enabled=False
    )

    assert result["scrapeAvailable"] is False
    assert "browser" in result["scrapeUnavailableReason"].lower()


def test_empty_report_is_success(monkeypatch, tmp_path):
    result = run_worker(monkeypatch, tmp_path, [], {})
    assert result["candidates"] == []
