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
        text = yaml.safe_dump(
            doc.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        )
        _atomic_write(path, text)
        return doc
