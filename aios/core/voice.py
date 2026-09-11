"""Voice provider layer — ElevenLabs (cloud) ou self-hosted (Coolify).

Self-hosted = endpoints OpenAI-compatible:
- TTS: openedai-speech (POST /v1/audio/speech)
- STT: whisper-asr-webservice (POST /v1/audio/transcriptions, fallback /asr)

PSTN/SIP discagem via bridge HTTP genérico (Twilio/LiveKit SIP/Asterisk).
Sem bridge configurado, chamada fica `queued` com áudio TTS pronto.
"""

import base64
import logging
import time

import httpx

from aios.config import settings
from aios.core.tracing import emit_usage_event

try:
    from aios.core.pii import redact_pii as _redact_pii
except Exception:  # pragma: no cover
    def _redact_pii(x):  # type: ignore
        return x

logger = logging.getLogger(__name__)


def voice_config(channel_config: dict | None = None) -> dict:
    c = dict(channel_config or {})
    return {
        "provider": c.get("provider") or settings.voice_provider,
        "elevenlabs_api_key": c.get("elevenlabs_api_key") or settings.elevenlabs_api_key,
        "elevenlabs_voice_id": c.get("elevenlabs_voice_id") or settings.elevenlabs_voice_id,
        "vapi_api_key": c.get("vapi_api_key") or settings.vapi_api_key,
        "vapi_assistant_id": c.get("vapi_assistant_id") or settings.vapi_assistant_id,
        "vapi_phone_number_id": c.get("vapi_phone_number_id") or settings.vapi_phone_number_id,
        "retell_api_key": c.get("retell_api_key") or settings.retell_api_key,
        "retell_agent_id": c.get("retell_agent_id") or settings.retell_agent_id,
        "tts_url": (c.get("tts_url") or settings.voice_tts_url or "").rstrip("/"),
        "stt_url": (c.get("stt_url") or settings.voice_stt_url or "").rstrip("/"),
        "bridge_url": (c.get("bridge_url") or settings.voice_bridge_url or "").rstrip("/"),
        "from_number": c.get("from_number") or settings.voice_from_number,
    }


async def synthesize(text: str, channel_config: dict | None = None, voice: str = "") -> dict:
    """Gera áudio TTS. Retorna {ok, audio_base64, mime, provider}."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "texto vazio"}
    cfg = voice_config(channel_config)
    if cfg["provider"] == "elevenlabs":
        return await _elevenlabs_tts(text, cfg, voice)
    # vapi/retell são plataformas de chamada, sem endpoint TTS avulso:
    # usa TTS self-hosted/OpenAI como fallback para preview e áudio WhatsApp
    return await _openai_compat_tts(text, cfg, voice)


async def _elevenlabs_tts(text: str, cfg: dict, voice: str = "") -> dict:
    key = cfg["elevenlabs_api_key"]
    if not key:
        return {"ok": False, "error": "sem elevenlabs api key"}
    voice_id = voice or cfg["elevenlabs_voice_id"]
    if not voice_id:
        return {"ok": False, "error": "sem voice_id"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                json={"text": text[:5000], "model_id": "eleven_multilingual_v2"},
            )
            if r.status_code == 200 and r.content:
                return {"ok": True, "audio_base64": base64.b64encode(r.content).decode(), "mime": "audio/mpeg", "provider": "elevenlabs", "bytes": len(r.content)}
            return {"ok": False, "error": r.text[:300], "status": r.status_code}
    except Exception as e:
        logger.exception("elevenlabs tts failed")
        return {"ok": False, "error": str(e)}


async def _openai_compat_tts(text: str, cfg: dict, voice: str = "") -> dict:
    base = cfg["tts_url"]
    if not base:
        return {"ok": False, "error": "sem tts_url self-hosted (VOICE_TTS_URL)"}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(
                f"{base}/v1/audio/speech",
                json={"model": "tts-1", "voice": voice or "af_sky", "input": text[:4000], "response_format": "mp3"},
            )
            if r.status_code == 200 and r.content:
                return {"ok": True, "audio_base64": base64.b64encode(r.content).decode(), "mime": "audio/mpeg", "provider": "selfhosted", "bytes": len(r.content)}
            return {"ok": False, "error": r.text[:300], "status": r.status_code}
    except Exception as e:
        logger.exception("selfhosted tts failed")
        return {"ok": False, "error": str(e)}


async def transcribe_audio(audio: bytes, channel_config: dict | None = None, language: str = "pt") -> dict:
    """STT via whisper self-hosted (ou OpenAI fallback)."""
    cfg = voice_config(channel_config)
    base = cfg["stt_url"]
    key = settings.openai_api_key or settings.openrouter_api_key
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            if base:
                files = {"file": ("audio.mp3", audio, "audio/mpeg"), "model": (None, "whisper-1"), "language": (None, language)}
                r = await client.post(f"{base}/v1/audio/transcriptions", files=files)
                if r.status_code == 404:
                    r = await client.post(f"{base}/asr?language={language}&output=json", files={"audio_file": ("audio.mp3", audio, "audio/mpeg")})
                if r.status_code == 200:
                    j = r.json() if "json" in r.headers.get("content-type", "") else {"text": r.text}
                    _text = j.get("text", "") if isinstance(j, dict) else str(j)
                    try:
                        logger.info("stt ok provider=selfhosted text=%s", _redact_pii(_text))
                    except Exception:
                        pass
                    return {"ok": True, "text": _text, "provider": "selfhosted"}
                return {"ok": False, "error": r.text[:300], "status": r.status_code}
            if not key:
                return {"ok": False, "error": "sem stt_url nem openai key"}
            files = {"file": ("audio.mp3", audio, "audio/mpeg"), "model": (None, "whisper-1"), "language": (None, language)}
            r = await client.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": f"Bearer {key}"}, files=files)
            if r.status_code == 200:
                _text2 = r.json().get("text", "")
                try:
                    logger.info("stt ok provider=openai text=%s", _redact_pii(_text2))
                except Exception:
                    pass
                return {"ok": True, "text": _text2, "provider": "openai"}
            return {"ok": False, "error": r.text[:300], "status": r.status_code}
    except Exception as e:
        logger.exception("stt failed")
        return {"ok": False, "error": str(e)}


async def place_call(to: str, script: str, channel_config: dict | None = None, extra: dict | None = None) -> dict:
    """Dispara chamada outbound. Sem bridge → queued com TTS pronto.
    
    Emits voice_minutes_used event on successful dialing for metered billing.
    """
    to = (to or "").strip()
    if not to:
        return {"ok": False, "error": "destino vazio"}
    cfg = voice_config(channel_config)
    tts = await synthesize(script or "Olá! Aqui é o assistente. Posso falar agora?", channel_config)
    call = {
        "ok": True,
        "status": "queued",
        "to": to,
        "from": cfg["from_number"],
        "provider": cfg["provider"],
        "created_at": time.time(),
        "tts_ready": bool(tts.get("ok")),
        "extra": extra or {},
    }
    if tts.get("ok"):
        call["audio_bytes"] = tts.get("bytes", 0)
    if cfg["provider"] == "vapi" and cfg["vapi_api_key"] and cfg["vapi_assistant_id"]:
        return await _vapi_call(call, to, script, cfg, extra)
    if cfg["provider"] == "retell" and cfg["retell_api_key"] and cfg["retell_agent_id"]:
        return await _retell_call(call, to, script, cfg, extra)
    bridge = cfg["bridge_url"]
    if not bridge:
        if cfg["provider"] == "livekit" and settings.livekit_url:
            call["hint"] = "realtime via POST /api/voice/room (browser entra na sala); PSTN precisa SIP trunk no LiveKit"
        else:
            call["hint"] = "sem bridge SIP configurado — use VOICE_BRIDGE_URL (Twilio/LiveKit/Asterisk)"
        return call
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{bridge}/calls", json={"to": to, "from": cfg["from_number"], "script": script, "extra": extra or {}})
            if r.status_code in (200, 201, 202):
                call["status"] = "dialing"
                call["bridge_response"] = r.text[:300]
                # Emit usage event for metered billing (estimated 1 min for dialing)
                org_id = extra.get("conversation_id", "").split("_")[0] if extra and extra.get("conversation_id") else "unknown"
                await emit_usage_event(
                    event="voice_minutes_used",
                    org_id=org_id,
                    quantity=1.0,
                    unit="minutes",
                    agent_id=extra.get("agent_id") if extra else None,
                    team_id=extra.get("team_id") if extra else None,
                    conversation_id=extra.get("conversation_id") if extra else None,
                    metadata={"to": to, "provider": cfg["provider"], "bridge": "generic"},
                )
            else:
                call["status"] = "bridge_error"
                call["bridge_response"] = r.text[:300]
    except Exception as e:
        call["status"] = "bridge_error"
        call["bridge_response"] = str(e)[:300]
    return call


async def _vapi_call(call: dict, to: str, script: str, cfg: dict, extra: dict | None) -> dict:
    """Outbound via Vapi: POST /call {assistantId, customer, phoneNumberId}."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            payload: dict = {
                "assistantId": cfg["vapi_assistant_id"],
                "customer": {"number": to},
            }
            if cfg["vapi_phone_number_id"]:
                payload["phoneNumberId"] = cfg["vapi_phone_number_id"]
            elif cfg["from_number"]:
                payload["customer"]["number"] = to
                payload["phoneNumber"] = {"number": cfg["from_number"]}
            if script:
                payload["assistantOverrides"] = {"firstMessage": script[:1000]}
            r = await client.post("https://api.vapi.ai/call", headers={"Authorization": f"Bearer {cfg['vapi_api_key']}", "Content-Type": "application/json"}, json=payload)
            if r.status_code in (200, 201):
                call["status"] = "dialing"
                try:
                    call["bridge_response"] = r.json().get("id", r.text[:300])
                except Exception:
                    call["bridge_response"] = r.text[:300]
                # Emit usage event for metered billing (Vapi bills per minute)
                org_id = extra.get("conversation_id", "").split("_")[0] if extra and extra.get("conversation_id") else "unknown"
                await emit_usage_event(
                    event="voice_minutes_used",
                    org_id=org_id,
                    quantity=1.0,
                    unit="minutes",
                    agent_id=extra.get("agent_id") if extra else None,
                    team_id=extra.get("team_id") if extra else None,
                    conversation_id=extra.get("conversation_id") if extra else None,
                    metadata={"to": to, "provider": "vapi", "call_id": call.get("bridge_response")},
                )
            else:
                call["status"] = "bridge_error"
                call["bridge_response"] = r.text[:300]
    except Exception as e:
        call["status"] = "bridge_error"
        call["bridge_response"] = str(e)[:300]
    return call


async def _retell_call(call: dict, to: str, script: str, cfg: dict, extra: dict | None) -> dict:
    """Outbound via Retell: POST /v2/create-phone-call {from_number, to_number, override_agent_id}."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            payload: dict = {
                "from_number": cfg["from_number"],
                "to_number": to,
                "override_agent_id": cfg["retell_agent_id"],
            }
            if script:
                payload["retell_llm_dynamic_variables"] = {"opening": script[:1000]}
            r = await client.post("https://api.retellai.com/v2/create-phone-call", headers={"Authorization": f"Bearer {cfg['retell_api_key']}", "Content-Type": "application/json"}, json=payload)
            if r.status_code in (200, 201):
                call["status"] = "dialing"
                try:
                    call["bridge_response"] = r.json().get("call_id", r.text[:300])
                except Exception:
                    call["bridge_response"] = r.text[:300]
                # Emit usage event for metered billing (Retell bills per minute)
                org_id = extra.get("conversation_id", "").split("_")[0] if extra and extra.get("conversation_id") else "unknown"
                await emit_usage_event(
                    event="voice_minutes_used",
                    org_id=org_id,
                    quantity=1.0,
                    unit="minutes",
                    agent_id=extra.get("agent_id") if extra else None,
                    team_id=extra.get("team_id") if extra else None,
                    conversation_id=extra.get("conversation_id") if extra else None,
                    metadata={"to": to, "provider": "retell", "call_id": call.get("bridge_response")},
                )
            else:
                call["status"] = "bridge_error"
                call["bridge_response"] = r.text[:300]
    except Exception as e:
        call["status"] = "bridge_error"
        call["bridge_response"] = str(e)[:300]
    return call
