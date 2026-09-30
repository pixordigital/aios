# Outbound Message & Discord Channel

> 23 nodes · cohesion 0.11

## Key Concepts

- **OutboundMessage** (41 connections) — `aios/channels/base.py`
- **test_security.py** (20 connections) — `tests/test_security.py`
- **VoiceChannel** (9 connections) — `aios/channels/voice.py`
- **DiscordChannel** (8 connections) — `aios/channels/discord.py`
- **TestEvolutionSSRF** (5 connections) — `tests/test_security.py`
- **._resolve_channel()** (4 connections) — `aios/channels/slack.py`
- **.send()** (4 connections) — `aios/channels/slack.py`
- **.send()** (4 connections) — `aios/channels/voice.py`
- **.test_send_blocks_private_url()** (3 connections) — `tests/test_security.py`
- **TestTemplateXSS** (3 connections) — `tests/test_security.py`
- **.send()** (2 connections) — `aios/channels/discord.py`
- **.test()** (2 connections) — `aios/channels/voice.py`
- **.__init__()** (1 connections) — `aios/channels/discord.py`
- **.start()** (1 connections) — `aios/channels/discord.py`
- **.stop()** (1 connections) — `aios/channels/discord.py`
- **Inbound stores the Slack channel as 'channel_id'; older callers used 'channel'.** (1 connections) — `aios/channels/slack.py`
- **.__init__()** (1 connections) — `aios/channels/voice.py`
- **.start()** (1 connections) — `aios/channels/voice.py`
- **.stop()** (1 connections) — `aios/channels/voice.py`
- **Security regression tests — auth-gating and XSS escaping fixes.** (1 connections) — `tests/test_security.py`
- **Evolution channel must not send/test private hosts.** (1 connections) — `tests/test_security.py`
- **User-controlled values in JS attribute contexts must be JS-escaped.** (1 connections) — `tests/test_security.py`
- **.test_confirm_sink_escaped()** (1 connections) — `tests/test_security.py`

## Relationships

- [Channel Base Interface](Channel_Base_Interface.md) (18 shared connections)
- [Evolution Channel (Baileys+Meta)](Evolution_Channel_Baileys+Meta.md) (8 shared connections)
- [Slack Token & Delivery](Slack_Token_&_Delivery.md) (6 shared connections)
- [Zernio Integration Tests](Zernio_Integration_Tests.md) (4 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (3 shared connections)
- [IVR, PII Redaction & Call Routing](IVR,_PII_Redaction_&_Call_Routing.md) (3 shared connections)
- [accept_invite() +2](accept_invite_+2.md) (3 shared connections)
- [Dashboard CSRF Tests](Dashboard_CSRF_Tests.md) (3 shared connections)
- [Admin Fleet & DLQ](Admin_Fleet_&_DLQ.md) (2 shared connections)
- [EmailChannel +2](EmailChannel_+2.md) (2 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)
- [AsyncSession Delegation](AsyncSession_Delegation.md) (2 shared connections)

## Source Files

- `aios/channels/base.py`
- `aios/channels/discord.py`
- `aios/channels/slack.py`
- `aios/channels/voice.py`
- `tests/test_security.py`

## Audit Trail

- EXTRACTED: 76 (85%)
- INFERRED: 13 (15%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*