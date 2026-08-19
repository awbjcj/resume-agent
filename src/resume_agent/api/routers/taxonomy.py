"""Synchronous taxonomy edits returning the refreshed match-gap payload."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.routers.match_gap import build_match_gap_payload
from resume_agent.api.schemas.match_gap import MatchGapOut
from resume_agent.api.schemas.taxonomy import (
    AddSkillIn,
    AliasIn,
    DomainMergeIn,
    DomainPatchIn,
    MoveSkillIn,
    NewDomainIn,
    RequirementTermTypeCorrectionIn,
    TermSourceIn,
    TermTypeCorrectionIn,
    TermTypeCorrectionOut,
    TermTypingDecisionOut,
)
from resume_agent.services import taxonomy as service
from resume_agent.services import term_typing as term_typing_service
from resume_agent.taxonomy.corrections import corrections_file_path
from resume_agent.taxonomy.term_corrections import load_term_type_corrections
from resume_agent.taxonomy.term_typing import TermSource, TermTypingDecision
from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.paths import resolve_tenant_path
from resume_agent.tracking.match_gap import collect_target_skill_tokens

router = APIRouter()
_CLUSTER_PATH = "data/profile/cluster_map.json"
_FACTS_PATH = "data/profile/facts.json"
_TERM_CORRECTIONS_PATH = "data/taxonomy/term_type_corrections.json"


def _paths() -> tuple[str, str]:
    return (
        str(resolve_tenant_path(corrections_file_path())),
        str(resolve_tenant_path(_CLUSTER_PATH)),
    )


def _term_correction_path():
    return resolve_tenant_path(_TERM_CORRECTIONS_PATH)


def _term_source(value: TermSourceIn) -> TermSource:
    return TermSource.model_validate(value.model_dump())


def _decision_out(decision: TermTypingDecision) -> TermTypingDecisionOut:
    return TermTypingDecisionOut(
        **decision.model_dump(mode="json"),
        original_text=decision.original_text,
    )


def _spec(value: NewDomainIn | None) -> service.NewDomainSpec | None:
    return (
        service.NewDomainSpec(label=value.label, category=value.category)
        if value is not None
        else None
    )


@contextmanager
def _translated_errors():
    try:
        yield
    except service.UnknownDomainError as exc:
        raise ApiException(404, "UNKNOWN_DOMAIN", str(exc)) from exc
    except service.UnknownCategoryError as exc:
        raise ApiException(400, "UNKNOWN_CATEGORY", str(exc)) from exc
    except service.UnknownSkillError as exc:
        raise ApiException(404, "UNKNOWN_SKILL", str(exc)) from exc
    except service.InvalidSkillTokenError as exc:
        raise ApiException(400, "INVALID_SKILL_TOKEN", str(exc)) from exc
    except service.AliasCycleError as exc:
        raise ApiException(400, "ALIAS_CYCLE", str(exc)) from exc
    except service.DomainMergeCycleError as exc:
        raise ApiException(400, "MERGE_CYCLE", str(exc)) from exc
    except ValueError as exc:
        raise ApiException(400, "INVALID_TAXONOMY_EDIT", str(exc)) from exc


@router.put("/taxonomy/skills/{token}/domain", response_model=MatchGapOut)
def move_skill(
    token: str, body: MoveSkillIn, session: Session = Depends(get_session)
):
    corrections_path, cluster_path = _paths()
    with _translated_errors():
        service.move_skill(
            corrections_path,
            cluster_path,
            token,
            domain_id=body.domain_id,
            new_domain=_spec(body.new_domain),
            known_tokens=collect_target_skill_tokens(session),
        )
    return build_match_gap_payload(session)


@router.post("/taxonomy/skills", response_model=MatchGapOut)
def add_skill(body: AddSkillIn, session: Session = Depends(get_session)):
    corrections_path, cluster_path = _paths()
    with _translated_errors():
        service.add_skill(
            corrections_path,
            cluster_path,
            body.token,
            domain_id=body.domain_id,
            new_domain=_spec(body.new_domain),
        )
    return build_match_gap_payload(session)


@router.delete("/taxonomy/skills/{token}", response_model=MatchGapOut)
def remove_skill(token: str, session: Session = Depends(get_session)):
    corrections_path, cluster_path = _paths()
    with _translated_errors():
        service.remove_skill(corrections_path, token, cluster_path=cluster_path)
    return build_match_gap_payload(session)


@router.patch("/taxonomy/domains/{domain_id}", response_model=MatchGapOut)
def patch_domain(
    domain_id: str,
    body: DomainPatchIn,
    session: Session = Depends(get_session),
):
    corrections_path, cluster_path = _paths()
    with _translated_errors():
        service.patch_domain(
            corrections_path,
            cluster_path,
            domain_id,
            label=body.label,
            category=body.category,
        )
    return build_match_gap_payload(session)


@router.post("/taxonomy/domains/{domain_id}/merge", response_model=MatchGapOut)
def merge_domain(
    domain_id: str,
    body: DomainMergeIn,
    session: Session = Depends(get_session),
):
    corrections_path, cluster_path = _paths()
    with _translated_errors():
        service.merge_domains(
            corrections_path, cluster_path, domain_id, body.into
        )
    return build_match_gap_payload(session)


@router.post("/taxonomy/aliases", response_model=MatchGapOut)
def add_alias(body: AliasIn, session: Session = Depends(get_session)):
    corrections_path, cluster_path = _paths()
    with _translated_errors():
        service.add_skill_alias(
            corrections_path,
            cluster_path,
            body.token,
            body.canonical,
            known_tokens=collect_target_skill_tokens(session),
        )
    return build_match_gap_payload(session)


@router.post(
    "/taxonomy/term-types:classify",
    response_model=TermTypingDecisionOut,
)
def classify_term(body: TermSourceIn):
    decision = term_typing_service.classify_term(
        _term_source(body),
        corrections_path=_term_correction_path(),
    )
    return _decision_out(decision)


@router.patch(
    "/taxonomy/term-types/{decision_id}",
    response_model=TermTypingDecisionOut,
)
def correct_term(
    decision_id: str,
    body: TermTypeCorrectionIn,
    session: Session = Depends(get_session),
):
    context = current_context()
    actor_id = context.user_id if context is not None else "local-user"
    try:
        facts_path = resolve_tenant_path(_FACTS_PATH)
        decision = term_typing_service.correct_term_and_rebuild_profile(
            _term_source(body.source),
            decision_id=decision_id,
            new_type=body.new_type,
            rationale=body.rationale,
            evidence_refs=body.evidence_refs,
            actor_id=actor_id,
            corrections_path=_term_correction_path(),
            profile_dir=facts_path.parent,
            facts_path=facts_path,
            session=session,
        )
    except term_typing_service.TermDecisionMismatchError as exc:
        raise ApiException(409, "TERM_DECISION_MISMATCH", str(exc)) from exc
    return _decision_out(decision)


@router.patch(
    "/taxonomy/jobs/{job_id}/requirements/{requirement_id}/term-type",
    response_model=TermTypingDecisionOut,
)
def correct_job_requirement(
    job_id: int,
    requirement_id: str,
    body: RequirementTermTypeCorrectionIn,
    session: Session = Depends(get_session),
):
    context = current_context()
    actor_id = context.user_id if context is not None else "local-user"
    facts_path = resolve_tenant_path(_FACTS_PATH)
    try:
        decision = term_typing_service.correct_job_requirement(
            session,
            job_id=job_id,
            requirement_id=requirement_id,
            new_type=body.new_type,
            rationale=body.rationale,
            evidence_refs=body.evidence_refs,
            actor_id=actor_id,
            corrections_path=_term_correction_path(),
            profile_dir=facts_path.parent,
            facts_path=facts_path,
        )
    except term_typing_service.JobRequirementNotFoundError as exc:
        raise ApiException(404, "JOB_REQUIREMENT_NOT_FOUND", str(exc)) from exc
    except term_typing_service.TermDecisionMismatchError as exc:
        raise ApiException(409, "TERM_DECISION_MISMATCH", str(exc)) from exc
    return _decision_out(decision)


@router.get(
    "/taxonomy/term-type-corrections",
    response_model=list[TermTypeCorrectionOut],
)
def list_term_type_corrections():
    return [
        TermTypeCorrectionOut.model_validate(event.model_dump(mode="json"))
        for event in load_term_type_corrections(_term_correction_path())
    ]
