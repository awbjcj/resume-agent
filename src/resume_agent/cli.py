from enum import Enum
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, cast

import typer
from sqlmodel import select

from resume_agent.admin_cli import admin_app
from resume_agent.config import get_settings, load_yaml
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.discovery.connectors.telemetry import read_runs
from resume_agent.gmail.classify import classify_email
from resume_agent.gmail.client import build_gmail_service, fetch_recent_messages
from resume_agent.gmail.propose import propose_transitions
from resume_agent.llm_runner import missing_model_keys, plan_search, resolve_api_key
from resume_agent.profile.depth import SUPPLY_TARGET
from resume_agent.profile.store import load_facts
from resume_agent.progress import ProgressReporter
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
    scrape_linkedin_jobs,
)
from resume_agent.services.prune import prune as run_prune
from resume_agent.services.rendering import render_resume_version
from resume_agent.services.tailoring import DEFAULT_REVIEW, DEFAULT_REVIEW_DEEP, tailor
from resume_agent.tenancy.paths import (
    CONNECTORS_PATH as DEFAULT_CONNECTORS,
)
from resume_agent.tenancy.paths import (
    FACTS_PATH as DEFAULT_FACTS,
)
from resume_agent.tenancy.paths import (
    SEARCH_PATH as DEFAULT_SEARCH,
)
from resume_agent.tenancy.paths import (
    TELEMETRY_PATH as CONNECTOR_RUNS_PATH,
)
from resume_agent.tracking.canonicalize import build_skill_canonicalizer
from resume_agent.tracking.match_gap import match_gap
from resume_agent.tracking.queries import application_job_pairs
from resume_agent.tracking.repository import (
    get_job,
    save_job,
    update_application_status,
)
from resume_agent.tracking.tables import Job, JobStatus

app = typer.Typer(help="Resume Agent — personal job-hunt automation pipeline.")
profile_app = typer.Typer(help="Build and manage your fact-lock profile.")
app.add_typer(profile_app, name="profile")
app.add_typer(admin_app, name="admin")


class ServeMode(str, Enum):
    local = "local"
    hosted = "hosted"


_NO_LOCAL_CONTEXT_COMMANDS = {"serve", "admin"}


@app.callback()
def _main(
    ctx: typer.Context,
    user: str | None = typer.Option(
        None,
        "--user",
        help="Workspace username on a multi-user data root (default: first admin).",
    ),
) -> None:
    if ctx.invoked_subcommand in _NO_LOCAL_CONTEXT_COMMANDS:
        # `serve` bootstraps its own admin/context per-request via the API app's
        # lifespan (ensure_bootstrapped); `admin` talks to a *deployed* instance
        # over HTTP and never touches a local data root. Activating a local
        # context here would require an admin to already exist, which is exactly
        # what `serve`'s first run is bootstrapping.
        return
    from resume_agent.tenancy.context import activate, deactivate
    from resume_agent.tenancy.local import resolve_local_context

    context = resolve_local_context(Path("data"), user)
    if context is not None:
        token = activate(context)
        # Scope activation to this invocation only (ctx.call_on_close runs after
        # the subcommand finishes, success or error) — otherwise the contextvar
        # stays set process-wide, which is invisible in normal CLI use (the
        # process exits right after) but silently contaminates every later test
        # in the same pytest run once a local admin exists.
        ctx.call_on_close(lambda: deactivate(token))


DEFAULT_SOURCES = "config/profile_sources.yaml"
DEFAULT_PROFILE_DIR = "data/profile"


def _tenant_cli_path(path: str | Path) -> Path:
    from resume_agent.tenancy.paths import resolve_tenant_path

    return resolve_tenant_path(path)


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
        None,
        "--mode",
        help="'literal', 'synthesis', or 'project' (default: .pptx → synthesis; dossier .md → project).",
    ),
    anchor: str | None = typer.Option(
        None,
        "--anchor",
        help="Experience/project fact id synthesized entries attach to.",
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
def profile_sources(dir: str = typer.Option(DEFAULT_PROFILE_DIR, "--dir")) -> None:
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


@profile_app.command("depth")
def profile_depth_cmd(
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    target: int = typer.Option(
        SUPPLY_TARGET, help="Source bullets an owner needs to clear the bar."
    ),
) -> None:
    """Show per-owner bullet supply and aspect coverage."""
    from resume_agent.profile.aspects import ASPECTS
    from resume_agent.profile.depth import owner_depth

    rows = owner_depth(load_facts(_tenant_cli_path(facts)), target=target)
    if not rows:
        typer.echo("No evidence owners found.")
        return
    for row in rows:
        mark = "OK " if row.meets_target else "GAP"
        typer.echo(
            f"{mark} {row.label} ({row.kind}): {row.source_total}/{target} bullets, "
            f"{len(row.aspects_present)}/{len(ASPECTS)} aspects"
        )
        if row.aspects_missing:
            typer.echo(f"      missing aspects: {', '.join(row.aspects_missing)}")
        if row.unclassified:
            typer.echo(f"      unclassified bullets: {row.unclassified}")
    gaps = [row for row in rows if not row.meets_target]
    if gaps:
        typer.echo(
            f"\n{len(gaps)} of {len(rows)} owners are below the supply target. "
            "Run `profile coach` to add evidence for them."
        )


@profile_app.command("add-note")
def profile_add_note(
    title: str = typer.Argument(..., help="Short note title."),
    text: str = typer.Argument(..., help="The fact(s) to record."),
    dir: str = typer.Option(DEFAULT_PROFILE_DIR, "--dir"),
) -> None:
    """Save free text as a literal profile source."""
    from resume_agent.profile.intake import add_note_source

    try:
        doc = add_note_source(dir, title, text)
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(code=1) from error
    typer.echo(f"Registered {doc.filename} as {doc.id} mode:{doc.mode}")


@profile_app.command("add-url")
def profile_add_url(
    url: str = typer.Argument(..., help="Public page to ingest."),
    dir: str = typer.Option(DEFAULT_PROFILE_DIR, "--dir"),
) -> None:
    """Fetch a public URL and save its readable text as a literal source."""
    import httpx

    from resume_agent.profile import intake

    try:
        doc = intake.add_url_source(dir, url)
    except (httpx.HTTPError, ValueError) as error:
        typer.echo(f"URL intake failed: {error}")
        raise typer.Exit(code=1) from error
    typer.echo(f"Registered {doc.filename} as {doc.id} mode:{doc.mode}")


@profile_app.command("sync-github")
def profile_sync_github(
    username: str | None = typer.Option(None, "--username"),
    sources: str = typer.Option(DEFAULT_SOURCES, "--sources"),
    dir: str = typer.Option(DEFAULT_PROFILE_DIR, "--dir"),
) -> None:
    """Refresh GitHub-derived sources without running a full profile build."""
    from resume_agent.profile.github_harvest import sync_github_sources

    sources_path = _tenant_cli_path(sources)
    config = load_yaml(sources_path) if sources_path.exists() else {}
    selected_username = username or cast(str | None, config.get("github_username"))
    if not selected_username:
        typer.echo("No GitHub username; pass --username or configure github_username.")
        raise typer.Exit(code=1)
    try:
        report = sync_github_sources(
            dir,
            selected_username,
            allow=tuple(config.get("github_repo_allow") or ()),
            deny=tuple(config.get("github_repo_deny") or ()),
            limit=int(config.get("github_repo_limit") or 20),
        )
    except ValueError as error:
        typer.echo(str(error))
        raise typer.Exit(code=1) from error
    typer.echo(
        f"written:{len(report.written)} removed:{len(report.removed)} "
        f"superseded:{len(report.superseded)} failures:{len(report.failures)}"
    )
    for name, reason in sorted(report.failures.items()):
        typer.echo(f"  FAILED {name}: {reason}")
    for warning in report.warnings:
        typer.echo(f"  WARNING: {warning}")


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
    out_path = _tenant_cli_path(out)
    profile_dir = _tenant_cli_path(dir)
    sources_path = _tenant_cli_path(sources)
    if out_path.resolve() != (profile_dir / "facts.json").resolve():
        typer.echo("--out must be <dir>/facts.json so facts and matrix stay bound")
        raise typer.Exit(code=1)
    if out_path.exists() and not refresh:
        typer.echo(
            f"{out} already exists. Use --refresh to rebuild (this discards manual edits)."
        )
        raise typer.Exit(code=1)

    cfg = load_yaml(sources_path) if sources_path.exists() else {}
    migrated = migrate_legacy(profile_dir, cast(str | None, cfg.get("resume_path")))
    if migrated is not None:
        typer.echo(f"Migrated legacy resume into the corpus as {migrated.id} (primary)")

    report = run_corpus_build(
        None,
        profile_dir=profile_dir,
        github_username=cast(str | None, cfg.get("github_username")),
        facts_out=out_path,
        github_allow=tuple(cfg.get("github_repo_allow") or ()),
        github_deny=tuple(cfg.get("github_repo_deny") or ()),
        github_limit=int(cfg.get("github_repo_limit") or 20),
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


@profile_app.command("coach")
def profile_coach_cmd(
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
    no_build: bool = typer.Option(
        False,
        "--no-build",
        help="End the session without rebuilding the profile.",
    ),
    profile_sources: str = typer.Option(
        DEFAULT_SOURCES,
        help="Profile source configuration used by the rebuild.",
    ),
) -> None:
    """Strengthen profile evidence in an interactive coaching chat."""
    from resume_agent.profile.coach_store import active_session
    from resume_agent.profile.corpus import load_manifest
    from resume_agent.services import profile_coach as coach_service
    from resume_agent.sessions.stream import ConsoleStreamSink, NullSink

    profile_dir = _tenant_cli_path(facts).parent
    if not any(
        doc.primary and doc.mode == "literal" for doc in load_manifest(profile_dir).docs
    ):
        typer.echo("Upload a primary resume before starting a coach session.")
        raise typer.Exit(code=1)
    settings = get_settings()
    missing = missing_model_keys(settings)
    if missing:
        typer.echo(f"Missing API key for configured model(s): {', '.join(missing)}")
        raise typer.Exit(code=1)

    class EchoReporter:
        process = "cli-coach"

        def begin(self, total, label, **extra):
            typer.echo(f"{label}…")

        def step(self, current, *, label=None, **extra):
            pass

        def checkpoint(self):
            pass

    reporter = EchoReporter()
    engine = _engine(db_url)
    stream_enabled = getattr(settings, "stream_enabled", True)

    def run_streamed(call, *, label: str = "COACH"):
        sink = (
            ConsoleStreamSink(lambda text: typer.echo(text, nl=False))
            if stream_enabled
            else NullSink()
        )
        if stream_enabled:
            typer.echo(f"\n{label}: ", nl=False)
        try:
            return call(sink)
        finally:
            sink.close()

    def show_latest(view: dict) -> None:
        if not stream_enabled and view["turns"]:
            typer.echo(f"\nCOACH: {view['turns'][-1]['text']}")

    def resolve_pending(view: dict) -> None:
        for draft in view["draftNotes"]:
            if draft["status"] != "pending":
                continue
            typer.echo(f"\nDRAFT NOTE — {draft['title']}\n{draft['summary']}")
            for quote in draft["quotes"]:
                typer.echo(f'  "{quote}"')
            choice = (
                typer.prompt(
                    "Resolve this note? [s]ave / [e]dit / [d]iscard / [l]eave",
                    default="l",
                )
                .strip()
                .lower()
            )
            title = draft["title"]
            summary = draft["summary"]
            quotes = list(draft["quotes"])
            if choice.startswith("e"):
                title = typer.prompt("Title", default=title)
                summary = typer.prompt("Summary", default=summary)
                quotes = [
                    typer.prompt(f"Quote {index}", default=quote)
                    for index, quote in enumerate(quotes, 1)
                ]
                choice = "s"
            if choice.startswith("s"):
                coach_service.approve_draft(
                    profile_dir,
                    view["sessionId"],
                    draft["topicId"],
                    title=title,
                    summary=summary,
                    quotes=quotes,
                )
                draft["status"] = "saved"
                typer.echo("Saved to profile.")
            elif choice.startswith("d"):
                coach_service.discard_draft(
                    profile_dir,
                    view["sessionId"],
                    draft["topicId"],
                )
                draft["status"] = "discarded"
                typer.echo("Discarded.")

    active = active_session(profile_dir)
    if active is None:
        view = run_streamed(
            lambda sink: coach_service.run_opening_turn(
                reporter,
                profile_dir=profile_dir,
                engine=engine,
                sink=sink,
            )
        )
    else:
        view = coach_service.session_view(profile_dir, active["session_id"])
        typer.echo("Resuming your active coaching session.")
    session_id = view["sessionId"]
    show_latest(view)

    while True:
        message = typer.prompt("You")
        if message.strip() == "/end":
            break
        view = run_streamed(
            lambda sink: coach_service.run_message_turn(
                reporter,
                profile_dir=profile_dir,
                session_id=session_id,
                message=message,
                engine=engine,
                sink=sink,
            )
        )
        show_latest(view)
        resolve_pending(view)

    resolve_pending(view)
    saved_any = any(draft["status"] == "saved" for draft in view["draftNotes"])
    recap = run_streamed(
        lambda sink: coach_service.run_recap_turn(
            reporter,
            profile_dir=profile_dir,
            session_id=session_id,
            sink=sink,
        ),
        label="RECAP",
    )
    if not stream_enabled:
        typer.echo(f"\nRECAP: {recap['recap']}")
    if no_build or not saved_any:
        typer.echo("Session saved without rebuilding.")
        return

    sources_path = _tenant_cli_path(profile_sources)
    config = load_yaml(sources_path) if sources_path.exists() else {}
    coach_service.run_build_with_impact(
        reporter,
        profile_dir=profile_dir,
        session_id=session_id,
        github_username=cast(str | None, config.get("github_username")),
        facts_out=profile_dir / "facts.json",
        github_allow=tuple(config.get("github_repo_allow") or ()),
        github_deny=tuple(config.get("github_repo_deny") or ()),
        github_limit=int(config.get("github_repo_limit") or 20),
    )
    typer.echo("Rebuilt profile with the new coach evidence.")


@app.command("career-lab")
def career_lab_cmd(
    goal: str | None = typer.Argument(
        None, help="The goal for this Career Lab session."
    ),
    skill: str | None = typer.Option(
        None, "--skill", help="One approved Career Lab skill."
    ),
    job_id: int | None = typer.Option(None, "--job-id", min=1),
    resume_version_id: int | None = typer.Option(None, "--resume-version-id", min=1),
    offer_application_id: list[int] = typer.Option(
        [], "--offer-application-id", min=1, help="Offer application id (repeatable)."
    ),
    db_url: str | None = typer.Option(None, "--db-url"),
) -> None:
    """Draft career guidance in an interactive, resumable Career Lab session."""
    from resume_agent.career_lab.store import active_session_for_job
    from resume_agent.career_skills.models import AgentFamily
    from resume_agent.career_skills.registry import (
        CareerSkillRegistry,
        SkillUnavailable,
    )
    from resume_agent.services import career_lab as career_service
    from resume_agent.sessions.stream import ConsoleStreamSink, NullSink
    from resume_agent.tenancy.context import current_context

    settings = get_settings()
    missing = missing_model_keys(settings)
    if missing:
        typer.echo(f"Missing API key for configured model(s): {', '.join(missing)}")
        raise typer.Exit(code=1)
    if goal and len(goal) > 2_000:
        typer.echo("Goal is too large (maximum 2,000 characters).")
        raise typer.Exit(code=1)
    try:
        if skill is not None:
            CareerSkillRegistry.from_settings(settings).require(
                skill, family=AgentFamily.CAREER_LAB, use="career_lab"
            )
    except SkillUnavailable as error:
        typer.echo(f"Skill unavailable: {error.reason}")
        raise typer.Exit(code=1) from error

    context = current_context()
    root = (
        context.paths.career_lab_dir
        if context is not None
        else _tenant_cli_path("data/career-lab")
    )
    engine = _engine(db_url)
    context_refs = career_service.CareerLabContextRefs(
        job_id=job_id,
        resume_version_id=resume_version_id,
        offer_application_ids=offer_application_id,
    )

    class EchoReporter:
        process = "cli-career-lab"

        def begin(self, _total, label, **_extra):
            typer.echo(f"{label}…")

        def step(self, *_args, **_kwargs):
            return None

        def checkpoint(self):
            return None

    reporter = EchoReporter()
    stream_enabled = getattr(settings, "stream_enabled", True)

    def run_streamed(call):
        sink = (
            ConsoleStreamSink(lambda text: typer.echo(text, nl=False))
            if stream_enabled
            else NullSink()
        )
        try:
            return call(sink)
        finally:
            sink.close()

    def show_latest(view: dict) -> None:
        if not stream_enabled and view.get("turns"):
            typer.echo(f"\nCareer Lab: {view['turns'][-1]['text']}")

    # Scoped to the job asked about: `--job-id 7` resumes job 7's thread, and a
    # bare invocation resumes the un-anchored one. Resuming "whatever is open"
    # was exact only while one thread could exist at a time — now it could adopt
    # a thread anchored to another job and append this job's context to it.
    active = active_session_for_job(root, job_id)
    if active is None:
        initial = typer.prompt("You")
        if initial.strip().casefold() in {"end", "quit"}:
            typer.echo("No active Career Lab session.")
            return
        view = run_streamed(
            lambda sink: career_service.run_start_turn(
                reporter,
                root=root,
                engine=engine,
                message=initial,
                goal=goal or "",
                skill=skill,
                context_refs=context_refs,
                sink=sink,
            )
        )
    else:
        view = career_service.session_view(root, active["session_id"])
        typer.echo("Resuming your active Career Lab session.")
    session_id = view["sessionId"]
    show_latest(view)

    while True:
        message = typer.prompt("You")
        command = message.strip().casefold()
        if command == "quit":
            typer.echo("Session left active.")
            return
        if command == "end":
            ended = career_service.run_end_turn(
                reporter, root=root, session_id=session_id
            )
            typer.echo("Career Lab session ended.")
            show_latest(ended)
            return
        if not message.strip():
            continue
        view = run_streamed(
            lambda sink: career_service.run_message_turn(
                reporter,
                root=root,
                engine=engine,
                session_id=session_id,
                message=message,
                skill=skill,
                context_refs=context_refs,
                sink=sink,
            )
        )
        show_latest(view)


def _engine(db_url: str | None):
    engine = make_engine(db_url or get_settings().db_url)
    init_db(engine)
    return engine


@app.command("scout")
def scout_cmd(
    initial_message: str | None = typer.Argument(
        None, help="Initial company and search-condition discovery goal."
    ),
    connectors_path: str = typer.Option(
        DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."
    ),
    search_path: str = typer.Option(
        DEFAULT_SEARCH, "--search", help="Path to search.yaml."
    ),
) -> None:
    """Research sources and search terms in an interactive Scout session."""
    import uuid

    from resume_agent.discovery.scout_store import active_session
    from resume_agent.services import scout as scout_service
    from resume_agent.services.config_store import YamlConfigStore
    from resume_agent.services.scout_intelligence import ScoutCompanyIntelligenceLookup
    from resume_agent.sessions.stream import ConsoleStreamSink, NullSink

    settings = get_settings()
    missing = missing_model_keys(settings)
    if missing:
        typer.echo(f"Missing API key for configured model(s): {', '.join(missing)}")
        raise typer.Exit(code=1)
    try:
        search_plan = plan_search(settings.mid_model, settings.search_mode)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if search_plan.strategy == "none":
        typer.echo("Discovery Scout needs web search; change search_mode from off.")
        raise typer.Exit(code=1)

    class EchoReporter:
        def begin(self, total, label, **extra):
            typer.echo(f"{label}…")

        def step(self, current, *, label=None, **extra):
            pass

        def checkpoint(self):
            pass

    reporter = EchoReporter()
    connectors = str(_tenant_cli_path(connectors_path))
    search = str(_tenant_cli_path(search_path))
    profile_dir = _tenant_cli_path(DEFAULT_PROFILE_DIR)
    workspace_root = profile_dir.parent
    config_store = YamlConfigStore(Path(connectors).parent)
    engine = _engine(None)
    stream_enabled = getattr(settings, "stream_enabled", True)

    def run_streamed(call, *, label="SCOUT"):
        sink = (
            ConsoleStreamSink(lambda text: typer.echo(text, nl=False))
            if stream_enabled
            else NullSink()
        )
        if stream_enabled:
            typer.echo(f"\n{label}: ", nl=False)
        try:
            with get_session(engine) as session:
                return call(sink, ScoutCompanyIntelligenceLookup(session))
        finally:
            sink.close()

    def show_latest(view: dict, *, label="SCOUT") -> None:
        if not stream_enabled and view.get("turns"):
            typer.echo(f"\n{label}: {view['turns'][-1]['text']}")

    def display_rows(view: dict) -> list[dict]:
        return list(view.get("proposals", []))

    def show_proposals(view: dict) -> list[dict]:
        rows = display_rows(view)
        for index, row in enumerate(rows, 1):
            if row["kind"] == "source":
                source = row["source"]
                label = source["company"]
                secondary = source.get("ats") or row["check"]
                if source.get("roleCount") is not None:
                    secondary += f" · {source['roleCount']} roles"
            else:
                term = row["term"]
                label = f'{term["termKind"]} "{term["value"]}"'
                secondary = row["check"]
            if row["status"] != "pending":
                secondary = row["status"]
            fit = f" · fit {row['fitScore']}" if row.get("fitScore") is not None else ""
            typer.echo(f"  [{index}] {label:<24} {secondary}{fit}")
        return rows

    active = active_session(workspace_root)
    if active is None:
        first = initial_message or typer.prompt("You")
        if first.strip().casefold() == "quit":
            return
        session_id = uuid.uuid4().hex
        view = run_streamed(
            lambda sink, intelligence_lookup: scout_service.run_start_turn(
                reporter,
                workspace_root=workspace_root,
                session_id=session_id,
                message=first,
                connectors_path=connectors,
                search_path=search,
                profile_dir=profile_dir,
                browser_enabled=settings.browser_enabled,
                sink=sink,
                company_intelligence_lookup=intelligence_lookup,
            )
        )
        show_latest(view)
    else:
        session_id = active["session_id"]
        view = scout_service.session_view(
            workspace_root, session_id, browser_enabled=settings.browser_enabled
        )
        typer.echo("Resuming your active Discovery Scout session.")

    show_proposals(view)
    while True:
        command = typer.prompt("You").strip()
        lowered = command.casefold()
        if lowered == "quit":
            return
        if lowered == "end":
            view = run_streamed(
                lambda sink, intelligence_lookup: scout_service.run_recap_turn(
                    reporter,
                    workspace_root=workspace_root,
                    session_id=session_id,
                    connectors_path=connectors,
                    search_path=search,
                    profile_dir=profile_dir,
                    browser_enabled=settings.browser_enabled,
                    sink=sink,
                    company_intelligence_lookup=intelligence_lookup,
                ),
                label="RECAP",
            )
            if not stream_enabled:
                typer.echo(f"\nRECAP: {view.get('recap') or ''}")
            return

        rows = display_rows(view)
        if lowered.startswith("add "):
            try:
                indexes = [int(value) for value in command.split()[1:]]
                proposal_ids = [rows[index - 1]["id"] for index in indexes if index > 0]
                if len(proposal_ids) != len(indexes):
                    raise IndexError
            except (ValueError, IndexError):
                typer.echo("Use: add <proposal number> [more numbers]")
                continue
            for proposal_id in proposal_ids:
                try:
                    view = scout_service.approve_proposal(
                        workspace_root,
                        session_id,
                        proposal_id,
                        config_store=config_store,
                        connectors_path=connectors,
                        search_path=search,
                        browser_enabled=settings.browser_enabled,
                    )
                except ValueError as exc:
                    typer.echo(f"Could not add {proposal_id}: {exc}")
            show_proposals(view)
            continue

        if lowered.startswith("skip "):
            parts = command.split(maxsplit=2)
            try:
                index = int(parts[1])
                proposal_id = rows[index - 1]["id"] if index > 0 else ""
                if not proposal_id:
                    raise IndexError
            except (ValueError, IndexError):
                typer.echo("Use: skip <proposal number> [reason]")
                continue
            view = scout_service.dismiss_proposal(
                workspace_root,
                session_id,
                proposal_id,
                reason=parts[2] if len(parts) > 2 else "",
                browser_enabled=settings.browser_enabled,
            )
            show_proposals(view)
            continue

        view = run_streamed(
            lambda sink, intelligence_lookup: scout_service.run_message_turn(
                reporter,
                workspace_root=workspace_root,
                session_id=session_id,
                message=command,
                connectors_path=connectors,
                search_path=search,
                profile_dir=profile_dir,
                browser_enabled=settings.browser_enabled,
                sink=sink,
                company_intelligence_lookup=intelligence_lookup,
            )
        )
        show_latest(view)
        show_proposals(view)


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
    limit: int | None = typer.Option(
        None,
        help=(
            "Default cap per source unit (board/URL/aggregator); per-source "
            "limits in connectors.yaml override."
        ),
    ),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Pull from connectors then discover the new jobs, in one pass."""
    if not _tenant_cli_path(connectors_path).exists():
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
    engine = _engine(db_url)
    with get_session(engine) as session:
        outcome = scrape_linkedin_jobs(session, search_path=search, limit=limit)
    if outcome["failures"]:
        joined = ", ".join(
            f"{url} ({reason})" for url, reason in outcome["failures"].items()
        )
        typer.echo(f"Skipped {len(outcome['failures'])} failed posting(s): {joined}")
    typer.echo(f"Scrape complete. Added {outcome['added']} new job(s).")


@app.command("pull")
def pull_cmd(
    search: str = typer.Option(DEFAULT_SEARCH, help="Path to search.yaml."),
    connectors_path: str = typer.Option(
        DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."
    ),
    limit: int | None = typer.Option(
        None,
        help=(
            "Default cap per source unit (board/URL/aggregator); per-source "
            "limits in connectors.yaml override."
        ),
    ),
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
    if not _tenant_cli_path(connectors_path).exists():
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


@app.command("fix-company-names")
def fix_company_names_cmd(
    connectors_path: str = typer.Option(
        DEFAULT_CONNECTORS, "--connectors", help="Path to connectors.yaml."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without writing."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
) -> None:
    """Rename token companies from configured or resolved display names."""
    from resume_agent.discovery.connectors.config import load_connectors_config
    from resume_agent.services.company_fix import fix_company_names

    if not _tenant_cli_path(connectors_path).exists():
        typer.echo(f"No connectors config found at {connectors_path}.")
        raise typer.Exit(code=1)
    config = load_connectors_config(connectors_path)
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = fix_company_names(session, config, dry_run=dry_run)
    for token, count in sorted(report.renamed.items()):
        qualifier = "would be " if dry_run else ""
        typer.echo(f"{token}: {count} row(s) {qualifier}renamed")
    for kept, skipped in report.conflicts:
        typer.echo(f"CONFLICT: row #{skipped} skipped (identity held by #{kept})")
    for token in report.unresolved:
        typer.echo(f"unresolved: {token} (no display name)")


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
    from resume_agent.profile.effective import build_effective_taxonomy

    profile_facts = load_facts(facts)
    profile_dir = _tenant_cli_path(facts).parent
    taxonomy = build_effective_taxonomy(profile_dir)
    use_cluster_map = taxonomy.is_populated
    canonicalizer = build_skill_canonicalizer() if llm and not use_cluster_map else None
    engine = _engine(db_url)
    with get_session(engine) as session:
        report = match_gap(
            session,
            profile_facts,
            canonicalizer=canonicalizer,
            cluster_map=taxonomy.cluster_map if use_cluster_map else None,
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
    deep: bool = typer.Option(
        False,
        "--deep",
        help="Use the full multi-round review roster.",
    ),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    skill: str | None = typer.Option(None, "--skill", help="Resume authoring skill."),
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

        review_path = (
            DEFAULT_REVIEW_DEEP if deep and review == DEFAULT_REVIEW else review
        )
        tailor_kwargs = {
            "job_ids": [job_id] if job_id is not None else None,
            "approved": approved,
            "review_path": review_path,
            "facts_path": facts,
            "reporter": ProgressReporter("tailor"),
        }
        if skill is not None:
            tailor_kwargs["authoring_skill"] = skill
        outcome = tailor(
            session,
            **tailor_kwargs,
        )
        for jid, versions in outcome.versions.items():
            typer.echo(
                f"Job #{jid}: {len(versions)} version(s); final fact_check_passed={versions[-1].fact_check_passed}"
            )
        for jid, failure in outcome.failures.items():
            typer.echo(f"Job #{jid}: failed -- {failure.error_type}: {failure.message}")


@app.command("cover-letter")
def cover_letter_cmd(
    job_id: int | None = typer.Option(
        None, help="Write a cover letter for a single job by id."
    ),
    approved: bool = typer.Option(
        False, "--approved", help="Write cover letters for all approved jobs."
    ),
    facts: str = typer.Option(DEFAULT_FACTS, help="Path to facts.json."),
    skill: str | None = typer.Option(None, "--skill", help="Cover-letter skill."),
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

        cover_kwargs = {
            "job_ids": [job_id] if job_id is not None else None,
            "approved": approved,
            "facts_path": facts,
        }
        if skill is not None:
            cover_kwargs["skill"] = skill
        results = write_cover_letters(
            session,
            **cover_kwargs,
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


def _delete_artifacts_cmd(
    ids: list[int], db_url: str | None, *, kind: Literal["resume", "cover-letter"]
) -> None:
    """Shared body for the two delete commands: same rules, different noun."""
    from resume_agent.services.board import (
        delete_cover_letters,
        delete_resume_versions,
    )

    noun = "Resume version" if kind == "resume" else "Cover letter"
    delete = delete_resume_versions if kind == "resume" else delete_cover_letters
    engine = _engine(db_url)
    with get_session(engine) as session:
        result = delete(session, ids)

    if result.missing_ids:
        typer.echo(f"{noun}(s) not found: {_id_list(result.missing_ids)}")
        raise typer.Exit(code=1)
    if result.blocked_ids:
        # Named rather than skipped: silently deleting the rest would leave the
        # caller believing the whole batch is gone.
        typer.echo(
            f"{noun}(s) selected for an application: {_id_list(result.blocked_ids)}\n"
            "Nothing was deleted. Unselect them first, then retry."
        )
        raise typer.Exit(code=1)
    typer.echo(f"Deleted {result.deleted} {kind}(s).")


def _id_list(ids: tuple[int, ...]) -> str:
    return ", ".join(f"#{value}" for value in ids)


@app.command("delete-resume-versions")
def delete_resume_versions_cmd(
    version_ids: list[int] = typer.Argument(..., help="resume_versions.id to delete."),
    db_url: str | None = typer.Option(
        None, "--db-url", help="Override the database URL."
    ),
) -> None:
    """Delete unneeded resume versions and their rendered PDFs.

    All-or-nothing: refuses the whole batch if any id is unknown or is the
    version selected for its job's application.
    """
    _delete_artifacts_cmd(version_ids, db_url, kind="resume")


@app.command("delete-cover-letters")
def delete_cover_letters_cmd(
    cover_letter_ids: list[int] = typer.Argument(
        ..., help="cover_letters.id to delete."
    ),
    db_url: str | None = typer.Option(
        None, "--db-url", help="Override the database URL."
    ),
) -> None:
    """Delete unneeded cover letters and their rendered PDFs."""
    _delete_artifacts_cmd(cover_letter_ids, db_url, kind="cover-letter")


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


@app.command("reset")
def reset_cmd(
    scope: str = typer.Option(
        ...,
        "--scope",
        help="What to clear: jobs | profile | all.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the typed confirmation.",
    ),
    db_url: str | None = typer.Option(
        None,
        "--db-url",
        help="Override the configured DB URL.",
    ),
) -> None:
    """Clear job data, the profile corpus, or all workspace-derived data."""
    from resume_agent.services.reset import (
        ResetPaths,
        ResetScope,
        count_rows,
        reset_workspace,
        scope_paths,
    )

    try:
        reset_scope = ResetScope(scope)
    except ValueError:
        raise typer.BadParameter(
            "scope must be jobs, profile, or all",
            param_hint="--scope",
        ) from None

    paths = ResetPaths.resolve()
    with get_session(_engine(db_url)) as session:
        if not yes:
            typer.echo(f"Reset scope '{reset_scope.value}' will delete:")
            for table, count in count_rows(session, reset_scope).items():
                typer.echo(f"  {table}: {count} rows")
            typer.echo("  filesystem targets:")
            for path in scope_paths(paths, reset_scope):
                typer.echo(f"    {path.absolute()}")
            answer = typer.prompt(f"Type {reset_scope.value} to confirm")
            if answer != reset_scope.value:
                typer.echo("Aborted.")
                raise typer.Exit(code=1)
        report = reset_workspace(session, paths, reset_scope)

    typer.echo(f"Deleted {sum(report.rows_deleted.values())} rows")
    typer.echo(f"Cleared: {', '.join(report.areas_cleared) or 'none'}")
    for path, reason in report.failures.items():
        typer.echo(f"Warning: {path}: {reason}", err=True)


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


@app.command("hash-password")
def hash_password_cmd(
    password: str = typer.Option(
        ...,
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Password to hash for AUTH_PASSWORD_HASH.",
    ),
) -> None:
    """Print the PBKDF2 hash used by single-account session auth."""
    from resume_agent.api.auth import hash_password

    typer.echo(hash_password(password))


@app.command("serve")
def serve_cmd(
    host: str = typer.Option(
        "127.0.0.1", help="Bind host (use 0.0.0.0 to expose on LAN)."
    ),
    port: int = typer.Option(8000, help="Bind port."),
    db_url: str | None = typer.Option(None, help="Override the database URL."),
    mode: ServeMode = typer.Option(
        ServeMode.local,
        help="Local bypasses account auth; hosted enables login and tenants.",
    ),
) -> None:
    """Run the FastAPI backend (for the React frontend / API clients)."""
    import uvicorn

    from resume_agent.api.app import create_app

    normalized_host = host.strip().strip("[]")
    try:
        loopback = ip_address(normalized_host).is_loopback
    except ValueError:
        loopback = normalized_host.casefold() == "localhost"
    if mode is ServeMode.local and not loopback:
        raise typer.BadParameter(
            "local mode has no authentication and must bind to a loopback host; "
            "use --mode hosted to expose the server"
        )
    uvicorn.run(create_app(db_url=db_url, app_mode=mode.value), host=host, port=port)


if __name__ == "__main__":
    app()
