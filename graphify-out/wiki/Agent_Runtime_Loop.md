# Agent Runtime Loop

> 90 nodes · cohesion 0.04

## Key Concepts

- **logging** (119 connections)
- **AgentRuntime** (68 connections) — `aios/core/agent.py`
- **core/agent.py** (40 connections) — `aios/core/agent.py`
- **json** (39 connections)
- **asyncio** (30 connections)
- **time** (29 connections)
- **workflow.py** (25 connections) — `aios/core/workflow.py`
- **memory.py** (24 connections) — `aios/core/memory.py`
- **core/orchestrator.py** (23 connections) — `aios/core/orchestrator.py`
- **dataclasses** (20 connections)
- **scheduler.py** (18 connections) — `aios/core/scheduler.py`
- **autonomous_agent.py** (16 connections) — `aios/core/autonomous_agent.py`
- **syscalls.py** (15 connections) — `aios/core/syscalls.py`
- **context_manager.py** (14 connections) — `aios/core/context_manager.py`
- **hooks.py** (13 connections) — `aios/core/hooks.py`
- **HookPoint** (13 connections) — `aios/core/hooks.py`
- **core/tools.py** (13 connections) — `aios/core/tools.py`
- **subagent.py** (12 connections) — `aios/core/subagent.py`
- **agent_health.py** (11 connections) — `aios/core/agent_health.py`
- **dynamic.py** (11 connections) — `aios/tools/dynamic.py`
- **approval.py** (9 connections) — `aios/core/approval.py`
- **bus.py** (9 connections) — `aios/core/bus.py`
- **cache.py** (9 connections) — `aios/core/cache.py`
- **event_bus.py** (9 connections) — `aios/core/event_bus.py`
- **meta_agent.py** (9 connections) — `aios/core/meta_agent.py`
- *... and 65 more nodes in this community*

## Relationships

- [Hook Registry](Hook_Registry.md) (21 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (21 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (21 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (18 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (15 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (12 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (11 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (11 shared connections)
- [Sandbox & Skill Loader](Sandbox_&_Skill_Loader.md) (11 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (10 shared connections)
- [Metrics, Superadmin Gate & Conversations](Metrics,_Superadmin_Gate_&_Conversations.md) (10 shared connections)
- [Structured Output & Traces](Structured_Output_&_Traces.md) (10 shared connections)

## Source Files

- `aios/core/agent.py`
- `aios/core/agent_health.py`
- `aios/core/approval.py`
- `aios/core/autonomous_agent.py`
- `aios/core/bus.py`
- `aios/core/cache.py`
- `aios/core/context_manager.py`
- `aios/core/dispatch.py`
- `aios/core/event_bus.py`
- `aios/core/hooks.py`
- `aios/core/memory.py`
- `aios/core/meta_agent.py`
- `aios/core/orchestrator.py`
- `aios/core/rubric.py`
- `aios/core/scheduler.py`
- `aios/core/subagent.py`
- `aios/core/syscalls.py`
- `aios/core/telemetry.py`
- `aios/core/tools.py`
- `aios/core/whatsapp/lgpd/retention.py`

## Audit Trail

- EXTRACTED: 541 (94%)
- INFERRED: 33 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*