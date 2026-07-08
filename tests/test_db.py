from sqlmodel import select

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.tracking.tables import Job


def test_make_engine_creates_sqlite_parent_dir(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)
    assert db_path.parent.exists()


def test_init_db_creates_tables_and_session_round_trips(tmp_path):
    db_path = tmp_path / "test.db"
    engine = make_engine(f"sqlite:///{db_path}")
    init_db(engine)

    with get_session(engine) as session:
        session.add(Job(source="linkedin", jd_text="hello"))
        session.commit()

    with get_session(engine) as session:
        jobs = session.exec(select(Job)).all()
        assert len(jobs) == 1
        assert jobs[0].source == "linkedin"


def test_file_sqlite_gets_wal_and_busy_timeout(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'wal.db'}")
    init_db(engine)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1
