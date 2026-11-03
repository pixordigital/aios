# ICM-X for AIOS — architecture and rollout

Status: **foundational implementation / opt-in**. This is not a replacement for the existing AIOS workflow engine.

## Architectural boundary

ICM-X defines how workflow context and artifacts are organized. Existing AIOS components remain authoritative:

| Concern | Authority |
|---|---|
| Workflow graph, run lifecycle, retries and scheduling | Existing AIOS workflow engine + PostgreSQL + ARQ |
| Tenant, user, record and tool permissions | Existing AIOS authentication and governance |
| Stage instructions and stable references | Versioned ICM workspace |
| Per-run artifacts and provenance files | Tenant-scoped workspace storage |
| Transactional business data | PostgreSQL / authorized integrations |
| Dynamic CRM, pricing, inventory and customer state | Authorized tools/API reads, not static files |
| Queueing and concurrency | Redis + ARQ, not filesystem locks |

The filesystem/object store is a workspace abstraction, not a transaction manager, message broker, permission system, or source of truth for live business records.

## Workspace layout

A logical workspace is scoped by organization and workspace ID:

~~~text
data/
  tenants/
    <org_id>/
      workspaces/
        <workspace_id>/
          L0/WORKSPACE.md
          L1/ROUTES.md
          L2/stages/<stage_id>/
            CONTEXT.md
            stage.yaml
          L3/static/
          runs/<run_id>/
            input/
            artifacts/
            provenance/
~~~

- L0: workspace identity and navigation.
- L1: task routing.
- L2: stage-specific contract and instructions.
- L3/static: stable company knowledge, policies and examples.
- Dynamic business context is fetched from authorized systems at execution time.
- Each run has an isolated directory. Secrets never belong in the workspace.

For multi-container production, use the existing S3-compatible storage abstraction or a shared durable volume. Local disk is suitable only when app and worker share the same persistent volume and deployment is intentionally single-host.

## Stage contract

`stage.yaml` is a strict Pydantic contract loaded with YAML safe parsing. Unknown fields are rejected. It declares:

- Stable stage ID and semantic version.
- Execution mode: deterministic, LLM, or hybrid.
- Time, LLM-call and cost ceilings.
- Input/output schema identifiers.
- Permitted context layers and token budget.
- Allowed and denied tool names.
- Whether side effects are permitted.
- Whether approval is required.
- Retryable and non-retryable error categories.

The manifest does **not** grant tool permission. Runtime authorization must intersect the stage allowlist with agent and user permissions and existing AIOS governance. Side-effecting tools continue enforcing authorization at the tool boundary.

## Execution and reliability

Do not create a second workflow runner. Map ICM stages onto existing AIOS workflow nodes and ARQ jobs incrementally. PostgreSQL remains authoritative for run and stage state. Retries must be idempotent for external side effects.

The initial module provides:
- Strict stage-manifest validation.
- Stable manifest fingerprints for future dependency/cache keys.
- Tenant-scoped workspace path construction.
- Explicit context-file selection, traversal protection and size limits.
- SHA-256 fingerprints for loaded context files.

It intentionally does **not** yet persist runs/approvals, execute tools, enforce authorization, implement distributed leases, cache LLM outputs, automatically rerun dependent stages, or copy live CRM/customer data into static files. Those require integration with the existing workflow, governance, database and queue layers.

## Example stage manifest

~~~yaml
id: company_research
version: 1.0.0
description: Research and normalize a prospect company
mode: llm
timeout_seconds: 60
max_llm_calls: 2
max_cost_usd: 0.03
inputs_schema: lead_research_input.v1
outputs_schema: company_research_output.v1
context:
  layers: [identity, routing, stage, static_references]
  max_context_tokens: 6000
allowed_tools: [company_lookup, web_search]
denied_tools: [crm_update, whatsapp_send]
side_effects: false
approval_required: false
retry:
  max_attempts: 2
  retry_on: [timeout, transient_provider_error, invalid_output]
  no_retry_on: [permission_denied, invalid_input]
~~~

## Deployment and rollout

This commit adds no service, database table, migration, environment variable, or change to Coolify startup. The package is inert until called.

1. Validate manifests and workspace paths in unit tests.
2. Create one versioned B2B lead-research workspace.
3. Add a thin adapter from existing workflow nodes to stage manifests.
4. Persist stage attempts, fingerprints and validation results using existing workflow-run persistence; extend schema only for a proven gap.
5. Add idempotent checkpoint/resume and dependency-aware selective reruns.
6. Bind approvals to exact artifact versions and effective permissions.
7. Benchmark against current AIOS before making ICM-X the default.

Operational acceptance criteria: existing workflow/channel tests remain green; cross-tenant and symlink traversal is rejected; invalid contracts fail closed; retries cannot duplicate WhatsApp/CRM side effects; worker restarts resume committed stage state; reference changes invalidate only dependent stages; cost, latency, tokens and verified business outcomes are measured per run.


## CI fixture note

The repository's `.env.example` keeps numeric optional settings parseable (`AIOS_CALCOM_EVENT_TYPE_ID=0`) so container smoke tests can boot without a configured Cal.com account. Replace the value with the real event-type ID only when Cal.com scheduling is enabled.


Workspace path construction validates each tenant/workspace/run identifier before filesystem access and checks symlink resolution before creating descendant directories. LLM-enabled stages must declare a positive per-stage USD cost ceiling.
