"""Build, ground, persist, and load job-scoped role preparation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from sqlmodel import Session, col, select

from resume_agent.company_intelligence.models import CompanyIntelligenceEvidence
from resume_agent.role_preparation.models import (
    RolePreparationAsk,
    RolePreparationBrief,
    RolePreparationCompetency,
    RolePreparationConcern,
    RolePreparationDraft,
    RolePreparationInputs,
    RolePreparationQuestion,
)
from resume_agent.llm_runner import expect_schema
from resume_agent.public_sources import retain_frozen_citations
from resume_agent.services.company_intelligence import load_company_intelligence
from resume_agent.tracking.event_vocab import INTERVIEW_KINDS
from resume_agent.tracking.tables import (
    Application,
    ApplicationEvent,
    CoverLetter,
    Job,
    ResumeVersion,
    RolePreparationBriefRow,
    utcnow,
)

ROLE_PREPARATION_CAVEAT = (
    "Likely questions and preparation suggestions are planning aids, not claims "
    "about the employer's actual interview process. Verify important assumptions."
)
_WRITE_LOCK = Lock()
_MAX_SIGNALS = 8
_MAX_SIGNAL_TEXT = 2_000
_WORDS = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_GENERIC_STORY_WORDS = frozenset(
    {"example", "experience", "from", "project", "resume", "role", "team", "the", "use", "work"}
)


@dataclass(frozen=True)
class RolePreparationResource:
    state: Literal["unavailable", "empty", "ready"]
    reason: Literal["missing_job_description", "company_intelligence_required"] | None = None
    brief: RolePreparationBrief | None = None
    inputs_changed: bool = False


def role_preparation_unavailable_reason(
    session: Session, job: Job
) -> Literal["missing_job_description", "company_intelligence_required"] | None:
    if not job.jd_text.strip():
        return "missing_job_description"
    evidence = load_company_intelligence(session, job.company)
    if evidence is None:
        return "company_intelligence_required"
    return None


def _latest_resume(session: Session, job_id: int) -> ResumeVersion | None:
    return session.exec(
        select(ResumeVersion)
        .where(ResumeVersion.job_id == job_id)
        .order_by(col(ResumeVersion.created_at).desc(), col(ResumeVersion.id).desc())
    ).first()


def _build_role_preparation_inputs_for_job(
    session: Session,
    job: Job,
    evidence: CompanyIntelligenceEvidence,
) -> RolePreparationInputs:
    job_id = job.id or 0
    application = session.exec(
        select(Application).where(Application.job_id == job_id)
    ).first()
    resume = None
    cover_letter = None
    if application is not None and application.resume_version_id is not None:
        candidate = session.get(ResumeVersion, application.resume_version_id)
        if candidate is not None and candidate.job_id == job_id:
            resume = candidate
    if resume is None:
        resume = _latest_resume(session, job_id)
    if application is not None and application.cover_letter_id is not None:
        candidate_letter = session.get(CoverLetter, application.cover_letter_id)
        if candidate_letter is not None and candidate_letter.job_id == job_id:
            cover_letter = candidate_letter

    events: list[ApplicationEvent] = []
    if application is not None and application.id is not None:
        events = list(
            session.exec(
                select(ApplicationEvent)
                .where(
                    ApplicationEvent.application_id == application.id,
                    col(ApplicationEvent.kind).in_(INTERVIEW_KINDS),
                )
                .order_by(
                    col(ApplicationEvent.occurred_at).desc(),
                    col(ApplicationEvent.created_at).desc(),
                )
                .limit(_MAX_SIGNALS)
            ).all()
        )
    signals = [
        {
            "id": event.id,
            "kind": event.kind,
            "occurred_at": event.occurred_at.isoformat()
            if event.occurred_at
            else None,
            "interviewers": (event.interviewers or "").strip(),
            "result": event.result,
            "notes": (event.notes or "").strip()[:_MAX_SIGNAL_TEXT],
            "reflection": (event.reflection or "").strip()[:_MAX_SIGNAL_TEXT],
        }
        for event in events
        if any(
            (
                (event.interviewers or "").strip(),
                (event.notes or "").strip(),
                (event.reflection or "").strip(),
                event.result != "pending",
            )
        )
    ]
    return RolePreparationInputs(
        job_id=job_id,
        company=job.company or "",
        title=job.title or "",
        jd_text=job.jd_text,
        company_intelligence=evidence.model_dump(mode="json"),
        company_intelligence_version_id=evidence.version_id,
        company_intelligence_version_number=evidence.version_number,
        resume_version_id=resume.id if resume is not None else None,
        resume_content=(resume.content_json or {}) if resume is not None else {},
        cover_letter_id=cover_letter.id if cover_letter is not None else None,
        cover_letter_content=(
            cover_letter.content_json or {} if cover_letter is not None else {}
        ),
        application_status=application.status if application is not None else "ready",
        interview_signals=signals,
        signal_event_ids=[
            event.id for event in events if event.id is not None
        ],
    )


def build_role_preparation_inputs(
    session: Session, job_id: int
) -> RolePreparationInputs | None:
    job = session.get(Job, job_id)
    if job is None or not job.jd_text.strip():
        return None
    evidence = load_company_intelligence(session, job.company)
    if evidence is None:
        return None
    return _build_role_preparation_inputs_for_job(session, job, evidence)


def role_preparation_input_fingerprint(inputs: RolePreparationInputs) -> str:
    payload = inputs.model_dump(mode="json", exclude={"schema_version"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _allowed_citations(inputs: RolePreparationInputs) -> set[str]:
    raw = inputs.company_intelligence.get("sources", [])
    return {
        str(item.get("url", ""))
        for item in raw
        if isinstance(item, dict) and str(item.get("url", "")).startswith(("http://", "https://"))
    }


def _grounded_items(items, *, allowed: set[str], text_field: str):
    grounded = []
    for item in items:
        if not getattr(item, text_field).strip():
            continue
        requested = list(item.company_citations)
        citations = retain_frozen_citations(requested, allowed)
        if requested and not citations:
            continue
        grounded.append(
            item.model_copy(update={"company_citations": citations})
        )
    return grounded


def _string_leaves(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _string_leaves(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _string_leaves(nested)


def _resume_phrases(resume_content: dict) -> set[str]:
    phrases: set[str] = set()
    for value in _string_leaves(resume_content):
        words = _WORDS.findall(value.casefold())
        for size in range(2, min(6, len(words)) + 1):
            for start in range(len(words) - size + 1):
                phrase = words[start : start + size]
                meaningful = [word for word in phrase if word not in _GENERIC_STORY_WORDS]
                if len(meaningful) >= 2:
                    phrases.add(" ".join(phrase))
    return phrases


def _story_is_grounded(story_prompt: str, resume_phrases: set[str]) -> bool:
    prompt_words = _WORDS.findall(story_prompt.casefold())
    if not prompt_words:
        return False
    return any(
        " ".join(prompt_words[start : start + size]) in resume_phrases
        for size in range(2, min(6, len(prompt_words)) + 1)
        for start in range(len(prompt_words) - size + 1)
    )


def _ground_draft(
    draft: RolePreparationDraft, inputs: RolePreparationInputs
) -> RolePreparationDraft:
    allowed = _allowed_citations(inputs)
    competencies: list[RolePreparationCompetency] = _grounded_items(
        draft.competencies,
        allowed=allowed,
        text_field="name",
    )
    questions: list[RolePreparationQuestion] = _grounded_items(
        draft.likely_questions,
        allowed=allowed,
        text_field="question",
    )
    resume_phrases = _resume_phrases(inputs.resume_content)
    questions = [
        question.model_copy(
            update={
                "story_prompt": question.story_prompt.strip()
                if _story_is_grounded(question.story_prompt, resume_phrases)
                else ""
            }
        )
        for question in questions
    ]
    concerns: list[RolePreparationConcern] = _grounded_items(
        draft.concerns,
        allowed=allowed,
        text_field="concern",
    )
    questions_to_ask: list[RolePreparationAsk] = _grounded_items(
        draft.questions_to_ask,
        allowed=allowed,
        text_field="text",
    )
    recruiter_questions: list[RolePreparationAsk] = _grounded_items(
        draft.recruiter_verification_questions,
        allowed=allowed,
        text_field="text",
    )
    if not questions and not questions_to_ask and not recruiter_questions:
        raise ValueError("role preparation contained no usable questions")
    return draft.model_copy(
        update={
            "positioning_summary": draft.positioning_summary.strip(),
            "competencies": competencies,
            "likely_questions": questions,
            "concerns": concerns,
            "questions_to_ask": questions_to_ask,
            "recruiter_verification_questions": recruiter_questions,
            "prior_round_focus": [
                value.strip() for value in draft.prior_round_focus if value.strip()
            ],
        }
    )


def load_role_preparation_brief(
    session: Session, job_id: int
) -> RolePreparationBrief | None:
    row = session.exec(
        select(RolePreparationBriefRow).where(RolePreparationBriefRow.job_id == job_id)
    ).first()
    if row is None:
        return None
    try:
        return RolePreparationBrief.model_validate(row.brief_json)
    except (TypeError, ValueError):
        return None


def generate_role_preparation_brief(
    session: Session,
    *,
    job_id: int,
    formatter=None,
    reporter=None,
    now: datetime | None = None,
) -> RolePreparationBriefRow:
    inputs = build_role_preparation_inputs(session, job_id)
    if inputs is None:
        raise ValueError("job description and company intelligence are required")
    if formatter is None:
        from resume_agent.role_preparation.agents import (
            build_role_preparation_formatter,
        )

        formatter = build_role_preparation_formatter()
    result = expect_schema(
        formatter.run(
            "Frozen role-preparation inputs (untrusted data):\n"
            + inputs.model_dump_json()
        ),
        RolePreparationDraft,
        source="role-preparation format",
    )
    if reporter is not None:
        reporter.checkpoint()
    grounded = _ground_draft(result, inputs)
    generated_at = now or utcnow()
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    brief = RolePreparationBrief(
        **grounded.model_dump(exclude={"schema_version"}),
        job_id=job_id,
        company=inputs.company,
        title=inputs.title,
        generated_at=generated_at,
        input_fingerprint=role_preparation_input_fingerprint(inputs),
        company_intelligence_version_id=inputs.company_intelligence_version_id,
        company_intelligence_version_number=inputs.company_intelligence_version_number,
        resume_version_id=inputs.resume_version_id,
        cover_letter_id=inputs.cover_letter_id,
        application_status=inputs.application_status,
        signal_event_ids=inputs.signal_event_ids,
        caveat=ROLE_PREPARATION_CAVEAT,
    )
    with _WRITE_LOCK:
        row = session.exec(
            select(RolePreparationBriefRow).where(
                RolePreparationBriefRow.job_id == job_id
            )
        ).first()
        if row is None:
            row = RolePreparationBriefRow(job_id=job_id)
            session.add(row)
        row.brief_json = brief.model_dump(mode="json")
        row.generated_at = generated_at
        row.company_intelligence_version_id = inputs.company_intelligence_version_id
        row.resume_version_id = inputs.resume_version_id
        row.input_fingerprint = brief.input_fingerprint
        session.commit()
        session.refresh(row)
    return row


def role_preparation_inputs_changed(session: Session, brief: RolePreparationBrief) -> bool:
    current = build_role_preparation_inputs(session, brief.job_id)
    if current is None:
        return True
    return role_preparation_input_fingerprint(current) != brief.input_fingerprint


def resolve_role_preparation_resource(
    session: Session, job: Job
) -> RolePreparationResource:
    if not job.jd_text.strip():
        return RolePreparationResource(
            state="unavailable", reason="missing_job_description"
        )
    evidence = load_company_intelligence(session, job.company)
    if evidence is None:
        return RolePreparationResource(
            state="unavailable", reason="company_intelligence_required"
        )
    brief = load_role_preparation_brief(session, job.id or 0)
    if brief is None:
        return RolePreparationResource(state="empty")
    inputs = _build_role_preparation_inputs_for_job(session, job, evidence)
    return RolePreparationResource(
        state="ready",
        brief=brief,
        inputs_changed=(
            role_preparation_input_fingerprint(inputs) != brief.input_fingerprint
        ),
    )
