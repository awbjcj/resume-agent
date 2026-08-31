"""Backfill token company names without merging identity collisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlmodel import Session, select

from resume_tailor_harness.discovery.connectors.config import ConnectorsConfig
from resume_tailor_harness.discovery.connectors.detect import detect_ats, identify_host
from resume_tailor_harness.discovery.connectors.greenhouse import fetch_greenhouse_board_name
from resume_tailor_harness.tracking.dedup import compute_dedup_key
from resume_tailor_harness.tracking.repository import company_rename_collision
from resume_tailor_harness.tracking.tables import Job


@dataclass(frozen=True)
class CompanyFixReport:
    renamed: dict[str, int] = field(default_factory=dict)
    conflicts: list[tuple[int, int]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def _record(
    mapping: dict[str, str],
    unresolved: list[str],
    token: str,
    name: str | None,
) -> None:
    token = token.strip()
    name = name.strip() if name else None
    if not token:
        return
    if name and name.casefold() != token.casefold():
        mapping[token] = name
    elif token not in unresolved:
        unresolved.append(token)


def _token_names(
    config: ConnectorsConfig,
    resolve: Callable[[str], str | None],
) -> tuple[dict[str, str], list[str]]:
    mapping: dict[str, str] = {}
    unresolved: list[str] = []

    def token_for(url: str) -> str:
        try:
            target = identify_host(url) or detect_ats(url)
        except Exception:  # noqa: BLE001 - unresolved sources remain reportable
            return ""
        return (target.tenant or target.token) if target else ""

    for board in config.greenhouse.boards:
        try:
            name = board.company or resolve(board.token)
        except Exception:  # noqa: BLE001 - one remote board must not abort backfill
            name = board.company
        _record(mapping, unresolved, board.token, name)
    for section in (config.lever, config.ashby):
        for board in section.boards:
            _record(mapping, unresolved, board.token, board.company)
    for section_name in (
        "workday",
        "tesla",
        "google",
        "smartrecruiters",
        "workable",
        "recruitee",
        "personio",
        "breezy",
        "jazzhr",
        "bamboohr",
    ):
        section = getattr(config, section_name)
        for board in section.boards:
            _record(mapping, unresolved, token_for(board.url), board.company)
    for entry in config.companies.urls:
        _record(mapping, unresolved, token_for(entry.url), entry.label)
    return mapping, unresolved


def fix_company_names(
    session: Session,
    config: ConnectorsConfig,
    *,
    dry_run: bool = False,
    resolve: Callable[[str], str | None] | None = None,
) -> CompanyFixReport:
    mapping, unresolved = _token_names(config, resolve or fetch_greenhouse_board_name)
    renamed: dict[str, int] = {}
    conflicts: list[tuple[int, int]] = []
    for token, name in mapping.items():
        rows = session.exec(
            select(Job).where(func.lower(Job.company) == token.lower())
        ).all()
        for row in rows:
            new_key = compute_dedup_key(name, row.title)
            keeper = company_rename_collision(session, existing=row, dedup_key=new_key)
            if keeper is not None:
                conflicts.append((keeper.id or -1, row.id or -1))
                continue
            renamed[token] = renamed.get(token, 0) + 1
            if not dry_run:
                row.company = name
                row.dedup_key = new_key
                session.add(row)
    if not dry_run:
        session.commit()
    return CompanyFixReport(
        renamed=renamed,
        conflicts=conflicts,
        unresolved=unresolved,
    )
