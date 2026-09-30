# Voice Webhook Inbound

> 31 nodes · cohesion 0.08

## Key Concepts

- **core/audit.py** (20 connections) — `aios/core/audit.py`
- **hashlib** (18 connections)
- **os** (17 connections)
- **voice_webhook.py** (16 connections) — `aios/api/voice_webhook.py`
- **core/license.py** (15 connections) — `aios/core/license.py`
- **hmac** (15 connections)
- **voice_webhook()** (9 connections) — `aios/api/voice_webhook.py`
- **test_kokoro_voices.py** (7 connections) — `tests/test_kokoro_voices.py`
- **test_whatsapp_webhook.py** (6 connections) — `tests/test_whatsapp_webhook.py`
- **webhook_validator.py** (5 connections) — `aios/core/whatsapp/webhook_validator.py`
- **_forward_to_siem()** (4 connections) — `aios/core/audit.py`
- **heartbeat_payload()** (4 connections) — `aios/core/license.py`
- **voice_webhook_verify()** (2 connections) — `aios/api/voice_webhook.py`
- **_image_digest()** (2 connections) — `aios/core/license.py`
- **_public_key_fp()** (2 connections) — `aios/core/license.py`
- **send_heartbeat()** (2 connections) — `aios/core/license.py`
- **verify_license_jwt()** (2 connections) — `aios/core/license.py`
- **post** (1 connections)
- **Request** (1 connections)
- **Voice webhook — LiveKit / Twilio inbound call events.** (1 connections) — `aios/api/voice_webhook.py`
- **Health check / verification endpoint.** (1 connections) — `aios/api/voice_webhook.py`
- **Receive voice events from LiveKit/Twilio → dispatch to agent.** (1 connections) — `aios/api/voice_webhook.py`
- **Audit log helper — records sensitive operations for security monitoring.…** (1 connections) — `aios/core/audit.py`
- **Forward audit log entry to configured SIEM webhook.** (1 connections) — `aios/core/audit.py`
- **License — JWT 24h + heartbeat 6h + tamper detection. Control Plane assina JWT…** (1 connections) — `aios/core/license.py`
- *... and 6 more nodes in this community*

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (10 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (7 shared connections)
- [Discord Webhook](Discord_Webhook.md) (6 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (6 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (6 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (3 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (3 shared connections)
- [Evolution Webhook Inbound](Evolution_Webhook_Inbound.md) (3 shared connections)
- [Structured Output & Traces](Structured_Output_&_Traces.md) (3 shared connections)
- [Automation Triggers & Workflow DAG](Automation_Triggers_&_Workflow_DAG.md) (2 shared connections)
- [SPARC Workflow Engine](SPARC_Workflow_Engine.md) (2 shared connections)
- [Billing, Budgets & Stripe Checkout](Billing,_Budgets_&_Stripe_Checkout.md) (2 shared connections)

## Source Files

- `aios/api/voice_webhook.py`
- `aios/core/audit.py`
- `aios/core/license.py`
- `aios/core/whatsapp/webhook_validator.py`
- `tests/test_kokoro_voices.py`
- `tests/test_whatsapp_webhook.py`

## Audit Trail

- EXTRACTED: 119 (97%)
- INFERRED: 4 (3%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*