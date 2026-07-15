"""Profile documents CRUD (+ profile build run, added in a later task)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import cast

import httpx
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from resume_agent.api.deps import (
    get_config_store,
    get_document_store,
    get_env_path,
    get_profile_dir,
    get_run_manager,
    get_settings_dep,
)
from resume_agent.api.errors import ApiException
from resume_agent.api.uploads import UploadTooLargeError, read_upload_async
from resume_agent.api.runs.manager import (
    RunManager,
    RunResetConflict,
    RunSingletonConflict,
)
from resume_agent.api.runs.models import RunState
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.config import ProfileConfigDoc
from resume_agent.api.schemas.profile import (
    DocumentOut,
    InterviewAnswersIn,
    InterviewAnswersOut,
    InterviewHistoryOut,
    MatrixOut,
    MatrixRowOut,
    NoteIn,
    SkeletonEntryOut,
    SourceOut,
    SourcePatch,
    SkillGroupOut,
    UrlIn,
)
from resume_agent.api.schemas.runs import RunOut
from resume_agent.api.schemas.secrets import LLM_KEY_ENV_VARS
from resume_agent.config import Settings
from resume_agent.llm_runner import resolve_api_key
from resume_agent.profile.corpus import (
    _UNSET,
    SourceMode,
    add_source,
    load_manifest,
    remove_source,
    update_source,
)
from resume_agent.profile.fragments import fragment_cache_status
from resume_agent.profile.github_harvest import sync_github_sources
from resume_agent.profile.intake import add_note_source, add_url_source
from resume_agent.profile.matrix import load_matrix
from resume_agent.profile.store import load_facts
from resume_agent.profile.synthesis import profile_skeleton
from resume_agent.services import profile_build
from resume_agent.services.env_config import read_env
from resume_agent.services.profile_documents import DocumentError, DocumentStore
from resume_agent.services.profile_interview import (
    interview_history_view,
    run_interview_round,
    submit_interview_answers,
)
from resume_agent.taxonomy.groups import SKILL_GROUPS

router = APIRouter()


def _docs(request: Request) -> DocumentStore:
    return get_document_store(request)


@router.get("/profile/documents", response_model=list[DocumentOut])
def list_documents(request: Request):
    return [DocumentOut.model_validate(rec) for rec in _docs(request).list()]


@router.post("/profile/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(..., alias="docType"),
):
    try:
        content = await read_upload_async(file, max_bytes=_MAX_SOURCE_BYTES)
    except UploadTooLargeError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
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
    env = read_env(get_env_path(request))
    if not any(env.get(k) for k in LLM_KEY_ENV_VARS):
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            "No LLM API key is set — add one in Settings > API Keys",
        )
    return _launch_build(request, mgr)


def _launch_build(
    request: Request,
    mgr: RunManager,
    *,
    singleton_conflict: str = "join",
) -> RunOut:
    profile_dir = _profile_dir(request)
    manifest = load_manifest(profile_dir)
    if not manifest.docs:
        resume_path = _docs(request).latest_resume_path()
        if resume_path is None:
            raise ApiException(
                400,
                "SETUP_INCOMPLETE",
                "Upload a resume document before building the profile",
            )
        # One-time migration mirroring the CLI's migrate_legacy: the wizard's
        # newest resume becomes the corpus primary.
        add_source(profile_dir, resume_path, primary=True)
    profile_cfg = cast(ProfileConfigDoc, get_config_store(request).get("profile"))
    github_username = profile_cfg.github_username
    facts_out = get_profile_dir(request) / "facts.json"

    def work(reporter):
        return profile_build.run_corpus_build(
            reporter,
            profile_dir=profile_dir,
            github_username=github_username,
            facts_out=facts_out,
            github_allow=tuple(profile_cfg.github_repo_allow),
            github_deny=tuple(profile_cfg.github_repo_deny),
            github_limit=profile_cfg.github_repo_limit,
        )

    run_id = mgr.submit(
        "profile-build",
        work,
        singleton_key="profile-build",
        singleton_conflict=singleton_conflict,
    )
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


_MAX_SOURCE_BYTES = 15 * 1024 * 1024
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _profile_dir(request: Request) -> Path:
    return get_profile_dir(request)


def _source_out(profile_dir: Path, doc) -> SourceOut:
    return SourceOut(
        id=doc.id,
        filename=doc.filename,
        mode=doc.mode,
        primary=doc.primary,
        anchor=doc.anchor,
        added_at=doc.added_at,
        fragment_status=fragment_cache_status(profile_dir, doc),
        origin=doc.origin,
    )


@router.post("/profile/interview", response_model=RunOut, status_code=202)
def launch_interview(
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    profile_dir = _profile_dir(request)
    if not any(
        doc.primary and doc.mode == "literal" for doc in load_manifest(profile_dir).docs
    ):
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            "Upload a primary resume before starting an interview",
        )
    configured = (("mid", settings.mid_model), ("cheap", settings.cheap_model))
    missing = [
        f"{tier} ({model})" for tier, model in configured if not resolve_api_key(model)
    ]
    if missing:
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            f"Missing API key for configured model(s): {', '.join(missing)}",
        )
    engine = request.app.state.engine

    def work(reporter):
        return run_interview_round(
            reporter,
            profile_dir=profile_dir,
            engine=engine,
        )

    run_id = mgr.submit(
        "profile-interview",
        work,
        singleton_key="profile-interview",
    )
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.post(
    "/profile/interview/{run_id}/answers",
    response_model=InterviewAnswersOut,
)
def answer_interview(
    run_id: str,
    payload: InterviewAnswersIn,
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    snapshot = mgr.get(run_id)
    if (
        snapshot is None
        or snapshot.kind != "profile-interview"
        or snapshot.state is not RunState.done
        or not isinstance(snapshot.result, dict)
    ):
        raise ApiException(404, "NOT_FOUND", f"No finished interview run '{run_id}'")
    round_id = snapshot.result.get("roundId")
    if not isinstance(round_id, str) or not round_id:
        raise ApiException(404, "NOT_FOUND", f"Interview run '{run_id}' has no round")
    try:
        doc_ids = submit_interview_answers(
            _profile_dir(request),
            round_id,
            [(answer.question_id, answer.text) for answer in payload.answers],
        )
    except ValueError as exc:
        if "already answered" in str(exc):
            raise ApiException(409, "ALREADY_ANSWERED", str(exc)) from exc
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc

    build_started = False
    build_run_id = None
    skipped = None
    if payload.build and doc_ids:
        try:
            build = _launch_build(request, mgr, singleton_conflict="raise")
            build_started = True
            build_run_id = build.run_id
        except (RunSingletonConflict, RunResetConflict) as exc:
            skipped = str(exc)
    elif not doc_ids:
        skipped = "no answers to build from"
    else:
        skipped = "build=false"
    return InterviewAnswersOut(
        doc_ids=doc_ids,
        build_started=build_started,
        build_run_id=build_run_id,
        build_skipped_reason=skipped,
    )


@router.get("/profile/interview/history", response_model=InterviewHistoryOut)
def interview_history(request: Request):
    return InterviewHistoryOut.model_validate(
        interview_history_view(_profile_dir(request))
    )


@router.get("/profile/sources", response_model=list[SourceOut])
def list_sources(request: Request):
    profile_dir = _profile_dir(request)
    return [_source_out(profile_dir, doc) for doc in load_manifest(profile_dir).docs]


@router.post("/profile/sources", response_model=SourceOut, status_code=201)
async def upload_source(
    request: Request,
    file: UploadFile = File(...),
    mode: SourceMode | None = Form(None),
    anchor: str | None = Form(None),
    primary: bool = Form(False),
):
    try:
        content = await read_upload_async(file, max_bytes=_MAX_SOURCE_BYTES)
    except UploadTooLargeError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    name = _UNSAFE_CHARS.sub("_", Path(file.filename or "upload").name) or "upload"
    profile_dir = _profile_dir(request)
    try:
        # add_source copies the staged file into sources/ under its original name.
        with tempfile.TemporaryDirectory() as scratch:
            staged = Path(scratch) / name
            staged.write_bytes(content)
            doc = add_source(
                profile_dir,
                staged,
                primary=primary,
                mode=mode,
                anchor=anchor,  # type: ignore[arg-type]
            )
    except ValueError as exc:
        raise ApiException(422, "VALIDATION_ERROR", str(exc)) from exc
    return _source_out(profile_dir, doc)


@router.post("/profile/sources/note", response_model=SourceOut, status_code=201)
def add_note(payload: NoteIn, request: Request):
    profile_dir = _profile_dir(request)
    try:
        doc = add_note_source(profile_dir, payload.title, payload.text)
    except ValueError as error:
        raise ApiException(422, "VALIDATION_ERROR", str(error)) from error
    return _source_out(profile_dir, doc)


@router.post("/profile/sources/url", response_model=SourceOut, status_code=201)
def add_url(payload: UrlIn, request: Request):
    profile_dir = _profile_dir(request)
    try:
        doc = add_url_source(profile_dir, str(payload.url))
    except (httpx.HTTPError, ValueError) as error:
        raise ApiException(
            422, "VALIDATION_ERROR", f"URL intake failed: {error}"
        ) from error
    return _source_out(profile_dir, doc)


@router.post("/profile/sync-github", response_model=RunOut, status_code=202)
def launch_github_sync(
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    profile_config = cast(ProfileConfigDoc, get_config_store(request).get("profile"))
    github_username = profile_config.github_username
    if not github_username:
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            "Set a GitHub username in Settings > Profile first",
        )
    profile_dir = _profile_dir(request)

    def work(_reporter):
        report = sync_github_sources(
            profile_dir,
            github_username,
            allow=tuple(profile_config.github_repo_allow),
            deny=tuple(profile_config.github_repo_deny),
            limit=profile_config.github_repo_limit,
        )
        return {
            "written": report.written,
            "removed": report.removed,
            "superseded": report.superseded,
            "failures": report.failures,
            "warnings": report.warnings,
        }

    run_id = mgr.submit("github-sync", work, singleton_key="github-sync")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.get("/profile/matrix", response_model=MatrixOut)
def get_profile_matrix(request: Request):
    matrix = load_matrix(_profile_dir(request) / "matrix.json")
    return MatrixOut(
        generated_at=matrix.generated_at if matrix is not None else "",
        groups=[
            SkillGroupOut(slug=slug, label=label)
            for slug, label in SKILL_GROUPS.items()
        ],
        rows=[MatrixRowOut.model_validate(row) for row in matrix.rows]
        if matrix is not None
        else [],
    )


@router.patch("/profile/sources/{doc_id}", response_model=SourceOut)
def patch_source(doc_id: str, payload: SourcePatch, request: Request):
    profile_dir = _profile_dir(request)
    anchor = payload.anchor if "anchor" in payload.model_fields_set else _UNSET
    try:
        doc = update_source(
            profile_dir,
            doc_id,
            mode=payload.mode,  # type: ignore[arg-type]
            anchor=anchor,
            primary=payload.primary,
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
