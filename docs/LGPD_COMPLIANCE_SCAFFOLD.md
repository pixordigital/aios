# LGPD Compliance Scaffold — Operational (Docs/Templates)

Status: **scaffold/template only**. No legal certification claim. Human-gated before production use.

Scope: docs/templates for LGPD operational readiness. No production data changes. No code behavior changes.

## Guardrails

- **Not legal advice/certification**: validate with qualified Brazilian privacy counsel/DPO before relying on any item here.
- **Human-gated**: owner/DPO/legal must approve policy, lawful basis, retention, DSAR responses, vendor terms, incident disclosures, and production rollout.
- **Truth over promise**: only claim controls that exist in code/config/evidence. Mark gaps explicitly.
- **Evidence first**: every completed item needs artifact, owner, date, and review cadence.

## Current Code Anchors (inspect before filling)

| Area | Current anchor | Notes / gap |
|---|---|---|
| Processing registry model | `aios/governance/privacy.py` (`ProcessingActivity`, `LAWFUL_BASES`, `ASSESSED_BASES`, `evaluate_processing`) | Deterministic evaluation exists; registry is template/data-driven, not legal validation. |
| Privacy API | `aios/api/privacy.py` (`/api/privacy/activities`, `/api/privacy/evaluate`, `/api/privacy/requests`) | Basic create/list/evaluate/request creation. Confirm authz, completeness, DSAR fulfillment workflow before prod. |
| Privacy request model | `aios/governance/privacy.py` (`PrivacyRequest`, `REQUEST_TYPES`, `request_due_at`) | Internal default due 15 days; confirm legal/SLA policy with counsel. |
| Org export | `aios/api/gdpr.py` `GET /api/org/export` | Exports org/agents/conversations/messages/crm_deals/channels; secrets not exported; messages capped/truncated. Confirm DSAR subject scope vs org export. |
| Org erasure | `aios/api/gdpr.py` `DELETE /api/org` | Org-wide FK-aware deletion walk; protected org slugs blocked; admin role gate. Confirm legal hold, backups, vendor deletion, subject-level erasure needs. |
| Deletion target checklist | `aios/governance/privacy.py` `deletion_targets()` | Includes crm/messages/transcripts/documents/rag_chunks/embeddings/caches/analytics_extracts/vendors; verify actual stores/vendors. |
| Privacy migration/tests | `alembic/versions/p8q9r0s1t2u3_privacy_governance.py`, `tests/test_privacy_governance.py`, `tests/test_privacy_api.py` | Use as baseline; add coverage when behavior changes. |
| Personal-data-bearing models (review) | `aios/db/models.py` | Review `User`, `OrganizationMembership`, `Conversation`, `Message`, `CrmDeal`, `WhatsappContact`, `WhatsappEvent`, `ChannelConnection`, `Invitation`, `AuditLog`, documents/call recordings/knowledge/memory tables as applicable. |

## 1) Data Map Template

Fill one row per processing/data store. Owner/DPO review required.

| Data domain | System/table/store | Data subjects | Personal data categories | Sensitive data? | Source | Purpose | Lawful basis | Retention | Access roles | Processors/vendors | Transfer/location | Deletion/export path | Evidence | Owner | Review date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Account/auth | `users`, `organization_memberships`, `refresh_tokens` | employees/admins/users | name/email, password hash, API key hash, TOTP, role/org membership, IP/session metadata where logged | Possible (auth/security) | user/admin | authentication, access control, security | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | DSAR/export/delete procedure; verify backups/logs | _TBD_ | _TBD_ | _TBD_ |
| Conversations/messages | `conversations`, `messages` | customers/leads/users | contact identifiers, message content, channel IDs, metadata | Possible | inbound/outbound channels | service delivery, support, agent operation | _TBD_ | _TBD_ | _TBD_ | channel/LLM vendors as used | _TBD_ | `GET /api/org/export`, org deletion walk; subject-level path TBD | _TBD_ | _TBD_ | _TBD_ |
| CRM | `crm_deals`, related CRM tables | leads/customers | name, email, phone, deal value/stage, notes/metadata | Possible | sales/agents/imports | sales pipeline, follow-up | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | export/delete coverage; verify all CRM tables | _TBD_ | _TBD_ | _TBD_ |
| WhatsApp/contact guard | `whatsapp_contacts`, `whatsapp_events`, `whatsapp_connections`, templates | contacts/tenants | phone number, opt-out/cooldown state, event detail, WABA IDs, encrypted tokens/secrets | Possible | WhatsApp/webhooks/admin config | messaging, compliance opt-out, deliverability | _TBD_ | _TBD_ | _TBD_ | Meta/WhatsApp providers | _TBD_ | verify erasure/export; encrypted secrets handling | _TBD_ | _TBD_ | _TBD_ |
| Documents/transcripts/knowledge | document/call recording/knowledge/memory tables | customers/users | uploaded files, transcripts, embeddings/chunks, derived knowledge | Possible/high risk | uploads/calls/agents | product functionality, search/RAG, support | _TBD_ | _TBD_ | _TBD_ | storage/ASR/LLM/vector vendors | _TBD_ | must cover files, transcripts, chunks, embeddings, caches | _TBD_ | _TBD_ | _TBD_ |
| Audit/security logs | `audit_logs`, security/privacy/audit sink artifacts | users/admins/subjects referenced in logs | actor IDs, IP, action/resource metadata | Possible | system events | security, accountability, incident response | _TBD_ | _TBD_ | _TBD_ | log/SIEM/storage vendors | _TBD_ | define retention/legal hold; avoid unnecessary PII in logs | _TBD_ | _TBD_ | _TBD_ |
| _Add row_ | _table/store_ | _subject_ | _categories_ | _Y/N_ | _source_ | _purpose_ | _basis_ | _retention_ | _roles_ | _vendors_ | _transfer_ | _path_ | _evidence_ | _owner_ | _date_ |

Data map checklist:
- [ ] Inventory all tables/stores with personal data, including caches, backups, analytics exports, logs, vector stores, file/object storage, and vendor systems.
- [ ] Mark sensitive data/special categories and minors/high-risk processing.
- [ ] Record actual storage location/region and cross-border transfer.
- [ ] Confirm deletion/export path is implemented and tested for each row.
- [ ] Assign business owner and review cadence.

## 2) Lawful Basis Register Template

Use one row per processing activity. Mirror approved entries into `ProcessingActivity` records where appropriate.

| Activity key | Controller/operator role | Purpose | Data categories | Subjects | Lawful basis | Basis evidence / assessment | Necessity/minimization | Sensitive data | RIPD needed/status | International transfer + mechanism | Retention | Rights route | Status | Approver | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `example_activity` | controller | _specific purpose_ | _minimal categories_ | _subjects_ | consent/contract/legal_obligation/legitimate_interest/public_policy/research/credit_protection/health_protection/life_protection | _link/doc id_ | _why needed, minimal fields_ | Y/N | not_required/required/approved | _none or mechanism_ | _N days/rule_ | _how subject exercises rights_ | draft/approved/suspended | _name/role_ | _YYYY-MM-DD_ |

Lawful basis checklist:
- [ ] One purpose per activity; no bundled incompatible purposes.
- [ ] Basis supported by evidence (contract, consent record, legal obligation, LIA/RIPD as applicable).
- [ ] Legitimate interest not used for sensitive data unless counsel-approved exception path exists; current code denies sensitive LI.
- [ ] International transfer has documented mechanism before approval.
- [ ] Necessity/minimization documented; collect/store only required fields.
- [ ] `ProcessingActivity.status` approved only after human review.

## 3) DPO / Owner Roles Checklist

Assign named humans. No agent owns legal accountability.

| Role | Named person | Backup | Responsibilities | Contact/escalation | Last reviewed |
|---|---|---|---|---|---|
| Executive owner | _TBD_ | _TBD_ | final accountability, budget/risk acceptance | _TBD_ | _TBD_ |
| DPO/privacy lead | _TBD_ | _TBD_ | LGPD program, DSAR oversight, ANPD/regulator interface as applicable | _TBD_ | _TBD_ |
| Legal counsel | _TBD_ | _TBD_ | lawful basis, contracts, notices, incident/legal signoff | _TBD_ | _TBD_ |
| Security lead | _TBD_ | _TBD_ | technical safeguards, incident response, access/log review | _TBD_ | _TBD_ |
| Engineering owner | _TBD_ | _TBD_ | implement/fix export/delete/retention controls, evidence | _TBD_ | _TBD_ |
| Support/ops owner | _TBD_ | _TBD_ | DSAR intake, identity verification, communications | _TBD_ | _TBD_ |
| Vendor/procurement owner | _TBD_ | _TBD_ | DPA/SCC/transfer terms, vendor deletion confirmations | _TBD_ | _TBD_ |

Roles checklist:
- [ ] DPO/owner named, reachable, documented in runbook/oncall.
- [ ] Escalation path covers nights/weekends for Sev1 privacy/security incidents.
- [ ] Access to personal data follows least privilege; periodic access review scheduled.
- [ ] All DSAR/legal decisions recorded with human approver and evidence.

## 4) DSAR Export/Delete Procedure

Human-gated procedure. Do not improvise in production.

### Intake and triage
- [ ] Receive request through approved channel; create `PrivacyRequest` or equivalent tracked ticket.
- [ ] Record: request type, subject identifier, date/time UTC, channel, requester details, scope, assignee.
- [ ] Verify identity before disclosing/changing data. Human approval required for ambiguous identity.
- [ ] Confirm tenant/org scope and authority. No cross-tenant access.
- [ ] Check legal hold, fraud/security, contract/legal obligation constraints before deletion/restriction.

### Evaluate request
- [ ] Classify type: access, correction, deletion, portability, objection, information, or local process equivalent.
- [ ] Locate data across data map: app DB, files/object storage, transcripts, embeddings/vector stores, caches, logs, backups, vendors.
- [ ] For deletion: identify `deletion_targets()` and any vendor/manual systems not covered by code.
- [ ] For export/portability: define format, scope, redaction, and secure delivery method.
- [ ] Escalate to DPO/legal when request is complex, sensitive, high-risk, or conflicts with legal obligations.

### Execute (approved only)
- [ ] **Export**: use approved export path. Current org export endpoint: `GET /api/org/export` (admin-gated, org-scoped). Validate it covers requested subject data; note message truncation/secrets exclusion behavior.
- [ ] **Deletion/erasure**: use approved erasure path. Current org deletion endpoint: `DELETE /api/org` (admin-gated, protected slugs blocked, FK-aware org subgraph deletion). Confirm if request is subject-level vs org-level; subject-level erasure may require product/code work.
- [ ] **Vendors**: issue deletion/suppression requests where required; capture confirmations.
- [ ] **Backups/logs**: follow documented retention/legal-hold policy; do not silently promise immediate backup purge unless process supports it.

### Verify and close
- [ ] Verify data removed/redacted/exported as approved; capture query/screenshot/log evidence.
- [ ] Record completion/rejection reason, approver, timestamps, and evidence bundle.
- [ ] Respond to subject through approved channel with clear, factual language.
- [ ] Retain DSAR evidence per policy; minimize retained personal data.

DSAR evidence fields:
- Request ID/ticket
- Subject identifier and verification method
- Request type/scope
- Received/due/completed timestamps (UTC)
- Systems/vendors checked
- Actions taken and approver
- Export file checksum/location (if applicable)
- Deletion confirmations (if applicable)
- Exceptions/legal hold/rejection reason

## 5) Retention Schedule Template

Define retention by data category. Human/legal approval required. Enforce only after code/job/support exists.

| Data category | Store/system | Retention period | Legal/operational basis | Deletion/anonymization method | Backup/log handling | Owner | Approved by | Review date |
|---|---|---|---|---|---|---|---|---|
| Account records | users/memberships | _TBD_ | _TBD_ | _delete/anonymize_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| Conversations/messages | conversations/messages | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| CRM/leads | crm_deals/related | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| WhatsApp opt-out/guard | whatsapp_contacts/events | _TBD; opt-out may require durable suppression_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| Documents/transcripts/embeddings | files/transcripts/rag | _TBD_ | _TBD_ | delete source + derived chunks/embeddings/cache | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| Audit/security logs | audit_logs/sink/SIEM | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |
| Backups | backup artifacts | _TBD_ | _TBD_ | expire/rotate/destroy per policy | N/A | _TBD_ | _TBD_ | _TBD_ |

Retention checklist:
- [ ] Retention period defined per category; no "keep forever" default without approved justification.
- [ ] Deletion covers derived data: embeddings, chunks, caches, analytics extracts, vendor copies.
- [ ] Legal hold process can pause deletion with documented approval and scope.
- [ ] Backup retention/restore behavior documented; DSAR responses must be factually accurate.

## 6) Incident / Legal Signoff Checklist

Use for privacy/security incidents, near misses, or DSAR escalations. Human-gated.

### Incident triage
- [ ] Declare incident, assign incident commander and privacy/legal owner.
- [ ] Contain: disable affected flow/integration/key, preserve evidence, limit blast radius.
- [ ] Assess scope: tenants, subjects, data categories, systems, vendors, timeframe, root cause hypothesis.
- [ ] Determine if personal data/sensitive data was involved; avoid assumptions.

### Legal/privacy assessment
- [ ] DPO/legal reviews whether notification/regulatory duties may apply. No public/legal claim without counsel.
- [ ] Preserve timeline/evidence: logs, audit sink, deployment/config changes, affected records, vendor communications.
- [ ] Decide DSAR/subject communications, regulator/contractual notifications, and external messaging with approved owners.
- [ ] Document decisions, rationale, approver, and timestamp.

### Recovery and signoff
- [ ] Remediate root cause; rotate credentials/tokens if needed.
- [ ] Verify fix with tests/smoke/evidence.
- [ ] Complete post-incident review: corrective actions, owners, deadlines.
- [ ] Legal/DPO/security/executive signoff recorded before closing high-severity privacy incident.

Signoff record template:

| Incident ID | Date UTC | Severity | Data involved | Tenants/subjects impacted | Containment | Notifications required? | Legal/DPO decision | Approvers | Evidence bundle | Closure date |
|---|---|---|---|---|---|---|---|---|---|---|
| _TBD_ | _TBD_ | Sev1/2/3 | _TBD_ | _TBD_ | _TBD_ | _TBD/pending counsel_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

## Minimal Operational Cadence

- [ ] Quarterly: review data map, lawful basis register, retention schedule, access/vendors.
- [ ] Per release touching personal data: update data map/register and run privacy tests/checklist.
- [ ] Per DSAR: capture evidence and close with human signoff.
- [ ] Per incident: complete signoff record and corrective actions.

## Related Docs

- `docs/SECURITY_RELIABILITY_HARDENING.md`
- `docs/business-os-runbook.md`
- `website/privacy.html` (public-facing notice; keep consistent with real controls only)
