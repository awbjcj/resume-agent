"""Pure pagination helper shared by every list use-case."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    data: list[T]
    page: int
    page_size: int
    total_items: int
    total_pages: int


def paginate(items: list[T], *, page: int = 1, page_size: int = 50) -> Page[T]:
    page = max(1, page)
    page_size = max(1, page_size)
    total = len(items)
    total_pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size
    return Page(
        data=items[start : start + page_size],
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=total_pages,
    )


def page_from_slice(
    items: Sequence[T],
    *,
    total: int,
    page: int,
    page_size: int,
) -> Page[T]:
    """Build a Page from rows already sliced by the persistence query."""
    page = max(1, page)
    page_size = max(1, page_size)
    total = max(0, total)
    return Page(
        data=list(items),
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=(total + page_size - 1) // page_size if total else 0,
    )
