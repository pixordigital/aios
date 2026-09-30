# Transactional Outbox

> 27 nodes · cohesion 0.12

## Key Concepts

- **test_suite_integration.py** (19 connections) — `tests/test_suite_integration.py`
- **publisher.py** (17 connections) — `aios/integrations/arvo/publisher.py`
- **IntegrationOutbox** (11 connections) — `aios/db/models.py`
- **send_event()** (9 connections) — `aios/integrations/arvo/client.py`
- **enqueue_outbox()** (9 connections) — `aios/integrations/arvo/publisher.py`
- **integration_outbox_flush()** (9 connections) — `aios/integrations/arvo/publisher.py`
- **flush_outbox()** (7 connections) — `aios/integrations/arvo/publisher.py`
- **test_outbox_single_flush_records_failed_attempts()** (7 connections) — `tests/test_suite_integration.py`
- **_claim_rows()** (5 connections) — `aios/integrations/arvo/publisher.py`
- **_deliver()** (5 connections) — `aios/integrations/arvo/publisher.py`
- **test_commitment_processing_is_org_scoped()** (5 connections) — `tests/test_suite_integration.py`
- **integration_outbox_cron()** (2 connections) — `aios/tasks/worker.py`
- **integration_outbox_flush_job()** (2 connections) — `aios/tasks/worker.py`
- **no_enqueue()** (2 connections) — `tests/test_suite_integration.py`
- **test_suite_control_center_exists()** (2 connections) — `tests/test_suite_integration.py`
- **test_suite_imports()** (2 connections) — `tests/test_suite_integration.py`
- **Transactional outbox — pending events for async publish to peer.** (1 connections) — `aios/db/models.py`
- **POST /events idempotente. Retry 3× em 5xx/timeout.** (1 connections) — `aios/integrations/arvo/client.py`
- **Outbox publisher — pending → HTTP to ARVO with retry.** (1 connections) — `aios/integrations/arvo/publisher.py`
- **Send claimed rows to peer. Returns send counters.** (1 connections) — `aios/integrations/arvo/publisher.py`
- **ARQ job: flush one id or batch of pending rows.** (1 connections) — `aios/integrations/arvo/publisher.py`
- **Insert durable pending row and best-effort schedule immediate flush.** (1 connections) — `aios/integrations/arvo/publisher.py`
- **Suite AIOS+ARVO — HMAC cross, events, suite health.** (1 connections) — `tests/test_suite_integration.py`
- **Both services importable as suite.** (1 connections) — `tests/test_suite_integration.py`
- **Control Center route exists as suite dashboard.** (1 connections) — `tests/test_suite_integration.py`
- *... and 2 more nodes in this community*

## Relationships

- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (6 shared connections)
- [ARVO Auth & Nonces](ARVO_Auth_&_Nonces.md) (6 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (5 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (4 shared connections)
- [Autoscaling & Agent Metrics](Autoscaling_&_Agent_Metrics.md) (4 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (3 shared connections)
- [_headers() +2](_headers_+2.md) (2 shared connections)
- [test_event_retry_uses_fresh_hmac_nonce() +2](test_event_retry_uses_fresh_hmac_nonce_+2.md) (2 shared connections)
- [.agents() +2](agents_+2.md) (1 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [DB Engine & Session](DB_Engine_&_Session.md) (1 shared connections)

## Source Files

- `aios/db/models.py`
- `aios/integrations/arvo/client.py`
- `aios/integrations/arvo/publisher.py`
- `aios/tasks/worker.py`
- `tests/test_suite_integration.py`

## Audit Trail

- EXTRACTED: 69 (85%)
- INFERRED: 12 (15%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*