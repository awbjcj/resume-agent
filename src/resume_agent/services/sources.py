"""Source Manager use-case layer over connectors.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from resume_agent.config import Settings, get_settings
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import (
    AshbyBoard,
    CompanyUrl,
    ConnectorsConfig,
    GreenhouseBoard,
    LeverBoard,
    NativeUrlBoard,
    load_connectors_config,
)
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.connectors.sources import (
    SourceView,
    company_url_id,
    list_source_views,
    native_url_id,
    NATIVE_URL_KINDS,
    scrape_target_id,
)
from resume_agent.discovery.search_config import load_search_config
from resume_agent.services.discovery import DEFAULT_CONNECTORS, DEFAULT_SEARCH

_PREVIEW_LIMIT = 50
_UNSET = object()


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
        config.greenhouse.boards.append(
            GreenhouseBoard(token=target.token, company=label)
        )
        new_id = f"greenhouse:{target.token}"
    elif target.ats == "lever" and target.token:
        if any(board.token == target.token for board in config.lever.boards):
            raise SourceError(f"Lever board '{target.token}' is already a source.")
        config.lever.enabled = True
        config.lever.boards.append(LeverBoard(token=target.token, company=label))
        new_id = f"lever:{target.token}"
    elif target.ats == "ashby" and target.token:
        if any(board.token == target.token for board in config.ashby.boards):
            raise SourceError(f"Ashby board '{target.token}' is already a source.")
        config.ashby.enabled = True
        config.ashby.boards.append(AshbyBoard(token=target.token, company=label))
        new_id = f"ashby:{target.token}"
    elif target.ats in NATIVE_URL_KINDS:
        section = getattr(config, target.ats)
        if any(board.url == url for board in section.boards):
            raise SourceError(f"This {target.ats.title()} board is already a source.")
        section.enabled = True
        section.boards.append(NativeUrlBoard(url=url, company=label))
        new_id = native_url_id(target.ats, url)
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
    return patch_source(source_id, enabled=enabled, connectors_path=connectors_path)


def set_source_limit(
    source_id: str,
    limit: int | None,
    connectors_path: str = DEFAULT_CONNECTORS,
) -> SourceView:
    return patch_source(source_id, limit=limit, connectors_path=connectors_path)


def patch_source(
    source_id: str,
    *,
    enabled: bool | object = _UNSET,
    limit: int | None | object = _UNSET,
    connectors_path: str = DEFAULT_CONNECTORS,
) -> SourceView:
    """Apply all requested source changes to one config snapshot and save once."""
    if enabled is _UNSET and limit is _UNSET:
        raise SourceError("Provide enabled and/or limit.")
    if enabled is not _UNSET and not isinstance(enabled, bool):
        raise SourceError("enabled must be true or false.")
    if limit is not _UNSET and (
        isinstance(limit, bool)
        or (limit is not None and (not isinstance(limit, int) or limit < 1))
    ):
        raise SourceError("limit must be a positive integer or null.")

    config = load_connectors_config(connectors_path)
    found = True
    if enabled is not _UNSET:
        found = _apply_enabled(config, source_id, cast(bool, enabled))
    if limit is not _UNSET:
        found = _apply_limit(config, source_id, cast(int | None, limit)) and found
    if not found:
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
            if enabled:
                config.greenhouse.enabled = True
            board.enabled = enabled
            return True
    for board in config.lever.boards:
        if f"lever:{board.token}" == source_id:
            if enabled:
                config.lever.enabled = True
            board.enabled = enabled
            return True
    for board in config.ashby.boards:
        if f"ashby:{board.token}" == source_id:
            if enabled:
                config.ashby.enabled = True
            board.enabled = enabled
            return True
    for kind in NATIVE_URL_KINDS:
        section = getattr(config, kind)
        for board in section.boards:
            if native_url_id(kind, board.url) == source_id:
                if enabled:
                    section.enabled = True
                board.enabled = enabled
                return True
    for entry in config.companies.urls:
        if company_url_id(entry.url) == source_id:
            if enabled:
                config.companies.enabled = True
            entry.enabled = enabled
            return True
    for target in config.scrape.targets:
        if scrape_target_id(target.url) == source_id:
            if enabled:
                config.scrape.enabled = True
            target.enabled = enabled
            return True
    return False


def _apply_limit(config: ConnectorsConfig, source_id: str, limit: int | None) -> bool:
    if source_id == "adzuna":
        config.adzuna.limit = limit
        return True
    if source_id == "remoteok":
        config.remoteok.limit = limit
        return True
    if source_id == "linkedin":
        config.linkedin.limit = limit
        return True
    for board in config.greenhouse.boards:
        if f"greenhouse:{board.token}" == source_id:
            board.limit = limit
            return True
    for board in config.lever.boards:
        if f"lever:{board.token}" == source_id:
            board.limit = limit
            return True
    for board in config.ashby.boards:
        if f"ashby:{board.token}" == source_id:
            board.limit = limit
            return True
    for kind in NATIVE_URL_KINDS:
        for board in getattr(config, kind).boards:
            if native_url_id(kind, board.url) == source_id:
                board.limit = limit
                return True
    for entry in config.companies.urls:
        if company_url_id(entry.url) == source_id:
            entry.limit = limit
            return True
    for target in config.scrape.targets:
        if scrape_target_id(target.url) == source_id:
            target.limit = limit
            return True
    return False


def _remove(config: ConnectorsConfig, source_id: str) -> bool:
    before = len(config.greenhouse.boards)
    config.greenhouse.boards = [
        board
        for board in config.greenhouse.boards
        if f"greenhouse:{board.token}" != source_id
    ]
    if len(config.greenhouse.boards) != before:
        return True

    before = len(config.lever.boards)
    config.lever.boards = [
        board for board in config.lever.boards if f"lever:{board.token}" != source_id
    ]
    if len(config.lever.boards) != before:
        return True

    before = len(config.ashby.boards)
    config.ashby.boards = [
        board for board in config.ashby.boards if f"ashby:{board.token}" != source_id
    ]
    if len(config.ashby.boards) != before:
        return True

    for kind in NATIVE_URL_KINDS:
        section = getattr(config, kind)
        before = len(section.boards)
        section.boards = [
            board
            for board in section.boards
            if native_url_id(kind, board.url) != source_id
        ]
        if len(section.boards) != before:
            return True

    before = len(config.companies.urls)
    config.companies.urls = [
        entry
        for entry in config.companies.urls
        if company_url_id(entry.url) != source_id
    ]
    if len(config.companies.urls) != before:
        return True

    before = len(config.scrape.targets)
    config.scrape.targets = [
        target
        for target in config.scrape.targets
        if scrape_target_id(target.url) != source_id
    ]
    return len(config.scrape.targets) != before
