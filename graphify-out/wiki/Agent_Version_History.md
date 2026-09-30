# Agent Version History

> 14 nodes · cohesion 0.15

## Key Concepts

- **Agents & Teams List** (6 connections) — `aios/dashboard/templates/agents.html`
- **Agent Version History Modal (GET /api/agents/{id}/versions)** (4 connections) — `aios/dashboard/templates/agent_form.html`
- **Channel Create/Edit Form** (4 connections) — `aios/dashboard/templates/channel_form.html`
- **Evolution Provider Selector (Baileys vs Meta Cloud API)** (4 connections) — `aios/dashboard/templates/channel_form.html`
- **Per-Type Credential Panels** (3 connections) — `aios/dashboard/templates/channel_form.html`
- **Agent Dry-Run Test (POST /dashboard/agents/{id}/test)** (2 connections) — `aios/dashboard/templates/agents.html`
- **Voice Agent Shortcuts (SDR / Closer / Suporte)** (2 connections) — `aios/dashboard/templates/agents.html`
- **Channel to Agent/Team Assignment** (2 connections) — `aios/dashboard/templates/channel_form.html`
- **Connection Test (POST /api/channels/test)** (2 connections) — `aios/dashboard/templates/channel_form.html`
- **Voice Provider Selector (self-hosted / ElevenLabs / Vapi / Retell / LiveKit)** (2 connections) — `aios/dashboard/templates/channel_form.html`
- **Version Diff View (unified + side-by-side fallback)** (1 connections) — `aios/dashboard/templates/agent_form.html`
- **One-Click Version Rollback (POST /api/agents/{id}/versions/{vid}/rollback)** (1 connections) — `aios/dashboard/templates/agent_form.html`
- **Sales Methodology Badges (BANT / SPIN / GPCT / DEF / H2H)** (1 connections) — `aios/dashboard/templates/agents.html`
- **Channel Save Action (POST /dashboard/channels/save)** (1 connections) — `aios/dashboard/templates/channel_form.html`

## Relationships

- [Agent Create/Edit Form](Agent_Create-Edit_Form.md) (4 shared connections)
- [Billing & Budget Dashboard](Billing_&_Budget_Dashboard.md) (1 shared connections)
- [Database Restore Action (POST /dashboard/admin +2](Database_Restore_Action_POST_-dashboard-admin_+2.md) (1 shared connections)
- [Agent Telemetry Health UI](Agent_Telemetry_Health_UI.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/agent_form.html`
- `aios/dashboard/templates/agents.html`
- `aios/dashboard/templates/channel_form.html`

## Audit Trail

- EXTRACTED: 16 (76%)
- INFERRED: 5 (24%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*