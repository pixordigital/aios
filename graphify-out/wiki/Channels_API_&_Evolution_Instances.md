# Channels API & Evolution Instances

> 42 nodes · cohesion 0.09

## Key Concepts

- **ChannelConnection** (83 connections) — `aios/db/models.py`
- **log_audit()** (40 connections) — `aios/core/audit.py`
- **channels.py** (39 connections) — `aios/api/channels.py`
- **inbox.py** (32 connections) — `aios/api/inbox.py`
- **list_inbox_conversations()** (9 connections) — `aios/api/inbox.py`
- **create_channel()** (8 connections) — `aios/api/channels.py`
- **evolution_analytics()** (7 connections) — `aios/api/channels.py`
- **post** (7 connections)
- **assign_conversation()** (7 connections) — `aios/api/inbox.py`
- **create_evolution_instance()** (6 connections) — `aios/api/channels.py`
- **delete_evolution_instance()** (6 connections) — `aios/api/channels.py`
- **close_conversation()** (6 connections) — `aios/api/inbox.py`
- **reopen_conversation()** (6 connections) — `aios/api/inbox.py`
- **unassign_conversation()** (6 connections) — `aios/api/inbox.py`
- **delete_channel()** (5 connections) — `aios/api/channels.py`
- **list_channels()** (5 connections) — `aios/api/channels.py`
- **test_channel()** (5 connections) — `aios/api/channels.py`
- **update_channel()** (5 connections) — `aios/api/channels.py`
- **post** (5 connections)
- **delete_team()** (5 connections) — `aios/api/teams.py`
- **get_evolution_qrcode()** (4 connections) — `aios/api/channels.py`
- **list_evolution_instances()** (4 connections) — `aios/api/channels.py`
- **start_channel()** (4 connections) — `aios/api/channels.py`
- **stop_channel()** (4 connections) — `aios/api/channels.py`
- **toggle_channel()** (4 connections) — `aios/api/channels.py`
- *... and 17 more nodes in this community*

## Relationships

- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (32 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (24 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (17 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (15 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (11 shared connections)
- [Agents CRUD & Deploy](Agents_CRUD_&_Deploy.md) (10 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (7 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (6 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (4 shared connections)
- [Voice API & Call Placement](Voice_API_&_Call_Placement.md) (4 shared connections)
- [Discord Webhook](Discord_Webhook.md) (4 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)

## Source Files

- `aios/api/channels.py`
- `aios/api/inbox.py`
- `aios/api/teams.py`
- `aios/core/audit.py`
- `aios/db/models.py`

## Audit Trail

- EXTRACTED: 164 (64%)
- INFERRED: 93 (36%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*