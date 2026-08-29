from sqlmodel import SQLModel


def test_application_updated_at_has_onupdate():
    col = SQLModel.metadata.tables["applications"].c.updated_at
    assert col.onupdate is not None
