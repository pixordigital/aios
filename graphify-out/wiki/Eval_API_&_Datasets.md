# Eval API & Datasets

> 18 nodes · cohesion 0.18

## Key Concepts

- **eval.py** (28 connections) — `aios/api/eval.py`
- **Dataset** (11 connections) — `aios/db/models.py`
- **EvalRun** (11 connections) — `aios/db/models.py`
- **eval_agent()** (9 connections) — `aios/api/eval.py`
- **upload_dataset_csv()** (6 connections) — `aios/api/eval.py`
- **create_dataset()** (5 connections) — `aios/api/eval.py`
- **eval_history()** (5 connections) — `aios/api/eval.py`
- **list_datasets()** (5 connections) — `aios/api/eval.py`
- **EvalRequest** (3 connections) — `aios/api/eval.py`
- **EvalResult** (3 connections) — `aios/api/eval.py`
- **BaseModel** (3 connections)
- **post** (3 connections)
- **EvalCase** (2 connections) — `aios/api/eval.py`
- **UploadFile** (1 connections)
- **Eval dataset — reusable test cases for agent evaluation.** (1 connections) — `aios/db/models.py`
- **Persisted evaluation run.** (1 connections) — `aios/db/models.py`
- **csv** (1 connections)
- **io** (1 connections)

## Relationships

- [Unified Search Library](Unified_Search_Library.md) (8 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (7 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (6 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (6 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (5 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (4 shared connections)
- [CRM2 Routes](CRM2_Routes.md) (2 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (2 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (2 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)

## Source Files

- `aios/api/eval.py`
- `aios/db/models.py`

## Audit Trail

- EXTRACTED: 50 (70%)
- INFERRED: 21 (30%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*