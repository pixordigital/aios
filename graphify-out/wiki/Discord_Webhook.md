# Discord Webhook

> 24 nodes · cohesion 0.11

## Key Concepts

- **dispatch_inbound()** (20 connections) — `aios/core/dispatch.py`
- **email_webhook.py** (13 connections) — `aios/api/email_webhook.py`
- **discord_webhook.py** (11 connections) — `aios/api/discord_webhook.py`
- **discord_webhook()** (7 connections) — `aios/api/discord_webhook.py`
- **email_webhook()** (6 connections) — `aios/api/email_webhook.py`
- **_process_inbound_email()** (6 connections) — `aios/api/email_webhook.py`
- **_verify_email_signature()** (4 connections) — `aios/api/email_webhook.py`
- **Health check endpoint.** (3 connections) — `aios/api/email_webhook.py`
- **.handle_incoming()** (3 connections) — `aios/channels/web.py`
- **discord_webhook_verify()** (2 connections) — `aios/api/discord_webhook.py`
- **email_webhook_verify()** (2 connections) — `aios/api/email_webhook.py`
- **Request** (2 connections)
- **slack_webhook_verify()** (2 connections) — `aios/api/slack_webhook.py`
- **post** (1 connections)
- **Request** (1 connections)
- **Discord webhook — inbound messages from Discord bot.** (1 connections) — `aios/api/discord_webhook.py`
- **Receive Discord messages via webhook → dispatch to agent.** (1 connections) — `aios/api/discord_webhook.py`
- **post** (1 connections)
- **Email webhook — inbound emails from SendGrid/Mailgun/SES/AWS.** (1 connections) — `aios/api/email_webhook.py`
- **Verify webhook signature based on provider.** (1 connections) — `aios/api/email_webhook.py`
- **Receive inbound email from provider → dispatch to agent.** (1 connections) — `aios/api/email_webhook.py`
- **Extract email content and dispatch to agent.** (1 connections) — `aios/api/email_webhook.py`
- **Receive incoming WebSocket message → dispatch to ARQ worker.** (1 connections) — `aios/channels/web.py`
- **Enqueue inbound message for async processing by ARQ worker. Called by webhook…** (1 connections) — `aios/core/dispatch.py`

## Relationships

- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (6 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (4 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)
- [Slack Webhook](Slack_Webhook.md) (3 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (2 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (2 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (2 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (2 shared connections)
- [Channel Base Interface](Channel_Base_Interface.md) (2 shared connections)
- [Evolution Webhook Inbound](Evolution_Webhook_Inbound.md) (2 shared connections)
- [Voice API & Call Placement](Voice_API_&_Call_Placement.md) (2 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (2 shared connections)

## Source Files

- `aios/api/discord_webhook.py`
- `aios/api/email_webhook.py`
- `aios/api/slack_webhook.py`
- `aios/channels/web.py`
- `aios/core/dispatch.py`

## Audit Trail

- EXTRACTED: 59 (94%)
- INFERRED: 4 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*