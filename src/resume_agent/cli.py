from pathlib import Path
from typing import cast

import typer
from sqlmodel import select

from resume_agent.config import load_yaml, get_settings
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.connectors.telemetry import read_runs
from resume_agent.discovery.ingest import ingest_jobs
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
from resume_agent.discovery.search_config import load_search_config
from resume_agent.gmail.classify import classify_email
from resume_agent.gmail.client import build_gmail_service, fetch_recent_messages
from resume_agent.gmail.propose import propose_transitions
from resume_agent.llm_runner import resolve_api_key
from resume_agent.progress import ProgressReporter
from resume_agent.profile.store import load_facts
from resume_agent.render.export import export_job_artifacts
from resume_agent.services.cover_letters import write_cover_letters
from resume_agent.services.discovery import (
    UrlFetchError,
    add_job_from_text,
    add_job_from_url,
    discover_jobs,
    pull_jobs,
    refresh_jobs,
    reprocess_jobs,
)
from resume_agent.services.prune import prune as run_prune
from resume_agent.services.rendering import render_resume_version
from resume_agent.services.tailoring import tailor
from resume_agent.tracking.queries import application_job_pairs
from resume_agent.tracking.repository import (
    get_job,
    save_job,
    update_application_status,
)
from resume_agent.tracking.canonicalize import build_skill_canonicalizer
from resume_agent.tracking.match_gap import match_gap
from resume_agent.tracking.tables import Job, JobStatus

app = typer.Typer(help="Resume Agent — personal job-hunt automation pipeline.")
profile_app = typer.Typer(help="Build and manage your fact-lock profile.")
app.add_typer(profile_app, name="profile")

DEFAULT_SOURCES = "config/profile_sources.yaml"
DEFAULT_FACTS = "data/profile/facts.json"
DEFAULT_PROFILE_DIR = "data/profile"


@profile_app.command("add")
def profile_add(
    file: str = typer.Argument(
        ..., help="Document to ingest (.pdf/.docx/.txt/.md/.pptx)."
    ),
    primary: bool = typer.Option(
        False, "--primary", help="Mark as the canonical resume."
    ),
    dir: str = typer.Option(
        DEFAULT_PROFILE_DIR, "--dir", help="Profile data directory."
    ),
    mode: str | None = typer.Option(
        None, "--mode", help="'literal' or 'synthesis' (default: by file type; .pptx → synthesis)."
    ),
    anchor: str | None = typer.Option(
        None, "--anchor", help="Experience/project fact id synthesized entries attach to."
    ),
) -> None:
    """Register a source document in the profile corpus."""
    from resume_agent.profile.corpus import add_source

    doc = add_source(dir, file, primary=primary, mode=mode, anchor=anchor)  # type: ignore[arg-type]
    suffix = " (primary)" if doc.primary else ""
    typer.echo(f"Registered {doc.filename} as {doc.id} mode:{doc.mode}{suffix}")


@profile_app.command("remove")
def profile_remove(
    ident: str = typer.Argument(..., help="Document id or filename."),
    purge: bool = typer.Option(
        False, "--purge", help="Also delete the stored source copy."
    ),
    dir: str = typer.Option(DEFAULT_PROFILE_DIR, "--dir"),
) -> None:
    """Unregister a source document and its cached fragment."""
    from resume_agent.profile.corpus import remove_source

    doc = remove_source(dir, ident, purge=purge)
    if doc is None:
        typer.echo(f"No source matches {ident!r}.")
        raise typer.Exit(code=1)
    typer.echo(f"Removed {doc.filename} ({doc.id})")


@profile_app.command("sources")
def profile_sources(
    dir: str = typer.Option(DEFAULT_PROFILE_DIR, "--dir")
) -> None:
    """List registered source documents and fragment cache status."""
    from resume_agent.profile.corpus import load_manifest
    from resume_agent.profile.fragments import fragment_cache_status

    manifest = load_manifest(dir)
    if not manifest.docs:
        typer.echo("No sources registered. Use 'resume-agent profile add <file>'.")
        return
    for doc in manifest.docs:
        flags = " primary" if doc.primary else ""
        status = fragment_cache_status(dir, doc)
        anchor = f" anchor:{doc.anchor}" if doc.anchor else ""
        typer.echo(
            f"{doc.id}  {doc.filename}  mode:{doc.mode}  sha:{doc.sha256[:8]}  "
            f"added:{doc.added_at}  fragment:{status}{anchor}{flags}"
        )


@profile_app.command("build")
def profile_build(
    sources: str = typer.Option(
        DEFAULT_SOURCES,
        help="Legacy profile_sources.yaml (GitHub username + resume migration).",
    ),
    out: str = typer.Option(DEFAULT_FACTS, help="Where to write facts.json."),
    dir: str = typer.Option(
        DEFAULT_PROFILE_DIR, "--dir", help="Profile data directory."
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Overwrite an existing facts.json (discards manual edits).",
    ),
) -> None:
    """Build bound facts.json and matrix.json artifacts from the corpus."""
    from resume_agent.profile.corpus import migrate_legacy
    from resume_agent.services.profile_build import run_corpus_build

    settings = get_settings()
    required_models = {settings.cheap_model, settings.mid_model}
    missing_models = sorted(
        model for model in required_models if not resolve_api_key(model)
    )
    if missing_models:
        typer.echo(
            f"Missing API key for configured model(s): {', '.join(missing_models)}"
        )
        raise typer.Exit(code=1)
    if Path(out).resolve() != (Path(dir) / "facts.json").resolve():
        typer.echo("--out must be <dir>/facts.json so facts and matrix stay bound")
        raise typer.Exit(code=1)
    if Path(out).exists() and not refresh:
        typer.echo(
            f"{out} already exists. Use --refresh to rebuild (this discards manual edits)."
        )
        raise typer.Exit(code=1)

    cfg = load_yaml(sources) if Path(sources).exists() else {}
    migrated = migrate_legacy(dir, cast(str | None, cfg.get("resume_path")))
    if migrated is not None:
        typer.echo(
            f"Migrated legacy resume into the corpus as {migrated.id} (primary)"
        )

    report = run_corpus_build(
        None,
        profile_dir=Path(dir),
        github_username=cast(str | None, cfg.get("github_username")),
        facts_out=out,
    )
    typer.echo(
        f"Wrote {report['experiences']} experiences and "
        f"{report['projects']} projects to {out}"
    )
    typer.echo(f"Matrix: {report['matrixRows']} skills")
    for doc_id, status in report["docStatus"].items():
        typer.echo(f"  {doc_id}: {status}")
    for conflict in report["conflicts"]:
        typer.echo(f"  CONFLICT: {conflict}")
    for name in report["inferred"]:
        typer.echo(f"  inferred: {name}")
    for line in report["anchorDecisions"]:
        typer.echo(f"  anchor: {line}")
    for line in report["verificationDrops"]:
        typer.echo(f"  DROPPED: {line}")
    for warning in report["warnings"]:
        typer.echo(f"  WARNING: {warning}")


DEFAULT_SEARCH = "config/search.yaml"
DEFAULT_CONNECTORS = "config/connectors.yaml"
CONNECTOR_RUNS_PATH = "data/connector_runs.json"


def _engine(db_url: str | None):
    engine = make_engine(db_url or get_settings().db_url)
    init_db(engine)
    return engine


def _read_piped_stdin() -> str | None:
    stream = typer.get_text_stream("stdin")
    if stream.isatty():
        return None
    text = stream.read()
    return text if text.strip() else None


@app.command("addjob")
def addjob(
    url: str | None = typer.Option(
        None,
        help="Posting URL. With no JD source, the page is fetched and fields are auto-extracted.",
    ),
    company: str | None = typer.Option(
        None, help="Company name (overrides extracted)."
    ),
    title: str | None = typer.Option(None, help="Job title (overrides extracted)."),
    location: str | None = typer.Option(None, help="Location (overrides extracted)."),
    jd_file: str | None = typer.Option(
        None, help="Read the JD from this file instead of stdin/URL."
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Force HTTP-only fetching (skip the Playwright fallback).",
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Add a job from a URL (auto-extract), a --jd-file, or JD pasted on stdin.

    Precedence: --jd-file, non-empty piped stdin, then URL extraction.
    """
    stdin_text = None if jd_file else _read_piped_stdin()
    engine = _engine(db_url)
    is_url_extract = bool(url) and not (jd_file or stdin_text is not None)
    if jd_file or stdin_text is not None:
        jd_text = (
            Path(jd_file).read_text(encoding="utf-8") if jd_file else stdin_text or ""
        )
        with get_session(engine) as session:
            job = add_job_from_text(
                session,
                jd_text=jd_text,
                url=url,
                company=company,
                title=title,
                location=location,
            )
    elif url:
        try:
            with get_session(engine) as session:
                job = add_job_from_url(
                    session,
                    url=url,
                    company=company,
                    title=title,
                    location=location,
                    allow_browser=not no_browser,
                )
        except UrlFetchError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=1) from exc
    else:
        jd_text = typer.get_text_stream("stdin").read()
        with get_session(engine) as session:
            job = add_job_from_text(
                session,
                jd_text=jd_text,
                url=url,
                company=company,
                title=title,
                location=location,
            )
    if is_url_extract and job is not None:
        typer.echo(
            f"Extracted: {job.title or '?'} @ {job.company or '?'} ({job.location or '?'})"
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
    """Run the discovery funnel over new (raw) jobs and report status counts."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        counts = discover_jobs(
            session,
            search_path=search,
            facts_path=facts,
            reporter=ProgressReporter("discover"),
        )
    typer.echo(f"Discovery complete. Status counts: {counts}")


@app.command("reprocess")
def reprocess_cmd(
    scope: list[str] = typer.Option(
        ["shortlisted"],
        "--scope",
        help="Repeatable: shortlisted | rejected:relevance | rejected:filtered | all.",
    ),
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Re-run the full funnel over chosen scopes (can flip fit + status)."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        counts = reprocess_jobs(
            session,
            scopes=scope,
            search_path=search,
            facts_path=facts,
            reporter=ProgressReporter("discover"),
        )
    typer.echo(f"Reprocess complete. Status counts: {counts}")


@app.command("refresh")
def refresh_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    connectors_path: str = typer.Option(
        DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."
    ),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    limit: int | None = typer.Option(None, help="Cap postings per connector this run."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Pull from connectors then discover the new jobs, in one pass."""
    if not Path(connectors_path).exists():
        typer.echo(
            f"No connectors config found at {connectors_path}. "
            "Copy config/connectors.yaml.example to config/connectors.yaml and edit it."
        )
        raise typer.Exit(code=1)
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = refresh_jobs(
            session,
            search_path=search,
            connectors_path=connectors_path,
            telemetry_path=CONNECTOR_RUNS_PATH,
            facts_path=facts,
            limit=limit,
            reporter=ProgressReporter("refresh"),
        )
    typer.echo(
        f"Refresh complete. +{report.pulled} pulled. Status counts: {report.status_counts}"
    )


@app.command("scrape")
def scrape_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    limit: int | None = typer.Option(
        None, help="Cap the number of postings fetched this run."
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Scrape LinkedIn for jobs matching search.yaml and insert them as raw jobs."""
    config = load_search_config(search)
    connector = build_linkedin_scraper()
    engine = _engine(db_url)
    with get_session(engine) as session:
        result = connector.fetch(config, limit=limit)
        added = ingest_jobs(session, result.jobs)
    if result.failures:
        joined = ", ".join(
            f"{url} ({reason})" for url, reason in result.failures.items()
        )
        typer.echo(f"Skipped {len(result.failures)} failed posting(s): {joined}")
    typer.echo(f"Scrape complete. Added {sum(added.values())} new job(s).")


@app.command("pull")
def pull_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    connectors_path: str = typer.Option(
        DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."
    ),
    limit: int | None = typer.Option(None, help="Cap postings per connector this run."),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Re-fetch jobs already known instead of skipping their expensive detail work.",
    ),
    relearn: bool = typer.Option(
        False,
        "--relearn",
        help="Force scrape connectors to learn fresh selector recipes this run.",
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run every enabled connector, dedupe into raw jobs, and report per-source counts."""
    if not Path(connectors_path).exists():
        typer.echo(
            f"No connectors config found at {connectors_path}. "
            "Copy config/connectors.yaml.example to config/connectors.yaml and edit it."
        )
        raise typer.Exit(code=1)
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = pull_jobs(
            session,
            search_path=search,
            connectors_path=connectors_path,
            telemetry_path=CONNECTOR_RUNS_PATH,
            limit=limit,
            reporter=ProgressReporter("pull"),
            skip_known=not refresh,
            relearn=relearn,
        )
    if not report.totals and not report.failures:
        typer.echo(
            "No connectors enabled. Edit connectors.yaml (and .env) to enable some."
        )
        raise typer.Exit(code=0)
    for name in sorted(report.totals):
        typer.echo(f"  {name:<12} +{report.totals.get(name, 0)}")
    for name, failures in report.failures.items():
        joined = ", ".join(f"{tok} ({reason})" for tok, reason in failures.items())
        typer.echo(f"  {name}: skipped {len(failures)} dead source(s): {joined}")
    typer.echo(f"Pull complete. Added {sum(report.totals.values())} new job(s).")


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
    job_id: int | None = typer.Option(
        None, help="Show gaps for one job instead of the aggregate."
    ),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    llm: bool = typer.Option(
        False,
        "--llm",
        help="Add a cheap-LLM synonym pass, such as k8s matching Kubernetes.",
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Report skills your target jobs demand that your profile does not show."""
    from resume_agent.profile.matrix import effective_cluster_map, load_overrides
    from resume_agent.taxonomy.clusters import load_cluster_map

    profile_facts = load_facts(facts)
    profile_dir = Path(facts).parent
    cluster_path = profile_dir / "cluster_map.json"
    overrides = load_overrides(profile_dir / "overrides.yaml")
    cluster_map = effective_cluster_map(load_cluster_map(cluster_path), overrides)
    has_persisted_map = cluster_path.exists() and bool(
        cluster_map.aliases or cluster_map.theme_of
    )
    has_overrides = bool(overrides.alias or overrides.forbid_alias)
    use_cluster_map = has_persisted_map or has_overrides
    canonicalizer = build_skill_canonicalizer() if llm and not use_cluster_map else None
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = match_gap(
            session,
            profile_facts,
            canonicalizer=canonicalizer,
            cluster_map=cluster_map if use_cluster_map else None,
        )

    if report.target_total == 0:
        typer.echo(
            "No jobs past discovery yet. Run `discover` and shortlist/approve some first."
        )
        raise typer.Exit(code=0)

    if job_id is not None:
        missing = report.per_job.get(job_id)
        if missing is None:
            typer.echo(
                f"Job #{job_id} is not among your {report.target_total} target jobs."
            )
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
        tier = " adjacent" if gap.adjacent else ""
        typer.echo(
            f"  {gap.skill:<28} demanded by {gap.demand_count}/{gap.target_total}{tier}"
        )


DEFAULT_REVIEW = "config/review.yaml"


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
    approved: bool = typer.Option(
        False, "--approved", help="Tailor all approved jobs."
    ),
    review: str = typer.Option(DEFAULT_REVIEW, help="Path to review.yaml."),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the tailor + review loop over approved job(s)."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        if job_id is None and not approved:
            typer.echo("Specify --job-id <id> or --approved.")
            raise typer.Exit(code=1)
        if job_id is not None and get_job(session, job_id) is None:
            typer.echo(f"Job #{job_id} not found.")
            raise typer.Exit(code=1)

        results = tailor(
            session,
            job_ids=[job_id] if job_id is not None else None,
            approved=approved,
            review_path=review,
            facts_path=facts,
            reporter=ProgressReporter("tailor"),
        )
        for jid, versions in results.items():
            typer.echo(
                f"Job #{jid}: {len(versions)} version(s); final fact_check_passed={versions[-1].fact_check_passed}"
            )


@app.command("cover-letter")
def cover_letter_cmd(
    job_id: int | None = typer.Option(
        None, help="Write a cover letter for a single job by id."
    ),
    approved: bool = typer.Option(
        False, "--approved", help="Write cover letters for all approved jobs."
    ),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Draft a fact-locked cover letter per job and render it to PDF."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        if job_id is None and not approved:
            typer.echo("Specify --job-id <id> or --approved.")
            raise typer.Exit(code=1)
        if job_id is not None and get_job(session, job_id) is None:
            typer.echo(f"Job #{job_id} not found.")
            raise typer.Exit(code=1)

        results = write_cover_letters(
            session,
            job_ids=[job_id] if job_id is not None else None,
            approved=approved,
            facts_path=facts,
        )
        for r in results:
            typer.echo(
                f"Job #{r.job_id}: cover letter #{r.cover_letter_id} "
                f"(fact_check_passed={r.fact_check_passed}) -> {r.pdf_path}"
            )


DEFAULT_RENDER = "config/render.yaml"


@app.command("render")
def render_cmd(
    version_id: int = typer.Argument(..., help="resume_versions.id to render to PDF."),
    config: str = typer.Option(DEFAULT_RENDER, help="Path to render.yaml."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Render a stored resume version to a PDF."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        path = render_resume_version(session, version_id, render_path=config)
    if path is None:
        typer.echo(f"Resume version #{version_id} not found.")
        raise typer.Exit(code=1)
    typer.echo(f"Rendered version #{version_id} -> {path}")


@app.command("export")
def export_cmd(
    job_id: int | None = typer.Argument(None, help="Job id to export."),
    all_jobs: bool = typer.Option(False, "--all", help="Export every job."),
    output: str = typer.Option("output", "--output", help="Base output directory."),
    db_url: str | None = typer.Option(
        None, "--db-url", help="Override the database URL."
    ),
) -> None:
    """Write per-job folders from the database-authoritative version store."""
    engine = _engine(db_url)
    with get_session(engine) as session:
        if all_jobs:
            ids = [
                job.id for job in session.exec(select(Job)).all() if job.id is not None
            ]
        elif job_id is not None:
            ids = [job_id]
        else:
            typer.echo("Pass a JOB_ID or --all.")
            raise typer.Exit(code=1)

        count = 0
        for current_job_id in ids:
            if export_job_artifacts(session, current_job_id, base=output) is not None:
                count += 1
    typer.echo(f"Exported {count} job folder(s) to {output}/")


@app.command("setup")
def setup_cmd() -> None:
    """Launch the interactive setup wizard (zero → configured → ready)."""
    from resume_agent.setup.app import SetupApp

    SetupApp().run()


@app.command("prune")
def prune(
    db_url: str | None = typer.Option(
        None, "--db-url", help="Override the configured DB URL."
    ),
    config: str = typer.Option(
        "config/prune.yaml", "--config", help="Path to prune.yaml."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show counts without writing."
    ),
    fit: int | None = typer.Option(None, "--fit", help="Override fit_threshold."),
    stale_days: int | None = typer.Option(
        None, "--stale-days", help="Override stale_days."
    ),
    retention_days: int | None = typer.Option(
        None, "--retention-days", help="Override retention_days."
    ),
) -> None:
    """Archive junk jobs (rejected / low-fit / stale) and expire old archived ones."""
    with get_session(_engine(db_url)) as session:
        report = run_prune(
            session,
            dry_run=dry_run,
            fit_threshold=fit,
            stale_days=stale_days,
            retention_days=retention_days,
            config_path=config,
        )
    if dry_run:
        typer.echo(
            f"[dry-run] {report.rejected} rejected, {report.low_fit} low-fit, "
            f"{report.stale} stale -> {report.archived} to archive; "
            f"{report.expired} to expire, {report.skipped} skipped (have progress)"
        )
    else:
        typer.echo(
            f"+{report.archived} archived "
            f"({report.rejected} rejected, {report.low_fit} low-fit, {report.stale} stale), "
            f"{report.expired} expired, {report.skipped} skipped"
        )


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
                update_application_status(
                    session, proposal.application_id, proposal.proposed_status
                )
            typer.echo(f"Applied {len(proposals)} transition(s).")
        else:
            typer.echo("Re-run with --apply to apply these transitions.")


@app.command("serve")
def serve_cmd(
    host: str = typer.Option(
        "127.0.0.1", help="Bind host (use 0.0.0.0 to expose on LAN)."
    ),
    port: int = typer.Option(8000, help="Bind port."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Run the FastAPI backend (for the React frontend / API clients)."""
    import uvicorn

    from resume_agent.api.app import create_app

    uvicorn.run(create_app(db_url=db_url), host=host, port=port)


if __name__ == "__main__":
    app()
