# Cron Scheduler

> 10 nodes · cohesion 0.24

## Key Concepts

- **EventBus** (8 connections) — `aios/core/event_bus.py`
- **.publish()** (3 connections) — `aios/core/event_bus.py`
- **InboundEvent** (3 connections) — `aios/core/event_bus.py`
- **.start()** (2 connections) — `aios/core/event_bus.py`
- **.subscribe()** (2 connections) — `aios/core/event_bus.py`
- **._worker()** (2 connections) — `aios/core/event_bus.py`
- **.__init__()** (1 connections) — `aios/core/event_bus.py`
- **.stop()** (1 connections) — `aios/core/event_bus.py`
- **Async event bus with publish/subscribe and worker pool.** (1 connections) — `aios/core/event_bus.py`
- **Queue event for processing. Returns False if queue full.** (1 connections) — `aios/core/event_bus.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)

## Source Files

- `aios/core/event_bus.py`

## Audit Trail

- EXTRACTED: 13 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*