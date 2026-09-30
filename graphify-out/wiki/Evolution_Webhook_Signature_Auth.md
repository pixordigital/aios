# Evolution Webhook Signature Auth

> 22 nodes · cohesion 0.16

## Key Concepts

- **test_evolution_channel.py** (20 connections) — `tests/test_evolution_channel.py`
- **_verify_request()** (12 connections) — `aios/api/evolution_webhook.py`
- **_Req** (10 connections) — `tests/test_evolution_channel.py`
- **TestEvolutionWebhookAuth** (8 connections) — `tests/test_evolution_channel.py`
- **humanize_delay()** (5 connections) — `aios/core/whatsapp_guard.py`
- **.test_hmac_body_path_still_works()** (4 connections) — `tests/test_evolution_channel.py`
- **_Conn** (3 connections) — `tests/test_evolution_channel.py`
- **TestBanSignalWiring** (3 connections) — `tests/test_evolution_channel.py`
- **.test_humanize_delay_is_not_awaited()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_all_supported_headers()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_empty_api_key_rejects()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_hmac_wrong_key_rejected()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_missing_header_rejected()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_shared_secret_header_accepted()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_wrong_secret_rejected()** (3 connections) — `tests/test_evolution_channel.py`
- **Authenticate an Evolution webhook call. Primary path is the shared secret…** (1 connections) — `aios/api/evolution_webhook.py`
- **.__init__()** (1 connections) — `tests/test_evolution_channel.py`
- **Evolution integration tests. Two production-blocking bugs: 1. `_validate_url()`…** (1 connections) — `tests/test_evolution_channel.py`
- **Regression: every Baileys send was failing silently. `await…** (1 connections) — `tests/test_evolution_channel.py`
- **Minimal Request stand-in.** (1 connections) — `tests/test_evolution_channel.py`
- **.__init__()** (1 connections) — `tests/test_evolution_channel.py`
- **.test_no_awaited_sync_guard_helpers_remain()** (1 connections) — `tests/test_evolution_channel.py`

## Relationships

- [Tool Test Doubles](Tool_Test_Doubles.md) (5 shared connections)
- [Evolution Webhook Inbound](Evolution_Webhook_Inbound.md) (4 shared connections)
- [Evolution Channel (Baileys+Meta)](Evolution_Channel_Baileys+Meta.md) (4 shared connections)
- [Verify HMAC-SHA256 over the canonical body (pr +2](Verify_HMAC-SHA256_over_the_canonical_body_pr_+2.md) (3 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (1 shared connections)
- [Regression: Organization has no .plan column;  +2](Regression-_Organization_has_no_.plan_column;__+2.md) (1 shared connections)
- [_FakeClient +2](_FakeClient_+2.md) (1 shared connections)

## Source Files

- `aios/api/evolution_webhook.py`
- `aios/core/whatsapp_guard.py`
- `tests/test_evolution_channel.py`

## Audit Trail

- EXTRACTED: 56 (98%)
- INFERRED: 1 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*