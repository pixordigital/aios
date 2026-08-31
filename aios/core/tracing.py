"""Lightweight observability — trace_id, LLM call tracking, metrics.

Supports structured JSON logging + optional OpenTelemetry export.
"""

import contextvars
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)

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
    try:
        import asyncio as _aio

        _aio.create_task(_persist_span(span))
    except Exception:
        pass
    try:
        _maybe_otel_export(span)
    except Exception:
        pass

    # persist metrics to disk periodically
    _maybe_flush_metrics()


async def _persist_span(span: TraceSpan):
    try:
        from aios.db.engine import async_session
        from aios.db.models import AgentMetric
        from datetime import datetime, timezone

        hour = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
        extra = span.extra or {}
        agent_id = extra.get("agent_id") or "unknown"
        org_id = extra.get("org_id") or "unknown"
        async with async_session() as sess:
            from sqlalchemy import select

            m = (
                await sess.execute(
                    select(AgentMetric).where(
                        AgentMetric.agent_id == agent_id, AgentMetric.hour == hour
                    )
                )
            ).scalar_one_or_none()
            dur = int((span.end - span.start) * 1000) if span.end else 0
            if m:
                m.tokens += tokens if (tokens := span.tokens) else 0
                m.errors += 1 if span.error else 0
                m.tool_calls += 1 if span.span_type == "tool" else 0
                m.messages += 1 if span.span_type == "agent_run" else 0
                m.avg_response_ms = (
                    int((m.avg_response_ms + dur) / 2) if m.avg_response_ms else dur
                )
            else:
                m = AgentMetric(
                    agent_id=agent_id,
                    org_id=org_id,
                    hour=hour,
                    tokens=span.tokens,
                    errors=1 if span.error else 0,
                    tool_calls=1 if span.span_type == "tool" else 0,
                    messages=1 if span.span_type == "agent_run" else 0,
                    avg_response_ms=dur,
                )
                sess.add(m)
            await sess.commit()
    except Exception:
        pass


_COST_PER_1K = {
    "openai/gpt-4o": 0.005,
    "openai/gpt-4o-mini": 0.00015,
    "openai/gpt-3.5-turbo": 0.0005,
    "anthropic/claude-3-5-sonnet": 0.003,
}


def estimate_cost(model: str, tokens: int) -> float:
    rate = _COST_PER_1K.get(model, 0.002)
    return round(tokens / 1000 * rate, 6)


def _maybe_otel_export(span: TraceSpan):
    try:
        import os

        ep = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not ep:
            return
        from opentelemetry import trace as _trace
        from opentelemetry.trace import SpanKind

        tracer = _trace.get_tracer("aios")
        with tracer.start_as_current_span(span.span_type, kind=SpanKind.INTERNAL) as s:
            s.set_attribute("trace_id", span.trace_id)
            s.set_attribute("model", span.model)
            s.set_attribute("tokens", span.tokens)
            s.set_attribute("cost_usd", estimate_cost(span.model, span.tokens))
            if span.error:
                s.set_attribute("error", span.error)
            for k, v in (span.extra or {}).items():
                try:
                    s.set_attribute(k, str(v)[:256])
                except Exception:
                    pass
    except Exception:
        pass


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
        for key, s in TRACES.items()
        if s.trace_id == trace_id
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
