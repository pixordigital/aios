# Voice API & Call Placement

> 19 nodes · cohesion 0.18

## Key Concepts

- **api/voice.py** (35 connections) — `aios/api/voice.py`
- **track_usage()** (15 connections) — `aios/core/limits.py`
- **call()** (12 connections) — `aios/api/voice.py`
- **webhook()** (11 connections) — `aios/api/voice.py`
- **room()** (7 connections) — `aios/api/voice.py`
- **say()** (7 connections) — `aios/api/voice.py`
- **_channel_config()** (6 connections) — `aios/api/voice.py`
- **post** (4 connections)
- **CallRequest** (3 connections) — `aios/api/voice.py`
- **BaseModel** (3 connections)
- **RoomRequest** (3 connections) — `aios/api/voice.py`
- **SayRequest** (3 connections) — `aios/api/voice.py`
- **🟡 Observações (não bloqueia, mas recomenda)** (3 connections) — `REUNIAO_SWE_CYBERSEC_2026_09_11.md`
- **providers()** (1 connections) — `aios/api/voice.py`
- **Request** (1 connections)
- **Voice API — TTS, chamadas outbound (SDR/support), webhook inbound.** (1 connections) — `aios/api/voice.py`
- **Sala voz realtime (LiveKit streaming). Retorna wss + token pro browser/telefone…** (1 connections) — `aios/api/voice.py`
- **Inbound do bridge SIP: {from, text?, audio_base64?, agent_id?, channel_id?}.** (1 connections) — `aios/api/voice.py`
- **Atomically increment usage counters — prevents double-counting on concurrent…** (1 connections) — `aios/core/limits.py`

## Relationships

- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (11 shared connections)
- [IVR, PII Redaction & Call Routing](IVR,_PII_Redaction_&_Call_Routing.md) (8 shared connections)
- [Approvals & Auth Dependencies](Approvals_&_Auth_Dependencies.md) (8 shared connections)
- [Analytics, Proactive Alerts & pgvector](Analytics,_Proactive_Alerts_&_pgvector.md) (6 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (4 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (3 shared connections)
- [Discord Webhook](Discord_Webhook.md) (2 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (2 shared connections)
- [Telemetry, Triggers & Org Export](Telemetry,_Triggers_&_Org_Export.md) (2 shared connections)
- [Agents & Conversations API](Agents_&_Conversations_API.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (1 shared connections)
- [Unified Search Library](Unified_Search_Library.md) (1 shared connections)

## Source Files

- `REUNIAO_SWE_CYBERSEC_2026_09_11.md`
- `aios/api/voice.py`
- `aios/core/limits.py`

## Audit Trail

- EXTRACTED: 70 (80%)
- INFERRED: 18 (20%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*