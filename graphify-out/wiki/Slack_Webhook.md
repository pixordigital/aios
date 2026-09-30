# Slack Webhook

> 12 nodes · cohesion 0.23

## Key Concepts

- **slack_webhook.py** (16 connections) — `aios/api/slack_webhook.py`
- **slack_webhook()** (9 connections) — `aios/api/slack_webhook.py`
- **_find_connection()** (5 connections) — `aios/api/slack_webhook.py`
- **_verify_slack_signature()** (4 connections) — `aios/api/slack_webhook.py`
- **_channel_id_of()** (3 connections) — `aios/api/slack_webhook.py`
- **Request** (2 connections)
- **post** (1 connections)
- **Slack webhook — inbound events from Slack app. Routing: each Slack channel (a…** (1 connections) — `aios/api/slack_webhook.py`
- **Verify Slack request signature. Falls back to the global setting when the…** (1 connections) — `aios/api/slack_webhook.py`
- **Route by Slack channel. Each team/manager 1:1 channel gets its own…** (1 connections) — `aios/api/slack_webhook.py`
- **Slack puts the channel in different places depending on the event type.** (1 connections) — `aios/api/slack_webhook.py`
- **Receive Slack events → dispatch to agent.** (1 connections) — `aios/api/slack_webhook.py`

## Relationships

- [Discord Webhook](Discord_Webhook.md) (3 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (2 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (2 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (1 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)

## Source Files

- `aios/api/slack_webhook.py`

## Audit Trail

- EXTRACTED: 28 (93%)
- INFERRED: 2 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*