import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.store import save_facts


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


def _seed_facts(data_dir):
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Languages": [Skill(name="Python", aliases=["py"])]},
    )
    save_facts(facts, data_dir / "profile" / "facts.json")
    return facts


def test_list_skills_before_profile_build_is_empty(client):
    test_client, _ = client
    resp = test_client.get("/api/profile/skills")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_skills_returns_flat_rows(client):
    test_client, data_dir = client
    _seed_facts(data_dir)
    resp = test_client.get("/api/profile/skills")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["name"] == "Python"
    assert body[0]["category"] is None


def test_add_skill_requires_a_built_profile(client):
    test_client, _ = client
    resp = test_client.post("/api/profile/skills", json={"name": "Rust"})
    assert resp.status_code == 400


def test_add_skill_creates_a_manual_entry(client):
    test_client, data_dir = client
    _seed_facts(data_dir)
    resp = test_client.post("/api/profile/skills", json={"name": "Rust", "category": "hard"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "new_skill"
    assert body["name"] == "Rust"

    listed = test_client.get("/api/profile/skills").json()
    assert any(row["name"] == "Rust" for row in listed)


def test_add_skill_rejects_a_duplicate(client):
    test_client, data_dir = client
    _seed_facts(data_dir)
    resp = test_client.post("/api/profile/skills", json={"name": "python"})
    assert resp.status_code == 422


def test_add_skill_rejects_whitespace_only_name(client):
    test_client, data_dir = client
    _seed_facts(data_dir)

    resp = test_client.post("/api/profile/skills", json={"name": "   "})

    assert resp.status_code == 422


def test_add_alias_attaches_to_the_chosen_skill(client):
    test_client, data_dir = client
    _seed_facts(data_dir)
    skill_id = test_client.get("/api/profile/skills").json()[0]["id"]

    resp = test_client.post(
        f"/api/profile/skills/{skill_id}/aliases", json={"alias": "Python3"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "alias"
    assert body["aliasText"] == "Python3"
    assert body["targetSkillDisplay"] == "Python"


def test_add_alias_rejects_unknown_skill_id(client):
    test_client, data_dir = client
    _seed_facts(data_dir)
    resp = test_client.post("/api/profile/skills/nope/aliases", json={"alias": "x"})
    assert resp.status_code == 404


def test_add_alias_rejects_whitespace_only_text(client):
    test_client, data_dir = client
    _seed_facts(data_dir)
    skill_id = test_client.get("/api/profile/skills").json()[0]["id"]

    resp = test_client.post(
        f"/api/profile/skills/{skill_id}/aliases", json={"alias": "   "}
    )

    assert resp.status_code == 422


def test_manual_skills_list_and_remove_round_trip(client):
    test_client, data_dir = client
    _seed_facts(data_dir)
    created = test_client.post("/api/profile/skills", json={"name": "Rust"}).json()

    listed = test_client.get("/api/profile/manual-skills").json()
    assert [row["id"] for row in listed] == [created["id"]]

    resp = test_client.delete(f"/api/profile/manual-skills/{created['id']}")
    assert resp.status_code == 204
    assert test_client.get("/api/profile/manual-skills").json() == []
    assert not any(
        row["name"] == "Rust" for row in test_client.get("/api/profile/skills").json()
    )


def test_remove_unknown_manual_entry_404s(client):
    test_client, data_dir = client
    _seed_facts(data_dir)
    resp = test_client.delete("/api/profile/manual-skills/nope")
    assert resp.status_code == 404
