# Business Readiness Status

Snapshot: 2026-11-27 (local workspace audit, read-only except this doc).  
Verdict: **not fully autonomous / not business-ready for unattended real-world side effects yet**. Current state is code-gated and fail-closed in key areas, but rollout requires human-gated credentials, approvals, deploy verification, and unresolved worktree/release hygiene.

## Scope / evidence

- Repo: `/home/pixor/ai_projects/claude_projects/pixor_aios`
- Branch/HEAD: `main` @ `7738d5b` (`git rev-parse --short HEAD`, `git branch --show-current`)
- Worktree: **dirty/heavy** — `git status --short | wc -l` = `102` entries (45 tracked modified, 57 untracked including new finance/execution/approval/idempotency/RLS code, migrations, tests, docs).
- Alembic heads: single head `j7k8l9m0n1o2 (head)` parent `i6j7k8l9m0n1` (`.venv/bin/alembic heads --verbose`). Local SQLite was upgraded to `j7k8l9m0n1o2` per `pendingwork.md`; prod Postgres not verified by this audit.
- No code behavior changes made by this report.

## Implemented now (code-gated / fail-closed)

| Area | Current state | Evidence |
|---|---|---|
| Business execution registry | Fail-closed adapter execution: adapter must be configured+approved; side effects require idempotency key; org scope required by default; duplicates replay/don't re-execute; stale processing fails closed. | `aios/core/business_execution.py` (`ExecutionDenied`, `ExecutionRegistry.execute`, idempotency claim/replay/stale handling) |
| Controlled execution service | Approval comes only from settings/config; no caller self-approval. Durable idempotency preferred; missing durable store fails closed when required; explicit dev/test opt-out via `AIOS_BUSINESS_IDEMPOTENCY_REQUIRED=false`. | `aios/core/business_execution_service.py` (`build_controlled_business_registry`, `execute_controlled_business_action`, `get_business_idempotency_store`) |
| Adapter registry | Registered adapters: `crm_internal`, `whatsapp_evolution`, `email_resend`, `calendar_calcom`, `calendar_google`, `fulfillment_service`, `billing_stripe`. Approval only via explicit config flags/CSV; missing config marks missing and keeps unapproved. Stripe sandbox-only stub, fail-closed unless approved+configured+sandbox. | `aios/core/adapters/registry.py` |
| Execution config flags | Default deny: `execution_approved_adapters=""`, all `execution_adapter_*_approved=false`, `business_idempotency_required=true`, `stripe_sandbox_mode=false`. Billing commercial surface default off: `billing_enabled=false`. | `aios/config.py` |
| Internal execution API | Authenticated org-scoped endpoint `/api/internal/business-execution/execute`; payload `org_id` must match auth org; caller cannot self-approve; denial maps to 403. | `aios/api/business_execution.py`, router include in `aios/api/router.py` |
| Action policy / HITL taxonomy | Central action classification; unknown/dynamic tools fail closed as approval-required; money/PII/legal/bulk/destructive/prod publish/routine side effects require approval; external commitments approval-required in production-sensitive contexts. | `aios/core/action_policy.py`, `aios/core/business_hitl_policy.py` |
| Approval evidence | DB-backed approval verify+consume, atomic CAS consume prevents replay/races; checks org, status approved, decided_by, consumed, tool/args/fingerprint, optional expiry. | `aios/core/approval_evidence.py` |
| Business idempotency durability | DB-backed idempotency store with atomic claim, replay, stale-processing reclaim path; migration present. | `aios/core/business_idempotency.py`, `alembic/versions/i6j7k8l9m0n1_business_idempotency.py` |
| Finance SOR (minimal internal) | Read/list/get plus guarded approval-gated posting/reconciliation endpoints; org-scoped, fail-closed validation, no external provider/money movement. | `aios/core/finance_sor.py`, `aios/api/finance_sor.py`, `alembic/versions/g4h5i6j7k8l9_finance_sor_minimal.py` |
| RLS scaffold | Optional Postgres RLS scaffold migration fail-safe no-op unless `AIOS_APPLY_RLS_SCAFFOLD=1`; app DB-session org context wiring exists, default off `AIOS_RLS_CONTEXT_ENABLED=false`. | `alembic/versions/h5i6j7k8l9m0_rls_scaffold_optional.py`, `aios/db/rls.py`, `docs/SECURITY_RELIABILITY_HARDENING.md` |
| Audit sink hardening | Local append-only hash-chained JSONL; optional external mirror path and optional fail-closed mirror flag; security-event mirror best-effort. Tamper-evident, not WORM by itself. | `aios/core/audit_sink.py`, `docs/SECURITY_RELIABILITY_HARDENING.md` |
| Billing commercial surface | Fail-closed by default; API/dashboard billing not mounted/exposed unless `AIOS_BILLING_ENABLED=true`. Stripe adapter is sandbox stub and separately gated. | `aios/api/billing.py`, `aios/api/router.py`, `tests/test_billing.py`, `aios/config.py` |
| Operational runbook | Business OS runbook covers onboarding, HITL, backup/restore drill, deploy/smoke, incident response, human owner accountability. | `docs/business-os-runbook.md` |

## Missing / not ready for unattended autonomy

| Gap | Why it blocks readiness | Owner/gate |
|---|---|---|
| Dirty/unreleased worktree | 102 changed/untracked paths; includes migrations/code/docs/tests not committed/pushed/deployed. Cannot claim prod readiness from local tree. | Engineering + release owner |
| Prod migration verification | Local Alembic head advanced; prod Postgres migration/head/smoke not verified in this audit. | Deploy/operator, human-gated |
| Real adapter credentials/config | All execution adapters default unapproved/missing config. No real Resend/Cal.com/Google/Stripe/Evolution/fulfillment credentials validated here. | Human/operator; secret manager |
| Durable idempotency in prod | DB idempotency store required by default; prod DB connectivity/table presence and worker behavior must be verified. | Deploy/operator |
| Approval/HITL operational wiring | Policy/evidence primitives exist, but real business flows need approved operators, approval UI/process, escalation, and audited decision ownership. | Product/ops/legal/human owner |
| RLS rollout | Scaffold exists but default off; enabling without full coverage/session wiring/background job audit can cause outage or false confidence. | DBA/security/human-gated |
| Independent/WORM audit sink | Local sink is tamper-evident only; external WORM/signed sink and fail-mode decision not configured. | Security/compliance owner |
| Backup/restore drill evidence | Procedure documented; no fresh restore drill evidence captured in this audit. | Ops/SRE, human-gated |
| SLO/oncall/DR ownership | Gaps documented, not closed. | SRE/org owner |
| End-to-end business loop proof | No real sandbox->controlled live proof in this audit for money/external commitments with human approvals, receipts, and rollback. | Product/QA/ops |
| Security/secret rotation & prod checks | Pendingwork lists token rotations, TLS/secrets/provider re-verify, LGPD/sign-offs, Founder activation, etc. | Human-gated |

## Human-gated decisions / credentials

- **Approve release scope**: decide which of 102 worktree items ship together; exclude unrelated/experimental changes.
- **Production deploy authorization**: push/deploy only after focused CI/tests and migration review.
- **Adapter approvals & secrets**: provide/rotate credentials in secret manager; explicitly set approved adapters only for intended sandbox/live scope.
- **Idempotency mode**: keep `AIOS_BUSINESS_IDEMPOTENCY_REQUIRED=true` in prod; any opt-out is dev/test only.
- **HITL ownership**: name human owner for money/external/legal/destructive actions; define approval SLA/escalation.
- **RLS enablement**: decide if/when to set `AIOS_RLS_CONTEXT_ENABLED` and apply `AIOS_APPLY_RLS_SCAFFOLD=1`; audit background jobs/service-role paths first.
- **Audit sink target**: choose local-only vs external mirror vs WORM; decide `AIOS_AUDIT_SINK_MIRROR_REQUIRED` behavior.
- **Billing exposure**: keep `AIOS_BILLING_ENABLED=false` unless commercial lifecycle/Stripe secrets/webhooks/support are ready.
- **Legal/compliance**: LGPD, contracts, Founder activation, Slack migration/data handling decisions remain human-gated.

## Verification evidence (commands/results)

| Command | Result (this audit) |
|---|---|
| `git status --short` | 102 entries; dirty/untracked wave present. |
| `git rev-parse --short HEAD && git branch --show-current` | `7738d5b`, `main`. |
| `.venv/bin/alembic heads --verbose` | single head `j7k8l9m0n1o2`, parent `i6j7k8l9m0n1`. |
| `git diff --check` | clean (no whitespace/conflict markers). |
| `AIOS_DATABASE_URL=sqlite+aiosqlite:////tmp/opencode/aios_test_readiness.db AIOS_BUSINESS_IDEMPOTENCY_REQUIRED=false .venv/bin/python -m pytest -q tests/test_audit_sink.py tests/test_billing.py tests/test_action_policy.py tests/test_business_execution.py tests/test_business_execution_api.py tests/test_business_execution_controlled.py tests/test_adapters_registry.py tests/test_approval_evidence.py tests/test_side_effect_hardening.py` | **env-limited**: `1 passed, 1 warning, 68 errors in 257.20s`; errors dominated by SQLAlchemy/SQLite disk I/O during fixture setup in this sandbox, not asserted functional failures. |
| `AIOS_DATABASE_URL=sqlite+aiosqlite:////tmp/opencode/aios_test_readiness2.db AIOS_BUSINESS_IDEMPOTENCY_REQUIRED=false .venv/bin/python -m pytest -q tests/test_business_scope_guards.py tests/test_rls_context.py tests/test_finance_sor_service.py` | **env-limited**: `1 warning, 23 errors in 107.99s`; same SQLite disk I/O setup errors. |
| Readiness subset (2026-11-27, this pass) | `30 passed, 1 warning in 329.64s` for `tests/test_business_execution_controlled.py tests/test_finance_sor_models.py tests/test_action_policy.py tests/test_approval_evidence.py`. | shell `sh_21f166b2e001UyygWqcD6SKHl5` |
| Broader readiness suite (2026-11-27, this pass) | **3 failed, 101 passed, 1 skipped, 7 warnings in 933.81s**. Failures: `tests/test_finance_sor_api.py::test_finance_sor_api_post_ledger_requires_approval_and_posts`, `::test_finance_sor_api_post_ledger_fail_closed`, `::test_finance_sor_api_mark_reconciliation_requires_approval`. Tracebacks not captured (`--tb=no`); rerun these 3 with `-vv` before ship. | shell `sh_21f13bda3001xetlu97ItZICOj` |
| Prior repo evidence | `pendingwork.md` records recent targeted green runs for related slices/migrations; treat as historical, re-run in clean CI/dev env before release. |

## Safe rollout order

1. **Freeze scope**: split dirty tree into reviewable commits/waves; exclude generated/noise (`graphify-out/` unless intentionally updated) and unrelated experiments.
2. **Green verification in clean env**: run focused pytest suites for execution/adapters/approval/idempotency/finance/RLS/audit/billing; confirm Alembic upgrade path on disposable Postgres.
3. **Stage deploy with defaults fail-closed**: keep `billing_enabled=false`, all execution adapters unapproved, `business_idempotency_required=true`, RLS scaffold off.
4. **Migrate staged DB**: backup, `alembic upgrade head`, verify `/health/ready` and migration head.
5. **Sandbox adapter smoke**: enable one adapter at a time in sandbox with explicit approval/config + idempotency + audit evidence; no real money movement.
6. **HITL drill**: exercise approval-required path (approve/deny/replay/consume) with named human owner and audit trail.
7. **Backup/restore drill**: isolated restore, migration, smoke, evidence log; no prod restore.
8. **Security/compliance gates**: secret rotation, TLS/provider re-verify, audit sink target/WORM decision, RLS decision, LGPD/legal sign-off.
9. **Controlled production canary**: minimal approved scope, monitoring/oncall, rollback plan, human owner accountable. No unattended autonomy claim until gates closed with evidence.
