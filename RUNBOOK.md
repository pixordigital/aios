# AIOS Runbook — Live Enterprise

## Deploy

```bash
git pull origin main
alembic upgrade head  # cria datasets, eval_runs, workflow tokens/cost, usage cost
docker compose up -d --build
docker compose exec app alembic upgrade head
```

## Verificação

- `GET /health/ready` → 200
- `GET /metrics` → prometheus
- `GET /api/docs` → swagger
- `k6 run scripts/k6_workflow.js -e TOKEN=...` → p95<5s

## Backup/Restore

```bash
./deploy/backup.sh  # /data/backups/aios_*.sql.gz 30d
pg_restore -d $AIOS_DATABASE_URL /data/backups/latest.sql.gz
```

## Canary

Deploy cria `green+canary:true`. `canary_rollback_job` 10min auto-rollback se err>5%. Manual:
`POST /api/agents/{id}/canary/promote` | `rollback`

## Workflow

`POST /api/workflows/{id}/run {"async":true}` → 202 + `WS /ws/workflows/{run_id}` streaming. Resume: `POST /resume/{run_id}` skip done. `on_failure: continue` para nós não críticos.

## RLS

Todas rotas `org_id` via `get_org_id`. `WorkflowRun` filtrado por `org_id`. Audit `X-Request-ID`.

## PromptLab

`/dashboard/promptlab` e `POST /api/promptlab/test` A/B.

## Escala

`autoscale_job` 0min hora verifica `avg_lat>3s`. `pgvector HNSW` já indexado.

## Incidente

Logs: `X-Trace-ID` header. DeadLetter: `GET /api/dead-letter`. Approvals: `GET /api/approvals`.
