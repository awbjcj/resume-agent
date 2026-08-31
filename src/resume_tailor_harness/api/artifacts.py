"""One HTTP mapping for artifact deletion, shared by both artifact routers.

Deleting a resume version and deleting a cover letter differ only in the noun,
so the status-code decision lives here rather than being written twice and
drifting -- the 409 in particular is load-bearing: it is what tells the client
to deselect the artifact before retrying.
"""

from __future__ import annotations

from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.services.board import ArtifactDeleteResult

ARTIFACT_IN_USE = "ARTIFACT_IN_USE"


def _join(ids: tuple[int, ...]) -> str:
    return ", ".join(f"#{artifact_id}" for artifact_id in ids)


def raise_for_delete_result(result: ArtifactDeleteResult, *, noun: str) -> None:
    """Turn a refused delete into the API envelope. A clean result is a no-op.

    Missing is checked first: an id that does not exist is a staler view than
    one that is merely in use, and reporting "in use" for a row that is gone
    would send the caller to deselect something they cannot see.
    """

    if result.missing_ids:
        raise ApiException(
            404, "NOT_FOUND", f"{noun} {_join(result.missing_ids)} not found"
        )
    if result.blocked_ids:
        raise ApiException(
            409,
            ARTIFACT_IN_USE,
            f"{noun} {_join(result.blocked_ids)} is selected for an application. "
            "Unselect it first, then delete.",
            {"blockedIds": list(result.blocked_ids)},
        )
