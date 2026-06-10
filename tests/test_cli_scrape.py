from typer.testing import CliRunner

from resume_agent import cli

runner = CliRunner()


def test_scrape_command_runs_ingest(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'jobs.db'}"

    monkeypatch.setattr(cli, "load_search_config", lambda path: object())
    monkeypatch.setattr(cli, "build_linkedin_scraper", lambda: object())
    monkeypatch.setattr(cli, "ingest_scraped", lambda session, scraper, config, limit=None: 5)

    result = runner.invoke(cli.app, ["scrape", "--db-url", db_url])

    assert result.exit_code == 0, result.output
    assert "5" in result.output
