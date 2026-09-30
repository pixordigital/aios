# Channel Dashboard & Test Endpoint

> 15 nodes · cohesion 0.14

## Key Concepts

- **Channel Type Taxonomy (web/evolution/slack/telegram/discord/email/voice)** (6 connections) — `aios/dashboard/templates/channels.html`
- **Channels Dashboard Page** (4 connections) — `aios/dashboard/templates/channels.html`
- **Unified Inbox Page** (4 connections) — `aios/dashboard/templates/conversations.html`
- **Quick Channel Connect Modal** (3 connections) — `aios/dashboard/templates/channels.html`
- **Multi-Channel Delivery With WhatsApp Central** (3 connections) — `website/index.html`
- **Channel List With Type Icon And Active Badge** (2 connections) — `aios/dashboard/templates/channels.html`
- **Human Handover With SLA Timer** (2 connections) — `aios/dashboard/templates/conversation_detail.html`
- **Bot / Human / Assigned Conversation State** (2 connections) — `aios/dashboard/templates/conversations.html`
- **Three-Step Getting Started Guide** (2 connections) — `aios/dashboard/templates/dashboard.html`
- **Slack Event Subscriptions** (2 connections) — `deploy/slack-manifest.yaml`
- **Slack OAuth Bot Scopes** (2 connections) — `deploy/slack-manifest.yaml`
- **Slack App Manifest (AIOS bot)** (2 connections) — `deploy/slack-manifest.yaml`
- **Slack Webhook Endpoint /api/slack/webhook** (2 connections) — `deploy/slack-manifest.yaml`
- **Channel Connection Test Endpoint (/api/channels/test)** (1 connections) — `aios/dashboard/templates/channels.html`
- **Client-Side Inbox Filter (channel/assignment/text)** (1 connections) — `aios/dashboard/templates/conversations.html`

## Relationships

- [Voice Provider Options](Voice_Provider_Options.md) (3 shared connections)
- [Dashboard Home Page +2](Dashboard_Home_Page_+2.md) (2 shared connections)
- [Evolution Gateway Wrapper](Evolution_Gateway_Wrapper.md) (1 shared connections)
- [HITL Queue Panel +2](HITL_Queue_Panel_+2.md) (1 shared connections)
- [Control Center & Deal Desk](Control_Center_&_Deal_Desk.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/channels.html`
- `aios/dashboard/templates/conversation_detail.html`
- `aios/dashboard/templates/conversations.html`
- `aios/dashboard/templates/dashboard.html`
- `deploy/slack-manifest.yaml`
- `website/index.html`

## Audit Trail

- EXTRACTED: 16 (70%)
- INFERRED: 7 (30%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*