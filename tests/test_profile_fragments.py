import json

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.corpus import add_source, load_manifest
from resume_agent.profile.fragments import (
    extract_fragments,
    fragment_cache_status,
    load_fragment,
)


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content, fail=False):
        self._content = content
        self.fail = fail
        self.calls = 0

    def run(self, prompt):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        return _FakeResult(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def _setup(tmp_path):
    profile_dir = tmp_path / "profile"
    doc_file = tmp_path / "resume.txt"
    doc_file.write_text("Ada Lovelace", encoding="utf-8")
    add_source(profile_dir, doc_file, primary=True)
    return profile_dir


def test_extracts_and_caches(tmp_path):
    profile_dir = _setup(tmp_path)
    agent = _FakeAgent(
        ProfileFacts(contact=Contact(name="Ada"), skills={"hard": [Skill(name="Python")]})
    )
    manifest = load_manifest(profile_dir)
    doc_id = manifest.docs[0].id

    first = extract_fragments(profile_dir, manifest, agent)
    assert first.status[doc_id] == "extracted"
    assert agent.calls == 1

    second = extract_fragments(profile_dir, manifest, agent)
    assert second.status[doc_id] == "cached"
    assert agent.calls == 1
    assert second.fragments[doc_id].contact.name == "Ada"


def test_fragment_ids_are_deterministic(tmp_path):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc_id = manifest.docs[0].id
    facts = ProfileFacts(
        contact=Contact(name="Ada"), skills={"hard": [Skill(name="Python")]}
    )
    extract_fragments(profile_dir, manifest, _FakeAgent(facts))
    cached = load_fragment(profile_dir, doc_id)
    assert cached is not None
    assert cached.skills["hard"][0].source_ref == doc_id


def test_source_change_repairs_manifest_and_reextracts(tmp_path):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc = manifest.docs[0]
    old_sha = doc.sha256
    extract_fragments(
        profile_dir, manifest, _FakeAgent(ProfileFacts(contact=Contact(name="Ada")))
    )
    (profile_dir / "sources" / doc.filename).write_text("Ada v2", encoding="utf-8")

    result = extract_fragments(
        profile_dir, manifest, _FakeAgent(ProfileFacts(contact=Contact(name="Ada v2")))
    )
    assert result.status[doc.id] == "source-changed"
    assert load_manifest(profile_dir).docs[0].sha256 != old_sha


def test_failure_keeps_previous_fragment(tmp_path):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc_id = manifest.docs[0].id
    extract_fragments(
        profile_dir, manifest, _FakeAgent(ProfileFacts(contact=Contact(name="Ada")))
    )
    doc = manifest.docs[0]
    (profile_dir / "sources" / doc.filename).write_text("Ada v2", encoding="utf-8")
    result = extract_fragments(profile_dir, manifest, _FakeAgent(None, fail=True))
    assert result.status[doc_id].startswith("stale: ")
    assert result.fragments[doc_id].contact.name == "Ada"


def test_failure_without_cache_reports_failed(tmp_path):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc_id = manifest.docs[0].id
    result = extract_fragments(profile_dir, manifest, _FakeAgent(None, fail=True))
    assert result.status[doc_id].startswith("failed: ")
    assert doc_id not in result.fragments


def test_malformed_metadata_is_stale_and_reextracted(tmp_path):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc = manifest.docs[0]
    agent = _FakeAgent(ProfileFacts(contact=Contact(name="Ada")))
    extract_fragments(profile_dir, manifest, agent)
    meta = profile_dir / "fragments" / f"{doc.id}.meta.json"
    meta.write_text("{broken", encoding="utf-8")
    assert fragment_cache_status(profile_dir, doc) == "stale"
    extract_fragments(profile_dir, manifest, agent)
    assert agent.calls == 2
    assert json.loads(meta.read_text(encoding="utf-8"))["sha256"] == doc.sha256


def test_cache_status_detects_changed_source_and_temp_files_are_cleaned(tmp_path):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc = manifest.docs[0]
    extract_fragments(
        profile_dir, manifest, _FakeAgent(ProfileFacts(contact=Contact(name="Ada")))
    )
    assert fragment_cache_status(profile_dir, doc) == "cached"
    assert not list((profile_dir / "fragments").glob("*.tmp"))
    (profile_dir / "sources" / doc.filename).write_text("changed", encoding="utf-8")
    assert fragment_cache_status(profile_dir, doc) == "source-changed"


def test_cache_status_is_stale_when_cached_source_disappears(tmp_path):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc = manifest.docs[0]
    extract_fragments(
        profile_dir, manifest, _FakeAgent(ProfileFacts(contact=Contact(name="Ada")))
    )
    (profile_dir / "sources" / doc.filename).unlink()
    assert fragment_cache_status(profile_dir, doc) == "stale"
