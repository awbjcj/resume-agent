from pathlib import Path

import pytest

from resume_tailor_harness.security.paths import PathEscapeError, confined_path


def test_confined_path_keeps_a_child_beneath_its_root(tmp_path: Path):
    assert confined_path(tmp_path, "nested", "record.json") == (
        tmp_path / "nested" / "record.json"
    )


@pytest.mark.parametrize("candidate", ["../outside.txt", "/outside.txt"])
def test_confined_path_rejects_escape_attempts(tmp_path: Path, candidate: str):
    with pytest.raises(PathEscapeError):
        confined_path(tmp_path, candidate)
