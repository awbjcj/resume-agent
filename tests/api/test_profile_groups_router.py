import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.store import save_facts
from resume_agent.taxonomy.groups import group_map_path, save_group_map


@pytest.fixture()
def client(tmp_path):
    data_dir = tmp_path / "data"
    app = create_app(
        db_url="sqlite://",
        data_dir=data_dir,
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
    )
    with TestClient(app) as test_client:
        yield test_client, data_dir


def _seed(data_dir):
    profile = data_dir / "profile"
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python", aliases=["py"])]},
    )
    save_facts(facts, profile / "facts.json")
    save_group_map({"python": "languages"}, group_map_path(profile))


def test_put_group_requires_a_built_profile(client):
    test_client, _ = client

    response = test_client.put(
        "/api/profile/skills/python/group",
        json={"group": "ai-ml"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SETUP_INCOMPLETE"


def test_put_group_rejects_unknown_slug(client):
    test_client, data_dir = client
    _seed(data_dir)

    response = test_client.put(
        "/api/profile/skills/python/group",
        json={"group": "not-a-group"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_put_group_rejects_unknown_skill(client):
    test_client, data_dir = client
    _seed(data_dir)

    response = test_client.put(
        "/api/profile/skills/cobol/group",
        json={"group": "languages"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_put_group_pins_alias_and_matrix_reports_source(client):
    test_client, data_dir = client
    _seed(data_dir)

    response = test_client.put(
        "/api/profile/skills/py/group",
        json={"group": "ai-ml"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "python"
    assert body["group"] == "ai-ml"
    assert body["groupSource"] == "correction"
    matrix = test_client.get("/api/profile/matrix").json()
    row = next(item for item in matrix["rows"] if item["key"] == "python")
    assert (row["group"], row["groupSource"]) == ("ai-ml", "correction")


def test_delete_group_reverts_to_taxonomy(client):
    test_client, data_dir = client
    _seed(data_dir)
    test_client.put(
        "/api/profile/skills/python/group",
        json={"group": "ai-ml"},
    )

    response = test_client.delete("/api/profile/skills/python/group")

    assert response.status_code == 204
    matrix = test_client.get("/api/profile/matrix").json()
    row = next(item for item in matrix["rows"] if item["key"] == "python")
    assert (row["group"], row["groupSource"]) == ("languages", "taxonomy")


def test_delete_group_without_correction_is_404(client):
    test_client, data_dir = client
    _seed(data_dir)

    response = test_client.delete("/api/profile/skills/python/group")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
