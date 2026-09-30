# Cron Scheduler & Durable Guard

> 38 nodes · cohesion 0.06

## Key Concepts

- **main.py** (89 connections) — `aios/main.py`
- **lifespan()** (23 connections) — `aios/main.py`
- **load_durable_state()** (6 connections) — `aios/core/whatsapp_guard.py`
- **close_pool()** (5 connections) — `aios/tasks/queue.py`
- **_validate_db_config()** (4 connections) — `aios/main.py`
- **stop_cron_scheduler()** (3 connections) — `aios/core/cron_scheduler.py`
- **_is_sqlite()** (3 connections) — `aios/db/engine.py`
- **health_ready()** (3 connections) — `aios/main.py`
- **_validate_security_config()** (3 connections) — `aios/main.py`
- **docs_page()** (2 connections) — `aios/main.py`
- **health_live()** (2 connections) — `aios/main.py`
- **privacy_policy()** (2 connections) — `aios/main.py`
- **FastAPI** (2 connections)
- **terms_of_service()** (2 connections) — `aios/main.py`
- **.on_shutdown()** (2 connections) — `aios/tasks/worker.py`
- **contextlib** (2 connections)
- **Rehydrate opt-outs and live cooldowns at startup. Called once per process boot.…** (1 connections) — `aios/core/whatsapp_guard.py`
- **context_status()** (1 connections) — `aios/main.py`
- **health()** (1 connections) — `aios/main.py`
- **landing_page()** (1 connections) — `aios/main.py`
- **_failover_watch()** (1 connections) — `aios/main.py`
- **_flush_telemetry()** (1 connections) — `aios/main.py`
- **_log_scheduler()** (1 connections) — `aios/main.py`
- **AIOS — main FastAPI application.** (1 connections) — `aios/main.py`
- **# NOTE: registered AFTER dashboard_auth in source so CSRF runs BEFORE auth in…** (1 connections) — `aios/main.py`
- *... and 13 more nodes in this community*

## Relationships

- [Middleware Stack](Middleware_Stack.md) (9 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (6 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (5 shared connections)
- [Artifact Content & Storage](Artifact_Content_&_Storage.md) (5 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (4 shared connections)
- [DB Engine & Session](DB_Engine_&_Session.md) (4 shared connections)
- [RFC7807 Error Model](RFC7807_Error_Model.md) (4 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (4 shared connections)
- [Cron Ticks (Backup, CRM, Pending)](Cron_Ticks_Backup,_CRM,_Pending.md) (3 shared connections)
- [Storage Backends](Storage_Backends.md) (3 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (3 shared connections)
- [CRM2 Routes](CRM2_Routes.md) (3 shared connections)

## Source Files

- `aios/core/cron_scheduler.py`
- `aios/core/whatsapp_guard.py`
- `aios/db/engine.py`
- `aios/main.py`
- `aios/tasks/queue.py`
- `aios/tasks/worker.py`

## Audit Trail

- EXTRACTED: 124 (95%)
- INFERRED: 7 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*