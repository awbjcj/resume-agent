"""ConfigStore seam: domain name -> typed document, storage behind a protocol.

YamlConfigStore is the only implementation today (YAML/markdown files under
config/). A future DbConfigStore implements the same protocol; routers depend
only on get/put, so the HTTP contract never learns about storage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import yaml

from resume_agent.api.schemas.base import CamelModel
from resume_agent.api.schemas.config import DOMAIN_SCHEMAS, StyleGuideDoc


class ConfigStore(Protocol):
    def get(self, domain: str) -> CamelModel: ...
    def put(self, domain: str, model: CamelModel) -> CamelModel: ...


# domain -> filename; style_guide is plain markdown, everything else YAML.
_FILES: dict[str, str] = {
    "search": "search.yaml",
    "review": "review.yaml",
    "review_deep": "review_deep.yaml",
    "prune": "prune.yaml",
    "render": "render.yaml",
    "style_guide": "style_guide.md",
    "profile": "profile_sources.yaml",
}


# Keys that must be dropped rather than preserved, because a newer key on the
# same document now owns their meaning. Preservation is otherwise the rule.
#
# `match_plan_enabled` is the deprecated spelling of
# `evidence_portfolio_enabled`, and `ReviewConfig` *rejects* a file where the
# two disagree. Carrying the stale one forward would therefore turn a UI toggle
# into an unloadable config: the DTO writes the new key as `true`, the old key
# survives as `false`, and the next tailor run raises on config load.
_SUPERSEDED_KEYS: dict[str, tuple[str, ...]] = {
    "review": ("match_plan_enabled",),
    "review_deep": ("match_plan_enabled",),
}


def _atomic_write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


class YamlConfigStore:
    def __init__(self, config_dir: Path | str = "config") -> None:
        self.config_dir = Path(config_dir)

    def _path(self, domain: str) -> Path:
        return self.config_dir / _FILES[domain]  # KeyError for unknown domains

    def get(self, domain: str) -> CamelModel:
        schema = DOMAIN_SCHEMAS[domain]
        path = self._path(domain)
        if schema is StyleGuideDoc:
            content = path.read_text(encoding="utf-8") if path.exists() else ""
            return StyleGuideDoc(content=content)
        if not path.exists():
            return schema()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return schema.model_validate(data)

    def put(self, domain: str, model: CamelModel) -> CamelModel:
        schema = DOMAIN_SCHEMAS[domain]
        doc = schema.model_validate(model.model_dump())
        path = self._path(domain)
        if schema is StyleGuideDoc:
            _atomic_write(path, doc.content)  # type: ignore[attr-defined]
            return doc
        payload = doc.model_dump(mode="json")
        # Write the document OVER the file's existing keys rather than replacing
        # the file with it. A DTO deliberately does not declare every key its
        # YAML may hold -- rendering keeps `template_path`/`output_dir` as
        # runtime-only CLI fields, profile sources keeps the wizard's
        # `resume_path` -- and a wholesale rewrite silently deleted each of them
        # the first time an unrelated field on that page was saved. Merging is
        # shallow on purpose: a key the DTO *does* own is replaced outright, so
        # removing an item from a list still removes it.
        if path.exists():
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if isinstance(existing, dict):
                preserved = {
                    key: value
                    for key, value in existing.items()
                    if key not in payload
                    and key not in _SUPERSEDED_KEYS.get(domain, ())
                }
                payload = {**preserved, **payload}
        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        _atomic_write(path, text)
        return doc
