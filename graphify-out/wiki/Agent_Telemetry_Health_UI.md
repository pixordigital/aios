# Agent Telemetry Health UI

> 13 nodes · cohesion 0.18

## Key Concepts

- **Analytics & Telemetry Page** (5 connections) — `aios/dashboard/templates/analytics.html`
- **Per-Agent Metrics (GET /api/analytics/telemetry/agents)** (4 connections) — `aios/dashboard/templates/analytics.html`
- **Workflow Runs History** (4 connections) — `aios/dashboard/templates/automation_detail.html`
- **Autoscale Recommendation Page** (3 connections) — `aios/dashboard/templates/autoscale.html`
- **WorkflowRun Cost History** (3 connections) — `aios/dashboard/templates/autoscale.html`
- **Agent Health Status (GET /api/analytics/telemetry/health)** (2 connections) — `aios/dashboard/templates/analytics.html`
- **Proactive Alerts (GET/POST /api/analytics/proactive-alerts[/toggle])** (2 connections) — `aios/dashboard/templates/analytics.html`
- **Automation Run Comparison** (2 connections) — `aios/dashboard/templates/automation_compare.html`
- **Workflow Run Detail (inputs / outputs / node status)** (2 connections) — `aios/dashboard/templates/automation_run.html`
- **AgentMetrics Hourly History (5h)** (2 connections) — `aios/dashboard/templates/autoscale.html`
- **Autoscale Recommendation (up / down / stable)** (2 connections) — `aios/dashboard/templates/autoscale.html`
- **Raw Metrics Viewer** (1 connections) — `aios/dashboard/templates/analytics.html`
- **Telemetry Summary (GET /api/analytics/telemetry/summary)** (1 connections) — `aios/dashboard/templates/analytics.html`

## Relationships

- [Billing & Budget Dashboard](Billing_&_Budget_Dashboard.md) (3 shared connections)
- [Agent Version History](Agent_Version_History.md) (1 shared connections)
- [Workflow DAG Builder UI](Workflow_DAG_Builder_UI.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/analytics.html`
- `aios/dashboard/templates/automation_compare.html`
- `aios/dashboard/templates/automation_detail.html`
- `aios/dashboard/templates/automation_run.html`
- `aios/dashboard/templates/autoscale.html`

## Audit Trail

- EXTRACTED: 11 (58%)
- INFERRED: 8 (42%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*