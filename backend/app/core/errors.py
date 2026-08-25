"""Standard error envelope and application exceptions.

Every error response has the shape:

    {"error": {"code": "...", "message": "...", "field_errors": {...}, "request_id": "..."}}

HTTP status mapping (frozen by the blueprint):
- 422 validation, 403 authorization, 401 authentication,
- 409 invalid state transitions / concurrency conflicts,
- 404 not found, 500 unexpected.
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import request_id_var

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """Base application error carried to the standard envelope."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"

    def __init__(self, message: str, *, code: str | None = None, field_errors: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.field_errors = field_errors or {}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHENTICATED"


class AuthorizationError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class ValidationFailedError(AppError):
    status_code = 422
    code = "VALIDATION_FAILED"


class ConflictError(AppError):
    """Invalid state transition or concurrency conflict."""

    status_code = status.HTTP_409_CONFLICT
    code = "INVALID_STATE_TRANSITION"


class IdempotencyConflictError(ConflictError):
    code = "IDEMPOTENCY_CONFLICT"


def _envelope(code: str, message: str, field_errors: dict | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "field_errors": field_errors or {},
            "request_id": request_id_var.get(),
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.field_errors),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        field_errors: dict[str, list[str]] = {}
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []) if p not in ("body", "query", "path"))
            field_errors.setdefault(loc or "_", []).append(err.get("msg", "Invalid value"))
        return JSONResponse(
            status_code=422,
            content=_envelope("VALIDATION_FAILED", "The request contains invalid fields.", field_errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
        code = codes.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak raw database/storage errors to the client.
        logger.exception("Unhandled error", extra={"route": request.url.path})
        return JSONResponse(
            status_code=500,
            content=_envelope("INTERNAL_ERROR", "An unexpected error occurred. Please retry."),
        )
