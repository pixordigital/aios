# SPARC Workflow Engine

> 14 nodes · cohesion 0.22

## Key Concepts

- **datetime** (30 connections)
- **SparcWorkflow** (13 connections) — `aios/db/models.py`
- **core/sparc.py** (12 connections) — `aios/core/sparc.py`
- **SparcEngine** (11 connections) — `aios/core/sparc.py`
- **.advance()** (4 connections) — `aios/core/sparc.py`
- **.list()** (4 connections) — `aios/core/sparc.py`
- **.create()** (3 connections) — `aios/core/sparc.py`
- **.fail_phase()** (3 connections) — `aios/core/sparc.py`
- **.get()** (3 connections) — `aios/core/sparc.py`
- **.phase_instruction()** (2 connections) — `aios/core/sparc.py`
- **SPARC workflow engine — Spec, Pseudocode, Architect, Refine, Code, Test. Ruflo…** (1 connections) — `aios/core/sparc.py`
- **Create and advance SPARC workflows.** (1 connections) — `aios/core/sparc.py`
- **Complete current phase with output and move to next. Returns workflow.** (1 connections) — `aios/core/sparc.py`
- **SPARC methodology workflow template — Spec, Pseudocode, Architect, Refine,…** (1 connections) — `aios/db/models.py`

## Relationships

- [Unified Search Library](Unified_Search_Library.md) (9 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (7 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (4 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (3 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (2 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (2 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (2 shared connections)
- [Secrets Envelope](Secrets_Envelope.md) (2 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (2 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (1 shared connections)
- [Auth Token Factory](Auth_Token_Factory.md) (1 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (1 shared connections)

## Source Files

- `aios/core/sparc.py`
- `aios/db/models.py`

## Audit Trail

- EXTRACTED: 66 (96%)
- INFERRED: 3 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*