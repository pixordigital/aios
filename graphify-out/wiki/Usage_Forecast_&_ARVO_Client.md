# Usage Forecast & ARVO Client

> 33 nodes · cohesion 0.11

## Key Concepts

- **Organization** (130 connections) — `aios/db/models.py`
- **limits.py** (30 connections) — `aios/core/limits.py`
- **check_org_limits()** (22 connections) — `aios/core/limits.py`
- **billing_page()** (15 connections) — `aios/dashboard/app.py`
- **estimate_cost()** (14 connections) — `aios/core/tracing.py`
- **get_monthly_usage()** (13 connections) — `aios/core/limits.py`
- **admin_dashboard()** (11 connections) — `aios/dashboard/app.py`
- **test_plans.py** (10 connections) — `tests/test_plans.py`
- **get_agent_usage_breakdown()** (9 connections) — `aios/core/limits.py`
- **_send_budget_alert()** (9 connections) — `aios/core/limits.py`
- **proposal_page()** (9 connections) — `aios/dashboard/app.py`
- **get_usage_summary()** (8 connections) — `aios/core/limits.py`
- **_send_quota_alert()** (8 connections) — `aios/core/limits.py`
- **_default_org_id()** (8 connections) — `aios/dashboard/app.py`
- **usage_models()** (6 connections) — `aios/api/analytics.py`
- **budget_forecast()** (6 connections) — `aios/api/billing.py`
- **budget_alert_job()** (5 connections) — `aios/tasks/jobs.py`
- **_get_plan()** (4 connections) — `aios/core/limits.py`
- **asyncio** (4 connections)
- **test_default_org_prefers_pixor()** (4 connections) — `tests/test_plans.py`
- **_is_sqlite()** (3 connections) — `aios/core/limits.py`
- **_plan_limit()** (3 connections) — `aios/core/limits.py`
- **test_non_pixor_org_keeps_plan()** (3 connections) — `tests/test_plans.py`
- **test_pixor_downgrade_reverted()** (3 connections) — `tests/test_plans.py`
- **test_pixor_org_forced_unlimited()** (3 connections) — `tests/test_plans.py`
- *... and 8 more nodes in this community*

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (45 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (22 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (12 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (12 shared connections)
- [Billing, Budgets & Stripe Checkout](Billing,_Budgets_&_Stripe_Checkout.md) (11 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (11 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (10 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (10 shared connections)
- [CRM2 API](CRM2_API.md) (10 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (8 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (7 shared connections)
- [Usage Plan & Legal Templates](Usage_Plan_&_Legal_Templates.md) (6 shared connections)

## Source Files

- `aios/api/analytics.py`
- `aios/api/billing.py`
- `aios/core/limits.py`
- `aios/core/tracing.py`
- `aios/dashboard/app.py`
- `aios/db/models.py`
- `aios/tasks/jobs.py`
- `tests/test_plans.py`

## Audit Trail

- EXTRACTED: 164 (57%)
- INFERRED: 125 (43%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*