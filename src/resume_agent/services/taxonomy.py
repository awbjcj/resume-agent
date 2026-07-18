"""Taxonomy edit use-cases: validate current state and persist one intent transaction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from resume_agent.taxonomy.clusters import (
    ClusterMap,
    _flatten_aliases,
    load_cluster_map,
    slugify_domain,
)
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    apply_taxonomy_corrections,
    update_taxonomy_corrections,
)
from resume_agent.taxonomy.vocabulary import SKILL_GROUPS
from resume_agent.tracking.match_gap import normalize_skill


class UnknownDomainError(ValueError):
    pass


class UnknownCategoryError(ValueError):
    pass


class UnknownSkillError(ValueError):
    pass


class InvalidSkillTokenError(ValueError):
    pass


class AliasCycleError(ValueError):
    pass


class DomainMergeCycleError(ValueError):
    pass


@dataclass(frozen=True)
class NewDomainSpec:
    label: str
    category: str


def _corrected_map(cluster_path: str | Path, ledger: TaxonomyCorrections) -> ClusterMap:
    return apply_taxonomy_corrections(load_cluster_map(cluster_path), ledger)


def _known_domain_ids(cmap: ClusterMap) -> set[str]:
    return set(cmap.domain_of.values()) | set(cmap.domain_label) | set(cmap.category_of)


def _known_skill_tokens(cmap: ClusterMap, ledger: TaxonomyCorrections) -> set[str]:
    return (
        set(cmap.aliases)
        | set(cmap.aliases.values())
        | set(cmap.domain_of)
        | set(ledger.added_skills)
    )


def _require_token(raw: str) -> str:
    token = normalize_skill(raw)
    if not token:
        raise InvalidSkillTokenError(f"{raw!r} is not a usable skill token")
    return token


def _require_category(category: str) -> None:
    if category not in SKILL_GROUPS:
        raise UnknownCategoryError(f"Unknown category {category!r}")


def _allocate_domain_id(label: str, occupied: set[str]) -> str:
    base = slugify_domain(label)
    if not base:
        raise InvalidSkillTokenError(
            "domain label must contain an alphanumeric character"
        )
    domain_id, suffix = base, 2
    while domain_id in occupied:
        domain_id = f"{base}-{suffix}"
        suffix += 1
    return domain_id


def _assign_skill(
    ledger: TaxonomyCorrections,
    cmap: ClusterMap,
    token: str,
    *,
    domain_id: str | None,
    new_domain: NewDomainSpec | None,
) -> None:
    if (domain_id is None) == (new_domain is None):
        raise ValueError("provide exactly one of domain_id or new_domain")
    if new_domain is not None:
        _require_category(new_domain.category)
        label = new_domain.label.strip()
        domain_id = _allocate_domain_id(label, _known_domain_ids(cmap))
        ledger.domain_renames[domain_id] = label
        ledger.domain_category[domain_id] = new_domain.category
    elif domain_id not in _known_domain_ids(cmap):
        raise UnknownDomainError(f"Unknown domain {domain_id!r}")
    assert domain_id is not None
    ledger.skill_domain[token] = domain_id


def move_skill(
    corrections_path: str | Path,
    cluster_path: str | Path,
    token: str,
    *,
    domain_id: str | None = None,
    new_domain: NewDomainSpec | None = None,
) -> None:
    token = _require_token(token)

    def mutate(ledger: TaxonomyCorrections) -> None:
        cmap = _corrected_map(cluster_path, ledger)
        if token not in _known_skill_tokens(cmap, ledger):
            raise UnknownSkillError(f"Unknown skill {token!r}")
        _assign_skill(
            ledger,
            cmap,
            token,
            domain_id=domain_id,
            new_domain=new_domain,
        )

    update_taxonomy_corrections(corrections_path, mutate)


def add_skill(
    corrections_path: str | Path,
    cluster_path: str | Path,
    token: str,
    *,
    domain_id: str | None = None,
    new_domain: NewDomainSpec | None = None,
) -> None:
    token = _require_token(token)

    def mutate(ledger: TaxonomyCorrections) -> None:
        _assign_skill(
            ledger,
            _corrected_map(cluster_path, ledger),
            token,
            domain_id=domain_id,
            new_domain=new_domain,
        )
        if token not in ledger.added_skills:
            ledger.added_skills.append(token)
        ledger.removed_skills = [item for item in ledger.removed_skills if item != token]

    update_taxonomy_corrections(corrections_path, mutate)


def remove_skill(corrections_path: str | Path, token: str) -> None:
    token = _require_token(token)

    def mutate(ledger: TaxonomyCorrections) -> None:
        ledger.added_skills = [item for item in ledger.added_skills if item != token]
        ledger.skill_domain.pop(token, None)
        if token not in ledger.removed_skills:
            ledger.removed_skills.append(token)

    update_taxonomy_corrections(corrections_path, mutate)


def patch_domain(
    corrections_path: str | Path,
    cluster_path: str | Path,
    domain_id: str,
    *,
    label: str | None = None,
    category: str | None = None,
) -> None:
    if label is None and category is None:
        raise ValueError("provide label or category")

    def mutate(ledger: TaxonomyCorrections) -> None:
        if domain_id not in _known_domain_ids(_corrected_map(cluster_path, ledger)):
            raise UnknownDomainError(f"Unknown domain {domain_id!r}")
        clean_label = label.strip() if label is not None else None
        if clean_label is not None and not clean_label:
            raise ValueError("domain label must not be blank")
        if category is not None:
            _require_category(category)
        if clean_label is not None:
            ledger.domain_renames[domain_id] = clean_label
        if category is not None:
            ledger.domain_category[domain_id] = category

    update_taxonomy_corrections(corrections_path, mutate)


def rename_domain(
    corrections_path: str | Path,
    cluster_path: str | Path,
    domain_id: str,
    label: str,
) -> None:
    patch_domain(corrections_path, cluster_path, domain_id, label=label)


def change_domain_category(
    corrections_path: str | Path,
    cluster_path: str | Path,
    domain_id: str,
    category: str,
) -> None:
    patch_domain(corrections_path, cluster_path, domain_id, category=category)


def merge_domains(
    corrections_path: str | Path,
    cluster_path: str | Path,
    source_id: str,
    target_id: str,
) -> None:
    if source_id == target_id:
        raise DomainMergeCycleError("cannot merge a domain into itself")

    def mutate(ledger: TaxonomyCorrections) -> None:
        candidate = {**ledger.domain_merges, source_id: target_id}
        try:
            flattened = _flatten_aliases(candidate)
        except ValueError as exc:
            raise DomainMergeCycleError(
                f"merging {source_id!r} into {target_id!r} would create a cycle"
            ) from exc
        base = load_cluster_map(cluster_path)
        known = _known_domain_ids(base) | _known_domain_ids(
            apply_taxonomy_corrections(base, ledger)
        )
        if source_id not in known:
            raise UnknownDomainError(f"Unknown domain {source_id!r}")
        if target_id not in known:
            raise UnknownDomainError(f"Unknown domain {target_id!r}")
        ledger.domain_merges = {
            source: target
            for source, target in flattened.items()
            if source != target
        }

    update_taxonomy_corrections(corrections_path, mutate)


def add_skill_alias(
    corrections_path: str | Path,
    cluster_path: str | Path,
    token: str,
    canonical: str,
) -> None:
    token = _require_token(token)
    canonical = _require_token(canonical)
    if token == canonical:
        raise AliasCycleError("a skill cannot alias itself")

    def mutate(ledger: TaxonomyCorrections) -> None:
        cmap = _corrected_map(cluster_path, ledger)
        known = _known_skill_tokens(cmap, ledger)
        if token not in known:
            raise UnknownSkillError(f"Unknown skill {token!r}")
        if canonical not in known:
            raise UnknownSkillError(f"Unknown skill {canonical!r}")
        candidate = {**ledger.aliases, token: canonical}
        try:
            ledger.aliases = _flatten_aliases(candidate)
        except ValueError as exc:
            raise AliasCycleError(
                f"aliasing {token!r} to {canonical!r} would create a cycle"
            ) from exc

    update_taxonomy_corrections(corrections_path, mutate)
