# Voice Smoke Test — self-hosted

Voice usa Kokoro TTS auto-hospedado. Não há mais transporte de streaming
(LiveKit foi removido do codebase), então não existe mais `livekit-server`
para subir nem `LIVEKIT_*` para configurar.

## Smoke

```bash
# core
docker compose -f docker-compose.coolify.yml config --services # 5: app worker worker2 postgres redis
curl -s http://localhost:8777/health | jq .rag

# voice (quando precisar)
docker compose -f docker-compose.coolify.yml --profile voice config --services
docker compose --profile voice up -d
curl -s http://localhost:8880/health || echo "kokoro not ready"
curl -s http://localhost:8880/v1/models | jq -r '.data[].id' | head
```

O serviço Kokoro publica `8880` direto (é o único serviço de voz com porta
exposta). Do host, se o container não publicar a porta, use o forwarder
loopback-only: `scripts/kokoro-host-forward.sh`.

## Coolify

- Deploy padrão: 5 serviços, sem voice. Ativar voice: Coolify → Service → General → Custom Docker Compose → add `--profile voice` ao `docker compose up`.
- O perfil `voice` sobe apenas `voice-tts-kokoro`. O antigo `voice-agent` (worker LiveKit) foi removido.
- `voice-stt` continua separado e opcional (Whisper STT).

## CI

`voice` excluído do `docker compose build` padrão.
