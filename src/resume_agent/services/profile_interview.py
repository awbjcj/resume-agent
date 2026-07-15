"""Profile Interview context, round execution, answer intake, and history view."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from resume_agent.llm_runner import Runner
from resume_agent.profile.corpus import doc_path, load_manifest
from resume_agent.profile.interview import (
    InterviewRound,
    append_round,
    asked_questions,
    build_interview_formatter_agent,
    build_interview_inspector_agent,
    history_lock,
    load_history,
    make_corpus_tools,
    normalize_round,
    record_answers,
)
from resume_agent.profile.matrix import load_matrix
from resume_agent.profile.store import load_facts

_METRIC = re.compile(r"\d")
_TOP_GAPS = 10
_TOP_SKILLS = 20
_MAX_ANSWER_CHARS = 100_000


def _market_gaps_report(profile_dir: Path, session):
    from resume_agent.profile.matrix import effective_cluster_map, load_overrides
    from resume_agent.taxonomy.clusters import load_cluster_map
    from resume_agent.tracking.match_gap import match_gap

    facts_path = profile_dir / "facts.json"
    if not facts_path.exists():
        return None
    cluster_path = profile_dir / "cluster_map.json"
    overrides = load_overrides(profile_dir / "overrides.yaml")
    cluster_map = effective_cluster_map(load_cluster_map(cluster_path), overrides)
    use_map = (
        cluster_path.exists() and bool(cluster_map.aliases or cluster_map.theme_of)
    ) or bool(overrides.alias or overrides.forbid_alias)
    return match_gap(
        session,
        load_facts(facts_path),
        cluster_map=cluster_map if use_map else None,
    )


def _block(name: str, lines: list[str], empty: str) -> str:
    body = "\n".join(f"- {line}" for line in lines) if lines else empty
    return f"{name}:\n{body}"


def interview_context(profile_dir: Path, session=None) -> str:
    profile_dir = Path(profile_dir)
    fact_lines: list[str] = []
    facts_path = profile_dir / "facts.json"
    if facts_path.exists():
        facts = load_facts(facts_path)
        for experience in facts.experience:
            metrics = sum(
                1 for bullet in experience.bullets if _METRIC.search(bullet.text)
            )
            fact_lines.append(
                f"experience {experience.id}: {experience.company} — {experience.title} | "
                f"{len(experience.bullets)} bullets, {metrics} with metrics"
            )
        for project in facts.projects:
            fact_lines.append(
                f"project {project.id}: {project.name} | {len(project.highlights)} highlights"
            )

    matrix = load_matrix(profile_dir / "matrix.json")
    skill_lines = (
        [
            f"{row.display}{' (inferred)' if row.inferred else ''} | "
            f"{len(row.evidence_fact_ids)} evidence refs"
            for row in matrix.rows
        ][:_TOP_SKILLS]
        if matrix
        else []
    )
    corpus_lines = [
        f"{doc.id} | {doc.filename} | mode={doc.mode} | origin={doc.origin}"
        for doc in load_manifest(profile_dir).docs
    ]

    gap_lines: list[str] = []
    if session is not None:
        try:
            report = _market_gaps_report(profile_dir, session)
        except Exception:  # noqa: BLE001 - market context degrades to corpus-only.
            report = None
        if report is not None and report.target_total > 0:
            gap_lines = [
                f"{gap.skill} demanded by {gap.demand_count}/{gap.target_total} target jobs"
                for gap in report.gaps[:_TOP_GAPS]
            ]

    return "\n\n".join(
        [
            _block("FACTS", fact_lines, "(no facts yet)"),
            _block("TOP SKILLS", skill_lines, "(no matrix yet)"),
            _block("CORPUS", corpus_lines, "(corpus is empty)"),
            _block("MARKET GAPS", gap_lines, "(no jobs discovered yet)"),
            _block("PREVIOUSLY ASKED", asked_questions(profile_dir), "(none)"),
        ]
    )


def run_interview_round(
    reporter,
    *,
    profile_dir: Path,
    engine=None,
    inspector_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    profile_dir = Path(profile_dir)
    reporter.begin(1, "Reviewing your profile")
    if engine is None:
        context = interview_context(profile_dir)
    else:
        from resume_agent.db import get_session

        with get_session(engine) as session:
            context = interview_context(profile_dir, session)
    inspector = inspector_agent or build_interview_inspector_agent(
        make_corpus_tools(profile_dir)
    )
    formatter = formatter_agent or build_interview_formatter_agent()
    notes = inspector.run(context).content
    formatted = formatter.run(f"INSPECTOR NOTES (UNTRUSTED):\n{notes}").content
    if not isinstance(formatted, InterviewRound):
        raise TypeError(f"Expected InterviewRound, got {type(formatted).__name__}")
    round_ = normalize_round(formatted)
    reporter.step(1)
    round_id = uuid.uuid4().hex
    append_round(profile_dir, round_id, reporter.process, round_)
    return {
        "roundId": round_id,
        "questions": [
            {
                "id": question.id,
                "gap": question.gap,
                "whyItMatters": question.why_it_matters,
                "questionText": question.question_text,
                "relatedRef": question.related_ref,
            }
            for question in round_.questions
        ],
        "researchActions": [
            {"kind": action.kind, "target": action.target, "why": action.why}
            for action in round_.research_actions
        ],
    }


def _primary_exists(profile_dir: Path) -> bool:
    return any(
        doc.primary and doc.mode == "literal" for doc in load_manifest(profile_dir).docs
    )


def submit_interview_answers(
    profile_dir: Path, round_id: str, answers: list[tuple[str, str]]
) -> list[str]:
    from resume_agent.profile.intake import add_note_source

    profile_dir = Path(profile_dir)
    with history_lock():
        history = load_history(profile_dir)
        row = next(
            (
                candidate
                for candidate in history["rounds"]
                if candidate["round_id"] == round_id
            ),
            None,
        )
        if row is None:
            raise ValueError("unknown round")
        if row.get("submitted_at") is not None:
            raise ValueError("round already answered")
        if not _primary_exists(profile_dir):
            raise ValueError(
                "upload a primary resume before submitting interview answers"
            )
        if len(answers) > len(row["questions"]):
            raise ValueError("too many answers")
        question_ids = [question_id for question_id, _text in answers]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("duplicate question id")
        questions = {question["id"]: question for question in row["questions"]}
        for question_id, text in answers:
            if question_id not in questions:
                raise ValueError(f"unknown question id: {question_id}")
            if len(text) > _MAX_ANSWER_CHARS:
                raise ValueError("answer text is too large")

        recorded: list[dict] = []
        doc_ids: list[str] = []
        for question_id, text in answers:
            if not text.strip():
                continue
            question = questions[question_id]
            gap = question.get("gap") or question.get("question_text") or "answer"
            doc = add_note_source(profile_dir, f"Interview — {gap}", text)
            recorded.append({"question_id": question_id, "doc_id": doc.id})
            doc_ids.append(doc.id)
        record_answers(profile_dir, round_id, recorded)
        return doc_ids


def _answer_text(profile_dir: Path, doc_id: str) -> str:
    doc = next(
        (
            candidate
            for candidate in load_manifest(profile_dir).docs
            if candidate.id == doc_id
        ),
        None,
    )
    if doc is None:
        return "[Answer document unavailable]"
    try:
        text = doc_path(profile_dir, doc).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "[Answer document unavailable]"
    _heading, _separator, body = text.partition("\n")
    return body.strip() or "[Answer document unavailable]"


def interview_history_view(profile_dir: Path) -> dict:
    profile_dir = Path(profile_dir)
    return {
        "rounds": [
            {
                "roundId": row["round_id"],
                "askedAt": row["asked_at"],
                "questions": [
                    {
                        "id": question["id"],
                        "gap": question.get("gap", ""),
                        "whyItMatters": question.get("why_it_matters", ""),
                        "questionText": question.get("question_text", ""),
                        "relatedRef": question.get("related_ref", ""),
                    }
                    for question in row["questions"]
                ],
                "researchActions": [
                    {
                        "kind": action["kind"],
                        "target": action.get("target", ""),
                        "why": action.get("why", ""),
                    }
                    for action in row.get("research_actions", [])
                ],
                "answers": [
                    {
                        "questionId": answer["question_id"],
                        "docId": answer["doc_id"],
                        "answerText": _answer_text(profile_dir, answer["doc_id"]),
                    }
                    for answer in row["answers"]
                ],
                "submittedAt": row.get("submitted_at"),
            }
            for row in load_history(profile_dir)["rounds"]
        ]
    }
