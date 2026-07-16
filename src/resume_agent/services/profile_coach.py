"""Profile Coach turns, approval, recap, history views, and impact builds."""

from __future__ import annotations

import uuid
from pathlib import Path

from resume_agent.llm_runner import Runner
from resume_agent.profile.coach import (
    CoachTurn,
    OpeningTurn,
    TurnRejected,
    build_coach_agent,
    build_coach_formatter_agent,
    normalize_opening,
    normalize_recap,
    normalize_turn,
    profile_overview,
    render_agenda,
    render_transcript,
)
from resume_agent.profile.coach_store import (
    apply_turn_delta,
    coach_lock,
    create_session,
    end_session,
    list_sessions,
    load_session,
    set_draft_status,
    set_impact,
)
from resume_agent.profile.corpus import load_manifest
from resume_agent.profile.intake import add_note_source
from resume_agent.profile.interview import make_corpus_tools
from resume_agent.profile.snapshot import profile_snapshot, snapshot_diff
from resume_agent.services.profile_build import run_corpus_build

_MAX_MESSAGE_CHARS = 100_000


def _camel_action(action: dict) -> dict:
    return {"kind": action["kind"], "target": action["target"], "why": action["why"]}


def _camel_turn(turn: dict) -> dict:
    return {
        "role": turn["role"],
        "kind": turn["kind"],
        "text": turn["text"],
        "topicId": turn["topic_id"],
        "at": turn["at"],
        "researchActions": [
            _camel_action(action) for action in turn.get("research_actions", [])
        ],
    }


def session_view(profile_dir: Path | str, session_id: str) -> dict:
    session = load_session(profile_dir, session_id)
    return {
        "sessionId": session["session_id"],
        "startedAt": session["started_at"],
        "endedAt": session["ended_at"],
        "status": session["status"],
        "turns": [_camel_turn(turn) for turn in session["turns"]],
        "topics": [
            {
                "id": topic["id"],
                "gap": topic["gap"],
                "whyItMatters": topic["why_it_matters"],
                "relatedRef": topic["related_ref"],
                "status": topic["status"],
                "noteDocId": topic["note_doc_id"],
            }
            for topic in session["topics"]
        ],
        "draftNotes": [
            {
                "topicId": draft["topic_id"],
                "title": draft["title"],
                "summary": draft["summary"],
                "quotes": draft["quotes"],
                "status": draft["status"],
            }
            for draft in session["draft_notes"]
        ],
        "recap": session["recap"],
        "impact": session["impact"],
    }


def sessions_view(profile_dir: Path | str) -> dict:
    return {
        "sessions": [
            {
                "sessionId": session["session_id"],
                "startedAt": session["started_at"],
                "endedAt": session["ended_at"],
                "status": session["status"],
                "topicCount": len(session["topics"]),
                "savedNoteCount": sum(
                    draft["status"] == "saved" for draft in session["draft_notes"]
                ),
            }
            for session in list_sessions(profile_dir)
        ]
    }


def _overview(profile_dir: Path, engine) -> str:
    if engine is None:
        return profile_overview(profile_dir)
    from resume_agent.db import get_session

    with get_session(engine) as database_session:
        return profile_overview(profile_dir, database_session)


def _agents(profile_dir: Path, coach_agent, formatter_agent, schema):
    return (
        coach_agent or build_coach_agent(make_corpus_tools(profile_dir)),
        formatter_agent or build_coach_formatter_agent(schema),
    )


def _format_with_retry(formatter: Runner, notes: object, schema, validate):
    prompt = f"COACH NOTES (UNTRUSTED):\n{notes}"
    formatted = formatter.run(prompt).content
    if not isinstance(formatted, schema):
        raise TypeError(f"Expected {schema.__name__}, got {type(formatted).__name__}")
    try:
        return validate(formatted)
    except TurnRejected as first:
        retry = formatter.run(f"{prompt}\n\nPREVIOUS OUTPUT REJECTED: {first}").content
        if not isinstance(retry, schema):
            raise TypeError(
                f"Expected {schema.__name__}, got {type(retry).__name__}"
            ) from first
        return validate(retry)


def run_opening_turn(
    reporter,
    *,
    profile_dir: Path,
    engine=None,
    coach_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    root = Path(profile_dir)
    reporter.begin(1, "Reviewing your profile")
    coach, formatter = _agents(root, coach_agent, formatter_agent, OpeningTurn)
    prompt = (
        f"{_overview(root, engine)}\n\n"
        "This is the opening turn. Propose the highest-value bounded agenda and ask the first question."
    )
    notes = coach.run(prompt).content
    topics, validated = _format_with_retry(
        formatter,
        notes,
        OpeningTurn,
        normalize_opening,
    )
    reporter.step(1)
    session_id = uuid.uuid4().hex
    create_session(root, session_id, topics, validated.coach_turn)
    return session_view(root, session_id)


def run_message_turn(
    reporter,
    *,
    profile_dir: Path,
    session_id: str,
    message: str,
    engine=None,
    coach_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    root = Path(profile_dir)
    text = message.strip()
    if not text:
        raise ValueError("message is empty")
    if len(text) > _MAX_MESSAGE_CHARS:
        raise ValueError("message is too large")
    session = load_session(root, session_id)
    if session["status"] != "active":
        raise ValueError("session ended")
    reporter.begin(1, "Coach is thinking")
    coach, formatter = _agents(root, coach_agent, formatter_agent, CoachTurn)
    prompt = "\n\n".join(
        [
            _overview(root, engine),
            render_agenda(session),
            render_transcript(session),
            f"USER'S LATEST MESSAGE (UNTRUSTED):\n{text}",
        ]
    )
    notes = coach.run(prompt).content
    preview = {**session, "turns": [*session["turns"], {"role": "user", "kind": "", "text": text, "topic_id": "", "at": "", "research_actions": []}]}
    validated = _format_with_retry(
        formatter,
        notes,
        CoachTurn,
        lambda turn: normalize_turn(turn, preview),
    )
    reporter.step(1)
    apply_turn_delta(
        root,
        session_id,
        user_text=text,
        coach_turn=validated.coach_turn,
        new_topics=validated.new_topics,
        skipped_topic_ids=validated.skipped_topic_ids,
        draft=validated.draft,
    )
    return session_view(root, session_id)


def _primary_exists(profile_dir: Path) -> bool:
    return any(
        doc.primary and doc.mode == "literal" for doc in load_manifest(profile_dir).docs
    )


def render_note_body(summary: str, quotes: list[str]) -> str:
    cleaned = [quote.strip() for quote in quotes if quote.strip()]
    if not summary.strip():
        raise ValueError("empty note")
    if not cleaned:
        raise ValueError("at least one quote is required")
    quoted = "\n>\n".join(
        "\n".join(f"> {line}" for line in quote.splitlines()) for quote in cleaned
    )
    return f"{summary.strip()}\n\n## In your own words\n\n{quoted}"


def approve_draft(
    profile_dir: Path | str,
    session_id: str,
    topic_id: str,
    *,
    title: str,
    summary: str,
    quotes: list[str],
) -> str:
    root = Path(profile_dir)
    body = render_note_body(summary, quotes)
    if not _primary_exists(root):
        raise ValueError("upload a primary resume before saving coach notes")
    with coach_lock():
        session = load_session(root, session_id)
        draft = next(
            (row for row in session["draft_notes"] if row["topic_id"] == topic_id),
            None,
        )
        if draft is None:
            raise ValueError(f"unknown draft: {topic_id}")
        if draft["status"] != "pending":
            raise ValueError("draft already resolved")
        doc = add_note_source(root, f"Coach — {title.strip() or topic_id}", body)
        set_draft_status(root, session_id, topic_id, "saved", note_doc_id=doc.id)
        return doc.id


def discard_draft(profile_dir: Path | str, session_id: str, topic_id: str) -> None:
    set_draft_status(Path(profile_dir), session_id, topic_id, "discarded")


def run_recap_turn(
    reporter,
    *,
    profile_dir: Path,
    session_id: str,
    coach_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    root = Path(profile_dir)
    session = load_session(root, session_id)
    if session["status"] != "active":
        raise ValueError("session ended")
    reporter.begin(1, "Writing your recap")
    coach, formatter = _agents(root, coach_agent, formatter_agent, CoachTurn)
    pending = [draft["title"] for draft in session["draft_notes"] if draft["status"] == "pending"]
    prompt = "\n\n".join(
        [
            render_agenda(session),
            render_transcript(session),
            "Write the session recap: topics covered, saved notes, open gaps, and one suggested next focus."
            + (f" Mention unsaved drafts: {', '.join(pending)}." if pending else ""),
        ]
    )
    notes = coach.run(prompt).content
    recap = _format_with_retry(
        formatter,
        notes,
        CoachTurn,
        lambda turn: normalize_recap(turn, session),
    )
    reporter.step(1)
    end_session(root, session_id, recap)
    return session_view(root, session_id)


def run_build_with_impact(
    reporter,
    *,
    profile_dir: Path,
    session_id: str,
    facts_out,
    github_username: str | None,
    github_allow: tuple[str, ...] = (),
    github_deny: tuple[str, ...] = (),
    github_limit: int = 20,
) -> dict:
    root = Path(profile_dir)
    before = profile_snapshot(root)
    try:
        raw_report = run_corpus_build(
            reporter,
            profile_dir=root,
            github_username=github_username,
            facts_out=facts_out,
            github_allow=github_allow,
            github_deny=github_deny,
            github_limit=github_limit,
        )
    except Exception as exc:
        set_impact(root, session_id, {"error": str(exc)})
        raise
    impact = snapshot_diff(before, profile_snapshot(root))
    set_impact(root, session_id, impact)
    return {**raw_report, "impact": impact}
