# Channel Input Validation Tests

> 20 nodes · cohesion 0.14

## Key Concepts

- **AsyncClient** (19 connections)
- **TestChannelValidation** (7 connections) — `tests/test_channel_types.py`
- **TestWhatsappGatewayAuth** (6 connections) — `tests/test_channel_types.py`
- **.test_invalid_channel_type_rejected()** (3 connections) — `tests/test_channel_types.py`
- **.test_missing_required_config_evolution()** (3 connections) — `tests/test_channel_types.py`
- **.test_missing_required_config_whatsapp()** (3 connections) — `tests/test_channel_types.py`
- **.test_ssrf_protection_allowed_public()** (3 connections) — `tests/test_channel_types.py`
- **.test_ssrf_protection_blocked()** (3 connections) — `tests/test_channel_types.py`
- **.test_legacy_webhook_fails_closed_without_secret()** (3 connections) — `tests/test_channel_types.py`
- **.test_call_requires_auth()** (2 connections) — `tests/test_channel_types.py`
- **.test_health_requires_auth()** (2 connections) — `tests/test_channel_types.py`
- **.test_send_requires_auth()** (2 connections) — `tests/test_channel_types.py`
- **Test channel input validation.** (1 connections) — `tests/test_channel_types.py`
- **Invalid channel type should be rejected by validation at runtime.** (1 connections) — `tests/test_channel_types.py`
- **WhatsApp channel should work with minimal config.** (1 connections) — `tests/test_channel_types.py`
- **Evolution channel should work with minimal config.** (1 connections) — `tests/test_channel_types.py`
- **Private URLs should be blocked in channel test (SSRF guard).** (1 connections) — `tests/test_channel_types.py`
- **Public URLs should be allowed in channel test.** (1 connections) — `tests/test_channel_types.py`
- **Regression: /api/whatsapp/* was mounted with no auth at all. Anyone who could…** (1 connections) — `tests/test_channel_types.py`
- **The legacy Evolution webhook validated with an empty secret. With no secret…** (1 connections) — `tests/test_channel_types.py`

## Relationships

- [Channel Association Tests](Channel_Association_Tests.md) (6 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (3 shared connections)
- [Test webhook endpoints for channels that have  +2](Test_webhook_endpoints_for_channels_that_have__+2.md) (3 shared connections)

## Source Files

- `tests/test_channel_types.py`

## Audit Trail

- EXTRACTED: 38 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*