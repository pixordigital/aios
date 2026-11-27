# Security/Reliability Hardening — Gaps, Scaffolds, Runbooks

Scope: code/docs/tests hardening only. No infra/prod changes. Human-gated for prod.

Related scaffold: `docs/SECRETS_KMS_ROTATION_SCAFFOLD.md` (secret inventory/KMS integration points/rotation/break-glass/audit/env separation/no-secrets-in-git; human-gated).

## 1) Audit sink independence / WORM

**Current state**
- `aios/core/audit_sink.py` writes append-only hash-chained JSONL locally, fsynced, verified by `read()`.
- Tamper-evident, not tamper-proof against root or compromised service account.
- `aios/governance/security.py:record_security_event` best-effort mirrors allowlisted security fields to sink; mirror failure never raises.
- Worker telemetry flush uses `mirror_telemetry()`.

**Hardening added (code)**
- Pluggable sink interface: `AuditSink.emit(record)->ack`, `emit_event` alias, local hash-chain sink default.
- Optional external stub sinks (no vendor SDK/creds/network): `AIOS_AUDIT_SINK_EXTERNAL_KIND=webhook_stub|file_queue_stub`, `AIOS_AUDIT_SINK_EXTERNAL_TARGET=<url|dir>`.
- Legacy external mirror path preserved: `AIOS_AUDIT_SINK_MIRROR_PATH`.
- Strict fail-closed: `AIOS_AUDIT_SINK_REQUIRED=1` makes configured external stub failures raise `AuditChainError` before primary append. `AIOS_AUDIT_SINK_MIRROR_REQUIRED=1` preserves legacy mirror strict behavior. Default remains best-effort unless strict configured.
- `append(..., mirror_path=...)` and `mirror_telemetry(..., mirror_path=...)` accept explicit paths for tests/controlled callers.

**Recommended WORM deployment (human-gated)**
1. Mount immutable/object-lock-backed path (S3 Object Lock, WORM NFS, append-only volume with vendor guarantees).
2. Set `AIOS_AUDIT_SINK_MIRROR_PATH=/mnt/audit-worm/telemetry.jsonl`.
3. Decide fail mode with owner/security:
   - availability-first: `AIOS_AUDIT_SINK_MIRROR_REQUIRED=0` (default) + alert on mirror warnings.
   - compliance-first: `AIOS_AUDIT_SINK_MIRROR_REQUIRED=1` (can block audited writes/events depending call path; validate before prod).
4. Forward sink to SIEM/S3 Object Lock pipeline; keep source-of-truth ownership explicit.
5. Verify: append record, confirm mirror file has identical line/hash, rotate/retention controlled by storage policy.

**Residual risk / blockers**
- Local sink alone is not independent/WORM. External mirror path is only as strong as target storage controls.
- `record_security_event` catches mirror exceptions and logs warning; required-mirror semantics should not be enabled for this path without separate product decision, because it can create denial/audit coupling.
- No out-of-band signature/KMS signing yet. Human decision: local tamper-evident acceptable vs external signed/WORM required.

## 2) Postgres RLS scaffold

**Current state**
- App-level org scoping is widespread (`org_id` FKs/indexes, deps checks). No Postgres RLS policies in Alembic by default.
- `aios/api/deps.py` enforces org presence; not DB-enforced row isolation.
- Optional DB-session org-context wiring exists in code, disabled by default.

**Hardening added (scaffold migration, fail-safe)**
- `alembic/versions/h5i6j7k8l9m0_rls_scaffold_optional.py`
- Default NO-OP. Applies only when:
  - dialect is PostgreSQL, and
  - `AIOS_APPLY_RLS_SCAFFOLD=1` set during migration.
- Enables/FORCEs RLS + `org_id = current_setting('app.current_org_id', true)` policy on key org-scoped tables.
- Downgrade removes policies/disables RLS only when same env flag set.

**Hardening added (app wiring, fail-safe, default off)**
- `AIOS_RLS_CONTEXT_ENABLED` (default `false`) gates DB-session org context.
- `aios/db/rls.py`: task-scoped org context (`contextvars`) + `apply_rls_org_context(session, org_id=None)`.
  - No-op when disabled.
  - No-op on SQLite/non-Postgres dialect.
  - No-op when org id missing.
  - On Postgres+enabled+org present: executes parameterized `SELECT set_config('app.current_org_id', :org_id, true)` (transaction-local).
- `aios/main.py` `rls_middleware` sets/resets task-scoped org context for authenticated API requests after resolving `request.state.org_id`.
- `aios/db/backends/sqlalchemy_backend.py` applies RLS context once per session lifecycle before first DB operation.
- `aios/db/backend.py` `db_session(org_id=...)` accepts explicit org id for guarded/background paths that cannot rely on request middleware.

**Not enabled by default because**
- Missing/incorrect setting can deny reads/writes or cause outages when RLS is enabled.
- Needs full table coverage audit, role ownership review, background jobs/service-role behavior review.
- System/background jobs must pass explicit org context or run with reviewed bypass strategy.

**Exact rollout steps (human-gated)**
1. **Inventory coverage**: confirm every org-scoped table/view/materialized path has `org_id` and policy coverage; extend `ORG_SCOPED_TABLES` in scaffold migration as needed.
2. **Stage deploy code first**: deploy app with `AIOS_RLS_CONTEXT_ENABLED=false` (default). Verify normal behavior.
3. **Enable context wiring in staging**: set `AIOS_RLS_CONTEXT_ENABLED=true` in staging only. Do NOT enable RLS policies yet. Verify logs/metrics and no regressions; confirm Postgres sessions issue `set_config` only when org present.
4. **Apply scaffold in staging DB**: run migration with `AIOS_APPLY_RLS_SCAFFOLD=1` on staging Postgres. Keep app flag on.
5. **Smoke staging with real orgs**: login, dashboard, API reads/writes, worker jobs, webhooks/integrations. Confirm cross-org isolation and no denied-query spikes.
6. **Guard background/system paths**: for non-request jobs touching RLS-protected tables, pass explicit `db_session(org_id=...)` or set/reset `aios.db.rls.set_rls_org_id` around work. Document any audited bypass role separately.
7. **Prod rollout**: repeat 2-6 in production during low traffic. Prefer table-by-table/policy rollout only after full coverage review; current scaffold is all-or-nothing per listed table set.
8. **Rollback**: disable app flag `AIOS_RLS_CONTEXT_ENABLED=false`; if policies applied and causing outage, run downgrade with `AIOS_APPLY_RLS_SCAFFOLD=1` during controlled window. Validate app recovery.
9. **Post-rollout checks**: monitor DB errors for `permission denied`/RLS policy failures, audit logs, and cross-tenant probes. Keep evidence.

## 3) Backup/restore drills

**Current state**
- `deploy/backup.sh` and `scripts/backup.sh` exist; business-os runbook has backup/restore section but not full drill procedure/evidence capture.
- Deploy doc has migration/restore notes.

**Hardening added (docs)**
- This doc defines drill procedure, commands, verification, evidence fields, RPO/RTO capture.
- See also `docs/business-os-runbook.md` updates below.

## Backup/Restore Drill Procedure (safe, isolated)

**Never run restore drill against production DB.**

### Preconditions
- Human owner approval.
- Isolated target: local docker Postgres or staging DB with throwaway database name.
- Recent backup artifact + checksum.
- Known migration head / app commit.

### Drill steps
1. **Select artifact**
   - `ls -lh /data/backups/aios_*.sql.gz | tail`
   - Record file, size, mtime, SHA256.
2. **Integrity check**
   - `sha256sum <file>`
   - `gzip -t <file>`
3. **Restore to isolated DB**
   - `createdb aios_restore_drill` (or dockerized psql)
   - `gunzip -c <file> | psql "$AIOS_RESTORE_DATABASE_URL"`
4. **Migrate to expected head (if needed)**
   - `AIOS_DATABASE_URL="$AIOS_RESTORE_DATABASE_URL" .venv/bin/alembic upgrade head`
   - `AIOS_DATABASE_URL="$AIOS_RESTORE_DATABASE_URL" .venv/bin/alembic current`
5. **App-level smoke (isolated)**
   - `AIOS_DATABASE_URL="$AIOS_RESTORE_DATABASE_URL" .venv/bin/python -c "from aios.db.engine import ..."` or run minimal app health checks.
   - Verify critical tables/counts: orgs, users, agents, conversations, messages, audit_logs.
6. **Data checks**
   - Row counts vs backup metadata/expected range.
   - Spot-check latest records, tenant isolation, recent migrations present.
7. **Evidence log**
   - date/time UTC, operator, backup file, checksum, restore target, restore duration, migration result, smoke result, row counts, RPO observed, RTO observed, issues, sign-off.
8. **Cleanup**
   - Drop isolated restore DB after evidence captured.

### Suggested verification commands
```bash
# artifact
sha256sum /data/backups/aios_YYYYMMDD_HHMMSS.sql.gz
gzip -t /data/backups/aios_YYYYMMDD_HHMMSS.sql.gz

# isolated restore (example)
createdb aios_restore_drill
gunzip -c /data/backups/aios_YYYYMMDD_HHMMSS.sql.gz | psql postgresql://user:pass@localhost:5432/aios_restore_drill

# migration/head
AIOS_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/aios_restore_drill .venv/bin/alembic upgrade head
AIOS_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/aios_restore_drill .venv/bin/alembic current

# minimal smoke
AIOS_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/aios_restore_drill .venv/bin/python - <<'PY'
import asyncio, sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
async def main():
    e=create_async_engine('postgresql+asyncpg://user:pass@localhost:5432/aios_restore_drill')
    async with e.connect() as c:
        for t in ['organizations','users','agents','conversations','messages','audit_logs']:
            r=await c.execute(sa.text(f'select count(*) from {t}'))
            print(t,r.scalar())
    await e.dispose()
asyncio.run(main())
PY
```

## 4) SLO/oncall/DR gaps (documented, human-gated)

- No SLO definitions enforced in repo; add service SLOs + error budget policy (owner/SRE decision).
- Oncall/escalation not encoded; define rotation, paging, Sev1-3 ownership, ack/mitigate timelines.
- DR: backups exist, restore drills not proven. Require periodic drill evidence.
- Prometheus rules exist under `deploy/prometheus/` but coverage/alert routing/oncall integration needs human verification.

## 5) LGPD/compliance operational scaffold (docs-only)

- Scaffold/template: [`docs/SECURITY_LGPD_COMPLIANCE.md`](./SECURITY_LGPD_COMPLIANCE.md) — data map template, DPO/owner checklist, lawful basis register, DSAR/export/delete procedure, retention schedule, incident/legal signoff checklist.
- Operational runbook cross-link: [`docs/business-os-runbook.md`](./business-os-runbook.md) (backup/restore, incident response, human owner).
- Human-gated: qualified legal/DPO review, identity verification, lawful basis/RIPD decisions, retention/legal hold, vendor terms, regulator/subject notifications. No legal certification claim. No production data changes.

## Checklist

- [x] Inspect audit sink, migrations, backup scripts, prometheus, runbooks.
- [x] Add optional external/WORM mirror hook/env + warnings in audit sink.
- [x] Add optional Postgres RLS scaffold migration (fail-safe no-op by default).
- [x] Add backup restore drill procedure + verification commands.
- [x] Add/adjust audit sink tests.
- [ ] Run targeted tests in venv.
- [ ] Human-gated: choose WORM/independent sink target, enable RLS with app session wiring, execute real restore drill, define SLO/oncall/DR ownership.
