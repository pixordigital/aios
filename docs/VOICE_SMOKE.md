# Voice Smoke Test — self-hosted

Sem `--profile voice`, core não builda voice-tts-stream (evita `livekit-streaming-tts[xtts]==0.1.1` fail).

## Smoke

```bash
# core
docker compose -f docker-compose.coolify.yml config --services # 5: app worker worker2 postgres redis
curl -s http://localhost:8777/health | jq .rag

# voice (quando precisar)
docker compose -f docker-compose.coolify.yml --profile voice config --services # 13
docker compose --profile voice up -d --build
curl -s http://localhost:8001/v1/voices || echo "tts not ready"
curl -s http://localhost:7880/ || echo "livekit not ready"
```

## Coolify

- Deploy padrão: 5 serviços, sem voice. Ativar voice: Coolify → Service → General → Custom Docker Compose → add `--profile voice` ao `docker compose up` ou criar serviço separado `voice-stack` com `docker-compose.voice.yml`.
- `AIOS_LIVEKIT_API_SECRET` deve ser `openssl rand -hex 32`, não `change-me`.

## CI

`voice` excluído de `mypy --exclude` e de `docker compose build` padrão.
