# AIOS SLO / SLI (Initial Scaffold)

Status: **initial targets, not production-approved**. No external SLO service wiring. Validate metrics exist before alerting/paging.

## Principles
- SLOs measure user/service outcomes; do not use infra metrics as sole targets.
- Use only metrics that exist or are explicitly marked TODO.
- Review monthly and after incidents; adjust targets with owner/SRE approval.

## Current Metric Inventory (repo-observed)
| Signal | Source | Status |
|---|---|---|
| Scrape/up | Prometheus `up{job=~"aios.*"}` | Available if Prometheus scrapes AIOS |
| HTTP request count | `aios_http_requests_total` (`aios/metrics.py`) | Available, **no status/method/path labels** |
| HTTP latency histogram | `aios_http_request_duration_seconds_bucket` (`aios/metrics.py`) | Available |
| Readiness/liveness | `/health/live`, `/health/ready` (`aios/main.py`) | Available as endpoint checks; not Prometheus metrics unless exported |
| Queue lag/depth | N/A found | **TODO metric gap** |
| Backup age/success | `deploy/backup.sh` artifacts/logs | **TODO metric gap** (no Prometheus metric) |

## Initial SLI/SLO Targets (draft)

| Service | SLI | Target (draft) | Window | Measurement | Notes |
|---|---|---:|---|---|---|
| AIOS API availability | Successful scrape / health availability | 99.5% | 30d | `avg_over_time(up{job=~"aios.*"}[30d])` and `/health/ready` probe success | `up` means scrapeable, not full user success; pair with synthetic checks |
| AIOS API latency | p95 request latency | p95 < 2s for 99% of 5m windows | 30d | `histogram_quantile(0.95, sum by (le) (rate(aios_http_request_duration_seconds_bucket[5m])))` | Uses existing histogram; add route labels before per-endpoint SLO |
| AIOS API error rate | 5xx / total requests | < 1% | 30d | **TODO** after instrumentation: `sum(rate(aios_http_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(aios_http_requests_total[5m])),1)` | Cannot be measured accurately until status label/counter exists |
| Async jobs/queue | Queue lag / oldest job age | p95 lag < 5m, backlog < `TODO` | 30d | **TODO metric gap**: export `aios_queue_lag_seconds` or oldest-job age | ARQ/Redis queue exists; metric export missing |
| Backup freshness | Time since last successful backup | < 26h | rolling | **TODO metric gap**: `time() - aios_backup_last_success_timestamp_seconds` | `deploy/backup.sh` creates `aios_*.sql.gz`; add textfile/push metric |
| Restore confidence | Successful restore drill | >= 1 successful drill / quarter | 90d | Manual evidence in runbook/incident/drill log | Not a Prometheus metric; human-gated |

## Error Budget (draft)
- 99.5% / 30d availability => ~3h 39m downtime budget.
- Error-rate/latency budgets: define after status-labeled metrics and traffic baseline exist.
- Policy (TODO): when budget burned >50%, freeze risky deploys; >100%, incident review required.

## Measurement Commands

### Prometheus / PromQL (when Prometheus running)
```bash
# Target up
curl -fsS 'http://PROMETHEUS/api/v1/query?query=up{job=~"aios.*"}'

# p95 latency (5m)
curl -fsS --get 'http://PROMETHEUS/api/v1/query' \
  --data-urlencode 'query=histogram_quantile(0.95, sum by (le) (rate(aios_http_request_duration_seconds_bucket[5m])))'

# Request rate (no status label yet)
curl -fsS --get 'http://PROMETHEUS/api/v1/query' \
  --data-urlencode 'query=sum(rate(aios_http_requests_total[5m]))'
```

### Direct health checks
```bash
curl -fsS http://AIOS_HOST:8777/health/live
curl -fsS http://AIOS_HOST:8777/health/ready
```

### Backup freshness (artifact-based until metric exists)
```bash
ls -lt /data/backups/aios_*.sql.gz | head
find /data/backups -name 'aios_*.sql.gz' -mmin -1560 -print
# expect at least one recent file (<26h)
```

### Rule/config validation
```bash
# YAML syntax (repo has PyYAML)
.venv/bin/python - <<'PY'
import yaml,glob
for f in glob.glob('deploy/prometheus/**/*.yml', recursive=True):
    yaml.safe_load(open(f))
    print('OK', f)
PY

# promtool (if installed)
promtool check rules deploy/prometheus/rules/*.yml
promtool check config deploy/prometheus/alerts-scaffold.yml
```

## Gaps / Human Decisions
- Add status labels to `aios_http_requests_total` or dedicated error counter.
- Export queue lag/depth/oldest age metrics from worker/Redis.
- Export backup last-success timestamp/bool via textfile collector or cron wrapper.
- Define service owners, paging receivers, RTO/RPO, and error-budget policy.
- Add synthetic probes/blackbox checks for user-facing availability.
