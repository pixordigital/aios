# Log Formatter & Injector

> 11 nodes · cohesion 0.18

## Key Concepts

- **.__init__()** (5 connections) — `aios/core/memory.py`
- **WriteBarrier** (5 connections) — `aios/core/memory.py`
- **Formatter** (4 connections) — `aios/core/memory.py`
- **Injector** (4 connections) — `aios/core/memory.py`
- **.allow()** (2 connections) — `aios/core/memory.py`
- **.format()** (1 connections) — `aios/core/memory.py`
- **Decide what memories to inject into agent context.** (1 connections) — `aios/core/memory.py`
- **Render selected memories as system prompt additions.** (1 connections) — `aios/core/memory.py`
- **Rate-limit and batch memory writes to avoid thrashing. ponytail: simple time-…** (1 connections) — `aios/core/memory.py`
- **Check if write is allowed (not rate-limited).** (1 connections) — `aios/core/memory.py`
- **.__init__()** (1 connections) — `aios/core/memory.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)
- [Extractor +2](Extractor_+2.md) (1 shared connections)
- [Memory Manager](Memory_Manager.md) (1 shared connections)

## Source Files

- `aios/core/memory.py`

## Audit Trail

- EXTRACTED: 16 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*