# Hermes Feature Tests

> 17 nodes · cohesion 0.18

## Key Concepts

- **test_features.py** (21 connections) — `tests/test_features.py`
- **asyncio** (10 connections)
- **test_approval_approve_flow()** (5 connections) — `tests/test_features.py`
- **test_approval_reject_flow()** (5 connections) — `tests/test_features.py`
- **test_approval_timeout()** (3 connections) — `tests/test_features.py`
- **test_fts_hybrid_search()** (3 connections) — `tests/test_features.py`
- **test_skills_crud()** (3 connections) — `tests/test_features.py`
- **pytest_asyncio** (2 connections)
- **test_meta_agent_evaluate_and_history()** (2 connections) — `tests/test_features.py`
- **test_rubric_create_and_score()** (2 connections) — `tests/test_features.py`
- **test_rubric_unknown_returns_error()** (2 connections) — `tests/test_features.py`
- **test_rubrics_api()** (2 connections) — `tests/test_features.py`
- **Tests for Hermes/HyperAgent-inspired features. Approval mode, skills, rubrics,…** (1 connections) — `tests/test_features.py`
- **decider()** (1 connections) — `tests/test_features.py`
- **requester()** (1 connections) — `tests/test_features.py`
- **decider()** (1 connections) — `tests/test_features.py`
- **requester()** (1 connections) — `tests/test_features.py`

## Relationships

- [ApprovalManager +2](ApprovalManager_+2.md) (4 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (2 shared connections)
- [Extractor +2](Extractor_+2.md) (2 shared connections)
- [Memory Manager](Memory_Manager.md) (2 shared connections)
- [Voice API Webhook](Voice_API_Webhook.md) (2 shared connections)
- [AsyncSession Delegation](AsyncSession_Delegation.md) (1 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (1 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (1 shared connections)

## Source Files

- `tests/test_features.py`

## Audit Trail

- EXTRACTED: 35 (88%)
- INFERRED: 5 (12%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*