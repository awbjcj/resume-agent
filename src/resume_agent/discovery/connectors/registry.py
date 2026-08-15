from dataclasses import dataclass, field
from typing import Any, Callable

from resume_agent.config import Settings
from resume_agent.discovery.connectors.adzuna import AdzunaConnector
from resume_agent.discovery.connectors.ashby import AshbyConnector
from resume_agent.discovery.connectors.base import Connector, FetchResult
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import (
    AshbyBoard,
    CompanyUrl,
    ConnectorsConfig,
    GreenhouseBoard,
    LeverBoard,
    NativeUrlBoard,
    ScrapeTarget,
)
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.connectors.remoteok import RemoteOKConnector
from resume_agent.discovery.connectors.sources import (
    NATIVE_URL_KINDS,
    company_url_id,
    native_url_id,
    scrape_target_id,
)
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
from resume_agent.discovery.scraper.dashboard import DashboardScraper
from resume_agent.discovery.source_resolution.catalog import BoardFamily, board_family

_BROWSER_DISABLED = "requires a local browser (browser_enabled=false)"


class _BrowserDisabledConnector:
    concurrent_fetch = True

    def __init__(self, name: str, failure_keys: list[str]):
        self.name = name
        self.failure_keys = failure_keys

    def fetch(self, search, limit=None, skip_seen=None) -> FetchResult:
        return FetchResult(
            jobs=[],
            failures={key: _BROWSER_DISABLED for key in self.failure_keys},
        )


@dataclass(frozen=True)
class ConnectorUnit:
    """One pullable sub-source of a connector kind (a board, URL, target, or the
    whole singleton), addressable by its stable source id."""

    source_id: str
    enabled: bool
    payload: Any  # board / url / target object; None for singleton kinds


@dataclass(frozen=True)
class ConnectorSpec:
    """Everything the registry knows about one connector kind.

    ``build`` receives the enabled payloads — all of them for the aggregate
    builder, exactly one for the per-source builder — so both public builders
    collapse to loops over this table. Table order is the canonical dedup order.

    The unit-addressing fields let Source Manager CRUD locate and mutate config
    units without re-enumerating connector kinds.
    """

    kind: str
    section_enabled: Callable[[ConnectorsConfig], bool]
    section: Callable[[ConnectorsConfig], Any]
    units: Callable[[ConnectorsConfig], list[ConnectorUnit]]
    build: Callable[[list[Any], ConnectorsConfig, Settings], Connector]
    pullable: Callable[[Settings], bool] = field(default=lambda settings: True)
    unit_items: Callable[[ConnectorsConfig], list[Any]] | None = None
    admits: Callable[[AtsTarget | None], bool] = field(default=lambda target: True)
    new_unit: (
        Callable[[AtsTarget | None, str, str | None], tuple[str, Any]] | None
    ) = None
    discovery: BoardFamily | None = None


def _token_admits(target: AtsTarget | None) -> bool:
    return target is not None and bool(target.token)


def _token_unit(kind: str, model, target: AtsTarget | None, label: str | None):
    if not _token_admits(target):
        raise ValueError(f"{kind} sources require a board token")
    assert target is not None
    return f"{kind}:{target.token}", model(token=target.token, company=label)


def _native_url_spec(kind: str) -> ConnectorSpec:
    return ConnectorSpec(
        kind=kind,
        section_enabled=lambda c: getattr(c, kind).enabled,
        section=lambda c: getattr(c, kind),
        units=lambda c: [
            ConnectorUnit(native_url_id(kind, board.url), board.enabled, board)
            for board in getattr(c, kind).boards
        ],
        build=lambda payloads, c, s: _named(
            CompaniesConnector(payloads, browser_enabled=s.browser_enabled), kind
        ),
        unit_items=lambda c: getattr(c, kind).boards,
        new_unit=lambda target, url, label: (
            native_url_id(kind, url),
            NativeUrlBoard(url=url, company=label),
        ),
        discovery=board_family(kind),
    )


CONNECTOR_SPECS: tuple[ConnectorSpec, ...] = (
    ConnectorSpec(
        kind="greenhouse",
        section_enabled=lambda c: c.greenhouse.enabled,
        section=lambda c: c.greenhouse,
        units=lambda c: [
            ConnectorUnit(f"greenhouse:{b.token}", b.enabled, b)
            for b in c.greenhouse.boards
        ],
        build=lambda payloads, c, s: GreenhouseConnector(payloads),
        unit_items=lambda c: c.greenhouse.boards,
        admits=_token_admits,
        new_unit=lambda target, url, label: _token_unit(
            "greenhouse", GreenhouseBoard, target, label
        ),
        discovery=board_family("greenhouse"),
    ),
    ConnectorSpec(
        kind="lever",
        section_enabled=lambda c: c.lever.enabled,
        section=lambda c: c.lever,
        units=lambda c: [
            ConnectorUnit(f"lever:{b.token}", b.enabled, b) for b in c.lever.boards
        ],
        build=lambda payloads, c, s: LeverConnector(payloads),
        unit_items=lambda c: c.lever.boards,
        admits=_token_admits,
        new_unit=lambda target, url, label: _token_unit(
            "lever", LeverBoard, target, label
        ),
        discovery=board_family("lever"),
    ),
    ConnectorSpec(
        kind="ashby",
        section_enabled=lambda c: c.ashby.enabled,
        section=lambda c: c.ashby,
        units=lambda c: [
            ConnectorUnit(f"ashby:{b.token}", b.enabled, b) for b in c.ashby.boards
        ],
        build=lambda payloads, c, s: AshbyConnector(payloads),
        unit_items=lambda c: c.ashby.boards,
        admits=_token_admits,
        new_unit=lambda target, url, label: _token_unit(
            "ashby", AshbyBoard, target, label
        ),
        discovery=board_family("ashby"),
    ),
    *(_native_url_spec(kind) for kind in NATIVE_URL_KINDS),
    ConnectorSpec(
        kind="companies",
        section_enabled=lambda c: c.companies.enabled,
        section=lambda c: c.companies,
        units=lambda c: [
            ConnectorUnit(company_url_id(e.url), e.enabled, e) for e in c.companies.urls
        ],
        build=lambda payloads, c, s: CompaniesConnector(
            payloads, browser_enabled=s.browser_enabled
        ),
        unit_items=lambda c: c.companies.urls,
        new_unit=lambda target, url, label: (
            company_url_id(url),
            CompanyUrl(url=url, label=label),
        ),
    ),
    ConnectorSpec(
        kind="scrape",
        section_enabled=lambda c: c.scrape.enabled,
        section=lambda c: c.scrape,
        units=lambda c: [
            ConnectorUnit(scrape_target_id(t.url), t.enabled, t)
            for t in c.scrape.targets
        ],
        build=lambda payloads, c, s: (
            DashboardScraper(payloads)
            if s.browser_enabled
            else _BrowserDisabledConnector(
                "scrape", [target.url for target in payloads]
            )
        ),
        unit_items=lambda c: c.scrape.targets,
        new_unit=lambda target, url, label: (
            scrape_target_id(url),
            ScrapeTarget(url=url, label=label),
        ),
    ),
    ConnectorSpec(
        kind="remoteok",
        section_enabled=lambda c: c.remoteok.enabled,
        section=lambda c: c.remoteok,
        units=lambda c: [ConnectorUnit("remoteok", c.remoteok.enabled, None)],
        build=lambda payloads, c, s: RemoteOKConnector(
            configured_limit=c.remoteok.limit
        ),
    ),
    ConnectorSpec(
        kind="adzuna",
        section_enabled=lambda c: c.adzuna.enabled,
        section=lambda c: c.adzuna,
        units=lambda c: [ConnectorUnit("adzuna", c.adzuna.enabled, None)],
        build=lambda payloads, c, s: AdzunaConnector(
            s.adzuna_app_id,
            s.adzuna_app_key,
            c.adzuna.country,
            configured_limit=c.adzuna.limit,
            enrich_details=s.browser_enabled,
        ),
        pullable=lambda s: bool(s.adzuna_app_id and s.adzuna_app_key),
    ),
    ConnectorSpec(
        kind="linkedin",
        section_enabled=lambda c: c.linkedin.enabled,
        section=lambda c: c.linkedin,
        units=lambda c: [ConnectorUnit("linkedin", c.linkedin.enabled, None)],
        build=lambda payloads, c, s: (
            build_linkedin_scraper(configured_limit=c.linkedin.limit)
            if s.browser_enabled
            else _BrowserDisabledConnector("linkedin", ["linkedin"])
        ),
    ),
)

_SPEC_BY_KIND = {spec.kind: spec for spec in CONNECTOR_SPECS}


def discoverable_board_families() -> tuple[BoardFamily, ...]:
    """Catalog-backed generic ATS families that have a connector registration."""
    return tuple(
        family
        for spec in CONNECTOR_SPECS
        if (family := spec.discovery) is not None
    )


def spec_for(kind: str) -> ConnectorSpec | None:
    return _SPEC_BY_KIND.get(kind)


def find_unit(
    config: ConnectorsConfig, source_id: str
) -> tuple[ConnectorSpec, Any] | None:
    """Locate one source unit by stable id; payload is None for singleton kinds."""
    for spec in CONNECTOR_SPECS:
        for unit in spec.units(config):
            if unit.source_id == source_id:
                return spec, unit.payload
    return None


def build_connectors(config: ConnectorsConfig, settings: Settings) -> list[Connector]:
    """Instantiate enabled connectors in canonical dedup order."""
    connectors: list[Connector] = []
    for spec in CONNECTOR_SPECS:
        if not spec.section_enabled(config) or not spec.pullable(settings):
            continue
        payloads = [unit.payload for unit in spec.units(config) if unit.enabled]
        if not payloads:
            continue
        connectors.append(spec.build(payloads, config, settings))
    return connectors


def _named(connector: Connector, source_id: str) -> Connector:
    connector.name = source_id
    return connector


def build_source_connectors(
    config: ConnectorsConfig,
    settings: Settings,
    source_ids: list[str] | None = None,
) -> list[Connector]:
    """Build one connector per enabled, pullable, selected source."""
    selected = set(source_ids) if source_ids is not None else None
    connectors: list[Connector] = []
    for spec in CONNECTOR_SPECS:
        if not spec.section_enabled(config) or not spec.pullable(settings):
            continue
        for unit in spec.units(config):
            if not unit.enabled:
                continue
            if selected is not None and unit.source_id not in selected:
                continue
            connectors.append(
                _named(spec.build([unit.payload], config, settings), unit.source_id)
            )
    return connectors
