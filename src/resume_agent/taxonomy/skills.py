"""Skill taxonomy: split compound skills and apply a synonym alias map."""

import json
import re
from pathlib import Path

from resume_agent.tracking.match_gap import Canonicalizer, normalize_skill

# Raw tokens that legitimately contain a split delimiter and must stay whole.
PROTECTED_TOKENS: tuple[str, ...] = (
    "CI/CD",
    "A/B testing",
    "TCP/IP",
    "I/O",
    "C/C++",
    "R&D",
)

# Split on comma, semicolon, slash, ampersand, and the words "or"/"and".
_DELIMITERS = re.compile(r"\s*(?:,|;|/|&|\bor\b|\band\b)\s*", re.IGNORECASE)


def split_skill(raw: str) -> list[str]:
    """Split one possibly-compound skill string into atomic skills."""
    text = raw
    placeholders: dict[str, str] = {}
    for i, token in enumerate(PROTECTED_TOKENS):
        marker = f"\x00{i}\x00"
        pattern = re.compile(re.escape(token), re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(marker, text)
            placeholders[marker] = token
    parts = _DELIMITERS.split(text)
    out: list[str] = []
    for part in parts:
        for marker, token in placeholders.items():
            part = part.replace(marker, token)
        part = part.strip()
        if part:
            out.append(part)
    return out


def split_skills(items: list[str]) -> list[str]:
    """Split every item and flatten, de-duplicating while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        for atomic in split_skill(item):
            if atomic not in seen:
                seen.add(atomic)
                out.append(atomic)
    return out


_ALIAS_CACHE: dict[Path, tuple[int, int, dict[str, str]]] = {}


def load_aliases(path: str | Path) -> dict[str, str]:
    """Load the token->canonical map; missing file -> empty (identity).

    Cached on (mtime_ns, size); the returned dict is shared — treat it as
    read-only (merge_aliases already copies before mutating).
    """
    from resume_agent.tenancy.paths import resolve_tenant_path

    p = resolve_tenant_path(path)
    try:
        stat = p.stat()
    except OSError:
        return {}
    resolved = p.resolve()
    cached = _ALIAS_CACHE.get(resolved)
    if cached is not None and (cached[0], cached[1]) == (stat.st_mtime_ns, stat.st_size):
        return cached[2]
    data = json.loads(p.read_text("utf-8"))
    _ALIAS_CACHE[resolved] = (stat.st_mtime_ns, stat.st_size, data)
    return data


def canonical_skill(name: str, aliases: dict[str, str]) -> str:
    """Normalize a skill name, then map it to its canonical token."""
    token = normalize_skill(name)
    return aliases.get(token, token)


def merge_aliases(existing: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Monotonic merge: existing canonical choices win for stability."""
    merged = dict(new)
    merged.update(existing)
    return merged


def refresh_aliases(
    tokens: set[str], canonicalizer: Canonicalizer, path: str | Path
) -> dict[str, str]:
    """Canonicalize the token union, merge into the saved map, write atomically."""
    mapping = canonicalizer(tokens) if tokens else {}
    merged = merge_aliases(load_aliases(path), mapping)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.tmp")
    tmp.write_text(json.dumps(merged, sort_keys=True), "utf-8")
    tmp.replace(p)
    return merged
