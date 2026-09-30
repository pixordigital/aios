# SSE Streaming Endpoint

> 39 nodes · cohesion 0.09

## Key Concepts

- **TeamOrchestrator** (40 connections) — `aios/core/orchestrator.py`
- **send_message_stream()** (16 connections) — `aios/api/conversations.py`
- **.org_id()** (13 connections) — `aios/channels/evolution.py`
- **.handle_message()** (11 connections) — `aios/core/orchestrator.py`
- **._supervisor_route()** (11 connections) — `aios/core/orchestrator.py`
- **_get_runtime()** (10 connections) — `aios/core/orchestrator.py`
- **6. Arquiteto — OS como um todo (10min)** (9 connections) — `REUNIAO_TECNICA_AGENTES_AUTONOMOS_2026_09_12.md`
- **.handle_message_stream()** (8 connections) — `aios/core/orchestrator.py`
- **._hierarchical_route()** (7 connections) — `aios/core/orchestrator.py`
- **._llm_route()** (7 connections) — `aios/core/orchestrator.py`
- **._supervisor_route_stream()** (7 connections) — `aios/core/orchestrator.py`
- **2. Teste ao vivo — WhatsApp objeção (Voz Eng, 10min)** (7 connections) — `REUNIAO_TECNICA_AGENTES_AUTONOMOS_2026_09_12.md`
- **.__init__()** (6 connections) — `aios/core/agent.py`
- **._hierarchical_route_stream()** (6 connections) — `aios/core/orchestrator.py`
- **._round_robin()** (6 connections) — `aios/core/orchestrator.py`
- **._semantic_route()** (6 connections) — `aios/core/orchestrator.py`
- **._semantic_route_stream()** (6 connections) — `aios/core/orchestrator.py`
- **`manager` — Gerente Handoff + SLA (SWE Lead)** (6 connections) — `REUNIAO_TECNICA_100_AUTONOMO_VALIDACAO_2026_09_13.md`
- **`orchestrator` — Roteamento (SWE Lead + Arquiteto)** (6 connections) — `REUNIAO_TECNICA_100_AUTONOMO_VALIDACAO_2026_09_13.md`
- **event_stream()** (5 connections) — `aios/api/conversations.py`
- **._broadcast()** (5 connections) — `aios/core/orchestrator.py`
- **._round_robin_stream()** (5 connections) — `aios/core/orchestrator.py`
- **._broadcast_stream()** (4 connections) — `aios/core/orchestrator.py`
- **._shared_context_for()** (4 connections) — `aios/core/orchestrator.py`
- **_maybe_reflect()** (3 connections) — `aios/core/orchestrator.py`
- *... and 14 more nodes in this community*

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (15 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (14 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (13 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (5 shared connections)
- [Autonomous Agent Loop](Autonomous_Agent_Loop.md) (5 shared connections)
- [Semantic Search & Embeddings](Semantic_Search_&_Embeddings.md) (4 shared connections)
- [File Read & Evaluator](File_Read_&_Evaluator.md) (4 shared connections)
- [CRM2 Routes](CRM2_Routes.md) (3 shared connections)
- [Memory Manager](Memory_Manager.md) (3 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (3 shared connections)
- [Skill Store](Skill_Store.md) (3 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)

## Source Files

- `REUNIAO_TECNICA_100_AUTONOMO_VALIDACAO_2026_09_13.md`
- `REUNIAO_TECNICA_AGENTES_AUTONOMOS_2026_09_12.md`
- `aios/api/conversations.py`
- `aios/api/deps.py`
- `aios/channels/evolution.py`
- `aios/core/agent.py`
- `aios/core/orchestrator.py`

## Audit Trail

- EXTRACTED: 104 (64%)
- INFERRED: 58 (36%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*