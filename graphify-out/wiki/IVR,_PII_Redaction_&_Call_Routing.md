# IVR, PII Redaction & Call Routing

> 28 nodes · cohesion 0.12

## Key Concepts

- **core/voice.py** (21 connections) — `aios/core/voice.py`
- **place_call()** (18 connections) — `aios/core/voice.py`
- **synthesize()** (15 connections) — `aios/core/voice.py`
- **emit_usage_event()** (9 connections) — `aios/core/tracing.py`
- **redact_pii()** (8 connections) — `aios/core/pii.py`
- **redact_pii_obj()** (8 connections) — `aios/core/pii.py`
- **transcribe_audio()** (8 connections) — `aios/core/voice.py`
- **voice_config()** (8 connections) — `aios/core/voice.py`
- **pii.py** (5 connections) — `aios/core/pii.py`
- **_retell_call()** (4 connections) — `aios/core/voice.py`
- **_vapi_call()** (4 connections) — `aios/core/voice.py`
- **3. OS — Memory, Workflow, Voice, Skills (Arquiteto, 15min)** (3 connections) — `REUNIAO_TECNICA_100_AUTONOMO_VALIDACAO_2026_09_13.md`
- **ivr_synthesize()** (2 connections) — `aios/api/whatsapp.py`
- **_elevenlabs_tts()** (2 connections) — `aios/core/voice.py`
- **_openai_compat_tts()** (2 connections) — `aios/core/voice.py`
- **_redact_pii()** (2 connections) — `aios/core/voice.py`
- **.test_retell_no_creds_falls_back()** (2 connections) — `tests/test_voice.py`
- **.test_vapi_no_creds_falls_back()** (2 connections) — `tests/test_voice.py`
- **PII auto-redaction — CPF, RG, cartão, telefone -> ***. Regex sem catastrophic…** (1 connections) — `aios/core/pii.py`
- **Substitui PII por ***. Não quebra se text não for str.** (1 connections) — `aios/core/pii.py`
- **Redact recursivo para dict/list/str — uso interno tracing.** (1 connections) — `aios/core/pii.py`
- **Emit usage event to configured webhook for metered billing. Events:…** (1 connections) — `aios/core/tracing.py`
- **Voice provider layer — ElevenLabs (cloud) ou self-hosted (Coolify). Self-hosted…** (1 connections) — `aios/core/voice.py`
- **STT via whisper self-hosted (ou OpenAI fallback).** (1 connections) — `aios/core/voice.py`
- **Dispara chamada outbound. Sem bridge → queued com TTS pronto. Emits…** (1 connections) — `aios/core/voice.py`
- *... and 3 more nodes in this community*

## Relationships

- [Voice API & Call Placement](Voice_API_&_Call_Placement.md) (8 shared connections)
- [Structured Output & Traces](Structured_Output_&_Traces.md) (7 shared connections)
- [Call Router](Call_Router.md) (5 shared connections)
- [Voice Call Tool Tests](Voice_Call_Tool_Tests.md) (4 shared connections)
- [Outbound Message & Discord Channel](Outbound_Message_&_Discord_Channel.md) (3 shared connections)
- [Channel Base Interface](Channel_Base_Interface.md) (3 shared connections)
- [WhatsApp Gateway API](WhatsApp_Gateway_API.md) (2 shared connections)
- [Agent Runtime Loop](Agent_Runtime_Loop.md) (2 shared connections)
- [WhatsApp Storage & ARVO Client](WhatsApp_Storage_&_ARVO_Client.md) (2 shared connections)
- [Tool Base Abstraction](Tool_Base_Abstraction.md) (2 shared connections)
- [Sandbox & Skill Loader](Sandbox_&_Skill_Loader.md) (1 shared connections)
- [Secrets Envelope](Secrets_Envelope.md) (1 shared connections)

## Source Files

- `REUNIAO_TECNICA_100_AUTONOMO_VALIDACAO_2026_09_13.md`
- `aios/api/whatsapp.py`
- `aios/core/pii.py`
- `aios/core/tracing.py`
- `aios/core/voice.py`
- `tests/test_voice.py`

## Audit Trail

- EXTRACTED: 86 (98%)
- INFERRED: 2 (2%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*