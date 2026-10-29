"""RFC 9457 problem+json responses for every error the API returns."""

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

PROBLEM_JSON = "application/problem+json"

log = structlog.get_logger()


def problem(status: int, detail: str | None = None, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        **extra,
    }
    if detail:
        body["detail"] = detail
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


async def _http_error(_: Request, exc: HTTPException) -> JSONResponse:
    response = problem(exc.status_code, str(exc.detail) if exc.detail else None)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in exc.errors()
    ]
    return problem(422, "Request validation failed", errors=errors)


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    # Details stay in the logs; the client only gets the request id to quote.
    log.exception("request.unhandled_error", exc_info=exc)
    return problem(500)


def register_error_handlers(app: FastAPI) -> None:
    app.exception_handler(HTTPException)(_http_error)
    app.exception_handler(RequestValidationError)(_validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
