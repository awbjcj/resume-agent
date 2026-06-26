"""Source identity and read-only projections over connector config."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.detect import identify_host


@dataclass(frozen=True)
class SourceView:
    id: str
    kind: str
    type: str
    display_name: str
    enabled: bool
    pullable: bool
    detail: str


def company_url_id(url: str) -> str:
    return "companies:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


def _company_kind(url: str) -> str:
    target = identify_host(url)
    return target.ats if target is not None else "companies"


def list_source_views(config: ConnectorsConfig, settings: Settings) -> list[SourceView]:
    views: list[SourceView] = []

    for board in config.greenhouse.boards:
        views.append(
            SourceView(
                id=f"greenhouse:{board.token}",
                kind="greenhouse",
                type="board",
                display_name=board.display(),
                enabled=board.enabled,
                pullable=board.enabled,
                detail=board.token,
            )
        )

    for board in config.lever.boards:
        views.append(
            SourceView(
                id=f"lever:{board.token}",
                kind="lever",
                type="board",
                display_name=board.display(),
                enabled=board.enabled,
                pullable=board.enabled,
                detail=board.token,
            )
        )

    for entry in config.companies.urls:
        views.append(
            SourceView(
                id=company_url_id(entry.url),
                kind=_company_kind(entry.url),
                type="board",
                display_name=entry.label or entry.url,
                enabled=entry.enabled,
                pullable=entry.enabled,
                detail=entry.url,
            )
        )

    adzuna_key_set = bool(settings.adzuna_app_id and settings.adzuna_app_key)
    views.append(
        SourceView(
            id="adzuna",
            kind="adzuna",
            type="aggregator",
            display_name="Adzuna",
            enabled=config.adzuna.enabled,
            pullable=config.adzuna.enabled and adzuna_key_set,
            detail=f"{config.adzuna.country.upper()} - "
            f"{'key set' if adzuna_key_set else 'no API key'}",
        )
    )
    views.append(
        SourceView(
            id="remoteok",
            kind="remoteok",
            type="aggregator",
            display_name="RemoteOK",
            enabled=config.remoteok.enabled,
            pullable=config.remoteok.enabled,
            detail="aggregator",
        )
    )
    views.append(
        SourceView(
            id="linkedin",
            kind="linkedin",
            type="aggregator",
            display_name="LinkedIn",
            enabled=config.linkedin.enabled,
            pullable=config.linkedin.enabled,
            detail="scraper",
        )
    )
    return views
