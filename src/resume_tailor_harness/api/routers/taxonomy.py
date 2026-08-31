"""Synchronous taxonomy edits returning the refreshed match-gap payload."""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, Depends
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.routers.match_gap import build_match_gap_payload
from resume_tailor_harness.api.schemas.match_gap import MatchGapOut
from resume_tailor_harness.api.schemas.taxonomy import (
    AddSkillIn,
    AliasIn,
    DomainMergeIn,
    DomainPatchIn,
    MoveSkillIn,
    NewDomainIn,
)
from resume_tailor_harness.services import taxonomy as service
from resume_tailor_harness.taxonomy.corrections import corrections_file_path
from resume_tailor_harness.tenancy.paths import resolve_tenant_path
from resume_tailor_harness.tracking.match_gap import collect_target_skill_tokens

router = APIRouter()
_CLUSTER_PATH = "data/profile/cluster_map.json"


def _paths() -> tuple[str, str]:
    return (
        str(resolve_tenant_path(corrections_file_path())),
        str(resolve_tenant_path(_CLUSTER_PATH)),
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
def move_skill(token: str, body: MoveSkillIn, session: Session = Depends(get_session)):
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
        service.merge_domains(corrections_path, cluster_path, domain_id, body.into)
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
