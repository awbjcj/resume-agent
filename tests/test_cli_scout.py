from typer.testing import CliRunner

from resume_agent import cli


def test_scout_command_prints_and_adds_only_validated(monkeypatch):
    added = []
    monkeypatch.setattr(cli, "resolve_api_key", lambda model_id: "key")
    monkeypatch.setattr(
        "resume_agent.services.source_discovery.run_source_discovery",
        lambda reporter, **kwargs: {
            "prompt": kwargs["prompt"],
            "scrapeAvailable": True,
            "scrapeUnavailableReason": None,
            "candidates": [
                {
                    "company": "Acme",
                    "url": "https://job-boards.greenhouse.io/acme",
                    "reason": "matches",
                    "confidence": "high",
                    "status": "validated",
                    "ats": "greenhouse",
                    "token": "acme",
                    "roleCount": 4,
                    "error": None,
                    "errorCode": None,
                },
                {
                    "company": "Plain",
                    "url": "https://plain.example/careers",
                    "reason": "plain",
                    "confidence": "low",
                    "status": "unverified",
                    "ats": None,
                    "token": None,
                    "roleCount": None,
                    "error": None,
                    "errorCode": "ATS_NOT_DETECTED",
                },
            ],
        },
    )
    monkeypatch.setattr(
        "resume_agent.services.sources.add_source",
        lambda **kwargs: added.append(kwargs["url"]),
    )

    result = CliRunner().invoke(cli.app, ["scout", "AI infrastructure", "--add"])

    assert result.exit_code == 0, result.output
    assert "Acme" in result.output and "validated" in result.output
    assert added == ["https://job-boards.greenhouse.io/acme"]


def test_scout_command_preflights_all_models(monkeypatch):
    seen = []

    def key(model_id):
        seen.append(model_id)
        return "key" if len(seen) == 1 else ""

    monkeypatch.setattr(cli, "resolve_api_key", key)
    result = CliRunner().invoke(cli.app, ["scout", "AI infrastructure"])

    assert result.exit_code == 1
    assert "Missing API key" in result.output
    assert len(set(seen)) == 2


def test_scout_search_cmd_prints_suggestions(monkeypatch):
    from resume_agent import cli

    monkeypatch.setattr(cli, "resolve_api_key", lambda model_id: "key")
    monkeypatch.setattr(
        "resume_agent.services.search_discovery.run_search_discovery",
        lambda *a, **k: {
            "prompt": "x",
            "suggestions": [
                {"value": "Rust", "kind": "keyword", "reason": "fits", "status": "new"}
            ],
        },
    )
    result = CliRunner().invoke(cli.app, ["scout-search", "platform roles"])
    assert result.exit_code == 0
    assert "Rust" in result.stdout
