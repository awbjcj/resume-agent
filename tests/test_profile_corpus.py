import pytest

from resume_agent.profile.corpus import (
    SourceDoc,
    SourceManifest,
    add_source,
    doc_path,
    load_manifest,
    migrate_legacy,
    remove_source,
    save_manifest,
)


def _make_doc(tmp_path, name="resume.txt", content="Ada Lovelace"):
    file = tmp_path / name
    file.write_text(content, encoding="utf-8")
    return file


def test_add_source_registers_and_copies(tmp_path):
    profile_dir = tmp_path / "profile"
    doc = add_source(profile_dir, _make_doc(tmp_path), primary=True)

    manifest = load_manifest(profile_dir)
    assert [item.id for item in manifest.docs] == [doc.id]
    assert manifest.docs[0].primary is True
    assert doc.id.startswith("resume-")
    assert doc_path(profile_dir, doc).read_text(encoding="utf-8") == "Ada Lovelace"


def test_add_source_same_content_is_noop(tmp_path):
    profile_dir = tmp_path / "profile"
    first = add_source(profile_dir, _make_doc(tmp_path))
    second = add_source(profile_dir, _make_doc(tmp_path))
    assert first.id == second.id
    assert len(load_manifest(profile_dir).docs) == 1


def test_first_source_is_automatically_primary(tmp_path):
    profile_dir = tmp_path / "profile"
    add_source(profile_dir, _make_doc(tmp_path))
    assert load_manifest(profile_dir).docs[0].primary is True


def test_add_second_primary_demotes_first(tmp_path):
    profile_dir = tmp_path / "profile"
    add_source(profile_dir, _make_doc(tmp_path, "a.txt", "A"), primary=True)
    add_source(profile_dir, _make_doc(tmp_path, "b.txt", "B"), primary=True)
    primaries = [doc for doc in load_manifest(profile_dir).docs if doc.primary]
    assert [doc.filename for doc in primaries] == ["b.txt"]


def test_add_source_rejects_unsupported_suffix(tmp_path):
    bad = tmp_path / "img.png"
    bad.write_bytes(b"\x89PNG")
    with pytest.raises(ValueError):
        add_source(tmp_path / "profile", bad)


def test_remove_source_by_filename(tmp_path):
    profile_dir = tmp_path / "profile"
    doc = add_source(profile_dir, _make_doc(tmp_path))
    removed = remove_source(profile_dir, "resume.txt")
    assert removed is not None and removed.id == doc.id
    assert load_manifest(profile_dir).docs == []
    assert doc_path(profile_dir, doc).exists()


def test_remove_source_purge_deletes_copy(tmp_path):
    profile_dir = tmp_path / "profile"
    doc = add_source(profile_dir, _make_doc(tmp_path))
    remove_source(profile_dir, doc.id, purge=True)
    assert not doc_path(profile_dir, doc).exists()


def test_remove_primary_promotes_oldest_remaining(tmp_path):
    profile_dir = tmp_path / "profile"
    first = add_source(profile_dir, _make_doc(tmp_path, "a.txt", "A"))
    second = add_source(profile_dir, _make_doc(tmp_path, "b.txt", "B"))
    remove_source(profile_dir, first.id)
    assert load_manifest(profile_dir).docs == [second.model_copy(update={"primary": True})]


def test_remove_primary_uses_manifest_order_when_timestamps_tie(tmp_path):
    profile_dir = tmp_path / "profile"
    manifest = SourceManifest(
        docs=[
            SourceDoc(
                id="primary",
                filename="primary.txt",
                sha256="0" * 64,
                added_at="2026-07-01T00:00:00+00:00",
                primary=True,
            ),
            SourceDoc(
                id="z-second",
                filename="second.txt",
                sha256="1" * 64,
                added_at="2026-07-01T00:00:00+00:00",
            ),
            SourceDoc(
                id="a-third",
                filename="third.txt",
                sha256="2" * 64,
                added_at="2026-07-01T00:00:00+00:00",
            ),
        ]
    )
    save_manifest(manifest, profile_dir)
    remove_source(profile_dir, "primary")
    assert load_manifest(profile_dir).docs[0].id == "z-second"
    assert load_manifest(profile_dir).docs[0].primary is True


def test_corrupt_manifest_fails_loudly(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "sources.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest"):
        load_manifest(profile_dir)


def test_manifest_rejects_invalid_primary_count():
    with pytest.raises(ValueError, match="exactly one primary"):
        SourceManifest(
            docs=[
                SourceDoc(
                    id="a",
                    filename="a.txt",
                    sha256="0" * 64,
                    added_at="2026-07-01T00:00:00+00:00",
                )
            ]
        )


def test_manifest_round_trip_is_atomic_file(tmp_path):
    profile_dir = tmp_path / "profile"
    add_source(profile_dir, _make_doc(tmp_path))
    save_manifest(load_manifest(profile_dir), profile_dir)
    assert not list(profile_dir.glob("*.tmp"))


def test_migrate_legacy_registers_primary_once(tmp_path):
    profile_dir = tmp_path / "profile"
    legacy = _make_doc(tmp_path, "legacy_resume.txt")
    doc = migrate_legacy(profile_dir, str(legacy))
    assert doc is not None and doc.primary is True
    assert migrate_legacy(profile_dir, str(legacy)) is None
    assert migrate_legacy(tmp_path / "other", None) is None
