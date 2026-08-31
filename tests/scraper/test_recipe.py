from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from resume_tailor_harness.discovery.scraper.recipe import (
    Pagination,
    RECIPE_SCHEMA_VERSION,
    ScrapeRecipe,
    Search,
)


def _recipe(**overrides):
    values = {
        "schema_version": RECIPE_SCHEMA_VERSION,
        "learned_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "card_container": "li.job",
        "jd_container": "div.jd",
        "title_sel": "h3",
        "location_sel": ".loc",
        "url_sel": "a",
        "detail_mode": "link",
        "pagination": Pagination(pattern="next", control_sel="a.next", max_pages=5),
        "search": Search(input_sel="#q", submit_sel="button[type=submit]"),
    }
    values.update(overrides)
    return ScrapeRecipe(**values)


def test_recipe_roundtrips_through_json():
    recipe = _recipe()
    restored = ScrapeRecipe.model_validate_json(recipe.model_dump_json())
    assert restored == recipe


def test_pagination_defaults():
    pagination = Pagination(pattern="infinite")
    assert pagination.control_sel is None
    assert pagination.max_pages == 10


def test_search_is_optional():
    assert _recipe(search=None).search is None


@pytest.mark.parametrize("max_pages", [0, 101])
def test_pagination_rejects_unsafe_page_caps(max_pages):
    with pytest.raises(ValidationError):
        Pagination(pattern="next", control_sel="a.next", max_pages=max_pages)


def test_non_infinite_pagination_requires_control_selector():
    with pytest.raises(ValidationError):
        Pagination(pattern="load_more")


def test_link_recipe_requires_url_selector():
    with pytest.raises(ValidationError):
        _recipe(url_sel=None)


def test_recipe_rejects_unknown_llm_fields():
    with pytest.raises(ValidationError):
        _recipe(unexpected_selector="div.job")
