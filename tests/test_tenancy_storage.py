from pathlib import Path

import pytest

from resume_agent.config import Settings
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.storage import (
    TenantPathError,
    artifact_path,
    resolve_artifact_pdf,
)
from resume_agent.tenancy.workspace import WorkspacePaths


def _context(paths: WorkspacePaths) -> UserContext:
    return UserContext(
        user_id="alice0000000",
        username="alice",
        role="user",
        paths=paths,
        settings=Settings(_env_file=None),  # type: ignore[call-arg]
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )


def test_artifact_path_resolves_cwd_relative_pdf_path_under_relative_data_dir(
    tmp_path, monkeypatch
):
    """Reproduces the production bug: data_dir configured relatively (as the
    app default is), so context.paths.output_dir and freshly rendered
    pdf_path values are both CWD-relative, not tenant-root-prefixed."""
    monkeypatch.chdir(tmp_path)
    workspace = WorkspacePaths(Path("data") / "users" / "alice0000000")
    real_pdf = tmp_path / workspace.output_dir / "acme-role-1"
    real_pdf.mkdir(parents=True)
    (real_pdf / "resume-v1-tailor.pdf").write_bytes(b"%PDF-1.4")

    pdf_path = str(workspace.output_dir / "acme-role-1" / "resume-v1-tailor.pdf")
    assert not Path(pdf_path).is_absolute()

    with use_context(_context(workspace)):
        resolved = artifact_path(pdf_path)

    assert resolved.is_file()
    assert resolved == (tmp_path / workspace.output_dir / "acme-role-1" / "resume-v1-tailor.pdf").resolve()


def test_artifact_path_still_rejects_paths_outside_the_tenant_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    workspace = WorkspacePaths(Path("data") / "users" / "alice0000000")
    workspace.output_dir.mkdir(parents=True)
    outside = Path("..") / "escaped.pdf"

    with use_context(_context(workspace)), pytest.raises(TenantPathError):
        artifact_path(str(outside))


def test_artifact_path_still_honors_output_prefix_from_import_normalization(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    workspace = WorkspacePaths(Path("data") / "users" / "alice0000000")
    real_pdf = tmp_path / workspace.output_dir / "acme-role-1"
    real_pdf.mkdir(parents=True)
    (real_pdf / "resume-v1-tailor.pdf").write_bytes(b"%PDF-1.4")

    with use_context(_context(workspace)):
        resolved = artifact_path("output/acme-role-1/resume-v1-tailor.pdf")

    assert resolved.is_file()


def test_resolve_artifact_pdf_returns_none_for_unset_path():
    assert resolve_artifact_pdf(None) is None
    assert resolve_artifact_pdf("") is None


def test_resolve_artifact_pdf_swallows_tenant_path_escape(tmp_path, monkeypatch):
    """The same escape ``artifact_path`` raises on is a 404, never a 500."""
    monkeypatch.chdir(tmp_path)
    workspace = WorkspacePaths(Path("data") / "users" / "alice0000000")
    workspace.output_dir.mkdir(parents=True)
    (tmp_path / "escaped.pdf").write_bytes(b"%PDF-1.4")
    outside = str(Path("..") / "escaped.pdf")

    with use_context(_context(workspace)):
        with pytest.raises(TenantPathError):
            artifact_path(outside)
        assert resolve_artifact_pdf(outside) is None


def test_resolve_artifact_pdf_returns_the_resolved_path_for_an_existing_file(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    workspace = WorkspacePaths(Path("data") / "users" / "alice0000000")
    rendered = tmp_path / workspace.output_dir / "acme-role-1"
    rendered.mkdir(parents=True)
    (rendered / "resume-v1-tailor.pdf").write_bytes(b"%PDF-1.4")
    pdf_path = str(workspace.output_dir / "acme-role-1" / "resume-v1-tailor.pdf")

    with use_context(_context(workspace)):
        resolved = resolve_artifact_pdf(pdf_path)

    assert resolved == (rendered / "resume-v1-tailor.pdf").resolve()
    assert resolved is not None and resolved.is_file()
