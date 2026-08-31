from pathlib import Path

from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.personio import (
    fetch_personio,
    parse_personio,
    search_url,
)
from resume_tailor_harness.discovery.search_config import SearchConfig


def _fixture() -> str:
    return (Path(__file__).parent / "fixtures" / "personio" / "search.json").read_text()


def test_personio_maps_search_json_and_converts_html():
    jobs = parse_personio(_fixture(), "pitch", "de")

    assert (
        search_url("pitch", "de")
        == "https://pitch.jobs.personio.de/search.json?language=en"
    )
    assert jobs[0].company == "Pitch Software GmbH"
    assert jobs[0].title == "Frontend Performance Engineer"
    assert jobs[0].location == "Berlin | Remote"
    assert jobs[0].url == "https://pitch.jobs.personio.de/job/160959"
    assert "- Five years building frontend systems" in jobs[0].jd_text


def test_personio_keeps_postings_without_description():
    jobs = parse_personio(_fixture(), "pitch", "de")

    # Evergreen rows with an empty description still surface with the structured
    # facts Personio provides outside the body.
    assert jobs[1].title == "Initiativbewerbung"
    assert "Location: Remote" in jobs[1].jd_text
    assert "Employment Type: Permanent employee" in jobs[1].jd_text
    assert "Department: General" in jobs[1].jd_text


def test_personio_fetch_uses_search_json_with_detected_country(monkeypatch):
    captured = {}

    class Response:
        text = _fixture()

        def raise_for_status(self):
            pass

    def fake_get(url, **kwargs):
        captured["url"] = url
        return Response()

    import resume_tailor_harness.discovery.connectors.personio as connector

    monkeypatch.setattr(connector.board, "get", fake_get)
    jobs = fetch_personio(AtsTarget("personio", "pitch", country="de"), SearchConfig())

    assert captured["url"] == "https://pitch.jobs.personio.de/search.json?language=en"
    assert jobs[0].jd_text


def test_personio_splits_the_offices_array_instead_of_the_joined_scalar():
    """`office` joins offices with a bare comma ("Madrid,Madrid (Remote)"),
    which reads as one "City, Region" pair and misparses. 7 of 9 postings on
    one live board carry more than one office."""
    payload = (
        '[{"id": 1, "name": "Engineer", "office": "Madrid,Madrid (Remote)",'
        ' "offices": ["Madrid", "Madrid (Remote)"], "employment_type": "Permanent employee",'
        ' "seniority": "Experienced", "schedule": "Full-time", "department": "Data",'
        ' "description": "<p>Build.</p>"}]'
    )

    [job] = parse_personio(payload, "astrafy")
    header = job.jd_text.split("\n\n")[0].splitlines()

    assert job.location == "Madrid | Madrid (Remote)"
    assert "Employment Type: Permanent employee" in header
    assert "Schedule: Full-time" in header
    assert "Experience Level: Experienced" in header
    assert "Department: Data" in header


def test_personio_falls_back_to_the_office_scalar():
    payload = '[{"id": 1, "name": "Engineer", "office": "Barcelona", "description": "<p>x</p>"}]'

    [job] = parse_personio(payload, "didit")

    assert job.location == "Barcelona"
