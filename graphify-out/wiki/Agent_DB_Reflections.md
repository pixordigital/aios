# Agent DB Reflections

> 18 nodes · cohesion 0.17

## Key Concepts

- **AgentDB** (16 connections) — `aios/core/agent_db.py`
- **core/agent_db.py** (14 connections) — `aios/core/agent_db.py`
- **AgentKnowledge** (11 connections) — `aios/db/models.py`
- **AgentReflection** (11 connections) — `aios/db/models.py`
- **.list_reflections()** (4 connections) — `aios/core/agent_db.py`
- **.put_knowledge()** (4 connections) — `aios/core/agent_db.py`
- **.record_learning()** (4 connections) — `aios/core/agent_db.py`
- **.similar_knowledge()** (4 connections) — `aios/core/agent_db.py`
- **.bump_knowledge_usage()** (3 connections) — `aios/core/agent_db.py`
- **.create_reflection()** (3 connections) — `aios/core/agent_db.py`
- **.get_knowledge()** (3 connections) — `aios/core/agent_db.py`
- **_pattern_sig()** (2 connections) — `aios/core/agent_db.py`
- **datetime** (2 connections)
- **AgentDB — persistent cross-session knowledge + learning + reflection store.…** (1 connections) — `aios/core/agent_db.py`
- **CRUD + vector search for agent knowledge, learnings, reflections.** (1 connections) — `aios/core/agent_db.py`
- **Keyword-based similarity (upgrade to vector cosine when embeddings present).** (1 connections) — `aios/core/agent_db.py`
- **Persistent agent knowledge base — survives restarts, shared across sessions.…** (1 connections) — `aios/db/models.py`
- **Agent self-reflection entries — post-task analysis for continuous improvement.…** (1 connections) — `aios/db/models.py`

## Relationships

- [Unified Search Library](Unified_Search_Library.md) (9 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (7 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (7 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (5 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (2 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (1 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (1 shared connections)
- [Skill Store](Skill_Store.md) (1 shared connections)

## Source Files

- `aios/core/agent_db.py`
- `aios/db/models.py`

## Audit Trail

- EXTRACTED: 54 (90%)
- INFERRED: 6 (10%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*