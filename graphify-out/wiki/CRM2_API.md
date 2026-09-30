# CRM2 API

> 27 nodes · cohesion 0.12

## Key Concepts

- **crm2.py** (37 connections) — `aios/api/crm2.py`
- **deal_desk.py** (11 connections) — `aios/governance/deal_desk.py`
- **audit_deal_change()** (10 connections) — `aios/governance/deal_desk.py`
- **capture_deal_insight()** (9 connections) — `aios/core/insights.py`
- **update_deal()** (8 connections) — `aios/api/crm2.py`
- **create_deal()** (7 connections) — `aios/api/crm2.py`
- **_crm_enabled()** (7 connections) — `aios/api/crm2.py`
- **list_deals()** (7 connections) — `aios/api/crm2.py`
- **goal_current()** (6 connections) — `aios/api/crm2.py`
- **set_goal()** (6 connections) — `aios/api/crm2.py`
- **stats()** (6 connections) — `aios/api/crm2.py`
- **check_human_deviation()** (6 connections) — `aios/governance/deal_desk.py`
- **admin_all()** (4 connections) — `aios/api/crm2.py`
- **delete_deal()** (4 connections) — `aios/api/crm2.py`
- **enable_crm()** (4 connections) — `aios/api/crm2.py`
- **get_deal()** (3 connections) — `aios/api/crm2.py`
- **post** (3 connections)
- **_expiry_days_for_org()** (3 connections) — `aios/governance/deal_desk.py`
- **_exposure()** (2 connections) — `aios/governance/deal_desk.py`
- **_max_discount_for_plan()** (2 connections) — `aios/governance/deal_desk.py`
- **delete** (1 connections)
- **Set monthly sales goal: {year_month: YYYY-MM, target_brl, team_id?}.** (1 connections) — `aios/api/crm2.py`
- **Goal progress + pace for a month (default current).** (1 connections) — `aios/api/crm2.py`
- **Salva insight + score QA como Memory long_term.** (1 connections) — `aios/core/insights.py`
- **Deal Desk Governado — wedge B2B. HITL + LGPD + ledger + performance. Reuso:…** (1 connections) — `aios/governance/deal_desk.py`
- *... and 2 more nodes in this community*

## Relationships

- [Daily Deal Queue](Daily_Deal_Queue.md) (11 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (11 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (10 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (8 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (4 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (4 shared connections)
- [sales_goals.py +2](sales_goals.py_+2.md) (3 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (3 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (3 shared connections)
- [insights.py +2](insights.py_+2.md) (3 shared connections)
- [HITL Pending Actions & CRM Create](HITL_Pending_Actions_&_CRM_Create.md) (3 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (2 shared connections)

## Source Files

- `aios/api/crm2.py`
- `aios/core/insights.py`
- `aios/governance/deal_desk.py`

## Audit Trail

- EXTRACTED: 82 (74%)
- INFERRED: 29 (26%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*