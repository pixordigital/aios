# Evolution Channel (Baileys+Meta)

> 46 nodes · cohesion 0.06

## Key Concepts

- **EvolutionChannel** (40 connections) — `aios/channels/evolution.py`
- **evolution.py** (23 connections) — `aios/channels/evolution.py`
- **._send_baileys()** (13 connections) — `aios/channels/evolution.py`
- **record_event()** (7 connections) — `aios/core/whatsapp/anti_ban/signals.py`
- **._send_meta()** (6 connections) — `aios/channels/evolution.py`
- **record_response()** (6 connections) — `aios/core/whatsapp/anti_ban/signals.py`
- **.reconcile_provider()** (5 connections) — `aios/channels/evolution.py`
- **._validate_url()** (5 connections) — `aios/channels/evolution.py`
- **._check_instance_limit()** (4 connections) — `aios/channels/evolution.py`
- **.meta_credentials()** (4 connections) — `aios/channels/evolution.py`
- **.send()** (4 connections) — `aios/channels/evolution.py`
- **persist_cooldown()** (4 connections) — `aios/core/whatsapp_guard.py`
- **._build_meta_payload()** (3 connections) — `aios/channels/evolution.py`
- **.create_instance()** (3 connections) — `aios/channels/evolution.py`
- **.missing_meta_credentials()** (3 connections) — `aios/channels/evolution.py`
- **._set_webhook()** (3 connections) — `aios/channels/evolution.py`
- **record_ban_signal()** (3 connections) — `aios/core/whatsapp_guard.py`
- **vary_text()** (3 connections) — `aios/core/whatsapp_guard.py`
- **.api_key()** (2 connections) — `aios/channels/evolution.py`
- **.delete_instance()** (2 connections) — `aios/channels/evolution.py`
- **.get_instance_qrcode()** (2 connections) — `aios/channels/evolution.py`
- **.list_instances()** (2 connections) — `aios/channels/evolution.py`
- **.provider()** (2 connections) — `aios/channels/evolution.py`
- **.test()** (2 connections) — `aios/channels/evolution.py`
- **.base_url()** (1 connections) — `aios/channels/evolution.py`
- *... and 21 more nodes in this community*

## Relationships

- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (8 shared connections)
- [Evolution Webhook Inbound](Evolution_Webhook_Inbound.md) (6 shared connections)
- [Channel Base Interface](Channel_Base_Interface.md) (5 shared connections)
- [WhatsApp Warmup Curves](WhatsApp_Warmup_Curves.md) (5 shared connections)
- [Evolution Webhook Signature Auth](Evolution_Webhook_Signature_Auth.md) (4 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (3 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (2 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (2 shared connections)
- [Anti-Ban Proxy & Fingerprint](Anti-Ban_Proxy_&_Fingerprint.md) (1 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)

## Source Files

- `aios/channels/evolution.py`
- `aios/core/whatsapp/anti_ban/signals.py`
- `aios/core/whatsapp_guard.py`

## Audit Trail

- EXTRACTED: 103 (93%)
- INFERRED: 8 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*