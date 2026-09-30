# Analytics, Proactive Alerts & pgvector

> 59 nodes · cohesion 0.05

## Key Concepts

- **DatabaseBackend** (249 connections) — `aios/db/backend.py`
- **analytics.py** (46 connections) — `aios/api/analytics.py`
- **automations.py** (38 connections) — `aios/api/automations.py`
- **get_proactive_alerts()** (7 connections) — `aios/api/analytics.py`
- **create_from_template()** (7 connections) — `aios/api/automations.py`
- **create_trigger()** (7 connections) — `aios/api/automations.py`
- **toggle_proactive_alerts()** (6 connections) — `aios/api/analytics.py`
- **create_credential()** (6 connections) — `aios/api/automations.py`
- **telemetry_agent()** (4 connections) — `aios/api/analytics.py`
- **usage_daily()** (4 connections) — `aios/api/analytics.py`
- **delete_credential()** (4 connections) — `aios/api/automations.py`
- **delete_trigger()** (4 connections) — `aios/api/automations.py`
- **list_credentials()** (4 connections) — `aios/api/automations.py`
- **_require_role()** (4 connections) — `aios/api/automations.py`
- **update_trigger()** (4 connections) — `aios/api/automations.py`
- **list_files()** (4 connections) — `aios/api/files.py`
- **oauth_status()** (4 connections) — `aios/api/integrations.py`
- **list_memories()** (4 connections) — `aios/api/knowledge.py`
- **delete_secret()** (4 connections) — `aios/api/secrets.py`
- **diff_version()** (4 connections) — `aios/api/versions.py`
- **get_trace_api()** (3 connections) — `aios/api/analytics.py`
- **OverviewOut** (3 connections) — `aios/api/analytics.py`
- **pgvector_health()** (3 connections) — `aios/api/analytics.py`
- **ProactiveAlertsToggle** (3 connections) — `aios/api/analytics.py`
- **telemetry_flush()** (3 connections) — `aios/api/analytics.py`
- *... and 34 more nodes in this community*

## Relationships

- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (53 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (26 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (24 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (17 shared connections)
- [Agents CRUD & Deploy](Agents_CRUD_&_Deploy.md) (17 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (17 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (16 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (14 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (14 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (12 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (11 shared connections)
- [CRM2 API](CRM2_API.md) (11 shared connections)

## Source Files

- `aios/api/analytics.py`
- `aios/api/automations.py`
- `aios/api/files.py`
- `aios/api/integrations.py`
- `aios/api/knowledge.py`
- `aios/api/secrets.py`
- `aios/api/teams.py`
- `aios/api/versions.py`
- `aios/db/backend.py`

## Audit Trail

- EXTRACTED: 194 (48%)
- INFERRED: 206 (52%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*