# ApprovalManager +2

> 9 nodes · cohesion 0.22

## Key Concepts

- **ApprovalManager** (13 connections) — `aios/core/approval.py`
- **.cancel_expired()** (2 connections) — `aios/core/approval.py`
- **.request_approval()** (2 connections) — `aios/core/approval.py`
- **PendingAction** (2 connections) — `aios/core/approval.py`
- **.get_pending()** (1 connections) — `aios/core/approval.py`
- **.__init__()** (1 connections) — `aios/core/approval.py`
- **.reject()** (1 connections) — `aios/core/approval.py`
- **Mark stale actions as expired.** (1 connections) — `aios/core/approval.py`
- **In-memory approval queue. Blocks agent until human decides.** (1 connections) — `aios/core/approval.py`

## Relationships

- [Hermes Feature Tests](Hermes_Feature_Tests.md) (4 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [AsyncSession Delegation](AsyncSession_Delegation.md) (1 shared connections)
- [HITL Pending Actions & CRM Create](HITL_Pending_Actions_&_CRM_Create.md) (1 shared connections)

## Source Files

- `aios/core/approval.py`

## Audit Trail

- EXTRACTED: 12 (75%)
- INFERRED: 4 (25%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*