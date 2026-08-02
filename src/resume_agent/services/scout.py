"""Discovery Scout turn orchestration and deterministic write boundaries."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import cast

from resume_agent.api.schemas.config import SearchConfigDoc
from resume_agent.concurrency import gather_isolated
from resume_agent.discovery.scout import (
    MESSAGE_CHAR_CAP,
    ScoutProposalDraft,
    ScoutTurnDraft,
    SuggestionKind,
    ValidatedScoutTurn,
    build_scout_agent,
    build_scout_formatter_agent,
    make_check_source_tool,
    normalize_recap,
    normalize_turn,
)
from resume_agent.discovery.scout_models import Citation
from resume_agent.discovery.scout_store import (
    ScoutProposal,
    ScoutTurnRecord,
    SourcePayload,
    TermPayload,
    apply_turn_delta,
    create_session_from_turn,
    end_session,
    list_sessions,
    load_session,
    scout_lock,
    set_proposal_status,
)
from resume_agent.llm_runner import Runner, UnparsedAgentOutput
from resume_agent.services.config_store import ConfigStore
from resume_agent.services.scout_context import (
    _EXISTING_FIELD,
    _candidate_keys,
    _company_key,
    _existing_keys,
    _existing_terms,
    _load_connectors,
    render_goal,
    render_ledger,
    render_transcript,
    scout_context,
    session_source_keys,
    session_term_keys,
)
from resume_agent.services.sources import SourcePreview, add_source, preview_source
from resume_agent.sessions.stream import Notice, NullSink, StreamSink
from resume_agent.sessions.turns import TurnRejected, format_with_retry, persona_output

logger = logging.getLogger(__name__)

_TURN_OMITTED_NOTICE = "Some turn details could not be read, so no proposals were attached."
_RECAP_OMITTED_NOTICE = "Some recap details could not be read."
_CHECK_ERROR_CAP = 500
_CHECK_RANK = {
    "validated": 0,
    "unverified": 1,
    "new": 2,
    "avoid": 3,
    "failed": 4,
    "duplicate": 5,
}


def _clean_message(message: str) -> str:
    text = message.strip()
    if not text:
        raise ValueError("message is empty")
    if len(text) > MESSAGE_CHAR_CAP:
        raise ValueError("message is too large")
    return text


def _source_payload(row: ScoutProposalDraft) -> SourcePayload:
    assert row.source is not None
    return SourcePayload(company=row.source.company, url=row.source.url)


def _term_payload(row: ScoutProposalDraft) -> TermPayload:
    assert row.term is not None
    return TermPayload(value=row.term.value, term_kind=cast(SuggestionKind, row.term.term_kind))


def _proposal(row: ScoutProposalDraft) -> ScoutProposal:
    is_source = row.kind == "source"
    return ScoutProposal(
        kind="source" if is_source else "search_term",
        source=_source_payload(row) if is_source else None,
        term=None if is_source else _term_payload(row),
        reason=row.reason,
        fit_score=row.fit_score,
        citations=[Citation.model_validate(citation.model_dump()) for citation in row.citations],
        check="avoid" if row.disposition == "avoid" else "new",
    )


def _rank(proposals: list[ScoutProposal]) -> list[ScoutProposal]:
    return sorted(
        proposals,
        key=lambda row: (
            _CHECK_RANK[row.check],
            -(row.fit_score if row.fit_score is not None else -1),
        ),
    )


def _post_process(
    reporter,
    drafts: list[ScoutProposalDraft],
    *,
    session: dict,
    connectors_path: str,
    search_path: str,
) -> list[ScoutProposal]:
    existing_sources = _existing_keys(_load_connectors(connectors_path))
    prior_sources = session_source_keys(session)
    existing_terms = _existing_terms(search_path)
    prior_terms = session_term_keys(session)
    seen_sources: set[str] = set()
    seen_terms: set[str] = set()
    proposals: list[ScoutProposal] = []
    fresh: list[tuple[int, ScoutProposal]] = []

    for draft in drafts:
        proposal = _proposal(draft)
        if proposal.kind == "source":
            assert proposal.source is not None
            company_key = _company_key(proposal.source.company)
            url_keys = _candidate_keys(proposal.source.url) if proposal.source.url else set()
            keys = {company_key, *url_keys}
            if proposal.check == "avoid":
                if keys & (prior_sources | seen_sources):
                    proposal = proposal.model_copy(update={"check": "duplicate"})
                seen_sources.update(keys)
            elif url_keys & existing_sources or keys & (prior_sources | seen_sources):
                proposal = proposal.model_copy(update={"check": "duplicate"})
            else:
                seen_sources.update(keys)
                fresh.append((len(proposals), proposal))
        else:
            assert proposal.term is not None
            destination = _EXISTING_FIELD[proposal.term.term_kind]
            key = f"{destination}:{proposal.term.value.casefold()}"
            if proposal.term.value.casefold() in existing_terms[destination] or key in prior_terms or key in seen_terms:
                proposal = proposal.model_copy(update={"check": "duplicate"})
            else:
                seen_terms.add(key)
        proposals.append(proposal)

    async def probe_all():
        async def probe(item: tuple[int, ScoutProposal]) -> SourcePreview:
            source = item[1].source
            assert source is not None
            return await asyncio.to_thread(
                preview_source,
                source.url,
                search_path=search_path,
                browser=False,
            )

        return await gather_isolated(
            fresh,
            probe,
            on_complete=reporter.step,
            checkpoint=reporter.checkpoint,
        )

    results = asyncio.run(probe_all()) if fresh else []
    for (index, proposal), result in zip(fresh, results, strict=True):
        assert proposal.source is not None
        preview = result.value if result.ok else None
        if preview is not None and preview.ok:
            check = "validated"
        elif preview is not None and preview.error_code == "ATS_NOT_DETECTED":
            check = "unverified"
        else:
            check = "failed"
            if preview is None:
                preview = SourcePreview(
                    ok=False,
                    url=proposal.source.url,
                    error=f"Validation failed ({type(result.error).__name__}).",
                    error_code="VALIDATION_ERROR",
                )
        source = proposal.source.model_copy(
            update={
                "url": preview.url,
                "ats": preview.kind,
                "token": preview.token,
                "role_count": preview.role_count,
                "error_code": preview.error_code,
            }
        )
        proposals[index] = proposal.model_copy(
            update={
                "source": source,
                "check": check,
                "check_error": (preview.error or "")[:_CHECK_ERROR_CAP] if check == "failed" else "",
            }
        )
    return _rank(proposals)


def _run_turn(
    reporter,
    *,
    workspace_root: Path,
    session_id: str,
    message: str,
    connectors_path: str,
    search_path: str,
    profile_dir: Path,
    browser_enabled: bool,
    start: bool,
    scout_agent: Runner | None,
    formatter_agent: Runner | None,
    sink: StreamSink | None,
) -> dict:
    text = _clean_message(message)
    session = (
        {"goal": text, "turns": [], "proposals": [], "status": "active"}
        if start
        else load_session(workspace_root, session_id)
    )
    if session["status"] != "active":
        raise ValueError("session ended")
    reporter.begin(1, "Discovery Scout is researching")
    researcher = scout_agent or build_scout_agent(make_check_source_tool(search_path))
    formatter = formatter_agent or build_scout_formatter_agent()
    prompt = "\n\n".join(
        [
            scout_context(connectors_path, search_path, profile_dir),
            render_goal(session),
            render_ledger(session),
            render_transcript(session),
            f"USER'S LATEST MESSAGE (UNTRUSTED):\n{text}",
        ]
    )
    output_sink = sink or NullSink()
    prose, notes = persona_output(
        researcher, prompt, output_sink, reporter, source="scout notes"
    )
    preview = {
        **session,
        "turns": [
            *session.get("turns", []),
            {"role": "user", "text": text, "kind": "", "notice": ""},
        ],
    }
    try:
        validated = format_with_retry(
            formatter,
            notes,
            ScoutTurnDraft,
            lambda turn, strict: normalize_turn(turn, preview, strict=strict),
            label="SCOUT NOTES",
        )
    except (TurnRejected, UnparsedAgentOutput) as exc:
        # UnparsedAgentOutput is how agno reports "the provider did not return
        # the schema" -- a truncated body, a refusal, or an error body dressed
        # as content. It is a TypeError, so it used to escape this fallback and
        # fail the run, deleting a reply the user had already watched stream in.
        # A formatter that cannot be parsed is a formatter that failed; degrade
        # the same way, and log the diagnostic so the provider fault stays
        # visible instead of being flattened into the notice.
        fallback = prose or getattr(exc, "fallback_text", "")
        if not fallback:
            raise
        if isinstance(exc, UnparsedAgentOutput):
            logger.warning("Scout formatter returned unusable output: %s", exc)
        validated = ValidatedScoutTurn(message=fallback, notice=_TURN_OMITTED_NOTICE)
    if prose:
        validated.message = prose
    proposals = _post_process(
        reporter,
        validated.proposals,
        session=session,
        connectors_path=connectors_path,
        search_path=search_path,
    )
    reporter.checkpoint()
    turn = ScoutTurnRecord(
        role="scout",
        kind="reply",
        text=validated.message,
        notice=validated.notice,
    )
    if start:
        create_session_from_turn(
            workspace_root,
            session_id,
            goal=validated.goal_update or text,
            user_text=text,
            scout_turn=turn,
            proposals=proposals,
        )
    else:
        apply_turn_delta(
            workspace_root,
            session_id,
            user_text=text,
            scout_turn=turn,
            proposals=proposals,
            goal_update=validated.goal_update,
        )
    if validated.notice:
        output_sink.emit(Notice(validated.notice))
    return session_view(workspace_root, session_id, browser_enabled=browser_enabled)


def run_start_turn(
    reporter,
    *,
    workspace_root: Path,
    session_id: str,
    message: str,
    connectors_path: str,
    search_path: str,
    profile_dir: Path,
    browser_enabled: bool,
    scout_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
    sink: StreamSink | None = None,
) -> dict:
    return _run_turn(
        reporter,
        workspace_root=workspace_root,
        session_id=session_id,
        message=message,
        connectors_path=connectors_path,
        search_path=search_path,
        profile_dir=profile_dir,
        browser_enabled=browser_enabled,
        start=True,
        scout_agent=scout_agent,
        formatter_agent=formatter_agent,
        sink=sink,
    )


def run_message_turn(
    reporter,
    *,
    workspace_root: Path,
    session_id: str,
    message: str,
    connectors_path: str,
    search_path: str,
    profile_dir: Path,
    browser_enabled: bool,
    scout_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
    sink: StreamSink | None = None,
) -> dict:
    return _run_turn(
        reporter,
        workspace_root=workspace_root,
        session_id=session_id,
        message=message,
        connectors_path=connectors_path,
        search_path=search_path,
        profile_dir=profile_dir,
        browser_enabled=browser_enabled,
        start=False,
        scout_agent=scout_agent,
        formatter_agent=formatter_agent,
        sink=sink,
    )


def run_recap_turn(
    reporter,
    *,
    workspace_root: Path,
    session_id: str,
    connectors_path: str,
    search_path: str,
    profile_dir: Path,
    browser_enabled: bool,
    scout_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
    sink: StreamSink | None = None,
) -> dict:
    session = load_session(workspace_root, session_id)
    if session["status"] != "active":
        raise ValueError("session ended")
    reporter.begin(1, "Discovery Scout is writing a recap")
    researcher = scout_agent or build_scout_agent(make_check_source_tool(search_path))
    formatter = formatter_agent or build_scout_formatter_agent()
    prompt = "\n\n".join(
        [
            scout_context(connectors_path, search_path, profile_dir),
            render_goal(session),
            render_ledger(session),
            render_transcript(session),
            "Write a recap with added, dismissed, and still-pending counts and labels.",
        ]
    )
    output_sink = sink or NullSink()
    prose, notes = persona_output(
        researcher, prompt, output_sink, reporter, source="scout notes"
    )
    notice = ""
    try:
        recap = format_with_retry(
            formatter,
            notes,
            ScoutTurnDraft,
            lambda turn, strict: normalize_recap(turn, session, strict),
            label="SCOUT NOTES",
        )
    except TurnRejected as exc:
        recap = prose or exc.fallback_text
        if not recap:
            raise
        notice = _RECAP_OMITTED_NOTICE
    if prose:
        recap = prose
    reporter.checkpoint()
    end_session(workspace_root, session_id, recap, notice=notice)
    if notice:
        output_sink.emit(Notice(notice))
    return session_view(workspace_root, session_id, browser_enabled=browser_enabled)


def _camel_source(source: dict | None) -> dict | None:
    if source is None:
        return None
    return {
        "company": source["company"],
        "url": source["url"],
        "ats": source["ats"],
        "token": source["token"],
        "roleCount": source["role_count"],
        "errorCode": source["error_code"],
    }


def _camel_term(term: dict | None) -> dict | None:
    if term is None:
        return None
    return {"value": term["value"], "termKind": term["term_kind"]}


def _camel_proposal(proposal: dict) -> dict:
    return {
        "id": proposal["id"],
        "kind": proposal["kind"],
        "source": _camel_source(proposal["source"]),
        "term": _camel_term(proposal["term"]),
        "reason": proposal["reason"],
        "fitScore": proposal["fit_score"],
        "citations": proposal["citations"],
        "check": proposal["check"],
        "checkError": proposal["check_error"],
        "status": proposal["status"],
        "dismissReason": proposal["dismiss_reason"],
        "resolvedAt": proposal["resolved_at"],
    }


def _camel_turn(turn: dict) -> dict:
    return {
        "role": turn["role"],
        "kind": turn["kind"],
        "text": turn["text"],
        "at": turn["at"],
        "notice": turn["notice"],
        "proposalIds": turn["proposal_ids"],
    }


def session_view(
    workspace_root: Path | str, session_id: str, *, browser_enabled: bool
) -> dict:
    session = load_session(workspace_root, session_id)
    return {
        "sessionId": session["session_id"],
        "startedAt": session["started_at"],
        "endedAt": session["ended_at"],
        "status": session["status"],
        "archivedAt": session["archived_at"],
        "goal": session["goal"],
        "turns": [_camel_turn(turn) for turn in session["turns"]],
        "proposals": [_camel_proposal(row) for row in session["proposals"]],
        "recap": session["recap"],
        "scrapeAvailable": browser_enabled,
        "scrapeUnavailableReason": None if browser_enabled else "Scrape targets require a local browser.",
    }


def sessions_view(
    workspace_root: Path | str,
    *,
    include_archived: bool = False,
    status: str | None = None,
) -> dict:
    rows = list_sessions(workspace_root, include_archived=include_archived)
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return {
        "sessions": [
            {
                "sessionId": row["session_id"],
                "startedAt": row["started_at"],
                "endedAt": row["ended_at"],
                "status": row["status"],
                "archivedAt": row["archived_at"],
                "goal": row["goal"],
                "proposalCount": len(row["proposals"]),
                "pendingCount": sum(item["status"] == "pending" for item in row["proposals"]),
                "addedCount": sum(item["status"] == "added" for item in row["proposals"]),
                "dismissedCount": sum(item["status"] == "dismissed" for item in row["proposals"]),
            }
            for row in rows
        ]
    }


def _pending_proposal(session: dict, proposal_id: str) -> dict:
    proposal = next((row for row in session["proposals"] if row["id"] == proposal_id), None)
    if proposal is None:
        raise ValueError(f"unknown proposal: {proposal_id}")
    if proposal["status"] != "pending":
        raise ValueError("proposal already resolved")
    return proposal


def approve_proposal(
    workspace_root: Path | str,
    session_id: str,
    proposal_id: str,
    *,
    config_store: ConfigStore,
    connectors_path: str,
    search_path: str,
    browser_enabled: bool,
) -> dict:
    with scout_lock():
        proposal = _pending_proposal(load_session(workspace_root, session_id), proposal_id)
        if proposal["kind"] == "source":
            if proposal["check"] not in {"validated", "unverified"}:
                raise ValueError(f"source proposal is not approvable: {proposal['check']}")
            if proposal["check"] == "unverified" and not browser_enabled:
                raise ValueError("scrape target requires a local browser")
            source = proposal["source"]
            assert source is not None
            if not (_candidate_keys(source["url"]) & _existing_keys(_load_connectors(connectors_path))):
                add_source(
                    provider="scrape" if proposal["check"] == "unverified" else "auto",
                    url=source["url"],
                    label=source["company"],
                    country="com",
                    connectors_path=connectors_path,
                    search_path=search_path,
                )
        else:
            term = proposal["term"]
            assert term is not None
            document = cast(SearchConfigDoc, config_store.get("search"))
            field = _EXISTING_FIELD[term["term_kind"]]
            values = list(getattr(document, field))
            if term["value"].casefold() not in {value.casefold() for value in values}:
                config_store.put(
                    "search",
                    document.model_copy(update={field: [*values, term["value"]]}),
                )
        set_proposal_status(workspace_root, session_id, proposal_id, "added")
    return session_view(workspace_root, session_id, browser_enabled=browser_enabled)


def dismiss_proposal(
    workspace_root: Path | str,
    session_id: str,
    proposal_id: str,
    *,
    reason: str,
    browser_enabled: bool,
) -> dict:
    cleaned = reason.strip()
    if len(cleaned) > 200:
        raise ValueError("dismissal reason must contain at most 200 characters")
    with scout_lock():
        set_proposal_status(
            workspace_root,
            session_id,
            proposal_id,
            "dismissed",
            reason=cleaned,
        )
    return session_view(workspace_root, session_id, browser_enabled=browser_enabled)
