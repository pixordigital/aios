# Admin Fleet & DLQ

> 56 nodes · cohesion 0.06

## Key Concepts

- **admin_api.py** (29 connections) — `aios/api/admin_api.py`
- **get_redis_pool()** (17 connections) — `aios/tasks/queue.py`
- **test_dead_letter.py** (17 connections) — `tests/test_dead_letter.py`
- **write_dlq()** (16 connections) — `aios/core/dead_letter.py`
- **delivery.py** (16 connections) — `aios/core/delivery.py`
- **dead_letter.py** (15 connections) — `aios/core/dead_letter.py`
- **DeadLetter** (14 connections) — `aios/db/models.py`
- **deliver_message()** (13 connections) — `aios/core/delivery.py`
- **retry_dlq()** (12 connections) — `aios/core/dead_letter.py`
- **list_dlq()** (9 connections) — `aios/core/dead_letter.py`
- **agent_run()** (9 connections) — `aios/tasks/jobs.py`
- **admin_dlq()** (8 connections) — `aios/dashboard/app.py`
- **test_dlq_retry_sets_status()** (8 connections) — `tests/test_dead_letter.py`
- **fleet_health_refresh()** (6 connections) — `aios/api/admin_api.py`
- **register_remote_admin()** (6 connections) — `aios/api/admin_api.py`
- **remote_health()** (6 connections) — `aios/api/admin_api.py`
- **clear_dlq()** (5 connections) — `aios/api/admin_api.py`
- **post** (5 connections)
- **clear_dlq()** (5 connections) — `aios/core/dead_letter.py`
- **_entry_to_dict()** (5 connections) — `aios/core/dead_letter.py`
- **_now()** (5 connections) — `aios/db/models.py`
- **_admin_headers()** (5 connections) — `tests/test_dead_letter.py`
- **retry_dlq_endpoint()** (4 connections) — `aios/api/admin_api.py`
- **get_dlq()** (3 connections) — `aios/api/admin_api.py`
- **reset_agent_health()** (3 connections) — `aios/api/admin_api.py`
- *... and 31 more nodes in this community*

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (25 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (8 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (8 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (7 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (7 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (7 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (6 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (4 shared connections)
- [Evolution Key Rotation & IP Allowlist](Evolution_Key_Rotation_&_IP_Allowlist.md) (4 shared connections)
- [LLM Retry & Inbound Processing](LLM_Retry_&_Inbound_Processing.md) (3 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (2 shared connections)
- [Discord Webhook](Discord_Webhook.md) (2 shared connections)

## Source Files

- `aios/api/admin_api.py`
- `aios/core/dead_letter.py`
- `aios/core/delivery.py`
- `aios/dashboard/app.py`
- `aios/db/models.py`
- `aios/tasks/jobs.py`
- `aios/tasks/queue.py`
- `tests/test_dead_letter.py`

## Audit Trail

- EXTRACTED: 163 (86%)
- INFERRED: 27 (14%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*