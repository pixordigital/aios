# Oncall, Alerting, DR Runbook (Scaffold)

Status: **scaffold**. No prod wiring/credentials. Human review required before enabling receivers or paging.

## Scope
- Prometheus rules: `deploy/prometheus/rules/aios-service.yml`, `deploy/prometheus/rules/whatsapp.yml`
- Prometheus scaffold: `deploy/prometheus/alerts-scaffold.yml`
- Alertmanager scaffold: `deploy/prometheus/alertmanager.scaffold.yml`
- Backup script: `deploy/backup.sh`

## RTO / RPO (placeholders — set with owner/SRE)
| Service/tier | RTO target | RPO target | Notes |
|---|---:|---:|---|
| AIOS API/dashboard | `TODO: e.g. 1h` | `TODO: e.g. 15m` | Depends on DB backup cadence + restore drill evidence |
| AIOS worker/queue | `TODO: e.g. 2h` | `TODO: e.g. 15m` | Define acceptable async backlog/replay |
| WhatsApp gateway | `TODO` | `TODO` | Channel-specific; confirm provider limits |
| Critical data (Postgres) | `TODO` | `TODO` | Must be proven by restore drill, not assumed |

## Escalation Matrix (placeholders)
| Severity | First response | Escalate to | Escalation time | Channel |
|---|---|---|---|---|
| critical | Oncall primary | Secondary/oncall lead + service owner | `TODO: 15m no ack` | `TODO: PagerDuty/Opsgenie/phone` |
| warning | Oncall/ops inbox | Service owner during business hours | `TODO: 4h no ack` | `TODO: Slack/email` |
| info | Ticket/backlog | N/A | N/A | `TODO` |

**Owners (fill):** service owner=`TODO`, SRE/oncall owner=`TODO`, DB owner=`TODO`, security owner=`TODO`.

## Paging / Ack / Comms
1. **Page fires**: Alertmanager routes by `severity` (scaffold). Confirm receiver before prod.
2. **Ack**: oncall acks within `TODO: 5m` critical / `TODO: 30m` warning. Ack means actively investigating.
3. **Mitigate/contain**: prefer safe containment (pause automation, scale/restart, rollback, disable integration) with human approval for destructive actions.
4. **Update cadence**: critical every `TODO: 15-30m`; warning every `TODO: 2-4h` or on state change.
5. **Resolve**: alert clears + smoke checks pass + evidence recorded.
6. **Post-incident**: create incident record, timeline, root cause, corrective action, update runbook/SLO.

## Alert Runbooks

### AIOSServiceDown
- **Signal**: `up{job=~"aios.*"} == 0` for 2m.
- **Impact**: API/dashboard unavailable or not scrapeable.
- **Check**:
  - `curl -fsS http://<aios>/health/live` and `/health/ready`
  - container/process logs, deploy events, DB/Redis connectivity.
  - Prometheus target page: confirm scrape config/labels.
- **Mitigate**: restart service after diagnosis; rollback recent deploy if correlated; restore DB connectivity.
- **Escalate**: if >`TODO RTO/2` or data risk.

### AIOSHTTPLatencyP95High
- **Signal**: p95 of `aios_http_request_duration_seconds_bucket` > 2s for 10m.
- **Impact**: degraded UX, timeouts, possible backlog.
- **Check**:
  - PromQL: `histogram_quantile(0.95, sum by (le) (rate(aios_http_request_duration_seconds_bucket[5m])))`
  - DB latency/locks, worker saturation, upstream LLM/provider latency, recent deploy.
- **Mitigate**: scale/restart affected component, shed load, disable expensive background jobs, rollback.
- **TODO**: add route/method labels for per-endpoint latency.

### AIOSHTTPErrorRateHigh
- **Status**: TODO metric gap. `aios_http_requests_total` has no `status` label in `aios/metrics.py`.
- **Before enabling**: instrument request counter with `status`/`method`/`path` labels or add dedicated 5xx counter; update rule in `deploy/prometheus/rules/aios-service.yml`.
- **Check when enabled**:
  - PromQL: `sum(rate(aios_http_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(aios_http_requests_total[5m])), 1)`
  - app logs, trace IDs, recent deploy, DB migrations, dependency failures.

### AIOSQueueLagHigh
- **Status**: TODO metric gap. No queue lag/depth metric found in repo metrics.
- **Before enabling**: export queue metric from worker/Redis (e.g., `aios_queue_lag_seconds`, `aios_queue_depth`, oldest job age). Label by queue/job.
- **Check when enabled**:
  - Redis connectivity, ARQ worker health, failed jobs/dead letters, external dependency latency.
  - Mitigate: restart worker, drain poison jobs with human review, scale workers.

### AIOSBackupStale
- **Status**: TODO metric gap. `deploy/backup.sh` writes backups/logs but no Prometheus metric.
- **Before enabling**: export `aios_backup_last_success_timestamp_seconds` via node_exporter textfile collector, cron wrapper, or pushgateway.
- **Check when enabled**:
  - inspect `/data/backups/backup.log`, latest `aios_*.sql.gz`, checksum/size, S3 sync status.
  - run manual backup in safe env; verify non-empty dump.

### AIOSBackupFailed
- **Status**: TODO metric gap. Export `aios_backup_last_success_bool` or last-exit metric.
- **Check when enabled**:
  - `deploy/backup.sh` exit/logs, pg_dump errors, disk space, DB creds, S3 permissions.
  - do not mark healthy until fresh backup artifact verified.

## DR Drill Checklist (human-gated, isolated only)
- [ ] Human owner approved drill; target is isolated throwaway DB/env.
- [ ] Select backup artifact; record name, size, mtime, SHA256.
- [ ] Integrity: `sha256sum <file>` and `gzip -t <file>`.
- [ ] Restore to isolated DB: `createdb aios_restore_drill` + `gunzip -c <file> | psql ...`.
- [ ] Migrate: `AIOS_DATABASE_URL=<restore> .venv/bin/alembic upgrade head` and `alembic current`.
- [ ] Smoke: `/health/ready` equivalent, login, critical tables/counts, basic queries.
- [ ] Spot-check tenant isolation and recent records.
- [ ] Record evidence: operator, UTC time, artifact, checksum, restore duration, migration/smoke result, observed RPO/RTO, issues, sign-off.
- [ ] Cleanup isolated DB/artifacts.
- [ ] File corrective actions; update runbook/SLO.

Reference: `docs/SECURITY_RELIABILITY_HARDENING.md`, `docs/business-os-runbook.md`.

## Alertmanager Notes
- `deploy/prometheus/alertmanager.scaffold.yml` uses null receivers by default. **Do not enable real receivers without approved secrets/TLS/auth.**
- Route critical/warning separately; inhibit warning when critical same alert/service.
- Add silences only with expiry, owner, and ticket.
