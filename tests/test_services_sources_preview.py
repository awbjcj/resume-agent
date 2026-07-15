import pytest

from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.detect import AtsInspection, AtsTarget
from resume_agent.services import sources as svc


def test_preview_undetectable_is_not_ok(monkeypatch):
    monkeypatch.setattr(
        svc, "inspect_ats", lambda url: AtsInspection(target=None, reachable=True)
    )

    preview = svc.preview_source("https://nope.example")

    assert preview.ok is False
    assert preview.error_code == "ATS_NOT_DETECTED"
    assert preview.error


def test_preview_unreachable_has_structured_error(monkeypatch):
    monkeypatch.setattr(
        svc, "inspect_ats", lambda url: AtsInspection(target=None, reachable=False)
    )

    preview = svc.preview_source("https://offline.example")

    assert preview.ok is False
    assert preview.error_code == "UNREACHABLE"


def test_preview_counts_roles_from_test_fetch(monkeypatch):
    monkeypatch.setattr(
        svc,
        "inspect_ats",
        lambda url: AtsInspection(AtsTarget("greenhouse", "cohere"), True),
    )

    class FakeConnector:
        name = "greenhouse:cohere"

        def fetch(self, search, limit=None):
            return FetchResult(
                jobs=[
                    RawJob(
                        "greenhouse",
                        "u",
                        "Cohere",
                        "AI Eng",
                        "Remote",
                        "jd",
                    )
                ]
            )

    monkeypatch.setattr(
        svc,
        "_preview_connector",
        lambda target, url, *, browser=True: FakeConnector(),
    )
    monkeypatch.setattr(svc, "load_search_config", lambda path: object())

    preview = svc.preview_source(
        "https://job-boards.greenhouse.io/cohere", label="Cohere"
    )

    assert preview.ok is True
    assert preview.kind == "greenhouse"
    assert preview.token == "cohere"
    assert preview.role_count == 1


def test_preview_forwards_limit_and_browser(monkeypatch):
    seen = {}

    class FakeConnector:
        def fetch(self, search, limit=None):
            seen["limit"] = limit
            return FetchResult(jobs=[])

    monkeypatch.setattr(
        svc,
        "inspect_ats",
        lambda url: AtsInspection(AtsTarget("greenhouse", "acme"), True),
    )
    monkeypatch.setattr(
        svc,
        "_preview_connector",
        lambda target, url, *, browser=True: seen.update(browser=browser)
        or FakeConnector(),
    )
    monkeypatch.setattr(svc, "load_search_config", lambda path: object())

    preview = svc.preview_source(
        "https://job-boards.greenhouse.io/acme", limit=5, browser=False
    )

    assert preview.ok is True
    assert seen == {"browser": False, "limit": 5}


@pytest.mark.parametrize(
    ("provider", "kwargs", "expected"),
    [
        ("greenhouse", {"token": "acme"}, "https://job-boards.greenhouse.io/acme"),
        ("personio", {"token": "acme", "country": "de"}, "https://acme.jobs.personio.de"),
        (
            "workday",
            {"tenant": "acme", "datacenter": "wd5", "site": "Careers"},
            "https://acme.wd5.myworkdayjobs.com/Careers",
        ),
    ],
)
def test_provider_recipe_builds_canonical_board_url(provider, kwargs, expected):
    assert svc._connection_url(provider=provider, **kwargs) == expected


def test_preview_native_provider_uses_real_connector_fetch(monkeypatch):
    seen = {}

    class FakeConnector:
        def fetch(self, search, limit=None):
            seen["limit"] = limit
            return FetchResult(jobs=[])

    def fake_connector(target, url, *, browser=True):
        seen["target"] = target
        seen["url"] = url
        return FakeConnector()

    monkeypatch.setattr(svc, "_preview_connector", fake_connector)
    monkeypatch.setattr(
        svc,
        "inspect_ats",
        lambda url: AtsInspection(AtsTarget("ashby", "acme"), True),
    )
    monkeypatch.setattr(svc, "load_search_config", lambda path: object())

    preview = svc.preview_source(provider="ashby", token="acme")

    assert preview.ok is True
    assert seen["target"] == AtsTarget("ashby", "acme")
    assert seen["url"] == "https://jobs.ashbyhq.com/acme"
    assert seen["limit"] == 50


def test_preview_rejects_unsafe_provider_token_before_fetch(monkeypatch):
    monkeypatch.setattr(
        svc,
        "inspect_ats",
        lambda _url: pytest.fail("invalid recipes must not reach detection"),
    )

    preview = svc.preview_source(provider="greenhouse", token="../internal")

    assert preview.ok is False
    assert "letters, numbers, and hyphens" in (preview.error or "")


def test_path_provider_allows_underscore_in_company_token():
    assert svc._connection_url(provider="greenhouse", token="acme_jobs") == (
        "https://job-boards.greenhouse.io/acme_jobs"
    )


def test_add_source_requires_successful_preview(tmp_path, monkeypatch):
    path = tmp_path / "connectors.yaml"
    path.write_text(
        "greenhouse: {enabled: true, boards: []}\ncompanies: {enabled: true, urls: []}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        svc,
        "preview_source",
        lambda url, label=None, **kwargs: svc.SourcePreview(
            ok=False, url=url, error="preview failed"
        ),
    )

    with pytest.raises(svc.SourceError, match="preview failed"):
        svc.add_source("https://nope.example", connectors_path=str(path))
