# Unified Search Library

> 44 nodes · cohesion 0.09

## Key Concepts

- **models.py** (128 connections) — `aios/db/models.py`
- **Base** (54 connections) — `aios/db/engine.py`
- **TimestampMixin** (45 connections) — `aios/db/models.py`
- **OrgScopedMixin** (20 connections) — `aios/db/models.py`
- **WorkflowNode** (18 connections) — `aios/db/models.py`
- **Artifact** (17 connections) — `aios/db/models.py`
- **Budget** (17 connections) — `aios/db/models.py`
- **uuid** (17 connections)
- **VoiceRecording** (16 connections) — `aios/db/models.py`
- **core/swarm.py** (14 connections) — `aios/core/swarm.py`
- **AuditLog** (14 connections) — `aios/db/models.py`
- **Tool** (14 connections) — `aios/db/models.py`
- **core/library.py** (11 connections) — `aios/core/library.py`
- **WhatsappContact** (10 connections) — `aios/db/models.py`
- **SwarmMessage** (9 connections) — `aios/db/models.py`
- **TeamSwarmConfig** (9 connections) — `aios/db/models.py`
- **SalesGoal** (8 connections) — `aios/db/models.py`
- **SparcPhaseLog** (7 connections) — `aios/db/models.py`
- **WhatsappEvent** (7 connections) — `aios/db/models.py`
- **OptimizationRecord** (6 connections) — `aios/db/models.py`
- **IntegrationNonce** (5 connections) — `aios/db/models.py`
- **LearningJob** (5 connections) — `aios/db/models.py`
- **OAuthAccount** (5 connections) — `aios/db/models.py`
- **_org_before_flush()** (3 connections) — `aios/db/models.py`
- **WorkflowExecutionLog** (3 connections) — `aios/db/models.py`
- *... and 19 more nodes in this community*

## Relationships

- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (30 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (24 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (23 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (18 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (16 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (11 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (10 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (10 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (9 shared connections)
- [SPARC Workflow Engine](SPARC_Workflow_Engine.md) (9 shared connections)
- [Agent DB Reflections](Agent_DB_Reflections.md) (9 shared connections)
- [Eval API & Datasets](Eval_API_&_Datasets.md) (8 shared connections)

## Source Files

- `aios/api/deps.py`
- `aios/core/library.py`
- `aios/core/swarm.py`
- `aios/db/engine.py`
- `aios/db/models.py`

## Audit Trail

- EXTRACTED: 345 (87%)
- INFERRED: 52 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*