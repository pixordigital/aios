# Logging Config

> 13 nodes · cohesion 0.18

## Key Concepts

- **log_config.py** (13 connections) — `aios/core/log_config.py`
- **current_trace_id()** (6 connections) — `aios/core/tracing.py`
- **sys** (4 connections)
- **JSONFormatter** (3 connections) — `aios/core/log_config.py`
- **setup_logging()** (3 connections) — `aios/core/log_config.py`
- **TraceIDFilter** (3 connections) — `aios/core/log_config.py`
- **.filter()** (3 connections) — `aios/core/log_config.py`
- **.format()** (2 connections) — `aios/core/log_config.py`
- **LogRecord** (2 connections)
- **Logging configuration — JSON or text format with trace_id injection.** (1 connections) — `aios/core/log_config.py`
- **Inject trace_id into every log record.** (1 connections) — `aios/core/log_config.py`
- **Format log records as JSON lines for container ingestion.** (1 connections) — `aios/core/log_config.py`
- **Configure root logger based on settings.log_format. Call once at startup before…** (1 connections) — `aios/core/log_config.py`

## Relationships

- [Structured Output & Traces](Structured_Output_&_Traces.md) (3 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)
- [DB Engine & Session](DB_Engine_&_Session.md) (1 shared connections)
- [SPARC Workflow Engine](SPARC_Workflow_Engine.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (1 shared connections)
- [ARVO Auth & Nonces](ARVO_Auth_&_Nonces.md) (1 shared connections)
- [Google Calendar Tools](Google_Calendar_Tools.md) (1 shared connections)

## Source Files

- `aios/core/log_config.py`
- `aios/core/tracing.py`

## Audit Trail

- EXTRACTED: 29 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*