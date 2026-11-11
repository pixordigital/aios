"""Logging configuration — JSON or text format with trace/request id injection."""

import contextvars
import json
import logging
import logging.config
import sys
from datetime import datetime, timezone

from aios.config import settings
from aios.core.tracing import current_trace_id

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_STANDARD_FIELDS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "trace_id", "request_id",
}


class TraceIDFilter(logging.Filter):
    """Inject trace_id and request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id() or "-"
        record.request_id = request_id_var.get() or "-"
        return True


def _extra_fields(record: logging.LogRecord) -> dict:
    """Non-standard fields passed through ``logger.info(..., extra={...})``."""
    return {
        k: v for k, v in record.__dict__.items()
        if k not in _STANDARD_FIELDS and not k.startswith("_")
    }


class JSONFormatter(logging.Formatter):
    """Format log records as JSON lines for container ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        now = datetime.fromtimestamp(record.created, tz=timezone.utc)
        obj = {
            "timestamp": now.isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", "-"),
            "request_id": getattr(record, "request_id", "-"),
            "module": record.module,
            "line": record.lineno,
        }
        obj.update(_extra_fields(record))
        if record.exc_info and record.exc_info[0]:
            obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str)


class TextFormatter(logging.Formatter):
    """Compact single-line text logs for local development."""

    def format(self, record: logging.LogRecord) -> str:
        record.trace_id = getattr(record, "trace_id", "-")
        record.request_id = getattr(record, "request_id", "-")
        base = super().format(record)
        extras = _extra_fields(record)
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def setup_logging() -> None:
    """Configure root logger based on settings.log_format/log_level.

    Call once at startup before any other logging.
    """
    fmt = settings.log_format
    level = (settings.log_level or "INFO").upper()
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "trace_id": {"()": TraceIDFilter},
        },
        "formatters": {
            "text": {
                "()": TextFormatter,
                "format": "%(asctime)s [%(levelname)s] %(name)s [trace=%(trace_id)s req=%(request_id)s]: %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            },
            "json": {
                "()": JSONFormatter,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": sys.stdout,
                "filters": ["trace_id"],
                "formatter": fmt if fmt == "json" else "text",
            },
        },
        "root": {
            "level": level,
            "handlers": ["console"],
        },
    }
    logging.config.dictConfig(config)
