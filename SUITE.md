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
pytest tests/test_team_collaboration.py → 31 passed

## Times reportando pro dono
Canal = ChannelConnection slack com `config.slack_1on1: true` (DM). Sem ele a
equipe não recebe relatório — o job conta em `teams_without_manager`/não posta.

- `weekly_report_job` — seg 9h15. Números 7d + meta do mês + leitura do gerente
  + pauta da 1:1. É a 1:1: o dono responde na thread.
- `monthly_report_job` — dia 1, 9h30. Fecha o mês anterior (janela do calendário).
- `weekly_standup_job` — seg 9h, no canal do time (números, sem meta).
- `ask_team_manager` / `notify_human` — tools nos managers e orquestradores.
  `ask_team_manager` é cross-team e bloqueado por org; teto de 3 saltos.

## Deploy
Coolify: AIOS 8777, ARVO 9777 (ou 9778:9777). Env:
AIOS_ARVO_INTEGRATION_ENABLED=true, ARVO_AIOS_INTEGRATION_ENABLED=true, same kid/secret.
Migrations: alembic upgrade head em ambos (budgets, integration_nonces/events).

## Control Center
/dashboard/control-center → HITL queue, degradação 24h, financeiro, humano vs agente, audit trail.
