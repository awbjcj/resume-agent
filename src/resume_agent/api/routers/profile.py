"""Profile documents CRUD (+ profile build run, added in a later task)."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Request, UploadFile

from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.profile import DocumentOut
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
