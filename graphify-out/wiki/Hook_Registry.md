# Hook Registry

> 46 nodes · cohesion 0.05

## Key Concepts

- **HookContext** (18 connections) — `aios/core/hooks.py`
- **AgentScheduler** (18 connections) — `aios/core/scheduler.py`
- **.enqueue()** (8 connections) — `aios/core/scheduler.py`
- **HookRegistry** (7 connections) — `aios/core/hooks.py`
- **AgentProcess** (7 connections) — `aios/core/scheduler.py`
- **SyscallDispatcher** (7 connections) — `aios/core/syscalls.py`
- **_fire_hook()** (6 connections) — `aios/core/context_manager.py`
- **.dispatch()** (5 connections) — `aios/core/syscalls.py`
- **.fire()** (4 connections) — `aios/core/hooks.py`
- **._persist_instance()** (4 connections) — `aios/core/scheduler.py`
- **.pop()** (4 connections) — `aios/core/scheduler.py`
- **.start()** (4 connections) — `aios/core/scheduler.py`
- **.register()** (3 connections) — `aios/core/hooks.py`
- **.unregister()** (3 connections) — `aios/core/hooks.py`
- **.preempt()** (3 connections) — `aios/core/scheduler.py`
- **.terminate()** (3 connections) — `aios/core/scheduler.py`
- **.register()** (3 connections) — `aios/core/syscalls.py`
- **.block()** (2 connections) — `aios/core/scheduler.py`
- **.get_process()** (2 connections) — `aios/core/scheduler.py`
- **.unblock()** (2 connections) — `aios/core/scheduler.py`
- **HookFn** (2 connections)
- **Fire hook with a minimal context.** (1 connections) — `aios/core/context_manager.py`
- **.add_error()** (1 connections) — `aios/core/hooks.py`
- **.clear()** (1 connections) — `aios/core/hooks.py`
- **.__init__()** (1 connections) — `aios/core/hooks.py`
- *... and 21 more nodes in this community*

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (21 shared connections)
- [Agents CRUD & Deploy](Agents_CRUD_&_Deploy.md) (3 shared connections)
- [Context Compression](Context_Compression.md) (2 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (1 shared connections)
- [WebSocket Manager](WebSocket_Manager.md) (1 shared connections)

## Source Files

- `aios/core/context_manager.py`
- `aios/core/hooks.py`
- `aios/core/scheduler.py`
- `aios/core/syscalls.py`

## Audit Trail

- EXTRACTED: 75 (89%)
- INFERRED: 9 (11%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*