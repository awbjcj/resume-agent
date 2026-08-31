import json
from pathlib import Path

from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.recruitee import (
    fetch_recruitee,
    offers_url,
    parse_recruitee,
)
from resume_tailor_harness.discovery.search_config import SearchConfig


def test_recruitee_maps_public_offers_payload():
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "recruitee" / "offers.json").read_text()
    )
    jobs = parse_recruitee(payload, "transperfect")

    assert (
        offers_url("transperfect") == "https://transperfect.recruitee.com/api/offers/"
    )
    assert jobs[0].company == "TransPerfect"
    assert jobs[0].url is not None
    assert jobs[0].url.endswith("/c/new")
    assert "SQL expertise" in jobs[0].jd_text


def test_recruitee_fetch_reads_public_offers(monkeypatch):
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "recruitee" / "offers.json").read_text()
    )

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    import resume_tailor_harness.discovery.connectors.recruitee as connector

    monkeypatch.setattr(connector.board, "get", lambda *args, **kwargs: Response())
    assert fetch_recruitee(AtsTarget("recruitee", "transperfect"), SearchConfig())[
        0
    ].jd_text


def test_recruitee_reads_the_structured_place_not_the_typed_label():
    """`location` is free text and is often a status, not a place.

    Measured live: 5 of 6 postings on one board wrote "Remote job" there, which
    resolves to no city, region or country at all -- while the payload carried
    all three in dedicated fields.
    """
    payload = {
        "offers": [
            {
                "title": "Engineer",
                "location": "Remote job",
                "city": "Boston",
                "state_name": "Massachusetts",
                "country": "United States",
                "country_code": "US",
                "remote": True,
                "department": "Sales",
                "employment_type_code": "fulltime_permanent",
                "salary": {
                    "min": 120000,
                    "max": 160000,
                    "currency": "USD",
                    "period": "year",
                },
            }
        ]
    }

    [job] = parse_recruitee(payload, "acme")
    header = job.jd_text.split("\n\n")[0].splitlines()

    assert job.location == "Boston, Massachusetts, United States"
    assert "Workplace Type: Remote" in header
    assert "Department: Sales" in header
    assert "Compensation: USD 120,000 - 160,000 per year" in header


def test_recruitee_keeps_every_office_of_a_multi_location_posting():
    payload = {
        "offers": [
            {
                "title": "Engineer",
                "location": "Remote job",
                "locations": [
                    {
                        "city": "Boston",
                        "state": "Massachusetts",
                        "country": "United States",
                    },
                    {"city": "Warsaw", "state": "Mazowieckie", "country": "Poland"},
                ],
            }
        ]
    }

    [job] = parse_recruitee(payload, "acme")

    assert job.location == (
        "Boston, Massachusetts, United States | Warsaw, Mazowieckie, Poland"
    )


def test_recruitee_falls_back_to_the_label_when_nothing_is_structured():
    payload = {"offers": [{"title": "Engineer", "location": "Anywhere"}]}

    [job] = parse_recruitee(payload, "acme")

    assert job.location == "Anywhere"
