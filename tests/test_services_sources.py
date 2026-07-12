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
    monkeypatch.setattr(
        svc, "detect_ats", lambda url: AtsTarget("greenhouse", "cohere")
    )

    view = svc.add_source(
        "https://job-boards.greenhouse.io/cohere", connectors_path=path
    )

    assert view.id == "greenhouse:cohere"
    reloaded = {source.id for source in svc.list_sources(path)}
    assert "greenhouse:cohere" in reloaded


def test_add_ashby_url_writes_typed_board(tmp_path, monkeypatch):
    path = _write(tmp_path, BASE)
    _preview_ok(monkeypatch)
    monkeypatch.setattr(svc, "detect_ats", lambda url: AtsTarget("ashby", "openai"))

    view = svc.add_source(
        "https://jobs.ashbyhq.com/openai", label="OpenAI", connectors_path=path
    )

    config = svc.load_connectors_config(path)
    assert view.id == "ashby:openai"
    assert config.ashby.enabled is True
    assert config.ashby.boards[0].token == "openai"
    assert config.ashby.boards[0].company == "OpenAI"
    assert config.companies.urls == [
        svc.CompanyUrl(url="https://jobs.ashbyhq.com/openai")
    ]


def test_add_url_based_native_ats_writes_its_own_section(tmp_path, monkeypatch):
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

    config = svc.load_connectors_config(path)
    assert view.id == svc.native_url_id(
        "workday", "https://gm.wd5.myworkdayjobs.com/Careers"
    )
    assert view.display_name == "GM"
    assert config.workday.enabled is True
    assert config.workday.boards[0].url == "https://gm.wd5.myworkdayjobs.com/Careers"
    assert config.workday.boards[0].company == "GM"


@pytest.mark.parametrize("kind", svc.NATIVE_URL_KINDS)
def test_add_routes_every_url_based_backend_to_native_section(
    kind, tmp_path, monkeypatch
):
    path = _write(tmp_path, BASE)
    _preview_ok(monkeypatch)
    monkeypatch.setattr(svc, "detect_ats", lambda url: AtsTarget(kind, token="acme"))
    url = f"https://jobs.example/{kind}"

    view = svc.add_source(url, label="Acme", connectors_path=path)

    config = svc.load_connectors_config(path)
    section = getattr(config, kind)
    assert view.id == svc.native_url_id(kind, url)
    assert section.enabled is True
    assert section.boards[0].url == url
    assert section.boards[0].company == "Acme"
    assert all(entry.url != url for entry in config.companies.urls)


def test_add_undetectable_raises(tmp_path, monkeypatch):
    path = _write(tmp_path, BASE)
    monkeypatch.setattr(svc, "detect_ats", lambda url: None)

    with pytest.raises(svc.SourceError):
        svc.add_source("https://nope.example", connectors_path=path)


def test_set_enabled_and_remove(tmp_path):
    path = _write(tmp_path, BASE)

    svc.set_source_enabled("greenhouse:anthropic", False, connectors_path=path)
    assert (
        next(
            source
            for source in svc.list_sources(path)
            if source.id == "greenhouse:anthropic"
        ).enabled
        is False
    )
    svc.remove_source("greenhouse:anthropic", connectors_path=path)
    assert "greenhouse:anthropic" not in {
        source.id for source in svc.list_sources(path)
    }


def test_enabling_child_source_enables_parent_group(tmp_path):
    path = _write(
        tmp_path,
        """
        greenhouse: {enabled: false, boards: [{token: anthropic, enabled: false}]}
        lever: {enabled: false, boards: [{token: zoox, enabled: false}]}
        companies: {enabled: false, urls: [{url: "https://jobs.ashbyhq.com/openai", enabled: false}]}
        adzuna: {enabled: false, country: us}
        remoteok: {enabled: false}
        linkedin: {enabled: false}
        """,
    )

    greenhouse = svc.set_source_enabled(
        "greenhouse:anthropic", True, connectors_path=path
    )
    lever = svc.set_source_enabled("lever:zoox", True, connectors_path=path)
    company_id = svc.company_url_id("https://jobs.ashbyhq.com/openai")
    company = svc.set_source_enabled(company_id, True, connectors_path=path)

    assert greenhouse.enabled is True
    assert greenhouse.pullable is True
    assert lever.enabled is True
    assert lever.pullable is True
    assert company.enabled is True
    assert company.pullable is True


def test_remove_unknown_raises(tmp_path):
    path = _write(tmp_path, BASE)

    with pytest.raises(svc.SourceError):
        svc.remove_source("greenhouse:ghost", connectors_path=path)


def test_set_source_limit_roundtrips_and_clears(tmp_path):
    path = _write(
        tmp_path,
        """
        greenhouse:
          enabled: true
          boards:
            - token: acme
        """,
    )
    view = svc.set_source_limit("greenhouse:acme", 10, connectors_path=path)
    assert view.limit == 10
    assert svc.load_connectors_config(path).greenhouse.boards[0].limit == 10

    view = svc.set_source_limit("greenhouse:acme", None, connectors_path=path)
    assert view.limit is None
    assert svc.load_connectors_config(path).greenhouse.boards[0].limit is None


def test_set_source_limit_supports_singletons_and_scrape_targets(tmp_path):
    path = _write(
        tmp_path,
        """
        remoteok: {enabled: true}
        scrape:
          enabled: true
          targets:
            - url: https://jobs.example/careers
        """,
    )
    assert svc.set_source_limit("remoteok", 25, connectors_path=path).limit == 25
    scrape_id = svc.scrape_target_id("https://jobs.example/careers")
    assert svc.set_source_limit(scrape_id, 7, connectors_path=path).limit == 7


def test_set_source_limit_rejects_non_positive_values_without_writing(tmp_path):
    path = _write(tmp_path, "remoteok: {enabled: true}\n")
    before = (tmp_path / "connectors.yaml").read_text(encoding="utf-8")
    with pytest.raises(svc.SourceError, match="positive"):
        svc.set_source_limit("remoteok", 0, connectors_path=path)
    assert (tmp_path / "connectors.yaml").read_text(encoding="utf-8") == before


def test_patch_source_applies_enabled_and_limit_with_one_save(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        """
        greenhouse:
          enabled: true
          boards:
            - token: acme
        """,
    )
    writes = 0
    original_save = svc._save

    def counting_save(*args, **kwargs):
        nonlocal writes
        writes += 1
        return original_save(*args, **kwargs)

    monkeypatch.setattr(svc, "_save", counting_save)
    view = svc.patch_source(
        "greenhouse:acme", enabled=False, limit=8, connectors_path=path
    )
    assert writes == 1
    assert view.enabled is False
    assert view.limit == 8


def test_scrape_source_can_be_disabled_and_removed(tmp_path):
    path = _write(
        tmp_path,
        """
        scrape:
          enabled: true
          targets:
            - url: https://jobs.example/careers
        """,
    )
    source_id = svc.scrape_target_id("https://jobs.example/careers")
    assert (
        svc.set_source_enabled(source_id, False, connectors_path=path).enabled is False
    )
    svc.remove_source(source_id, connectors_path=path)
    assert source_id not in {source.id for source in svc.list_sources(path)}
