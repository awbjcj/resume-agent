"""Profile documents CRUD (+ profile build run, added in a later task)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from resume_agent.api.deps import get_run_manager
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.profile import (
    DocumentOut,
    SkeletonEntryOut,
    SourceOut,
    SourcePatch,
)
from resume_agent.api.schemas.runs import RunOut
from resume_agent.api.schemas.secrets import LLM_KEY_ENV_VARS
from resume_agent.profile.corpus import (
    _UNSET,
    add_source,
    load_manifest,
    remove_source,
    update_source,
)
from resume_agent.profile.fragments import fragment_cache_status
from resume_agent.profile.store import load_facts
from resume_agent.profile.synthesis import profile_skeleton
from resume_agent.services import profile_build
from resume_agent.services.env_config import read_env
from resume_agent.services.profile_documents import DocumentError, DocumentStore

router = APIRouter()


def _docs(request: Request) -> DocumentStore:
    return request.app.state.document_store


@router.get("/profile/documents", response_model=list[DocumentOut])
def list_documents(request: Request):
    return [DocumentOut.model_validate(rec) for rec in _docs(request).list()]


@router.post("/profile/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(..., alias="docType"),
):
    content = await file.read()
    try:
        record = _docs(request).add(file.filename or "upload", content, doc_type)
    except DocumentError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    return DocumentOut.model_validate(record)


@router.delete("/profile/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, request: Request):
    if not _docs(request).delete(doc_id):
        raise ApiException(404, "NOT_FOUND", f"No document '{doc_id}'")


@router.post("/profile/build", response_model=RunOut, status_code=202)
def launch_profile_build(request: Request, mgr: RunManager = Depends(get_run_manager)):
    # Read the key from the injected env_path — NOT app.state.settings, which
    # create_app seeds from the global get_settings() (the real .env / OS env)
    # and never re-reads env_path at startup. Using env_path keeps this gate
    # consistent with GET /api/setup/status and makes the offline test
    # deterministic regardless of the developer's real env. Any configured LLM
    # key satisfies this — profile build uses Settings.mid_model, which may
    # select a non-Anthropic provider (see llm_runner.split_provider).
    env = read_env(request.app.state.env_path)
    if not any(env.get(k) for k in LLM_KEY_ENV_VARS):
        raise ApiException(400, "SETUP_INCOMPLETE",
                           "No LLM API key is set — add one in Settings > API Keys")
    profile_dir = _profile_dir(request)
    manifest = load_manifest(profile_dir)
    if not manifest.docs:
        resume_path = _docs(request).latest_resume_path()
        if resume_path is None:
            raise ApiException(400, "SETUP_INCOMPLETE",
                               "Upload a resume document before building the profile")
        # One-time migration mirroring the CLI's migrate_legacy: the wizard's
        # newest resume becomes the corpus primary.
        add_source(profile_dir, resume_path, primary=True)
    profile_cfg = request.app.state.config_store.get("profile")
    github_username = profile_cfg.github_username
    facts_out = request.app.state.data_dir / "profile" / "facts.json"

    def work(reporter):
        return profile_build.run_corpus_build(
            reporter, profile_dir=profile_dir,
            github_username=github_username, facts_out=facts_out,
        )

    run_id = mgr.submit("profile-build", work, singleton_key="profile-build")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


_MAX_SOURCE_BYTES = 15 * 1024 * 1024
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _profile_dir(request: Request) -> Path:
    return request.app.state.data_dir / "profile"


def _source_out(profile_dir: Path, doc) -> SourceOut:
    return SourceOut(
        id=doc.id, filename=doc.filename, mode=doc.mode, primary=doc.primary,
        anchor=doc.anchor, added_at=doc.added_at,
        fragment_status=fragment_cache_status(profile_dir, doc),
    )


@router.get("/profile/sources", response_model=list[SourceOut])
def list_sources(request: Request):
    profile_dir = _profile_dir(request)
    return [_source_out(profile_dir, doc) for doc in load_manifest(profile_dir).docs]


@router.post("/profile/sources", response_model=SourceOut, status_code=201)
async def upload_source(
    request: Request,
    file: UploadFile = File(...),
    mode: str | None = Form(None),
    anchor: str | None = Form(None),
    primary: bool = Form(False),
):
    content = await file.read()
    if len(content) > _MAX_SOURCE_BYTES:
        raise ApiException(422, "VALIDATION_ERROR", "File exceeds the 15 MB limit")
    name = _UNSAFE_CHARS.sub("_", Path(file.filename or "upload").name) or "upload"
    profile_dir = _profile_dir(request)
    try:
        # add_source copies the staged file into sources/ under its original name.
        with tempfile.TemporaryDirectory() as scratch:
            staged = Path(scratch) / name
            staged.write_bytes(content)
            doc = add_source(
                profile_dir, staged, primary=primary,
                mode=mode, anchor=anchor,  # type: ignore[arg-type]
            )
    except ValueError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    return _source_out(profile_dir, doc)


@router.patch("/profile/sources/{doc_id}", response_model=SourceOut)
def patch_source(doc_id: str, payload: SourcePatch, request: Request):
    profile_dir = _profile_dir(request)
    anchor = payload.anchor if "anchor" in payload.model_fields_set else _UNSET
    try:
        doc = update_source(
            profile_dir, doc_id, mode=payload.mode,  # type: ignore[arg-type]
            anchor=anchor, primary=payload.primary,
        )
    except ValueError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    if doc is None:
        raise ApiException(404, "NOT_FOUND", f"No source '{doc_id}'")
    return _source_out(profile_dir, doc)


@router.delete("/profile/sources/{doc_id}", status_code=204)
def delete_source(doc_id: str, request: Request, purge: bool = False):
    try:
        doc = remove_source(_profile_dir(request), doc_id, purge=purge)
    except ValueError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    if doc is None:
        raise ApiException(404, "NOT_FOUND", f"No source '{doc_id}'")


@router.get("/profile/skeleton", response_model=list[SkeletonEntryOut])
def get_skeleton(request: Request):
    facts_path = _profile_dir(request) / "facts.json"
    if not facts_path.exists():
        return []
    facts = load_facts(facts_path)
    rows: list[SkeletonEntryOut] = []
    for row in profile_skeleton(facts):
        label = (
            f"{row['company']} — {row['title']}"
            if row["kind"] == "experience"
            else row["name"]
        )
        rows.append(SkeletonEntryOut(id=row["id"], kind=row["kind"], label=label))
    return rows
