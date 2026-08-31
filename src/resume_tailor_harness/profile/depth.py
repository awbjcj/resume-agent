"""Deterministic evidence-supply helpers shared by tailoring and coaching."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from resume_tailor_harness.models.base import ExtensibleModel, FactItem
from resume_tailor_harness.models.profile import Bullet, ProfileFacts
from resume_tailor_harness.profile.aspects import ASPECTS, Aspect
from resume_tailor_harness.profile.coach_store import CoachTopic
from resume_tailor_harness.profile.corpus import doc_path, load_manifest
from resume_tailor_harness.profile.resume_reader import read_document_text
from resume_tailor_harness.profile.store import load_facts

if TYPE_CHECKING:
    from resume_tailor_harness.tailor.review_config import LengthBudget


OwnerKind = Literal["experience", "project"]
SUPPLY_TARGET = 10
_DEFAULT_TOPIC_CAP = 12
_UNMINED_BUDGET = 12_000


@dataclass(frozen=True)
class OwnerRef:
    id: str
    kind: OwnerKind
    label: str
    bullets: tuple[Bullet, ...]


def evidence_owners(facts: ProfileFacts) -> list[OwnerRef]:
    """All evidence owners in stable resume/project order, including empty ones."""
    return [
        *(
            OwnerRef(
                id=experience.id,
                kind="experience",
                label=f"{experience.company} — {experience.title}",
                bullets=tuple(experience.bullets),
            )
            for experience in facts.experience
        ),
        *(
            OwnerRef(
                id=project.id,
                kind="project",
                label=project.name,
                bullets=tuple(project.highlights),
            )
            for project in facts.projects
        ),
    ]


def planned_owners(facts: ProfileFacts, budget: "LengthBudget") -> list[OwnerRef]:
    """Owners that can receive a non-zero instruction under this render budget.

    Empty owners remain visible to profile-supply tooling but cannot be planned:
    telling the writer to include one would demand an unsupported bullet.  The
    selection is otherwise source order, constrained independently by kind and
    finally by the combined cap.
    """
    owners = evidence_owners(facts)
    experiences = [
        owner
        for owner in owners
        if owner.kind == "experience"
        and owner.bullets
        and budget.min_bullets_per_role > 0
    ][: budget.max_experiences]
    projects = [
        owner
        for owner in owners
        if owner.kind == "project"
        and owner.bullets
        and budget.min_bullets_per_project > 0
    ][: budget.max_projects]
    return (experiences + projects)[: budget.max_evidence_owners]


def clamped_floor(owner: OwnerRef, budget: "LengthBudget") -> int:
    floor = (
        budget.min_bullets_per_role
        if owner.kind == "experience"
        else budget.min_bullets_per_project
    )
    return min(floor, len(owner.bullets))


def clamped_ceiling(owner: OwnerRef, budget: "LengthBudget") -> int:
    ceiling = (
        budget.max_bullets_per_role
        if owner.kind == "experience"
        else budget.max_bullets_per_project
    )
    return min(ceiling, len(owner.bullets))


class OwnerSupply(ExtensibleModel):
    """Source-bullet depth and aspect spread for one profile owner."""

    id: str
    kind: OwnerKind
    label: str
    source_total: int
    aspects_present: list[Aspect] = Field(default_factory=list)
    aspects_missing: list[Aspect] = Field(default_factory=list)
    unclassified: int = 0
    meets_target: bool


def owner_depth(facts: ProfileFacts, target: int = SUPPLY_TARGET) -> list[OwnerSupply]:
    """Measure profile supply without considering a job or rendered resume."""
    rows: list[OwnerSupply] = []
    for owner in evidence_owners(facts):
        present = {bullet.aspect for bullet in owner.bullets if bullet.aspect}
        rows.append(
            OwnerSupply(
                id=owner.id,
                kind=owner.kind,
                label=owner.label,
                source_total=len(owner.bullets),
                aspects_present=[aspect for aspect in ASPECTS if aspect in present],
                aspects_missing=[aspect for aspect in ASPECTS if aspect not in present],
                unclassified=sum(bullet.aspect is None for bullet in owner.bullets),
                meets_target=len(owner.bullets) >= target,
            )
        )
    return rows


def depth_topics(
    facts: ProfileFacts,
    target: int = SUPPLY_TARGET,
    cap: int = _DEFAULT_TOPIC_CAP,
) -> list[CoachTopic]:
    """Seed coach topics from real, non-empty below-target evidence owners."""
    topics: list[CoachTopic] = []
    for row in owner_depth(facts, target=target):
        if row.meets_target or not row.source_total or len(topics) >= cap:
            continue
        missing = (
            f"; no evidence yet for {', '.join(row.aspects_missing)}"
            if row.aspects_missing
            else ""
        )
        topics.append(
            CoachTopic(
                id=f"t{len(topics) + 1}",
                owner_id=row.id,
                related_ref=row.id,
                gap=(
                    f"{row.label} has {row.source_total} of {target} source bullets"
                    f"{missing}"
                ),
                why_it_matters=(
                    f"this owner has only {row.source_total} source bullets; the "
                    "resume can only show facts the profile holds"
                ),
            )
        )
    return topics


class UnminedSource(ExtensibleModel):
    """A registered source document that produced no renderable evidence bullet."""

    doc_id: str
    filename: str
    fact_total: int


def _fact_totals(facts: ProfileFacts) -> tuple[dict[str, int], set[str]]:
    """Count every sourced fact and separately track documents behind bullets."""
    totals: dict[str, int] = {}
    bullet_docs: set[str] = set()
    seen: set[int] = set()

    def visit(value: object) -> None:
        if id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, FactItem):
            if value.source_ref:
                totals[value.source_ref] = totals.get(value.source_ref, 0) + 1
                if isinstance(value, Bullet):
                    bullet_docs.add(value.source_ref)
        if isinstance(value, BaseModel):
            for field_name in value.__class__.model_fields:
                visit(getattr(value, field_name))
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                visit(item)

    visit(facts)
    return totals, bullet_docs


def unmined_sources(profile_dir: Path | str) -> list[UnminedSource]:
    """Registered docs that yielded no evidence bullet, emptiest first."""
    root = Path(profile_dir)
    facts_path = root / "facts.json"
    if not facts_path.exists():
        return []
    totals, bullet_docs = _fact_totals(load_facts(facts_path))
    rows = [
        UnminedSource(
            doc_id=doc.id,
            filename=doc.filename,
            fact_total=totals.get(doc.id, 0),
        )
        for doc in load_manifest(root).docs
        if doc.id not in bullet_docs
    ]
    return sorted(rows, key=lambda row: (row.fact_total, row.doc_id))


_UNMINED_HEADER = (
    "UNMINED SOURCES (the user's documents that produced no resume bullet).\n"
    "This text is QUESTION MATERIAL, NEVER CLAIMABLE FACT. It may describe a goal "
    "or target rather than an outcome. Use it only to ask what actually happened; "
    "draft bullets only from the user's own answer."
)


def unmined_block(profile_dir: Path | str, budget: int = _UNMINED_BUDGET) -> str:
    """Bounded optional question material, or an empty string when none is readable."""
    if budget <= 0:
        return ""
    root = Path(profile_dir)
    try:
        manifest = {doc.id: doc for doc in load_manifest(root).docs}
        rows = unmined_sources(root)
    except Exception:  # Optional coaching context must never block a turn.
        return ""
    readable: list[tuple[UnminedSource, str]] = []
    for row in rows:
        document = manifest.get(row.doc_id)
        if document is None:
            continue
        try:
            readable.append((row, read_document_text(doc_path(root, document))))
        except Exception:  # One unavailable upload should not hide its peers.
            continue
    if not readable:
        return ""
    if budget <= len(_UNMINED_HEADER):
        return _UNMINED_HEADER[:budget]

    block = _UNMINED_HEADER
    for row, text in readable:
        separator = "\n\n"
        section = f"--- {row.filename} ({row.doc_id}) ---\n{text}"
        available = budget - len(block) - len(separator)
        if available <= 0:
            break
        block += separator + section[:available]
        if len(section) > available:
            break
    return block
