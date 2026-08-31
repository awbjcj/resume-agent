import pytest
from pydantic import ValidationError

from resume_tailor_harness.discovery.scout import ScoutProposalDraft, SourceDraft
from resume_tailor_harness.discovery.scout_models import Citation
from resume_tailor_harness.discovery.scout_store import ScoutProposal, SourcePayload, TermPayload


def test_scout_enrichment_defaults_are_backward_compatible():
    source = ScoutProposalDraft(kind="source")
    search = ScoutProposalDraft(kind="search_term")

    assert source.fit_score is None
    assert source.disposition == "propose"
    assert source.citations == []
    assert search.fit_score is None
    assert search.citations == []


def test_scout_enrichment_accepts_shared_citations_and_new_kinds():
    citation = Citation(url="https://example.test/evidence", title="Evidence")
    source = ScoutProposalDraft(
        kind="source",
        source=SourceDraft(company="Acme"),
        disposition="avoid",
        fit_score=10,
        citations=[citation],
    )
    suggestions = [
        ScoutProposal(
            kind="search_term",
            term=TermPayload(value="Berlin", term_kind="location"),
            fit_score=80,
        ),
        ScoutProposal(
            kind="search_term",
            term=TermPayload(value="mid-senior", term_kind="seniority"),
            fit_score=70,
        ),
        ScoutProposal(
            kind="search_term",
            term=TermPayload(value="Platform Architect", term_kind="adjacent_role"),
        ),
    ]

    assert source.citations[0] == citation
    assert {row.term.term_kind for row in suggestions if row.term is not None} == {
        "location",
        "seniority",
        "adjacent_role",
    }


@pytest.mark.parametrize("score", [-1, 101])
def test_fit_scores_are_bounded(score):
    with pytest.raises(ValidationError):
        ScoutProposal(
            kind="source", source=SourcePayload(company="Acme"), fit_score=score
        )
    with pytest.raises(ValidationError):
        ScoutProposal(
            kind="search_term", term=TermPayload(value="python"), fit_score=score
        )


def test_seniority_uses_existing_search_config_vocabulary():
    with pytest.raises(ValidationError):
        TermPayload(value="Staff", term_kind="seniority")
