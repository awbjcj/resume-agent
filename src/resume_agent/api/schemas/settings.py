"""Wire DTOs for the settings bundle and reset controls."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class SettingsSectionOut(CamelModel):
    id: str
    label: str
    customized: bool


class SettingsSectionList(CamelModel):
    sections: list[SettingsSectionOut]


class BundlePreview(CamelModel):
    version: int
    exported_at: str
    sections: list[SettingsSectionOut]
    unknown_sections: list[str]


class BundleApplied(CamelModel):
    applied: list[str]
