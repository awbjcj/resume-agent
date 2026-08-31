from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from resume_tailor_harness.config import load_yaml
from resume_tailor_harness.models.base import ExtensibleModel


class GreenhouseBoard(ExtensibleModel):
    token: str
    company: str | None = None
    enabled: bool = True
    limit: int | None = Field(default=None, ge=1)

    def display(self) -> str:
        return self.company or self.token


class GreenhouseConfig(ExtensibleModel):
    enabled: bool = False
    boards: list[GreenhouseBoard] = Field(default_factory=list)


class LeverBoard(ExtensibleModel):
    token: str
    company: str | None = None
    enabled: bool = True
    limit: int | None = Field(default=None, ge=1)

    def display(self) -> str:
        return self.company or self.token


class LeverConfig(ExtensibleModel):
    enabled: bool = False
    boards: list[LeverBoard] = Field(default_factory=list)


class AshbyBoard(ExtensibleModel):
    token: str
    company: str | None = None
    enabled: bool = True
    limit: int | None = Field(default=None, ge=1)

    def display(self) -> str:
        return self.company or self.token


class AshbyConfig(ExtensibleModel):
    enabled: bool = False
    boards: list[AshbyBoard] = Field(default_factory=list)


class NativeUrlBoard(ExtensibleModel):
    url: str
    company: str | None = None
    enabled: bool = True
    limit: int | None = Field(default=None, ge=1)

    def display(self) -> str:
        return self.company or self.url


class NativeUrlConfig(ExtensibleModel):
    enabled: bool = False
    boards: list[NativeUrlBoard] = Field(default_factory=list)


class AdzunaConfig(ExtensibleModel):
    enabled: bool = False
    country: str = "us"
    limit: int | None = Field(default=None, ge=1)


class RemoteOKConfig(ExtensibleModel):
    enabled: bool = False
    limit: int | None = Field(default=None, ge=1)


class LinkedInConfig(ExtensibleModel):
    enabled: bool = False
    limit: int | None = Field(default=None, ge=1)


class CompanyUrl(ExtensibleModel):
    url: str
    enabled: bool = True
    label: str | None = None
    limit: int | None = Field(default=None, ge=1)


class CompaniesConfig(ExtensibleModel):
    enabled: bool = False
    urls: list[CompanyUrl] = Field(default_factory=list)

    @field_validator("urls", mode="before")
    @classmethod
    def _coerce_bare_strings(cls, value):
        if isinstance(value, list):
            return [{"url": item} if isinstance(item, str) else item for item in value]
        return value


class ScrapeTarget(ExtensibleModel):
    url: str
    enabled: bool = True
    label: str | None = None
    limit: int | None = Field(default=None, ge=1)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("scrape target must be an absolute http(s) URL")
        return normalized


class ScrapeConfig(ExtensibleModel):
    enabled: bool = False
    targets: list[ScrapeTarget] = Field(default_factory=list)

    @field_validator("targets", mode="before")
    @classmethod
    def _coerce_bare_strings(cls, value):
        if isinstance(value, list):
            return [{"url": item} if isinstance(item, str) else item for item in value]
        return value

    @model_validator(mode="after")
    def _unique_recipe_hosts(self) -> Self:
        from resume_tailor_harness.discovery.scraper.recipe_store import host_key

        hosts = [host_key(target.url) for target in self.targets]
        if len(hosts) != len(set(hosts)):
            raise ValueError("scrape config supports one target per host")
        return self


class ConnectorsConfig(ExtensibleModel):
    greenhouse: GreenhouseConfig = Field(default_factory=GreenhouseConfig)
    lever: LeverConfig = Field(default_factory=LeverConfig)
    ashby: AshbyConfig = Field(default_factory=AshbyConfig)
    workday: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    tesla: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    google: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    smartrecruiters: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    workable: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    recruitee: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    personio: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    breezy: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    jazzhr: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    bamboohr: NativeUrlConfig = Field(default_factory=NativeUrlConfig)
    adzuna: AdzunaConfig = Field(default_factory=AdzunaConfig)
    remoteok: RemoteOKConfig = Field(default_factory=RemoteOKConfig)
    linkedin: LinkedInConfig = Field(default_factory=LinkedInConfig)
    companies: CompaniesConfig = Field(default_factory=CompaniesConfig)
    scrape: ScrapeConfig = Field(default_factory=ScrapeConfig)


def load_connectors_config(path: str | Path) -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(load_yaml(path))
