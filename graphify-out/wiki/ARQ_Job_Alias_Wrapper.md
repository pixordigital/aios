# ARQ Job Alias Wrapper

> 24 nodes · cohesion 0.12

## Key Concepts

- **test_worker_registry.py** (19 connections) — `tests/test_worker_registry.py`
- **_registered_names()** (9 connections) — `tests/test_worker_registry.py`
- **_aliased()** (6 connections) — `aios/tasks/worker.py`
- **_registry()** (5 connections) — `aios/tasks/worker.py`
- **WorkerSettings** (5 connections) — `aios/tasks/worker.py`
- **test_alias_wrapper_delegates()** (3 connections) — `tests/test_worker_registry.py`
- **test_budget_alert_job_noops_without_org()** (3 connections) — `tests/test_worker_registry.py`
- **test_budget_alert_job_registered()** (3 connections) — `tests/test_worker_registry.py`
- **test_phantom_jobs_still_unregistered()** (3 connections) — `tests/test_worker_registry.py`
- **test_registry_keeps_originals()** (3 connections) — `tests/test_worker_registry.py`
- **test_all_qualified_enqueue_names_resolve()** (2 connections) — `tests/test_worker_registry.py`
- **test_bare_names_still_resolve()** (2 connections) — `tests/test_worker_registry.py`
- **test_process_inbound_registered_bare()** (2 connections) — `tests/test_worker_registry.py`
- **test_process_inbound_registered_qualified()** (2 connections) — `tests/test_worker_registry.py`
- **test_registry_does_not_mutate_originals()** (2 connections) — `tests/test_worker_registry.py`
- **wrapper()** (1 connections) — `aios/tasks/worker.py`
- **Register fn under an alternate name. ARQ keys its function registry on…** (1 connections) — `aios/tasks/worker.py`
- **Every job registered under its bare name and its qualified name. Enqueue sites…** (1 connections) — `aios/tasks/worker.py`
- **ARQ worker function registry tests. Regression: enqueue sites pass fully-…** (1 connections) — `tests/test_worker_registry.py`
- **A malformed payload must not raise out of the worker.** (1 connections) — `tests/test_worker_registry.py`
- **Both the original and the alias must be callable.** (1 connections) — `tests/test_worker_registry.py`
- **Documents known dead enqueues so they surface instead of vanishing. limits.py…** (1 connections) — `tests/test_worker_registry.py`
- **Regression: limits.py enqueued budget_alert_job for months while no such…** (1 connections) — `tests/test_worker_registry.py`
- **sample()** (1 connections) — `tests/test_worker_registry.py`

## Relationships

- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (4 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (2 shared connections)
- [DB Engine & Session](DB_Engine_&_Session.md) (1 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (1 shared connections)
- [LLM Retry & Inbound Processing](LLM_Retry_&_Inbound_Processing.md) (1 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (1 shared connections)

## Source Files

- `aios/tasks/worker.py`
- `tests/test_worker_registry.py`

## Audit Trail

- EXTRACTED: 41 (93%)
- INFERRED: 3 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*