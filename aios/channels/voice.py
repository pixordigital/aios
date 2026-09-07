"""Voice channel — TTS + chamadas atreladas ao agente (SDR/support).

send() com extra_data:
- voice_action=say (default): gera TTS do texto, retorna audio ref
- voice_action=call: dispara chamada para extra.to com script=texto
Inbound via aios/api/voice.py webhook → agente responde → TTS.
"""

import logging

from aios.channels.base import Channel, OutboundMessage

logger = logging.getLogger(__name__)


class VoiceChannel(Channel):
    channel_type = "voice"

    def __init__(self, connection=None, agent_or_team=None, db=None):
        self.connection = connection
        self.agent_or_team = agent_or_team
        self.db = db
        self._config = connection.config if connection and connection.config else {}

    async def send(self, message: OutboundMessage) -> str | None:
        from aios.core.voice import place_call, synthesize

        extra = message.extra_data or {}
        action = extra.get("voice_action") or "say"
        try:
            if action == "call":
                to = extra.get("to") or extra.get("from_number") or ""
                if not to:
                    logger.warning("Voice call sem destino")
                    return None
                res = await place_call(to, message.text, self._config, {"conversation_id": message.conversation_id})
                if res.get("ok"):
                    return f"{res.get('status')}:{to}"
                logger.warning("Voice call falhou: %s", res.get("error"))
                return None
            res = await synthesize(message.text, self._config, extra.get("voice") or "")
            if res.get("ok"):
                return f"tts:{res.get('provider')}:{res.get('bytes', 0)}b"
            logger.warning("Voice TTS falhou: %s", res.get("error"))
            return None
        except Exception:
            logger.exception("Voice send error")
            return None

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def test(self) -> dict:
        from aios.core.voice import voice_config

        cfg = voice_config(self._config)
        if cfg["provider"] == "elevenlabs":
            if not cfg["elevenlabs_api_key"]:
                return {"ok": False, "message": "Missing elevenlabs api key"}
            try:
                import httpx

                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": cfg["elevenlabs_api_key"]})
                    if r.status_code == 200:
                        sub = r.json().get("subscription", {})
                        return {"ok": True, "message": f"ElevenLabs ok — {sub.get('tier', '?')} ({sub.get('character_count', 0)}/{sub.get('character_limit', 0)} chars)"}
                    return {"ok": False, "message": f"ElevenLabs {r.status_code}: {r.text[:120]}"}
            except Exception as e:
                return {"ok": False, "message": str(e)}
        if cfg["provider"] == "vapi":
            if not cfg["vapi_api_key"]:
                return {"ok": False, "message": "Missing vapi api key"}
            try:
                import httpx

                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get("https://api.vapi.ai/assistant?limit=1", headers={"Authorization": f"Bearer {cfg['vapi_api_key']}"})
                    if r.status_code == 200:
                        msg = "Vapi ok"
                        msg += " + assistant configurado" if cfg["vapi_assistant_id"] else " (sem assistantId — outbound indisponível)"
                        return {"ok": True, "message": msg}
                    return {"ok": False, "message": f"Vapi {r.status_code}: {r.text[:120]}"}
            except Exception as e:
                return {"ok": False, "message": str(e)}
        if cfg["provider"] == "retell":
            if not cfg["retell_api_key"]:
                return {"ok": False, "message": "Missing retell api key"}
            try:
                import httpx

                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.get("https://api.retellai.com/list-agents", headers={"Authorization": f"Bearer {cfg['retell_api_key']}"})
                    if r.status_code == 200:
                        msg = "Retell ok"
                        msg += " + agent configurado" if cfg["retell_agent_id"] else " (sem agentId — outbound indisponível)"
                        return {"ok": True, "message": msg}
                    return {"ok": False, "message": f"Retell {r.status_code}: {r.text[:120]}"}
            except Exception as e:
                return {"ok": False, "message": str(e)}
        if cfg["provider"] == "livekit":
            from aios.config import settings as _s
            if not _s.livekit_url:
                return {"ok": False, "message": "Missing LIVEKIT_URL (suba serviço livekit no Coolify)"}
            try:
                import socket as _sock
                from urllib.parse import urlparse as _up
                host = _up(_s.livekit_url.replace("wss://", "https://").replace("ws://", "http://")).hostname
                port = _up(_s.livekit_url.replace("wss://", "https://").replace("ws://", "http://")).port or 7880
                with _sock.create_connection((host, port), timeout=5):
                    pass
                return {"ok": True, "message": f"LiveKit ok ({_s.livekit_tts_engine} primário, kokoro fallback)"}
            except Exception as e:
                return {"ok": False, "message": f"LiveKit inalcançável: {e}"}
        if not cfg["tts_url"]:
            return {"ok": False, "message": "Missing tts_url (VOICE_TTS_URL, ex. http://voice-tts:8000)"}
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                for path in ("/health", "/docs", "/v1/models"):
                    try:
                        r = await client.get(f"{cfg['tts_url']}{path}")
                        if r.status_code < 500:
                            msg = f"TTS self-hosted ok ({path})"
                            if cfg["bridge_url"]:
                                msg += " + bridge SIP configurado"
                            elif cfg["stt_url"]:
                                msg += " + STT configurado"
                            else:
                                msg += " (sem bridge SIP — chamadas ficam queued)"
                            return {"ok": True, "message": msg}
                    except Exception:
                        continue
                return {"ok": False, "message": f"TTS inalcançável em {cfg['tts_url']}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}
