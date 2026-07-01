from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

RECIPE_SCHEMA_VERSION = 1


class _RecipeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Pagination(_RecipeModel):
    pattern: Literal["numbered", "next", "infinite", "load_more"]
    control_sel: str | None = Field(default=None, min_length=1)
    max_pages: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def validate_control(self) -> Self:
        if self.pattern != "infinite" and self.control_sel is None:
            raise ValueError(f"{self.pattern} pagination requires control_sel")
        return self


class Search(_RecipeModel):
    input_sel: str = Field(min_length=1)
    submit_sel: str | None = Field(default=None, min_length=1)


class ScrapeRecipe(_RecipeModel):
    """Validated selectors learned for one company-owned job-board host."""

    schema_version: int = RECIPE_SCHEMA_VERSION
    learned_at: datetime
    card_container: str = Field(min_length=1)
    jd_container: str = Field(min_length=1)
    title_sel: str = Field(min_length=1)
    location_sel: str | None = Field(default=None, min_length=1)
    url_sel: str | None = Field(default=None, min_length=1)
    detail_mode: Literal["link", "inline"] = "link"
    pagination: Pagination
    search: Search | None = None

    @model_validator(mode="after")
    def validate_detail_mode(self) -> Self:
        if self.detail_mode == "link" and self.url_sel is None:
            raise ValueError("link recipes require url_sel")
        return self
