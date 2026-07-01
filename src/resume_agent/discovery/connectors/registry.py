from resume_agent.config import Settings
from resume_agent.discovery.connectors.adzuna import AdzunaConnector
from resume_agent.discovery.connectors.base import Connector
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.connectors.remoteok import RemoteOKConnector
from resume_agent.discovery.connectors.sources import company_url_id
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper
from resume_agent.discovery.scraper.dashboard import DashboardScraper
from resume_agent.discovery.scraper.recipe_store import host_key


def build_connectors(config: ConnectorsConfig, settings: Settings) -> list[Connector]:
    """Instantiate enabled connectors in canonical dedup order."""
    connectors: list[Connector] = []

    if config.greenhouse.enabled:
        boards = [board for board in config.greenhouse.boards if board.enabled]
        if boards:
            connectors.append(GreenhouseConnector(boards))

    if config.lever.enabled:
        boards = [board for board in config.lever.boards if board.enabled]
        if boards:
            connectors.append(LeverConnector(boards))

    if config.companies.enabled:
        urls = [entry.url for entry in config.companies.urls if entry.enabled]
        if urls:
            connectors.append(CompaniesConnector(urls))

    if config.scrape.enabled:
        targets = [target for target in config.scrape.targets if target.enabled]
        if targets:
            connectors.append(DashboardScraper(targets))

    if config.remoteok.enabled:
        connectors.append(RemoteOKConnector())

    if config.adzuna.enabled and settings.adzuna_app_id and settings.adzuna_app_key:
        connectors.append(
            AdzunaConnector(settings.adzuna_app_id, settings.adzuna_app_key, config.adzuna.country)
        )

    if config.linkedin.enabled:
        connectors.append(build_linkedin_scraper())

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

    def picked(source_id: str, enabled: bool, pullable: bool = True) -> bool:
        if not enabled or not pullable:
            return False
        return selected is None or source_id in selected

    connectors: list[Connector] = []

    if config.greenhouse.enabled:
        for board in config.greenhouse.boards:
            source_id = f"greenhouse:{board.token}"
            if picked(source_id, board.enabled):
                connectors.append(_named(GreenhouseConnector([board]), source_id))

    if config.lever.enabled:
        for board in config.lever.boards:
            source_id = f"lever:{board.token}"
            if picked(source_id, board.enabled):
                connectors.append(_named(LeverConnector([board]), source_id))

    if config.companies.enabled:
        for entry in config.companies.urls:
            source_id = company_url_id(entry.url)
            if picked(source_id, entry.enabled):
                connectors.append(_named(CompaniesConnector([entry.url]), source_id))

    if config.scrape.enabled:
        for target in config.scrape.targets:
            source_id = f"scrape:{host_key(target.url)}"
            if picked(source_id, target.enabled):
                connectors.append(_named(DashboardScraper([target]), source_id))

    if picked("remoteok", config.remoteok.enabled):
        connectors.append(_named(RemoteOKConnector(), "remoteok"))

    adzuna_pullable = bool(settings.adzuna_app_id and settings.adzuna_app_key)
    if picked("adzuna", config.adzuna.enabled, adzuna_pullable):
        connectors.append(
            _named(
                AdzunaConnector(
                    settings.adzuna_app_id,
                    settings.adzuna_app_key,
                    config.adzuna.country,
                ),
                "adzuna",
            )
        )

    if picked("linkedin", config.linkedin.enabled):
        connectors.append(_named(build_linkedin_scraper(), "linkedin"))

    return connectors
