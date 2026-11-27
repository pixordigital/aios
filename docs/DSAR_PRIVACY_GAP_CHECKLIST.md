# DSAR / Privacy Gap Checklist (Scaffold)

Status: **audit scaffold, docs-only**. No legal certification. No production data changes. Human-gated before implementation or production use.

## Scope

Covers DSAR export, deletion/anonymization, retention, consent/lawful basis tracking. Based on code inspection on 2026-11-27.

## Factual Current State

| Area | Exists | Paths | Notes |
|---|---|---|---|
| Processing registry model | Yes | `aios/governance/privacy.py` | `ProcessingActivity`, lawful bases, assessed bases, RIPD helper, deterministic `evaluate_processing`. |
| Privacy API | Partial | `aios/api/privacy.py` | Create/list activities, evaluate, create rights requests. No authz role gate beyond authenticated org scope; no list/get/update/fulfill DSAR workflow. |
| Rights request model | Partial | `aios/governance/privacy.py`, migration `alembic/versions/p8q9r0s1t2u3_privacy_governance.py` | `PrivacyRequest` has type/status/due/scope/evidence/rejection fields; no fulfillment execution, identity verification, or audit trail workflow. |
| Org export | Partial | `aios/api/gdpr.py` `GET /api/org/export` | Admin-gated, org-scoped. Exports org, agents, conversations, messages (capped 10000, `messages_truncated`), crm deals, channels. Excludes secrets. Not subject-scoped DSAR export; misses many PII stores. |
| Org erasure | Partial/risky for subject DSAR | `aios/api/gdpr.py` `DELETE /api/org` | Admin-gated, blocks `pixor/default`, FK-aware org subgraph delete. Org-wide only; no subject-level erasure/anonymization, no legal hold check, no backup/vendor/cache/vector/log handling. |
| Deletion targets list | Conceptual | `aios/governance/privacy.py` `deletion_targets()` | Lists crm/messages/transcripts/documents/rag_chunks/embeddings/caches/analytics_extracts/vendors; not wired to execution. |
| Consent/lawful basis tracking | Partial | `aios/governance/privacy.py`, `aios/api/privacy.py`, `aios/core/whatsapp/lgpd/consent.py`, `aios/api/whatsapp.py` | ProcessingActivity captures lawful basis/evidence/necessity/transfer/retention/status. WhatsApp STOP/opt-out stored as hashed phone in `Organization.extra_data.lgpd_consent`; not unified with ProcessingActivity/PrivacyRequest. No consent receipt table/audit trail. |
| Retention | Partial | `ProcessingActivity.retention_days`, `aios/db/models.py` `KnowledgeRecord.retention_until`, `aios/core/rag.py`, `aios/governance/knowledge.py` | Knowledge/RAG has retention expiry filter; no general retention enforcement/purge jobs across PII stores. |
| Tests | Partial | `tests/test_privacy_api.py`, `tests/test_privacy_governance.py` | Cover activity validation, deterministic evaluation, request creation. No DSAR fulfillment, subject export/delete, retention purge, consent lifecycle coverage. |
| Docs | Present | `docs/LGPD_COMPLIANCE_SCAFFOLD.md`, `docs/SECURITY_RELIABILITY_HARDENING.md` | Operational scaffold exists; needs validation against real behavior before external claims. |

## DSAR Gap Checklist

### A. Intake, Identity, Workflow
- [ ] **Human-gated**: define DSAR intake channels, identity verification, authority/proxy rules.
- [ ] Add PrivacyRequest list/get/update endpoints (org-scoped, role-gated, audited).
- [ ] Add status transitions: received/verifying/in_progress/completed/rejected/overdue with reason/evidence.
- [ ] Add identity verification evidence fields; never fulfill ambiguous requests automatically.
- [ ] Add assignee/owner, internal notes, communication log, due-date/SLA monitor.
- [ ] Add legal-hold/preservation flag; block deletion when hold active.

### B. Subject-Scoped Export / Portability
- [ ] **Human-gated**: define subject identifier canonicalization (email, phone, user_id, external_id, document) and matching rules.
- [ ] Inventory PII stores for export: users, memberships, invitations, conversations/messages, CRM deals/contacts/accounts, WhatsApp contacts/events/templates/connections as applicable, voice recordings/transcripts, documents/files/knowledge/RAG chunks/embeddings, agent knowledge/learnings/reflections/memory, audit/security logs where lawful, support tickets, vendor exports.
- [ ] Implement subject-scoped export service; avoid org-wide over-disclosure.
- [ ] Include export manifest: scope, systems checked, timestamp UTC, truncation/redaction, checksum.
- [ ] Keep secrets/tokens/credentials excluded; redact third-party personal data where required.
- [ ] Add secure delivery/expiry/access control for export artifacts.

### C. Deletion / Anonymization
- [ ] **Human-gated**: classify deletable vs legally retained data; define anonymization strategy per store.
- [ ] Implement subject-scoped erasure/anonymization workflow; do not reuse org-wide `DELETE /api/org` for subject requests.
- [ ] Cover derived data: RAG chunks, embeddings, caches, analytics extracts, search indexes, file/object storage, backups policy.
- [ ] Add vendor/processor deletion/suppression requests and confirmation evidence.
- [ ] Ensure transactional/auditable execution; record per-system result.
- [ ] Handle backup/legal-hold reality factually in DSAR responses; no false immediate-purge promise.

### D. Retention
- [ ] **Human-gated**: approve retention schedule per data category with legal/ops basis.
- [ ] Add retention metadata where missing; normalize `retention_days`/`retention_until` semantics.
- [ ] Implement scheduled purge/anonymization jobs with dry-run, audit, and tenant scoping.
- [ ] Include logs, exports, temp files, backups, vendor retention in policy.
- [ ] Add tests for retention expiry/purge behavior before enabling in prod.

### E. Consent / Lawful Basis
- [ ] **Human-gated**: map each processing purpose to lawful basis; counsel/DPO validation required.
- [ ] Unify WhatsApp consent/opt-out with privacy registry/request workflow where appropriate.
- [ ] Add consent receipt/evidence model: subject, purpose, granted/denied, timestamp, source, proof, version.
- [ ] Add ProcessingActivity approval workflow and evidence requirements; prevent `approved` without human review.
- [ ] Enforce `evaluate_processing` at real data-access/processing boundaries (fail closed for sensitive/new processing).
- [ ] Add transfer/vendor assessment fields and evidence links.

### F. Security / Audit / Verification
- [ ] Audit every DSAR/privacy action: who, when, org, subject scope, action, result, evidence.
- [ ] Add tests: subject export scope, deletion completeness, legal hold block, consent revocation, retention purge, cross-tenant denial.
- [ ] Add runbook for DSAR fulfillment and incident/legal signoff; keep `docs/LGPD_COMPLIANCE_SCAFFOLD.md` aligned with real controls.
- [ ] Verify metrics/alerts for overdue requests, failed deletions, export generation failures.

## Human-Gated Items

- Any production DSAR fulfillment behavior.
- Subject-level deletion/anonymization implementation and execution.
- Retention periods, legal hold, backup purge statements.
- Lawful basis, consent wording, transfer mechanisms, DPO/legal approvals.
- Vendor deletion contracts/processes.

## Suggested Safe Next Implementation Slices

1. **Read-only DSAR admin API**: list/get/update PrivacyRequest status/evidence, no data mutation. Add tests.
2. **Subject data inventory service**: dry-run locator returning stores/counts for a subject identifier, no export/delete.
3. **Export manifest v2**: extend org export metadata or create subject-scoped export artifact with explicit coverage/truncation.
4. **Retention dry-run report**: identify expired records by category; no deletion.
5. **Consent receipt model**: additive migration + API, no behavior change to existing flows.