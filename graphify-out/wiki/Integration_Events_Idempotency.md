# Integration Events Idempotency

> 25 nodes · cohesion 0.14

## Key Concepts

- **routes.py** (35 connections) — `aios/integrations/arvo/routes.py`
- **ingest_event()** (10 connections) — `aios/integrations/arvo/routes.py`
- **IntegrationEvent** (9 connections) — `aios/db/models.py`
- **_require_auth()** (6 connections) — `aios/integrations/arvo/routes.py`
- **_handle_commitment_at_risk()** (5 connections) — `aios/integrations/arvo/routes.py`
- **ArvoEvent** (4 connections) — `aios/integrations/arvo/routes.py`
- **_db_persist_nonce()** (4 connections) — `aios/integrations/arvo/routes.py`
- **_forget_nonce()** (3 connections) — `aios/integrations/arvo/auth.py`
- **ContextRequest** (3 connections) — `aios/integrations/arvo/routes.py`
- **_db_claim_event()** (3 connections) — `aios/integrations/arvo/routes.py`
- **_db_complete_event()** (3 connections) — `aios/integrations/arvo/routes.py`
- **_db_get_event()** (3 connections) — `aios/integrations/arvo/routes.py`
- **_db_release_event()** (3 connections) — `aios/integrations/arvo/routes.py`
- **health_probe()** (3 connections) — `aios/integrations/arvo/routes.py`
- **post** (3 connections)
- **_get_idempotent()** (2 connections) — `aios/integrations/arvo/routes.py`
- **health()** (2 connections) — `aios/integrations/arvo/routes.py`
- **BaseModel** (2 connections)
- **_require_enabled()** (2 connections) — `aios/integrations/arvo/routes.py`
- **_store_idempotent()** (2 connections) — `aios/integrations/arvo/routes.py`
- **Idempotency log para POST /events — deduplica por Idempotency-Key.** (1 connections) — `aios/db/models.py`
- **Request** (1 connections)
- **Rotas de integração ARVO ↔ AIOS (Fase 1C/2 + Fase payload + Fase persist). HMAC…** (1 connections) — `aios/integrations/arvo/routes.py`
- **Phase 4 slice: commitment.at_risk → audit + enqueue agent run → outbox…** (1 connections) — `aios/integrations/arvo/routes.py`
- **Insert nonce; False means duplicate, None means persistence unavailable.** (1 connections) — `aios/integrations/arvo/routes.py`

## Relationships

- [Unified Search Library](Unified_Search_Library.md) (6 shared connections)
- [ARVO Auth & Nonces](ARVO_Auth_&_Nonces.md) (6 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (3 shared connections)
- [api-contract/SKILL.md +2](api-contract-SKILL.md_+2.md) (2 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (2 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (1 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (1 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)
- [SPARC Workflow Engine](SPARC_Workflow_Engine.md) (1 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (1 shared connections)

## Source Files

- `aios/db/models.py`
- `aios/integrations/arvo/auth.py`
- `aios/integrations/arvo/routes.py`

## Audit Trail

- EXTRACTED: 65 (93%)
- INFERRED: 5 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*