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

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ProblemResponse(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str = ""
    instance: str = ""


def _problem(status: int, title: str, detail: str = "", instance: str = "") -> dict:
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

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_problem(exc.status_code, exc.detail, "", str(request.url.path)),
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
