"""Pure profile-facts to capability-assertions builder."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.assertions import (
    ASSERTION_POLICY_REVISION,
    CapabilityAssertion,
    LegacyAssertionProjection,
)
from resume_agent.taxonomy.graph_adapter import legacy_concept_id
from resume_agent.taxonomy.graph_models import ConceptType
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy
from resume_agent.taxonomy.term_typing import (
    TERM_TYPING_POLICY_REVISION,
    TermSource,
    type_term,
)
from resume_agent.tracking.match_gap import normalize_skill

_YEAR_IN_DATE = re.compile(r"(?:19|20)\d{2}")


@dataclass
class _Candidate:
    key: str
    display: str
    aliases: set[str] = field(default_factory=set)
    category: str | None = None
    contexts: list[str] = field(default_factory=list)
    literal_ids: set[str] = field(default_factory=set)
    source_skill_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    strength_ids: set[str] = field(default_factory=set)
    last_used: str | None = None


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _facts_revision(facts: ProfileFacts) -> str:
    return _digest(facts.model_dump(mode="json"))


def _known_fact_ids(value: object) -> set[str]:
    found: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, dict):
            identifier = item.get("id")
            if isinstance(identifier, str) and identifier:
                found.add(identifier)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return found


def _date_year(value: str | None) -> int | None:
    match = _YEAR_IN_DATE.search(value or "")
    return int(match.group()) if match else None


def _recency(last_used: str | None, today: date) -> float:
    if last_used in (None, "current"):
        return 1.0
    year = _date_year(last_used)
    if year is None:
        return 1.0
    return max(0.25, 1.0 - 0.15 * max(0, today.year - year))


def _owner_end(owner: object) -> str | None:
    if getattr(owner, "current", False):
        return "current"
    end = getattr(owner, "end", None)
    return str(end) if end is not None else None


def _later(first: str | None, second: str | None) -> str | None:
    if first == "current" or second == "current":
        return "current"
    values = [value for value in (first, second) if value is not None]
    return max(
        values,
        key=lambda value: (_date_year(value) or -1, value),
        default=None,
    )


def _governed_types(
    taxonomy: EffectiveTaxonomy,
) -> dict[str, tuple[str, ConceptType]]:
    snapshot = taxonomy.capability_snapshot
    if snapshot is None:
        return {}
    return {
        normalize_skill(node.preferred_label): (node.id, node.type)
        for node in snapshot.graph.nodes
        if node.status == "active"
        and node.type_assignment_status == "governed"
        and normalize_skill(node.preferred_label)
    }


def _assertion_id(
    *,
    subject_id: str,
    concept_id: str,
    evidence_fact_ids: list[str],
    facts_revision: str,
    taxonomy_revision: str,
    term_decision_id: str,
) -> str:
    digest = _digest(
        {
            "subject_id": subject_id,
            "concept_id": concept_id,
            "evidence_fact_ids": sorted(evidence_fact_ids),
            "facts_revision": facts_revision,
            "taxonomy_revision": taxonomy_revision,
            "term_decision_id": term_decision_id,
            "assertion_policy_revision": ASSERTION_POLICY_REVISION,
        }
    )
    return f"assertion:{digest}"


def build_capability_assertions(
    facts: ProfileFacts,
    taxonomy: EffectiveTaxonomy,
    *,
    today: date | None = None,
    subject_id: str = "profile:current",
) -> list[CapabilityAssertion]:
    today = today or datetime.now(timezone.utc).date()
    aliases = taxonomy.cluster_map.aliases
    candidates: dict[str, _Candidate] = {}
    known_ids = _known_fact_ids(facts.model_dump(mode="json"))
    missing_ids: set[str] = set()

    for skills in facts.skills.values():
        for skill in skills:
            token = normalize_skill(skill.name)
            key = aliases.get(token, token)
            if not key or key in taxonomy.banned_keys:
                continue
            candidate = candidates.setdefault(
                key,
                _Candidate(key=key, display=skill.name),
            )
            if skill.id:
                candidate.source_skill_ids.append(skill.id)
                candidate.evidence_ids.append(skill.id)
            candidate.aliases.update(
                alias for alias in skill.aliases if normalize_skill(alias) != key
            )
            candidate.aliases.update(
                alias_token
                for alias_token, head in aliases.items()
                if head == key and alias_token != key
            )
            if skill.category is not None:
                candidate.category = skill.category
            if skill.context:
                candidate.contexts.append(skill.context)
            if skill.inferred:
                candidate.strength_ids.update(skill.evidence_fact_ids)
            else:
                candidate.literal_ids.add(skill.id)
                candidate.strength_ids.add(skill.id)
            for evidence_id in skill.evidence_fact_ids:
                if evidence_id not in known_ids:
                    missing_ids.add(evidence_id)
                if evidence_id not in candidate.evidence_ids:
                    candidate.evidence_ids.append(evidence_id)

    if missing_ids:
        raise ValueError(
            "missing evidence fact IDs: " + ", ".join(sorted(missing_ids))
        )

    owners = [*facts.experience, *facts.projects]
    owner_by_fact_id = {
        fact_id: owner
        for owner in owners
        for fact_id in (
            owner.id,
            *(bullet.id for bullet in getattr(owner, "bullets", [])),
        )
    }
    for candidate in candidates.values():
        needles = {
            candidate.key,
            normalize_skill(candidate.display),
            *map(normalize_skill, candidate.aliases),
        }
        needles.discard("")
        for owner in owners:
            technology = {normalize_skill(item) for item in getattr(owner, "tech", [])}
            technology_hit = bool(needles & technology)
            bullet_hits: list[str] = []
            for bullet in getattr(owner, "bullets", []):
                text = normalize_skill(bullet.text)
                if any(f" {needle} " in f" {text} " for needle in needles):
                    if bullet.id not in candidate.evidence_ids:
                        candidate.evidence_ids.append(bullet.id)
                    bullet_hits.append(bullet.id)
            if bullet_hits:
                candidate.strength_ids.update(bullet_hits)
            elif technology_hit:
                if owner.id not in candidate.evidence_ids:
                    candidate.evidence_ids.append(owner.id)
                candidate.strength_ids.add(owner.id)

        for owner in owners:
            bullet_ids = {bullet.id for bullet in getattr(owner, "bullets", [])}
            if owner.id in candidate.strength_ids and candidate.strength_ids & bullet_ids:
                candidate.strength_ids.discard(owner.id)

        for fact_id in candidate.strength_ids:
            owner = owner_by_fact_id.get(fact_id)
            if owner is not None:
                candidate.last_used = _later(candidate.last_used, _owner_end(owner))

    facts_revision = _facts_revision(facts)
    governed_types = _governed_types(taxonomy)
    assertions: list[CapabilityAssertion] = []
    for candidate in candidates.values():
        decision = type_term(
            TermSource.without_offsets(
                source_kind="profile_skill",
                source_id=candidate.source_skill_ids[0],
                original_text=candidate.display,
            ),
            canonical_text=candidate.key,
            governed_types=governed_types,
        )
        supporting = set(candidate.evidence_ids) - set(candidate.source_skill_ids)
        inferred = not candidate.literal_ids
        if inferred:
            status = "inferred"
            claimability = "supported_inference"
        elif supporting:
            status = "evidenced"
            claimability = "literal_evidenced"
        else:
            status = "self_reported"
            claimability = "self_reported_unverified"
        category_override = taxonomy.category_overrides.get(candidate.key)
        category = (
            category_override
            if category_override in ("hard", "soft", "domain")
            else candidate.category
        )
        compatibility_strength = round(
            sum(
                _recency(
                    _owner_end(owner_by_fact_id[fact_id])
                    if fact_id in owner_by_fact_id
                    else None,
                    today,
                )
                for fact_id in candidate.strength_ids
            ),
            2,
        )
        evidence_ids = list(dict.fromkeys(candidate.evidence_ids))
        concept_id = decision.concept_id or legacy_concept_id(candidate.key)
        assertions.append(
            CapabilityAssertion(
                id=_assertion_id(
                    subject_id=subject_id,
                    concept_id=concept_id,
                    evidence_fact_ids=evidence_ids,
                    facts_revision=facts_revision,
                    taxonomy_revision=taxonomy.semantic_revision,
                    term_decision_id=decision.id,
                ),
                subject_id=subject_id,
                concept_id=concept_id,
                concept_type=decision.concept_type,
                term_decision_id=decision.id,
                assertion_status=status,
                evidence_fact_ids=evidence_ids,
                context="; ".join(dict.fromkeys(candidate.contexts)) or None,
                evidence_confidence=1.0 if supporting or inferred else None,
                last_used=candidate.last_used,
                usage_count=len(candidate.strength_ids),
                claimability=claimability,
                facts_revision=facts_revision,
                taxonomy_revision=taxonomy.semantic_revision,
                term_typing_policy_revision=TERM_TYPING_POLICY_REVISION,
                legacy_projection=LegacyAssertionProjection(
                    key=candidate.key,
                    display=candidate.display,
                    aliases=sorted(candidate.aliases),
                    category=category,
                    inferred=inferred,
                    strength=compatibility_strength,
                ),
            )
        )
    return sorted(assertions, key=lambda item: item.legacy_projection.key)
