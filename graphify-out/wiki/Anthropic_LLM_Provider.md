# Anthropic LLM Provider

> 37 nodes · cohesion 0.09

## Key Concepts

- **providers.py** (25 connections) — `aios/core/providers.py`
- **LLMProvider** (12 connections) — `aios/core/providers.py`
- **AnthropicProvider** (8 connections) — `aios/core/providers.py`
- **LLMError** (8 connections) — `aios/core/providers.py`
- **_retry()** (8 connections) — `aios/core/providers.py`
- **.chat_stream_retry()** (7 connections) — `aios/core/providers.py`
- **OllamaProvider** (6 connections) — `aios/core/providers.py`
- **OpenAIProvider** (6 connections) — `aios/core/providers.py`
- **OpenRouterProvider** (6 connections) — `aios/core/providers.py`
- **.chat()** (4 connections) — `aios/core/providers.py`
- **_circuit_allowed()** (4 connections) — `aios/core/providers.py`
- **_circuit_record_failure()** (4 connections) — `aios/core/providers.py`
- **_circuit_record_success()** (4 connections) — `aios/core/providers.py`
- **_circuit_state()** (4 connections) — `aios/core/providers.py`
- **.chat()** (4 connections) — `aios/core/providers.py`
- **.chat_stream()** (3 connections) — `aios/core/providers.py`
- **._to_anthropic_msgs()** (3 connections) — `aios/core/providers.py`
- **._to_openai_tools()** (3 connections) — `aios/core/providers.py`
- **_circuit_key()** (3 connections) — `aios/core/providers.py`
- **_fallback_models()** (2 connections) — `aios/core/providers.py`
- **.chat_stream()** (2 connections) — `aios/core/providers.py`
- **.chat_stream()** (2 connections) — `aios/core/providers.py`
- **.chat()** (2 connections) — `aios/core/providers.py`
- **.chat()** (2 connections) — `aios/core/providers.py`
- **ABC** (2 connections)
- *... and 12 more nodes in this community*

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (8 shared connections)
- [CRM2 Routes](CRM2_Routes.md) (6 shared connections)
- [LLM Retry & Inbound Processing](LLM_Retry_&_Inbound_Processing.md) (3 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [Alembic Migrations](Alembic_Migrations.md) (1 shared connections)

## Source Files

- `aios/core/providers.py`

## Audit Trail

- EXTRACTED: 83 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*