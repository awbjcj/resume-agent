from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from resume_agent import cli
from resume_agent.discovery import scout_store
from resume_agent.services import scout as scout_service


def _proposal(pid, label, *, kind="source"):
    return {
        "id": pid,
        "kind": kind,
        "source": {
            "company": label,
            "url": f"https://{label}.example/jobs",
            "ats": "greenhouse",
            "roleCount": 4,
        }
        if kind == "source"
        else None,
        "term": {"value": label, "termKind": "keyword"}
        if kind == "search_term"
        else None,
        "fitScore": 80,
        "check": "validated" if kind == "source" else "new",
        "status": "pending",
    }


def test_scout_command_snapshots_indexes_and_uses_shared_services(
    monkeypatch, tmp_path
):
    view = {
        "sessionId": "s1",
        "status": "active",
        "turns": [{"role": "scout", "text": "Found three."}],
        "proposals": [
            _proposal("p1", "Modal"),
            _proposal("p2", "Baseten"),
            _proposal("p3", "inference serving", kind="search_term"),
        ],
        "recap": None,
    }
    approved = []
    dismissed = []
    turn_lookups = []
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            mid_model="x",
            cheap_model="y",
            search_mode="auto",
            stream_enabled=False,
            browser_enabled=False,
            db_url="sqlite://",
        ),
    )
    monkeypatch.setattr(cli, "missing_model_keys", lambda settings: [])
    monkeypatch.setattr(
        cli, "plan_search", lambda *args: SimpleNamespace(strategy="tool")
    )
    monkeypatch.setattr(
        cli, "_tenant_cli_path", lambda value: Path(tmp_path) / Path(value).name
    )
    monkeypatch.setattr(scout_store, "active_session", lambda root: None)
    def start_turn(*_args, **kwargs):
        turn_lookups.append(kwargs["company_intelligence_lookup"])
        return view

    monkeypatch.setattr(scout_service, "run_start_turn", start_turn)

    def approve(_root, _sid, pid, **kwargs):
        approved.append(pid)
        next(row for row in view["proposals"] if row["id"] == pid)["status"] = "added"
        return view

    def dismiss(_root, _sid, pid, **kwargs):
        dismissed.append((pid, kwargs["reason"]))
        next(row for row in view["proposals"] if row["id"] == pid)["status"] = (
            "dismissed"
        )
        return view

    monkeypatch.setattr(scout_service, "approve_proposal", approve)
    monkeypatch.setattr(scout_service, "dismiss_proposal", dismiss)
    def recap_turn(*_args, **kwargs):
        turn_lookups.append(kwargs["company_intelligence_lookup"])
        return view | {"status": "ended", "recap": "Done"}

    monkeypatch.setattr(scout_service, "run_recap_turn", recap_turn)

    result = CliRunner().invoke(
        cli.app,
        ["scout", "AI infrastructure"],
        input="add 1 3\nskip 2 too early stage\nend\n",
    )

    assert result.exit_code == 0, result.output
    assert approved == ["p1", "p3"]
    assert dismissed == [("p2", "too early stage")]
    assert len(turn_lookups) == 2
    assert turn_lookups[0] is not turn_lookups[1]
    assert "Modal" in result.output and "inference serving" in result.output


def test_scout_resumes_active_session_and_quit_leaves_it_open(monkeypatch, tmp_path):
    view = {
        "sessionId": "s1",
        "status": "active",
        "turns": [],
        "proposals": [],
        "recap": None,
    }
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            mid_model="x",
            cheap_model="y",
            search_mode="auto",
            stream_enabled=False,
            browser_enabled=False,
            db_url="sqlite://",
        ),
    )
    monkeypatch.setattr(cli, "missing_model_keys", lambda settings: [])
    monkeypatch.setattr(
        cli, "plan_search", lambda *args: SimpleNamespace(strategy="tool")
    )
    monkeypatch.setattr(
        cli, "_tenant_cli_path", lambda value: Path(tmp_path) / Path(value).name
    )
    monkeypatch.setattr(
        scout_store, "active_session", lambda root: {"session_id": "s1"}
    )
    monkeypatch.setattr(scout_service, "session_view", lambda *args, **kwargs: view)
    monkeypatch.setattr(
        scout_service,
        "run_recap_turn",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not end")),
    )

    result = CliRunner().invoke(cli.app, ["scout"], input="quit\n")
    assert result.exit_code == 0, result.output
    assert "Resuming" in result.output


def test_scout_search_command_is_retired():
    result = CliRunner().invoke(cli.app, ["scout-search", "platform roles"])
    assert result.exit_code != 0
