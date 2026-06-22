"""Shared API schema base: camelCase wire format + the pagination envelope."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class CamelModel(BaseModel):
    """All request/response models serialize to camelCase on the wire.

    Python field names stay snake_case; the alias generator maps them to camelCase.
    `populate_by_name` lets construction work with either spelling;
    `from_attributes` lets `model_validate(dto)` read snake_case dataclass attrs.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class Pagination(CamelModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class Page(CamelModel, Generic[T]):
    data: list[T]
    pagination: Pagination
