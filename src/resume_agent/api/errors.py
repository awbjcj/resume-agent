"""Single error envelope + handlers. Every error response is { "error": {...} }."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from resume_agent.api.schemas.base import CamelModel


class ErrorBody(CamelModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(CamelModel):
    error: ErrorBody


class ApiException(Exception):
    """Raise to return a structured error with a chosen status + machine code."""

    def __init__(self, status_code: int, code: str, message: str, details: Any | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _envelope(code: str, message: str, details: Any | None = None) -> dict:
    return ErrorResponse(error=ErrorBody(code=code, message=message, details=details)).model_dump(
        by_alias=True
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api_exc(_: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_envelope("VALIDATION_ERROR", "Request validation failed", exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 409: "CONFLICT"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))
