# Autoscaling & Agent Metrics

> 37 nodes · cohesion 0.08

## Key Concepts

- **worker.py** (39 connections) — `aios/tasks/worker.py`
- **AgentMetric** (22 connections) — `aios/db/models.py`
- **learning_worker.py** (20 connections) — `aios/tasks/learning_worker.py`
- **AgentLearning** (14 connections) — `aios/db/models.py`
- **queue.py** (13 connections) — `aios/tasks/queue.py`
- **_learning_job_wrapper()** (9 connections) — `aios/tasks/worker.py`
- **eval_review_job()** (8 connections) — `aios/tasks/learning_worker.py`
- **memory_consolidation_job()** (8 connections) — `aios/tasks/learning_worker.py`
- **optimization_review_job()** (8 connections) — `aios/tasks/learning_worker.py`
- **pattern_extraction_job()** (8 connections) — `aios/tasks/learning_worker.py`
- **canary_rollback_job()** (5 connections) — `aios/tasks/worker.py`
- **_parse_redis()** (4 connections) — `aios/tasks/queue.py`
- **autoscaling.py** (3 connections) — `aios/core/autoscaling.py`
- **_parse_redis()** (3 connections) — `aios/tasks/worker.py`
- **_eval_review_cron()** (2 connections) — `aios/tasks/worker.py`
- **_memory_consolidation_cron()** (2 connections) — `aios/tasks/worker.py`
- **_optimization_review_cron()** (2 connections) — `aios/tasks/worker.py`
- **_pattern_extraction_cron()** (2 connections) — `aios/tasks/worker.py`
- **run()** (2 connections) — `aios/tasks/worker.py`
- **arq** (2 connections)
- **arq_connections** (2 connections)
- **Per-agent performance metrics — aggregated hourly.** (1 connections) — `aios/db/models.py`
- **Agent learning records — what worked, what didn't, for continuous improvement.…** (1 connections) — `aios/db/models.py`
- **Background learning worker — pattern extraction, memory consolidation,…** (1 connections) — `aios/tasks/learning_worker.py`
- **Review recent eval runs with low scores and create learnings.** (1 connections) — `aios/tasks/learning_worker.py`
- *... and 12 more nodes in this community*

## Relationships

- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (12 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (10 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (8 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (5 shared connections)
- [Agent DB Reflections](Agent_DB_Reflections.md) (5 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (5 shared connections)
- [Transactional Outbox](Transactional_Outbox.md) (4 shared connections)
- [ARQ Job Alias Wrapper](ARQ_Job_Alias_Wrapper.md) (4 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (3 shared connections)
- [Agents CRUD & Deploy](Agents_CRUD_&_Deploy.md) (3 shared connections)
- [Structured Output & Traces](Structured_Output_&_Traces.md) (2 shared connections)
- [Skill Store](Skill_Store.md) (2 shared connections)

## Source Files

- `aios/core/autoscaling.py`
- `aios/db/models.py`
- `aios/tasks/learning_worker.py`
- `aios/tasks/queue.py`
- `aios/tasks/worker.py`

## Audit Trail

- EXTRACTED: 112 (80%)
- INFERRED: 28 (20%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*