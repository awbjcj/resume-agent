import pytest
from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

from resume_agent.api.schemas.scout import (
    ScoutApproveIn,
    ScoutEvidenceOut,
    ScoutManualConfirmationOut,
    ScoutProposalOut,
    ScoutResolveSourceIn,
    ScoutSourceOut,
)


_http_url = TypeAdapter(AnyHttpUrl).validate_python


def test_source_resolution_fields_serialize_as_camel_case():
    source = ScoutSourceOut(
        company="Acme",
        url="https://jobs.lever.co/acme",
        requested_url="https://acme.example/careers",
        canonical_board_url="https://jobs.lever.co/acme",
        resolution_status="unverified",
        resolution_reason="OWNERSHIP_NOT_PROVEN",
        evidence=[
            ScoutEvidenceOut(
                kind="candidate", source_url="https://acme.example/careers"
            )
        ],
        searched_families=["lever"],
        unsearched_families=["workday"],
    )

    wire = source.model_dump(by_alias=True)

    assert wire["requestedUrl"] == "https://acme.example/careers"
    assert wire["canonicalBoardUrl"] == "https://jobs.lever.co/acme"
    assert wire["evidence"][0]["sourceUrl"] == "https://acme.example/careers"


def test_approval_and_exact_url_request_models_are_closed_at_the_boundary():
    assert ScoutApproveIn().manual_confirmation is False
    assert (
        str(ScoutResolveSourceIn(url=_http_url("https://jobs.lever.co/acme")).url)
        == "https://jobs.lever.co/acme"
    )
    with pytest.raises(ValidationError):
        ScoutResolveSourceIn.model_validate({"url": "file:///tmp/board"})

    proposal = ScoutProposalOut(
        id="p1",
        kind="source",
        source=ScoutSourceOut(company="Acme"),
        check="conflict",
        status="pending",
        manual_confirmation=ScoutManualConfirmationOut(
            company="Acme",
            url="https://jobs.lever.co/acme",
            resolution_reason="OWNERSHIP_NOT_PROVEN",
            confirmed_at="2026-08-14T12:00:00Z",
        ),
    )
    assert proposal.model_dump(by_alias=True)["manualConfirmation"]["company"] == "Acme"
