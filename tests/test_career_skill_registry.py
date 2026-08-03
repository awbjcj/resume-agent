import hashlib
import json
import shutil
from pathlib import Path

import pytest

from resume_agent.career_skills.models import AgentFamily
from resume_agent.career_skills.registry import (
    SkillUnavailable,
    registry_for_paths,
)


def _manifest_entry(
    root: Path,
    name: str,
    *,
    skill_path: str | None = None,
    content: bytes = b"---\nname: resume-customizer\ndescription: test\n---\n",
    family: str = "resume_authoring",
    uses: list[str] | None = None,
    visibility: str = "public",
) -> dict:
    path = root / (skill_path or f"skills/{name}/SKILL.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    canonical = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return {
        "source": "local",
        "sourceType": "local",
        "reviewedRef": "test",
        "skillPath": skill_path or f"skills/{name}/SKILL.md",
        "computedHash": hashlib.sha256(canonical).hexdigest(),
        "localVersion": "test",
        "family": family,
        "uses": uses or ["tailor"],
        "visibility": visibility,
    }


def _write_manifest(path: Path, entries: dict[str, dict]) -> None:
    path.write_text(
        json.dumps(
            {"version": 2, "hashMode": "utf8-lf-v1", "skills": entries},
            indent=2,
        ),
        encoding="utf-8",
    )


def test_shipped_manifest_covers_every_skill_once():
    registry = registry_for_paths(Path("skills"), Path("skills-lock.json"))

    assert len(registry.all()) == 35
    assert len(registry.public_capabilities()) == 34
    assert registry.require(
        "project-dossier", family=AgentFamily.INTERNAL_PROFILE, use="profile_project"
    ).ref.name == "project-dossier"
    assert all(skill.ref.sha256 for skill in registry.all())


@pytest.mark.parametrize(
    "failure", ["traversal", "symlink_escape", "hash", "utf8", "oversize", "duplicate"]
)
def test_invalid_manifest_entry_fails_only_its_capability(tmp_path, failure):
    root = tmp_path / "root"
    manifest = tmp_path / "skills-lock.json"
    good = _manifest_entry(
        root,
        "job-fit-analyzer",
        content=b"---\nname: job-fit-analyzer\ndescription: good\n---\n",
        family="job_analysis",
        uses=["fit"],
    )
    bad_content = b"---\nname: resume-customizer\ndescription: bad\n---\n"
    bad = _manifest_entry(
        root,
        "resume-customizer",
        content=bad_content,
        family="resume_authoring",
        uses=["tailor"],
    )
    if failure == "traversal":
        bad["skillPath"] = "../outside/SKILL.md"
    elif failure == "hash":
        bad["computedHash"] = "0" * 64
    elif failure == "utf8":
        path = root / bad["skillPath"]
        path.write_bytes(b"\xff\xfe")
    elif failure == "oversize":
        path = root / bad["skillPath"]
        path.write_bytes(
            b"---\nname: resume-customizer\ndescription: bad\n---\n"
            + b"x" * (256 * 1024)
        )
    elif failure == "duplicate":
        bad["skillPath"] = good["skillPath"]
    elif failure == "symlink_escape":
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_skill = outside / "SKILL.md"
        outside_skill.write_bytes(bad_content)
        link = root / "skills" / "resume-customizer"
        shutil.rmtree(link)
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks are unavailable in this Windows test environment")

    _write_manifest(
        manifest,
        {"job-fit-analyzer": good, "resume-customizer": bad},
    )
    registry = registry_for_paths(root, manifest)

    with pytest.raises(SkillUnavailable):
        registry.require(
            "resume-customizer", family=AgentFamily.RESUME_AUTHORING, use="tailor"
        )
    assert registry.require(
        "job-fit-analyzer", family=AgentFamily.JOB_ANALYSIS, use="fit"
    ).ref.name == "job-fit-analyzer"


def test_registry_resolves_paths_consistently(tmp_path):
    root = tmp_path / "root"
    manifest = tmp_path / "skills-lock.json"
    entry = _manifest_entry(
        root,
        "job-fit-analyzer",
        content=b"---\nname: job-fit-analyzer\ndescription: good\n---\n",
        family="job_analysis",
        uses=["fit"],
    )
    _write_manifest(manifest, {"job-fit-analyzer": entry})

    first = registry_for_paths(root, manifest)
    second = registry_for_paths(root.resolve(), manifest.resolve())
    assert first.root == second.root
    assert first.manifest_path == second.manifest_path


def test_registry_revalidates_a_skill_after_the_file_changes(tmp_path):
    root = tmp_path / "root"
    manifest = tmp_path / "skills-lock.json"
    entry = _manifest_entry(
        root,
        "job-fit-analyzer",
        content=b"---\nname: job-fit-analyzer\ndescription: good\n---\n",
        family="job_analysis",
        uses=["fit"],
    )
    _write_manifest(manifest, {"job-fit-analyzer": entry})
    first = registry_for_paths(root, manifest)

    (root / entry["skillPath"]).write_bytes(
        b"---\nname: job-fit-analyzer\ndescription: changed\n---\n"
    )
    second = registry_for_paths(root, manifest)

    assert first is not second
    with pytest.raises(SkillUnavailable):
        second.require(
            "job-fit-analyzer", family=AgentFamily.JOB_ANALYSIS, use="fit"
        )
