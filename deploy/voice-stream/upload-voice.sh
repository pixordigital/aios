#!/bin/sh
# Sobe voz referência PT-BR pro tts-server (XTTS exige upload).
# Coloca speakers/ptbr.wav (6-30s fala limpa) e roda este script no boot.
TTS="${TTS_HTTP_URL:-http://voice-tts-stream:8001}"
WAV="${1:-/speakers/ptbr.wav}"
[ -f "$WAV" ] || { echo "sem $WAV — XTTS usa default (qualidade menor)"; exit 0; }
until curl -sf "$TTS/v1/voices" >/dev/null 2>&1; do sleep 3; done
curl -sf -X POST "$TTS/v1/voices/upload" -F "voice_id=ptbr" -F "file=@$WAV" && echo "voz ptbr ok"
