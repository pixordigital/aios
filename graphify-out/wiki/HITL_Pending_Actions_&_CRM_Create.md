# HITL Pending Actions & CRM Create

> 12 nodes · cohesion 0.27

## Key Concepts

- **crm.py** (24 connections) — `aios/tools/crm.py`
- **PendingAction** (23 connections) — `aios/db/models.py`
- **CRMUpdateTool** (6 connections) — `aios/tools/crm.py`
- **BaseModel** (6 connections)
- **.run()** (4 connections) — `aios/tools/crm.py`
- **CRMCreateDealInput** (2 connections) — `aios/tools/crm.py`
- **CRMListDealsInput** (2 connections) — `aios/tools/crm.py`
- **CRMMergeDealsInput** (2 connections) — `aios/tools/crm.py`
- **CRMSetFollowUpInput** (2 connections) — `aios/tools/crm.py`
- **CRMStaleDealsInput** (2 connections) — `aios/tools/crm.py`
- **CRMUpdateDealInput** (2 connections) — `aios/tools/crm.py`
- **Human-in-the-loop approval queue for agent tool calls.** (1 connections) — `aios/db/models.py`

## Relationships

- [CRM Agent Tools](CRM_Agent_Tools.md) (7 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (5 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (5 shared connections)
- [Vector Extension & CRM Versions](Vector_Extension_&_CRM_Versions.md) (4 shared connections)
- [CRM2 API](CRM2_API.md) (3 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (3 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (2 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Cron Ticks (Backup, CRM, Pending)](Cron_Ticks_Backup,_CRM,_Pending.md) (2 shared connections)
- [Daily Deal Queue](Daily_Deal_Queue.md) (2 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (1 shared connections)

## Source Files

- `aios/db/models.py`
- `aios/tools/crm.py`

## Audit Trail

- EXTRACTED: 47 (81%)
- INFERRED: 11 (19%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*