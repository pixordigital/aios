# Security/LGPD Compliance — Operational Scaffold

> **Operational scaffold, not legal advice.** This document is a checklist/template pack for LGPD/privacy operations. It does **not** certify compliance, does **not** replace qualified Brazilian privacy/legal counsel, and does **not** authorize production data handling changes by itself. Human-gated items are marked **[HUMAN-GATED]**.

## Scope

- Docs/templates/checklists only. No production data changes.
- Grounded in current repo behavior; gaps called out explicitly.
- Related docs: [`docs/SECURITY_RELIABILITY_HARDENING.md`](./SECURITY_RELIABILITY_HARDENING.md), [`docs/business-os-runbook.md`](./business-os-runbook.md), [`docs/business-os-legal-boundaries.md`](./business-os-legal-boundaries.md), [`docs/AIOS_OPERATING_MODEL.md`](./AIOS_OPERATING_MODEL.md).

## Current Code/Doc State (reality check)

| Area | Current state | Gap / human decision |
|---|---|---|
| Processing registry | `aios/governance/privacy.py` defines `ProcessingActivity`; `POST/GET /api/privacy/activities`, `POST /api/privacy/evaluate` exist. Deterministic, fail-closed evaluation. | Registry entries need qualified privacy/legal review. API create supports subset of fields; full art. 37 record quality is operational process. |
| Data-subject requests | `PrivacyRequest` model + `POST /api/privacy/requests` creates request (`received`, due date). | No end-to-end fulfillment workflow, no assignment/verification/closure API, no evidence package generation, no subject-identity verification flow. **[HUMAN-GATED]** |
| Org export | `GET /api/org/export` exports org, agents, conversations, messages (capped/truncated), CRM deals, channel metadata; excludes channel secrets. | Org-level export, not a complete subject-scoped DSAR package across all stores. Truncation/coverage must be disclosed. **[HUMAN-GATED]** |
| Org erasure | `DELETE /api/org` owner/admin path deletes org subgraph by FK walk. | Org-level destructive erasure; protected orgs blocked. Not a selective subject erasure workflow. Backups/logs/legal holds/vendor copies need separate handling. **[HUMAN-GATED]** |
| Deletion targets | `aios/governance/privacy.py:deletion_targets()` lists `crm,messages,transcripts,documents,rag_chunks,embeddings,caches,analytics_extracts,vendors`. | List is declarative; not proven orchestrated across every store/vendor. Verify before claiming erasure coverage. |
| Retention | `ProcessingActivity.retention_days`, `KnowledgeRecord.retention_until`, CRM retention helper exists. | No unified retention schedule enforcement/report. Backup retention and legal hold process are operational. **[HUMAN-GATED]** |
| Security/privacy handoff | `SecurityIncident.personal_data_involved`, `require_privacy_handoff()`, security metrics/response endpoints. | Incident/legal/privacy signoff workflow is manual; notification duties require counsel/DPO decision. **[HUMAN-GATED]** |
| WhatsApp LGPD | `aios/core/whatsapp/lgpd/audit.py` has audit placeholder; runbook mentions DSR endpoints. | Verify actual endpoint implementation and WORM/audit persistence before relying on it. |

## 1) LGPD Data Map Template

Fill one row per processing activity/data store. Keep it factual; unknown = `UNKNOWN` (do not guess).

| Field | Template value | Owner | Evidence / code ref |
|---|---|---|---|
| Activity key | `example_activity` | Product/Eng/Privacy | `processing_activities.activity_key` |
| Business purpose | Why data is processed | Product | PRD/ticket |
| Data subjects | customer, lead, employee, user, visitor | Privacy/Legal |  |
| Personal data categories | name, email, phone, messages, identifiers, IP, etc. | Eng/Privacy | schema/API |
| Sensitive data? | yes/no/UNKNOWN | Privacy/Legal **[HUMAN-GATED]** |  |
| Children data? | yes/no/UNKNOWN | Privacy/Legal **[HUMAN-GATED]** |  |
| Source | webhook, user input, import, integration, generated | Eng |  |
| Systems/stores | Postgres tables, object storage, logs, cache, vector store, vendor | Eng | `aios/db/models.py`, infra |
| Legal basis | consent/contract/legal_obligation/legitimate_interest/... | Legal/DPO **[HUMAN-GATED]** | `aios/governance/privacy.py` |
| Legal basis evidence | contract, consent record, LIA doc, legal ref | Legal/DPO |  |
| Necessity/minimization | minimum fields needed | Privacy/Product |  |
| Retention | days/rule/trigger | Legal/Privacy **[HUMAN-GATED]** |  |
| Deletion/anonymization path | API/job/manual/vendor request | Eng |  |
| Recipients/vendors | processors/subprocessors/internal teams | Ops/Legal |  |
| International transfer? | yes/no/UNKNOWN; mechanism | Legal **[HUMAN-GATED]** |  |
| Security safeguards | RBAC, encryption, audit, backup, RLS plan | Security/Eng |  |
| DSAR route | export/correct/delete/object/info | Privacy/Ops |  |
| RIPD needed? | yes/no/UNKNOWN | Legal/DPO **[HUMAN-GATED]** |  |
| Owner / approver | name/role | Human owner |  |
| Status | draft/review/approved/suspended | Human owner |  |

### Suggested starting map (verify before use)

| Store / model | Likely personal data | Notes |
|---|---|---|
| `users`, `organization_memberships` | email, role, auth identifiers, TOTP metadata | Account/admin data. |
| `conversations`, `messages` | contact identifiers, message content, channel IDs, attachments metadata | High DSAR/export sensitivity; may include third-party personal data. |
| `crm_deals`, CRM accounts/contacts | lead name/email/phone, deal data | Commercial records; retention/legal hold possible. |
| `whatsapp_contacts`, WhatsApp message/transcript stores | phone, profile, message content, media refs | Verify actual WhatsApp tables/endpoints in deployment. |
| `voice_recordings` | phone numbers, audio URL/path, transcript | Sensitive content possible; retention/access controls critical. |
| `audit_logs`, security events, dead letters | actor IDs, payload snippets, operational metadata | Minimize personal data in logs; define retention. |
| `knowledge_records`, RAG chunks/embeddings | ingested content may contain personal data | Provenance and deletion propagation must be verified. |
| Backups/object storage/vendor systems | copies of above | Not covered by app-level delete alone. **[HUMAN-GATED]** |

## 2) DPO/Owner Checklist

Assign named humans. No agent owns legal accountability.

- [ ] **[HUMAN-GATED]** Name accountable business owner (final approver).
- [ ] **[HUMAN-GATED]** Name privacy owner/DPO/encarregado-equivalent contact, as applicable to org structure and counsel guidance.
- [ ] **[HUMAN-GATED]** Define escalation path: Privacy, Security, Legal, Engineering, Support, Founder/Owner.
- [ ] **[HUMAN-GATED]** Publish internal contact route for DSARs and incidents; test it.
- [ ] [ ] Inventory processing activities in `ProcessingActivity` registry and keep versioned evidence.
- [ ] [ ] Review lawful bases and sensitive-data assessments with qualified counsel.
- [ ] [ ] Confirm vendor/subprocessor list, contracts, DPAs/addenda, and transfer mechanisms.
- [ ] [ ] Define retention schedule and legal-hold override process.
- [ ] [ ] Define DSAR identity verification, response SLA, and evidence capture.
- [ ] [ ] Define incident severity, privacy handoff, and notification decision workflow.
- [ ] [ ] Train operators on "no guess, no unauthorized disclosure, escalate when uncertain".
- [ ] [ ] Schedule periodic review (quarterly or after material system change).

## 3) Lawful Basis Register Template

One row per activity/purpose. Legal basis selection requires qualified review.

| Activity key | Purpose | Data categories | Subjects | Lawful basis | Evidence doc/ref | Sensitive data assessment | Necessity/minimization | Opt-out/objection route | Transfer mechanism | Owner | Approved by | Approved at | Review date | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `lia_outreach` | example only | name, email, phone | leads | legitimate_interest **[HUMAN-GATED]** | LIA doc | N/A or assessment | minimal fields | opt-out list/process | N/A | name | legal/privacy | date | date | draft |

Rules from code (`evaluate_processing`): cross-tenant denied; missing/unapproved activity denied; missing policy on sensitive denied; purpose mismatch restricted; `legitimate_interest` needs evidence and cannot ground sensitive data; opt-out blocks outreach/market/communicate; legal hold blocks delete; transfer without mechanism requires approval; missing necessity requires approval.

## 4) DSAR / Export / Delete Procedure

### Intake and triage

1. **Receive request** through approved channel. Record request type: access, correction, deletion, portability, objection, information.
2. **Create tracking record**: `POST /api/privacy/requests` (or equivalent internal ticket). Capture subject identifier, scope, received time, due date.
3. **Identity verification [HUMAN-GATED]** before disclosing or changing personal data. Do not fulfill on unverified identity.
4. **Scope check [HUMAN-GATED]**: confirm tenant/org, subject identifiers, systems, legal exceptions, legal holds, contractual/legal retention duties.
5. **Assign owner** and log evidence.

### Export / access / portability

- Current org-level export endpoint: `GET /api/org/export` (authenticated, org-scoped). Returns org, agents, conversations, messages, CRM deals, channel metadata; secrets excluded; messages may be truncated.
- **Gap:** not subject-scoped across all stores/vendors. For subject DSAR, human/operator must define scope and verify completeness. **[HUMAN-GATED]**
- Package should include: request record, identity verification evidence, systems searched, export artifact checksum, redactions applied, omissions/truncation, legal basis for any refusal/redaction.

### Correction / objection / information

- No generic automated correction workflow documented here. Route to system owner; apply least-privilege change; log before/after evidence where lawful.
- Objection/opt-out: enforce in outreach/processing gates and vendor propagation where applicable. **[HUMAN-GATED]**

### Deletion / erasure

- Current org-level erasure endpoint: `DELETE /api/org` (admin/org_admin/superadmin; protected orgs blocked). Deletes org subgraph by FK walk.
- **Gap:** destructive org action, not selective subject erasure. Do not use as subject DSAR delete without legal/privacy approval. **[HUMAN-GATED]**
- Before any erasure: confirm identity, scope, legal hold, contractual/regulatory retention, backup impact, vendor deletion duties.
- After erasure: record tables/systems affected, vendor requests, backup disposition/expiry, residual data justification, completion evidence.

### DSAR response checklist

- [ ] Request logged with ID, type, received_at, due_at, owner.
- [ ] Identity verified. **[HUMAN-GATED]**
- [ ] Legal hold/exception checked. **[HUMAN-GATED]**
- [ ] Systems/vendors searched per data map.
- [ ] Action completed or lawful refusal documented.
- [ ] Evidence package stored in approved secure location.
- [ ] Request status updated and requester notified per approved process. **[HUMAN-GATED]**

## 5) Retention Schedule Template

Define retention by data class, not ad hoc. Legal review required.

| Data class | System/store | Retention rule | Trigger | Legal hold override | Delete/anonymize method | Owner | Review date |
|---|---|---|---|---|---|---|---|
| Account/admin records | users, memberships, org | TBD | contract end / account closure | yes | app delete/anonymize + backup expiry | Ops/Legal |  |
| Conversations/messages | conversations, messages, dead letters | TBD | last activity / request | yes | targeted delete/export review | Product/Legal |  |
| CRM/leads | crm_deals, contacts/accounts | TBD | inactivity / contract / objection | yes | delete/anonymize/vendor sync | Sales/Legal |  |
| Voice/transcripts | voice_recordings, storage | TBD | call age / purpose complete | yes | delete file + DB row + transcript | Ops/Legal |  |
| Security/audit logs | audit_logs, security events, sink/WORM | TBD | event age | possible legal/security hold | rotate/purge per policy | Security/Legal |  |
| Knowledge/RAG | knowledge_records, embeddings, chunks | TBD | retention_until / source removal | yes | delete source + derived vectors | Eng/Privacy |  |
| Backups | DB/object backups | TBD | backup age | restore/legal hold exception | expiry/destruction per backup policy | Infra/Security |  |

## 6) Incident / Legal Signoff Checklist

Use with `docs/SECURITY_RELIABILITY_HARDENING.md` and security incident flow.

### Triage

- [ ] Incident recorded (`/api/security/incidents` or incident process).
- [ ] Severity classified; `personal_data_involved` set accurately.
- [ ] If personal data involved, trigger privacy handoff (`require_privacy_handoff` / human Privacy owner). **[HUMAN-GATED]**
- [ ] Contain: disable affected automation/integration, revoke credentials, isolate systems as needed.

### Legal/privacy assessment

- [ ] **[HUMAN-GATED]** Privacy/legal counsel assesses whether incident is a security incident with potential personal-data impact requiring regulator/subject notification under applicable law.
- [ ] **[HUMAN-GATED]** Determine affected tenants/subjects, data categories, volume, likelihood/severity of harm, and mitigation.
- [ ] **[HUMAN-GATED]** Decide notification duties, deadlines, content, and responsible sender. Do not guess deadlines.
- [ ] **[HUMAN-GATED]** Preserve evidence; avoid destructive cleanup before legal/security approval.

### Signoff record

| Item | Value |
|---|---|
| Incident ID |  |
| Detected at (UTC) |  |
| Contained at (UTC) |  |
| Personal data involved | yes/no/unknown |
| Data categories |  |
| Tenants/subjects affected (count/scope) |  |
| Root cause summary |  |
| Containment/remediation actions |  |
| Privacy owner signoff | name/date/decision |
| Legal signoff | name/date/decision |
| Regulator notification required? | yes/no/pending counsel **[HUMAN-GATED]** |
| Subject notification required? | yes/no/pending counsel **[HUMAN-GATED]** |
| Communications approved by |  |
| Evidence package location |  |
| Postmortem / corrective actions |  |

## 7) Operational Commands / Checks (safe)

```bash
# Inspect privacy/governance code anchors
grep -rn "ProcessingActivity\|PrivacyRequest\|deletion_targets\|evaluate_processing" aios/governance/privacy.py aios/api/privacy.py

# Inspect GDPR/org export+delete paths
grep -rn "def export_org\|def delete_org" aios/api/gdpr.py

# Run focused privacy tests (venv)
.venv/bin/pytest -q tests/test_privacy_governance.py tests/test_privacy_api.py
```

Do not run destructive export/delete endpoints against production data without approved change window, verified scope, backup/rollback plan, and human signoff.

## Change Log

- 2026-11-27: Initial operational scaffold created (docs-only). No legal certification claimed.