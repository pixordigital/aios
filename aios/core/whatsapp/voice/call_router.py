import time, logging
from aios.core.voice import place_call
from .webrtc_handler import webrtc_create_session
logger = logging.getLogger(__name__)

async def route_inbound(from_number: str, instance: str) -> dict:
    sess = await webrtc_create_session()
    return {"ok": sess.get("ok"), "session": sess, "from": from_number, "instance": instance, "status": "ringing" if sess.get("ok") else "janus_unavailable", "ts": time.time()}

async def start_outbound(to: str, script: str, channel_config: dict | None = None) -> dict:
    # Reuso place_call que já faz TTS + bridge; aqui força WhatsApp+WebRTC path
    return await place_call(to, script, channel_config)
