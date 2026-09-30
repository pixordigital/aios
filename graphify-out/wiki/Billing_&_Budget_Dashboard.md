# Billing & Budget Dashboard

> 14 nodes · cohesion 0.19

## Key Concepts

- **Billing & Usage Page** (11 connections) — `aios/dashboard/templates/billing.html`
- **Budget CRUD API (/api/billing/budget)** (4 connections) — `aios/dashboard/templates/billing.html`
- **Cost Breakdown by Agent and by Model** (3 connections) — `aios/dashboard/templates/billing.html`
- **Internal Mode Cost Control (AIOS_INTERNAL_MODE)** (3 connections) — `aios/dashboard/templates/billing.html`
- **Plan Quota & Usage Meter** (3 connections) — `aios/dashboard/templates/billing.html`
- **Internal Mode Nav Label (Uso & Custos vs Cobranca)** (2 connections) — `aios/dashboard/templates/base.html`
- **Budget Burn Forecast (how long the budget lasts)** (2 connections) — `aios/dashboard/templates/billing.html`
- **14-Day Pro Trial Offer** (2 connections) — `aios/dashboard/templates/billing.html`
- **ROI / Savings Calculator** (2 connections) — `aios/dashboard/templates/billing.html`
- **SLA Response Proxy (avg daily tokens)** (2 connections) — `aios/dashboard/templates/billing.html`
- **Stripe Checkout & Billing Portal** (2 connections) — `aios/dashboard/templates/billing.html`
- **WhatsApp Cloud API Recommendation Banner** (2 connections) — `aios/dashboard/templates/billing.html`
- **Budget Scoping (org / team / agent)** (1 connections) — `aios/dashboard/templates/billing.html`
- **Usage CSV Export (/api/analytics/usage/daily?days=30)** (1 connections) — `aios/dashboard/templates/billing.html`

## Relationships

- [Agent Telemetry Health UI](Agent_Telemetry_Health_UI.md) (3 shared connections)
- [Admin & Custom Domain Config](Admin_&_Custom_Domain_Config.md) (1 shared connections)
- [Per-Request Cost Estimator +2](Per-Request_Cost_Estimator_+2.md) (1 shared connections)
- [Agent Version History](Agent_Version_History.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/base.html`
- `aios/dashboard/templates/billing.html`

## Audit Trail

- EXTRACTED: 18 (78%)
- INFERRED: 5 (22%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*