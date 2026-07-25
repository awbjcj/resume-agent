from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.tracking.tables import Job, JobStatus


def _seed_rank_cases(app) -> None:
    now = datetime.now(timezone.utc)
    rows = (
        ("Fit leader", 95, 50_000, now - timedelta(days=30)),
        ("Pay leader", 50, 250_000, now - timedelta(days=15)),
        ("Fresh leader", 60, 100_000, now),
    )
    with get_session(app.state.engine) as session:
        for company, fit_score, salary, posted_at in rows:
            session.add(
                Job(
                    source="manual",
                    company=company,
                    title="Engineer",
                    jd_text="Build systems",
                    status=JobStatus.shortlisted.value,
                    fit_score=fit_score,
                    posted_at=posted_at,
                    criteria_json={
                        "salary_range": {
                            "maximum": salary,
                            "currency": "USD",
                        }
                    },
                )
            )
        session.commit()


def _companies(client: TestClient, query: str) -> list[str]:
    response = client.get(f"/api/shortlist?{query}")
    assert response.status_code == 200
    return [row["company"] for row in response.json()["data"]]


def test_composite_presets_produce_distinct_rankings():
    client = TestClient(create_app(db_url="sqlite://"))
    with client:
        _seed_rank_cases(client.app)

        fit = _companies(client, "sortBy=fit")
        pay_first = _companies(client, "sortBy=composite&preset=pay_first")
        freshest = _companies(client, "sortBy=composite&preset=freshest")

    assert fit == ["Fit leader", "Fresh leader", "Pay leader"]
    assert pay_first == ["Pay leader", "Fresh leader", "Fit leader"]
    assert freshest == ["Fresh leader", "Pay leader", "Fit leader"]


def test_board_query_rejects_unknown_sort_and_preset():
    client = TestClient(create_app(db_url="sqlite://"))
    with client:
        assert client.get("/api/shortlist?sortBy=unknown").status_code == 422
        assert client.get("/api/shortlist?preset=unknown").status_code == 422
