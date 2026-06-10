import os
import subprocess
from pathlib import Path
from typing import cast

import typer

from resume_agent.config import load_yaml, get_settings
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.ingest import add_job
from resume_agent.discovery.extract import build_extract_agent
from resume_agent.discovery.fit import build_fit_agent
from resume_agent.discovery.pipeline import discover
from resume_agent.discovery.scraper.ingest import ingest_scraped
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
from resume_agent.discovery.search_config import load_search_config
from resume_agent.profile.build import build_profile
from resume_agent.profile.store import load_facts, save_facts
from resume_agent.tailor.agents import build_reviewer_agent, build_reviser_agent, build_tailor_agent, model_for_tier
from resume_agent.tailor.review_config import load_review_config
from resume_agent.tailor.service import tailor_job
from resume_agent.render.render_config import RenderConfig, load_render_config
from resume_agent.render.service import render_version
from resume_agent.tracking.repository import get_job, jobs_by_status, save_job
from resume_agent.tracking.tables import JobStatus

app = typer.Typer(help="Resume Agent — personal job-hunt automation pipeline.")
profile_app = typer.Typer(help="Build and manage your fact-lock profile.")
app.add_typer(profile_app, name="profile")

DEFAULT_SOURCES = "config/profile_sources.yaml"
DEFAULT_FACTS = "data/profile/facts.json"


def _require_str(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise typer.BadParameter(f"{name} must be configured as a non-empty string.")
    return value


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
        resume_path=_require_str(cfg.get("resume_path"), "resume_path"),
        github_username=cast(str | None, cfg.get("github_username")),
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


@app.command("scrape")
def scrape_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    limit: int | None = typer.Option(None, help="Cap the number of postings fetched this run."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Scrape LinkedIn for jobs matching search.yaml and insert them as raw jobs."""
    config = load_search_config(search)
    scraper = build_linkedin_scraper()
    engine = _engine(db_url)
    with get_session(engine) as session:
        added = ingest_scraped(session, scraper, config, limit=limit)
    typer.echo(f"Scrape complete. Added {added} new job(s).")


DEFAULT_REVIEW = "config/review.yaml"


def build_reviewer_agents(config) -> dict:
    """Build one Agno reviewer agent per configured reviewer, at its model tier."""
    return {
        spec.name: build_reviewer_agent(spec.name, model_for_tier(spec.model_tier))
        for spec in config.reviewers
    }


@app.command("approve")
def approve(
    job_id: int = typer.Argument(..., help="Job id to approve for tailoring."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Mark a shortlisted job as approved (the human checkpoint before tailoring)."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        job = get_job(session, job_id)
        if job is None:
            typer.echo(f"Job #{job_id} not found.")
            raise typer.Exit(code=1)
        job.status = JobStatus.approved.value
        save_job(session, job)
    typer.echo(f"Approved job #{job_id}.")


@app.command("tailor")
def tailor_cmd(
    job_id: int = typer.Option(None, help="Tailor a single job by id."),
    approved: bool = typer.Option(False, "--approved", help="Tailor all approved jobs."),
    review: str = typer.Option(DEFAULT_REVIEW, help="Path to review.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the tailor + review loop over approved job(s)."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        if job_id is not None:
            job = get_job(session, job_id)
            if job is None:
                typer.echo(f"Job #{job_id} not found.")
                raise typer.Exit(code=1)
            targets = [job]
        elif approved:
            targets = jobs_by_status(session, JobStatus.approved.value)
        else:
            typer.echo("Specify --job-id <id> or --approved.")
            raise typer.Exit(code=1)

        config = load_review_config(review)
        profile_facts = load_facts(facts)
        tailor_agent = build_tailor_agent()
        reviser_agent = build_reviser_agent()
        reviewer_agents = build_reviewer_agents(config)

        for job in targets:
            versions = tailor_job(
                session, job, profile_facts, config, tailor_agent, reviewer_agents, reviser_agent
            )
            typer.echo(
                f"Job #{job.id}: {len(versions)} version(s); final fact_check_passed={versions[-1].fact_check_passed}"
            )


DEFAULT_RENDER = "config/render.yaml"


@app.command("render")
def render_cmd(
    version_id: int = typer.Argument(..., help="resume_versions.id to render to PDF."),
    config: str = typer.Option(DEFAULT_RENDER, help="Path to render.yaml."),
    db_url: str = typer.Option(None, help="Override the database URL."),
) -> None:
    """Render a stored resume version to a PDF."""
    render_config = load_render_config(config) if Path(config).exists() else RenderConfig()
    engine = _engine(db_url)
    with get_session(engine) as session:
        path = render_version(session, version_id, render_config)
    if path is None:
        typer.echo(f"Resume version #{version_id} not found.")
        raise typer.Exit(code=1)
    typer.echo(f"Rendered version #{version_id} -> {path}")


@app.command("dashboard")
def dashboard_cmd(
    db_url: str = typer.Option(None, help="Override the database URL for the dashboard."),
) -> None:
    """Launch the Streamlit dashboard (shortlist checkpoint + pipeline board)."""
    app_path = str(Path(__file__).parent / "dashboard" / "app.py")
    env = dict(os.environ)
    if db_url:
        env["DB_URL"] = db_url
    subprocess.run(["streamlit", "run", app_path], env=env)


if __name__ == "__main__":
    app()
