# LLM Response Cache

> 15 nodes · cohesion 0.16

## Key Concepts

- **ResponseCache** (8 connections) — `aios/core/cache.py`
- **ToolResultCache** (7 connections) — `aios/core/cache.py`
- **._key()** (5 connections) — `aios/core/cache.py`
- **.get()** (2 connections) — `aios/core/cache.py`
- **.set()** (2 connections) — `aios/core/cache.py`
- **.get()** (2 connections) — `aios/core/cache.py`
- **.set()** (2 connections) — `aios/core/cache.py`
- **LRU cache with TTL for LLM responses.** (1 connections) — `aios/core/cache.py`
- **Time-based cache for tool execution results. Keyed by (tool_name, arg_hash).…** (1 connections) — `aios/core/cache.py`
- **.clear()** (1 connections) — `aios/core/cache.py`
- **.__init__()** (1 connections) — `aios/core/cache.py`
- **._key()** (1 connections) — `aios/core/cache.py`
- **.stats()** (1 connections) — `aios/core/cache.py`
- **.clear()** (1 connections) — `aios/core/cache.py`
- **.__init__()** (1 connections) — `aios/core/cache.py`

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)

## Source Files

- `aios/core/cache.py`

## Audit Trail

- EXTRACTED: 19 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*