import os
import subprocess
from pathlib import Path
from typing import cast

import httpx
import typer
from playwright.sync_api import Error as PlaywrightError

from resume_agent.config import load_yaml, get_settings
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.connectors.config import load_connectors_config
from resume_agent.discovery.connectors.registry import build_connectors
from resume_agent.discovery.connectors.runner import run_pull
from resume_agent.discovery.connectors.telemetry import read_runs
from resume_agent.discovery.ingest import add_job, ingest_jobs
from resume_agent.discovery.url_ingest.llm import build_url_extract_agent
from resume_agent.discovery.url_ingest.service import job_from_url
from resume_agent.discovery.extract import build_extract_agent
from resume_agent.discovery.fit import build_fit_agent
from resume_agent.discovery.pipeline import discover
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
from resume_agent.discovery.search_config import load_search_config
from resume_agent.cover_letter.agents import build_cover_letter_agent, build_cover_letter_reviser_agent
from resume_agent.cover_letter.render import render_cover_letter
from resume_agent.cover_letter.service import generate_cover_letter
from resume_agent.gmail.classify import classify_email
from resume_agent.gmail.client import build_gmail_service, fetch_recent_messages
from resume_agent.gmail.propose import propose_transitions
from resume_agent.profile.build import build_profile
from resume_agent.profile.store import load_facts, save_facts
from resume_agent.profile.validate import validate_profile
from resume_agent.tailor.agents import build_reviewer_agent, build_reviser_agent, build_tailor_agent, model_for_tier
from resume_agent.tailor.review_config import load_review_config
from resume_agent.tailor.service import tailor_job
from resume_agent.tailor.style_guide import load_style_guide
from resume_agent.render.render_config import RenderConfig, load_render_config
from resume_agent.render.service import render_version
from resume_agent.tracking.queries import application_job_pairs
from resume_agent.tracking.repository import get_job, jobs_by_status, save_job, update_application_status
from resume_agent.tracking.canonicalize import build_skill_canonicalizer
from resume_agent.tracking.match_gap import match_gap
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
    facts, raw_text = build_profile(
        resume_path=_require_str(cfg.get("resume_path"), "resume_path"),
        github_username=cast(str | None, cfg.get("github_username")),
    )
    report = validate_profile(facts, raw_text)
    path = save_facts(facts, out)
    typer.echo(
        f"Wrote {len(facts.experience)} experiences and {len(facts.projects)} projects to {path}"
    )
    for warning in report.warnings:
        typer.echo(f"  WARNING: {warning}")


DEFAULT_SEARCH = "config/search.yaml"
DEFAULT_CONNECTORS = "config/connectors.yaml"
CONNECTOR_RUNS_PATH = "data/connector_runs.json"


def _engine(db_url: str | None):
    engine = make_engine(db_url or get_settings().db_url)
    init_db(engine)
    return engine


@app.command("addjob")
def addjob(
    url: str | None = typer.Option(None, help="Posting URL. With no JD source, the page is fetched and fields are auto-extracted."),
    company: str | None = typer.Option(None, help="Company name (overrides extracted)."),
    title: str | None = typer.Option(None, help="Job title (overrides extracted)."),
    location: str | None = typer.Option(None, help="Location (overrides extracted)."),
    jd_file: str | None = typer.Option(None, help="Read the JD from this file instead of stdin/URL."),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Force HTTP-only fetching (skip the Playwright fallback)."
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Add a job from a URL (auto-extract), a --jd-file, or JD pasted on stdin.

    Precedence: --url (with no --jd-file) fetches the page and auto-extracts.
    Otherwise --jd-file or stdin supplies the JD. Note: when --url is given
    without --jd-file, any piped stdin is ignored.
    """
    if url and not jd_file:
        try:
            raw = job_from_url(
                url, agent=build_url_extract_agent(), allow_browser=not no_browser
            )
        except (httpx.HTTPError, PlaywrightError) as exc:
            typer.echo(f"Couldn't fetch {url}: {exc}")
            raise typer.Exit(code=1) from exc
        if raw is None:
            typer.echo("Couldn't extract a job description from that URL.")
            raise typer.Exit(code=1)
        jd_text = raw.jd_text
        company = company or raw.company
        title = title or raw.title
        location = location or raw.location
        source = "url"
        typer.echo(f"Extracted: {title or '?'} @ {company or '?'} ({location or '?'})")
    else:
        jd_text = (
            Path(jd_file).read_text(encoding="utf-8")
            if jd_file
            else typer.get_text_stream("stdin").read()
        )
        source = "manual"
    engine = _engine(db_url)
    with get_session(engine) as session:
        job = add_job(
            session, source=source, jd_text=jd_text, url=url,
            company=company, title=title, location=location,
        )
    if job is None:
        typer.echo("Duplicate job (same URL or JD already present); not added.")
        raise typer.Exit(code=0)
    typer.echo(f"Added job #{job.id} ({company or '?'} — status={job.status}).")


@app.command("discover")
def discover_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
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
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Scrape LinkedIn for jobs matching search.yaml and insert them as raw jobs."""
    config = load_search_config(search)
    connector = build_linkedin_scraper()
    engine = _engine(db_url)
    with get_session(engine) as session:
        added = ingest_jobs(session, connector.fetch(config, limit=limit))
    typer.echo(f"Scrape complete. Added {sum(added.values())} new job(s).")


@app.command("pull")
def pull_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    connectors_path: str = typer.Option(
        DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."
    ),
    limit: int | None = typer.Option(None, help="Cap postings per connector this run."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run every enabled connector, dedupe into raw jobs, and report per-source counts."""
    if not Path(connectors_path).exists():
        typer.echo(
            f"No connectors config found at {connectors_path}. "
            "Copy config/connectors.yaml.example to config/connectors.yaml and edit it."
        )
        raise typer.Exit(code=1)
    search_config = load_search_config(search)
    connectors_config = load_connectors_config(connectors_path)
    connectors = build_connectors(connectors_config, get_settings())
    if not connectors:
        typer.echo("No connectors enabled. Edit connectors.yaml (and .env) to enable some.")
        raise typer.Exit(code=0)
    engine = _engine(db_url)
    with get_session(engine) as session:
        totals = run_pull(session, connectors, search_config, CONNECTOR_RUNS_PATH, limit=limit)
    for name in (c.name for c in connectors):
        typer.echo(f"  {name:<12} +{totals.get(name, 0)}")
    typer.echo(f"Pull complete. Added {sum(totals.values())} new job(s).")


@app.command("sources")
def sources_cmd() -> None:
    """Show each connector's last run: when, jobs added, and last error."""
    runs = read_runs(CONNECTOR_RUNS_PATH)
    if not runs:
        typer.echo("No connector runs recorded yet. Run `resume-agent pull` first.")
        raise typer.Exit(code=0)
    for name, info in sorted(runs.items()):
        status = info.get("error") or f"+{info.get('added', 0)} added"
        typer.echo(f"  {name:<12} {info.get('last_run', '-'):<22} {status}")


@app.command("match-gap")
def match_gap_cmd(
    job_id: int | None = typer.Option(None, help="Show gaps for one job instead of the aggregate."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    llm: bool = typer.Option(
        False, "--llm", help="Add a cheap-LLM synonym pass, such as k8s matching Kubernetes."
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Report skills your target jobs demand that your profile does not show."""
    profile_facts = load_facts(facts)
    canonicalizer = build_skill_canonicalizer() if llm else None
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = match_gap(session, profile_facts, canonicalizer=canonicalizer)

    if report.target_total == 0:
        typer.echo("No jobs past discovery yet. Run `discover` and shortlist/approve some first.")
        raise typer.Exit(code=0)

    if job_id is not None:
        missing = report.per_job.get(job_id)
        if missing is None:
            typer.echo(f"Job #{job_id} is not among your {report.target_total} target jobs.")
            raise typer.Exit(code=1)
        if not missing:
            typer.echo(f"Job #{job_id}: no skill gaps.")
            raise typer.Exit(code=0)
        typer.echo(f"Job #{job_id} missing skills:")
        for skill in missing:
            typer.echo(f"  {skill}")
        raise typer.Exit(code=0)

    if not report.gaps:
        typer.echo(f"No gaps across your {report.target_total} target jobs.")
        raise typer.Exit(code=0)
    typer.echo(f"Skill gaps across {report.target_total} target jobs:")
    for gap in report.gaps:
        typer.echo(f"  {gap.skill:<28} demanded by {gap.demand_count}/{gap.target_total}")


DEFAULT_REVIEW = "config/review.yaml"


def build_reviewer_agents(config, style_guide: str | None = None) -> dict:
    """Build one Agno reviewer agent per configured reviewer, at its model tier."""
    return {
        spec.name: build_reviewer_agent(
            spec.name, model_for_tier(spec.model_tier), style_guide=style_guide
        )
        for spec in config.reviewers
    }


@app.command("approve")
def approve(
    job_id: int = typer.Argument(..., help="Job id to approve for tailoring."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
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
    job_id: int | None = typer.Option(None, help="Tailor a single job by id."),
    approved: bool = typer.Option(False, "--approved", help="Tailor all approved jobs."),
    review: str = typer.Option(DEFAULT_REVIEW, help="Path to review.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
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
        style_guide = load_style_guide(config.style_guide_path)
        tailor_agent = build_tailor_agent(style_guide=style_guide)
        reviser_agent = build_reviser_agent(style_guide=style_guide)
        reviewer_agents = build_reviewer_agents(config, style_guide=style_guide)

        for job in targets:
            versions = tailor_job(
                session, job, profile_facts, config, tailor_agent, reviewer_agents, reviser_agent
            )
            typer.echo(
                f"Job #{job.id}: {len(versions)} version(s); final fact_check_passed={versions[-1].fact_check_passed}"
            )


@app.command("cover-letter")
def cover_letter_cmd(
    job_id: int | None = typer.Option(None, help="Write a cover letter for a single job by id."),
    approved: bool = typer.Option(False, "--approved", help="Write cover letters for all approved jobs."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Draft a fact-locked cover letter per job and render it to PDF."""
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

        profile_facts = load_facts(facts)
        draft_agent = build_cover_letter_agent()
        reviser_agent = build_cover_letter_reviser_agent()

        for job in targets:
            cover = generate_cover_letter(session, job, profile_facts, draft_agent, reviser_agent)
            if cover.id is None:
                raise RuntimeError("Cover letter was not persisted")
            path = render_cover_letter(session, cover.id)
            typer.echo(
                f"Job #{job.id}: cover letter #{cover.id} "
                f"(fact_check_passed={cover.fact_check_passed}) -> {path}"
            )


DEFAULT_RENDER = "config/render.yaml"


@app.command("render")
def render_cmd(
    version_id: int = typer.Argument(..., help="resume_versions.id to render to PDF."),
    config: str = typer.Option(DEFAULT_RENDER, help="Path to render.yaml."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
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
    db_url: str | None = typer.Option(None, help="Override the database URL for the dashboard."),
) -> None:
    """Launch the Streamlit dashboard (shortlist checkpoint + pipeline board)."""
    app_path = str(Path(__file__).parent / "dashboard" / "app.py")
    env = dict(os.environ)
    if db_url:
        env["DB_URL"] = db_url
    subprocess.run(["streamlit", "run", app_path], env=env)


@app.command("setup")
def setup_cmd() -> None:
    """Launch the interactive setup wizard (zero → configured → ready)."""
    from resume_agent.setup.app import SetupApp

    SetupApp().run()


@app.command("sync-status")
def sync_status_cmd(
    apply: bool = typer.Option(
        False, "--apply", help="Apply the proposed transitions (default: list only)."
    ),
    max_results: int = typer.Option(50, help="How many recent emails to scan."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Scan recent Gmail and propose application-status updates."""
    service = build_gmail_service()
    emails = fetch_recent_messages(service, max_results=max_results)
    engine = _engine(db_url)
    with get_session(engine) as session:
        pairs = application_job_pairs(session)
        proposals = propose_transitions(emails, pairs, classify_email)
        if not proposals:
            typer.echo("No status changes proposed.")
            raise typer.Exit(code=0)
        for proposal in proposals:
            typer.echo(
                f"  {proposal.label}: {proposal.current_status} -> "
                f"{proposal.proposed_status} ({proposal.evidence})"
            )
        if apply:
            for proposal in proposals:
                update_application_status(session, proposal.application_id, proposal.proposed_status)
            typer.echo(f"Applied {len(proposals)} transition(s).")
        else:
            typer.echo("Re-run with --apply to apply these transitions.")


if __name__ == "__main__":
    app()
