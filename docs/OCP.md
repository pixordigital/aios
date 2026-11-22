# OCP - Organizational Control Plane

## Scope
OCP owns shared organizational primitives: departments, department members, authority grants, shared tasks, goals, decisions, and org events. Deterministic code owns transitions, authority checks, and decision gates. LLMs may propose; they do not approve.

## Boundaries
- **OCP vs Workflow/ICM**: OCP tracks org state and decision/task lifecycle; workflow engines execute process steps. A workflow may create/update OCP tasks, but OCP is not a BPM runtime.
- **OCP vs Governance/Agent Runtime**: Governance/runtime enforce tool/model/runtime policy. OCP authority grants are organizational delegation records; runtime policy remains authoritative for execution safety.
- **OCP vs Approvals (`PendingAction/ApprovalManager`)**: `PendingAction` is the human-in-the-loop queue for tool-call approvals. `DecisionRecord` is the Founder/organizational decision protocol. They are related but **not unified**.
  - Bridge: OCP emits `OrgEvent` on decision propose/decide/execute with decision id/status/level. `POST /api/ocp/decisions/{id}/link-approval` stores external approval refs in `DecisionRecord.justification["_external_approvals"]` (no schema change, no core approval ownership change). `GET /api/ocp/tasks/{id}/approval-links` returns refs from decisions linked to a task.
  - Decision payload includes `approval_bridge`: `{mode:"external_refs_only", unified:false, external_approval_count, limitation}`. This is status/metadata only.
  - **Limitation (explicit, not done)**: full PendingAction/ApprovalManager↔DecisionRecord unification deferred; requires core approval/runtime schema and behavior changes outside this track. Do not claim unified approval.
- **OCP vs Adapters/Observability**: adapters emit domain events; OCP stores org-control events in `org_events` for tenant-scoped audit/read API. External observability may ingest these events.

## Event Model
`OrgEvent` is append-only, tenant-scoped.

Emitted by OCP API/governance on:
- `department.created`, `department.member_added`, `department.member_removed`
- `authority.granted`, `authority.revoked`
- `task.created`, `task.transitioned`
- `goal.created`, `goal.updated`
- `decision.proposed`, `decision.decided`, `decision.executed`

Read: `GET /api/ocp/events?event_type=&entity_type=&entity_id=&limit=`

## Authority Wiring
`authorize()` is deterministic. OCP API wires it non-breakingly by default:
- If subject has active grants in the action domain, a matching grant is required (403 on deny).
- If no relevant grants configured for subject/action domain, request is allowed unless org enables strict mode.

Optional strict mode (OCP domain, default off, no schema change): `Organization.extra_data.ocp.strict_default_deny = true` denies when no relevant grant is configured.

Policy endpoints (Founder/owner for PUT): `GET /api/ocp/policy`, `PUT /api/ocp/policy` with `{"strict_default_deny": bool}`. Persisted in `org.extra_data.ocp`.

Mutating actions wired through OCP policy: `department:create`, `department:bootstrap`, `department:member_add`, `department:member_remove`, `authority:grant`, `authority:revoke`, `task:create`, `task:transition`, `goal:create`, `goal:update`, `decision:propose`, `decision:decide`, `decision:link_approval`, `decision:execute`. Founder-gated endpoints (`department:bootstrap`, `decision:decide`) keep Founder bypass but still evaluate policy for non-founders.

## Task Views/Filters
`GET /api/ocp/tasks` filters: `status`, `department_id`/`responsible_department_id`, `requesting_department_id`, `owner_type`, `owner_id`, `overdue=true`, `my_dept=<dept_id>`.

## Decision Execution
`POST /api/ocp/decisions/{id}/execute` reconciles task IDs against provided/body/linked tasks in-org and persists reconciled `linked_task_ids`. Only approved decisions execute; ready tasks transition to in_progress with audit history.
