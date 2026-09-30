# Zernio Integration Tests

> 25 nodes · cohesion 0.13

## Key Concepts

- **test_zernio.py** (22 connections) — `tests/test_zernio.py`
- **_FakeClient** (9 connections) — `tests/test_zernio.py`
- **asyncio** (7 connections)
- **_chan()** (5 connections) — `tests/test_zernio.py`
- **_Resp** (5 connections) — `tests/test_zernio.py`
- **test_zernio_cold_outreach_no_template_uses_utility()** (5 connections) — `tests/test_zernio.py`
- **test_zernio_cold_outreach_uses_template()** (5 connections) — `tests/test_zernio.py`
- **test_zernio_reply_in_thread()** (5 connections) — `tests/test_zernio.py`
- **test_meta_path_untouched()** (4 connections) — `tests/test_zernio.py`
- **.post()** (2 connections) — `tests/test_zernio.py`
- **test_webhook_rejects_bad_signature()** (2 connections) — `tests/test_zernio.py`
- **test_webhook_rejects_missing_signature()** (2 connections) — `tests/test_zernio.py`
- **test_webhook_rejects_unconfigured_secret()** (2 connections) — `tests/test_zernio.py`
- **aios_api_zernio_webhook** (1 connections)
- **aios_channels_whatsapp** (1 connections)
- **.__aenter__()** (1 connections) — `tests/test_zernio.py`
- **.__aexit__()** (1 connections) — `tests/test_zernio.py`
- **.__init__()** (1 connections) — `tests/test_zernio.py`
- **Zernio WhatsApp transport tests. Outbound uses Zernio's unified REST API…** (1 connections) — `tests/test_zernio.py`
- **provider unset → Meta Cloud path (no api_key/account used).** (1 connections) — `tests/test_zernio.py`
- **Captures requests and returns canned responses.** (1 connections) — `tests/test_zernio.py`
- **.__init__()** (1 connections) — `tests/test_zernio.py`
- **.json()** (1 connections) — `tests/test_zernio.py`
- **_sig()** (1 connections) — `tests/test_zernio.py`
- **test_zernio_matches()** (1 connections) — `tests/test_zernio.py`

## Relationships

- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (4 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (2 shared connections)
- [Channel Base Interface](Channel_Base_Interface.md) (1 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (1 shared connections)
- [Vector Extension & CRM Versions](Vector_Extension_&_CRM_Versions.md) (1 shared connections)

## Source Files

- `tests/test_zernio.py`

## Audit Trail

- EXTRACTED: 46 (94%)
- INFERRED: 3 (6%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*