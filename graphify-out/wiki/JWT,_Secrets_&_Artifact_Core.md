# JWT, Secrets & Artifact Core

> 163 nodes · cohesion 0.05

## Key Concepts

- **app.py** (252 connections) — `aios/dashboard/app.py`
- **db_session()** (232 connections) — `aios/db/backend.py`
- **Request** (133 connections)
- **_org_filter()** (92 connections) — `aios/dashboard/app.py`
- **_render()** (58 connections) — `aios/dashboard/app.py`
- **post** (50 connections)
- **AutomationTrigger** (25 connections) — `aios/db/models.py`
- **_require_superadmin()** (18 connections) — `aios/dashboard/app.py`
- **RemoteInstance** (13 connections) — `aios/db/models.py`
- **control_center()** (12 connections) — `aios/dashboard/app.py`
- **crm_page()** (12 connections) — `aios/dashboard/app.py`
- **lojista_create()** (12 connections) — `aios/dashboard/app.py`
- **admin_org_detail()** (11 connections) — `aios/dashboard/app.py`
- **automation_detail()** (11 connections) — `aios/dashboard/app.py`
- **crm_deal_detail()** (11 connections) — `aios/dashboard/app.py`
- **lab_agent_publish()** (11 connections) — `aios/dashboard/app.py`
- **login_action()** (11 connections) — `aios/dashboard/app.py`
- **register_action()** (11 connections) — `aios/dashboard/app.py`
- **whatsapp_risk_page()** (11 connections) — `aios/dashboard/app.py`
- **wizard_create()** (11 connections) — `aios/dashboard/app.py`
- **encrypt_channel_config()** (10 connections) — `aios/core/secrets.py`
- **read_artifact_text()** (10 connections) — `aios/core/storage.py`
- **automations_list()** (10 connections) — `aios/dashboard/app.py`
- **autoscale_page()** (10 connections) — `aios/dashboard/app.py`
- **agent_versions_page()** (9 connections) — `aios/dashboard/app.py`
- *... and 138 more nodes in this community*

## Relationships

- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (96 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (68 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (45 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (37 shared connections)
- [Admin Fleet & DLQ](Admin_Fleet_&_DLQ.md) (25 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (24 shared connections)
- [Evolution Key Rotation & IP Allowlist](Evolution_Key_Rotation_&_IP_Allowlist.md) (19 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (16 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (15 shared connections)
- [Daily Deal Queue](Daily_Deal_Queue.md) (13 shared connections)
- [Artifact Content & Storage](Artifact_Content_&_Storage.md) (11 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (11 shared connections)

## Source Files

- `aios/api/deps.py`
- `aios/core/secrets.py`
- `aios/core/storage.py`
- `aios/core/tracing.py`
- `aios/dashboard/app.py`
- `aios/db/backend.py`
- `aios/db/models.py`

## Audit Trail

- EXTRACTED: 914 (79%)
- INFERRED: 239 (21%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*