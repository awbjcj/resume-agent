from pathlib import Path

import typer

from resume_agent.config import load_yaml, get_settings
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.extract import build_extract_agent
from resume_agent.discovery.fit import build_fit_agent
from resume_agent.discovery.pipeline import discover
from resume_agent.discovery.search_config import load_search_config
from resume_agent.profile.build import build_profile
from resume_agent.profile.store import load_facts, save_facts

app = typer.Typer(help="Resume Agent — personal job-hunt automation pipeline.")
profile_app = typer.Typer(help="Build and manage your fact-lock profile.")
app.add_typer(profile_app, name="profile")

DEFAULT_SOURCES = "config/profile_sources.yaml"
DEFAULT_FACTS = "data/profile/facts.json"


@profile_app.command("build")
def profile_build(
    sources: str = typer.Option(DEFAULT_SOURCES, help="Path to profile_sources.yaml."),
    out: str = typer.Option(DEFAULT_FACTS, help="Where to write facts.json."),
    refresh: bool = typer.Option(
        False, "--refresh", help="Overwrite an existing facts.json (discards manual edits)."
    ),
) -> None:
    """Build facts.json from your resume + GitHub."""
    if Path(out).exists() and not refresh:
        typer.echo(f"{out} already exists. Use --refresh to rebuild (this discards manual edits).")
        raise typer.Exit(code=1)

    cfg = load_yaml(sources)
    facts = build_profile(
        resume_path=cfg.get("resume_path"),
        github_username=cfg.get("github_username"),
    )
    path = save_facts(facts, out)
    typer.echo(
        f"Wrote {len(facts.experience)} experiences and {len(facts.projects)} projects to {path}"
    )


DEFAULT_SEARCH = "config/search.yaml"


def _engine(db_url: str | None):
    engine = make_engine(db_url or get_settings().db_url)
    init_db(engine)
    return engine


@app.command("addjob")
def addjob(
    url: str = typer.Option(None, help="Posting URL (used for dedupe)."),
    company: str = typer.Option(None, help="Company name."),
    title: str = typer.Option(None, help="Job title."),
    location: str = typer.Option(None, help="Location."),
    jd_file: str = typer.Option(None, help="Read the JD from this file instead of stdin."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Manually add a job (paste the JD on stdin, or pass --jd-file)."""
    jd_text = Path(jd_file).read_text(encoding="utf-8") if jd_file else typer.get_text_stream("stdin").read()
    engine = _engine(db_url)
    with get_session(engine) as session:
        job = add_job(
            session, source="manual", jd_text=jd_text, url=url, company=company, title=title, location=location
        )
    if job is None:
        typer.echo("Duplicate job (same URL or JD already present); not added.")
        raise typer.Exit(code=0)
    typer.echo(f"Added job #{job.id} (status={job.status}).")


@app.command("discover")
def discover_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the discovery funnel over current jobs and report status counts."""
    config = load_search_config(search)
    profile_facts = load_facts(facts)
    extract_agent = build_extract_agent()
    fit_agent = build_fit_agent()
    engine = _engine(db_url)
    with get_session(engine) as session:
        counts = discover(session, config, profile_facts, extract_agent, fit_agent)
    typer.echo(f"Discovery complete. Status counts: {counts}")


if __name__ == "__main__":
    app()
