# Voice Call Tool Tests

> 19 nodes · cohesion 0.18

## Key Concepts

- **TestVoice** (20 connections) — `tests/test_voice.py`
- **AsyncClient** (13 connections)
- **VoiceCallTool** (7 connections) — `aios/tools/voice_call.py`
- **.run()** (6 connections) — `aios/tools/voice_call.py`
- **.test_call_rejects_custom_agent()** (3 connections) — `tests/test_voice.py`
- **.test_call_queued_without_bridge()** (2 connections) — `tests/test_voice.py`
- **.test_call_rejects_bad_agent()** (2 connections) — `tests/test_voice.py`
- **.test_channel_test_voice()** (2 connections) — `tests/test_voice.py`
- **.test_providers()** (2 connections) — `tests/test_voice.py`
- **.test_providers_requires_auth()** (2 connections) — `tests/test_voice.py`
- **.test_room_409_without_livekit()** (2 connections) — `tests/test_voice.py`
- **.test_room_rejects_bad_agent()** (2 connections) — `tests/test_voice.py`
- **.test_room_requires_auth()** (2 connections) — `tests/test_voice.py`
- **.test_say_no_provider()** (2 connections) — `tests/test_voice.py`
- **.test_say_validation()** (2 connections) — `tests/test_voice.py`
- **.test_voice_tool_validation()** (2 connections) — `tests/test_voice.py`
- **.test_webhook_rejects_empty()** (2 connections) — `tests/test_voice.py`
- **.test_webhook_rejects_no_secret()** (2 connections) — `tests/test_voice.py`
- **.test_tool_registered()** (1 connections) — `tests/test_voice.py`

## Relationships

- [IVR, PII Redaction & Call Routing](IVR,_PII_Redaction_&_Call_Routing.md) (4 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (2 shared connections)
- [Inbox & Org Lifecycle API](Inbox_&_Org_Lifecycle_API.md) (2 shared connections)
- [Channels API & Evolution Instances](Channels_API_&_Evolution_Instances.md) (1 shared connections)
- [JWT, Secrets & Artifact Core](JWT,_Secrets_&_Artifact_Core.md) (1 shared connections)
- [Secrets Encryption](Secrets_Encryption.md) (1 shared connections)
- [Voice API & Call Placement](Voice_API_&_Call_Placement.md) (1 shared connections)

## Source Files

- `aios/tools/voice_call.py`
- `tests/test_voice.py`

## Audit Trail

- EXTRACTED: 42 (93%)
- INFERRED: 3 (7%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*