# db_session()

> God node · 232 connections · `aios/db/backend.py`

**Community:** [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md)

## Connections by Relation

### calls
- _render() `EXTRACTED`
- lifespan() `EXTRACTED`
- _register_syscall_handlers() `EXTRACTED`
- evolution_webhook() `EXTRACTED`
- _process_inbound_once() `EXTRACTED`
- write_dlq() `EXTRACTED`
- billing_page() `EXTRACTED`
- deliver_message() `EXTRACTED`
- biweekly_1on1_job() `EXTRACTED`
- weekly_standup_job() `EXTRACTED`
- retry_dlq() `EXTRACTED`
- control_center() `EXTRACTED`
- crm_page() `EXTRACTED`
- dashboard_home() `EXTRACTED`
- lojista_create() `EXTRACTED`
- heartbeat() `EXTRACTED`
- .update() `EXTRACTED`
- admin_dashboard() `EXTRACTED`
- admin_org_detail() `EXTRACTED`
- automation_detail() `EXTRACTED`
- *…and 177 more `calls` connection(s) not listed (lowest-degree first to go)*

### contains
- db/backend.py `EXTRACTED`

### imports
- app.py `EXTRACTED`
- main.py `EXTRACTED`
- jobs.py `EXTRACTED`
- billing.py `EXTRACTED`
- whatsapp.py `EXTRACTED`
- limits.py `EXTRACTED`
- admin_api.py `EXTRACTED`
- whatsapp_guard.py `EXTRACTED`
- evolution_webhook.py `EXTRACTED`
- test_crm_tools.py `EXTRACTED`
- ws.py `EXTRACTED`
- learning_worker.py `EXTRACTED`
- test_dead_letter.py `EXTRACTED`
- slack_webhook.py `EXTRACTED`
- autonomous_agent.py `EXTRACTED`
- delivery.py `EXTRACTED`
- seed_internal_teams.py `EXTRACTED`
- dead_letter.py `EXTRACTED`
- api/license.py `EXTRACTED`
- core/agent_db.py `EXTRACTED`
- *…and 11 more `imports` connection(s) not listed (lowest-degree first to go)*

### rationale_for
- Context manager yielding a fresh backend with dedicated session per call. Each… `EXTRACTED`

### references
- [DatabaseBackend](DatabaseBackend.md) `EXTRACTED`
- 1. O que foi entregue (SWE Lead, 10min) `INFERRED`

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*