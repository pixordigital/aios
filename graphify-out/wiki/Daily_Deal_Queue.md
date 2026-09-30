# Daily Deal Queue

> 12 nodes · cohesion 0.30

## Key Concepts

- **CrmDeal** (51 connections) — `aios/db/models.py`
- **queue()** (9 connections) — `aios/api/crm2.py`
- **rank_queue()** (9 connections) — `aios/core/signals.py`
- **timing_score()** (6 connections) — `aios/core/signals.py`
- **TestSignals** (5 connections) — `tests/test_lojista_signals.py`
- **core/signals.py** (4 connections) — `aios/core/signals.py`
- **datetime** (3 connections)
- **.test_cold_stale_scores_low()** (3 connections) — `tests/test_lojista_signals.py`
- **.test_hot_inbound_scores_high()** (3 connections) — `tests/test_lojista_signals.py`
- **.test_rank_skips_closed()** (3 connections) — `tests/test_lojista_signals.py`
- **Fila do dia — deals abertos ordenados por timing (origem+recência+tentativas).** (1 connections) — `aios/api/crm2.py`
- **Sinais-lite — score de timing 0-100 com dado interno (sem provedor externo).…** (1 connections) — `aios/core/signals.py`

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (13 shared connections)
- [CRM2 API](CRM2_API.md) (11 shared connections)
- [Lojista Signal Tests](Lojista_Signal_Tests.md) (6 shared connections)
- [CRM Agent Tools](CRM_Agent_Tools.md) (5 shared connections)
- [Vector Extension & CRM Versions](Vector_Extension_&_CRM_Versions.md) (4 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (4 shared connections)
- [CRM Org Isolation Tests](CRM_Org_Isolation_Tests.md) (3 shared connections)
- [Cron Ticks (Backup, CRM, Pending)](Cron_Ticks_Backup,_CRM,_Pending.md) (2 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (2 shared connections)
- [sales_goals.py +2](sales_goals.py_+2.md) (2 shared connections)
- [HITL Pending Actions & CRM Create](HITL_Pending_Actions_&_CRM_Create.md) (2 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)

## Source Files

- `aios/api/crm2.py`
- `aios/core/signals.py`
- `aios/db/models.py`
- `tests/test_lojista_signals.py`

## Audit Trail

- EXTRACTED: 41 (53%)
- INFERRED: 37 (47%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*