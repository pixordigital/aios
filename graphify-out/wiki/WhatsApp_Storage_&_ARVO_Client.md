# WhatsApp Storage & ARVO Client

> 33 nodes · cohesion 0.09

## Key Concepts

- **httpx** (42 connections)
- **pytest** (35 connections)
- **arvo/client.py** (12 connections) — `aios/integrations/arvo/client.py`
- **test_registration_closed.py** (9 connections) — `tests/test_registration_closed.py`
- **test_errors.py** (7 connections) — `tests/test_errors.py`
- **test_voice.py** (7 connections) — `tests/test_voice.py`
- **test_config.py** (6 connections) — `tests/test_config.py`
- **AsyncClient** (4 connections)
- **asyncio** (4 connections)
- **TestWorkflowsAsync** (4 connections) — `tests/test_workflows_async.py`
- **whatsapp/storage.py** (3 connections) — `aios/core/whatsapp/storage.py`
- **test_agents.py** (3 connections) — `tests/test_agents.py`
- **asyncio** (3 connections)
- **test_api_register_blocked_when_closed()** (3 connections) — `tests/test_registration_closed.py`
- **test_dashboard_register_blocked_when_closed()** (3 connections) — `tests/test_registration_closed.py`
- **test_oauth_blocked_when_closed()** (3 connections) — `tests/test_registration_closed.py`
- **test_register_allowed_when_open()** (3 connections) — `tests/test_registration_closed.py`
- **test_workflows_async.py** (3 connections) — `tests/test_workflows_async.py`
- **AsyncClient** (3 connections)
- **fastapi_testclient** (2 connections)
- **test_404_route_miss()** (2 connections) — `tests/test_errors.py`
- **test_413_oversized_body()** (2 connections) — `tests/test_errors.py`
- **test_422_validation()** (2 connections) — `tests/test_errors.py`
- **.test_workflow_async_default()** (2 connections) — `tests/test_workflows_async.py`
- **.test_workflow_cycle_rejected()** (2 connections) — `tests/test_workflows_async.py`
- *... and 8 more nodes in this community*

## Relationships

- [Settings & Channel Health](Settings_&_Channel_Health.md) (6 shared connections)
- [Transactional Outbox](Transactional_Outbox.md) (4 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (4 shared connections)
- [_headers() +2](_headers_+2.md) (3 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (3 shared connections)
- [AsyncSession Delegation](AsyncSession_Delegation.md) (3 shared connections)
- [ARVO Auth & Nonces](ARVO_Auth_&_Nonces.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [IVR, PII Redaction & Call Routing](IVR,_PII_Redaction_&_Call_Routing.md) (2 shared connections)
- [Evolution Webhook Signature Auth](Evolution_Webhook_Signature_Auth.md) (2 shared connections)
- [Evolution Integration Tests](Evolution_Integration_Tests.md) (2 shared connections)
- [AIOS SDK Test Client](AIOS_SDK_Test_Client.md) (2 shared connections)

## Source Files

- `aios/core/whatsapp/storage.py`
- `aios/integrations/arvo/client.py`
- `tests/test_agents.py`
- `tests/test_config.py`
- `tests/test_errors.py`
- `tests/test_registration_closed.py`
- `tests/test_voice.py`
- `tests/test_workflows_async.py`

## Audit Trail

- EXTRACTED: 132 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*