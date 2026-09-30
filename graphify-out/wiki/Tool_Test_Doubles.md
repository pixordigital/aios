# Tool Test Doubles

> 22 nodes · cohesion 0.23

## Key Concepts

- **_ch()** (15 connections) — `tests/test_evolution_channel.py`
- **asyncio** (12 connections)
- **_FakeResp** (10 connections) — `tests/test_evolution_channel.py`
- **TestProviderSwitch** (10 connections) — `tests/test_evolution_channel.py`
- **._patch()** (8 connections) — `tests/test_evolution_channel.py`
- **TestEvolutionUrlValidation** (6 connections) — `tests/test_evolution_channel.py`
- **.test_asks_for_qr_when_baileys_not_connected()** (5 connections) — `tests/test_evolution_channel.py`
- **.test_meta_creates_separate_instance_with_credentials()** (5 connections) — `tests/test_evolution_channel.py`
- **.test_recreates_when_name_exists_with_wrong_integration()** (5 connections) — `tests/test_evolution_channel.py`
- **.test_reports_webhook_failure_even_when_instance_ok()** (5 connections) — `tests/test_evolution_channel.py`
- **.test_switch_back_reuses_paired_baileys_instance()** (5 connections) — `tests/test_evolution_channel.py`
- **.test_webhook_secret_goes_in_headers_not_webhookauth()** (5 connections) — `tests/test_evolution_channel.py`
- **.test_internal_evolution_url_is_allowed()** (4 connections) — `tests/test_evolution_channel.py`
- **.test_embedded_credentials_blocked()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_https_public_allowed()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_missing_host_blocked()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_non_http_scheme_blocked()** (3 connections) — `tests/test_evolution_channel.py`
- **.test_meta_requires_credentials()** (3 connections) — `tests/test_evolution_channel.py`
- **.__init__()** (1 connections) — `tests/test_evolution_channel.py`
- **.json()** (1 connections) — `tests/test_evolution_channel.py`
- **The channel form writes config['provider'] but never told Evolution. Flipping…** (1 connections) — `tests/test_evolution_channel.py`
- **The regression: internal Docker host must pass.** (1 connections) — `tests/test_evolution_channel.py`

## Relationships

- [Evolution Webhook Signature Auth](Evolution_Webhook_Signature_Auth.md) (5 shared connections)
- [_FakeClient +2](_FakeClient_+2.md) (2 shared connections)
- [Evolution Channel (Baileys+Meta)](Evolution_Channel_Baileys+Meta.md) (1 shared connections)

## Source Files

- `tests/test_evolution_channel.py`

## Audit Trail

- EXTRACTED: 61 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*