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
_WORD_INITIAL = re.compile(r"(?<!\w)([^\W\d_])", flags=re.UNICODE)
_LEGAL_SUFFIXES = {
    "ag",
    "co",
    "company",
    "corp",
    "corporation",
    "gmbh",
    "inc",
    "incorporated",
    "lp",
    "llp",
    "limited",
    "llc",
    "ltd",
    "na",
    "nv",
    "pa",
    "pbc",
    "pc",
    "plc",
    "pllc",
    "sa",
}
_COMPANY_ABBREVIATIONS = (
    (("p", "l", "l", "c"), "pllc"),
    (("g", "m", "b", "h"), "gmbh"),
    (("l", "l", "c"), "llc"),
    (("l", "l", "p"), "llp"),
    (("p", "l", "c"), "plc"),
    (("u", "s", "a"), "usa"),
    (("u", "s"), "us"),
    (("n", "a"), "na"),
    (("p", "b", "c"), "pbc"),
    (("p", "a"), "pa"),
    (("p", "c"), "pc"),
    (("l", "p"), "lp"),
    (("s", "a"), "sa"),
    (("a", "g"), "ag"),
    (("b", "v"), "bv"),
    (("n", "v"), "nv"),
)
_LEGAL_SUFFIX_PHRASES = (
    ("professional", "limited", "liability", "company"),
    ("limited", "liability", "partnership"),
    ("limited", "liability", "company"),
    ("public", "benefit", "corporation"),
    ("professional", "corporation"),
)
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
    words = _normalize_text(str(value).replace("&", " and ")).split()
    canonical_words: list[str] = []
    index = 0
    while index < len(words):
        for source, replacement in _COMPANY_ABBREVIATIONS:
            end = index + len(source)
            if tuple(words[index:end]) == source:
                canonical_words.append(replacement)
                index = end
                break
        else:
            canonical_words.append(words[index])
            index += 1

    words = canonical_words
    if len(words) > 1 and words[0] == "the":
        words.pop(0)
    while words:
        if any(
            len(words) >= len(phrase) and tuple(words[-len(phrase) :]) == phrase
            for phrase in _LEGAL_SUFFIX_PHRASES
        ):
            phrase_length = next(
                len(phrase)
                for phrase in _LEGAL_SUFFIX_PHRASES
                if len(words) >= len(phrase) and tuple(words[-len(phrase) :]) == phrase
            )
            del words[-phrase_length:]
            continue
        if words[-1] in _LEGAL_SUFFIXES:
            words.pop()
            continue
        break
    return " ".join(words) or None


def clean_industry_label(value: object | None) -> str | None:
    """Return a capitalized display label, rejecting numeric or long values.

    Only word initials are changed. That gives human-readable labels such as
    ``Financial Technology`` without corrupting meaningful internal casing in
    abbreviations such as ``AI`` or ``SaaS``.
    """
    if value is None:
        return None
    label = _WHITESPACE.sub(" ", str(value)).strip(" \t\r\n.,;:!?-_/")
    key = normalize_industry(label)
    if key is None or len(key.split()) > 4:
        return None
    return _WORD_INITIAL.sub(lambda match: match.group(1).upper(), label)


def canonical_industry(
    company: object | None,
    candidate: object | None,
    taxonomy: IndustryTaxonomy,
) -> str | None:
    company_key = normalize_company(company)
    if company_key and company_key in taxonomy.companies:
        return clean_industry_label(taxonomy.companies[company_key])
    industry_key = normalize_industry(candidate)
    canonical = taxonomy.aliases.get(industry_key) if industry_key else None
    return clean_industry_label(canonical)


def merge_industry_taxonomy(
    existing: IndustryTaxonomy,
    *,
    aliases: dict[str, str] | None = None,
    companies: dict[str, str] | None = None,
) -> IndustryTaxonomy:
    """Add mappings without redirecting any established alias or company."""
    merged_aliases: dict[str, str] = {}
    for raw_alias, canonical in existing.aliases.items():
        key = normalize_industry(raw_alias)
        label = clean_industry_label(canonical)
        if key and label:
            merged_aliases.setdefault(key, label)
    for raw_alias, canonical in (aliases or {}).items():
        key = normalize_industry(raw_alias)
        label = clean_industry_label(canonical)
        if key and label:
            merged_aliases.setdefault(key, label)

    merged_companies: dict[str, str] = {}
    for raw_company, canonical in existing.companies.items():
        key = normalize_company(raw_company)
        label = clean_industry_label(canonical)
        if key and label:
            merged_companies.setdefault(key, label)
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
