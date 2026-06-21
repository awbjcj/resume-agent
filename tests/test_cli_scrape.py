from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.discovery.connectors.base import FetchResult, RawJob

runner = CliRunner()


class _FakeConnector:
    name = "linkedin"

    def fetch(self, search, limit=None):
        return FetchResult(
            jobs=[RawJob("linkedin", "https://li/1", "Acme", "Engineer", "Remote", "a real jd")]
        )


class _FakeConnectorWithFailure:
    name = "linkedin"

    def fetch(self, search, limit=None):
        return FetchResult(jobs=[], failures={"https://li/dead": "Error"})


def test_scrape_command_ingests_via_connector(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "build_linkedin_scraper", lambda: _FakeConnector())

    result = runner.invoke(cli.app, ["scrape", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "Added 1" in result.output


def test_scrape_command_reports_failed_postings(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "build_linkedin_scraper", lambda: _FakeConnectorWithFailure())

    result = runner.invoke(cli.app, ["scrape", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "Skipped 1 failed posting(s): https://li/dead (Error)" in result.output
    assert "Added 0" in result.output
