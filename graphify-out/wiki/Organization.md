# Organization

> God node · 130 connections · `aios/db/models.py`

**Community:** [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md)

## Connections by Relation

### calls
- _oauth_login_or_register() `EXTRACTED`
- _org() `EXTRACTED`
- main() `EXTRACTED`
- .test_free_plan_max_agents() `EXTRACTED`
- .test_free_plan_max_channels() `EXTRACTED`
- .test_get_artifact_content_org_enforced() `EXTRACTED`

### contains
- models.py `EXTRACTED`

### imports
- app.py `EXTRACTED`
- main.py `EXTRACTED`
- api/auth.py `EXTRACTED`
- jobs.py `EXTRACTED`
- workflows.py `EXTRACTED`
- analytics.py `EXTRACTED`
- billing.py `EXTRACTED`
- agents.py `EXTRACTED`
- worker.py `EXTRACTED`
- crm2.py `EXTRACTED`
- routes.py `EXTRACTED`
- limits.py `EXTRACTED`
- conftest.py `EXTRACTED`
- admin_api.py `EXTRACTED`
- cron_scheduler.py `EXTRACTED`
- teams.py `EXTRACTED`
- test_crm_tools.py `EXTRACTED`
- evolution.py `EXTRACTED`
- test_evolution_channel.py `EXTRACTED`
- test_security.py `EXTRACTED`
- *…and 14 more `imports` connection(s) not listed (lowest-degree first to go)*

### inherits
- Base `EXTRACTED`
- TimestampMixin `EXTRACTED`

### references
- 2. BAA / DPA — LGPD (Encarregado + Medidas) `INFERRED`

### uses
- _render() `INFERRED`
- EvolutionChannel `INFERRED`
- lifespan() `INFERRED`
- check_org_limits() `INFERRED`
- _register_syscall_handlers() `INFERRED`
- register() `INFERRED`
- billing_page() `INFERRED`
- get_monthly_usage() `INFERRED`
- biweekly_1on1_job() `INFERRED`
- weekly_standup_job() `INFERRED`
- crm_page() `INFERRED`
- heartbeat() `INFERRED`
- admin_dashboard() `INFERRED`
- admin_org_detail() `INFERRED`
- crm_deal_detail() `INFERRED`
- register_action() `INFERRED`
- stripe_webhook() `INFERRED`
- create_agent() `INFERRED`
- deploy_agent() `INFERRED`
- google_calendar_disconnect() `INFERRED`
- *…and 66 more `uses` connection(s) not listed (lowest-degree first to go)*

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*