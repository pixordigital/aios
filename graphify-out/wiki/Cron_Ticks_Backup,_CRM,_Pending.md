# Cron Ticks (Backup, CRM, Pending)

> 17 nodes · cohesion 0.18

## Key Concepts

- **cron_scheduler.py** (27 connections) — `aios/core/cron_scheduler.py`
- **_crm_mql_stale_tick()** (9 connections) — `aios/core/cron_scheduler.py`
- **_proactive_alerts_tick()** (8 connections) — `aios/core/cron_scheduler.py`
- **check_sales_drop()** (8 connections) — `aios/tools/proactive_alerts.py`
- **send_alert_via_evolution()** (8 connections) — `aios/tools/proactive_alerts.py`
- **_expire_pending_tick()** (7 connections) — `aios/core/cron_scheduler.py`
- **_loop()** (7 connections) — `aios/core/cron_scheduler.py`
- **start_cron_scheduler()** (4 connections) — `aios/core/cron_scheduler.py`
- **_backup_tick()** (3 connections) — `aios/core/cron_scheduler.py`
- **.run()** (3 connections) — `aios/tools/proactive_alerts.py`
- **subprocess** (2 connections)
- **C4: Daily 09:00 UTC - deals em mql >7d sem mover → push WhatsApp pro dono.** (1 connections) — `aios/core/cron_scheduler.py`
- **Daily 02:00 UTC — expira PendingAction alert-only por org pending_expiry_days…** (1 connections) — `aios/core/cron_scheduler.py`
- **Daily 03:00 UTC backup via deploy/backup.sh (minimalista, aws cli opcional).** (1 connections) — `aios/core/cron_scheduler.py`
- **Daily 08:00 UTC proactive sales drop alerts via WhatsApp.** (1 connections) — `aios/core/cron_scheduler.py`
- **Send alert message via active Evolution channel for org.** (1 connections) — `aios/tools/proactive_alerts.py`
- **Check if sales dropped >12% yesterday vs 7-day average. Returns alert dict if…** (1 connections) — `aios/tools/proactive_alerts.py`

## Relationships

- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (5 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (5 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (3 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (3 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (3 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (3 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (2 shared connections)
- [Daily Deal Queue](Daily_Deal_Queue.md) (2 shared connections)
- [Evolution Key Rotation & IP Allowlist](Evolution_Key_Rotation_&_IP_Allowlist.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)
- [HITL Pending Actions & CRM Create](HITL_Pending_Actions_&_CRM_Create.md) (2 shared connections)

## Source Files

- `aios/core/cron_scheduler.py`
- `aios/tools/proactive_alerts.py`

## Audit Trail

- EXTRACTED: 53 (78%)
- INFERRED: 15 (22%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*