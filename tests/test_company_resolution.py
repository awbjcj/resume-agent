from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import CompanyUrl, GreenhouseBoard
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.workday import apply_detail, parse_list_rows
from resume_agent.discovery.search_config import SearchConfig


def _payload():
    return {
        "jobs": [
            {
                "title": "Engineer",
                "absolute_url": "https://x.test/1",
                "content": "Build systems",
            }
        ]
    }


def test_greenhouse_resolves_board_name_and_preserves_token(monkeypatch):
    connector = GreenhouseConnector([GreenhouseBoard(token="acmecorp")])
    monkeypatch.setattr(connector, "_get_board", lambda _token: _payload())
    monkeypatch.setattr(connector, "_get_board_name", lambda _token: "Acme Corp")

    result = connector.fetch(SearchConfig())

    assert result.jobs[0].company == "Acme Corp"
    assert result.jobs[0].stale_company == "acmecorp"


def test_configured_greenhouse_company_wins(monkeypatch):
    connector = GreenhouseConnector(
        [GreenhouseBoard(token="acmecorp", company="ACME Inc")]
    )
    monkeypatch.setattr(connector, "_get_board", lambda _token: _payload())
    monkeypatch.setattr(
        connector,
        "_get_board_name",
        lambda _token: (_ for _ in ()).throw(AssertionError("should not resolve")),
    )

    result = connector.fetch(SearchConfig())

    assert result.jobs[0].company == "ACME Inc"
    assert result.jobs[0].stale_company == "acmecorp"


def test_workday_detail_preserves_tenant_as_stale_company():
    target = AtsTarget("workday", tenant="acme", datacenter="wd5", site="Careers")
    row = parse_list_rows(
        target,
        {"jobPostings": [{"title": "Engineer", "externalPath": "/job/1"}]},
    )[0]

    apply_detail(
        row,
        {
            "jobPostingInfo": {
                "jobDescription": "Build systems",
                "companyName": "Acme Corp",
            }
        },
    )

    assert row.company == "Acme Corp"
    assert row.stale_company == "acme"


def test_company_label_preserves_deepest_fallback(monkeypatch):
    import resume_agent.discovery.connectors.companies as companies

    monkeypatch.setattr(
        companies,
        "detect_ats",
        lambda _url: AtsTarget("ashby", token="acmecorp"),
    )
    monkeypatch.setitem(
        companies._BACKENDS,
        "ashby",
        lambda *_args, **_kwargs: [
            RawJob(
                source="ashby",
                url="https://x.test/1",
                company="Acme Careers",
                title="Engineer",
                location="Remote",
                jd_text="Build systems",
                stale_company="acmecorp",
            )
        ],
    )
    connector = CompaniesConnector(
        [CompanyUrl(url="https://jobs.ashbyhq.com/acmecorp", label="Acme Corp")]
    )

    result = connector.fetch(SearchConfig())

    assert result.jobs[0].company == "Acme Corp"
    assert result.jobs[0].stale_company == "acmecorp"
