from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel

BoardName = Literal["triage", "shortlist", "pipeline"]


class SavedBoardViewCreate(CamelModel):
    board: BoardName
    name: str = Field(min_length=1, max_length=80)
    query_string: str = Field(default="", max_length=4_000)


class SavedBoardViewUpdate(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    query_string: str | None = Field(default=None, max_length=4_000)


class SavedBoardViewOut(CamelModel):
    id: int
    board: BoardName
    name: str
    query_string: str
    created_at: datetime
    updated_at: datetime
