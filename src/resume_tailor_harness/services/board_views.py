"""Workspace-scoped saved board view CRUD."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from resume_tailor_harness.tracking.tables import SavedBoardView, utcnow

BOARDS = frozenset({"triage", "shortlist", "pipeline"})


class SavedBoardViewConflict(ValueError):
    pass


def _normalize_name(name: str) -> str:
    normalized = " ".join(name.split())
    if not normalized:
        raise ValueError("view name is required")
    if len(normalized) > 80:
        raise ValueError("view name must be at most 80 characters")
    return normalized


def _validate(board: str, query_string: str) -> None:
    if board not in BOARDS:
        raise ValueError(f"unsupported board: {board}")
    if len(query_string) > 4_000:
        raise ValueError("view query must be at most 4000 characters")


def _commit(session: Session, name: str) -> None:
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise SavedBoardViewConflict(f'A view named "{name}" already exists') from error


def list_board_views(session: Session, board: str | None = None) -> list[SavedBoardView]:
    query = select(SavedBoardView).order_by(
        col(SavedBoardView.board), col(SavedBoardView.name)
    )
    if board is not None:
        _validate(board, "")
        query = query.where(SavedBoardView.board == board)
    return list(session.exec(query).all())


def create_board_view(
    session: Session, *, board: str, name: str, query_string: str
) -> SavedBoardView:
    name = _normalize_name(name)
    _validate(board, query_string)
    existing = session.exec(
        select(SavedBoardView).where(
            SavedBoardView.board == board,
            SavedBoardView.name == name,
        )
    ).first()
    if existing is not None:
        raise SavedBoardViewConflict(f'A view named "{name}" already exists')
    row = SavedBoardView(board=board, name=name, query_string=query_string)
    session.add(row)
    _commit(session, name)
    session.refresh(row)
    return row


def update_board_view(
    session: Session,
    view_id: int,
    *,
    name: str | None = None,
    query_string: str | None = None,
) -> SavedBoardView | None:
    row = session.get(SavedBoardView, view_id)
    if row is None:
        return None
    next_name = _normalize_name(name) if name is not None else row.name
    next_query = query_string if query_string is not None else row.query_string
    _validate(row.board, next_query)
    duplicate = session.exec(
        select(SavedBoardView).where(
            SavedBoardView.board == row.board,
            SavedBoardView.name == next_name,
            SavedBoardView.id != view_id,
        )
    ).first()
    if duplicate is not None:
        raise SavedBoardViewConflict(f'A view named "{next_name}" already exists')
    row.name = next_name
    row.query_string = next_query
    row.updated_at = utcnow()
    session.add(row)
    _commit(session, next_name)
    session.refresh(row)
    return row


def delete_board_view(session: Session, view_id: int) -> bool:
    row = session.get(SavedBoardView, view_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
