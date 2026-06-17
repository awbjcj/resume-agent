import uuid
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Source(str, Enum):
    """Where an atomic fact originated."""

    resume = "resume"
    github = "github"
    manual = "manual"


def new_id() -> str:
    """Stable, short identifier used for provenance pointers."""
    return uuid.uuid4().hex[:12]


class ExtensibleModel(BaseModel):
    """Base for all domain models.

    - ``schema_version`` enables explicit future migrations.
    - ``extra`` is the escape hatch for experimental fields before they are
      promoted to first-class.
    - ``extra="allow"`` preserves unknown keys so a load->save round-trip of
      newer JSON doesn't silently drop fields the model doesn't know yet.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1


class FactItem(ExtensibleModel):
    """An atomic fact carrying provenance: a stable id + where it came from."""

    id: str = Field(default_factory=new_id)
    source: Source = Source.resume
