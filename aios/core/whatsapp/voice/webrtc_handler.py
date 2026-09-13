import httpx, logging, uuid
from aios.core.whatsapp.config import settings
logger = logging.getLogger(__name__)

JANUS_URL = "http://janus:8088/janus"  # self-hosted Janus (deploy new)

async def webrtc_create_session() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(JANUS_URL, json={"janus":"create","transaction": uuid.uuid4().hex[:12]})
            j = r.json() if r.status_code==200 else {}
            sid = j.get("data",{}).get("id")
            return {"ok": bool(sid), "session_id": sid, "raw": j}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def webrtc_attach_plugin(session_id: int, plugin: str = "janus.plugin.videoroom") -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(f"{JANUS_URL}/{session_id}", json={"janus":"attach","plugin":plugin,"transaction": uuid.uuid4().hex[:12]})
            j = r.json() if r.status_code==200 else {}
            hid = j.get("data",{}).get("id")
            return {"ok": bool(hid), "handle_id": hid, "raw": j}
    except Exception as e:
        return {"ok": False, "error": str(e)}
