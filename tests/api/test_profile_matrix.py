import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.profile.matrix import MatrixRow, SkillMatrix, save_matrix


@pytest.fixture()
def client(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(db_url="sqlite://", data_dir=data_dir)
    with TestClient(app) as test_client:
        yield test_client, data_dir


def test_matrix_route_serves_rooted_rows_and_ordered_vocabulary(client):
    test_client, data_dir = client
    save_matrix(
        SkillMatrix(
            generated_at="2026-07-10T00:00:00+00:00",
            rows=[
                MatrixRow(
                    key="python",
                    display="Python",
                    category="hard",
                    group="languages",
                    strength=2.5,
                    last_used="current",
                )
            ],
        ),
        data_dir / "profile" / "matrix.json",
    )
    response = test_client.get("/api/profile/matrix")
    assert response.status_code == 200
    body = response.json()
    assert body["generatedAt"] == "2026-07-10T00:00:00+00:00"
    assert body["rows"][0] == {
        "key": "python",
        "display": "Python",
        "category": "hard",
        "group": "languages",
        "inferred": False,
        "strength": 2.5,
        "lastUsed": "current",
    }
    assert len(body["groups"]) == 13
    assert body["groups"][-1] == {"slug": "other", "label": "Other"}


def test_matrix_route_is_empty_but_self_describing_before_build(client):
    test_client, _ = client
    body = test_client.get("/api/profile/matrix").json()
    assert body["generatedAt"] == ""
    assert body["rows"] == []
    assert body["groups"][0] == {"slug": "languages", "label": "Languages"}
