# Evolution Integration Tests

> 28 nodes · cohesion 0.13

## Key Concepts

- **test_evolution_integration.py** (19 connections) — `tests/test_evolution_integration.py`
- **EvolutionTestClient** (18 connections) — `tests/test_evolution_integration.py`
- **run_full_test_suite()** (9 connections) — `tests/test_evolution_integration.py`
- **asyncio** (8 connections)
- **test_01_create_instance()** (5 connections) — `tests/test_evolution_integration.py`
- **test_02_get_qrcode()** (5 connections) — `tests/test_evolution_integration.py`
- **test_03_wait_for_connection()** (5 connections) — `tests/test_evolution_integration.py`
- **test_04_send_text_message()** (5 connections) — `tests/test_evolution_integration.py`
- **test_05_send_media_message()** (5 connections) — `tests/test_evolution_integration.py`
- **test_07_cleanup_instance()** (5 connections) — `tests/test_evolution_integration.py`
- **test_06_receive_webhook_simulation()** (4 connections) — `tests/test_evolution_integration.py`
- **.create_instance()** (1 connections) — `tests/test_evolution_integration.py`
- **.delete_instance()** (1 connections) — `tests/test_evolution_integration.py`
- **.get_qrcode()** (1 connections) — `tests/test_evolution_integration.py`
- **.get_status()** (1 connections) — `tests/test_evolution_integration.py`
- **.__init__()** (1 connections) — `tests/test_evolution_integration.py`
- **.send_media()** (1 connections) — `tests/test_evolution_integration.py`
- **.send_message()** (1 connections) — `tests/test_evolution_integration.py`
- **Evolution API Integration Test — tests real Evolution instance lifecycle.…** (1 connections) — `tests/test_evolution_integration.py`
- **Test creating a new Evolution instance.** (1 connections) — `tests/test_evolution_integration.py`
- **Test getting QR code for instance connection.** (1 connections) — `tests/test_evolution_integration.py`
- **Wait for WhatsApp to connect (manual scan required).** (1 connections) — `tests/test_evolution_integration.py`
- **Send a test text message to the configured test number.** (1 connections) — `tests/test_evolution_integration.py`
- **Send a test media message (image) to the configured test number.** (1 connections) — `tests/test_evolution_integration.py`
- **Simulate receiving a webhook (test webhook endpoint).** (1 connections) — `tests/test_evolution_integration.py`
- *... and 3 more nodes in this community*

## Relationships

- [evolution_client() +2](evolution_client_+2.md) (3 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (1 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (1 shared connections)
- [YouTube Todos & Workflow Comparison](YouTube_Todos_&_Workflow_Comparison.md) (1 shared connections)

## Source Files

- `tests/test_evolution_integration.py`

## Audit Trail

- EXTRACTED: 57 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*