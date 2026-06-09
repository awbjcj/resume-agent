from resume_agent.tracking.tables import Application


def test_application_updated_at_has_onupdate():
    col = Application.__table__.c.updated_at
    assert col.onupdate is not None
