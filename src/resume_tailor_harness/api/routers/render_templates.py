"""Manage validated rendering templates by public id rather than path."""

from fastapi import APIRouter, Request, Response, UploadFile

from resume_tailor_harness.api.deps import get_config_store
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.schemas.render_templates import TemplateListItem
from resume_tailor_harness.api.uploads import UploadTooLargeError, read_upload
from resume_tailor_harness.render.templates import TemplateNotFoundError, list_templates
from resume_tailor_harness.services.render_templates import (
    MAX_TEMPLATE_BYTES,
    TemplateValidationError,
    delete_custom_template,
    render_preview,
    save_custom_template,
)


router = APIRouter()


def _item(info) -> TemplateListItem:
    return TemplateListItem.model_validate(info)


@router.get("/config/render/templates", response_model=list[TemplateListItem])
def get_templates() -> list[TemplateListItem]:
    return [_item(info) for info in list_templates()]


@router.post("/config/render/templates", response_model=TemplateListItem)
def upload_template(file: UploadFile) -> TemplateListItem:
    try:
        data = read_upload(file, max_bytes=MAX_TEMPLATE_BYTES)
        return _item(save_custom_template(file.filename or "", data))
    except (TemplateValidationError, UploadTooLargeError) as exc:
        raise ApiException(
            422,
            "template_invalid",
            "Template validation failed. Provide a .typ file that reads the "
            "'data' and 'zoom' system inputs.",
            details=str(exc),
        ) from exc


@router.delete("/config/render/templates/{stem}", status_code=204)
def delete_template(stem: str, request: Request) -> Response:
    try:
        deleted = delete_custom_template(stem, get_config_store(request))
    except TemplateNotFoundError as exc:
        raise ApiException(422, "template_not_found", str(exc)) from exc
    if not deleted:
        raise ApiException(422, "template_not_found", f"No custom template {stem!r}.")
    return Response(status_code=204)


@router.get("/config/render/templates/{template_id}/preview")
def preview_template(template_id: str) -> Response:
    try:
        pdf = render_preview(template_id)
    except TemplateNotFoundError as exc:
        raise ApiException(422, "template_not_found", str(exc)) from exc
    except TemplateValidationError as exc:
        raise ApiException(
            422, "template_invalid", "Template preview failed.", details=str(exc)
        ) from exc
    return Response(content=pdf, media_type="application/pdf")
