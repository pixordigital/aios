# Voice Provider Options

> 16 nodes · cohesion 0.31

## Key Concepts

- **AIOS Deployment Topology (postgres, redis, otel, evolution, app, worker, voice)** (14 connections) — `docker-compose.coolify.yml`
- **FastAPI App Service (port 8777)** (11 connections) — `docker-compose.coolify.yml`
- **Evolution API v2.3.7 Service** (7 connections) — `docker-compose.coolify.yml`
- **Async Task Worker (aios.tasks.worker)** (7 connections) — `docker-compose.coolify.yml`
- **Whisper STT Service (CPU, large-v3 capable)** (6 connections) — `docker-compose.coolify.yml`
- **Voice Agent Service (voice-stream)** (5 connections) — `docker-compose.coolify.yml`
- **Kokoro TTS Service (CPU)** (5 connections) — `docker-compose.coolify.yml`
- **Coolify One-Click Compose Variant** (4 connections) — `docker-compose.coolify.one-click.yml`
- **OpenTelemetry Collector** (4 connections) — `docker-compose.coolify.yml`
- **Postgres (pgvector pg15)** (4 connections) — `docker-compose.coolify.yml`
- **Redis 7 Cache And Broker** (4 connections) — `docker-compose.coolify.yml`
- **Voice Channel Provider Options (selfhosted/elevenlabs/vapi/retell/livekit)** (3 connections) — `aios/dashboard/templates/channels.html`
- **Evolution IP Allowlist Hardening (C10)** (3 connections) — `docker-compose.coolify.yml`
- **LiteLLM Proxy Service (Removed)** (3 connections) — `docker-compose.coolify.yml`
- **Voice Channel (Kokoro TTS + Whisper STT)** (3 connections) — `website/index.html`
- **Compose Profiles (voice, voice-stt)** (2 connections) — `docker-compose.coolify.yml`

## Relationships

- [Control Center & Deal Desk](Control_Center_&_Deal_Desk.md) (4 shared connections)
- [Channel Dashboard & Test Endpoint](Channel_Dashboard_&_Test_Endpoint.md) (3 shared connections)
- [HITL Queue Panel +2](HITL_Queue_Panel_+2.md) (2 shared connections)
- [Dev Page (Claude + Codex) +2](Dev_Page_Claude_+_Codex_+2.md) (1 shared connections)
- [Evolution Gateway Wrapper](Evolution_Gateway_Wrapper.md) (1 shared connections)

## Source Files

- `aios/dashboard/templates/channels.html`
- `docker-compose.coolify.one-click.yml`
- `docker-compose.coolify.yml`
- `website/index.html`

## Audit Trail

- EXTRACTED: 30 (62%)
- INFERRED: 14 (29%)
- AMBIGUOUS: 4 (8%)

---

*Part of the graphify knowledge wiki. See [index](index.md) to navigate.*