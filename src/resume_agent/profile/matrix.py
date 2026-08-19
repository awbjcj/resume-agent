"""Derived skill matrix: canonical skills, evidence, strength, and recency."""

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.assertion_builder import build_capability_assertions
from resume_agent.profile.assertions import (
    ASSERTION_POLICY_REVISION,
    CapabilityAssertion,
)
from resume_agent.profile.group_corrections import (
    corrections_path,
    load_group_corrections,
)
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.groups import (
    SKILL_GROUPS,
    groups_from_cluster_map,
    group_map_path,
    load_group_map,
    sanitize_group_map,
)
from resume_agent.profile.projections import (
    UccmProfileProjection,
    build_profile_projection,
)
from resume_agent.profile.requirement_facts import build_requirement_facts
from resume_agent.matching.models import VerifiedRequirementFact
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy
from resume_agent.taxonomy.skills import split_skills
from resume_agent.taxonomy.term_typing import TERM_TYPING_POLICY_REVISION
from resume_agent.taxonomy.term_corrections import TermTypeCorrection
from resume_agent.tracking.match_gap import normalize_skill

DEFAULT_MATRIX_PATH = "data/profile/matrix.json"
DEFAULT_OVERRIDES_PATH = "data/profile/overrides.yaml"


class MatrixRow(ExtensibleModel):
    key: str
    display: str
    aliases: list[str] = Field(default_factory=list)
    category: Literal["hard", "soft", "domain"] | None = None
    group: str | None = None
    group_source: Literal["correction", "override", "taxonomy"] | None = None
    inferred: bool = False
    evidence_fact_ids: list[str] = Field(default_factory=list)
    strength: float = 0.0
    last_used: str | None = None

    @field_validator("group", mode="before")
    @classmethod
    def validate_group(cls, value: object) -> str | None:
        return value if isinstance(value, str) and value in SKILL_GROUPS else None

    @field_validator("group_source", mode="before")
    @classmethod
    def validate_group_source(cls, value: object) -> str | None:
        return (
            value
            if isinstance(value, str)
            and value in ("correction", "override", "taxonomy")
            else None
        )


class SourceSnapshotRevisionModel(ExtensibleModel):
    namespace: str
    version: str
    checksum: str


class TaxonomyRevisionModel(ExtensibleModel):
    internal_graph_version: str = ""
    external_source_snapshots: list[SourceSnapshotRevisionModel] = Field(
        default_factory=list
    )
    crosswalk_revision: str = ""
    tenant_overlay_revision: str = ""
    generated_legacy_map_revision: str = ""
    correction_ledger_revision: str = ""
    lifecycle_state_revision: str = ""
    canonicalization_override_revision: str = ""
    correction_policy_version: str = ""
    matching_policy_version: str = ""
    effective_hash: str = ""


class TaxonomyManifestModel(ExtensibleModel):
    generated: str = ""
    corrections: str = ""
    term_type_corrections: str = ""
    state: str = ""
    overrides: str = ""
    semantic: str = ""
    capability_mode: Literal["legacy", "shadow", "uccm"] = "legacy"
    capability_effective_mode: Literal["legacy", "shadow", "uccm"] = "legacy"
    capability_status: Literal["disabled", "shadow", "active", "fallback"] = (
        "disabled"
    )
    capability_error_code: str | None = None
    capability_activation_report_revision: str | None = None
    capability: TaxonomyRevisionModel | None = None


class SkillMatrix(ExtensibleModel):
    generated_at: str = ""
    facts_sha256: str = ""
    canonical_map_sha256: str = ""
    taxonomy_revision: str = ""
    taxonomy_manifest: TaxonomyManifestModel | None = None
    assertion_policy_revision: str = ""
    term_typing_policy_revision: str = ""
    term_type_corrections: list[TermTypeCorrection] = Field(default_factory=list)
    assertions: list[CapabilityAssertion] = Field(default_factory=list)
    uccm_profile: UccmProfileProjection | None = None
    verified_requirement_facts: list[VerifiedRequirementFact] = Field(
        default_factory=list
    )
    rows: list[MatrixRow] = Field(default_factory=list)


class SkillMatch(ExtensibleModel):
    requirement: str
    source: Literal["must", "nice", "tech"]
    coverage: Literal["covered", "adjacent", "gap"]
    row: MatrixRow | None = None


class SkillMatchContext(ExtensibleModel):
    matches: list[SkillMatch] = Field(default_factory=list)


class Overrides(ExtensibleModel):
    ban: list[str] = Field(default_factory=list)
    alias: dict[str, str] = Field(default_factory=dict)
    forbid_alias: list[list[str]] = Field(default_factory=list)
    category: dict[str, str] = Field(default_factory=dict)
    group: dict[str, str] = Field(default_factory=dict)

    @field_validator("group", mode="before")
    @classmethod
    def validate_groups(cls, value: object) -> dict[str, str]:
        return sanitize_group_map(value)


def load_overrides(path: str | Path) -> Overrides:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except OSError:
        return Overrides()
    return Overrides.model_validate(data)


def _flatten_aliases(aliases: dict[str, str]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for start in set(aliases) | set(aliases.values()):
        token = start
        seen: set[str] = set()
        while token in aliases and aliases[token] != token:
            if token in seen:
                raise ValueError(f"alias cycle detected at {token!r}")
            seen.add(token)
            token = aliases[token]
        flattened[start] = token
    return flattened


def effective_cluster_map(cluster_map: ClusterMap, overrides: Overrides) -> ClusterMap:
    """Apply forced aliases first, then split every forbidden pair."""
    aliases = {
        normalized_token: normalized_head
        for token, head in cluster_map.aliases.items()
        if (normalized_token := normalize_skill(token))
        and (normalized_head := normalize_skill(head))
    }
    for token, head in overrides.alias.items():
        normalized_token = normalize_skill(token)
        normalized_head = normalize_skill(head)
        if normalized_token and normalized_head:
            aliases[normalized_token] = normalized_head
    aliases = _flatten_aliases(aliases)

    domain_of = {
        aliases.get(normalized_token, normalized_token): theme
        for token, theme in cluster_map.domain_of.items()
        if (normalized_token := normalize_skill(token))
    }
    for pair in overrides.forbid_alias:
        if len(pair) != 2:
            continue
        first, second = (normalize_skill(token) for token in pair)
        if not first or not second or first == second:
            continue
        old_first = aliases.get(first, first)
        old_second = aliases.get(second, second)
        first_theme = domain_of.get(old_first)
        second_theme = domain_of.get(old_second)
        aliases[first] = first
        aliases[second] = second
        if first_theme is not None:
            domain_of[first] = first_theme
        if second_theme is not None:
            domain_of[second] = second_theme
    return ClusterMap(
        aliases=aliases,
        domain_of=domain_of,
        domain_label=dict(cluster_map.domain_label),
        category_of=dict(cluster_map.category_of),
    )


def facts_sha256(facts: ProfileFacts) -> str:
    payload = json.dumps(
        facts.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def canonical_map_sha256(cluster_map: ClusterMap) -> str:
    payload = json.dumps(
        {
            "aliases": cluster_map.aliases,
            "domain_of": cluster_map.domain_of,
            "domain_label": cluster_map.domain_label,
            "category_of": cluster_map.category_of,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def override_tokens(overrides: Overrides) -> set[str]:
    raw = [
        *overrides.alias.keys(),
        *overrides.alias.values(),
        *overrides.category.keys(),
        *(token for pair in overrides.forbid_alias for token in pair),
    ]
    return {token for value in raw if (token := normalize_skill(value))}


def build_skill_match_context(
    criteria: JobCriteria,
    matrix: SkillMatrix,
    cluster_map: ClusterMap,
) -> SkillMatchContext:
    rows_by_key = {row.key: row for row in matrix.rows}
    matches: list[SkillMatch] = []
    field_sources: tuple[tuple[str, Literal["must", "nice", "tech"]], ...] = (
        ("must_have_skills", "must"),
        ("nice_to_have_skills", "nice"),
        ("tech_stack", "tech"),
    )
    for field_name, source in field_sources:
        for requirement in split_skills(getattr(criteria, field_name)):
            token = normalize_skill(requirement)
            canonical = cluster_map.aliases.get(token, token)
            row = rows_by_key.get(canonical)
            coverage: Literal["covered", "adjacent", "gap"] = "gap"
            if row is not None:
                coverage = "covered"
            else:
                theme = cluster_map.domain_of.get(canonical)
                candidates = [
                    candidate
                    for candidate in matrix.rows
                    if theme is not None
                    and cluster_map.domain_of.get(candidate.key) == theme
                ]
                if candidates:
                    row = min(
                        candidates,
                        key=lambda candidate: (-candidate.strength, candidate.key),
                    )
                    coverage = "adjacent"
            matches.append(
                SkillMatch(
                    requirement=requirement,
                    source=source,
                    coverage=coverage,
                    row=row,
                )
            )
    return SkillMatchContext(matches=matches)


def build_matrix(
    facts: ProfileFacts,
    taxonomy: EffectiveTaxonomy,
    *,
    today: date | None = None,
) -> SkillMatrix:
    today = today or datetime.now(timezone.utc).date()
    effective = taxonomy.cluster_map
    assertions = build_capability_assertions(facts, taxonomy, today=today)
    rows = [
        MatrixRow(
            key=(projection := assertion.legacy_projection).key,
            display=projection.display,
            aliases=projection.aliases,
            category=projection.category,
            inferred=projection.inferred,
            evidence_fact_ids=assertion.evidence_fact_ids,
            strength=projection.strength,
            last_used=assertion.last_used,
        )
        for assertion in assertions
    ]

    return SkillMatrix(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        facts_sha256=facts_sha256(facts),
        canonical_map_sha256=canonical_map_sha256(effective),
        taxonomy_revision=taxonomy.semantic_revision,
        taxonomy_manifest=TaxonomyManifestModel(**asdict(taxonomy.manifest)),
        assertion_policy_revision=ASSERTION_POLICY_REVISION,
        term_typing_policy_revision=TERM_TYPING_POLICY_REVISION,
        term_type_corrections=list(taxonomy.term_type_corrections),
        assertions=assertions,
        uccm_profile=build_profile_projection(assertions, taxonomy),
        verified_requirement_facts=build_requirement_facts(facts),
        rows=sorted(rows, key=lambda row: (-row.strength, row.key)),
    )


def _lookup_group(mapping: dict[str, str], keys: list[str]) -> str | None:
    return next((mapping[key] for key in keys if key in mapping), None)


def apply_skill_groups(
    matrix: SkillMatrix,
    group_of: dict[str, str],
    group_overrides: Mapping[str, str],
    corrections: dict[str, str] | None = None,
) -> None:
    """Decorate rows with validated groups; corrections beat overrides and taxonomy."""
    taxonomy = sanitize_group_map(group_of)
    override_groups = sanitize_group_map(group_overrides)
    correction_groups = sanitize_group_map(corrections or {})
    for row in matrix.rows:
        lookup_keys = [
            row.key,
            normalize_skill(row.display),
            *(normalize_skill(alias) for alias in row.aliases),
        ]
        correction = _lookup_group(correction_groups, lookup_keys)
        override = _lookup_group(override_groups, lookup_keys)
        taxonomy_group = _lookup_group(taxonomy, lookup_keys)
        if correction is not None:
            row.group, row.group_source = correction, "correction"
        elif override is not None:
            row.group, row.group_source = override, "override"
        elif taxonomy_group is not None:
            row.group, row.group_source = taxonomy_group, "taxonomy"
        else:
            row.group, row.group_source = None, None


def decorate_matrix_groups(
    matrix: SkillMatrix,
    profile_dir: str | Path,
    taxonomy: EffectiveTaxonomy,
) -> None:
    """Apply every on-disk skill-group layer through one shared seam."""
    profile_dir = Path(profile_dir)
    group_map = groups_from_cluster_map(taxonomy.cluster_map)
    # One migration-only display fallback: a legacy map can guide the first
    # profile rebuild, but is never written or consulted once that rebuild has
    # recorded its import hash in taxonomy_state.json.
    if not group_map and taxonomy.state.legacy_group_map_sha256 is None:
        group_map = load_group_map(group_map_path(profile_dir))
    corrections = load_group_corrections(corrections_path(profile_dir)).as_map()
    apply_skill_groups(
        matrix,
        group_map,
        taxonomy.group_overrides,
        corrections=corrections,
    )


def build_decorated_matrix(profile_dir: str | Path, facts: ProfileFacts) -> SkillMatrix:
    """Build and decorate a matrix without persisting it."""
    from resume_agent.profile.effective import build_effective_taxonomy

    profile_dir = Path(profile_dir)
    taxonomy = build_effective_taxonomy(profile_dir)
    matrix = build_matrix(facts, taxonomy)
    decorate_matrix_groups(matrix, profile_dir, taxonomy)
    return matrix


def rebuild_saved_matrix(
    profile_dir: str | Path,
    facts: ProfileFacts,
    *,
    taxonomy: EffectiveTaxonomy | None = None,
) -> SkillMatrix:
    """Build, decorate, and persist matrix.json from current profile artifacts."""
    profile_dir = Path(profile_dir)
    if taxonomy is None:
        matrix = build_decorated_matrix(profile_dir, facts)
    else:
        matrix = build_matrix(facts, taxonomy)
        decorate_matrix_groups(matrix, profile_dir, taxonomy)
    save_matrix(matrix, profile_dir / "matrix.json")
    return matrix


def save_matrix(matrix: SkillMatrix, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(matrix.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_matrix(
    path: str | Path,
    facts: ProfileFacts | None = None,
    taxonomy: EffectiveTaxonomy | None = None,
) -> SkillMatrix | None:
    try:
        matrix = SkillMatrix.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if facts is not None and matrix.facts_sha256 != facts_sha256(facts):
        return None
    if taxonomy is not None and matrix.taxonomy_revision != taxonomy.semantic_revision:
        return None
    return matrix
