# ARVO Auth & Nonces

> 28 nodes · cohesion 0.15

## Key Concepts

- **sign_request()** (17 connections) — `aios/integrations/arvo/auth.py`
- **arvo/auth.py** (16 connections) — `aios/integrations/arvo/auth.py`
- **verify_request()** (15 connections) — `aios/integrations/arvo/auth.py`
- **test_arvo_integration.py** (15 connections) — `tests/test_arvo_integration.py`
- **_clear_nonces()** (9 connections) — `aios/integrations/arvo/auth.py`
- **_clear_events()** (5 connections) — `aios/integrations/arvo/routes.py`
- **test_suite_health_both()** (5 connections) — `tests/test_suite_integration.py`
- **test_suite_hmac_cross()** (5 connections) — `tests/test_suite_integration.py`
- **test_events_idempotency()** (4 connections) — `tests/test_arvo_integration.py`
- **test_verify_rejects_bad_body_tamper()** (4 connections) — `tests/test_arvo_integration.py`
- **test_verify_rejects_replay()** (4 connections) — `tests/test_arvo_integration.py`
- **_body_hash()** (3 connections) — `aios/integrations/arvo/auth.py`
- **_canonical()** (3 connections) — `aios/integrations/arvo/auth.py`
- **_register_nonce()** (3 connections) — `aios/integrations/arvo/auth.py`
- **test_health_requires_auth_when_enabled()** (3 connections) — `tests/test_arvo_integration.py`
- **test_sign_verify_roundtrip()** (3 connections) — `tests/test_arvo_integration.py`
- **test_verify_rejects_stale_timestamp()** (3 connections) — `tests/test_arvo_integration.py`
- **test_verify_rejects_wrong_key()** (3 connections) — `tests/test_arvo_integration.py`
- **threading** (3 connections)
- **Ambiente de autenticação service-to-service ARVO. HMAC stdlib, sem novas deps.…** (1 connections) — `aios/integrations/arvo/auth.py`
- **Registra nonce; retorna False se replay. Expira após 2× skew.** (1 connections) — `aios/integrations/arvo/auth.py`
- **Headers de assinatura para request outbound.** (1 connections) — `aios/integrations/arvo/auth.py`
- **Valida assinatura inbound. Segurança: - comparação constante de tempo contra…** (1 connections) — `aios/integrations/arvo/auth.py`
- **ambiguous_python_import_e36d78a17588** (1 connections)
- **Fase 1 — ARVO integration config + auth self-check. Fase 2 — HMAC + nonce +…** (1 connections) — `tests/test_arvo_integration.py`
- *... and 3 more nodes in this community*

## Relationships

- [Integration Events Idempotency](Integration_Events_Idempotency.md) (6 shared connections)
- [Transactional Outbox](Transactional_Outbox.md) (6 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (2 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [_headers() +2](_headers_+2.md) (1 shared connections)
- [Logging Config](Logging_Config.md) (1 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (1 shared connections)

## Source Files

- `aios/integrations/arvo/auth.py`
- `aios/integrations/arvo/routes.py`
- `tests/test_arvo_integration.py`
- `tests/test_suite_integration.py`

## Audit Trail

- EXTRACTED: 76 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*