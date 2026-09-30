# CRM Agent Tools

> 28 nodes · cohesion 0.12

## Key Concepts

- **test_crm_tools.py** (25 connections) — `tests/test_crm_tools.py`
- **TestNoOrgFailsClosed** (11 connections) — `tests/test_crm_tools.py`
- **CRMTool** (10 connections) — `aios/tools/crm.py`
- **_now_utc()** (10 connections) — `aios/tools/crm.py`
- **CRMSetFollowUpTool** (8 connections) — `aios/tools/crm.py`
- **CRMListDealsTool** (7 connections) — `aios/tools/crm.py`
- **CRMStaleDealsTool** (7 connections) — `aios/tools/crm.py`
- **TestNaiveUtcAndNoFakeSuccess** (7 connections) — `tests/test_crm_tools.py`
- **asyncio** (4 connections)
- **.test_create_fails_honestly_when_db_write_fails()** (4 connections) — `tests/test_crm_tools.py`
- **.run()** (3 connections) — `aios/tools/crm.py`
- **.test_create_refuses()** (3 connections) — `tests/test_crm_tools.py`
- **.test_follow_up_refuses()** (3 connections) — `tests/test_crm_tools.py`
- **.test_list_refuses()** (3 connections) — `tests/test_crm_tools.py`
- **.test_stale_refuses()** (3 connections) — `tests/test_crm_tools.py`
- **.run()** (2 connections) — `aios/tools/crm.py`
- **.run()** (2 connections) — `aios/tools/crm.py`
- **datetime** (2 connections)
- **.test_now_utc_is_naive()** (2 connections) — `tests/test_crm_tools.py`
- **Naive UTC. crm_deals datetime columns are TIMESTAMP WITHOUT TIME ZONE (models…** (1 connections) — `aios/tools/crm.py`
- **CRM tools for agents: org isolation, plus the read/follow-up operations. The…** (1 connections) — `tests/test_crm_tools.py`
- **Live round-trip found: crm_create_deal failed on Postgres (tz-aware datetime…** (1 connections) — `tests/test_crm_tools.py`
- **A failed internal insert must surface, never fabricate an id. The live bug:…** (1 connections) — `tests/test_crm_tools.py`
- **No engine org must refuse, not fall back to the first org.** (1 connections) — `tests/test_crm_tools.py`
- **boom()** (1 connections) — `tests/test_crm_tools.py`
- *... and 3 more nodes in this community*

## Relationships

- [HITL Pending Actions & CRM Create](HITL_Pending_Actions_&_CRM_Create.md) (7 shared connections)
- [Vector Extension & CRM Versions](Vector_Extension_&_CRM_Versions.md) (6 shared connections)
- [Daily Deal Queue](Daily_Deal_Queue.md) (5 shared connections)
- [CRM Org Isolation Tests](CRM_Org_Isolation_Tests.md) (5 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (4 shared connections)
- [Metrics, Superadmin Gate & Conversations](Metrics,_Superadmin_Gate_&_Conversations.md) (3 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (1 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (1 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (1 shared connections)

## Source Files

- `aios/tools/crm.py`
- `tests/test_crm_tools.py`

## Audit Trail

- EXTRACTED: 69 (85%)
- INFERRED: 12 (15%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*