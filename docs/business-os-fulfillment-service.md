# Business OS — Fulfillment = Service as Software

> **Scaffold, not live fulfillment automation.** This adapter models service fulfillment as software. No real external provisioning, no credentials, no customer-facing delivery system is wired. Any real side effect requires explicit configuration, HITL approval, and owner accountability.

## Model

Service-as-Software fulfillment treats a sold service as a case with explicit steps, evidence, acceptance, and closure. The system can orchestrate state and audit; a human owner remains accountable for the deliverable, commercial promises, and irreversible actions.

Core object: **service case** (`service_case_id`) inside an org (`org_id`).

## Required inputs from owner

Before enabling fulfillment for a real service, the owner must define:

| Input | Required | Notes |
|---|---|---|
| Deliverable definition | Yes | What is being delivered, format, scope boundaries, exclusions. |
| SLA / timeline | Yes | Start time, milestones, due dates, breach/escalation path. |
| Acceptance criteria | Yes | Objective criteria the customer/owner uses to accept or reject. |
| Proof / evidence | Yes | Artifacts required to prove delivery (files, logs, screenshots, report, sign-off). |
| Cancel/refund policy | Yes | When cancellation is allowed, who approves, refund/credit rules, legal review if needed. |
| Steps/checklist | Yes | Configured execution steps; adapter fails closed if missing. |
| Sandbox/executor handler | Yes | Callable that performs sandbox/non-production work; no real provisioning by default. |
| Approval owner | Yes | Named human responsible for irreversible approvals. |

## HITL points

| Action | External/irreversible? | HITL |
|---|---|---|
| `provision` | Internal/setup | Recommended; required by policy if it causes external side effect. |
| `start` | Internal/start | Recommended. |
| `deliver` | **Irreversible/external** | **Required.** Missing approval fails closed. |
| `accept` | Business closure signal | Owner/customer acceptance recorded; human accountability. |
| `cancel` | **Irreversible/commercial** | **Required.** Missing approval fails closed; follow cancel/refund policy. |

Approval must be explicit (`approved=true` or `approval_id`). The adapter does not fabricate approval.

## Status mapping to business loop

Business loop states (`aios/core/business_loop.py`): `lead -> qualify -> outreach -> follow_up -> close -> invoice -> delivery -> support -> retention`, with `lost/cancelled` terminals. `delivery` is side-effectful and requires HITL in the loop.

| Fulfillment action | Adapter result status | Business loop mapping | Notes |
|---|---|---|---|
| `provision` | `ok` / `idempotent_replay` | Pre-`delivery` prep while case is at `invoice` or internal ops | No loop transition by itself; owner process decides. |
| `start` | `ok` / `idempotent_replay` | Work started before `delivery` | Internal execution state. |
| `deliver` | `ok` / `idempotent_replay` | Enables/records evidence for `invoice -> delivery` transition | Loop transition to `delivery` remains HITL-gated and audited. |
| `accept` | `ok` / `idempotent_replay` | Supports `delivery -> support` after acceptance criteria met | Acceptance evidence should be attached by owner/process. |
| `cancel` | `ok` / `idempotent_replay` | Maps to `cancelled` terminal path | Requires HITL approval and cancel/refund policy; legal/commercial review as needed. |

## Fail-closed rules

- Missing adapter config: denied.
- Missing `idempotency_key`, `org_id`, or `service_case_id`: denied.
- Unsupported action: denied.
- `deliver`/`cancel` without explicit approval: denied.
- No real external provisioning: sandbox handler only.

## Audit

Every attempt emits audit events (`fulfillment.start/denied/result/error/idempotent_replay`) to in-memory `audit_log` and optional callback. Audit records include action, idempotency key, org/case, and outcome; they do not include secrets.
