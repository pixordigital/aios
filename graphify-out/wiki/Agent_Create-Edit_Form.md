# Agent Create/Edit Form

> 13 nodes · cohesion 0.22

## Key Concepts

- **Agent Create/Edit Form** (12 connections) — `aios/dashboard/templates/agent_form.html`
- **Lightweight Markdown Prompt Editor** (4 connections) — `aios/dashboard/templates/agent_form.html`
- **All Agent Blueprints Catalog (agent_templates)** (4 connections) — `aios/dashboard/templates/agents.html`
- **Governance Blueprints - Deal Desk (5 Specialists)** (4 connections) — `aios/dashboard/templates/agents.html`
- **Autonomous Agent Governance Loop (100% + HITL)** (3 connections) — `aios/dashboard/templates/agent_form.html`
- **Per-Agent-Type Prompt Templates (PROMPT_TEMPLATES)** (3 connections) — `aios/dashboard/templates/agent_form.html`
- **HITL Escalation Thresholds (value / discount)** (2 connections) — `aios/dashboard/templates/agent_form.html`
- **Prompt Tag Structure (6 tags / 12 tags advanced)** (2 connections) — `aios/dashboard/templates/agent_form.html`
- **Skills Import from URL (POST /api/skills/import-url, GET /api/skills)** (2 connections) — `aios/dashboard/templates/agent_form.html`
- **Agent Tool Picker (tool pills)** (2 connections) — `aios/dashboard/templates/agent_form.html`
- **Agent Save Action (POST /dashboard/agents/save)** (1 connections) — `aios/dashboard/templates/agent_form.html`
- **Agent Memory Configuration (short-term / long-term / episodic)** (1 connections) — `aios/dashboard/templates/agent_form.html`
- **Prompt Validation (length + PT-BR language gate)** (1 connections) — `aios/dashboard/templates/agent_form.html`

## Relationships

- [Agent Version History](Agent_Version_History.md) (4 shared connections)
- [Workflow DAG Builder UI](Workflow_DAG_Builder_UI.md) (2 shared connections)
- [Per-Request Cost Estimator +2](Per-Request_Cost_Estimator_+2.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/agent_form.html`
- `aios/dashboard/templates/agents.html`

## Audit Trail

- EXTRACTED: 18 (75%)
- INFERRED: 6 (25%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*