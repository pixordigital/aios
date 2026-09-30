# Context Compression

> 39 nodes · cohesion 0.07

## Key Concepts

- **ContextManager** (13 connections) — `aios/core/context_manager.py`
- **count_tokens()** (9 connections) — `aios/core/tokenizer.py`
- **tokenizer.py** (8 connections) — `aios/core/tokenizer.py`
- **.save()** (7 connections) — `aios/core/context_manager.py`
- **compression.py** (5 connections) — `aios/core/compression.py`
- **ContextCompressor** (5 connections) — `aios/core/compression.py`
- **.load()** (5 connections) — `aios/core/context_manager.py`
- **.restore_after_switch()** (5 connections) — `aios/core/context_manager.py`
- **SavedContext** (5 connections) — `aios/core/context_manager.py`
- **.compress_and_fit()** (4 connections) — `aios/core/compression.py`
- **.cache_key()** (4 connections) — `aios/core/context_manager.py`
- **.compress_and_fit()** (4 connections) — `aios/core/context_manager.py`
- **.enforce_budget()** (4 connections) — `aios/core/context_manager.py`
- **.save_for_switch()** (4 connections) — `aios/core/context_manager.py`
- **count_message_tokens()** (4 connections) — `aios/core/tokenizer.py`
- **._summarize_messages()** (3 connections) — `aios/core/compression.py`
- **truncate_context()** (3 connections) — `aios/core/tokenizer.py`
- **.drop()** (2 connections) — `aios/core/context_manager.py`
- **._evict_if_needed()** (2 connections) — `aios/core/context_manager.py`
- **_load_tiktoken()** (2 connections) — `aios/core/tokenizer.py`
- **.__init__()** (1 connections) — `aios/core/compression.py`
- **Context compression — summarize oldest messages instead of dropping them. When…** (1 connections) — `aios/core/compression.py`
- **Summarize oldest messages to fit within token budget.** (1 connections) — `aios/core/compression.py`
- **Compress oldest messages to fit token budget. Keeps system prompt + recent…** (1 connections) — `aios/core/compression.py`
- **Use LLM to summarize a block of messages.** (1 connections) — `aios/core/compression.py`
- *... and 14 more nodes in this community*

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (6 shared connections)
- [Hook Registry](Hook_Registry.md) (2 shared connections)
- [Autonomous Agent Loop](Autonomous_Agent_Loop.md) (1 shared connections)

## Source Files

- `aios/core/compression.py`
- `aios/core/context_manager.py`
- `aios/core/tokenizer.py`

## Audit Trail

- EXTRACTED: 62 (98%)
- INFERRED: 1 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*