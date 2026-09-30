# Memory Manager

> 18 nodes · cohesion 0.16

## Key Concepts

- **MemoryManager** (27 connections) — `aios/core/memory.py`
- **._store_vector()** (6 connections) — `aios/core/memory.py`
- **.search_hybrid()** (5 connections) — `aios/core/memory.py`
- **.search_similar()** (5 connections) — `aios/core/memory.py`
- **.get_context_injections()** (4 connections) — `aios/core/memory.py`
- **._load_from_db()** (4 connections) — `aios/core/memory.py`
- **.search_fts()** (4 connections) — `aios/core/memory.py`
- **._summarize()** (4 connections) — `aios/core/memory.py`
- **.add()** (3 connections) — `aios/core/memory.py`
- **.get_recent()** (3 connections) — `aios/core/memory.py`
- **.clear()** (1 connections) — `aios/core/memory.py`
- **Three-tier memory with AIOS pipeline: extract → inject → format → write barrier.** (1 connections) — `aios/core/memory.py`
- **Get formatted memory injections — uses SA-CTS when autonomous.** (1 connections) — `aios/core/memory.py`
- **Tier 3: vector similarity search across stored memories.** (1 connections) — `aios/core/memory.py`
- **FTS5 full-text search for exact keyword matches.** (1 connections) — `aios/core/memory.py`
- **Hybrid search: merge FTS5 exact + vector semantic results.** (1 connections) — `aios/core/memory.py`
- **Store content + embedding in vector DB. Also indexes in FTS5.** (1 connections) — `aios/core/memory.py`
- **Tier 2: store a summary memory for dropped content.** (1 connections) — `aios/core/memory.py`

## Relationships

- [Voice API Webhook](Voice_API_Webhook.md) (6 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (4 shared connections)
- [Semantic Search & Embeddings](Semantic_Search_&_Embeddings.md) (4 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (3 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (3 shared connections)
- [Hermes Feature Tests](Hermes_Feature_Tests.md) (2 shared connections)
- [Log Formatter & Injector](Log_Formatter_&_Injector.md) (1 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (1 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)

## Source Files

- `aios/core/memory.py`

## Audit Trail

- EXTRACTED: 44 (90%)
- INFERRED: 5 (10%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*