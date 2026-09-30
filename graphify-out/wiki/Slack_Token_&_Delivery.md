# Slack Token & Delivery

> 25 nodes · cohesion 0.21

## Key Concepts

- **SlackChannel** (21 connections) — `aios/channels/slack.py`
- **_patch()** (16 connections) — `tests/test_slack_channel.py`
- **test_slack_channel.py** (13 connections) — `tests/test_slack_channel.py`
- **TestSlackOutbound** (12 connections) — `tests/test_slack_channel.py`
- **_Conn** (11 connections) — `tests/test_slack_channel.py`
- **_msg()** (11 connections) — `tests/test_slack_channel.py`
- **.test_api_error_raises_for_retry()** (6 connections) — `tests/test_slack_channel.py`
- **.test_resolves_channel_id_key()** (6 connections) — `tests/test_slack_channel.py`
- **.test_falls_back_to_config_channel()** (5 connections) — `tests/test_slack_channel.py`
- **.test_legacy_channel_key_still_works()** (5 connections) — `tests/test_slack_channel.py`
- **.test_no_channel_returns_none()** (5 connections) — `tests/test_slack_channel.py`
- **.test_no_token_returns_none()** (5 connections) — `tests/test_slack_channel.py`
- **.test_send_works_without_start()** (5 connections) — `tests/test_slack_channel.py`
- **.test_thread_ts_forwarded()** (5 connections) — `tests/test_slack_channel.py`
- **.test_transport_error_propagates()** (5 connections) — `tests/test_slack_channel.py`
- **._ensure_app()** (4 connections) — `aios/channels/slack.py`
- **.start()** (2 connections) — `aios/channels/slack.py`
- **Return the bot token, or None if unconfigured. delivery.py calls build() per…** (1 connections) — `aios/channels/slack.py`
- **.__init__()** (1 connections) — `aios/channels/slack.py`
- **.stop()** (1 connections) — `aios/channels/slack.py`
- **.__init__()** (1 connections) — `tests/test_slack_channel.py`
- **Slack channel outbound + webhook routing tests. Outbound goes through httpx to…** (1 connections) — `tests/test_slack_channel.py`
- **A Slack API error must raise so delivery.py retries, not silently drop.** (1 connections) — `tests/test_slack_channel.py`
- **Regression: agent replies must reach Slack. delivery.py builds a fresh channel…** (1 connections) — `tests/test_slack_channel.py`
- **Inbound stores 'channel_id'; send must read that, not 'channel'.** (1 connections) — `tests/test_slack_channel.py`

## Relationships

- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (6 shared connections)
- [Channel Base Interface](Channel_Base_Interface.md) (5 shared connections)
- [Workflow Result](Workflow_Result.md) (3 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [Each manager/orchestrator channel routes to it +2](Each_manager-orchestrator_channel_routes_to_it_+2.md) (1 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (1 shared connections)
- [Billing, Budgets & Stripe Checkout](Billing,_Budgets_&_Stripe_Checkout.md) (1 shared connections)
- [CRM2 API](CRM2_API.md) (1 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (1 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (1 shared connections)

## Source Files

- `aios/channels/slack.py`
- `tests/test_slack_channel.py`

## Audit Trail

- EXTRACTED: 80 (96%)
- INFERRED: 3 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*