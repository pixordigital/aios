# Agent DB Knowledge & Learning

> 73 nodes · cohesion 0.05

## Key Concepts

- **User** (115 connections) — `aios/db/models.py`
- **api/agent_db.py** (23 connections) — `aios/api/agent_db.py`
- **api/swarm.py** (23 connections) — `aios/api/swarm.py`
- **api/sparc.py** (19 connections) — `aios/api/sparc.py`
- **api/library.py** (12 connections) — `aios/api/library.py`
- **_hash_password()** (11 connections) — `aios/api/auth.py`
- **test_channel_types.py** (11 connections) — `tests/test_channel_types.py`
- **test_agent_types.py** (9 connections) — `tests/test_agent_types.py`
- **TestAgentQuotas** (6 connections) — `tests/test_agent_types.py`
- **.test_free_plan_max_agents()** (6 connections) — `tests/test_agent_types.py`
- **.test_free_plan_max_channels()** (6 connections) — `tests/test_channel_types.py`
- **list_approvals()** (5 connections) — `aios/api/approvals.py`
- **post** (5 connections)
- **list_threads()** (5 connections) — `aios/api/threads.py`
- **TestChannelQuotas** (5 connections) — `tests/test_channel_types.py`
- **create_knowledge()** (4 connections) — `aios/api/agent_db.py`
- **create_learning()** (4 connections) — `aios/api/agent_db.py`
- **create_reflection()** (4 connections) — `aios/api/agent_db.py`
- **approve_action()** (4 connections) — `aios/api/approvals.py`
- **reject_action()** (4 connections) — `aios/api/approvals.py`
- **advance_phase()** (4 connections) — `aios/api/sparc.py`
- **create_sparc()** (4 connections) — `aios/api/sparc.py`
- **dispatch_task()** (4 connections) — `aios/api/swarm.py`
- **put_shared_memory()** (4 connections) — `aios/api/swarm.py`
- **update_swarm_config()** (4 connections) — `aios/api/swarm.py`
- *... and 48 more nodes in this community*

## Relationships

- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (32 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (14 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (11 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (10 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (9 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (9 shared connections)
- [Skills API](Skills_API.md) (7 shared connections)
- [Rubrics API](Rubrics_API.md) (6 shared connections)
- [AsyncSession Delegation](AsyncSession_Delegation.md) (5 shared connections)
- [Metrics, Superadmin Gate & Conversations](Metrics,_Superadmin_Gate_&_Conversations.md) (5 shared connections)
- [Meta API Improvement Loop](Meta_API_Improvement_Loop.md) (5 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (4 shared connections)

## Source Files

- `aios/api/agent_db.py`
- `aios/api/approvals.py`
- `aios/api/auth.py`
- `aios/api/library.py`
- `aios/api/sparc.py`
- `aios/api/swarm.py`
- `aios/api/threads.py`
- `aios/db/models.py`
- `tests/test_agent_types.py`
- `tests/test_channel_types.py`

## Audit Trail

- EXTRACTED: 179 (66%)
- INFERRED: 94 (34%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*