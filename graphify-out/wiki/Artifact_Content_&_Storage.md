# Artifact Content & Storage

> 14 nodes · cohesion 0.18

## Key Concepts

- **_register_syscall_handlers()** (20 connections) — `aios/main.py`
- **get_artifact_content()** (15 connections) — `aios/core/storage.py`
- **save_artifact()** (15 connections) — `aios/core/storage.py`
- **list_artifacts()** (12 connections) — `aios/core/storage.py`
- **handle_storage_list()** (3 connections) — `aios/main.py`
- **handle_storage_read()** (3 connections) — `aios/main.py`
- **handle_storage_save()** (3 connections) — `aios/main.py`
- **.run()** (2 connections) — `aios/tools/read_file.py`
- **Save a file as an artifact and return its metadata.** (1 connections) — `aios/core/storage.py`
- **Read artifact file content from backend. org_id enforced when provided —…** (1 connections) — `aios/core/storage.py`
- **List artifacts for an org, optionally filtered by conversation.** (1 connections) — `aios/core/storage.py`
- **Register handlers for each syscall type.** (1 connections) — `aios/main.py`
- **handle_memory_read()** (1 connections) — `aios/main.py`
- **handle_memory_write()** (1 connections) — `aios/main.py`

## Relationships

- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (11 shared connections)
- [Storage Backends](Storage_Backends.md) (5 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (5 shared connections)
- [CRM2 Routes](CRM2_Routes.md) (5 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (4 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (3 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (2 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (2 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (2 shared connections)
- [AsyncSession Delegation](AsyncSession_Delegation.md) (1 shared connections)
- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (1 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)

## Source Files

- `aios/core/storage.py`
- `aios/main.py`
- `aios/tools/read_file.py`

## Audit Trail

- EXTRACTED: 47 (75%)
- INFERRED: 16 (25%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*