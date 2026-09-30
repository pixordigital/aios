# CRM2 Routes

> 10 nodes · cohesion 0.33

## Key Concepts

- **get_provider()** (28 connections) — `aios/core/providers.py`
- **get_org_secret()** (12 connections) — `aios/core/org_settings.py`
- **org_settings.py** (9 connections) — `aios/core/org_settings.py`
- **model_to_secret_key()** (6 connections) — `aios/core/org_settings.py`
- **handle_llm_chat()** (5 connections) — `aios/main.py`
- **handle_llm_chat_stream()** (5 connections) — `aios/main.py`
- **get_org_secret_async()** (4 connections) — `aios/core/org_settings.py`
- **mask_key()** (3 connections) — `aios/core/org_settings.py`
- **resolve_api_key()** (3 connections) — `aios/core/org_settings.py`
- **Route to correct provider based on model name prefix.** (1 connections) — `aios/core/providers.py`

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (10 shared connections)
- [Anthropic LLM Provider](Anthropic_LLM_Provider.md) (6 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (5 shared connections)
- [Artifact Content & Storage](Artifact_Content_&_Storage.md) (5 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (3 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (3 shared connections)
- [SSE Streaming Endpoint](SSE_Streaming_Endpoint.md) (3 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (2 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (2 shared connections)
- [Eval API & Datasets](Eval_API_&_Datasets.md) (2 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (2 shared connections)
- [CyberSec Meeting & Prod Readiness](CyberSec_Meeting_&_Prod_Readiness.md) (1 shared connections)

## Source Files

- `aios/core/org_settings.py`
- `aios/core/providers.py`
- `aios/main.py`

## Audit Trail

- EXTRACTED: 57 (93%)
- INFERRED: 4 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*