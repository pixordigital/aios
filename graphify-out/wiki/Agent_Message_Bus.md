# Agent Message Bus

> 14 nodes · cohesion 0.20

## Key Concepts

- **MessageBus** (8 connections) — `aios/core/bus.py`
- **.request()** (6 connections) — `aios/core/bus.py`
- **AgentMessage** (5 connections) — `aios/core/bus.py`
- **.publish()** (4 connections) — `aios/core/bus.py`
- **.subscribe()** (3 connections) — `aios/core/bus.py`
- **.unsubscribe()** (3 connections) — `aios/core/bus.py`
- **.recent()** (2 connections) — `aios/core/bus.py`
- **Queue** (2 connections)
- **.__init__()** (1 connections) — `aios/core/bus.py`
- **A typed message between agents.** (1 connections) — `aios/core/bus.py`
- **In-process pub/sub bus for agent messages. ponytail: single process bus. Swap…** (1 connections) — `aios/core/bus.py`
- **Return a queue that receives messages of this type.** (1 connections) — `aios/core/bus.py`
- **Publish message to all subscribers of its type. Returns delivery count.** (1 connections) — `aios/core/bus.py`
- **Publish and collect responses from subscribers. Yields responses until timeout.…** (1 connections) — `aios/core/bus.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (1 shared connections)

## Source Files

- `aios/core/bus.py`

## Audit Trail

- EXTRACTED: 20 (95%)
- INFERRED: 1 (5%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*