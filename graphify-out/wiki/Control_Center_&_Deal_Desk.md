# Control Center & Deal Desk

> 18 nodes · cohesion 0.16

## Key Concepts

- **AIOS Landing Page** (13 connections) — `website/index.html`
- **Control Center Page (Deal Desk Governado)** (8 connections) — `aios/dashboard/templates/control_center.html`
- **Governance Blueprints (deal_auditor, pricing_guardian, evidence_compiler, performance_watcher, human_auditor)** (6 connections) — `website/index.html`
- **Audit Trail / 3-Layer Evidence Pack** (3 connections) — `aios/dashboard/templates/control_center.html`
- **Human vs Agent Deal Change View (CrmDealVersion)** (3 connections) — `aios/dashboard/templates/control_center.html`
- **Pricing Guardian Financial Panel** (3 connections) — `aios/dashboard/templates/control_center.html`
- **ARVO Immutable Financial Ledger Suite** (3 connections) — `website/index.html`
- **Internal Tool Positioning (No Signup, No Billing)** (3 connections) — `website/index.html`
- **Deal Desk Team Template** (2 connections) — `aios/dashboard/templates/control_center.html`
- **Performance Degradation 24h Panel** (2 connections) — `aios/dashboard/templates/control_center.html`
- **Daily Call Queue With Timing Score** (2 connections) — `aios/dashboard/templates/crm.html`
- **Deal Change History (C6)** (2 connections) — `aios/dashboard/templates/crm_deal_detail.html`
- **16 One-Click Agent Blueprints** (2 connections) — `website/index.html`
- **Outbox + Async Event Integration Flow (HMAC-SHA256)** (2 connections) — `website/index.html`
- **OpenTelemetry Observability** (2 connections) — `website/index.html`
- **Per-Organization RLS Isolation** (2 connections) — `website/index.html`
- **PDF Knowledge Base / RAG Pipeline** (2 connections) — `website/index.html`
- **Artifact File Viewer Page** (1 connections) — `aios/dashboard/templates/file_view.html`

## Relationships

- [AI-Operated Deal Pipeline](AI-Operated_Deal_Pipeline.md) (4 shared connections)
- [Voice Provider Options](Voice_Provider_Options.md) (4 shared connections)
- [HITL Queue Panel +2](HITL_Queue_Panel_+2.md) (2 shared connections)
- [Dashboard Home Page +2](Dashboard_Home_Page_+2.md) (1 shared connections)
- [Dev Page (Claude + Codex) +2](Dev_Page_Claude_+_Codex_+2.md) (1 shared connections)
- [Channel Dashboard & Test Endpoint](Channel_Dashboard_&_Test_Endpoint.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/control_center.html`
- `aios/dashboard/templates/crm.html`
- `aios/dashboard/templates/crm_deal_detail.html`
- `aios/dashboard/templates/file_view.html`
- `website/index.html`

## Audit Trail

- EXTRACTED: 22 (59%)
- INFERRED: 15 (41%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*