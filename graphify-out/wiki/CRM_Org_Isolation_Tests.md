# CRM Org Isolation Tests

> 12 nodes · cohesion 0.38

## Key Concepts

- **_deal()** (9 connections) — `tests/test_crm_tools.py`
- **_org()** (9 connections) — `tests/test_crm_tools.py`
- **_tool()** (9 connections) — `tests/test_crm_tools.py`
- **TestReadTools** (7 connections) — `tests/test_crm_tools.py`
- **.test_update_foreign_deal_refused()** (6 connections) — `tests/test_crm_tools.py`
- **.test_set_follow_up_persists_and_versions()** (6 connections) — `tests/test_crm_tools.py`
- **TestOrgIsolation** (4 connections) — `tests/test_crm_tools.py`
- **.test_list_only_sees_own_org()** (4 connections) — `tests/test_crm_tools.py`
- **.test_list_excludes_closed()** (4 connections) — `tests/test_crm_tools.py`
- **.test_stale_flags_never_contacted()** (4 connections) — `tests/test_crm_tools.py`
- **.test_stale_flags_overdue_follow_up()** (4 connections) — `tests/test_crm_tools.py`
- **Load a tool the way the runtime does: engine sets _org_id per call.** (1 connections) — `tests/test_crm_tools.py`

## Relationships

- [CRM Agent Tools](CRM_Agent_Tools.md) (5 shared connections)
- [Daily Deal Queue](Daily_Deal_Queue.md) (3 shared connections)
- [Metrics, Superadmin Gate & Conversations](Metrics,_Superadmin_Gate_&_Conversations.md) (3 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (2 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (1 shared connections)
- [Vector Extension & CRM Versions](Vector_Extension_&_CRM_Versions.md) (1 shared connections)

## Source Files

- `tests/test_crm_tools.py`

## Audit Trail

- EXTRACTED: 37 (88%)
- INFERRED: 5 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*