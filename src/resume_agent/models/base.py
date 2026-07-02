import types
import uuid
from enum import Enum
from typing import Any, Union, get_origin

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(str, Enum):
    """Where an atomic fact originated."""

    resume = "resume"
    github = "github"
    manual = "manual"


def new_id() -> str:
    """Stable, short identifier used for provenance pointers."""
    return uuid.uuid4().hex[:12]


_SEQUENCE_ORIGINS = (list, set, frozenset)


def _empty_for_collection(annotation: Any) -> Any | None:
    """Return ``[]``/``{}`` for a non-nullable list/dict annotation, else ``None``.

    Returning ``None`` signals "do not coerce": the field is either not a
    collection or is a union (e.g. ``list[str] | None``) where ``None`` is valid.
    """
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return None
    if origin in _SEQUENCE_ORIGINS:
        return []
    if origin is dict:
        return {}
    return None


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_null_collections(cls, data: Any) -> Any:
        """Coerce an explicit ``null`` to an empty collection for non-nullable fields.

        JSON-mode LLM providers (no native structured outputs) treat an
        ``output_schema`` as a hint, not a grammar, and may emit ``null`` for an
        empty ``list``/``dict`` field even though the schema marks it
        non-nullable -- which otherwise raises and discards the entire structured
        result. None is never valid for such a field, so coercing it to an empty
        collection is strictly safe. Nullable fields (``list[...] | None``) are
        left untouched, since there ``None`` is meaningful. Mirrors the targeted
        coercion on :class:`JobCriteriaExtract`.
        """
        if not isinstance(data, dict):
            return data
        coerced: dict[Any, Any] | None = None
        for name, field in cls.model_fields.items():
            if name not in data or data[name] is not None:
                continue
            empty = _empty_for_collection(field.annotation)
            if empty is None:
                continue
            if coerced is None:
                coerced = dict(data)
            coerced[name] = empty
        return coerced if coerced is not None else data


class FactItem(ExtensibleModel):
    """An atomic fact carrying provenance: a stable id + where it came from."""

    id: str = Field(default_factory=new_id)
    source: Source = Source.resume
    source_ref: str | None = None
