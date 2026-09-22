# Suite AIOS + ARVO

**AIOS** = agente workforce (SDR, closer, deal_auditor, pricing_guardian, performance_watcher) + HITL + WhatsApp 2026 + Budget forecast.
**ARVO** = ledger financeiro idempotente + findings + evidence pack.

Suite = HMAC service-to-service + POST /events idempotente + Control Center.

## Health
- AIOS: GET /health/live → live, GET /api/integrations/arvo/v1/health HMAC → ok
- ARVO: GET /health/live → live, GET /api/v1/integrations/aios/v1/health HMAC → ok

## Suite teste
pytest tests/test_suite_integration.py -v → 4 passed
pytest tests/test_arvo_integration.py -v → 8 passed
pytest tests/test_aios_integration.py (arvo) → 8 passed

## Deploy
Coolify: AIOS 8777, ARVO 9777 (ou 9778:9777). Env:
AIOS_ARVO_INTEGRATION_ENABLED=true, ARVO_AIOS_INTEGRATION_ENABLED=true, same kid/secret.
Migrations: alembic upgrade head em ambos (budgets, integration_nonces/events).

## Control Center
/dashboard/control-center → HITL queue, degradação 24h, financeiro, humano vs agente, audit trail.
