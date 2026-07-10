from dataclasses import dataclass, field
from typing import Any, Callable

from resume_agent.config import Settings
from resume_agent.discovery.connectors.adzuna import AdzunaConnector
from resume_agent.discovery.connectors.base import Connector, FetchResult
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.connectors.remoteok import RemoteOKConnector
from resume_agent.discovery.connectors.sources import company_url_id, scrape_target_id
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
from resume_agent.discovery.scraper.dashboard import DashboardScraper

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
    """

    kind: str
    section_enabled: Callable[[ConnectorsConfig], bool]
    units: Callable[[ConnectorsConfig], list[ConnectorUnit]]
    build: Callable[[list[Any], ConnectorsConfig, Settings], Connector]
    pullable: Callable[[Settings], bool] = field(default=lambda settings: True)


CONNECTOR_SPECS: tuple[ConnectorSpec, ...] = (
    ConnectorSpec(
        kind="greenhouse",
        section_enabled=lambda c: c.greenhouse.enabled,
        units=lambda c: [
            ConnectorUnit(f"greenhouse:{b.token}", b.enabled, b) for b in c.greenhouse.boards
        ],
        build=lambda payloads, c, s: GreenhouseConnector(payloads),
    ),
    ConnectorSpec(
        kind="lever",
        section_enabled=lambda c: c.lever.enabled,
        units=lambda c: [
            ConnectorUnit(f"lever:{b.token}", b.enabled, b) for b in c.lever.boards
        ],
        build=lambda payloads, c, s: LeverConnector(payloads),
    ),
    ConnectorSpec(
        kind="companies",
        section_enabled=lambda c: c.companies.enabled,
        units=lambda c: [
            ConnectorUnit(company_url_id(e.url), e.enabled, e) for e in c.companies.urls
        ],
        build=lambda payloads, c, s: CompaniesConnector(
            payloads, browser_enabled=s.browser_enabled
        ),
    ),
    ConnectorSpec(
        kind="scrape",
        section_enabled=lambda c: c.scrape.enabled,
        units=lambda c: [
            ConnectorUnit(scrape_target_id(t.url), t.enabled, t) for t in c.scrape.targets
        ],
        build=lambda payloads, c, s: (
            DashboardScraper(payloads)
            if s.browser_enabled
            else _BrowserDisabledConnector(
                "scrape", [target.url for target in payloads]
            )
        ),
    ),
    ConnectorSpec(
        kind="remoteok",
        section_enabled=lambda c: c.remoteok.enabled,
        units=lambda c: [ConnectorUnit("remoteok", c.remoteok.enabled, None)],
        build=lambda payloads, c, s: RemoteOKConnector(
            configured_limit=c.remoteok.limit
        ),
    ),
    ConnectorSpec(
        kind="adzuna",
        section_enabled=lambda c: c.adzuna.enabled,
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
        units=lambda c: [ConnectorUnit("linkedin", c.linkedin.enabled, None)],
        build=lambda payloads, c, s: (
            build_linkedin_scraper(configured_limit=c.linkedin.limit)
            if s.browser_enabled
            else _BrowserDisabledConnector("linkedin", ["linkedin"])
        ),
    ),
)


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
