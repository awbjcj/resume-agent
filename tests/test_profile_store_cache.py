import os

import pytest

from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.store import load_facts, save_facts


def test_load_facts_caches_until_file_changes(tmp_path):
    path = tmp_path / "facts.json"
    save_facts(ProfileFacts(contact=Contact(name="Ada")), path)
    first = load_facts(path)
    assert load_facts(path) is first  # unchanged file -> cached object

    # save_facts replaces the file (new mtime/size) -> cache invalidates
    os.utime(path, ns=(os.stat(path).st_mtime_ns + 1_000_000,) * 2)
    assert load_facts(path) is not first


def test_load_facts_missing_file_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_facts(tmp_path / "absent.json")
