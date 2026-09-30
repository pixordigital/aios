# Workflow DAG Builder UI

> 13 nodes · cohesion 0.18

## Key Concepts

- **Automations List** (7 connections) — `aios/dashboard/templates/automations.html`
- **Automation Detail** (4 connections) — `aios/dashboard/templates/automation_detail.html`
- **DAG Node Builder (agent / tool / code / if / wait)** (4 connections) — `aios/dashboard/templates/automation_detail.html`
- **Workflow Triggers (webhook / cron / event)** (3 connections) — `aios/dashboard/templates/automation_detail.html`
- **Workflow DAG Flow View** (2 connections) — `aios/dashboard/templates/automation_detail.html`
- **Automation Credential Store (POST /dashboard/automations/credentials)** (2 connections) — `aios/dashboard/templates/automations.html`
- **Visual Cron Builder** (2 connections) — `aios/dashboard/templates/automations.html`
- **Recent Executions Panel** (2 connections) — `aios/dashboard/templates/automations.html`
- **Automation Templates (1-click)** (2 connections) — `aios/dashboard/templates/automations.html`
- **Template Data Passing ({{json.*}} / {{outputs.node_id}})** (1 connections) — `aios/dashboard/templates/automation_detail.html`
- **Webhook Trigger URL (/api/automations/webhook/{path})** (1 connections) — `aios/dashboard/templates/automation_detail.html`
- **Automation Test Run (POST /dashboard/automations/{id}/run)** (1 connections) — `aios/dashboard/templates/automations.html`
- **No-n8n Workflow Positioning** (1 connections) — `aios/dashboard/templates/automations.html`

## Relationships

- [Agent Create/Edit Form](Agent_Create-Edit_Form.md) (2 shared connections)
- [Agent Telemetry Health UI](Agent_Telemetry_Health_UI.md) (1 shared connections)
- [Database Restore Action (POST /dashboard/admin +2](Database_Restore_Action_POST_-dashboard-admin_+2.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/automation_detail.html`
- `aios/dashboard/templates/automations.html`

## Audit Trail

- EXTRACTED: 15 (83%)
- INFERRED: 3 (17%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*