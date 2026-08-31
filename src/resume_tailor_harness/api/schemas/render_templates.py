"""Wire models for the rendering template picker."""

from typing import Literal

from resume_tailor_harness.api.schemas.base import CamelModel


class TemplateListItem(CamelModel):
    id: str
    title: str
    description: str
    kind: Literal["bundled", "custom"]
