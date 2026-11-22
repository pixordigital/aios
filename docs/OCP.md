# OCP - Organizational Control Plane

## Scope
OCP owns shared organizational primitives: departments, department members, authority grants, shared tasks, goals, decisions, and org events. Deterministic code owns transitions, authority checks, and decision gates. LLMs may propose; they do not approve.

## Boundaries
- **OCP vs Workflow/ICM**: OCP tracks org state and decision/task lifecycle; workflow engines execute process steps. A workflow may create/update OCP tasks, but OCP is not a BPM runtime.
- **OCP vs Governance/Agent Runtime**: Governance/runtime enforce tool/model/runtime policy. OCP authority grants are organizational delegation records; runtime policy remains authoritative for execution safety.
- **OCP vs Approvals (`PendingAction/ApprovalManager`)**: `PendingAction` is the human-in-the-loop queue for tool-call approvals. `DecisionRecord` is the Founder/organizational decision protocol. They are related but not unified yet.
  - Bridge: OCP emits `OrgEvent` on decision propose/decide/execute with decision id/status/level. Consumers can correlate decision lifecycle to approval systems by event payload and linked task/approval ids when available.
  - Full unification deferred: requires core approval/runtime schema and behavior changes outside this track.
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
`authorize()` is deterministic. OCP API wires it non-breakingly:
- If subject has active grants in the action domain, a matching grant is required (403 on deny).
- If no relevant grants configured for subject/action domain, request is allowed for backward compatibility.

Sensitive actions wired: `task:create`, `task:transition`, `decision:execute` (when actor_type/actor_id supplied; defaults to authenticated human).

## Task Views/Filters
`GET /api/ocp/tasks` filters: `status`, `department_id`/`responsible_department_id`, `requesting_department_id`, `owner_type`, `owner_id`, `overdue=true`, `my_dept=<dept_id>`.

## Decision Execution
`POST /api/ocp/decisions/{id}/execute` reconciles task IDs against provided/body/linked tasks in-org and persists reconciled `linked_task_ids`. Only approved decisions execute; ready tasks transition to in_progress with audit history.
