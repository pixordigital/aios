# Structured Output & Traces

> 20 nodes · cohesion 0.17

## Key Concepts

- **tracing.py** (33 connections) — `aios/core/tracing.py`
- **end_span()** (9 connections) — `aios/core/tracing.py`
- **.run_structured()** (7 connections) — `aios/core/agent.py`
- **_log_span_event()** (7 connections) — `aios/core/tracing.py`
- **start_span()** (7 connections) — `aios/core/tracing.py`
- **TraceSpan** (7 connections) — `aios/core/tracing.py`
- **_maybe_flush_metrics()** (5 connections) — `aios/core/tracing.py`
- **_persist_span()** (5 connections) — `aios/core/tracing.py`
- **_maybe_otel_export()** (4 connections) — `aios/core/tracing.py`
- **new_trace_id()** (4 connections) — `aios/core/tracing.py`
- **flush_metrics()** (2 connections) — `aios/core/tracing.py`
- **_metrics_path()** (2 connections) — `aios/core/tracing.py`
- **Run agent with forced structured output matching output_schema.** (1 connections) — `aios/core/agent.py`
- **estimate_cost_detailed()** (1 connections) — `aios/core/tracing.py`
- **Lightweight observability — trace_id, LLM call tracking, metrics, usage events.…** (1 connections) — `aios/core/tracing.py`
- **Emit structured JSON log line for span events.** (1 connections) — `aios/core/tracing.py`
- **Append current metrics to daily log file every interval.** (1 connections) — `aios/core/tracing.py`
- **reset_metrics()** (1 connections) — `aios/core/tracing.py`
- **.to_dict()** (1 connections) — `aios/core/tracing.py`
- **contextvars** (1 connections)

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (10 shared connections)
- [IVR, PII Redaction & Call Routing](IVR,_PII_Redaction_&_Call_Routing.md) (7 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (3 shared connections)
- [Logging Config](Logging_Config.md) (3 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (2 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (2 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (2 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (1 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (1 shared connections)
- [Middleware Stack](Middleware_Stack.md) (1 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (1 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)

## Source Files

- `aios/core/agent.py`
- `aios/core/tracing.py`

## Audit Trail

- EXTRACTED: 66 (99%)
- INFERRED: 1 (1%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*