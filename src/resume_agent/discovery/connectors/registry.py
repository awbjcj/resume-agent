from resume_agent.config import Settings
from resume_agent.discovery.connectors.adzuna import AdzunaConnector
from resume_agent.discovery.connectors.base import Connector
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.greenhouse import GreenhouseConnector
from resume_agent.discovery.connectors.lever import LeverConnector
from resume_agent.discovery.connectors.remoteok import RemoteOKConnector
from resume_agent.discovery.scraper.linkedin import build_linkedin_scraper


def build_connectors(config: ConnectorsConfig, settings: Settings) -> list[Connector]:
    """Instantiate enabled connectors in canonical dedup order."""
    connectors: list[Connector] = []

    if config.greenhouse.enabled and config.greenhouse.boards:
        connectors.append(GreenhouseConnector(config.greenhouse.boards))

    if config.lever.enabled and config.lever.boards:
        connectors.append(LeverConnector(config.lever.boards))

    if config.companies.enabled and config.companies.urls:
        connectors.append(CompaniesConnector(config.companies.urls))

    if config.remoteok.enabled:
        connectors.append(RemoteOKConnector())

    if config.adzuna.enabled and settings.adzuna_app_id and settings.adzuna_app_key:
        connectors.append(
            AdzunaConnector(settings.adzuna_app_id, settings.adzuna_app_key, config.adzuna.country)
        )

    if config.linkedin.enabled:
        connectors.append(build_linkedin_scraper())

    return connectors
