# Business OS — Scope & Limits (Honest Status)

> **Status: not live business automation.** This document reports current capability scope honestly. It is not legal/tax/financial advice; for legal, tax, or financial decisions, escalate to a qualified human professional.

## Principle

AIOS Business OS components are scaffolds/integration surfaces unless explicitly configured, credentialed, integrated, tested, and approved by a Human owner. No real payment/CRM/email/WhatsApp/calendar/fulfillment wired by default. Any external side effect requires HITL (human-in-the-loop) approval before execution.

## Capability / Domain Status

| Capability / Domain | Status | What's needed | Human owner accountability |
|---|---|---|---|
| Payments / billing / invoicing (`payment`) | `not_configured` | Real provider credentials, webhook verification, idempotency/reconciliation, HITL for charges/refunds, legal/tax review | Human owner approves pricing, charges, refunds, and tax/compliance handling |
| CRM / pipeline / contacts (`crm`) | `not_configured` | CRM credentials/integration, field mapping, data ownership rules, HITL for writes/outbound actions, LGPD/privacy review | Human owner owns customer data decisions, outreach approval, and record accuracy |
| Email / inbox / outbound (`email`) | `not_configured` | Provider credentials (SMTP/API), domain/auth (SPF/DKIM/DMARC), templates, HITL for sends, compliance review | Human owner approves external communications and sender identity |
| WhatsApp / messaging (`whatsapp`) | `not_configured` | WhatsApp provider credentials, approved templates/numbers, webhook config, HITL for sends, opt-in/privacy review | Human owner approves message content, recipients, and compliance |
| Calendar / scheduling (`calendar`) | `not_configured` | Calendar provider credentials/OAuth, timezone/availability rules, HITL for bookings/changes, privacy review | Human owner approves meetings, cancellations, and external commitments |
| Fulfillment / operations / delivery (`fulfillment`) | `not_configured` | Provider/integration credentials, order/inventory mapping, HITL for state changes, legal/commercial review | Human owner approves fulfillment actions, exceptions, and customer commitments |
| Agent packs / routines / automations | `scaffold` | Explicit config, credential scoping, HITL gates, audit logging, tested rollback path | Human owner approves activation, scope, and kill-switch decisions |
| Knowledge / RAG / memory | `scaffold` | Data source curation, access control, retention policy, human review for sensitive content | Human owner accountable for data quality, privacy, and permitted use |
| Public claims / pricing / legal copy | `scaffold` | Verification against real code/config, legal review, HITL before publish | Human owner accountable for published claims and compliance |

## Guardrails

- **Not live business automation:** no domain above is considered live until configured, tested, and explicitly approved by a Human owner.
- **HITL required:** side effects (send, charge, book, update external system, publish, delete) require human-in-the-loop approval.
- **No silent escalation:** if credentials/integration/policy are missing, status remains `not_configured` and action must fail closed.
- **No legal/tax/financial advice:** agents may draft/summarize; Human owner obtains qualified professional review before acting.
- **Truth principle:** docs/UI must match real limits in code/config; do not promise unimplemented capabilities.

## Evidence / Source of Truth

- Plans/limits: `aios/config.py` (`PLANS`), `aios/core/limits.py` (`check_org_limits`)
- HITL/approvals: approval flows and pending-action gates in API/core/runtime
- Deploy/health: `docs/DEPLOY.md`, `/health/ready` smoke checks
- Legal boundaries: `docs/business-os-legal-boundaries.md`
