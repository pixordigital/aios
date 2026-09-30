# Telemetry, Triggers & Org Export

> 50 nodes · cohesion 0.05

## Key Concepts

- **.select()** (195 connections) — `aios/core/memory.py`
- **SwarmCoordinator** (18 connections) — `aios/core/swarm.py`
- **SwarmTask** (11 connections) — `aios/db/models.py`
- **get_context()** (9 connections) — `aios/integrations/arvo/routes.py`
- **process_commitment_at_risk()** (9 connections) — `aios/tasks/jobs.py`
- **LibraryIndex** (8 connections) — `aios/core/library.py`
- **check_autoscale()** (7 connections) — `aios/core/autoscaling.py`
- **telemetry_agents()** (5 connections) — `aios/api/analytics.py`
- **list_triggers()** (5 connections) — `aios/api/automations.py`
- **export_org()** (5 connections) — `aios/api/gdpr.py`
- **inbox_stats()** (5 connections) — `aios/api/inbox.py`
- **list_versions()** (5 connections) — `aios/api/versions.py`
- **.search_knowledge()** (5 connections) — `aios/core/agent_db.py`
- **.vote()** (5 connections) — `aios/core/swarm.py`
- **.flush_to_db()** (5 connections) — `aios/core/telemetry.py`
- **autoscale_job()** (5 connections) — `aios/tasks/worker.py`
- **list_executions()** (4 connections) — `aios/api/automations.py`
- **.list_learnings()** (4 connections) — `aios/core/agent_db.py`
- **.top_patterns()** (4 connections) — `aios/core/agent_db.py`
- **.recent()** (4 connections) — `aios/core/library.py`
- **.search()** (4 connections) — `aios/core/library.py`
- **.stats()** (4 connections) — `aios/core/library.py`
- **.logs()** (4 connections) — `aios/core/sparc.py`
- **.dispatch()** (4 connections) — `aios/core/swarm.py`
- **.ensure_config()** (4 connections) — `aios/core/swarm.py`
- *... and 25 more nodes in this community*

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (68 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (27 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (16 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (16 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (12 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (12 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (12 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (7 shared connections)
- [Agent DB Reflections](Agent_DB_Reflections.md) (7 shared connections)
- [Admin Fleet & DLQ](Admin_Fleet_&_DLQ.md) (6 shared connections)
- [Transactional Outbox](Transactional_Outbox.md) (6 shared connections)
- [Agents CRUD & Deploy](Agents_CRUD_&_Deploy.md) (5 shared connections)

## Source Files

- `aios/api/analytics.py`
- `aios/api/automations.py`
- `aios/api/gdpr.py`
- `aios/api/inbox.py`
- `aios/api/versions.py`
- `aios/core/agent_db.py`
- `aios/core/autoscaling.py`
- `aios/core/library.py`
- `aios/core/memory.py`
- `aios/core/sparc.py`
- `aios/core/swarm.py`
- `aios/core/telemetry.py`
- `aios/db/models.py`
- `aios/integrations/arvo/routes.py`
- `aios/tasks/jobs.py`
- `aios/tasks/worker.py`
- `aios/tools/transcribe.py`

## Audit Trail

- EXTRACTED: 104 (32%)
- INFERRED: 223 (68%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*