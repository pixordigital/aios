# Channel Base Interface

> 42 nodes · cohesion 0.07

## Key Concepts

- **Channel** (25 connections) — `aios/channels/base.py`
- **channels/manager.py** (21 connections) — `aios/channels/manager.py`
- **channels/base.py** (16 connections) — `aios/channels/base.py`
- **email_.py** (11 connections) — `aios/channels/email_.py`
- **channels/voice.py** (10 connections) — `aios/channels/voice.py`
- **WebChannel** (10 connections) — `aios/channels/web.py`
- **slack.py** (9 connections) — `aios/channels/slack.py`
- **web.py** (9 connections) — `aios/channels/web.py`
- **TelegramChannel** (8 connections) — `aios/channels/telegram.py`
- **ChannelManager** (7 connections) — `aios/channels/manager.py`
- **discord.py** (6 connections) — `aios/channels/discord.py`
- **telegram.py** (6 connections) — `aios/channels/telegram.py`
- **.build()** (3 connections) — `aios/channels/manager.py`
- **.send()** (2 connections) — `aios/channels/base.py`
- **.test()** (2 connections) — `aios/channels/base.py`
- **ABC** (2 connections)
- **.start()** (2 connections) — `aios/channels/manager.py`
- **.stop()** (2 connections) — `aios/channels/manager.py`
- **.send()** (2 connections) — `aios/channels/telegram.py`
- **.send()** (2 connections) — `aios/channels/web.py`
- **.start()** (1 connections) — `aios/channels/base.py`
- **.stop()** (1 connections) — `aios/channels/base.py`
- **InboundMessage** (1 connections) — `aios/channels/base.py`
- **Channel abstraction — all adapters implement this.** (1 connections) — `aios/channels/base.py`
- **Test connection. Returns {"ok": True/False, "message": "..."}.** (1 connections) — `aios/channels/base.py`
- *... and 17 more nodes in this community*

## Relationships

- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (18 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (9 shared connections)
- [Evolution Channel (Baileys+Meta)](Evolution_Channel_Baileys+Meta.md) (5 shared connections)
- [Slack Token & Delivery](Slack_Token_&_Delivery.md) (5 shared connections)
- [EmailChannel +2](EmailChannel_+2.md) (3 shared connections)
- [IVR, PII Redaction & Call Routing](IVR,_PII_Redaction_&_Call_Routing.md) (3 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (2 shared connections)
- [Discord Webhook](Discord_Webhook.md) (2 shared connections)
- [Zernio Integration Tests](Zernio_Integration_Tests.md) (1 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (1 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (1 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)

## Source Files

- `aios/channels/base.py`
- `aios/channels/discord.py`
- `aios/channels/email_.py`
- `aios/channels/manager.py`
- `aios/channels/slack.py`
- `aios/channels/telegram.py`
- `aios/channels/voice.py`
- `aios/channels/web.py`

## Audit Trail

- EXTRACTED: 111 (97%)
- INFERRED: 3 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*