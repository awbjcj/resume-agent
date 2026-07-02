"""Derived skill matrix: canonical skills, evidence, strength, and recency."""

import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.skills import split_skills
from resume_agent.tracking.match_gap import normalize_skill

DEFAULT_MATRIX_PATH = "data/profile/matrix.json"
DEFAULT_OVERRIDES_PATH = "data/profile/overrides.yaml"


class MatrixRow(ExtensibleModel):
    key: str
    display: str
    aliases: list[str] = Field(default_factory=list)
    category: Literal["hard", "soft", "domain"] | None = None
    inferred: bool = False
    evidence_fact_ids: list[str] = Field(default_factory=list)
    strength: float = 0.0
    last_used: str | None = None


class SkillMatrix(ExtensibleModel):
    generated_at: str = ""
    facts_sha256: str = ""
    canonical_map_sha256: str = ""
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

    theme_of = {
        aliases.get(normalized_token, normalized_token): theme
        for token, theme in cluster_map.theme_of.items()
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
        first_theme = theme_of.get(old_first)
        second_theme = theme_of.get(old_second)
        aliases[first] = first
        aliases[second] = second
        if first_theme is not None:
            theme_of[first] = first_theme
        if second_theme is not None:
            theme_of[second] = second_theme
    return ClusterMap(
        aliases=aliases,
        theme_of=theme_of,
        theme_label=dict(cluster_map.theme_label),
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
            "theme_of": cluster_map.theme_of,
            "theme_label": cluster_map.theme_label,
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
                theme = cluster_map.theme_of.get(canonical)
                candidates = [
                    candidate
                    for candidate in matrix.rows
                    if theme is not None
                    and cluster_map.theme_of.get(candidate.key) == theme
                ]
                if candidates:
                    row = min(candidates, key=lambda candidate: (-candidate.strength, candidate.key))
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


_YEAR_IN_DATE = re.compile(r"(?:19|20)\d{2}")


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


def _owner_end(owner) -> str | None:
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


def build_matrix(
    facts: ProfileFacts,
    cluster_map: ClusterMap,
    overrides: Overrides,
    today: date | None = None,
) -> SkillMatrix:
    today = today or datetime.now(timezone.utc).date()
    effective = effective_cluster_map(cluster_map, overrides)
    aliases = effective.aliases
    banned = {
        aliases.get(token, token)
        for value in overrides.ban
        if (token := normalize_skill(value))
    }
    category_overrides = {
        aliases.get(token, token): category
        for value, category in overrides.category.items()
        if (token := normalize_skill(value))
    }

    rows: dict[str, MatrixRow] = {}
    literal_keys: set[str] = set()
    strength_ids: dict[str, set[str]] = {}
    for skills in facts.skills.values():
        for skill in skills:
            token = normalize_skill(skill.name)
            key = aliases.get(token, token)
            if not key or key in banned:
                continue
            row = rows.setdefault(key, MatrixRow(key=key, display=skill.name))
            evidence_strength = strength_ids.setdefault(key, set())
            if skill.inferred:
                evidence_strength.update(skill.evidence_fact_ids)
            else:
                literal_keys.add(key)
                evidence_strength.add(skill.id)
            row.aliases = sorted(
                set(row.aliases)
                | {
                    alias
                    for alias in skill.aliases
                    if normalize_skill(alias) != key
                }
                | {
                    alias_token
                    for alias_token, head in aliases.items()
                    if head == key and alias_token != key
                }
            )
            if skill.category is not None:
                row.category = skill.category
            row.evidence_fact_ids = list(
                dict.fromkeys(
                    [*row.evidence_fact_ids, skill.id, *skill.evidence_fact_ids]
                )
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
    for row in rows.values():
        row.inferred = row.key not in literal_keys
        needles = {
            row.key,
            normalize_skill(row.display),
            *map(normalize_skill, row.aliases),
        }
        needles.discard("")
        for owner in owners:
            technology = {normalize_skill(item) for item in getattr(owner, "tech", [])}
            technology_hit = bool(needles & technology)
            bullet_hits: list[str] = []
            for bullet in getattr(owner, "bullets", []):
                text = normalize_skill(bullet.text)
                if any(f" {needle} " in f" {text} " for needle in needles):
                    if bullet.id not in row.evidence_fact_ids:
                        row.evidence_fact_ids.append(bullet.id)
                    bullet_hits.append(bullet.id)
            if bullet_hits:
                strength_ids[row.key].update(bullet_hits)
            elif technology_hit:
                if owner.id not in row.evidence_fact_ids:
                    row.evidence_fact_ids.append(owner.id)
                strength_ids[row.key].add(owner.id)

        for owner in owners:
            bullet_ids = {
                bullet.id for bullet in getattr(owner, "bullets", [])
            }
            if owner.id in strength_ids[row.key] and strength_ids[row.key] & bullet_ids:
                strength_ids[row.key].discard(owner.id)

        for fact_id in strength_ids[row.key]:
            owner = owner_by_fact_id.get(fact_id)
            if owner is not None:
                row.last_used = _later(row.last_used, _owner_end(owner))

    for row in rows.values():
        override_category = category_overrides.get(row.key)
        if override_category in ("hard", "soft", "domain"):
            row.category = override_category
        row.strength = round(
            sum(
                _recency(
                    _owner_end(owner_by_fact_id[fact_id])
                    if fact_id in owner_by_fact_id
                    else None,
                    today,
                )
                for fact_id in strength_ids[row.key]
            ),
            2,
        )

    return SkillMatrix(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        facts_sha256=facts_sha256(facts),
        canonical_map_sha256=canonical_map_sha256(effective),
        rows=sorted(rows.values(), key=lambda row: (-row.strength, row.key)),
    )


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
    cluster_map: ClusterMap | None = None,
) -> SkillMatrix | None:
    try:
        matrix = SkillMatrix.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if facts is not None and matrix.facts_sha256 != facts_sha256(facts):
        return None
    if (
        cluster_map is not None
        and matrix.canonical_map_sha256 != canonical_map_sha256(cluster_map)
    ):
        return None
    return matrix
