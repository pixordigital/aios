#!/bin/sh
# tts-server + auto-upload voz PT-BR no boot (XTTS exige voz registrada).
ENGINE="${VOICE_TTS_ENGINE:-xtts}"
tts-server --engine "$ENGINE" --host 0.0.0.0 --port 8001 &
SRV=$!
/app/upload-voice.sh
wait $SRV
