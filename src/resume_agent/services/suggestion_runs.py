"""Submit suggestion generation through the shared background-run substrate."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from resume_agent.api.runs.manager import RunManager
from resume_agent.db import get_session as open_session
from resume_agent.github.repos import verify_repo
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.store import load_facts
from resume_agent.services.suggestions import (
    SuggestionContext,
    generate_suggestion,
    resolve_suggestion_context,
)
from resume_agent.suggestions.agents import build_formatter_agent, build_search_agent
from resume_agent.taxonomy.clusters import load_cluster_map
from resume_agent.taxonomy.corrections import (
    apply_taxonomy_corrections,
    corrections_file_path,
    load_taxonomy_corrections,
)
from resume_agent.tracking.match_gap import DemandGraph, build_demand_graph
from resume_agent.tenancy.paths import resolve_tenant_path


def load_suggestion_graph(
    session: Session,
    *,
    facts_path: str,
    cluster_path: str,
) -> tuple[ProfileFacts, DemandGraph]:
    resolved_facts = resolve_tenant_path(facts_path)
    facts = (
        load_facts(resolved_facts)
        if resolved_facts.exists()
        else ProfileFacts(contact=Contact(name=""))
    )
    corrections = load_taxonomy_corrections(
        resolve_tenant_path(corrections_file_path())
    )
    graph = build_demand_graph(
        session,
        facts,
        cluster_map=apply_taxonomy_corrections(
            load_cluster_map(cluster_path),
            corrections,
        ),
        corrections=corrections,
    )
    return facts, graph


def submit_suggestion_run(
    manager: RunManager,
    *,
    engine: Any,
    github_token: str,
    context: SuggestionContext,
    facts_path: str,
    cluster_path: str,
) -> str:
    def work(reporter):
        reporter.begin(1, f"Researching {context.label}")
        with open_session(engine) as worker_session:
            facts, graph = load_suggestion_graph(
                worker_session,
                facts_path=facts_path,
                cluster_path=cluster_path,
            )
            current_context = resolve_suggestion_context(
                graph,
                kind=context.kind,
                key=context.key,
            )
            # End the graph-read transaction before the expensive concurrent
            # research phase, especially for the shared in-memory SQLite engine.
            worker_session.rollback()
            row = generate_suggestion(
                worker_session,
                context=current_context,
                search_agent=build_search_agent(),
                formatter=build_formatter_agent(),
                verify=lambda owner, name: verify_repo(
                    owner,
                    name,
                    token=github_token,
                ),
                facts=facts,
                reporter=reporter,
            )
        reporter.step(1)
        return {"kind": row.kind, "key": row.key}

    return manager.submit("suggestion", work)
