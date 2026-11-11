"""Structured logging fields used by the log viewer and container ingestion."""
import json
import logging

from aios.core.log_config import JSONFormatter, TextFormatter, request_id_var


def _record(**extra) -> logging.LogRecord:
    rec = logging.LogRecord(
        name="aios.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    rec.trace_id = "trace-1"
    rec.request_id = "req-1"
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_json_formatter_includes_ids_and_extras():
    rec = _record(http_status=200, duration_ms=12.5)
    out = json.loads(JSONFormatter().format(rec))
    assert out["message"] == "hello world"
    assert out["trace_id"] == "trace-1"
    assert out["request_id"] == "req-1"
    assert out["http_status"] == 200
    assert out["duration_ms"] == 12.5


def test_text_formatter_shows_ids_and_extras():
    rec = _record(http_path="/api/x")
    out = TextFormatter(
        "%(levelname)s [trace=%(trace_id)s req=%(request_id)s]: %(message)s"
    ).format(rec)
    assert "trace=trace-1" in out
    assert "req=req-1" in out
    assert "http_path=/api/x" in out


def test_request_id_contextvar_default():
    assert request_id_var.get() == "-"
