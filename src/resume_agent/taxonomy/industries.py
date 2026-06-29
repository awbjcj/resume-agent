"""Stable, human-readable industry taxonomy state."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

INDUSTRY_TAXONOMY_PATH = Path("data/industry_taxonomy.json")

_NON_ALNUM = re.compile(r"[^\w]+", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "gmbh",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "ltd",
    "plc",
}
_SAVE_LOCK = Lock()


@dataclass(frozen=True)
class IndustryTaxonomy:
    aliases: dict[str, str] = field(default_factory=dict)
    companies: dict[str, str] = field(default_factory=dict)


def _normalize_text(value: object) -> str:
    text = _NON_ALNUM.sub(" ", str(value).casefold().replace("_", " "))
    return _WHITESPACE.sub(" ", text).strip()


def normalize_industry(value: object | None) -> str | None:
    """Return the stable lookup key for a readable industry label."""
    if value is None:
        return None
    normalized = _normalize_text(value)
    if not normalized or normalized.isdecimal():
        return None
    return normalized


def normalize_company(value: object | None) -> str | None:
    """Normalize company identity without merging named brands or subsidiaries."""
    if value is None:
        return None
    words = _normalize_text(value).split()
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words) or None


def clean_industry_label(value: object | None) -> str | None:
    """Clean a display label while rejecting numeric-only or overly long values."""
    if value is None:
        return None
    label = _WHITESPACE.sub(" ", str(value)).strip(" \t\r\n.,;:!?-_/")
    key = normalize_industry(label)
    if key is None or len(key.split()) > 4:
        return None
    return label


def canonical_industry(
    company: object | None,
    candidate: object | None,
    taxonomy: IndustryTaxonomy,
) -> str | None:
    company_key = normalize_company(company)
    if company_key and company_key in taxonomy.companies:
        return taxonomy.companies[company_key]
    industry_key = normalize_industry(candidate)
    return taxonomy.aliases.get(industry_key) if industry_key else None


def merge_industry_taxonomy(
    existing: IndustryTaxonomy,
    *,
    aliases: dict[str, str] | None = None,
    companies: dict[str, str] | None = None,
) -> IndustryTaxonomy:
    """Add mappings without redirecting any established alias or company."""
    merged_aliases = dict(existing.aliases)
    for raw_alias, canonical in (aliases or {}).items():
        key = normalize_industry(raw_alias)
        label = clean_industry_label(canonical)
        if key and label:
            merged_aliases.setdefault(key, label)

    merged_companies = dict(existing.companies)
    for raw_company, canonical in (companies or {}).items():
        key = normalize_company(raw_company)
        label = clean_industry_label(canonical)
        if key and label:
            merged_companies.setdefault(key, label)

    return IndustryTaxonomy(aliases=merged_aliases, companies=merged_companies)


def load_industry_taxonomy(
    path: Path | str = INDUSTRY_TAXONOMY_PATH,
) -> IndustryTaxonomy:
    source = Path(path)
    if not source.exists():
        return IndustryTaxonomy()
    payload = json.loads(source.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("industry taxonomy must be a JSON object")
    aliases = payload.get("aliases", {})
    companies = payload.get("companies", {})
    if not isinstance(aliases, dict) or not isinstance(companies, dict):
        raise ValueError("industry taxonomy mappings must be JSON objects")
    return merge_industry_taxonomy(
        IndustryTaxonomy(), aliases=aliases, companies=companies
    )


def save_industry_taxonomy(
    taxonomy: IndustryTaxonomy,
    path: Path | str = INDUSTRY_TAXONOMY_PATH,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _SAVE_LOCK:
        persisted = load_industry_taxonomy(destination)
        merged = merge_industry_taxonomy(
            persisted,
            aliases=taxonomy.aliases,
            companies=taxonomy.companies,
        )
        payload = {"aliases": merged.aliases, "companies": merged.companies}
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(
                    json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
                    + "\n"
                )
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
