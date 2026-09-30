# AsyncSession Delegation

> 53 nodes · cohesion 0.06

## Key Concepts

- **conftest.py** (30 connections) — `tests/conftest.py`
- **SQLAlchemyBackend** (23 connections) — `aios/db/backends/sqlalchemy_backend.py`
- **._sess()** (12 connections) — `aios/db/backends/sqlalchemy_backend.py`
- **fixture** (9 connections)
- **test_execute_contract.py** (9 connections) — `tests/test_execute_contract.py`
- **test_db_session()** (7 connections) — `tests/conftest.py`
- **test_user()** (6 connections) — `tests/conftest.py`
- **TestArtifactOrgIsolation** (6 connections) — `tests/test_security.py`
- **async_client()** (5 connections) — `tests/conftest.py`
- **AsyncSession** (5 connections)
- **test_org()** (5 connections) — `tests/conftest.py`
- **.test_get_artifact_content_org_enforced()** (5 connections) — `tests/test_security.py`
- **auth_client()** (4 connections) — `tests/conftest.py`
- **auth_headers()** (4 connections) — `tests/conftest.py`
- **test_session()** (4 connections) — `tests/conftest.py`
- **.execute()** (3 connections) — `aios/db/backends/sqlalchemy_backend.py`
- **.get()** (3 connections) — `aios/db/backends/sqlalchemy_backend.py`
- **.health()** (3 connections) — `aios/db/backends/sqlalchemy_backend.py`
- **_fresh_db()** (3 connections) — `tests/conftest.py`
- **test_engine()** (3 connections) — `tests/conftest.py`
- **test_no_wrapper_execute_with_positional_params()** (3 connections) — `tests/test_execute_contract.py`
- **_wrapper_execute_calls()** (3 connections) — `tests/test_execute_contract.py`
- **.approve()** (2 connections) — `aios/core/approval.py`
- **_db_approve()** (2 connections) — `aios/core/approval.py`
- **Any** (2 connections)
- *... and 28 more nodes in this community*

## Relationships

- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (5 shared connections)
- [Agent DB Knowledge & Learning](Agent_DB_Knowledge_&_Learning.md) (5 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (5 shared connections)
- [Usage Forecast & ARVO Client](Usage_Forecast_&_ARVO_Client.md) (5 shared connections)
- [DB Engine & Session](DB_Engine_&_Session.md) (3 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (3 shared connections)
- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [ApprovalManager +2](ApprovalManager_+2.md) (1 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (1 shared connections)
- [Vector Extension & CRM Versions](Vector_Extension_&_CRM_Versions.md) (1 shared connections)
- [Admin Fleet & DLQ](Admin_Fleet_&_DLQ.md) (1 shared connections)

## Source Files

- `aios/core/approval.py`
- `aios/db/backends/sqlalchemy_backend.py`
- `tests/conftest.py`
- `tests/test_execute_contract.py`
- `tests/test_security.py`

## Audit Trail

- EXTRACTED: 105 (87%)
- INFERRED: 16 (13%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*