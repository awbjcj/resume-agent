import pytest
from pydantic import ValidationError

from resume_agent.discovery.scout_models import Citation
from resume_agent.discovery.search_scout import SearchSuggestion
from resume_agent.discovery.source_scout import ScoutCandidate


def test_scout_enrichment_defaults_are_backward_compatible():
    source = ScoutCandidate()
    search = SearchSuggestion()

    assert source.fit_score is None
    assert source.signal == "positive"
    assert source.citations == []
    assert search.fit_score is None
    assert search.citations == []


def test_scout_enrichment_accepts_shared_citations_and_new_kinds():
    citation = Citation(url="https://example.test/evidence", title="Evidence")
    source = ScoutCandidate(
        company="Acme",
        signal="avoid",
        fit_score=10,
        citations=[citation],
    )
    suggestions = [
        SearchSuggestion(value="Berlin", kind="location", fit_score=80),
        SearchSuggestion(value="mid-senior", kind="seniority", fit_score=70),
        SearchSuggestion(value="Platform Architect", kind="adjacent_role"),
    ]

    assert source.citations[0] == citation
    assert {row.kind for row in suggestions} == {
        "location",
        "seniority",
        "adjacent_role",
    }


@pytest.mark.parametrize("score", [-1, 101])
def test_fit_scores_are_bounded(score):
    with pytest.raises(ValidationError):
        ScoutCandidate(fit_score=score)
    with pytest.raises(ValidationError):
        SearchSuggestion(fit_score=score)


def test_seniority_uses_existing_search_config_vocabulary():
    with pytest.raises(ValidationError):
        SearchSuggestion(value="Staff", kind="seniority")
