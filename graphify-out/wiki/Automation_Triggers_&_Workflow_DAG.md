# Automation Triggers & Workflow DAG

> 55 nodes · cohesion 0.09

## Key Concepts

- **Workflow** (61 connections) — `aios/db/models.py`
- **jobs.py** (52 connections) — `aios/tasks/jobs.py`
- **workflows.py** (49 connections) — `aios/api/workflows.py`
- **WorkflowRun** (33 connections) — `aios/db/models.py`
- **enqueue_job()** (27 connections) — `aios/tasks/queue.py`
- **WorkflowEngine** (24 connections) — `aios/core/workflow.py`
- **WorkflowDef** (13 connections) — `aios/core/workflow.py`
- **WorkflowNode** (12 connections) — `aios/core/workflow.py`
- **webhook_dispatch()** (11 connections) — `aios/api/automations.py`
- **add_node()** (11 connections) — `aios/api/workflows.py`
- **automations_run()** (11 connections) — `aios/dashboard/app.py`
- **._execute_node()** (10 connections) — `aios/core/workflow.py`
- **patch_workflow()** (9 connections) — `aios/api/workflows.py`
- **replay_run()** (9 connections) — `aios/api/workflows.py`
- **run_workflow()** (9 connections) — `aios/api/workflows.py`
- **create_workflow()** (8 connections) — `aios/api/workflows.py`
- **resume_run()** (8 connections) — `aios/api/workflows.py`
- **workflow_run_job()** (8 connections) — `aios/tasks/jobs.py`
- **import_workflow()** (7 connections) — `aios/api/workflows.py`
- **post** (7 connections)
- **_tick()** (7 connections) — `aios/core/cron_scheduler.py`
- **.run()** (7 connections) — `aios/core/workflow.py`
- **download_voice_recording()** (7 connections) — `aios/tasks/jobs.py`
- **fire_event_triggers()** (6 connections) — `aios/api/automations.py`
- **eval_workflow_run()** (6 connections) — `aios/api/workflows.py`
- *... and 30 more nodes in this community*

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (37 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (26 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (26 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (18 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (12 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (12 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (10 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (8 shared connections)
- [Admin Fleet & DLQ](Admin_Fleet_&_DLQ.md) (7 shared connections)
- [Cron Ticks (Backup, CRM, Pending)](Cron_Ticks_Backup,_CRM,_Pending.md) (5 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (4 shared connections)
- [CRM2 Routes](CRM2_Routes.md) (3 shared connections)

## Source Files

- `aios/api/automations.py`
- `aios/api/workflows.py`
- `aios/core/cron_scheduler.py`
- `aios/core/workflow.py`
- `aios/dashboard/app.py`
- `aios/db/models.py`
- `aios/tasks/jobs.py`
- `aios/tasks/queue.py`

## Audit Trail

- EXTRACTED: 212 (60%)
- INFERRED: 141 (40%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*