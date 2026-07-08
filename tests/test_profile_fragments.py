import json

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.corpus import add_source, load_manifest, remove_source
from resume_agent.profile.fragments import (
    extract_fragments,
    extract_synthesis_fragments,
    fragment_cache_status,
    load_fragment,
)
from resume_agent.profile.synthesis import (
    ClaimVerdict,
    ClaimVerdicts,
    SynthesizedClaim,
    SynthesizedEntry,
    SynthesizedFragment,
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


def test_converter_version_bump_invalidates_cache(tmp_path, monkeypatch):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc_id = manifest.docs[0].id
    agent = _FakeAgent(ProfileFacts(contact=Contact(name="Ada")))

    extract_fragments(profile_dir, manifest, agent)
    assert agent.calls == 1

    monkeypatch.setattr("resume_agent.profile.fragments.CONVERTER_VERSION", 99)
    again = extract_fragments(profile_dir, load_manifest(profile_dir), agent)
    assert agent.calls == 2
    assert again.status[doc_id] == "extracted"


def _corpus_with_deck(tmp_path):
    profile_dir = tmp_path / "profile"
    resume = tmp_path / "resume.txt"
    resume.write_text("Ada Lovelace", encoding="utf-8")
    add_source(profile_dir, resume, primary=True)
    deck = tmp_path / "deck.md"
    deck.write_text("Cut latency 30% at Acme.", encoding="utf-8")
    doc = add_source(profile_dir, deck, mode="synthesis")
    return profile_dir, doc


_SKELETON = [{"id": "exp1", "kind": "experience", "company": "Acme",
              "title": "Engineer", "start": None, "end": None}]


def _synth_agent():
    return _FakeAgent(SynthesizedFragment(entries=[SynthesizedEntry(
        kind="experience_bullets", anchor_id="exp1",
        claims=[SynthesizedClaim(text="Cut latency 30%",
                                 support=["Cut latency 30%"])],
    )]))


class _ApproveAll:
    calls = 0

    def run(self, prompt):
        self.calls += 1
        claims = json.loads(prompt)
        return _FakeResult(ClaimVerdicts(verdicts=[
            ClaimVerdict(index=c["index"], verdict="supported") for c in claims
        ]))

    async def arun(self, prompt):
        return self.run(prompt)


def test_extract_fragments_skips_synthesis_docs(tmp_path):
    profile_dir, doc = _corpus_with_deck(tmp_path)
    agent = _FakeAgent(ProfileFacts(contact=Contact(name="Ada")))
    result = extract_fragments(profile_dir, load_manifest(profile_dir), agent)
    assert doc.id not in result.fragments
    assert agent.calls == 1  # only the literal resume


def test_synthesis_fragments_cache_and_write_evidence(tmp_path):
    profile_dir, doc = _corpus_with_deck(tmp_path)
    synth = _synth_agent()

    first = extract_synthesis_fragments(
        profile_dir, load_manifest(profile_dir), _SKELETON, synth, _ApproveAll()
    )
    assert first.status[doc.id] == "extracted"
    assert synth.calls == 1
    stub = first.fragments[doc.id].experience[0]
    assert stub.id == "exp1" and stub.bullets[0].synthesized

    evidence_path = profile_dir / "fragments" / f"{doc.id}.evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload[stub.bullets[0].id]["support"] == ["Cut latency 30%"]

    second = extract_synthesis_fragments(
        profile_dir, load_manifest(profile_dir), _SKELETON, synth, _ApproveAll()
    )
    assert second.status[doc.id] == "cached"
    assert synth.calls == 1


def test_anchor_change_invalidates_synthesis_cache(tmp_path):
    from resume_agent.profile.corpus import update_source

    profile_dir, doc = _corpus_with_deck(tmp_path)
    synth = _synth_agent()
    extract_synthesis_fragments(
        profile_dir, load_manifest(profile_dir), _SKELETON, synth, _ApproveAll()
    )
    update_source(profile_dir, doc.id, anchor="exp1")
    extract_synthesis_fragments(
        profile_dir, load_manifest(profile_dir), _SKELETON, synth, _ApproveAll()
    )
    assert synth.calls == 2


def test_synthesis_failure_keeps_previous_fragment(tmp_path):
    profile_dir, doc = _corpus_with_deck(tmp_path)
    extract_synthesis_fragments(
        profile_dir, load_manifest(profile_dir), _SKELETON, _synth_agent(), _ApproveAll()
    )
    deck = profile_dir / "sources" / "deck.md"
    deck.write_text("Different text now.", encoding="utf-8")

    failing = _FakeAgent(None, fail=True)
    result = extract_synthesis_fragments(
        profile_dir, load_manifest(profile_dir), _SKELETON, failing, _ApproveAll()
    )
    assert result.status[doc.id].startswith("stale")
    assert result.fragments[doc.id].experience[0].id == "exp1"  # cached fragment served


def test_remove_source_deletes_evidence_sidecar(tmp_path):
    profile_dir, doc = _corpus_with_deck(tmp_path)
    extract_synthesis_fragments(
        profile_dir, load_manifest(profile_dir), _SKELETON, _synth_agent(), _ApproveAll()
    )
    evidence_path = profile_dir / "fragments" / f"{doc.id}.evidence.json"
    assert evidence_path.exists()
    remove_source(profile_dir, doc.id)
    assert not evidence_path.exists()


def test_walk_stale_fallback_is_shared_by_both_modes(tmp_path):
    profile_dir = _setup(tmp_path)
    manifest = load_manifest(profile_dir)
    doc_id = manifest.docs[0].id
    good = ProfileFacts(contact=Contact(name="Ada"))
    extract_fragments(profile_dir, manifest, _FakeAgent(good))

    (tmp_path / "profile" / "sources" / "resume.txt").write_text(
        "Ada v2", encoding="utf-8"
    )
    result = extract_fragments(
        profile_dir, load_manifest(profile_dir), _FakeAgent(None, fail=True)
    )

    assert result.status[doc_id].startswith("stale:")
    assert result.fragments[doc_id].contact.name == "Ada"
