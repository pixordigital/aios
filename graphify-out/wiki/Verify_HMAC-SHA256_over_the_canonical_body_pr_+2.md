# Verify HMAC-SHA256 over the canonical body (pr +2

> 8 nodes · cohesion 0.32

## Key Concepts

- **test_evolution_e2e.py** (9 connections) — `tests/test_evolution_e2e.py`
- **_verify_evolution_sig()** (7 connections) — `aios/api/evolution_webhook.py`
- **TranscribeTool** (6 connections) — `aios/tools/transcribe.py`
- **test_evolution_full_loop()** (2 connections) — `tests/test_evolution_e2e.py`
- **test_transcribe_tool_exists()** (2 connections) — `tests/test_evolution_e2e.py`
- **Verify HMAC-SHA256 over the canonical body (proxy-fronted deployments).** (1 connections) — `aios/api/evolution_webhook.py`
- **test_automation_templates()** (1 connections) — `tests/test_evolution_e2e.py`
- **test_knowledge_search_endpoint()** (1 connections) — `tests/test_evolution_e2e.py`

## Relationships

- [Evolution Webhook Signature Auth](Evolution_Webhook_Signature_Auth.md) (3 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (2 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (2 shared connections)
- [Evolution Webhook Inbound](Evolution_Webhook_Inbound.md) (1 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (1 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (1 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)

## Source Files

- `aios/api/evolution_webhook.py`
- `aios/tools/transcribe.py`
- `tests/test_evolution_e2e.py`

## Audit Trail

- EXTRACTED: 18 (90%)
- INFERRED: 2 (10%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*