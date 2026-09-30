# Agents CRUD & Deploy

> 35 nodes · cohesion 0.09

## Key Concepts

- **agents.py** (42 connections) — `aios/api/agents.py`
- **AgentInstance** (16 connections) — `aios/db/models.py`
- **post** (10 connections)
- **create_agent()** (9 connections) — `aios/api/agents.py`
- **deploy_agent()** (9 connections) — `aios/api/agents.py`
- **promote_canary()** (7 connections) — `aios/api/agents.py`
- **push_agent_to_fleet()** (7 connections) — `aios/api/agents.py`
- **rollback_canary()** (7 connections) — `aios/api/agents.py`
- **stop_agent()** (7 connections) — `aios/api/agents.py`
- **enqueue_task()** (7 connections) — `aios/tasks/queue.py`
- **import_agent()** (6 connections) — `aios/api/agents.py`
- **AgentCreate** (6 connections) — `aios/schemas/__init__.py`
- **AgentUpdate** (6 connections) — `aios/schemas/__init__.py`
- **delete_agent()** (5 connections) — `aios/api/agents.py`
- **reload_agent_skills()** (5 connections) — `aios/api/agents.py`
- **reset_agent_health()** (5 connections) — `aios/api/agents.py`
- **spawn_subagent()** (5 connections) — `aios/api/agents.py`
- **update_agent()** (5 connections) — `aios/api/agents.py`
- **export_agent()** (4 connections) — `aios/api/agents.py`
- **get_agent_skills()** (4 connections) — `aios/api/agents.py`
- **field_validator** (4 connections)
- **get_agent()** (3 connections) — `aios/api/agents.py`
- **._validate_llm()** (2 connections) — `aios/schemas/__init__.py`
- **._validate_tools()** (2 connections) — `aios/schemas/__init__.py`
- **._validate_llm()** (2 connections) — `aios/schemas/__init__.py`
- *... and 10 more nodes in this community*

## Relationships

- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (18 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (17 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (10 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (8 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (8 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (5 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (4 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (3 shared connections)
- [Hook Registry](Hook_Registry.md) (3 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (3 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)

## Source Files

- `aios/api/agents.py`
- `aios/db/models.py`
- `aios/schemas/__init__.py`
- `aios/tasks/queue.py`

## Audit Trail

- EXTRACTED: 98 (69%)
- INFERRED: 45 (31%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*