import textwrap

import pytest

from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.services import sources as svc


def _write(tmp_path, body: str) -> str:
    path = tmp_path / "connectors.yaml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


BASE = """
greenhouse: {enabled: true, boards: [{token: anthropic, company: Anthropic}]}
lever: {enabled: true, boards: []}
companies: {enabled: true, urls: ["https://jobs.ashbyhq.com/openai"]}
adzuna: {enabled: true, country: us}
remoteok: {enabled: true}
linkedin: {enabled: false}
"""


def _preview_ok(monkeypatch):
    monkeypatch.setattr(
        svc,
        "preview_source",
        lambda url, label=None: svc.SourcePreview(ok=True, url=url, kind="greenhouse"),
    )


def test_add_greenhouse_url_writes_typed_board(tmp_path, monkeypatch):
    path = _write(tmp_path, BASE)
    _preview_ok(monkeypatch)
    monkeypatch.setattr(svc, "detect_ats", lambda url: AtsTarget("greenhouse", "cohere"))

    view = svc.add_source("https://job-boards.greenhouse.io/cohere", connectors_path=path)

    assert view.id == "greenhouse:cohere"
    reloaded = {source.id for source in svc.list_sources(path)}
    assert "greenhouse:cohere" in reloaded


def test_add_unknown_ats_falls_to_companies(tmp_path, monkeypatch):
    path = _write(tmp_path, BASE)
    _preview_ok(monkeypatch)
    monkeypatch.setattr(
        svc,
        "detect_ats",
        lambda url: AtsTarget("workday", tenant="gm", datacenter="wd5", site="Careers"),
    )

    view = svc.add_source(
        "https://gm.wd5.myworkdayjobs.com/Careers",
        label="GM",
        connectors_path=path,
    )

    assert view.detail == "https://gm.wd5.myworkdayjobs.com/Careers"
    assert view.display_name == "GM"


def test_add_undetectable_raises(tmp_path, monkeypatch):
    path = _write(tmp_path, BASE)
    monkeypatch.setattr(svc, "detect_ats", lambda url: None)

    with pytest.raises(svc.SourceError):
        svc.add_source("https://nope.example", connectors_path=path)


def test_set_enabled_and_remove(tmp_path):
    path = _write(tmp_path, BASE)

    svc.set_source_enabled("greenhouse:anthropic", False, connectors_path=path)
    assert (
        next(source for source in svc.list_sources(path) if source.id == "greenhouse:anthropic").enabled
        is False
    )
    svc.remove_source("greenhouse:anthropic", connectors_path=path)
    assert "greenhouse:anthropic" not in {source.id for source in svc.list_sources(path)}


def test_remove_unknown_raises(tmp_path):
    path = _write(tmp_path, BASE)

    with pytest.raises(svc.SourceError):
        svc.remove_source("greenhouse:ghost", connectors_path=path)
