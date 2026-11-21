# Privacy & LGPD Compliance Department
## Formal Organizational Charter and Organizational Control Plane Integration

**Status:** Proposed governance specification  
**Owner:** Founder / controller's executive authority  
**Applies to:** AIOS internal operations and customer-facing processing, with controller/operator roles determined per processing purpose and contract  
**Implementation status:** Architecture specification only; this document does not claim that the controls described are implemented.

> This is an engineering and governance specification, not a legal opinion or certification of LGPD compliance. Brazilian privacy counsel must validate the operating model, contracts, legal bases, notices, transfer mechanisms and formal designation of the Encarregado before production use.

## 1. Executive decision

Establish a **Privacy & LGPD Compliance Department** as an independent governance and assurance function with direct access to the Founder.

Three responsibilities must remain distinct:

1. **Privacy Department:** governance framework, assessments, oversight, rights-request coordination, risk monitoring and evidence.
2. **Designated Encarregado:** the formal communication and advisory function required by applicable LGPD/ANPD rules. This must be a qualified natural person or legal entity, not an AI agent. It must have appropriate autonomy, resources and access to senior management; conflicts of interest must be assessed.
3. **Controller / Operator business owners:** retain their legal and operational responsibilities. The controller decides purposes and essential means; an operator processes on documented instructions within the applicable contract and law.

AI agents may prepare drafts, organize evidence, monitor deadlines and route tasks. They cannot be represented as the legally designated Encarregado, independently make binding legal determinations, or replace authorized humans in regulatory communications.

## 2. Mission and mandate

### Mission

Establish, maintain and continuously improve AIOS's privacy governance program so every personal-data processing activity is purpose-bound, legally assessed, proportionate, transparent, secure, accountable and subject to appropriate oversight.

### Mandate

The department shall:

- Maintain privacy policies, standards, procedures and the control catalogue.
- Maintain the record of processing activities (ROPA / registro das operações de tratamento), including owners, purposes, data categories, data subjects, legal bases, recipients, locations, retention, safeguards and controller/operator roles.
- Coordinate legal-basis assessments for each distinct purpose and operation. Consent is not the universal/default legal basis; legitimate interest is not blanket authorization.
- Review new or materially changed features, agents, tools, workflows, integrations, datasets, analytics, customer deployments and business processes.
- Coordinate privacy risk assessments and RIPD preparation where appropriate or required.
- Coordinate data-subject rights requests and complaints with the responsible controller and designated Encarregado.
- Govern retention, deletion, blocking, anonymization and downstream data lifecycle requirements.
- Assess vendors, subprocessors, data-sharing arrangements and international transfers.
- Coordinate privacy aspects of incidents with Security and the responsible controller.
- Provide training, operational guidance and periodic assurance reviews.
- Maintain evidence of assessments, decisions, approvals, remediation and control effectiveness.
- Advise on controller/operator allocation for each purpose and contractual relationship.

### Exclusions

The department does not replace Legal Counsel, the designated Encarregado, Security or Engineering; determine business purposes on behalf of the controller; make unlawful processing lawful by approving a checklist; assume the controller's statutory responsibility; grant agents blanket access; or treat public data as exempt from LGPD.

A RIPD is not a universal prerequisite for every low-risk code change. Assessments must be risk-based and follow applicable ANPD requirements.

## 3. Scope

The governance scope includes:

- CRM, accounts, contacts, Customer 360, sales and customer-success records.
- LIA, prospect research, contact enrichment, qualification and outreach.
- WhatsApp, email, voice, Google Meet and other communication channels.
- Secretary, meeting intelligence, transcripts, summaries, action items and organizational memory.
- Organizational Knowledge, RAG, vector/full-text indexes, embeddings and derived insights.
- Agent memory, prompts, tools, workflow inputs/outputs, traces and execution logs.
- Product analytics, BI, evaluation datasets and telemetry.
- Employee, contractor, supplier and applicant data used in internal operations.
- Customer environments, support, backups, exports, monitoring and incident evidence.
- Cloud infrastructure, LLM providers, search, storage and other vendors/subprocessors.

AIOS's role must be determined per purpose. AIOS may be a controller for its own business activities and an operator for processing performed on customer instructions. The actual role follows the facts, decisions and contract, not a global label.

## 4. Reporting and independence

### Reporting line

- The Privacy Department reports directly to the Founder / highest human executive authority.
- It is independent from Engineering, Product, Sales, Operations and Security in its assurance findings.
- It may request information and remediation from every department.
- It may escalate unresolved material risk directly to the Founder.
- The Founder/controller retains legal accountability and decides whether to accept residual business risk. Risk acceptance cannot authorize unlawful processing.
- Security is a peer department: Security leads technical security detection and response; Privacy leads privacy impact, data-subject impact, regulatory coordination and privacy remediation requirements.

### Encarregado independence

The designated Encarregado must have a formal written designation, adequate resources, technical autonomy, access to senior management and a suitable substitute/continuity arrangement. Identity and contact details must be disclosed as required.

The Encarregado's advisory and communication duties must not be confused with the controller's responsibility for compliance. The Encarregado must declare potential conflicts. Do not appoint a person whose other duties create a material conflict by deciding the purposes or essential means they are expected to oversee. Obtain counsel's assessment of the actual role.

An AI agent may draft responses and organize evidence, but must never be represented as the legally designated Encarregado or independently conduct regulatory communications requiring human/legal judgment.

### Reporting cadence

- **Immediate:** suspected unlawful processing, high-risk privacy-control failure, material data incident, rights-request deadline risk or ANPD communication.
- **Weekly:** open requests, risk register, assessments, overdue remediation and upcoming releases.
- **Monthly:** written privacy posture report to Founder, including unresolved risks and decisions required.
- **Quarterly:** cross-department assurance review and control-effectiveness assessment.
- **Pre-release:** privacy assessment before new or materially changed high-risk processing goes live.

## 5. Internal roles

Roles are functional responsibilities, not a requirement to create one AI agent per title.

| Role | Responsibilities | Limits |
|---|---|---|
| Privacy Program Manager | Department planning, coordination, risk reporting, policy ownership and cross-team escalation | Cannot determine business purposes, grant itself access or approve its own exceptions |
| Privacy Governance Analyst | Processing inventory, legal-basis evidence, notices, policy documentation and audit evidence | Cannot give binding legal opinions |
| Privacy Risk Analyst | Privacy risk assessments, RIPD coordination, feature/vendor review and mitigation tracking | Cannot unilaterally accept residual risk |
| Privacy Operations Analyst | Rights-request intake, identity/authority workflow, retention/deletion coordination and complaint tracking | Cannot disclose or erase data outside an approved, verified procedure |
| Privacy Engineering Liaison | Translate requirements into testable technical controls and verify remediation evidence | Does not deploy production changes or grant privileges independently |
| Designated Encarregado | Statutory communication channel, guidance, receipt of ANPD communications and advice on privacy practices | Must remain independent; does not assume controller responsibility |
| External Brazilian privacy counsel | Legal interpretation, contract review, legal-basis validation, regulatory strategy and escalation advice | Engagement and scope must be documented |

### Initial staffing

Start lean:

- One Privacy Program Manager agent.
- One combined Governance & Operations agent.
- Privacy Engineering Liaison as a shared function with Engineering.
- One formally designated human or legal-entity Encarregado, with qualified Brazilian privacy counsel available.

Do not build a large autonomous department before processing volume justifies it.

## 6. Authority matrix

**RACI:** A = accountable decision owner; R = responsible executor; C = consulted; I = informed. This internal matrix does not alter statutory responsibility.

| Activity / decision | Privacy Dept | Encarregado | Business owner | Security | Engineering | Founder / controller |
|---|---:|---:|---:|---:|---:|---:|
| Maintain privacy program and control catalogue | R | C | C | C | C | A |
| Register processing activity | R | C | R | C | C | A |
| Define business purpose and essential means | C | C | R | I | C | A |
| Propose legal basis and necessity assessment | R | C | C | C | I | A |
| Validate complex legal interpretation | R | C | C | I | I | A, with counsel |
| New high-risk processing assessment | R | C | R | C | C | A |
| RIPD preparation and approval | R | C | R | C | C | A |
| Implement technical privacy controls | C | I | C | C | R | A |
| Vendor / international-transfer assessment | R | C | R | C | C | A |
| Rights-request coordination | R | R/C | R | C | R | A |
| External response to ANPD | C | R | I | C | C | A / authorized human |
| Technical incident containment | C | I | I | A/R | R | I |
| Privacy impact / notification assessment | R | R/C | C | R | C | A |
| Routine deletion under approved schedule | C | I | A | C | R | I |
| Exceptional deletion / legal-hold conflict | R | C | C | C | R | A |
| Approve new processing purpose | C | C | R | I | C | A |
| Accept residual privacy risk | C | C | R | C | C | A |
| Temporary restriction on credible high-risk concern | R | C | I | R | R | A for strategic resolution |
| Approve privacy policy changes | R | C | C | C | C | A |
| Audit privacy controls | A/R | C | C | C | C | I |

### Delegated authority

The department may require a processing record before new processing begins; require documented assessment before material changes; request evidence from any department; open and assign remediation tasks; mark processing as **not cleared** when required evidence is missing; recommend temporary reversible restriction under a pre-approved emergency policy; and escalate unresolved disagreements.

It may not determine business purposes, grant itself or agents broad access, approve its own exceptions, permanently delete data or destroy backups without authorized review, send substantive regulatory statements autonomously, or accept residual legal risk on behalf of the controller.

A status such as "approved" is a governance record, not a legal safe harbor. Runtime controls must independently enforce permissions and purpose restrictions.

## 7. Risk tiers and decision gates

| Tier | Example | Required controls |
|---|---|---|
| Low | UI change with no new personal-data processing | Change record; confirm no data-flow change |
| Moderate | New CRM field or new internal analytics use | Purpose, necessity, legal basis, notice, access and retention review |
| High | Cross-source customer profiling, conversation intelligence, scoring affecting individuals, broad employee monitoring | Formal privacy risk assessment, counsel/Encarregado consultation as appropriate, minimization, human oversight and documented release gate |
| Critical | Sensitive data, large-scale monitoring, high-impact automated decisions, broad cross-tenant access, unvalidated international transfer, material incident | Block pending executive/legal review, documented assessment and safeguards |

A high numerical score cannot compensate for a prohibited purpose, missing legal basis, lack of necessity, invalid transfer mechanism or missing mandatory safeguard.

## 8. Mandatory processing lifecycle record

Every processing activity must record:

- Activity ID and version.
- Controller and operator roles for the specific purpose.
- Business owner and technical owner.
- Purpose and compatibility assessment.
- Categories of data subjects and personal data; sensitive-data flag.
- Source and collection method.
- Legal basis and supporting assessment; consent evidence when relied upon.
- Necessity and minimization rationale.
- Recipients, vendors and subprocessors.
- Storage/access locations and international transfer mechanism where applicable.
- Transparency notice reference.
- Retention period, deletion trigger and legal-hold handling.
- Data-subject rights route.
- Security safeguards and access policy.
- Risk tier, assessment and RIPD reference where applicable.
- Approval, review date and change history.

No processing may be activated solely because an LLM or manager agent recommends it.

## 9. Organizational Control Plane integration

### Current repository baseline

The current main branch contains useful foundations:

- Organization, User, Agent, Team, team_agents and Budget in aios/db/models.py.
- Team creation and assignment in aios/api/teams.py.
- Idempotent creation of a cross-team orchestrator and a small set of business teams in aios/core/org_bootstrap.py.
- Human approval records/API through PendingAction and aios/api/approvals.py.
- AuditLog and aios/core/audit.py.
- Skill, Workflow, workflow-run and ARQ execution foundations.
- Existing organization export and organization deletion endpoints in aios/api/gdpr.py.
- Basic pattern-based PII redaction in aios/core/pii.py.

The focused repository inspection did not identify a complete first-class Organizational Control Plane: no unified Department entity, human/agent organizational membership model, delegated authority model, shared organizational task registry, or complete privacy processing registry.

The current aios/api/gdpr.py is not a complete data-subject request system. Organization export and organization deletion are not substitutes for an individual rights-request workflow, purpose-specific restriction, downstream deletion propagation or a verified response process.

### Integration principle

Do not build a separate Privacy organization-management system. Represent Privacy as a Department and its roles, goals, tasks, approvals and reporting through the shared Organizational Control Plane. Keep privacy-specific records and enforcement in a dedicated capability.

### Shared Control Plane primitives

Implement only where no equivalent exists:

- **Department:** organization, stable key, name, mission, status, manager, reporting target and policy references.
- **OrgMembership:** human or agent identity, department, role, status and validity dates.
- **OrgRole / AuthorityGrant:** action/resource scope, autonomy tier, approver, validity and revocation.
- **OrgTask:** shared task registry with requester, owning department, assignee, objective, priority, deadline, dependencies, evidence, status and audit history.
- **OrgGoal:** objective, owner, measures, period and status.
- **OrgApproval:** approval linked to a specific action, resource version, policy decision and evidence.
- **OrgEvent:** durable events for delegation, task state, approvals, escalations and department changes.

Avoid parallel PrivacyTask, PrivacyApproval or PrivacyAgent tables if generic Control Plane objects exist. Privacy workflows reference shared IDs.

### Privacy capability package

Target layout:

~~~text
aios/
  governance/
    privacy/
      __init__.py
      models.py
      registry.py
      policies.py
      assessment.py
      legal_basis.py
      legitimate_interest.py
      rights_requests.py
      retention.py
      deletion.py
      anonymization.py
      transfers.py
      vendors.py
      ripd.py
      incidents.py
      enforcement.py
      audit.py
      workflows/
        new_processing.yaml
        feature_release.yaml
        data_subject_request.yaml
        vendor_assessment.yaml
        international_transfer.yaml
        retention_deletion.yaml
        privacy_incident.yaml
~~~

This is a target package, not a claim these files exist.

### Department bootstrap

Extend aios/core/org_bootstrap.py only after generic Department and membership models exist.

Create an idempotent internal department with a stable marker:

~~~python
{
    "business_setup": "internal_department",
    "department_key": "privacy_lgpd",
    "visibility": "internal_only",
    "reports_to": "founder"
}
~~~

Create the Privacy Program Manager and Governance & Operations roles using existing Agent/Team mechanisms. Do not make an agent the Encarregado. Store the designated human/legal-entity appointment as a separately governed record with access-controlled contact details.

The Privacy Department belongs to AIOS's internal organization only. It must not be automatically provisioned into every customer tenant. Customer tenants may have their own privacy contacts and responsibilities; AIOS's internal team operates under its own authorization and contractual scope.

### Backlog integration

Privacy work uses the shared task registry:

- Department-owned: processing inventory, policy review, vendor assessment, rights requests and audits.
- Cross-department requests: Engineering implements deletion propagation; Security supplies incident evidence; Product supplies proposed data flows; Sales supplies customer/contract context.
- Incoming requests: each department retains ownership of its operational work; Privacy defines requirements and verifies evidence.
- Escalations: unresolved legal or high-risk matters route to the Founder, not indefinitely through agent managers.

Every privacy task includes purpose, affected processing activity, risk tier, data scope, required evidence, due date, owner and approval requirements. Avoid unnecessary personal data in task descriptions; reference protected records by ID.

## 10. Privacy enforcement architecture

The department cannot rely on prompts or post-hoc audits alone. A deterministic enforcement layer must be called by systems that access or process data.

### Enforcement decision

Before a relevant operation, evaluate:

1. Authenticated actor and organization/tenant.
2. Resource and data-subject scope.
3. Requested action: read, create, infer, export, share, delete or transmit.
4. Declared purpose and processing activity ID.
5. Effective user, agent, workflow and tool permissions.
6. Processing record and legal-basis assessment status.
7. Minimization and sensitive-data constraints.
8. Recipient, vendor and transfer restrictions.
9. Retention, restriction, opt-out and legal-hold state.
10. Required approval and current policy version.

Possible decisions:

- **allow:** mandatory controls pass.
- **deny:** prohibited, unauthorized or unsupported.
- **require_approval:** policy requires human authorization.
- **restrict:** only a limited operation is permitted, such as redacted or aggregate output.
- **defer:** required evidence or policy evaluation is unavailable.

Fail closed for new or sensitive processing when policy evaluation is unavailable. An agent cannot override a denial by changing its prompt or requesting a different tool.

### Enforcement placement

- API/service layer: identity, tenant, purpose and record authorization.
- Tool gateway: action-specific permission and side-effect checks.
- Retrieval/RAG: permission filtering before retrieval and context assembly, not merely after generation.
- CRM/Customer 360: field and relationship access, retention and rights-state checks.
- LIA: source provenance, lawful purpose, contact restrictions and suppression.
- Secretary/meeting intelligence: recording/transcription authorization, notices, scope, access and retention.
- Knowledge indexing: provenance, permission metadata, deletion propagation to chunks and embeddings.
- LLM/provider gateway: approved data classes, provider allowlist, region/transfer rules and minimization/redaction.
- Export and deletion services: verified identity/authority, scope, exceptions, audit and completion evidence.
- Analytics: aggregation/anonymization controls and re-identification restrictions.

The LLM may assist in classifying a request or drafting a rationale, but deterministic policy code decides access.

### Data lifecycle and deletion

A rights request or approved retention event creates a traceable deletion/restriction job. It identifies source records and derived copies, including CRM, messages, transcripts, documents, RAG chunks, embeddings, caches, analytics extracts and third-party systems where applicable.

Deletion respects legal retention obligations, legal holds and technical constraints. Backups require documented expiry and restore handling; do not claim immediate physical erasure from immutable backups if the system cannot do it. If deleted data is restored from backup, tombstone/deletion events must be replayed before restored data becomes available for normal processing.

## 11. Required workflows

### A. New processing / new feature

1. Requesting department creates a proposal in the shared backlog.
2. Product/Engineering describe data flows, data classes, sources, recipients and intended outcome.
3. Privacy creates or updates the processing record and performs the initial assessment.
4. Legal counsel/Encarregado are consulted where required by risk or legal uncertainty.
5. Security assesses technical threats; Engineering implements controls.
6. Privacy verifies evidence and records a governance decision.
7. Authorized human release owner approves launch.
8. Processing registry and notices are updated; post-release controls are monitored.

### B. Data-subject request

1. Receive request through the published channel.
2. Verify identity and authority proportionately; do not collect excessive identity documents.
3. Identify the relevant controller and processing purposes.
4. Locate records and derived data using the data inventory and lineage.
5. Assess applicable rights, exceptions, legal holds and retention duties.
6. Prepare response and actions.
7. Authorized controller/human approves complex disclosure or exceptions.
8. Execute access, correction, restriction, deletion or other applicable action.
9. Propagate actions to downstream processors and derived stores where required.
10. Record completion, response, deadlines and evidence.

### C. Vendor / international transfer

1. Identify vendor, subprocessor, location, support access and onward recipients.
2. Determine AIOS/customer controller-operator roles and documented instructions.
3. Record purpose, data categories, necessity and legal basis.
4. Assess security, retention, model training/use, access controls and deletion.
5. Validate a lawful international transfer mechanism when a transfer occurs; a general vendor contract or region label is not enough.
6. Review contractual terms, transparency and data-subject rights support.
7. Approve through the authorized human process and record reassessment triggers.

### D. Privacy incident

1. Security detects or receives the signal and starts incident handling.
2. Preserve evidence and contain the threat under Security policy.
3. Privacy determines whether personal data may be involved and identifies affected processing activities and controllers.
4. Establish facts, categories, affected subjects, consequences and mitigation.
5. Notify the responsible controller and Encarregado immediately.
6. Authorized human/legal decision-makers determine external notifications and communications under applicable deadlines.
7. Document the decision, rationale, timeline, communications and remediation.
8. Verify corrective controls and update the risk register.

For incidents within the scope of ANPD Resolution CD/ANPD No. 15/2024, the controller's communication deadline is generally three business days under the applicable rule, subject to its scope, trigger and exceptions. The workflow must be designed around the current rule and counsel-confirmed trigger; it must not wait for a weekly meeting.

## 12. Privacy data model

Use normalized, versioned, organization-scoped records:

- privacy_processing_activities: activity, purpose, owner, controller/operator role, status, version.
- privacy_data_categories: category, sensitive flag, data-subject category, source.
- privacy_legal_basis_assessments: purpose, legal basis, factual rationale, necessity, balancing/safeguards, reviewer, status, version.
- privacy_recipients: recipient/vendor/subprocessor, role, purpose, destination.
- privacy_transfer_assessments: destination, transfer mechanism, contractual reference, safeguards, onward transfer.
- privacy_retention_rules: data class, trigger, period, deletion/archival action, exception/hold.
- privacy_risk_assessments: inherent/residual risk, likelihood, impact, mitigations, owner, status.
- privacy_ripd_records: scope, methodology, risks, safeguards, approval and version.
- privacy_rights_requests: requester reference, verified scope, request type, controller, received/deadline/status, actions and evidence.
- privacy_deletion_jobs: source/derived targets, execution status, exceptions, backup expiry and verification.
- privacy_vendor_assessments: vendor, subprocessors, data, location, terms, assessment and review date.
- privacy_incident_records: incident reference, affected activity, controller, facts, timeline, decisions and communications.
- privacy_notices: notice version, audience, purposes, channels, publication date.
- privacy_audit_evidence: control, evidence reference, collection time, integrity and retention.

Avoid copying raw personal data into governance records when a protected resource ID and minimal metadata suffice.

## 13. Control objectives and KPIs

Measure control coverage and effectiveness, not document volume:

- Processing inventory coverage.
- Legal-basis evidence coverage for active purposes.
- High-risk pre-release assessment coverage.
- Percentage of stores and derived indexes covered by rights/deletion lineage.
- Rights-request completion within applicable deadlines.
- Vendor and international-transfer assessment coverage.
- Retention-policy execution and exception rates.
- Overdue high-risk remediation count and age.
- Privacy enforcement denials and overrides; overrides should be exceptional and audited.
- Incident triage time and notification-decision timeliness.
- Control test pass rate, including cross-tenant and unauthorized retrieval tests.
- Training completion and recurring process failures.

Set targets after a baseline inventory, not before measurement.

## 14. Implementation roadmap

### Phase 0 — Governance foundation

- Approve this charter.
- Confirm controller/operator mapping for AIOS's own and customer processing.
- Appoint a qualified human/legal-entity Encarregado and substitute where applicable.
- Establish counsel support and escalation route.
- Create department, roles, authority grants and reporting.
- Build processing inventory and privacy risk register.
- Freeze unassessed high-risk new processing.

### Phase 1 — Operational workflows

- Rights-request intake and tracking.
- Vendor/subprocessor register.
- International transfer assessment.
- Retention schedule and legal-hold process.
- Incident coordination workflow and deadline tracking.
- Privacy review gates in Product/Engineering releases.

### Phase 2 — Technical enforcement

- Shared privacy policy decision point.
- Purpose-bound service and tool authorization.
- Retrieval-time permissions.
- Data lineage and deletion propagation.
- LLM/provider data-class and transfer controls.
- Audit evidence and monitoring.
- Tenant-isolation, unauthorized retrieval and deletion regression tests.

### Phase 3 — Continuous assurance

- Scheduled control tests and evidence collection.
- Department dashboards and monthly reports.
- Vendor reassessments and change alerts.
- Periodic retention and access reviews.
- Incident exercises and recovery verification.
- Independent review of high-risk processing.

## 15. Definition of done

The department is not operational merely because it exists in an org chart or bootstrap.

Minimum acceptance criteria:

1. Formal charter, executive sponsor and department owner approved.
2. Qualified human/legal-entity Encarregado formally designated where required, with published contact route and conflict review.
3. All departments have named data/process owners.
4. Material processing activities inventoried with purpose, role, legal basis, data categories, recipients, location, retention and controls.
5. High-risk activities cannot launch without documented assessment and authorized release approval.
6. Privacy enforcement is checked by code at data-access and tool boundaries; prompts alone do not count.
7. Cross-tenant retrieval and unauthorized agent access tests pass.
8. Rights requests can be verified, tracked, executed and evidenced across source and derived systems.
9. Retention, deletion, legal holds and backup restore behavior are documented and tested.
10. Vendors and international transfers are assessed with valid contractual/transfer mechanisms.
11. Security and Privacy have a tested incident handoff and escalation process.
12. Audit evidence is protected and retained according to the threat model and policy.
13. Unresolved risks and overdue actions are reported to the Founder.
14. Brazilian privacy counsel validates the legal and contractual operating model before production compliance claims.

## 16. Legal and regulatory reference baseline

Check the consolidated law and current ANPD regulations at deployment. Baseline:

- Lei nº 13.709/2018 (LGPD), including principles, legal bases, data-subject rights, records of processing, RIPD, controller/operator responsibilities, Encarregado, security and governance.
- ANPD Resolution CD/ANPD nº 18/2024 — Encarregado designation, duties, resources, autonomy and conflict of interest.
- ANPD Resolution CD/ANPD nº 15/2024 — communication of security incidents.
- ANPD Resolution CD/ANPD nº 19/2024 — international data transfers and standard contractual clauses.
- Applicable ANPD rules for small processing agents, where relevant; eligibility and exemptions must be assessed rather than assumed.
- Other applicable Brazilian laws and sector-specific requirements.

Official references:

- LGPD consolidated text: https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm
- ANPD Encarregado regulation (Resolution 18/2024): https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/documentos/encarregado-completo_ocultado.pdf
- ANPD incident communication guidance: https://www.gov.br/anpd/pt-br/canais_atendimento/agente-de-tratamento/comunicado-de-incidente-de-seguranca
- ANPD international transfer regulation: https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-19-de-23-de-agosto-de-2024

---

**Final architectural rule:** Privacy is a cross-cutting governance and enforcement layer, not a prompt, dashboard, single agent or department that can approve its own work. The Organizational Control Plane manages ownership and decision authority; the Privacy capability defines and evaluates constraints; deterministic enforcement applies them at runtime; the controller and authorized humans retain legal and strategic accountability.
