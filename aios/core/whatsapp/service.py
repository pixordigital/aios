import logging
from .provider.factory import get_provider
from .provider.base import OutboundMessage
from .anti_ban.human_simulator import human_delay
from .anti_ban.ban_detector import risk_score

logger = logging.getLogger(__name__)

async def send_via_gateway(instance: str, to: str, text: str, provider: str = "baileys", risk: int = 0) -> dict:
    """Pipeline anti-ban enxuto: delay humano + provider send + ban check."""
    await human_delay(risk)
    p = get_provider(provider if provider in ("baileys","cloud") else "baileys")
    res = await p.send(instance, OutboundMessage(to=to, text=text))
    score = risk_score(connected=res.ok, fails_24h=0 if res.ok else 1, qr_regenerations=0, http_429=1 if res.status_code==429 else 0)
    return {"ok": res.ok, "message_id": res.message_id, "error": res.error, "status_code": res.status_code, "risk": score}
