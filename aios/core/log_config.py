"""Logging configuration — JSON or text format with trace_id injection."""

import json
import logging
import logging.config
import sys
from datetime import datetime, timezone

from aios.config import settings
from aios.core.tracing import current_trace_id


class TraceIDFilter(logging.Filter):
    """Inject trace_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id() or "-"
        return True


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
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0]:
            obj["exception"] = self.formatException(record.exc_info)
        if record.args:
            obj["args"] = str(record.args)
        return json.dumps(obj, default=str)


def setup_logging() -> None:
    """Configure root logger based on settings.log_format.

    Call once at startup before any other logging.
    """
    fmt = settings.log_format
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "trace_id": {"()": TraceIDFilter},
        },
        "formatters": {
            "text": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
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
            "level": "INFO",
            "handlers": ["console"],
        },
    }
    logging.config.dictConfig(config)
