# Evolution Webhook Inbound

> 33 nodes · cohesion 0.11

## Key Concepts

- **whatsapp_guard.py** (29 connections) — `aios/core/whatsapp_guard.py`
- **evolution_webhook.py** (28 connections) — `aios/api/evolution_webhook.py`
- **evolution_webhook()** (18 connections) — `aios/api/evolution_webhook.py`
- **guard_send()** (12 connections) — `aios/core/whatsapp_guard.py`
- **_store_contact()** (6 connections) — `aios/core/whatsapp_guard.py`
- **can_send()** (5 connections) — `aios/core/whatsapp_guard.py`
- **_get_evolution_api_key()** (4 connections) — `aios/api/evolution_webhook.py`
- **_parse_message()** (4 connections) — `aios/api/evolution_webhook.py`
- **is_opt_out()** (4 connections) — `aios/core/whatsapp_guard.py`
- **persist_opt_in()** (4 connections) — `aios/core/whatsapp_guard.py`
- **persist_opt_out()** (4 connections) — `aios/core/whatsapp_guard.py`
- **record_opt_out()** (4 connections) — `aios/core/whatsapp_guard.py`
- **_global_quota()** (3 connections) — `aios/core/whatsapp_guard.py`
- **human_handover_needed()** (3 connections) — `aios/core/whatsapp_guard.py`
- **is_opt_in()** (3 connections) — `aios/core/whatsapp_guard.py`
- **record_opt_in()** (3 connections) — `aios/core/whatsapp_guard.py`
- **_warmup_limits()** (3 connections) — `aios/core/whatsapp_guard.py`
- **verify_evolution_webhook()** (2 connections) — `aios/api/evolution_webhook.py`
- **check_opt_out()** (2 connections) — `aios/core/whatsapp_guard.py`
- **has_spam_signals()** (2 connections) — `aios/core/whatsapp_guard.py`
- **is_duplicate()** (2 connections) — `aios/core/whatsapp_guard.py`
- **record_global_send()** (2 connections) — `aios/core/whatsapp_guard.py`
- **record_send()** (2 connections) — `aios/core/whatsapp_guard.py`
- **test_parse_message_types()** (2 connections) — `tests/test_whatsapp_webhook.py`
- **post** (1 connections)
- *... and 8 more nodes in this community*

## Relationships

- [Evolution Channel (Baileys+Meta)](Evolution_Channel_Baileys+Meta.md) (6 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (5 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (4 shared connections)
- [Evolution Webhook Signature Auth](Evolution_Webhook_Signature_Auth.md) (4 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (3 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (3 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (3 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (3 shared connections)
- [Discord Webhook](Discord_Webhook.md) (2 shared connections)
- [Cron Scheduler & Durable Guard](Cron_Scheduler_&_Durable_Guard.md) (2 shared connections)
- [Admin Fleet & DLQ](Admin_Fleet_&_DLQ.md) (2 shared connections)
- [Settings & Channel Health](Settings_&_Channel_Health.md) (1 shared connections)

## Source Files

- `aios/api/evolution_webhook.py`
- `aios/core/whatsapp_guard.py`
- `tests/test_whatsapp_webhook.py`

## Audit Trail

- EXTRACTED: 96 (96%)
- INFERRED: 4 (4%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*