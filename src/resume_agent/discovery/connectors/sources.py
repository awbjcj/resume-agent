"""Source identity and read-only projections over connector config."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from resume_agent.config import Settings
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.detect import identify_host
from resume_agent.discovery.scraper.recipe_store import host_key


@dataclass(frozen=True)
class SourceView:
    id: str
    kind: str
    type: str
    display_name: str
    enabled: bool
    pullable: bool
    detail: str
    limit: int | None = None


def company_url_id(url: str) -> str:
    return "companies:" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


def scrape_target_id(url: str) -> str:
    return f"scrape:{host_key(url)}"


def _company_kind(url: str) -> str:
    target = identify_host(url)
    return target.ats if target is not None else "companies"


def list_source_views(config: ConnectorsConfig, settings: Settings) -> list[SourceView]:
    views: list[SourceView] = []

    for board in config.greenhouse.boards:
        enabled = config.greenhouse.enabled and board.enabled
        views.append(
            SourceView(
                id=f"greenhouse:{board.token}",
                kind="greenhouse",
                type="board",
                display_name=board.display(),
                enabled=enabled,
                pullable=enabled,
                detail=board.token,
                limit=board.limit,
            )
        )

    for board in config.lever.boards:
        enabled = config.lever.enabled and board.enabled
        views.append(
            SourceView(
                id=f"lever:{board.token}",
                kind="lever",
                type="board",
                display_name=board.display(),
                enabled=enabled,
                pullable=enabled,
                detail=board.token,
                limit=board.limit,
            )
        )

    for entry in config.companies.urls:
        enabled = config.companies.enabled and entry.enabled
        target = identify_host(entry.url)
        views.append(
            SourceView(
                id=company_url_id(entry.url),
                kind=_company_kind(entry.url),
                type="board",
                display_name=entry.label or entry.url,
                enabled=enabled,
                pullable=enabled,
                # Known ATS sources use the same compact board identity as the
                # dedicated Greenhouse and Lever rows. Keep the URL only for
                # generic careers pages where there is no canonical token.
                detail=target.token
                if target is not None and target.token
                else entry.url,
                limit=entry.limit,
            )
        )

    for target in config.scrape.targets:
        enabled = config.scrape.enabled and target.enabled
        views.append(
            SourceView(
                id=scrape_target_id(target.url),
                kind="scrape",
                type="board",
                display_name=target.label or target.url,
                enabled=enabled,
                pullable=enabled,
                detail=target.url,
                limit=target.limit,
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
            limit=config.adzuna.limit,
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
            limit=config.remoteok.limit,
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
            limit=config.linkedin.limit,
        )
    )
    return views
