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

    def __init__(
        self, status_code: int, code: str, message: str, details: Any | None = None
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _envelope(code: str, message: str, details: Any | None = None) -> dict:
    return ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details)
    ).model_dump(by_alias=True)


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Return Pydantic validation details that JSONResponse can always encode."""
    details: list[dict[str, Any]] = []
    for error in exc.errors():
        context = error.get("ctx")
        if context:
            error = {
                **error,
                "ctx": {
                    key: str(value) if isinstance(value, BaseException) else value
                    for key, value in context.items()
                },
            }
        details.append(error)
    return details


def install_error_handlers(app: FastAPI) -> None:
    from resume_agent.tenancy.limits import CostRateUnavailableError
    from resume_agent.tenancy.quotas import (
        CostQuotaExceededError,
        GlobalCostQuotaExceededError,
    )

    @app.exception_handler(CostQuotaExceededError)
    async def _cost_quota(_: Request, exc: CostQuotaExceededError) -> JSONResponse:
        return JSONResponse(status_code=429, content=_envelope(exc.code, str(exc)))

    @app.exception_handler(GlobalCostQuotaExceededError)
    async def _global_cost_quota(
        _: Request, exc: GlobalCostQuotaExceededError
    ) -> JSONResponse:
        return JSONResponse(status_code=429, content=_envelope(exc.code, str(exc)))

    @app.exception_handler(CostRateUnavailableError)
    async def _cost_rate(_: Request, exc: CostRateUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content=_envelope(exc.code, str(exc)))

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
            content=_envelope(
                "VALIDATION_ERROR",
                "Request validation failed",
                _validation_details(exc),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            404: "NOT_FOUND",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            409: "CONFLICT",
        }.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code, content=_envelope(code, str(exc.detail))
        )
