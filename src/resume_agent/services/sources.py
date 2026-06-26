"""Source Manager use-case layer over connectors.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from resume_agent.config import Settings, get_settings
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import (
    CompanyUrl,
    ConnectorsConfig,
    GreenhouseBoard,
    LeverBoard,
    load_connectors_config,
)
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.connectors.sources import (
    SourceView,
    company_url_id,
    list_source_views,
)
from resume_agent.discovery.search_config import load_search_config
from resume_agent.services.discovery import DEFAULT_CONNECTORS, DEFAULT_SEARCH

_PREVIEW_LIMIT = 50


class SourceError(Exception):
    """A source mutation the user can fix: unknown, duplicate, or invalid source."""


@dataclass(frozen=True)
class SourcePreview:
    ok: bool
    url: str
    kind: str | None = None
    token: str | None = None
    label: str | None = None
    role_count: int | None = None
    error: str | None = None


def _save(path: str, config: ConnectorsConfig) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(
            config.model_dump(mode="python"),
            stream,
            sort_keys=False,
            allow_unicode=True,
        )
    os.replace(tmp, target)


def list_sources(
    connectors_path: str = DEFAULT_CONNECTORS,
    settings: Settings | None = None,
) -> list[SourceView]:
    config = load_connectors_config(connectors_path)
    return list_source_views(config, settings or get_settings())


def _view(config: ConnectorsConfig, source_id: str) -> SourceView:
    offline_settings = Settings.model_construct()
    for view in list_source_views(config, offline_settings):
        if view.id == source_id:
            return view
    raise SourceError(f"Unknown source '{source_id}'")


def _preview_connector(target: AtsTarget, url: str):
    if target.ats == "greenhouse" and target.token:
        return GreenhouseConnector([GreenhouseBoard(token=target.token)])
    if target.ats == "lever" and target.token:
        return LeverConnector([LeverBoard(token=target.token)])
    return CompaniesConnector([url])


def preview_source(
    url: str,
    label: str | None = None,
    search_path: str = DEFAULT_SEARCH,
) -> SourcePreview:
    target = detect_ats(url)
    if target is None:
        return SourcePreview(
            ok=False,
            url=url,
            error="Could not detect a known ATS behind this URL.",
        )

    try:
        result = _preview_connector(target, url).fetch(
            load_search_config(search_path),
            limit=_PREVIEW_LIMIT,
        )
    except Exception as exc:  # noqa: BLE001 - preview returns errors instead of raising.
        return SourcePreview(
            ok=False,
            url=url,
            kind=target.ats,
            token=target.token or None,
            error=f"Could not reach this source: {type(exc).__name__}",
        )

    if result.failures and not result.jobs:
        reason = "; ".join(result.failures.values())
        return SourcePreview(
            ok=False,
            url=url,
            kind=target.ats,
            token=target.token or None,
            error=reason,
        )

    return SourcePreview(
        ok=True,
        url=url,
        kind=target.ats,
        token=target.token or None,
        label=label,
        role_count=len(result.jobs),
    )


def add_source(
    url: str,
    label: str | None = None,
    connectors_path: str = DEFAULT_CONNECTORS,
) -> SourceView:
    preview = preview_source(url, label=label)
    if not preview.ok:
        raise SourceError(preview.error or "Could not validate this source.")

    config = load_connectors_config(connectors_path)
    target = detect_ats(url)
    if target is None:
        raise SourceError("Could not detect a known ATS behind this URL.")

    if target.ats == "greenhouse" and target.token:
        if any(board.token == target.token for board in config.greenhouse.boards):
            raise SourceError(f"Greenhouse board '{target.token}' is already a source.")
        config.greenhouse.enabled = True
        config.greenhouse.boards.append(GreenhouseBoard(token=target.token, company=label))
        new_id = f"greenhouse:{target.token}"
    elif target.ats == "lever" and target.token:
        if any(board.token == target.token for board in config.lever.boards):
            raise SourceError(f"Lever board '{target.token}' is already a source.")
        config.lever.enabled = True
        config.lever.boards.append(LeverBoard(token=target.token, company=label))
        new_id = f"lever:{target.token}"
    else:
        if any(entry.url == url for entry in config.companies.urls):
            raise SourceError("This URL is already a source.")
        config.companies.enabled = True
        config.companies.urls.append(CompanyUrl(url=url, label=label))
        new_id = company_url_id(url)

    _save(connectors_path, config)
    return _view(config, new_id)


def set_source_enabled(
    source_id: str,
    enabled: bool,
    connectors_path: str = DEFAULT_CONNECTORS,
) -> SourceView:
    config = load_connectors_config(connectors_path)
    if not _apply_enabled(config, source_id, enabled):
        raise SourceError(f"Unknown source '{source_id}'")
    _save(connectors_path, config)
    return _view(config, source_id)


def remove_source(source_id: str, connectors_path: str = DEFAULT_CONNECTORS) -> None:
    config = load_connectors_config(connectors_path)
    if not _remove(config, source_id):
        raise SourceError(f"Unknown source '{source_id}'")
    _save(connectors_path, config)


def _apply_enabled(config: ConnectorsConfig, source_id: str, enabled: bool) -> bool:
    if source_id == "adzuna":
        config.adzuna.enabled = enabled
        return True
    if source_id == "remoteok":
        config.remoteok.enabled = enabled
        return True
    if source_id == "linkedin":
        config.linkedin.enabled = enabled
        return True

    for board in config.greenhouse.boards:
        if f"greenhouse:{board.token}" == source_id:
            board.enabled = enabled
            return True
    for board in config.lever.boards:
        if f"lever:{board.token}" == source_id:
            board.enabled = enabled
            return True
    for entry in config.companies.urls:
        if company_url_id(entry.url) == source_id:
            entry.enabled = enabled
            return True
    return False


def _remove(config: ConnectorsConfig, source_id: str) -> bool:
    before = len(config.greenhouse.boards)
    config.greenhouse.boards = [
        board for board in config.greenhouse.boards if f"greenhouse:{board.token}" != source_id
    ]
    if len(config.greenhouse.boards) != before:
        return True

    before = len(config.lever.boards)
    config.lever.boards = [
        board for board in config.lever.boards if f"lever:{board.token}" != source_id
    ]
    if len(config.lever.boards) != before:
        return True

    before = len(config.companies.urls)
    config.companies.urls = [
        entry for entry in config.companies.urls if company_url_id(entry.url) != source_id
    ]
    return len(config.companies.urls) != before
