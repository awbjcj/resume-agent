"""Shared normalization and retention rules for public-source evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit

from resume_tailor_harness.discovery.source_resolution.identity import registrable_domain

PUBLIC_URL_PATTERN = re.compile(r"https?://[^\s<>\]\[()]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:"


def normalize_http_url(value: str) -> str | None:
    """Return a comparison key for an HTTP(S) URL, excluding fragments."""
    try:
        parsed = urlsplit(value.rstrip(_TRAILING_PUNCTUATION))
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


@dataclass(frozen=True)
class PublicSourceIndex:
    """Map normalized public URLs back to the exact evidence transcript URLs."""

    _exact_by_normalized: dict[str, str]

    @classmethod
    def from_text(cls, text: str) -> PublicSourceIndex:
        return cls.from_urls(PUBLIC_URL_PATTERN.findall(text))

    @classmethod
    def from_urls(cls, urls: Iterable[str]) -> PublicSourceIndex:
        exact_by_normalized: dict[str, str] = {}
        for raw in urls:
            exact = raw.rstrip(_TRAILING_PUNCTUATION)
            normalized = normalize_http_url(exact)
            if normalized is not None:
                exact_by_normalized.setdefault(normalized, exact)
        return cls(exact_by_normalized)

    def resolve(self, value: str) -> str | None:
        normalized = normalize_http_url(value)
        return (
            self._exact_by_normalized.get(normalized)
            if normalized is not None
            else None
        )

    def retain(self, values: Iterable[str]) -> list[str]:
        """Return sorted, deduplicated exact URLs present in this index."""
        return sorted(
            {
                exact
                for value in values
                if (exact := self.resolve(value)) is not None
            }
        )

    @staticmethod
    def authorities(urls: Iterable[str]) -> set[str]:
        return {
            domain
            for url in urls
            if (domain := registrable_domain(url))
        }


def retain_frozen_citations(
    requested: Iterable[str], allowed_urls: Iterable[str]
) -> list[str]:
    """Retain only exact URLs from an already-frozen evidence snapshot."""
    allowed = set(allowed_urls)
    return sorted({value for value in requested if value in allowed})
