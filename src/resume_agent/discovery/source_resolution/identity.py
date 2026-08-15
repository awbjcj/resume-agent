"""Conservative, deterministic company-identity evidence helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Iterator
from urllib.parse import urlsplit

import tldextract
from bs4 import BeautifulSoup


_TLD = tldextract.TLDExtract(suffix_list_urls=())
_LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "llc",
        "ltd",
        "limited",
        "plc",
        "gmbh",
        "ag",
        "co",
        "company",
    }
)
_WORD = re.compile(r"[^\w]+", re.UNICODE)


def registrable_domain(url: str) -> str:
    """Return a network-free registrable domain, or an empty string."""
    try:
        host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""
    parsed = _TLD(host)
    return ".".join(part for part in (parsed.domain, parsed.suffix) if part)


def normalize_company_name(value: str) -> str:
    """Normalize a company label while preserving meaningful word boundaries."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    words = [word for word in _WORD.sub(" ", normalized).split() if word]
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def _company_words(value: str) -> tuple[str, ...]:
    return tuple(normalize_company_name(value).split())


def company_names_match(expected: str, observed: str) -> bool:
    """Match exact identities or unambiguous short corporate names only."""
    expected_words = _company_words(expected)
    observed_words = _company_words(observed)
    if not expected_words or not observed_words:
        return False
    if expected_words == observed_words:
        return True
    shorter, longer = sorted((expected_words, observed_words), key=len)
    return (
        len(shorter) < len(longer)
        and len("".join(shorter)) >= 5
        and all(word in longer for word in shorter)
    )


def _organization_values(node: object) -> Iterator[str]:
    if isinstance(node, list):
        for item in node:
            yield from _organization_values(item)
        return
    if not isinstance(node, dict):
        return
    raw_type = node.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    if any(isinstance(item, str) and item.casefold() == "organization" for item in types):
        for key in ("name", "alternateName"):
            value = node.get(key)
            values: Iterable[object] = value if isinstance(value, list) else (value,)
            for item in values:
                if isinstance(item, str) and item.strip():
                    yield item.strip()
    for value in node.values():
        yield from _organization_values(value)


def _claims(soup: BeautifulSoup) -> tuple[set[str], set[str]]:
    claims: set[str] = set()
    organization_claims: set[str] = set()
    if soup.title and (title := soup.title.get_text(" ", strip=True)):
        claims.add(title)
    for selector in ('meta[property="og:site_name"]', 'meta[name="application-name"]'):
        for tag in soup.select(selector):
            if value := tag.get("content"):
                claims.add(str(value).strip())
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = set(_organization_values(payload))
        organization_claims.update(values)
        claims.update(values)
    return claims, organization_claims


def company_claims_from_html(html: str) -> tuple[str, ...]:
    """Extract minimal company claims from page metadata without page prose."""
    claims, _ = _claims(BeautifulSoup(html, "html.parser"))
    return tuple(sorted((claim for claim in claims if claim), key=str.casefold))


def page_matches_company(company: str, url: str, html: str) -> bool:
    """Return true only when metadata or the corporate domain binds the company."""
    claims, organization_claims = _claims(BeautifulSoup(html, "html.parser"))
    normalized_company = normalize_company_name(company)
    if any(normalize_company_name(claim) == normalized_company for claim in claims):
        return True
    company_words = set(_company_words(company))
    for claim in organization_claims:
        claim_words = _company_words(claim)
        if (
            len(claim_words) > 1
            and company_words & set(claim_words)
            and not company_names_match(company, claim)
        ):
            return False
    if any(company_names_match(company, claim) for claim in claims):
        return True
    domain = registrable_domain(url)
    label = domain.split(".", 1)[0] if domain else ""
    return company_names_match(company, label)
