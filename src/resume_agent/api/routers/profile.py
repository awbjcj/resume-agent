"""Profile documents CRUD (+ profile build run, added in a later task)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from resume_agent.api.deps import get_run_manager
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.profile import DocumentOut
from resume_agent.api.schemas.runs import RunOut
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
    # deterministic regardless of the developer's real ANTHROPIC_API_KEY.
    if not read_env(request.app.state.env_path).get("ANTHROPIC_API_KEY"):
        raise ApiException(400, "SETUP_INCOMPLETE",
                           "ANTHROPIC_API_KEY is not set — add it in Settings > API Keys")
    resume_path = _docs(request).latest_resume_path()
    if resume_path is None:
        raise ApiException(400, "SETUP_INCOMPLETE",
                           "Upload a resume document before building the profile")
    profile_cfg = request.app.state.config_store.get("profile")
    github_username = profile_cfg.github_username
    facts_out = request.app.state.data_dir / "profile" / "facts.json"

    def work(reporter):
        return profile_build.run_profile_build(
            reporter, resume_path=resume_path,
            github_username=github_username, facts_out=facts_out,
        )

    run_id = mgr.submit("profile-build", work, singleton_key="profile-build")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)
