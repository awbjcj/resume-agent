import uuid
from enum import Enum
from typing import Any

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
    - ``extra="ignore"`` tolerates unknown keys so older code can load newer
      JSON without crashing.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    extra: dict[str, Any] = Field(default_factory=dict)


class FactItem(ExtensibleModel):
    """An atomic fact carrying provenance: a stable id + where it came from."""

    id: str = Field(default_factory=new_id)
    source: Source = Source.resume
