# Voice API Webhook

> 10 nodes · cohesion 0.20

## Key Concepts

- **_vec_db()** (12 connections) — `aios/core/memory.py`
- **.discard_memory()** (3 connections) — `aios/core/memory.py`
- **.get_agent_memories()** (3 connections) — `aios/core/memory.py`
- **.update_memory()** (3 connections) — `aios/core/memory.py`
- **test_fts_vector_db_has_fts_table()** (2 connections) — `tests/test_features.py`
- **RL GRPO: success increments usage/success, failure decays (Agentic Memory).** (1 connections) — `aios/core/memory.py`
- **RL discard: delete if success_rate <0.3 after 10 uses.** (1 connections) — `aios/core/memory.py`
- **Lazy-init per-agent vector store with FTS5 + RL stats.** (1 connections) — `aios/core/memory.py`
- **Load memories across all conversations for this agent (cross-conversation).** (1 connections) — `aios/core/memory.py`
- **Connection** (1 connections)

## Relationships

- [Memory Manager](Memory_Manager.md) (6 shared connections)
- [Hermes Feature Tests](Hermes_Feature_Tests.md) (2 shared connections)
- [Semantic Search & Embeddings](Semantic_Search_&_Embeddings.md) (1 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)

## Source Files

- `aios/core/memory.py`
- `tests/test_features.py`

## Audit Trail

- EXTRACTED: 19 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*