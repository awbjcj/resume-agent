from pathlib import Path

from pydantic import Field, field_validator

from resume_agent.config import load_yaml
from resume_agent.models.base import ExtensibleModel


class GreenhouseBoard(ExtensibleModel):
    token: str
    company: str | None = None
    enabled: bool = True

    def display(self) -> str:
        return self.company or self.token


class GreenhouseConfig(ExtensibleModel):
    enabled: bool = False
    boards: list[GreenhouseBoard] = Field(default_factory=list)


class LeverBoard(ExtensibleModel):
    token: str
    company: str | None = None
    enabled: bool = True

    def display(self) -> str:
        return self.company or self.token


class LeverConfig(ExtensibleModel):
    enabled: bool = False
    boards: list[LeverBoard] = Field(default_factory=list)


class AdzunaConfig(ExtensibleModel):
    enabled: bool = False
    country: str = "us"


class RemoteOKConfig(ExtensibleModel):
    enabled: bool = False


class LinkedInConfig(ExtensibleModel):
    enabled: bool = False


class CompanyUrl(ExtensibleModel):
    url: str
    enabled: bool = True
    label: str | None = None


class CompaniesConfig(ExtensibleModel):
    enabled: bool = False
    urls: list[CompanyUrl] = Field(default_factory=list)

    @field_validator("urls", mode="before")
    @classmethod
    def _coerce_bare_strings(cls, value):
        if isinstance(value, list):
            return [{"url": item} if isinstance(item, str) else item for item in value]
        return value


class ConnectorsConfig(ExtensibleModel):
    greenhouse: GreenhouseConfig = Field(default_factory=GreenhouseConfig)
    lever: LeverConfig = Field(default_factory=LeverConfig)
    adzuna: AdzunaConfig = Field(default_factory=AdzunaConfig)
    remoteok: RemoteOKConfig = Field(default_factory=RemoteOKConfig)
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)
    companies: CompaniesConfig = Field(default_factory=CompaniesConfig)


def load_connectors_config(path: str | Path) -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(load_yaml(path))
