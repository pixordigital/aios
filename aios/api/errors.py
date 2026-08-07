"""RFC 7807 (Problem Details) error responses.

All API errors return:
{
  "type": "about:blank",
  "title": "string",
  "status": int,
  "detail": "string",
  "instance": "/path"
}
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ProblemResponse(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str = ""
    instance: str = ""


_DEFAULT_TITLES = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    413: "Payload too large",
    422: "Unprocessable entity",
    429: "Too many requests",
    500: "Internal server error",
}


def _problem(status: int, title: str = "", detail: str = "", instance: str = "") -> dict:
    """Build a Problem Details dict. Falls back to a default title by status."""
    if not title:
        title = _DEFAULT_TITLES.get(status, "Error")
    return ProblemResponse(type="about:blank", title=title, status=status, detail=detail, instance=instance).model_dump()


def register_error_handlers(app: FastAPI):
    """Mount error handlers returning RFC 7807 problems."""

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        cleaned = []
        for e in errors:
            loc = " -> ".join(str(x) for x in e.get("loc", []))
            msg = e.get("msg", "")
            cleaned.append(f"{loc}: {msg}" if loc else msg)
        return JSONResponse(
            status_code=422,
            content=_problem(422, "Validation failed", "; ".join(cleaned), str(request.url.path)),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # StarletteHTTPException is the supertype — covers both fastapi.HTTPException
        # raises and Starlette route-miss 404/405. title derives from status; the
        # developer's message goes in detail (RFC 7807 semantics).
        return JSONResponse(
            status_code=exc.status_code,
            content=_problem(exc.status_code, detail=exc.detail or "", instance=str(request.url.path)),
        )

    @app.exception_handler(Exception)
    async def global_handler(request: Request, exc: Exception):
        import logging
        logger = logging.getLogger(__name__)
        logger.exception("Unhandled error: %s", exc)
        from aios.config import settings
        detail = str(exc) if settings.debug else "Internal server error"
        return JSONResponse(status_code=500, content=_problem(500, "Internal server error", detail, str(request.url.path)))

    return app