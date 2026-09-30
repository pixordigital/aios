# Inbox & Org Lifecycle API

> 84 nodes · cohesion 0.04

## Key Concepts

- **Agent** (153 connections) — `aios/db/models.py`
- **Team** (80 connections) — `aios/db/models.py`
- **Conversation** (60 connections) — `aios/db/models.py`
- **Message** (50 connections) — `aios/db/models.py`
- **ws.py** (21 connections) — `aios/api/ws.py`
- **AgentVersion** (21 connections) — `aios/db/models.py`
- **_process_inbound_once()** (17 connections) — `aios/tasks/jobs.py`
- **seed_internal_teams.py** (16 connections) — `scripts/seed_internal_teams.py`
- **biweekly_1on1_job()** (13 connections) — `aios/tasks/jobs.py`
- **weekly_standup_job()** (13 connections) — `aios/tasks/jobs.py`
- **meetings.py** (12 connections) — `aios/core/meetings.py`
- **dashboard_home()** (12 connections) — `aios/dashboard/app.py`
- **_resolve_org_id()** (11 connections) — `aios/dashboard/app.py`
- **test_reply_meta.py** (11 connections) — `tests/test_reply_meta.py`
- **websocket_chat()** (10 connections) — `aios/api/ws.py`
- **voice_create()** (10 connections) — `aios/dashboard/app.py`
- **apply_template()** (10 connections) — `aios/templates/__init__.py`
- **delete_org()** (9 connections) — `aios/api/gdpr.py`
- **create_team()** (9 connections) — `aios/api/teams.py`
- **team_week_stats()** (9 connections) — `aios/core/meetings.py`
- **team_save()** (9 connections) — `aios/dashboard/app.py`
- **test_evolution_analytics_isolation_by_org()** (9 connections) — `tests/test_evolution_analytics.py`
- **get_inbox_conversation()** (8 connections) — `aios/api/inbox.py`
- **send_inbox_message()** (8 connections) — `aios/api/inbox.py`
- **agent_save()** (8 connections) — `aios/dashboard/app.py`
- *... and 59 more nodes in this community*

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (96 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (32 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (27 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (26 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (25 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (23 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (22 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (22 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (21 shared connections)
- [Agents CRUD & Deploy](Agents_CRUD_&_Deploy.md) (18 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (17 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (13 shared connections)

## Source Files

- `ANALISE_ARQUITETURA_AUTONOMO_2026_09_13.md`
- `ANALISE_DETALHADA_ARQUITETURA_OPERACIONAL_TIMES_2026_09_13.md`
- `REUNIAO_6_TIMES_COMPETITIVIDADE_2026_09_11.md`
- `REUNIAO_7_TIMES_VALIDACAO_2026_09_12.md`
- `REUNIAO_TECNICA_AGENTES_AUTONOMOS_2026_09_12.md`
- `REUNIAO_TECNICA_VALIDACAO_FINAL_2026_09_13.md`
- `aios/api/analytics.py`
- `aios/api/conversations.py`
- `aios/api/gdpr.py`
- `aios/api/inbox.py`
- `aios/api/teams.py`
- `aios/api/versions.py`
- `aios/api/ws.py`
- `aios/core/meetings.py`
- `aios/dashboard/app.py`
- `aios/db/models.py`
- `aios/tasks/jobs.py`
- `aios/templates/__init__.py`
- `docs/ENTERPRISE_LEGAL_TEMPLATES.md`
- `docs/REQUISITO_AGENTES_100_AUTONOMOS_HITL.md`

## Audit Trail

- EXTRACTED: 305 (49%)
- INFERRED: 315 (51%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*