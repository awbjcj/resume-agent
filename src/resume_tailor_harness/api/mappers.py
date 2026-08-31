"""DTO/table -> schema converters. Most are model_validate (from_attributes)."""

from __future__ import annotations

from resume_tailor_harness.api.schemas.base import BoardPage, Page, Pagination
from resume_tailor_harness.services.pagination import Page as ServicePage


def to_page(service_page: ServicePage, item_model) -> Page:
    return Page(
        data=[item_model.model_validate(row) for row in service_page.data],
        pagination=Pagination(
            page=service_page.page,
            page_size=service_page.page_size,
            total_items=service_page.total_items,
            total_pages=service_page.total_pages,
        ),
    )


def to_board_page(
    service_page: ServicePage,
    item_model,
    facets: dict[str, dict[str, int]] | None,
) -> BoardPage:
    return BoardPage(
        data=[item_model.model_validate(row) for row in service_page.data],
        pagination=Pagination(
            page=service_page.page,
            page_size=service_page.page_size,
            total_items=service_page.total_items,
            total_pages=service_page.total_pages,
        ),
        facets=facets,
        total=service_page.total_items,
    )
