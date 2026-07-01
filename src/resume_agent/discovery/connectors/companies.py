import httpx

from resume_agent.discovery.connectors.ashby import fetch_ashby_board, parse_ashby
from resume_agent.discovery.connectors.bamboohr import fetch_bamboohr
from resume_agent.discovery.connectors.base import (
    FetchResult,
    RawJob,
    SkipSeen,
    board_error,
)
from resume_agent.discovery.connectors.breezy import fetch_breezy
from resume_agent.discovery.connectors.detect import AtsTarget, detect_ats
from resume_agent.discovery.connectors.google import fetch_google
from resume_agent.discovery.connectors.greenhouse import (
    fetch_greenhouse_board,
    parse_greenhouse,
)
from resume_agent.discovery.connectors.harvest import harvest
from resume_agent.discovery.connectors.lever import fetch_lever_board, parse_lever
from resume_agent.discovery.connectors.jazzhr import fetch_jazzhr
from resume_agent.discovery.connectors.personio import fetch_personio
from resume_agent.discovery.connectors.recruitee import fetch_recruitee
from resume_agent.discovery.connectors.smartrecruiters import fetch_smartrecruiters
from resume_agent.discovery.connectors.tesla import fetch_tesla
from resume_agent.discovery.connectors.workday import fetch_workday
from resume_agent.discovery.connectors.workable import fetch_workable
from resume_agent.discovery.search_config import SearchConfig


class NoAtsDetected(Exception):
    """detect_ats could not identify the ATS behind a careers URL."""


class UnsupportedAts(Exception):
    """The ATS was recognized but has no registered backend."""

    def __init__(self, ats: str):
        super().__init__(ats)
        self.ats = ats


# Adapters: thin, late-bound wrappers so each backend stays monkeypatchable at the
# module seam and shares one dispatch shape:
# (target, search, limit, skip_seen) -> RawJob[]. Single-shot backends ignore
# skip_seen internally; CompaniesConnector.fetch drops known rows from the union.
def _greenhouse(
    target: AtsTarget, search: SearchConfig, limit=None, skip_seen=None
) -> list[RawJob]:
    return parse_greenhouse(fetch_greenhouse_board(target.token), target.token)


def _lever(
    target: AtsTarget, search: SearchConfig, limit=None, skip_seen=None
) -> list[RawJob]:
    return parse_lever(fetch_lever_board(target.token, search), target.token)


def _ashby(
    target: AtsTarget, search: SearchConfig, limit=None, skip_seen=None
) -> list[RawJob]:
    return parse_ashby(fetch_ashby_board(target.token), target.token)


def _workday(
    target: AtsTarget, search: SearchConfig, limit=None, skip_seen=None
) -> list[RawJob]:
    return fetch_workday(target, search, limit, skip_seen=skip_seen)


def _tesla(
    target: AtsTarget, search: SearchConfig, limit=None, skip_seen=None
) -> list[RawJob]:
    return fetch_tesla(target, search, limit, skip_seen=skip_seen)


def _google(
    target: AtsTarget, search: SearchConfig, limit=None, skip_seen=None
) -> list[RawJob]:
    return fetch_google(target, search, limit, skip_seen=skip_seen)


def _smartrecruiters(target, search, limit=None, skip_seen=None):
    return fetch_smartrecruiters(target, search, limit, skip_seen=skip_seen)


def _workable(target, search, limit=None, skip_seen=None):
    return fetch_workable(target, search, limit, skip_seen=skip_seen)


def _recruitee(target, search, limit=None, skip_seen=None):
    return fetch_recruitee(target, search, limit, skip_seen=skip_seen)


def _personio(target, search, limit=None, skip_seen=None):
    return fetch_personio(target, search, limit, skip_seen=skip_seen)


def _breezy(target, search, limit=None, skip_seen=None):
    return fetch_breezy(target, search, limit, skip_seen=skip_seen)


def _jazzhr(target, search, limit=None, skip_seen=None):
    return fetch_jazzhr(target, search, limit, skip_seen=skip_seen)


def _bamboohr(target, search, limit=None, skip_seen=None):
    return fetch_bamboohr(target, search, limit, skip_seen=skip_seen)


# ats -> adapter(target, search, limit, skip_seen) -> RawJob[]
_BACKENDS = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "workday": _workday,
    "tesla": _tesla,
    "google": _google,
    "smartrecruiters": _smartrecruiters,
    "workable": _workable,
    "recruitee": _recruitee,
    "personio": _personio,
    "breezy": _breezy,
    "jazzhr": _jazzhr,
    "bamboohr": _bamboohr,
}


def _failure_reason(exc: Exception) -> str | None:
    """harvest on_error policy: render each isolable failure for one careers URL.

    Reverse-engineered singleton payloads (Tesla/Google) may shift shape; a parse
    failure is isolated to its URL rather than aborting the whole pull.
    """
    if isinstance(exc, NoAtsDetected):
        return "no known ATS detected"
    if isinstance(exc, UnsupportedAts):
        return f"{exc.ats.title()} recognized, not yet supported"
    if isinstance(exc, httpx.HTTPError):
        return board_error(exc)
    if isinstance(exc, (ValueError, KeyError, TypeError, AttributeError)):
        return f"parse error: {type(exc).__name__}"
    return None


class CompaniesConnector:
    """Pull openings from company careers URLs by auto-detecting their ATS."""

    name = "companies"

    def __init__(self, urls: list[str]):
        self.urls = urls

    def fetch(
        self,
        search: SearchConfig,
        limit: int | None = None,
        skip_seen: SkipSeen | None = None,
    ) -> FetchResult:
        return harvest(
            self.urls,
            lambda url: self._produce(url, search, limit, skip_seen),
            search=search,
            limit=limit,
            key=lambda url: url,
            on_error=_failure_reason,
            skip_seen=skip_seen,
        )

    def _produce(
        self,
        url: str,
        search: SearchConfig,
        limit: int | None,
        skip_seen: SkipSeen | None,
    ) -> list[RawJob]:
        target = detect_ats(url)
        if target is None:
            raise NoAtsDetected
        backend = _BACKENDS.get(target.ats)
        if backend is None:
            raise UnsupportedAts(target.ats)
        return backend(target, search, limit, skip_seen=skip_seen)
