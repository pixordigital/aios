# Storage Backends

> 19 nodes · cohesion 0.14

## Key Concepts

- **core/storage.py** (24 connections) — `aios/core/storage.py`
- **StorageBackend** (10 connections) — `aios/core/storage.py`
- **backend()** (9 connections) — `aios/core/storage.py`
- **LocalStorage** (7 connections) — `aios/core/storage.py`
- **_get_backend()** (5 connections) — `aios/core/storage.py`
- **ensure_storage()** (3 connections) — `aios/core/storage.py`
- **ABC** (2 connections)
- **.delete()** (2 connections) — `aios/core/storage.py`
- **.read()** (2 connections) — `aios/core/storage.py`
- **.save()** (2 connections) — `aios/core/storage.py`
- **.delete()** (1 connections) — `aios/core/storage.py`
- **.read()** (1 connections) — `aios/core/storage.py`
- **.save()** (1 connections) — `aios/core/storage.py`
- **Storage manager — file upload, listing, retrieval for agents. Supports local…** (1 connections) — `aios/core/storage.py`
- **Abstract storage backend.** (1 connections) — `aios/core/storage.py`
- **Save content, return storage path/key.** (1 connections) — `aios/core/storage.py`
- **Read content from storage path.** (1 connections) — `aios/core/storage.py`
- **Delete content. Returns True if existed.** (1 connections) — `aios/core/storage.py`
- **Local filesystem storage.** (1 connections) — `aios/core/storage.py`

## Relationships

- [Artifact Content & Storage](Artifact_Content_&_Storage.md) (5 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (3 shared connections)
- [Voice Recordings & Transcription](Voice_Recordings_&_Transcription.md) (3 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (3 shared connections)
- [S3 Object Put & Versioning](S3_Object_Put_&_Versioning.md) (3 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (2 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (2 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (1 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [Sandbox & Skill Loader](Sandbox_&_Skill_Loader.md) (1 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)

## Source Files

- `aios/core/storage.py`

## Audit Trail

- EXTRACTED: 51 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*