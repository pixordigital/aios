"""Lightweight observability — trace_id, LLM call tracking, metrics, usage events.

Supports structured JSON logging + optional OpenTelemetry export + metered billing webhooks.
"""

import contextvars
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=""
)

# Bounded: spans were inserted on every start_span and only ever updated, never
# removed, so the dict grew monotonically until the 1536MB container was OOM
# killed. Keep the most recent N; callers already render only the tail.
TRACES_MAX = 2000
TRACES: "dict[str, TraceSpan]" = {}
METRICS: dict = {"llm_calls": 0, "llm_tokens": 0, "tool_calls": 0, "errors": 0}

# ─── Usage events for metered billing ───
# Events: voice_minutes_used, llm_tokens_used
# Webhook: POST {event, org_id, agent_id, team_id, conversation_id, quantity, unit, metadata, timestamp}


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
    # Owner of the run that produced this span. Empty for system spans that
    # predate scoping; get_trace_api treats those as unscoped for backward
    # compatibility rather than locking out every existing dashboard.
    org_id: str = ""
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
    # Evict oldest once over the cap. Insertion order is start order, so the
    # first keys are the oldest.
    if len(TRACES) > TRACES_MAX:
        for _old in list(TRACES.keys())[: len(TRACES) - TRACES_MAX]:
            TRACES.pop(_old, None)
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

    # emit llm_tokens_used for metered billing
    if tokens > 0 and span.span_type == "llm":
        extra = span.extra or {}
        org_id = extra.get("org_id")
        agent_id = extra.get("agent_id")
        team_id = extra.get("team_id")
        conversation_id = extra.get("conversation_id")
        if org_id:
            try:
                import asyncio as _aio
                _aio.create_task(emit_usage_event(
                    event="llm_tokens_used",
                    org_id=org_id,
                    quantity=float(tokens),
                    unit="tokens",
                    agent_id=agent_id,
                    team_id=team_id,
                    conversation_id=conversation_id,
                    metadata={"model": span.model, "input_tokens": extra.get("input_tokens"), "output_tokens": extra.get("output_tokens")},
                ))
            except Exception:
                pass

    # persist metrics to disk periodically
    _maybe_flush_metrics()


def _metric_upsert_stmt():
    """INSERT .. ON CONFLICT for AgentMetric, dialect-aware.

    SQLite supports ON CONFLICT from 3.24 but needs its own insert construct, and
    the Postgres one is not portable. Pick from the live bind so tests and local
    SQLite runs behave like production.
    """
    from aios.db.engine import engine
    from aios.db.models import AgentMetric
    name = engine.sync_engine.dialect.name if hasattr(engine, "sync_engine") else "postgresql"
    if name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as _ins
    else:
        from sqlalchemy.dialects.postgresql import insert as _ins
    return _ins, AgentMetric


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

            dur = int((span.end - span.start) * 1000) if span.end else 0
            tok = span.tokens or 0
            err = 1 if span.error else 0
            tc = 1 if span.span_type == "tool" else 0
            msgs = 1 if span.span_type == "agent_run" else 0
            _ins, AgentMetric = _metric_upsert_stmt()

            # Atomic upsert. The old SELECT-then-INSERT had no unique constraint,
            # so two concurrent spans for the same agent/hour both inserted, after
            # which scalar_one_or_none() raised MultipleResultsFound and the bare
            # `except Exception: pass` swallowed it -- telemetry for that agent/hour
            # was then lost forever, silently, and the duplicate rows double-counted
            # every dashboard total.
            await sess.execute(
                _ins(AgentMetric).values(
                    agent_id=agent_id, org_id=org_id, hour=hour,
                    tokens=tok, errors=err, tool_calls=tc, messages=msgs,
                    avg_response_ms=dur, samples=1,
                ).on_conflict_do_update(
                    index_elements=["agent_id", "hour"],
                    set_={
                        "tokens": AgentMetric.tokens + tok,
                        "errors": AgentMetric.errors + err,
                        "tool_calls": AgentMetric.tool_calls + tc,
                        "messages": AgentMetric.messages + msgs,
                        # weighted running mean. (avg + dur) / 2 is the mean only
                        # at n == 2, so the reported latency drifted toward the most
                        # recent call.
                        "avg_response_ms": (
                            AgentMetric.__table__.c.avg_response_ms * AgentMetric.__table__.c.samples + dur
                        ) / (AgentMetric.__table__.c.samples + 1),
                        "samples": AgentMetric.__table__.c.samples + 1,
                    },
                )
            )
            await sess.commit()
    except Exception:
        logger.exception("agent metric persist failed (agent=%s hour=%s)", agent_id, hour)



_COST_PER_1K = {
    "openai/gpt-4o": 0.005,
    "openai/gpt-4o-mini": 0.00015,
    "openai/gpt-4.1": 0.005,
    "openai/gpt-4.1-mini": 0.0004,
    "openai/gpt-4.1-nano": 0.0001,
    "openai/gpt-3.5-turbo": 0.0005,
    "openai/o3": 0.01,
    "openai/o3-mini": 0.0011,
    "openai/o4": 0.02,
    "openai/o4-mini": 0.003,
    "anthropic/claude-3-5-sonnet": 0.003,
    "anthropic/claude-3-haiku": 0.00025,
    "anthropic/claude-sonnet-4-20250514": 0.003,
    "anthropic/claude-4.5-sonnet": 0.003,
    "anthropic/claude-opus-4-20250514": 0.015,
    "anthropic/claude-3-opus": 0.015,
}

# input vs output pricing (avg)
_COST_IN_OUT = {
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4.1": (2.50, 10.00),
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "openai/gpt-4.1-nano": (0.10, 0.40),
    "openai/o3": (5.00, 20.00),
    "openai/o3-mini": (1.10, 4.40),
    "anthropic/claude-sonnet-4-20250514": (3.00, 15.00),
    "anthropic/claude-4.5-sonnet": (3.00, 15.00),
    "anthropic/claude-opus-4-20250514": (15.00, 75.00),
}


def estimate_cost(model: str, tokens: int, input_tokens: int | None = None, output_tokens: int | None = None) -> float:
    if input_tokens is not None and output_tokens is not None and model in _COST_IN_OUT:
        inp_rate, out_rate = _COST_IN_OUT[model]
        return round(input_tokens / 1000 * inp_rate / 1000 + output_tokens / 1000 * out_rate / 1000, 6) if False else round(input_tokens * inp_rate / 1_000_000 + output_tokens * out_rate / 1_000_000, 6)
    rate = _COST_PER_1K.get(model, 0.002)
    return round(tokens / 1000 * rate, 6)


def estimate_cost_detailed(model: str, input_tokens: int, output_tokens: int) -> float:
    if model in _COST_IN_OUT:
        inp, out = _COST_IN_OUT[model]
        return round(input_tokens * inp / 1_000_000 + output_tokens * out / 1_000_000, 6)
    rate = _COST_PER_1K.get(model, 0.002)
    return round((input_tokens + output_tokens) / 1000 * rate, 6)


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
    # PII auto-redaction antes de json.dumps — extra e messages
    try:
        from aios.core.pii import redact_pii, redact_pii_obj  # lazy to avoid cycle
        if span.extra:
            # redact dict/lists recursivamente; mantém estrutura mas troca valores sensíveis por ***
            record["extra"] = redact_pii_obj(span.extra)  # type: ignore
            # compat: se extra já contém "messages", também redacted via obj
            if "messages" in span.extra:
                record["messages"] = redact_pii_obj(span.extra.get("messages"))
        # também redact error/messages caso contenham PII solto
        if isinstance(record.get("error"), str) and record["error"]:
            record["error"] = redact_pii(record["error"])
        if "messages" in record and isinstance(record["messages"], str):
            record["messages"] = redact_pii(record["messages"])  # type: ignore
    except Exception:
        pass
    logging.getLogger("aios.tracing").info(json.dumps(record))


def get_trace_scoped(trace_id: str, org_id: str) -> list[dict] | None:
    """Spans for one trace, visible only to the org that produced them.

    Returns None when the trace exists but belongs to another org. Spans that
    carry no org (system spans predating scoping) stay visible, so existing
    dashboards do not go dark; spans stamped with a *different* org hide the
    whole trace rather than leaking which parts are foreign.
    """
    spans = [sp for sp in TRACES.values() if sp.trace_id == trace_id]
    if not spans:
        return []
    stamped = [sp for sp in spans if sp.org_id]
    if stamped and all(sp.org_id != org_id for sp in stamped):
        return None
    return [sp.to_dict() for sp in spans if not sp.org_id or sp.org_id == org_id]


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


# ─── Metered billing usage webhook ───
async def emit_usage_event(
    event: str,
    org_id: str,
    quantity: float,
    unit: str,
    agent_id: str | None = None,
    team_id: str | None = None,
    conversation_id: str | None = None,
    metadata: dict | None = None,
):
    """Emit usage event to configured webhook for metered billing.
    
    Events: voice_minutes_used, llm_tokens_used
    Payload: {event, org_id, agent_id, team_id, conversation_id, quantity, unit, metadata, timestamp}
    """
    from aios.config import settings
    
    url = settings.usage_webhook_url
    secret = settings.usage_webhook_secret
    if not url:
        return  # no webhook configured
    
    import httpx
    payload = {
        "event": event,
        "org_id": org_id,
        "agent_id": agent_id,
        "team_id": team_id,
        "conversation_id": conversation_id,
        "quantity": quantity,
        "unit": unit,
        "metadata": metadata or {},
        "timestamp": time.time(),
    }
    # PII auto-redaction antes de json.dumps — extra/messages equivalente: metadata
    try:
        from aios.core.pii import redact_pii_obj
        if payload.get("metadata"):
            payload["metadata"] = redact_pii_obj(payload["metadata"])
        # também redact campos que podem conter mensagem bruta com PII
        for _k in ("conversation_id", "agent_id", "team_id"):
            if isinstance(payload.get(_k), str) and payload[_k]:
                # ids normalmente não têm PII, mas mantém redaction seguro
                from aios.core.pii import redact_pii as _rp
                payload[_k] = _rp(payload[_k])  # type: ignore
    except Exception:
        pass
    
    headers = {"Content-Type": "application/json"}
    if secret:
        sig = hmac.new(
            secret.encode(), 
            json.dumps(payload, separators=(",", ":")).encode(), 
            hashlib.sha256
        ).hexdigest()
        headers["X-AIOS-Signature"] = sig
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload, headers=headers)
    except Exception:
        logger.warning("Usage webhook failed for %s", event)
