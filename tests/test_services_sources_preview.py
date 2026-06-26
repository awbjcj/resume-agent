import pytest

from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.services import sources as svc


def test_preview_undetectable_is_not_ok(monkeypatch):
    monkeypatch.setattr(svc, "detect_ats", lambda url: None)

    preview = svc.preview_source("https://nope.example")

    assert preview.ok is False
    assert preview.error


def test_preview_counts_roles_from_test_fetch(monkeypatch):
    monkeypatch.setattr(svc, "detect_ats", lambda url: AtsTarget("greenhouse", "cohere"))

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

    monkeypatch.setattr(svc, "_preview_connector", lambda target, url: FakeConnector())

    preview = svc.preview_source("https://job-boards.greenhouse.io/cohere", label="Cohere")

    assert preview.ok is True
    assert preview.kind == "greenhouse"
    assert preview.token == "cohere"
    assert preview.role_count == 1


def test_add_source_requires_successful_preview(tmp_path, monkeypatch):
    path = tmp_path / "connectors.yaml"
    path.write_text(
        "greenhouse: {enabled: true, boards: []}\ncompanies: {enabled: true, urls: []}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        svc,
        "preview_source",
        lambda url, label=None: svc.SourcePreview(ok=False, url=url, error="preview failed"),
    )

    with pytest.raises(svc.SourceError, match="preview failed"):
        svc.add_source("https://nope.example", connectors_path=str(path))
