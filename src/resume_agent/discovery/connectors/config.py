from pathlib import Path

from pydantic import Field

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class GreenhouseBoard(ExtensibleModel):
    token: str
    company: str | None = None

    def display(self) -> str:
        return self.company or self.token


class GreenhouseConfig(ExtensibleModel):
    enabled: bool = False
    boards: list[GreenhouseBoard] = Field(default_factory=list)


class AdzunaConfig(ExtensibleModel):
    enabled: bool = False
    country: str = "us"


class RemoteOKConfig(ExtensibleModel):
    enabled: bool = False


class LinkedInConfig(ExtensibleModel):
    enabled: bool = False


class ConnectorsConfig(ExtensibleModel):
    greenhouse: GreenhouseConfig = Field(default_factory=GreenhouseConfig)
    adzuna: AdzunaConfig = Field(default_factory=AdzunaConfig)
    remoteok: RemoteOKConfig = Field(default_factory=RemoteOKConfig)
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)


def load_connectors_config(path: str | Path) -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(load_yaml(path))
