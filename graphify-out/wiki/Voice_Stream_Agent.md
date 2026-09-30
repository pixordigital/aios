# Voice Stream Agent

> 27 nodes · cohesion 0.11

## Key Concepts

- **voice-stream/agent.py** (19 connections) — `deploy/voice-stream/agent.py`
- **SimpleEnergyVAD** (10 connections) — `deploy/voice-stream/agent.py`
- **entrypoint()** (7 connections) — `deploy/voice-stream/agent.py`
- **get_local_vad()** (4 connections) — `deploy/voice-stream/agent.py`
- **interrupt_tts_playback()** (4 connections) — `deploy/voice-stream/agent.py`
- **.process_frame()** (4 connections) — `deploy/voice-stream/agent.py`
- **.rms()** (4 connections) — `deploy/voice-stream/agent.py`
- **_rms_normalized()** (3 connections) — `deploy/voice-stream/agent.py`
- **.should_interrupt()** (3 connections) — `deploy/voice-stream/agent.py`
- **_use_livekit_turn_detection()** (3 connections) — `deploy/voice-stream/agent.py`
- **build_llm()** (2 connections) — `deploy/voice-stream/agent.py`
- **build_stt()** (2 connections) — `deploy/voice-stream/agent.py`
- **build_tts()** (2 connections) — `deploy/voice-stream/agent.py`
- **fetch_agent_prompt()** (2 connections) — `deploy/voice-stream/agent.py`
- **.is_end_of_turn()** (2 connections) — `deploy/voice-stream/agent.py`
- **.is_speech()** (2 connections) — `deploy/voice-stream/agent.py`
- **Voice-stream worker — Kokoro primary, LiveKit optional. Pipeline: silero VAD ->…** (1 connections) — `deploy/voice-stream/agent.py`
- **Helper rápido p/ caller: deve interromper TTS?** (1 connections) — `deploy/voice-stream/agent.py`
- **Se LIVEKIT_URL configurado e livekit disponível, usa turn detection nativo.** (1 connections) — `deploy/voice-stream/agent.py`
- **Cancela playback TTS e reinicia STT. Seguro se VAD desabilitado.** (1 connections) — `deploy/voice-stream/agent.py`
- **RMS energia normalizada 0-1 para PCM 16-bit mono LE. Puro python, sem deps.** (1 connections) — `deploy/voice-stream/agent.py`
- **VAD simples energia RMS + silence detection 800ms + barge-in 120ms. Uso: vad =…** (1 connections) — `deploy/voice-stream/agent.py`
- **.__init__()** (1 connections) — `deploy/voice-stream/agent.py`
- **.reset()** (1 connections) — `deploy/voice-stream/agent.py`
- **livekit_agents** (1 connections)
- *... and 2 more nodes in this community*

## Relationships

- [Agent Runtime Loop](Agent_Runtime_Loop.md) (5 shared connections)
- [Voice Webhook Inbound](Voice_Webhook_Inbound.md) (1 shared connections)

## Source Files

- `deploy/voice-stream/agent.py`

## Audit Trail

- EXTRACTED: 45 (100%)
- INFERRED: 0 (0%)
- AMBIGUOUS: 0 (0%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*