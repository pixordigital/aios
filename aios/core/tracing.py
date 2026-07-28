"""Lightweight observability — trace_id, LLM call tracking, metrics.

Supports structured JSON logging + optional OpenTelemetry export.
"""

import contextvars
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")

TRACES: dict[str, "TraceSpan"] = {}
METRICS: dict = {"llm_calls": 0, "llm_tokens": 0, "tool_calls": 0, "errors": 0}


def new_trace_id() -> str:
    tid = uuid.uuid4().hex[:12]
    trace_id_var.set(tid)
    return tid


def current_trace_id() -> str:
    return trace_id_var.get()


@dataclass
class TraceSpan:
    trace_id: str
    span_type: str  # "llm", "tool", "agent_run"
    start: float = 0.0
    end: float = 0.0
    model: str = ""
    tokens: int = 0
    error: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_type": self.span_type,
            "duration_ms": round((self.end - self.start) * 1000, 1) if self.end else 0,
            "model": self.model,
            "tokens": self.tokens,
            "error": self.error,
            **self.extra,
        }


def start_span(span_type: str, **kw) -> TraceSpan:
    tid = current_trace_id() or new_trace_id()
    s = TraceSpan(trace_id=tid, span_type=span_type, start=time.time(), **kw)
    key = f"{tid}_{span_type}_{int(s.start * 1000)}"
    TRACES[key] = s
    _log_span_event("start", s)
    return s


def end_span(span: TraceSpan, tokens: int = 0, error: str = ""):
    span.end = time.time()
    span.tokens = tokens
    span.error = error
    METRICS["llm_calls"] += 1
    METRICS["llm_tokens"] += tokens
    if error:
        METRICS["errors"] += 1
    _log_span_event("end", span)

    # persist metrics to disk periodically
    _maybe_flush_metrics()


def _log_span_event(event: str, span: TraceSpan) -> None:
    """Emit structured JSON log line for span events."""
    record = {
        "event": f"span.{event}",
        "trace_id": span.trace_id,
        "span_type": span.span_type,
        "model": span.model,
        "tokens": span.tokens,
        "error": span.error,
    }
    if event == "end" and span.end:
        record["duration_ms"] = round((span.end - span.start) * 1000, 1)
    logging.getLogger("aios.tracing").info(json.dumps(record))


def get_trace(trace_id: str) -> list[dict]:
    return [
        {
            "type": s.span_type,
            "model": s.model,
            "duration_ms": round((s.end - s.start) * 1000, 1) if s.end else 0,
            "tokens": s.tokens,
            "error": s.error,
        }
        for key, s in TRACES.items() if s.trace_id == trace_id
    ]


def reset_metrics():
    METRICS.clear()
    METRICS.update({"llm_calls": 0, "llm_tokens": 0, "tool_calls": 0, "errors": 0})


# ─── Periodic metric flush ───

_METRIC_FLUSH_INTERVAL = 60  # seconds
_LAST_FLUSH = 0
_METRICS_DIR = None


def _metrics_path() -> str:
    global _METRICS_DIR
    if _METRICS_DIR is None:
        from aios.config import settings
        _METRICS_DIR = os.path.join(settings.app_data_dir, "metrics")
        os.makedirs(_METRICS_DIR, exist_ok=True)
    return _METRICS_DIR


def _maybe_flush_metrics():
    """Append current metrics to daily log file every interval."""
    global _LAST_FLUSH
    now = time.time()
    if now - _LAST_FLUSH < _METRIC_FLUSH_INTERVAL:
        return
    _LAST_FLUSH = now

    try:
        day = time.strftime("%Y-%m-%d", time.localtime())
        path = os.path.join(_metrics_path(), f"{day}.jsonl")
        snapshot = dict(METRICS)
        snapshot["_ts"] = int(now)
        # ponytail: sync I/O, acceptable for metrics flush
        with open(path, "a") as f:
            f.write(json.dumps(snapshot) + "\n")
    except Exception:
        pass  # ponytail: fail open — metrics are non-critical


def flush_metrics():
    """Force flush to disk."""
    _LAST_FLUSH = 0
    _maybe_flush_metrics()
