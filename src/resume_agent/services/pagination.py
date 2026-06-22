"""Pure pagination helper shared by every list use-case."""

from __future__ import annotations

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
        page=page, page_size=page_size,
        total_items=total, total_pages=total_pages,
    )
