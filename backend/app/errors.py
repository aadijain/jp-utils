"""Standard error contract and the exception handlers that produce it.

Every failure leaving the API serializes to `shared.errors.ErrorResponse` so the
add-on parses one shape. Raise `APIError` for expected, coded failures; the
handlers below also map FastAPI validation errors, Starlette HTTP exceptions, and
any uncaught exception onto the same envelope.
"""

import logging
from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.errors import ErrorBody, ErrorResponse

logger = logging.getLogger("jp_utils.backend")


class APIError(Exception):
    """An expected failure with an HTTP status and a stable machine code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status_code, content=asdict(body))


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _handle_api_error(_request: Request, exc: APIError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(422, "validation_error", "Request validation failed")

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
        return _error_response(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception")
        return _error_response(500, "internal_error", "An unexpected error occurred")
