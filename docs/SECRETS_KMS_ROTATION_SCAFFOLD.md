# Secrets / KMS / Rotation / Credential Handling — Scaffold

**Status:** scaffold/docs only. **No prod secrets, no prod infra, no code behavior change.**  
**Human-gated:** any KMS rollout, secret rotation, break-glass use, or env changes require named human owner approval + evidence.

## Scope

Covers AIOS secret inventory, KMS integration points, rotation procedure, break-glass, audit, env separation, and no-secrets-in-git checks. Current implementation is app-level encryption; external KMS/Vault is not wired in prod by this scaffold.

## Current state (code-observed)

| Area | Current behavior | Evidence |
|---|---|---|
| App secret encryption | `aios/core/secrets.py` uses Fernet key derived from `AIOS_ENCRYPTION_KEY`; falls back to `AIOS_JWT_SECRET` derivation for legacy rows. Missing encryption key for channel secrets fails closed. | `aios/core/secrets.py`, `aios/config.py:77` |
| JWT signing | HS256/Ed25519 config exists; rotation days config present. | `aios/config.py:71-78`, `aios/api/auth.py` |
| WhatsApp envelope/KMS scaffold | `aios/core/whatsapp/kms/envelope.py` uses local Fernet derived from `AIOS_WHATSAPP_VAULT_TOKEN` or `AIOS_JWT_SECRET`; exits if missing. `aios/core/whatsapp/config.py` has `vault_url`/`vault_token` placeholders. Dev compose includes `vault` service; no prod wiring. | `aios/core/whatsapp/kms/envelope.py`, `aios/core/whatsapp/config.py`, `docker-compose.yml` |
| Audit sink | Append-only hash-chained JSONL; optional mirror/WORM path envs. Tamper-evident, not tamper-proof against root/compromised account. | `aios/core/audit_sink.py`, `docs/SECURITY_RELIABILITY_HARDENING.md` |
| Secret rotation docs | Basic JWT/Postgres/Redis rotation and BFG guidance exists. | `docs/SECRET_ROTATION.md`, `docs/BFG_CLEANUP.md` |
| Deploy env | Secrets injected via Coolify/env/secret manager; compose requires strong passwords/JWT. | `docker-compose*.yml`, `docs/PRODUCTION_CONFIG.md`, `deploy/coolify-one-click.md` |

## Secret inventory template

Maintain a private, access-controlled inventory outside git. Template:

| Secret / credential | Purpose | Owner | Storage location | Prod env var / key name | Consumers | Rotation cadence | Last rotated (UTC) | Next due (UTC) | Break-glass allowed | Audit signal | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `<JWT signing secret/key>` | API auth tokens | `<human owner>` | `<secret manager>` | `AIOS_JWT_SECRET` / Ed25519 keys | app, worker, auth | `<=90d` or on incident | `<yyyy-mm-dd>` | `<yyyy-mm-dd>` | emergency only | auth failures, token invalidation | Rotation invalidates existing JWTs; plan user re-login |
| `<Admin master key>` | fleet/admin auth | `<human owner>` | `<secret manager>` | `AIOS_ADMIN_MASTER_KEY` | admin flows | `<=90d` / incident |  |  | emergency only | admin audit logs |  |
| `<At-rest encryption key>` | app secret/channel config encryption | `<human owner>` | `<secret manager/KMS>` | `AIOS_ENCRYPTION_KEY` | app, worker | planned, with re-encrypt migration |  |  | no routine break-glass | decrypt/encrypt errors | Legacy fallback to JWT derivation exists; rotation needs data migration plan |
| `<DB password/DSN>` | Postgres/Supabase auth | `<human owner>` | `<secret manager>` | `AIOS_DATABASE_URL` / `AIOS_SUPABASE_DATABASE_URL` / `POSTGRES_PASSWORD` | app, worker, migrations | `<=90d` / incident |  |  | emergency only | DB auth failures | Never print DSN/password |
| `<Redis password/URL>` | queue/cache auth | `<human owner>` | `<secret manager>` | `AIOS_REDIS_URL` / `REDIS_PASSWORD` | app, worker, redis | `<=90d` / incident |  |  | emergency only | Redis auth failures |  |
| `<Provider API keys>` | LLM/email/calendar/payments/etc. | `<human owner>` | `<secret manager>` | `AIOS_OPENROUTER_API_KEY`, `AIOS_RESEND_API_KEY`, `AIOS_CALCOM_API_KEY`, etc. | app/worker as configured | provider policy / incident |  |  | emergency only | provider 401/403, audit | Only configured providers; fail closed when missing |
| `<Webhook/HMAC secrets>` | inbound signature verification | `<human owner>` | `<secret manager>` | `AIOS_*_WEBHOOK_SECRET`, `EVOLUTION_API_KEY` where applicable | webhook endpoints | `<=90d` / incident |  |  | emergency only | signature failures | Keep verification fail-closed |
| `<S3/Storage creds>` | object storage | `<human owner>` | `<secret manager>` | `AIOS_S3_*` | app, worker | policy / incident |  |  | emergency only | storage auth errors | SSE/versioning per S3 hardening doc |

Do not copy real values into tickets, chat, logs, or git. Inventory may include secret IDs/ARNs/versions, never secret material.

## KMS integration points (scaffold)

| Integration point | Current | Target scaffold | Human-gated decision |
|---|---|---|---|
| App at-rest encryption | Fernet key from env (`AIOS_ENCRYPTION_KEY` or JWT-derived legacy) in `aios/core/secrets.py` | KMS-generated data key or KMS envelope encryption; app stores ciphertext + key metadata; decrypt via KMS with least-privilege IAM | KMS provider (AWS KMS/GCP KMS/Vault Transit), key hierarchy, region, IAM, latency budget, fallback policy |
| WhatsApp envelope | Local Fernet fallback in `aios/core/whatsapp/kms/envelope.py`; Vault URL/token config exists but not prod-wired | Vault Transit or cloud KMS for envelope encrypt/decrypt; key ID/versioned ciphertext; no local raw key in env | Vault/KMS availability, auth method (AppRole/workload identity), break-glass local key policy |
| Secret delivery | Env vars/Coolify secrets | Secret manager references/injection at deploy/runtime; short-lived where possible | Secret manager choice, access model, audit log export |
| DB credentials | Static DSN/password env | Managed rotation or dynamic DB creds where supported | Supabase/managed Postgres rotation support, app reconnect behavior |
| API keys / webhooks | Static env/config | Vaulted secrets with version metadata and rotation workflow | Provider rotation API support, dual-secret verification window |
| Audit/WORM | Local hash-chained JSONL + optional mirror path | Mirror to object-lock/WORM bucket or SIEM with immutable retention | Storage target, retention/legal hold, fail-open vs fail-closed mirror |

**Integration rule:** introduce KMS behind a narrow interface; keep fail-closed behavior for missing decrypt/encrypt capability; no silent plaintext fallback.

## Rotation procedure (human-gated)

### Preconditions

- Named human owner approves rotation window and rollback.
- Inventory updated with current secret version/location.
- Recent backup/restore confidence for affected data (see `docs/SECURITY_RELIABILITY_HARDENING.md`, `docs/business-os-runbook.md`).
- Monitoring/log access ready; oncall aware.
- No secret values written to git, tickets, or chat.

### Generic rotation flow

1. **Classify secret**: auth/session, at-rest encryption, DB, cache, provider API key, webhook secret, storage, integration.
2. **Plan compatibility window**:
   - Dual-accept if supported (old+new valid briefly).
   - For JWT secrets, expect session invalidation unless dual-verification implemented.
   - For encryption keys, plan re-encrypt/migration; do not rotate by overwriting key without migration path.
3. **Generate new secret in approved manager/KMS**. Record secret ID/version, not value.
4. **Stage in non-prod**. Run smoke tests and verify audit/log signals.
5. **Apply in prod during approved window**:
   - Update secret manager/Coolify env.
   - Redeploy/restart affected services only.
   - Verify `/health/ready`, auth, worker, affected integration.
6. **Revoke old secret** after verification window.
7. **Record evidence**: operator, UTC time, secret ID/version changed, services restarted, verification results, old secret revoked time.
8. **Post-rotation checks**: no elevated 401/403/5xx, no decrypt failures, no queue/auth failures.

### Secret-specific notes

| Secret | Rotation note |
|---|---|
| `AIOS_JWT_SECRET` | Existing JWTs invalid; communicate re-login. See `docs/SECRET_ROTATION.md`. |
| `AIOS_ENCRYPTION_KEY` | **High risk.** Current code supports legacy fallback from old JWT-derived key; changing to dedicated key or rotating dedicated key requires re-encryption plan for stored `enc:*`/`_secrets_enc` data. Human-gated migration required. |
| `AIOS_ADMIN_MASTER_KEY` | Rotate with admin owner; verify admin flows and audit. |
| DB/Redis passwords | Coordinate app/worker restart; verify migrations/jobs/queues. |
| Webhook secrets | Prefer provider dual-secret window; update verifier before sender cutover when possible. |
| Provider API keys | Create new key, deploy, verify, revoke old. Least privilege/scoped key. |
| Evolution API key | Rotate monthly policy exists in config/docs; update Coolify env and verify WhatsApp send/receive. |

## Break-glass procedure (human-gated)

Break-glass = emergency access/use of privileged secret recovery path. Default: **not used**.

- **Trigger:** Sev1 security incident, outage blocking recovery, or KMS/secret manager unavailable preventing critical restore.
- **Approvers:** named human owner + security/ops owner (two-person rule where possible).
- **Allowed actions:** retrieve emergency credential from approved sealed storage; temporary manual secret injection; controlled rollback.
- **Forbidden:** copying secrets to git/chat/tickets; sharing over unencrypted channels; disabling signature/encryption checks in prod without explicit incident approval.
- **Procedure:**
  1. Declare incident and open evidence log.
  2. Obtain two-person approval; record reason, scope, TTL.
  3. Use minimum-scope emergency credential/path; time-box access.
  4. Restore normal secret manager/KMS path ASAP.
  5. Rotate all exposed/emergency-used secrets after incident.
  6. Record audit: who/when/why/what accessed/what changed/verification/revocation.
- **Evidence:** incident ID, approvers, UTC timestamps, systems touched, secret IDs/versions rotated, post-incident review.

## Audit and monitoring

- **App audit:** security events go through `aios/governance/security.py` / audit sink where wired. Keep sink independent/WORM target human-gated.
- **Secret access audit:** enable secret manager/KMS audit logs; export to SIEM.
- **Minimum events to capture:** secret create/rotate/revoke/read (manager/KMS), failed decrypt/encrypt, webhook signature failures, admin auth/key use, DB/Redis auth failures, break-glass access.
- **Alerts:** repeated decrypt failures, signature failure spikes, unexpected secret reads, rotation overdue, mirror write failures.
- **No secret material in logs:** redact tokens/passwords/keys/DSN credentials. Review log formatters and exception paths.

## Environment separation

| Environment | Secret source | Rules |
|---|---|---|
| Local/dev | `.env` local only, dummy/test secrets | Never use prod secrets. `.env` must be gitignored. Prefer `.env.example` placeholders only. |
| Staging | Separate secret manager/Coolify project/env | Separate DB/Redis/KMS keys/providers where possible. No prod data unless approved and scrubbed. |
| Prod | Secret manager/Coolify secrets, least privilege | Human-gated changes, audit enabled, rotation schedule, break-glass documented. |

Checks:
- Prod and non-prod secrets/keys/DBs are different.
- Service accounts have least privilege per env.
- KMS key policies separate prod/staging decrypt rights.
- CI/CD cannot print secrets; masked variables only.

## No-secrets-in-git checks

### Preventive controls

- Keep `.env`, key files, dumps, and credential exports in `.gitignore`. Verify before commit.
- Never commit `.env.example` with real values; placeholders only.
- Use pre-commit secret scanning in dev/CI (human-gated rollout): `gitleaks protect --staged` or equivalent.
- Add CI secret scan on push/PR; fail closed on findings.

### Detection commands (safe, local)

```bash
# working tree + history scan (if gitleaks installed)
gitleaks detect --source . --no-banner --redact

# staged scan before commit
gitleaks protect --staged --no-banner --redact

# quick grep for obvious patterns (review false positives; do not paste matches externally)
git grep -nE '(AIOS_[A-Z_]*(SECRET|KEY|TOKEN|PASSWORD)|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|sk-[A-Za-z0-9]{20,}|whsec_[A-Za-z0-9]+)' -- .
```

### If secret leaked

1. **Contain:** revoke/rotate secret immediately (human-gated, incident record).
2. **Assess:** determine exposure window, systems, logs, artifacts.
3. **Clean:** remove from git history only with approved process (`git filter-repo`/BFG); coordinate force-push and all clones. See `docs/BFG_CLEANUP.md`.
4. **Verify:** rescan history; confirm old secret unusable.
5. **Document:** incident timeline, affected secrets, rotation evidence.

## Human-gated checklist

- [ ] Human owner named for secret inventory and rotation approvals.
- [ ] Secret inventory created in approved private location (no secrets in git).
- [ ] KMS/secret manager target selected; IAM/workload identity design reviewed.
- [ ] `AIOS_ENCRYPTION_KEY` rotation/migration plan approved before any key change.
- [ ] Dual-secret/dual-accept windows defined where supported.
- [ ] Break-glass approvers, sealed storage, TTL, and audit path defined.
- [ ] Secret manager/KMS audit logs exported to SIEM.
- [ ] No-secrets-in-git scanning enabled in pre-commit/CI.
- [ ] Staging rotation drill completed with evidence before prod rollout.
- [ ] Prod rotation/runbook evidence captured after each rotation.

## References

- `docs/SECRET_ROTATION.md`
- `docs/SECURITY_RELIABILITY_HARDENING.md`
- `docs/business-os-runbook.md`
- `docs/PRODUCTION_CONFIG.md`
- `docs/S3_SECURITY_HARDENING.md`
- `docs/BFG_CLEANUP.md`
- `aios/config.py`
- `aios/core/secrets.py`
- `aios/core/audit_sink.py`
- `aios/core/whatsapp/kms/envelope.py`
- `docker-compose.yml`, `docker-compose.coolify.yml`, `docker-compose.coolify.one-click.yml`
