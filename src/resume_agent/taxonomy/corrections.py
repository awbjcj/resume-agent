"""Durable user taxonomy intents replayed over derived cluster maps."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from threading import Lock

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    _canonicalize_domain_keys,
    _sanitize_aliases,
)
from resume_agent.taxonomy.vocabulary import SKILL_GROUPS
from resume_agent.tracking.match_gap import normalize_skill

_LEDGER_LOCK = Lock()


def corrections_file_path() -> str:
    return "data/taxonomy/taxonomy_corrections.json"


class TaxonomyCorrections(ExtensibleModel):
    skill_domain: dict[str, str] = Field(default_factory=dict)
    domain_renames: dict[str, str] = Field(default_factory=dict)
    domain_merges: dict[str, str] = Field(default_factory=dict)
    domain_category: dict[str, str] = Field(default_factory=dict)
    added_skills: list[str] = Field(default_factory=list)
    removed_skills: list[str] = Field(default_factory=list)
    aliases: dict[str, str] = Field(default_factory=dict)


def _clean_str_map(
    value: object,
    *,
    normalize_keys: bool = False,
    normalize_values: bool = False,
) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str):
            continue
        key = normalize_skill(raw_key) if normalize_keys else raw_key.strip()
        item = normalize_skill(raw_value) if normalize_values else raw_value.strip()
        if key and item:
            clean.setdefault(key, item)
    return clean


def _clean_tokens(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    clean: list[str] = []
    seen: set[str] = set()
    for raw in value:
        token = normalize_skill(raw) if isinstance(raw, str) else ""
        if token and token not in seen:
            seen.add(token)
            clean.append(token)
    return clean


def _sanitize_merge_map(value: object) -> dict[str, str]:
    flattened = _sanitize_aliases(_clean_str_map(value))
    return {source: target for source, target in flattened.items() if source != target}


def _from_raw(value: object) -> TaxonomyCorrections:
    if not isinstance(value, dict):
        return TaxonomyCorrections()
    added = _clean_tokens(value.get("added_skills"))
    added_set = set(added)
    removed = [
        token
        for token in _clean_tokens(value.get("removed_skills"))
        if token not in added_set
    ]
    return TaxonomyCorrections(
        skill_domain=_clean_str_map(value.get("skill_domain"), normalize_keys=True),
        domain_renames=_clean_str_map(value.get("domain_renames")),
        domain_merges=_sanitize_merge_map(value.get("domain_merges")),
        domain_category={
            domain_id: slug
            for domain_id, slug in _clean_str_map(value.get("domain_category")).items()
            if slug in SKILL_GROUPS
        },
        added_skills=added,
        removed_skills=removed,
        aliases=_sanitize_aliases(
            _clean_str_map(
                value.get("aliases"), normalize_keys=True, normalize_values=True
            )
        ),
    )


def sanitize_taxonomy_corrections(
    ledger: TaxonomyCorrections,
) -> TaxonomyCorrections:
    return _from_raw(ledger.model_dump(mode="python"))


def load_taxonomy_corrections(path: str | Path) -> TaxonomyCorrections:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return TaxonomyCorrections()
    return _from_raw(raw)


def load_taxonomy_corrections_strict(path: str | Path) -> TaxonomyCorrections:
    """Load a mutation base without treating corrupt user intent as empty."""

    destination = Path(path)
    try:
        raw = json.loads(destination.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return TaxonomyCorrections()
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"taxonomy corrections are unreadable: {destination}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"taxonomy corrections are unreadable: {destination}")
    try:
        parsed = TaxonomyCorrections.model_validate(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"taxonomy corrections are unreadable: {destination}") from exc
    return sanitize_taxonomy_corrections(parsed)


def _write_taxonomy_corrections(
    ledger: TaxonomyCorrections, destination: Path
) -> TaxonomyCorrections:
    clean = sanitize_taxonomy_corrections(ledger)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = clean.model_dump_json(indent=2) + "\n"
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
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return clean


def save_taxonomy_corrections(
    ledger: TaxonomyCorrections, path: str | Path
) -> None:
    with _LEDGER_LOCK:
        _write_taxonomy_corrections(ledger, Path(path))


def update_taxonomy_corrections(
    path: str | Path, mutate: Callable[[TaxonomyCorrections], None]
) -> TaxonomyCorrections:
    """Serialize a complete read-modify-write ledger transaction."""
    destination = Path(path)
    with _LEDGER_LOCK:
        ledger = load_taxonomy_corrections(destination)
        mutate(ledger)
        return _write_taxonomy_corrections(ledger, destination)


def added_canonical_tokens(
    corrections: TaxonomyCorrections, aliases: dict[str, str]
) -> set[str]:
    return {aliases.get(token, token) for token in corrections.added_skills}


def removed_canonical_tokens(
    corrections: TaxonomyCorrections, aliases: dict[str, str]
) -> set[str]:
    return {aliases.get(token, token) for token in corrections.removed_skills}


def apply_taxonomy_corrections(
    cmap: ClusterMap, corrections: TaxonomyCorrections
) -> ClusterMap:
    """Pure, idempotent replay with user intents taking final precedence."""
    corrections = sanitize_taxonomy_corrections(corrections)
    combined_aliases = dict(cmap.aliases)
    combined_aliases.update(corrections.aliases)
    aliases = _sanitize_aliases(combined_aliases)

    domain_of = _canonicalize_domain_keys(cmap.domain_of, aliases)
    domain_label = dict(cmap.domain_label)
    category_of = dict(cmap.category_of)

    reconstructible = set(corrections.domain_renames) & set(
        corrections.domain_category
    )
    for domain_id in reconstructible:
        domain_label.setdefault(domain_id, corrections.domain_renames[domain_id])
        category_of.setdefault(domain_id, corrections.domain_category[domain_id])

    known_ids = set(domain_of.values()) | set(domain_label) | set(category_of)
    merges = corrections.domain_merges
    for loser, winner in merges.items():
        if loser not in known_ids or winner not in known_ids:
            continue
        domain_of = {
            token: winner if domain_id == loser else domain_id
            for token, domain_id in domain_of.items()
        }
        domain_label.pop(loser, None)
        category_of.pop(loser, None)
        known_ids.discard(loser)

    for token, target in corrections.skill_domain.items():
        target = merges.get(target, target)
        if target not in known_ids:
            continue
        domain_of[aliases.get(token, token)] = target

    for domain_id, label in corrections.domain_renames.items():
        target = merges.get(domain_id, domain_id)
        if target in known_ids:
            domain_label[target] = label
    for domain_id, slug in corrections.domain_category.items():
        target = merges.get(domain_id, domain_id)
        if target in known_ids:
            category_of[target] = slug

    # Keep labels/categories only for domains a skill still references. This
    # drops phantom domains left behind when a reconstructed (renamed +
    # categorized) domain loses its last skill, so they never linger in the map
    # or count against the per-category cap.
    referenced = set(domain_of.values())
    domain_label = {
        domain_id: domain_label.get(domain_id, domain_id) for domain_id in referenced
    }
    category_of = {
        domain_id: category_of.get(domain_id, "other") for domain_id in referenced
    }

    return ClusterMap(
        aliases=aliases,
        domain_of=domain_of,
        domain_label=domain_label,
        category_of=category_of,
    )
