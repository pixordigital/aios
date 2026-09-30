# Queue (Subagent Spawn)

> 14 nodes · cohesion 0.18

## Key Concepts

- **_subagent_worker()** (7 connections) — `aios/core/subagent.py`
- **SubAgentPool** (7 connections) — `aios/core/subagent.py`
- **.spawn()** (5 connections) — `aios/core/subagent.py`
- **.spawn_many()** (4 connections) — `aios/core/subagent.py`
- **SubagentResult** (4 connections) — `aios/core/subagent.py`
- **.get_result()** (2 connections) — `aios/core/subagent.py`
- **Queue** (1 connections)
- **Spawn multiple subagents concurrently. tasks: [{"agent_config": {...},…** (1 connections) — `aios/core/subagent.py`
- **Run in subprocess — loads agent, executes task, puts JSON result.** (1 connections) — `aios/core/subagent.py`
- **Manage subprocess-based subagents.** (1 connections) — `aios/core/subagent.py`
- **Spawn a single subagent. Blocks until done or timeout.** (1 connections) — `aios/core/subagent.py`
- **_run()** (1 connections) — `aios/core/subagent.py`
- **.active_count()** (1 connections) — `aios/core/subagent.py`
- **.__init__()** (1 connections) — `aios/core/subagent.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (4 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (1 shared connections)

## Source Files

- `aios/core/subagent.py`

## Audit Trail

- EXTRACTED: 20 (95%)
- INFERRED: 1 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*