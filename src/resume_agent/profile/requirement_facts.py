"""Explicit profile facts used by strict non-capability requirement lanes."""

from __future__ import annotations

import hashlib
import json

from resume_agent.matching.models import VerifiedRequirementFact
from resume_agent.models.profile import ProfileFacts
from resume_agent.tracking.match_gap import normalize_skill


def _facts_revision(facts: ProfileFacts) -> str:
    payload = json.dumps(
        facts.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _fact(
    *,
    fact_type,
    display: str,
    evidence_fact_id: str,
    verification_status,
    facts_revision: str,
) -> VerifiedRequirementFact:
    identity = hashlib.sha256(
        f"{fact_type}|{normalize_skill(display)}|{evidence_fact_id}".encode()
    ).hexdigest()
    return VerifiedRequirementFact(
        id=f"requirement-fact:{identity}",
        fact_type=fact_type,
        normalized_value=normalize_skill(display),
        display=display,
        evidence_fact_id=evidence_fact_id,
        verification_status=verification_status,
        facts_revision=facts_revision,
    )


def build_requirement_facts(facts: ProfileFacts) -> list[VerifiedRequirementFact]:
    revision = _facts_revision(facts)
    result: list[VerifiedRequirementFact] = []
    for certification in facts.certifications:
        if certification.name.strip():
            result.append(
                _fact(
                    fact_type="credential",
                    display=certification.name,
                    evidence_fact_id=certification.id,
                    verification_status=(
                        "verified" if certification.credential_id else "asserted"
                    ),
                    facts_revision=revision,
                )
            )
    for education in facts.education:
        if education.degree and education.degree.strip():
            result.append(
                _fact(
                    fact_type="education",
                    display=education.degree,
                    evidence_fact_id=education.id,
                    verification_status="asserted",
                    facts_revision=revision,
                )
            )
    for language in facts.languages:
        if language.language.strip():
            result.append(
                _fact(
                    fact_type="language",
                    display=language.language,
                    evidence_fact_id=language.id,
                    verification_status="asserted",
                    facts_revision=revision,
                )
            )
    authorization = facts.contact.work_authorization
    if authorization and authorization.strip():
        evidence_id = "contact:work_authorization:" + hashlib.sha256(
            authorization.strip().encode()
        ).hexdigest()[:16]
        result.append(
            _fact(
                fact_type="work_authorization",
                display=authorization.strip(),
                evidence_fact_id=evidence_id,
                verification_status="asserted",
                facts_revision=revision,
            )
        )
    return sorted(result, key=lambda item: (item.fact_type, item.id))
