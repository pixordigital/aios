# Agent Health Tracker

> 18 nodes · cohesion 0.15

## Key Concepts

- **AgentHealthTracker** (10 connections) — `aios/core/agent_health.py`
- **_escalate()** (7 connections) — `aios/core/agent_health.py`
- **._get()** (6 connections) — `aios/core/agent_health.py`
- **.record_failure()** (4 connections) — `aios/core/agent_health.py`
- **AgentHealth** (3 connections) — `aios/core/agent_health.py`
- **.get_status()** (3 connections) — `aios/core/agent_health.py`
- **.is_available()** (3 connections) — `aios/core/agent_health.py`
- **.record_success()** (3 connections) — `aios/core/agent_health.py`
- **.reset()** (3 connections) — `aios/core/agent_health.py`
- **_log()** (3 connections) — `aios/core/agent_health.py`
- **.all_status()** (2 connections) — `aios/core/agent_health.py`
- **.__init__()** (1 connections) — `aios/core/agent_health.py`
- **Manually reset agent health.** (1 connections) — `aios/core/agent_health.py`
- **Escalate agent failure to admin via audit log.** (1 connections) — `aios/core/agent_health.py`
- **Track health status of all agents.** (1 connections) — `aios/core/agent_health.py`
- **Record agent failure. Returns new status.** (1 connections) — `aios/core/agent_health.py`
- **Record agent success. Returns new status.** (1 connections) — `aios/core/agent_health.py`
- **Check if agent is available for processing.** (1 connections) — `aios/core/agent_health.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (2 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (1 shared connections)

## Source Files

- `aios/core/agent_health.py`

## Audit Trail

- EXTRACTED: 30 (97%)
- INFERRED: 1 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*