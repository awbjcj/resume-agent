from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from resume_tailor_harness.api.deps import get_session
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.schemas.board_views import (
    BoardName,
    SavedBoardViewCreate,
    SavedBoardViewOut,
    SavedBoardViewUpdate,
)
from resume_tailor_harness.services.board_views import (
    SavedBoardViewConflict,
    create_board_view,
    delete_board_view,
    list_board_views,
    update_board_view,
)

router = APIRouter()


def _conflict(error: SavedBoardViewConflict) -> ApiException:
    return ApiException(409, "VIEW_NAME_CONFLICT", str(error))


@router.get("/board-views", response_model=list[SavedBoardViewOut])
def list_views(
    board: BoardName | None = Query(default=None),
    session: Session = Depends(get_session),
):
    return list_board_views(session, board)


@router.post("/board-views", response_model=SavedBoardViewOut, status_code=201)
def create_view(body: SavedBoardViewCreate, session: Session = Depends(get_session)):
    try:
        return create_board_view(
            session,
            board=body.board,
            name=body.name,
            query_string=body.query_string,
        )
    except SavedBoardViewConflict as error:
        raise _conflict(error) from error


@router.patch("/board-views/{view_id}", response_model=SavedBoardViewOut)
def update_view(
    view_id: int,
    body: SavedBoardViewUpdate,
    session: Session = Depends(get_session),
):
    try:
        row = update_board_view(
            session,
            view_id,
            name=body.name,
            query_string=body.query_string,
        )
    except SavedBoardViewConflict as error:
        raise _conflict(error) from error
    if row is None:
        raise ApiException(404, "NOT_FOUND", f"Saved view #{view_id} not found")
    return row


@router.delete("/board-views/{view_id}", status_code=204)
def delete_view(view_id: int, session: Session = Depends(get_session)) -> Response:
    if not delete_board_view(session, view_id):
        raise ApiException(404, "NOT_FOUND", f"Saved view #{view_id} not found")
    return Response(status_code=204)
