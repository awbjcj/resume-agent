from typer.testing import CliRunner

from resume_tailor_harness import cli
from resume_tailor_harness.profile.corpus import add_source


def _view(sid="s1", *, status="active", turns=None, drafts=None):
    return {
        "sessionId": sid,
        "startedAt": "",
        "endedAt": None,
        "status": status,
        "turns": turns
        or [
            {
                "role": "coach",
                "kind": "question",
                "text": "What changed at Acme?",
                "topicId": "t1",
                "at": "",
                "researchActions": [],
            }
        ],
        "topics": [
            {
                "id": "t1",
                "gap": "Acme impact",
                "whyItMatters": "",
                "relatedRef": "",
                "status": "open",
                "noteDocId": None,
            }
        ],
        "draftNotes": drafts or [],
        "recap": None,
        "impact": None,
    }


def _setup(monkeypatch, tmp_path, *, resume=False):
    profile_dir = tmp_path / "profile"
    source = tmp_path / "resume.txt"
    source.write_text("Acme experience", encoding="utf-8")
    add_source(profile_dir, source, primary=True, mode="literal")
    calls = {"opened": 0, "messages": [], "approved": [], "discarded": [], "built": []}
    monkeypatch.setattr(
        "resume_tailor_harness.llm_runner.resolve_api_key", lambda model, **_kwargs: "key"
    )
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: type(
            "S", (), {"cheap_model": "c", "mid_model": "m", "db_url": "sqlite://"}
        )(),
    )
    monkeypatch.setattr(cli, "_engine", lambda db_url: object())
    monkeypatch.setattr(
        "resume_tailor_harness.profile.coach_store.active_session",
        lambda profile_dir: {"session_id": "s1"} if resume else None,
    )

    def opening(reporter, **kwargs):
        calls["opened"] += 1
        return _view()

    monkeypatch.setattr("resume_tailor_harness.services.profile_coach.run_opening_turn", opening)
    monkeypatch.setattr(
        "resume_tailor_harness.services.profile_coach.session_view",
        lambda profile_dir, sid: _view(),
    )

    def message(reporter, **kwargs):
        calls["messages"].append(kwargs["message"])
        return _view(
            turns=[
                {
                    "role": "coach",
                    "kind": "draft_note",
                    "text": "Draft ready.",
                    "topicId": "t1",
                    "at": "",
                    "researchActions": [],
                }
            ],
            drafts=[
                {
                    "topicId": "t1",
                    "title": "Acme deploys",
                    "summary": "Cut deploy time 40%.",
                    "quotes": [kwargs["message"]],
                    "status": "pending",
                }
            ],
        )

    monkeypatch.setattr("resume_tailor_harness.services.profile_coach.run_message_turn", message)
    monkeypatch.setattr(
        "resume_tailor_harness.services.profile_coach.run_recap_turn",
        lambda reporter, **kwargs: _view(status="ended") | {"recap": "Covered Acme."},
    )
    monkeypatch.setattr(
        "resume_tailor_harness.services.profile_coach.approve_draft",
        lambda profile_dir, sid, topic_id, **kwargs: (
            calls["approved"].append(kwargs) or "doc-1"
        ),
    )
    monkeypatch.setattr(
        "resume_tailor_harness.services.profile_coach.discard_draft",
        lambda profile_dir, sid, topic_id: calls["discarded"].append(topic_id),
    )
    monkeypatch.setattr(
        "resume_tailor_harness.services.profile_coach.run_build_with_impact",
        lambda reporter, **kwargs: calls["built"].append(kwargs) or {"impact": {}},
    )
    return profile_dir, calls


def test_coach_edits_saves_and_builds(monkeypatch, tmp_path):
    profile_dir, calls = _setup(monkeypatch, tmp_path)
    result = CliRunner().invoke(
        cli.app,
        ["profile", "coach", "--facts", str(profile_dir / "facts.json")],
        input="I cut deploy time 40%.\ne\nEdited title\nEdited summary\nEdited quote\n/end\n",
    )
    assert result.exit_code == 0, result.output
    assert calls["opened"] == 1
    assert calls["approved"][0]["title"] == "Edited title"
    assert calls["approved"][0]["quotes"] == ["Edited quote"]
    assert calls["built"]


def test_coach_resumes_active_session_and_can_leave_then_discard(monkeypatch, tmp_path):
    profile_dir, calls = _setup(monkeypatch, tmp_path, resume=True)
    # Leave the new draft pending, then discard it during /end resolution.
    result = CliRunner().invoke(
        cli.app,
        ["profile", "coach", "--facts", str(profile_dir / "facts.json"), "--no-build"],
        input="Evidence.\nl\n/end\nd\n",
    )
    assert result.exit_code == 0, result.output
    assert calls["opened"] == 0
    assert calls["discarded"] == ["t1"]
    assert not calls["built"]
