"""The Session substrate: file custody shared by every turn-per-run session kind."""

from typing import Literal

import pytest

from resume_agent.sessions.store import (
    SessionModel,
    SessionStore,
    now_iso,
    valid_session_id,
)


class _Session(SessionModel):
    ended_at: str | None = None
    payload: str = ""


@pytest.fixture()
def store() -> SessionStore[_Session]:
    return SessionStore(_Session, label="probe")


def _seed(
    store,
    root,
    session_id,
    *,
    status: Literal["active", "ended"] = "active",
    started_at="2026-07-19T00:00:00+00:00",
):
    root.mkdir(parents=True, exist_ok=True)
    store.write(
        root,
        _Session(
            session_id=session_id, started_at=started_at, status=status
        ).model_dump(mode="json"),
    )


def test_valid_session_id_rules():
    assert valid_session_id("abc-123_X")
    assert not valid_session_id("")
    assert not valid_session_id("-leading-dash")
    assert not valid_session_id("has/slash")
    assert not valid_session_id("x" * 65)


def test_path_rejects_invalid_id(store, tmp_path):
    with pytest.raises(ValueError, match="unknown session"):
        store.path(tmp_path, "../escape")


def test_write_load_round_trip_validates(store, tmp_path):
    _seed(store, tmp_path, "s1")
    loaded = store.load(tmp_path, "s1")
    assert loaded["session_id"] == "s1"
    assert (tmp_path / "session-s1.json").exists()


def test_load_unknown_raises(store, tmp_path):
    with pytest.raises(ValueError, match="unknown session"):
        store.load(tmp_path, "nope")


def test_read_invalid_json_names_the_label(store, tmp_path):
    bad = tmp_path / "session-bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid probe session"):
        store.read(tmp_path, bad)


def test_list_sorts_and_filters_archived(store, tmp_path):
    _seed(store, tmp_path, "b", started_at="2026-07-19T02:00:00+00:00")
    _seed(store, tmp_path, "a", started_at="2026-07-19T01:00:00+00:00")
    _seed(store, tmp_path, "c", status="ended", started_at="2026-07-19T00:30:00+00:00")
    store.archive(tmp_path, "c")
    assert [row["session_id"] for row in store.list(tmp_path)] == ["a", "b"]
    assert [
        row["session_id"] for row in store.list(tmp_path, include_archived=True)
    ] == ["c", "a", "b"]


def test_list_missing_root_is_empty(store, tmp_path):
    assert store.list(tmp_path / "absent") == []


def test_active_filters_status(store, tmp_path):
    _seed(store, tmp_path, "live")
    _seed(store, tmp_path, "done", status="ended")
    assert [row["session_id"] for row in store.active(tmp_path)] == ["live"]


def test_mutate_applies_and_persists(store, tmp_path):
    _seed(store, tmp_path, "s1")
    out = store.mutate(tmp_path, "s1", lambda s: s.__setitem__("payload", "changed"))
    assert out["payload"] == "changed"
    assert store.load(tmp_path, "s1")["payload"] == "changed"


def test_archive_lifecycle_rules(store, tmp_path):
    _seed(store, tmp_path, "s1")
    with pytest.raises(ValueError, match="only ended sessions can be archived"):
        store.archive(tmp_path, "s1")
    store.mutate(tmp_path, "s1", lambda s: s.__setitem__("status", "ended"))
    archived = store.archive(tmp_path, "s1")
    assert archived["archived_at"]
    with pytest.raises(ValueError, match="session already archived"):
        store.archive(tmp_path, "s1")
    restored = store.unarchive(tmp_path, "s1")
    assert restored["archived_at"] is None
    with pytest.raises(ValueError, match="session not archived"):
        store.unarchive(tmp_path, "s1")


def test_delete_removes_file_and_rejects_unknown(store, tmp_path):
    _seed(store, tmp_path, "s1")
    store.delete(tmp_path, "s1")
    assert not (tmp_path / "session-s1.json").exists()
    with pytest.raises(ValueError, match="unknown session"):
        store.delete(tmp_path, "s1")


def test_delete_where_removes_only_matches_including_archived(store, tmp_path):
    _seed(store, tmp_path, "keep")
    _seed(store, tmp_path, "drop-active")
    _seed(store, tmp_path, "drop-archived", status="ended")
    store.archive(tmp_path, "drop-archived")

    removed = store.delete_where(
        tmp_path, lambda row: row["session_id"].startswith("drop")
    )

    assert removed == 2
    assert [
        row["session_id"] for row in store.list(tmp_path, include_archived=True)
    ] == ["keep"]
    # Idempotent: nothing left to match is zero, not an error.
    assert (
        store.delete_where(tmp_path, lambda row: row["session_id"].startswith("drop"))
        == 0
    )


def test_list_skips_an_unreadable_file_but_load_still_raises(store, tmp_path, caplog):
    """One corrupt file must not take down enumeration for the whole workspace.

    `load` is a request for one named session and stays strict; `list` backs
    active-session checks and bulk deletes, where failing hard on an unrelated
    bad file is worse than omitting it.
    """
    _seed(store, tmp_path, "good")
    (tmp_path / "session-bad.json").write_text("{not json", encoding="utf-8")

    with caplog.at_level("WARNING"):
        rows = store.list(tmp_path)

    assert [row["session_id"] for row in rows] == ["good"]
    assert "session-bad.json" in caplog.text
    with pytest.raises(ValueError, match="invalid probe session"):
        store.load(tmp_path, "bad")


def test_delete_where_survives_an_unreadable_sibling(store, tmp_path):
    _seed(store, tmp_path, "drop-me")
    (tmp_path / "session-bad.json").write_text("{not json", encoding="utf-8")

    assert store.delete_where(tmp_path, lambda row: row["session_id"] == "drop-me") == 1
    # The corrupt file is left alone rather than guessed about.
    assert (tmp_path / "session-bad.json").exists()


def test_rename_trims_and_validates_title(store, tmp_path):
    _seed(store, tmp_path, "s1")
    renamed = store.rename(tmp_path, "s1", "  Interview practice  ")
    assert renamed["session_title"] == "Interview practice"
    assert store.load(tmp_path, "s1")["session_title"] == "Interview practice"
    with pytest.raises(ValueError, match="empty"):
        store.rename(tmp_path, "s1", "   ")


def test_now_iso_is_utc_seconds():
    stamp = now_iso()
    assert stamp.endswith("+00:00")
    assert "." not in stamp
